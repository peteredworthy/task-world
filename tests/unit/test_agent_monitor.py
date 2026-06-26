"""Unit tests for AgentRunnerMonitor class."""

import json
import os
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.runners import AgentRunnerMonitor
from orchestrator.config import AgentRunnerType, RunStatus, TaskStatus
from orchestrator.config.models import RequirementConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import RunRepository
from orchestrator.db import SqliteEventStore
from orchestrator.db.access.mutations import save_run
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
    agent_runner_type: AgentRunnerType | None = None,
    agent_runner_config: dict[str, Any] | None = None,
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
    run.agent_runner_type = agent_runner_type
    run.agent_runner_config = agent_runner_config or {}
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
            run_id="run1",
            agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
            agent_runner_config={"pid": 12345},
        )
        run.status = RunStatus.ACTIVE
        await save_run(repo.session, run)
        await session.commit()

    # Call on_agent_died
    await monitor.on_agent_died(
        run_id="run1",
        agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
        exit_code=1,
        reason="agent_process_died",
    )

    # Verify run is now PAUSED with pause_reason set
    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = SqliteEventStore(session)
        updated_run = await repo.get("run1")
        assert updated_run.status == RunStatus.PAUSED
        assert updated_run.pause_reason == "agent_process_died"

        # Verify events were logged
        events = await event_store.get_stream("run1")
        assert len(events) == 2
        assert events[0].event_type == "agent_died"
        agent_died_payload = json.loads(events[0].payload)
        assert agent_died_payload["agent_runner_type"] == "cli_subprocess"
        assert agent_died_payload["exit_code"] == 1
        assert agent_died_payload["reason"] == "agent_process_died"
        assert events[1].event_type == "run_status_changed"
        status_payload = json.loads(events[1].payload)
        assert status_payload["old_status"] == "active"
        assert status_payload["new_status"] == "paused"
        assert status_payload["pause_reason"] == "agent_process_died"


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
        run = _create_test_run(run_id="run2", agent_runner_type=AgentRunnerType.CLI_SUBPROCESS)
        run.status = RunStatus.COMPLETED
        await save_run(repo.session, run)
        await session.commit()

    # Call on_agent_died
    await monitor.on_agent_died(
        run_id="run2",
        agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
        exit_code=1,
    )

    # Verify run status unchanged
    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = SqliteEventStore(session)
        updated_run = await repo.get("run2")
        assert updated_run.status == RunStatus.COMPLETED

        # Verify no events were logged
        events = await event_store.get_stream("run2")
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
        agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
        agent_runner_config={"pid": current_pid},
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
    # tasks.  check_agent_alive always returns True for this agent runner type;
    # the executor's own try/except handles real subprocess failures.
    fake_pid = 999999
    run = _create_test_run(
        run_id="run4",
        agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
        agent_runner_config={"pid": fake_pid},
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
        agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
        agent_runner_config={},  # No PID — not yet spawned
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
        agent_runner_type=AgentRunnerType.OPENHANDS_LOCAL,
        agent_runner_config={},
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is True


@pytest.mark.asyncio
async def test_check_agent_alive_with_no_agent_runner_type(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """Run without agent_runner_type should be considered dead."""
    session_factory = db_setup
    monitor = AgentRunnerMonitor(session_factory)

    run = _create_test_run(run_id="run10", agent_runner_type=None)
    run.status = RunStatus.DRAFT

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is False


# ---------- startup recovery tests ----------


@pytest.mark.asyncio
async def test_recover_active_runs_on_startup_batches_dead_managed_runs(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """Startup recovery pauses orphaned managed runs without per-run reloads."""
    session_factory = db_setup
    monitor = AgentRunnerMonitor(session_factory)

    async with session_factory() as session:
        repo = RunRepository(session)
        for run_id in ("run-startup-a", "run-startup-b"):
            run = _create_test_run(
                run_id=run_id,
                agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
                agent_runner_config={"pid": 12345},
            )
            run.status = RunStatus.ACTIVE
            await save_run(repo.session, run)

        completed = _create_test_run(
            run_id="run-startup-completed",
            agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
        )
        completed.status = RunStatus.COMPLETED
        await save_run(repo.session, completed)
        await session.commit()

    paused_ids = await monitor.recover_active_runs_on_startup()

    assert paused_ids == ["run-startup-a", "run-startup-b"]

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = SqliteEventStore(session)

        for run_id in paused_ids:
            run = await repo.get(run_id)
            assert run.status == RunStatus.PAUSED
            assert run.pause_reason == "agent_not_running_on_startup"

            events = await event_store.get_stream(run_id)
            assert [e.event_type for e in events] == ["agent_died", "run_status_changed"]
            agent_died_payload = json.loads(events[0].payload)
            assert agent_died_payload["reason"] == "agent_not_running_on_startup"
            status_payload = json.loads(events[1].payload)
            assert status_payload["old_status"] == "active"
            assert status_payload["new_status"] == "paused"
            assert status_payload["pause_reason"] == "agent_not_running_on_startup"

        completed_run = await repo.get("run-startup-completed")
        assert completed_run.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_recover_active_runs_on_startup_ignores_graph_runs(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """Graph-mode lifecycle recovery is owned by graph startup recovery."""
    session_factory = db_setup
    monitor = AgentRunnerMonitor(session_factory)

    async with session_factory() as session:
        repo = RunRepository(session)
        run = _create_test_run(run_id="run-startup-graph", agent_runner_type=None)
        run.status = RunStatus.ACTIVE
        run.execution_mode = "graph"
        await save_run(repo.session, run)
        await session.commit()

    paused_ids = await monitor.recover_active_runs_on_startup()

    assert paused_ids == []

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = SqliteEventStore(session)
        run = await repo.get("run-startup-graph")
        assert run.status == RunStatus.ACTIVE
        assert await event_store.get_stream("run-startup-graph") == []


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
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
            agent_runner_config={"pid": 999999},
        )
        run.status = RunStatus.ACTIVE
        # Simulate the task being in BUILDING state (agent started it)
        task_state = run.steps[0].tasks[0]
        task_state.status = TaskStatus.BUILDING
        await save_run(repo.session, run)
        await session.commit()

    # Pre-acquire the lock as the agent would have done
    now = datetime.now(timezone.utc)
    acquired = lock_manager.acquire(task_state.id, "default", now)
    assert acquired is True
    assert lock_manager.is_locked(task_state.id, now) is True

    # Agent dies → monitor should release the lock
    await monitor.on_agent_died(
        run_id="run-lock-cs",
        agent_runner_type=AgentRunnerType.CODEX_SERVER,
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
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
            agent_runner_config={"pid": 999999},
        )
        run.status = RunStatus.ACTIVE
        task_state = run.steps[0].tasks[0]
        task_state.status = TaskStatus.BUILDING
        await save_run(repo.session, run)
        await session.commit()

    # Should not raise even without a lock_manager
    await monitor.on_agent_died(
        run_id="run-nolock",
        agent_runner_type=AgentRunnerType.CODEX_SERVER,
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
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
            agent_runner_config={"pid": 999999},
        )
        run.status = RunStatus.ACTIVE
        # Task is already COMPLETED — no lock should be held or released
        task_state = run.steps[0].tasks[0]
        task_state.status = TaskStatus.COMPLETED
        await save_run(repo.session, run)
        await session.commit()

    task_id = task_state.id
    # Acquire a lock on some OTHER resource to confirm release is not called incorrectly
    now = datetime.now(timezone.utc)
    lock_manager.acquire(task_id, "other-agent", now)
    assert lock_manager.is_locked(task_id, now) is True

    await monitor.on_agent_died(
        run_id="run-completed",
        agent_runner_type=AgentRunnerType.CODEX_SERVER,
        reason="local_codex_process_not_alive",
    )

    # Lock held by "other-agent" should be untouched (monitor only releases "default")
    assert lock_manager.is_locked(task_id, datetime.now(timezone.utc)) is True
