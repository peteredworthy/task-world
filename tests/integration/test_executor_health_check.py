"""Tests for the pre-run health check in AgentRunnerExecutor.

Covers four scenarios:
1. Failing project tests → task start blocked (run paused with health_check_failed)
2. Passing project tests → task starts normally (health check does not block)
3. test_command: null → health check skipped entirely
4. No .task-world/config.yaml → convention default command used
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.api.app import create_app
from orchestrator.config.enums import AgentRunnerType, RoutineSource, RunStatus
from orchestrator.db.connection import init_db
from orchestrator.db.repositories import RunRepository

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def session_factory(app: FastAPI) -> async_sessionmaker[AsyncSession]:
    sf: async_sessionmaker[AsyncSession] = app.state.session_factory
    return sf


async def _make_run(
    session_factory: async_sessionmaker[AsyncSession],
    worktree_path: str,
    agent_command: str = "true",
) -> str:
    """Create a run with the given worktree_path and a simple CLI agent."""
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
        run.worktree_path = worktree_path
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run.agent_config = {"command": agent_command}

        run = await service.create_run(run)
        run_id = run.id

        executor = AgentRunnerExecutor(
            session_factory=session_factory,
            spawn_agents=True,
        )
        await executor.start_run_with_agent(run_id, service)
        await session.commit()

    return run_id


async def _poll_until_paused(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    timeout_iters: int = 80,
) -> str | None:
    """Poll until the run is paused; return pause_reason or None if timed out."""
    for _ in range(timeout_iters):
        async with session_factory() as session:
            repo = RunRepository(session)
            run = await repo.get(run_id)
            if run.status == RunStatus.PAUSED:
                return run.pause_reason
        await asyncio.sleep(0.05)
    return None


# ---------------------------------------------------------------------------
# Scenario 1: Failing health check blocks task start
# ---------------------------------------------------------------------------


async def test_failing_tests_block_task_start(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """When test_command exits non-zero the run is paused with health_check_failed."""
    task_world = tmp_path / ".task-world"
    task_world.mkdir()
    (task_world / "config.yaml").write_text("test_command: 'exit 1'\n")

    # The agent command doesn't matter; health check fires before agent execution.
    run_id = await _make_run(session_factory, str(tmp_path), agent_command="true")

    pause_reason = await _poll_until_paused(session_factory, run_id)

    assert pause_reason == "health_check_failed", (
        f"Expected pause_reason='health_check_failed', got {pause_reason!r}"
    )

    # Also verify last_error contains useful context
    async with session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)
    assert run.last_error is not None
    assert "health check failed" in run.last_error.lower()
    assert "exit 1" in run.last_error


# ---------------------------------------------------------------------------
# Scenario 2: Passing health check allows normal task start
# ---------------------------------------------------------------------------


async def test_passing_tests_allow_task_start(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """When test_command exits 0 the health check does not block the run.

    The run may still pause for other reasons (agent doesn't do useful work),
    but the pause_reason must NOT be health_check_failed.
    """
    task_world = tmp_path / ".task-world"
    task_world.mkdir()
    # 'true' always exits 0
    (task_world / "config.yaml").write_text("test_command: 'true'\n")

    run_id = await _make_run(session_factory, str(tmp_path), agent_command="true")

    # Give the executor a moment to run the health check and proceed
    pause_reason = await _poll_until_paused(session_factory, run_id, timeout_iters=80)

    # If the run paused, it must NOT be because of a health check failure
    if pause_reason is not None:
        assert pause_reason != "health_check_failed", (
            "Passing health check should not block run; got pause_reason='health_check_failed'"
        )


# ---------------------------------------------------------------------------
# Scenario 3: test_command: null skips the health check
# ---------------------------------------------------------------------------


async def test_null_test_command_skips_health_check(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """When test_command is null the health check is skipped entirely.

    The method returns None immediately without running any subprocess.
    We verify this by calling _run_project_health_check directly with a config
    that has test_command: null.
    """
    task_world = tmp_path / ".task-world"
    task_world.mkdir()
    (task_world / "config.yaml").write_text("test_command: null\n")

    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        spawn_agents=False,
    )
    result = await executor._run_project_health_check(str(tmp_path))

    assert result is None, (
        f"Expected None (health check skipped) when test_command is null, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 4: No .task-world/config.yaml → default convention command used
# ---------------------------------------------------------------------------


async def test_no_config_file_uses_default_command(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """When .task-world/config.yaml is absent the default 'uv run pytest --tb=no -q' is used.

    In an empty tmp_path there are no tests, so pytest exits non-zero; the error
    message must mention the default command so callers can understand what ran.
    """
    # Ensure no config file exists
    assert not (tmp_path / ".task-world" / "config.yaml").exists()

    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        spawn_agents=False,
    )
    result = await executor._run_project_health_check(str(tmp_path))

    # The health check ran the default command and failed (no tests in tmp_path)
    assert result is not None, (
        "Expected a non-None error when default pytest fails on empty directory"
    )
    assert "uv run pytest" in result, (
        f"Error message should include the default command 'uv run pytest', got: {result!r}"
    )
