"""Unit tests for Codex agent lifecycle control paths in AgentRunnerExecutor.

Covers:
- ``_prepare_codex_config``: deterministic recovery rule for session health.
- ``check_agent_alive`` (AgentRunnerMonitor): Codex-specific liveness checks.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.runners import AgentRunnerMonitor
from orchestrator.config.enums import AgentRunnerType, RunStatus
from orchestrator.config.global_config import GlobalConfig
from orchestrator.config.models import RequirementConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import Run


# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_setup() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    yield session_factory
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor(global_config: GlobalConfig | None = None) -> AgentRunnerExecutor:
    """Return an AgentRunnerExecutor with no real DB session and spawning disabled."""
    return AgentRunnerExecutor(
        session_factory=None,  # type: ignore[arg-type]
        global_config=global_config,
        spawn_agents=False,
    )


def _create_test_run(
    run_id: str = "test-run",
    agent_type: AgentRunnerType | None = None,
    agent_config: dict | None = None,
) -> Run:
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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: datetime) -> str:
    """Return ISO-8601 string from a datetime."""
    return dt.isoformat()


# ===========================================================================
# _prepare_codex_config — CODEX_SERVER (local)
# ===========================================================================


class TestPrepareCodexConfigLocal:
    """Tests for the deterministic recovery rule for the local Codex variant."""

    def test_no_pid_stored_returns_unchanged(self) -> None:
        """No PID in config → nothing to classify, config returned unchanged."""
        executor = _make_executor()
        config = {"endpoint": "http://localhost:9000", "model": "o3"}
        result_config, stale_reason = executor._prepare_codex_config(
            AgentRunnerType.CODEX_SERVER, config
        )
        assert stale_reason is None
        assert result_config is config  # same object

    def test_alive_pid_returns_unchanged(self) -> None:
        """PID of the current (alive) process → healthy, config unchanged."""
        executor = _make_executor()
        config = {"pid": os.getpid()}
        result_config, stale_reason = executor._prepare_codex_config(
            AgentRunnerType.CODEX_SERVER, config
        )
        assert stale_reason is None
        assert result_config["pid"] == os.getpid()

    def test_dead_pid_strips_pid_and_returns_reason(self) -> None:
        """Dead PID → stale; PID key removed; reason returned."""
        executor = _make_executor()
        config = {"pid": 999999, "endpoint": "http://localhost:9000"}
        result_config, stale_reason = executor._prepare_codex_config(
            AgentRunnerType.CODEX_SERVER, config
        )
        assert stale_reason is not None
        assert "pid" not in result_config
        assert "999999" in stale_reason
        assert "endpoint" in result_config  # other keys preserved

    def test_dead_pid_reason_mentions_process_not_alive(self) -> None:
        """Stale reason contains 'not_alive' for a dead local process."""
        executor = _make_executor()
        config = {"pid": 999999}
        _, stale_reason = executor._prepare_codex_config(AgentRunnerType.CODEX_SERVER, config)
        assert stale_reason is not None
        assert "not_alive" in stale_reason

    def test_non_codex_agent_type_returned_unchanged(self) -> None:
        """Non-Codex agent types are not classified — config returned unchanged."""
        executor = _make_executor()
        config = {"pid": os.getpid(), "command": "claude"}
        for agent_type in (
            AgentRunnerType.CLI_SUBPROCESS,
            AgentRunnerType.OPENHANDS_LOCAL,
            AgentRunnerType.OPENHANDS_DOCKER,
            AgentRunnerType.USER_MANAGED,
        ):
            result_config, stale_reason = executor._prepare_codex_config(agent_type, config)
            assert stale_reason is None
            assert result_config is config


# ===========================================================================
# check_agent_alive — CODEX_SERVER (local)
# ===========================================================================


class TestCheckAgentAliveCodexLocal:
    """AgentRunnerMonitor.check_agent_alive for CODEX_SERVER agent type."""

    @pytest.mark.asyncio
    async def test_codex_server_alive_pid(self, db_setup: async_sessionmaker[AsyncSession]) -> None:
        """CODEX_SERVER with a live PID → alive."""
        monitor = AgentRunnerMonitor(db_setup)
        run = _create_test_run(
            run_id="r1",
            agent_type=AgentRunnerType.CODEX_SERVER,
            agent_config={"pid": os.getpid()},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is True

    @pytest.mark.asyncio
    async def test_codex_server_dead_pid(self, db_setup: async_sessionmaker[AsyncSession]) -> None:
        """CODEX_SERVER with a dead PID → still alive (per-task subprocess model).

        CodexServerAgent spawns a new process per task, so the PID is stale
        between tasks.  check_agent_alive always returns True; the executor's
        own error handling catches real subprocess failures.
        """
        monitor = AgentRunnerMonitor(db_setup)
        run = _create_test_run(
            run_id="r2",
            agent_type=AgentRunnerType.CODEX_SERVER,
            agent_config={"pid": 999999},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is True

    @pytest.mark.asyncio
    async def test_codex_server_no_pid(self, db_setup: async_sessionmaker[AsyncSession]) -> None:
        """CODEX_SERVER with no PID in config → still alive (per-task subprocess model)."""
        monitor = AgentRunnerMonitor(db_setup)
        run = _create_test_run(
            run_id="r3",
            agent_type=AgentRunnerType.CODEX_SERVER,
            agent_config={},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is True


# ===========================================================================
# Dead-agent monitoring integration — on_agent_died for Codex variants
# ===========================================================================


@pytest.mark.asyncio
async def test_on_agent_died_codex_server_transitions_to_paused() -> None:
    """AgentRunnerMonitor.on_agent_died transitions a CODEX_SERVER run to PAUSED."""
    from orchestrator.db import create_engine, create_session_factory, init_db
    from orchestrator.db import RunRepository

    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    try:
        monitor = AgentRunnerMonitor(session_factory)

        async with session_factory() as session:
            repo = RunRepository(session)
            run = _create_test_run(
                run_id="run-cs",
                agent_type=AgentRunnerType.CODEX_SERVER,
                agent_config={"pid": 999999},
            )
            run.status = RunStatus.ACTIVE
            await repo.save(run)
            await session.commit()

        await monitor.on_agent_died(
            run_id="run-cs",
            agent_type=AgentRunnerType.CODEX_SERVER,
            reason="local_codex_process_not_alive",
        )

        async with session_factory() as session:
            repo = RunRepository(session)
            updated = await repo.get("run-cs")
            assert updated.status == RunStatus.PAUSED
            assert updated.pause_reason == "local_codex_process_not_alive"
    finally:
        await engine.dispose()


# ===========================================================================
# Lifecycle: spawn_for_run includes both Codex variants
# ===========================================================================


def test_spawn_for_run_codex_server_returns_false_when_disabled() -> None:
    """spawn_for_run returns False when spawning is disabled for CODEX_SERVER."""
    executor = AgentRunnerExecutor(session_factory=None, spawn_agents=False)  # type: ignore[arg-type]
    spawned = executor.spawn_for_run("run-id", AgentRunnerType.CODEX_SERVER, {})
    assert spawned is False


def test_is_running_returns_false_before_spawn() -> None:
    """is_running returns False for a run that has not been spawned."""
    executor = AgentRunnerExecutor(session_factory=None, spawn_agents=False)  # type: ignore[arg-type]
    assert executor.is_running("run-id") is False
