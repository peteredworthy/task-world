"""Integration tests for AgentExecutor error handling."""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.agents.executor import AgentExecutor
from orchestrator.api.app import create_app
from orchestrator.config.enums import AgentType, RoutineSource, RunStatus
from orchestrator.db.connection import init_db
from orchestrator.db.repositories import RunRepository
from orchestrator.workflow.service import WorkflowService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


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
    from orchestrator.db.event_store import EventStore
    from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
    from orchestrator.workflow.event_logger import PersistentEventEmitter

    sf: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with sf() as session:
        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        yield WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )


async def test_executor_pauses_run_on_agent_not_available(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """AgentNotAvailableError should pause the run."""
    # Create executor with spawning enabled
    executor = AgentExecutor(
        session_factory=session_factory,
        spawn_agents=True,
    )

    # Create and start a run with a non-existent command
    async with session_factory() as session:
        from orchestrator.db.event_store import EventStore
        from orchestrator.db.repositories import RunRepository
        from orchestrator.routines.discovery import discover_routines
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
        from orchestrator.workflow.event_logger import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        # Discover routines and create run
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentType.CLI_SUBPROCESS
        run.agent_config = {"command": "nonexistent_command_xyz_12345"}

        run = await service.create_run(run)
        run_id = run.id

        # Start the run with the executor
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    # Poll until the run is paused (agent loop should fail quickly)
    for _ in range(50):
        async with session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run.status == RunStatus.PAUSED:
                break
        await asyncio.sleep(0.05)
    else:
        async with session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
        assert run.status == RunStatus.PAUSED, (
            f"Run should be PAUSED when agent is not available, got {run.status.value}"
        )


async def test_executor_pauses_run_on_agent_execution_error(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """AgentExecutionError should pause the run."""
    # Create executor with spawning enabled
    executor = AgentExecutor(
        session_factory=session_factory,
        spawn_agents=True,
    )

    # Create and start a run with a command that times out
    async with session_factory() as session:
        from orchestrator.db.event_store import EventStore
        from orchestrator.db.repositories import RunRepository
        from orchestrator.routines.discovery import discover_routines
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
        from orchestrator.workflow.event_logger import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService
        from orchestrator.config.global_config import (
            GlobalConfig,
            NudgerConfig as GlobalNudgerConfig,
        )

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        # Discover routines and create run
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentType.CLI_SUBPROCESS
        # This command will hang and be killed by the nudger
        run.agent_config = {
            "command": "python3",
            "args": ["-c", "import time; time.sleep(300)"],
            "poll_interval": 0.1,  # Fast polling for tests
        }

        run = await service.create_run(run)
        run_id = run.id

    # Create a new executor with aggressive nudger config
    from orchestrator.config.global_config import GlobalConfig, NudgerConfig as GlobalNudgerConfig

    global_config = GlobalConfig(
        nudger=GlobalNudgerConfig(
            check_interval_seconds=1,
            nudge_after_seconds=1,
            kill_after_seconds=1,
        )
    )
    executor = AgentExecutor(
        session_factory=session_factory,
        global_config=global_config,
        spawn_agents=True,
    )

    # Start the run
    async with session_factory() as session:
        from orchestrator.db.event_store import EventStore
        from orchestrator.db.repositories import RunRepository
        from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
        from orchestrator.workflow.event_logger import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    # Poll until the run is paused (nudger should kill the stuck agent quickly)
    for _ in range(100):
        async with session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run.status == RunStatus.PAUSED:
                break
        await asyncio.sleep(0.05)
    else:
        async with session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
        assert run.status == RunStatus.PAUSED, (
            f"Run should be PAUSED when agent execution fails, got {run.status.value}"
        )


async def test_executor_pauses_run_when_agent_returns_unsuccessful_result(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Non-zero subprocess exit should pause the run instead of retry-looping."""
    executor = AgentExecutor(
        session_factory=session_factory,
        spawn_agents=True,
    )

    async with session_factory() as session:
        from orchestrator.db.event_store import EventStore
        from orchestrator.db.repositories import RunRepository
        from orchestrator.routines.discovery import discover_routines
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
        from orchestrator.workflow.event_logger import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentType.CLI_SUBPROCESS
        run.agent_config = {
            "command": "python3",
            "args": ["-c", "import sys; sys.exit(1)"],
        }

        run = await service.create_run(run)
        run_id = run.id
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    for _ in range(80):
        async with session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run.status == RunStatus.PAUSED:
                break
        await asyncio.sleep(0.05)
    else:
        async with session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
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
    # Create executor with spawning enabled
    executor = AgentExecutor(
        session_factory=session_factory,
        spawn_agents=True,
    )

    # Create and start a run with a successful command that doesn't do anything useful
    async with session_factory() as session:
        from orchestrator.db.event_store import EventStore
        from orchestrator.db.repositories import RunRepository
        from orchestrator.routines.discovery import discover_routines
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
        from orchestrator.workflow.event_logger import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        # Discover routines and create run
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentType.CLI_SUBPROCESS
        # This command will succeed but doesn't mark checklist items as done
        run.agent_config = {"command": "echo", "args": ["hello"]}

        run = await service.create_run(run)
        run_id = run.id

        # Start the run with the executor
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    # Poll until the run is paused (agent should complete quickly then gate check fails)
    for _ in range(50):
        async with session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run.status == RunStatus.PAUSED:
                break
        await asyncio.sleep(0.05)
    else:
        async with session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
        # Run should be PAUSED because the agent succeeded but the workflow
        # couldn't progress (gate check failed due to incomplete checklist)
        assert run.status == RunStatus.PAUSED, (
            f"Run should be PAUSED when agent fails to complete workflow, got {run.status.value}"
        )


async def test_executor_persists_builder_prompt_before_execution(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Builder prompt should be persisted before agent execution starts."""
    # Create executor with spawning enabled
    executor = AgentExecutor(
        session_factory=session_factory,
        spawn_agents=True,
    )

    # Create and start a run with a command that immediately fails
    async with session_factory() as session:
        from orchestrator.db.event_store import EventStore
        from orchestrator.db.repositories import RunRepository
        from orchestrator.routines.discovery import discover_routines
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
        from orchestrator.workflow.event_logger import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        # Discover routines and create run
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.worktree_path = str(tmp_path)  # Set worktree for CLI agent to work
        run.agent_type = AgentType.CLI_SUBPROCESS
        # Use a command that exits immediately with error
        run.agent_config = {"command": "false"}
        # Skip pre-run health check in tests
        (tmp_path / ".task-world").mkdir(exist_ok=True)
        (tmp_path / ".task-world" / "config.yaml").write_text("test_command: null\n")

        run = await service.create_run(run)
        run_id = run.id

        # Start the run with the executor
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    # Poll until the run is paused
    for _ in range(50):
        async with session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run.status == RunStatus.PAUSED:
                break
        await asyncio.sleep(0.05)

    # Verify the builder prompt was persisted
    async with session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)

        # Get the first task's first attempt
        assert len(run.steps) > 0
        assert len(run.steps[0].tasks) > 0
        task = run.steps[0].tasks[0]
        assert len(task.attempts) > 0
        attempt = task.attempts[0]

        # Verify builder prompt was stored
        assert attempt.builder_prompt is not None
        assert len(attempt.builder_prompt) > 0
        # Verify it contains expected builder prompt content
        assert "builder phase" in attempt.builder_prompt.lower()
        assert "## Task" in attempt.builder_prompt
        # Verify verifier prompt is not set for builder phase
        assert attempt.verifier_prompt is None


async def test_agent_metadata_persisted_immediately(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Agent metadata (PID) should be persisted immediately when subprocess is created."""
    # Create executor with spawning enabled
    executor = AgentExecutor(
        session_factory=session_factory,
        spawn_agents=True,
    )

    # Create and start a run with a slow command so we can check metadata while running
    async with session_factory() as session:
        from orchestrator.db.event_store import EventStore
        from orchestrator.db.repositories import RunRepository
        from orchestrator.routines.discovery import discover_routines
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
        from orchestrator.workflow.event_logger import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        # Discover routines and create run
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentType.CLI_SUBPROCESS
        # Use a command that will sleep briefly so metadata is persisted before completion
        run.agent_config = {"command": "sleep", "args": ["0.1"]}
        # Set worktree path so agent can execute
        run.worktree_path = str(tmp_path)
        # Skip pre-run health check in tests
        (tmp_path / ".task-world").mkdir(exist_ok=True)
        (tmp_path / ".task-world" / "config.yaml").write_text("test_command: null\n")

        run = await service.create_run(run)
        run_id = run.id

        # Start the run with the executor
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    # Wait for agent to start and metadata callback to execute
    # The agent loop should start executing the first task, which triggers the callback
    for i in range(100):
        await asyncio.sleep(0.05)
        async with session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if "pid" in run.agent_config:
                break

    async with session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)

        # Verify that agent_config contains pid (metadata persisted immediately)
        assert "pid" in run.agent_config, (
            f"Agent metadata (pid) should be persisted immediately when subprocess is created. "
            f"Got agent_config: {run.agent_config}"
        )
        pid = run.agent_config.get("pid")
        assert isinstance(pid, int) and pid > 0, f"Invalid pid: {pid}"


async def test_agent_death_detection_on_startup(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """On startup recovery, runs with dead agents should be paused."""
    # First, create an executor and start a run, but don't wait for it to complete
    executor1 = AgentExecutor(
        session_factory=session_factory,
        spawn_agents=True,
    )

    # Create and start a run with a fast-failing command
    async with session_factory() as session:
        from orchestrator.db.event_store import EventStore
        from orchestrator.db.repositories import RunRepository
        from orchestrator.routines.discovery import discover_routines
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
        from orchestrator.workflow.event_logger import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        # Discover routines and create run
        routines = discover_routines([(FIXTURES, RoutineSource.LOCAL)])
        routine = next(r for r in routines if r.config.id == "simple-routine")

        run = create_run_from_routine(
            routine=routine.config,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.config.model_dump(mode="json")
        run.agent_type = AgentType.CLI_SUBPROCESS
        # Command that fails immediately
        run.agent_config = {"command": "false"}
        # Set worktree path so agent can execute
        run.worktree_path = str(tmp_path)
        # Skip pre-run health check in tests
        (tmp_path / ".task-world").mkdir(exist_ok=True)
        (tmp_path / ".task-world" / "config.yaml").write_text("test_command: null\n")

        run = await service.create_run(run)
        run_id = run.id

        # Start the run
        await executor1.start_run_with_agent(run_id, service)
        await session.commit()

    # Wait a bit for agent to fail
    await asyncio.sleep(0.5)

    # Check that run was paused due to agent failure
    async with session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)
        # Run should be PAUSED because agent exited with non-zero code
        assert run.status in (RunStatus.PAUSED, RunStatus.FAILED), (
            f"Run should be PAUSED or FAILED after agent fails, got {run.status.value}"
        )
