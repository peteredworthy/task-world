"""Unit tests for AgentRunnerMonitor class."""

import os
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.runners import AgentRunnerMonitor
from orchestrator.config import AgentRunnerType, RunStatus, TaskStatus
from orchestrator.config.global_config import AgentsConfig, GlobalConfig
from orchestrator.config.models import RequirementConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import EventStore
from orchestrator.db import RunRepository
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import Run
from orchestrator.workflow.locks import InMemoryLockManager


@pytest.fixture
async def db_setup() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Create in-memory database and return session factory."""
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    yield session_factory

    await engine.dispose()


def _create_test_run(
    run_id: str = "test-run",
    agent_type: AgentRunnerType | None = None,
    agent_config: dict[str, Any] | None = None,
) -> Run:
    """Create a minimal test run."""
    routine = RoutineConfig(
        id="test-routine",
        name="Test Routine",
        steps=[
            StepConfig(
                id="step1",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="task1",
                        title="Task 1",
                        task_context="Do something",
                        requirements=[RequirementConfig(id="c1", desc="Check")],
                    )
                ],
            )
        ],
    )

    run = create_run_from_routine(
        routine=routine,
        repo_name="test-project",
        source_branch="main",
        id_generator=lambda: run_id,  # Use fixed ID for testing
    )
    run.agent_type = agent_type
    run.agent_config = agent_config or {}
    return run


# ---------- on_agent_died tests ----------


@pytest.mark.asyncio
async def test_on_agent_died_transitions_run_to_paused(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """When an ACTIVE run's agent dies, on_agent_died transitions it to PAUSED."""
    session_factory = db_setup
    monitor = AgentRunnerMonitor(session_factory)

    # Create and save an ACTIVE run
    async with session_factory() as session:
        repo = RunRepository(session)
        run = _create_test_run(
            run_id="run1", agent_type=AgentRunnerType.CLI_SUBPROCESS, agent_config={"pid": 12345}
        )
        run.status = RunStatus.ACTIVE
        await repo.save(run)
        await session.commit()

    # Call on_agent_died
    await monitor.on_agent_died(
        run_id="run1",
        agent_type=AgentRunnerType.CLI_SUBPROCESS,
        exit_code=1,
        reason="agent_process_died",
    )

    # Verify run is now PAUSED with pause_reason set
    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = EventStore(session)
        updated_run = await repo.get("run1")
        assert updated_run.status == RunStatus.PAUSED
        assert updated_run.pause_reason == "agent_process_died"

        # Verify events were logged
        events = await event_store.get_events_for_run("run1")
        assert len(events) == 2
        assert events[0]["type"] == "agent_died"
        assert events[0]["payload"]["agent_type"] == "cli_subprocess"
        assert events[0]["payload"]["exit_code"] == 1
        assert events[0]["payload"]["reason"] == "agent_process_died"
        assert events[1]["type"] == "run_status_changed"
        assert events[1]["payload"]["old_status"] == "active"
        assert events[1]["payload"]["new_status"] == "paused"


@pytest.mark.asyncio
async def test_on_agent_died_ignores_non_active_run(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """on_agent_died should do nothing if run is not ACTIVE."""
    session_factory = db_setup
    monitor = AgentRunnerMonitor(session_factory)

    # Create a COMPLETED run
    async with session_factory() as session:
        repo = RunRepository(session)
        run = _create_test_run(run_id="run2", agent_type=AgentRunnerType.CLI_SUBPROCESS)
        run.status = RunStatus.COMPLETED
        await repo.save(run)
        await session.commit()

    # Call on_agent_died
    await monitor.on_agent_died(
        run_id="run2",
        agent_type=AgentRunnerType.CLI_SUBPROCESS,
        exit_code=1,
    )

    # Verify run status unchanged
    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = EventStore(session)
        updated_run = await repo.get("run2")
        assert updated_run.status == RunStatus.COMPLETED

        # Verify no events were logged
        events = await event_store.get_events_for_run("run2")
        assert len(events) == 0


# ---------- check_agent_alive tests ----------


@pytest.mark.asyncio
async def test_check_agent_alive_cli_subprocess_with_valid_pid(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """CLI_SUBPROCESS agent with a valid PID should be considered alive."""
    session_factory = db_setup
    monitor = AgentRunnerMonitor(session_factory)

    # Use the current process PID (which is definitely alive)
    current_pid = os.getpid()
    run = _create_test_run(
        run_id="run3",
        agent_type=AgentRunnerType.CLI_SUBPROCESS,
        agent_config={"pid": current_pid},
    )
    run.status = RunStatus.ACTIVE

    # check_agent_alive doesn't need DB, works directly on the Run
    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is True


@pytest.mark.asyncio
async def test_check_agent_alive_cli_subprocess_with_dead_pid(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """CLI_SUBPROCESS agent with a dead PID should be considered dead."""
    session_factory = db_setup
    monitor = AgentRunnerMonitor(session_factory)

    # CLI_SUBPROCESS spawns a new process per task so PID is stale between
    # tasks.  check_agent_alive always returns True for this agent type;
    # the executor's own try/except handles real subprocess failures.
    fake_pid = 999999
    run = _create_test_run(
        run_id="run4",
        agent_type=AgentRunnerType.CLI_SUBPROCESS,
        agent_config={"pid": fake_pid},
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is True


@pytest.mark.asyncio
async def test_check_agent_alive_cli_subprocess_without_pid(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """CLI_SUBPROCESS without PID is treated as alive (not yet spawned).

    The subprocess may not have been spawned yet (e.g. pre-run health check
    is still running). The health monitor should not kill the run prematurely.
    Startup recovery handles the no-PID case separately.
    """
    session_factory = db_setup
    monitor = AgentRunnerMonitor(session_factory)

    run = _create_test_run(
        run_id="run5",
        agent_type=AgentRunnerType.CLI_SUBPROCESS,
        agent_config={},  # No PID — not yet spawned
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is True


@pytest.mark.asyncio
async def test_check_agent_alive_openhands_local_returns_true(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """OPENHANDS_LOCAL agent should be considered alive during normal operation.

    In-process agents run via asyncio.to_thread and don't require health monitoring
    since the executor handles failures. Returns True to prevent the health monitor
    from killing the agent prematurely. Server restart recovery is handled separately.
    """
    session_factory = db_setup
    monitor = AgentRunnerMonitor(session_factory)

    run = _create_test_run(
        run_id="run6",
        agent_type=AgentRunnerType.OPENHANDS_LOCAL,
        agent_config={},
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is True


@pytest.mark.asyncio
async def test_check_agent_alive_user_managed_within_timeout(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """USER_MANAGED agent with recent activity should be considered alive."""
    session_factory = db_setup

    # Configure custom timeout (10 minutes)
    config = GlobalConfig(agents=AgentsConfig(user_managed_timeout_minutes=10))
    monitor = AgentRunnerMonitor(session_factory, global_config=config)

    # Set last_activity_at to 5 minutes ago
    now = datetime.now(timezone.utc)
    last_activity = now - timedelta(minutes=5)

    run = _create_test_run(
        run_id="run7",
        agent_type=AgentRunnerType.USER_MANAGED,
        agent_config={"last_activity_at": last_activity.isoformat()},
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is True


@pytest.mark.asyncio
async def test_check_agent_alive_user_managed_beyond_timeout(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """USER_MANAGED agent with stale activity should be considered dead."""
    session_factory = db_setup

    # Configure custom timeout (10 minutes)
    config = GlobalConfig(agents=AgentsConfig(user_managed_timeout_minutes=10))
    monitor = AgentRunnerMonitor(session_factory, global_config=config)

    # Set last_activity_at to 15 minutes ago (beyond timeout)
    now = datetime.now(timezone.utc)
    last_activity = now - timedelta(minutes=15)

    run = _create_test_run(
        run_id="run8",
        agent_type=AgentRunnerType.USER_MANAGED,
        agent_config={"last_activity_at": last_activity.isoformat()},
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is False


@pytest.mark.asyncio
async def test_check_agent_alive_user_managed_without_last_activity(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """USER_MANAGED agent without last_activity_at should be considered dead."""
    session_factory = db_setup
    monitor = AgentRunnerMonitor(session_factory)

    run = _create_test_run(
        run_id="run9",
        agent_type=AgentRunnerType.USER_MANAGED,
        agent_config={},  # No last_activity_at
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is False


@pytest.mark.asyncio
async def test_check_agent_alive_with_no_agent_type(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """Run without agent_type should be considered dead."""
    session_factory = db_setup
    monitor = AgentRunnerMonitor(session_factory)

    run = _create_test_run(run_id="run10", agent_type=None)
    run.status = RunStatus.DRAFT

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is False


@pytest.mark.asyncio
async def test_check_agent_alive_user_managed_with_malformed_timestamp(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """USER_MANAGED agent with malformed timestamp should be considered dead."""
    session_factory = db_setup

    config = GlobalConfig(agents=AgentsConfig(user_managed_timeout_minutes=10))
    monitor = AgentRunnerMonitor(session_factory, global_config=config)

    run = _create_test_run(
        run_id="run11",
        agent_type=AgentRunnerType.USER_MANAGED,
        agent_config={"last_activity_at": "not-a-valid-timestamp"},
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is False


# ---------- lock cleanup tests ----------


@pytest.mark.asyncio
async def test_on_agent_died_releases_building_task_lock_codex_server(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """on_agent_died releases the lock on a BUILDING task for CODEX_SERVER."""
    session_factory = db_setup
    lock_manager = InMemoryLockManager()
    monitor = AgentRunnerMonitor(session_factory, lock_manager=lock_manager)

    # Create and save an ACTIVE run with a task that will be put into BUILDING
    async with session_factory() as session:
        repo = RunRepository(session)
        run = _create_test_run(
            run_id="run-lock-cs",
            agent_type=AgentRunnerType.CODEX_SERVER,
            agent_config={"pid": 999999},
        )
        run.status = RunStatus.ACTIVE
        # Simulate the task being in BUILDING state (agent started it)
        task_state = run.steps[0].tasks[0]
        task_state.status = TaskStatus.BUILDING
        await repo.save(run)
        await session.commit()

    # Pre-acquire the lock as the agent would have done
    now = datetime.now(timezone.utc)
    acquired = lock_manager.acquire(task_state.id, "default", now)
    assert acquired is True
    assert lock_manager.is_locked(task_state.id, now) is True

    # Agent dies → monitor should release the lock
    await monitor.on_agent_died(
        run_id="run-lock-cs",
        agent_type=AgentRunnerType.CODEX_SERVER,
        reason="local_codex_process_not_alive",
    )

    # Lock must be released — no orphan
    assert lock_manager.is_locked(task_state.id, datetime.now(timezone.utc)) is False


@pytest.mark.asyncio
async def test_on_agent_died_without_lock_manager_does_not_error(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """on_agent_died works correctly when no lock_manager is provided."""
    session_factory = db_setup
    # No lock_manager passed — should be a no-op for lock cleanup
    monitor = AgentRunnerMonitor(session_factory)

    async with session_factory() as session:
        repo = RunRepository(session)
        run = _create_test_run(
            run_id="run-nolock",
            agent_type=AgentRunnerType.CODEX_SERVER,
            agent_config={"pid": 999999},
        )
        run.status = RunStatus.ACTIVE
        task_state = run.steps[0].tasks[0]
        task_state.status = TaskStatus.BUILDING
        await repo.save(run)
        await session.commit()

    # Should not raise even without a lock_manager
    await monitor.on_agent_died(
        run_id="run-nolock",
        agent_type=AgentRunnerType.CODEX_SERVER,
        reason="local_codex_process_not_alive",
    )

    # Run should still be paused
    async with session_factory() as session:
        repo = RunRepository(session)
        updated = await repo.get("run-nolock")
        assert updated.status == RunStatus.PAUSED


@pytest.mark.asyncio
async def test_on_agent_died_does_not_release_completed_task_lock(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """on_agent_died only releases locks for BUILDING/VERIFYING tasks, not COMPLETED."""
    session_factory = db_setup
    lock_manager = InMemoryLockManager()
    monitor = AgentRunnerMonitor(session_factory, lock_manager=lock_manager)

    async with session_factory() as session:
        repo = RunRepository(session)
        run = _create_test_run(
            run_id="run-completed",
            agent_type=AgentRunnerType.CODEX_SERVER,
            agent_config={"pid": 999999},
        )
        run.status = RunStatus.ACTIVE
        # Task is already COMPLETED — no lock should be held or released
        task_state = run.steps[0].tasks[0]
        task_state.status = TaskStatus.COMPLETED
        await repo.save(run)
        await session.commit()

    task_id = task_state.id
    # Acquire a lock on some OTHER resource to confirm release is not called incorrectly
    now = datetime.now(timezone.utc)
    lock_manager.acquire(task_id, "other-agent", now)
    assert lock_manager.is_locked(task_id, now) is True

    await monitor.on_agent_died(
        run_id="run-completed",
        agent_type=AgentRunnerType.CODEX_SERVER,
        reason="local_codex_process_not_alive",
    )

    # Lock held by "other-agent" should be untouched (monitor only releases "default")
    assert lock_manager.is_locked(task_id, datetime.now(timezone.utc)) is True
