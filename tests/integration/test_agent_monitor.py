"""Integration tests for AgentRunnerMonitor.on_agent_died and lock cleanup.

These tests verify side effects that require a real database:
- Run status transitions persisted to DB
- Events logged to EventStore
- Task lock release on agent death
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.runners import AgentRunnerMonitor
from orchestrator.config import AgentRunnerType, RunStatus, TaskStatus
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
        id_generator=lambda: run_id,
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

    async with session_factory() as session:
        repo = RunRepository(session)
        run = _create_test_run(
            run_id="run1", agent_type=AgentRunnerType.CLI_SUBPROCESS, agent_config={"pid": 12345}
        )
        run.status = RunStatus.ACTIVE
        await repo.save(run)
        await session.commit()

    await monitor.on_agent_died(
        run_id="run1",
        agent_type=AgentRunnerType.CLI_SUBPROCESS,
        exit_code=1,
        reason="agent_process_died",
    )

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = EventStore(session)
        updated_run = await repo.get("run1")
        assert updated_run.status == RunStatus.PAUSED
        assert updated_run.pause_reason == "agent_process_died"

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

    async with session_factory() as session:
        repo = RunRepository(session)
        run = _create_test_run(run_id="run2", agent_type=AgentRunnerType.CLI_SUBPROCESS)
        run.status = RunStatus.COMPLETED
        await repo.save(run)
        await session.commit()

    await monitor.on_agent_died(
        run_id="run2",
        agent_type=AgentRunnerType.CLI_SUBPROCESS,
        exit_code=1,
    )

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = EventStore(session)
        updated_run = await repo.get("run2")
        assert updated_run.status == RunStatus.COMPLETED

        events = await event_store.get_events_for_run("run2")
        assert len(events) == 0


# ---------- lock cleanup tests ----------


@pytest.mark.asyncio
async def test_on_agent_died_releases_building_task_lock_codex_server(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """on_agent_died releases the lock on a BUILDING task for CODEX_SERVER."""
    session_factory = db_setup
    lock_manager = InMemoryLockManager()
    monitor = AgentRunnerMonitor(session_factory, lock_manager=lock_manager)

    async with session_factory() as session:
        repo = RunRepository(session)
        run = _create_test_run(
            run_id="run-lock-cs",
            agent_type=AgentRunnerType.CODEX_SERVER,
            agent_config={"pid": 999999},
        )
        run.status = RunStatus.ACTIVE
        task_state = run.steps[0].tasks[0]
        task_state.status = TaskStatus.BUILDING
        await repo.save(run)
        await session.commit()

    now = datetime.now(timezone.utc)
    acquired = lock_manager.acquire(task_state.id, "default", now)
    assert acquired is True
    assert lock_manager.is_locked(task_state.id, now) is True

    await monitor.on_agent_died(
        run_id="run-lock-cs",
        agent_type=AgentRunnerType.CODEX_SERVER,
        reason="local_codex_process_not_alive",
    )

    assert lock_manager.is_locked(task_state.id, datetime.now(timezone.utc)) is False


@pytest.mark.asyncio
async def test_on_agent_died_without_lock_manager_does_not_error(
    db_setup: async_sessionmaker[AsyncSession],
) -> None:
    """on_agent_died works correctly when no lock_manager is provided."""
    session_factory = db_setup
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

    await monitor.on_agent_died(
        run_id="run-nolock",
        agent_type=AgentRunnerType.CODEX_SERVER,
        reason="local_codex_process_not_alive",
    )

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
        task_state = run.steps[0].tasks[0]
        task_state.status = TaskStatus.COMPLETED
        await repo.save(run)
        await session.commit()

    task_id = task_state.id
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
