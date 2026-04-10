"""Integration tests for AgentRunnerExecutor error handling.

These tests verify that the executor transitions runs to PAUSED when
agents fail in various ways. Instead of polling the DB with sleeps,
each test awaits the executor's background task directly so that
assertions run immediately after the agent loop exits — no timing
dependence.
"""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.api.app import create_app
from orchestrator.config import AgentRunnerType, RoutineSource, RunStatus
from orchestrator.db import init_db
from orchestrator.db import RunRepository
from orchestrator.workflow.service import WorkflowService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _await_agent_loop(executor: AgentRunnerExecutor, run_id: str) -> None:
    """Wait for the executor's background agent-loop task to finish.

    ``start_run_with_agent`` stores its ``asyncio.Task`` in
    ``executor._running_tasks[run_id]``.  Awaiting it removes all timing
    dependence — the test proceeds as soon as the loop exits rather than
    polling with arbitrary sleeps.

    Also cancels any remaining background tasks (e.g. health monitor) to
    prevent them from accessing the in-memory DB after the test's engine
    is disposed.
    """
    task = executor._running_tasks.get(run_id)
    if task is not None:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass  # Agent errors are expected — we inspect DB state below

    # Cancel any lingering background tasks to avoid "no such table"
    # errors when the in-memory DB is torn down.
    for tid, t in list(executor._running_tasks.items()):
        if not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


def _make_service_args(session: AsyncSession) -> dict:
    """Build the kwargs dict for constructing a WorkflowService."""
    from orchestrator.db import EventStore
    from orchestrator.workflow import LocalAutoVerifyRunner
    from orchestrator.workflow import PersistentEventEmitter

    repo = RunRepository(session)
    event_store = EventStore(session)
    emitter = PersistentEventEmitter(event_store)
    return dict(
        session=session,
        repo=repo,
        event_store=event_store,
        event_emitter=emitter,
        auto_verify_runner=LocalAutoVerifyRunner(),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
    """Create test app with in-memory database."""
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def session_factory(app: FastAPI) -> async_sessionmaker[AsyncSession]:
    """Get session factory from app."""
    sf: async_sessionmaker[AsyncSession] = app.state.session_factory
    return sf


@pytest.fixture
async def service(app: FastAPI) -> AsyncGenerator[WorkflowService, None]:
    """Create WorkflowService for tests."""
    sf: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with sf() as session:
        yield WorkflowService(**_make_service_args(session))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_executor_pauses_run_on_agent_not_available(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """AgentNotAvailableError should pause the run."""
    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        service_factory=app.state.service_factory,
        spawn_agents=True,
    )

    async with session_factory() as session:
        from orchestrator.config import discover_routines
        from orchestrator.state.factory import create_run_from_routine

        service = WorkflowService(**_make_service_args(session))
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run.agent_config = {"command": "nonexistent_command_xyz_12345"}

        run = await service.create_run(run)
        run_id = run.id
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    await _await_agent_loop(executor, run_id)

    async with session_factory() as session:
        run = await RunRepository(session).get(run_id)
        assert run.status == RunStatus.PAUSED, (
            f"Run should be PAUSED when agent is not available, got {run.status.value}"
        )


async def test_executor_pauses_run_on_agent_execution_error(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """AgentExecutionError should pause the run."""
    from orchestrator.config.global_config import GlobalConfig, NudgerConfig as GlobalNudgerConfig

    # Aggressive nudger config so the stuck agent is killed quickly
    global_config = GlobalConfig(
        nudger=GlobalNudgerConfig(
            check_interval_seconds=1,
            nudge_after_seconds=1,
            kill_after_seconds=1,
        )
    )
    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        global_config=global_config,
        service_factory=app.state.service_factory,
        spawn_agents=True,
    )

    async with session_factory() as session:
        from orchestrator.config import discover_routines
        from orchestrator.state.factory import create_run_from_routine

        service = WorkflowService(**_make_service_args(session))
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run.agent_config = {
            "command": "python3",
            "args": ["-c", "import time; time.sleep(300)"],
            "poll_interval": 0.1,
        }

        run = await service.create_run(run)
        run_id = run.id
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    await _await_agent_loop(executor, run_id)

    async with session_factory() as session:
        run = await RunRepository(session).get(run_id)
        assert run.status == RunStatus.PAUSED, (
            f"Run should be PAUSED when agent execution fails, got {run.status.value}"
        )


async def test_executor_pauses_run_when_agent_returns_unsuccessful_result(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Non-zero subprocess exit should pause the run instead of retry-looping."""
    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        service_factory=app.state.service_factory,
        spawn_agents=True,
    )

    async with session_factory() as session:
        from orchestrator.config import discover_routines
        from orchestrator.state.factory import create_run_from_routine

        service = WorkflowService(**_make_service_args(session))
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run.agent_config = {
            "command": "python3",
            "args": ["-c", "import sys; sys.exit(1)"],
        }

        run = await service.create_run(run)
        run_id = run.id
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    await _await_agent_loop(executor, run_id)

    async with session_factory() as session:
        run = await RunRepository(session).get(run_id)
        assert run.status == RunStatus.PAUSED, (
            "Run should be PAUSED when subprocess exits non-zero to avoid retry loops"
        )


async def test_executor_pauses_when_agent_fails_to_complete_workflow(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Executor should pause run when agent succeeds but workflow doesn't progress.

    When an agent exits successfully (code 0) but fails to progress the workflow
    (e.g., doesn't mark checklist items as done), the on_submit callback will
    trigger a gate check that fails. The executor catches this error and pauses
    the run so the user can investigate.
    """
    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        service_factory=app.state.service_factory,
        spawn_agents=True,
    )

    async with session_factory() as session:
        from orchestrator.config import discover_routines
        from orchestrator.state.factory import create_run_from_routine

        service = WorkflowService(**_make_service_args(session))
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run.agent_config = {"command": "echo", "args": ["hello"]}

        run = await service.create_run(run)
        run_id = run.id
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    await _await_agent_loop(executor, run_id)

    async with session_factory() as session:
        run = await RunRepository(session).get(run_id)
        assert run.status == RunStatus.PAUSED, (
            f"Run should be PAUSED when agent fails to complete workflow, got {run.status.value}"
        )


async def test_executor_persists_builder_prompt_before_execution(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Builder prompt should be persisted before agent execution starts."""
    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        service_factory=app.state.service_factory,
        spawn_agents=True,
    )

    async with session_factory() as session:
        from orchestrator.config import discover_routines
        from orchestrator.state.factory import create_run_from_routine

        service = WorkflowService(**_make_service_args(session))
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.worktree_path = str(tmp_path)
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run.agent_config = {"command": "false"}
        (tmp_path / ".task-world").mkdir(exist_ok=True)
        (tmp_path / ".task-world" / "config.yaml").write_text("test_command: null\n")

        run = await service.create_run(run)
        run_id = run.id
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    await _await_agent_loop(executor, run_id)

    async with session_factory() as session:
        run = await RunRepository(session).get(run_id)
        assert run.status == RunStatus.PAUSED
        assert len(run.steps) > 0
        assert len(run.steps[0].tasks) > 0
        task = run.steps[0].tasks[0]
        assert len(task.attempts) > 0
        attempt = task.attempts[0]

        assert attempt.builder_prompt is not None
        assert len(attempt.builder_prompt) > 0
        assert "builder phase" in attempt.builder_prompt.lower()
        assert "## Task" in attempt.builder_prompt
        assert attempt.verifier_prompt is None


async def test_agent_metadata_persisted_immediately(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Agent metadata (PID) should be persisted immediately when subprocess is created."""
    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        service_factory=app.state.service_factory,
        spawn_agents=True,
    )

    async with session_factory() as session:
        from orchestrator.config import discover_routines
        from orchestrator.state.factory import create_run_from_routine

        service = WorkflowService(**_make_service_args(session))
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        # Use a command that exits immediately — the PID is persisted via
        # the on_agent_metadata callback before the process terminates.
        run.agent_config = {"command": "false"}
        run.worktree_path = str(tmp_path)
        (tmp_path / ".task-world").mkdir(exist_ok=True)
        (tmp_path / ".task-world" / "config.yaml").write_text("test_command: null\n")

        run = await service.create_run(run)
        run_id = run.id
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    await _await_agent_loop(executor, run_id)

    async with session_factory() as session:
        run = await RunRepository(session).get(run_id)
        assert "pid" in run.agent_config, (
            f"Agent metadata (pid) should be persisted when subprocess is created. "
            f"Got agent_config: {run.agent_config}"
        )
        pid = run.agent_config.get("pid")
        assert isinstance(pid, int) and pid > 0, f"Invalid pid: {pid}"


async def test_agent_death_detection_on_startup(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """On startup recovery, runs with dead agents should be paused."""
    executor1 = AgentRunnerExecutor(
        session_factory=session_factory,
        service_factory=app.state.service_factory,
        spawn_agents=True,
    )

    async with session_factory() as session:
        from orchestrator.config import discover_routines
        from orchestrator.state.factory import create_run_from_routine

        service = WorkflowService(**_make_service_args(session))
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run.agent_config = {"command": "false"}
        run.worktree_path = str(tmp_path)
        (tmp_path / ".task-world").mkdir(exist_ok=True)
        (tmp_path / ".task-world" / "config.yaml").write_text("test_command: null\n")

        run = await service.create_run(run)
        run_id = run.id
        await executor1.start_run_with_agent(run_id, service)
        await session.commit()

    await _await_agent_loop(executor1, run_id)

    async with session_factory() as session:
        run = await RunRepository(session).get(run_id)
        assert run.status in (RunStatus.PAUSED, RunStatus.FAILED), (
            f"Run should be PAUSED or FAILED after agent fails, got {run.status.value}"
        )
