"""Unit tests for Codex agent lifecycle control paths in AgentExecutor.

Covers:
- ``_prepare_codex_config``: deterministic recovery rule for session health.
- ``check_agent_alive`` (AgentMonitor): Codex-specific liveness checks.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.agents.executor import AgentExecutor
from orchestrator.agents.monitor import AgentMonitor
from orchestrator.config.enums import AgentType, RunStatus
from orchestrator.config.global_config import AgentsConfig, GlobalConfig
from orchestrator.config.models import RequirementConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.db.connection import create_engine, create_session_factory, init_db
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


def _make_executor(global_config: GlobalConfig | None = None) -> AgentExecutor:
    """Return an AgentExecutor with no real DB session and spawning disabled."""
    return AgentExecutor(
        session_factory=None,  # type: ignore[arg-type]
        global_config=global_config,
        spawn_agents=False,
    )


def _create_test_run(
    run_id: str = "test-run",
    agent_type: AgentType | None = None,
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
        result_config, stale_reason = executor._prepare_codex_config(AgentType.CODEX_SERVER, config)
        assert stale_reason is None
        assert result_config is config  # same object

    def test_alive_pid_returns_unchanged(self) -> None:
        """PID of the current (alive) process → healthy, config unchanged."""
        executor = _make_executor()
        config = {"pid": os.getpid()}
        result_config, stale_reason = executor._prepare_codex_config(AgentType.CODEX_SERVER, config)
        assert stale_reason is None
        assert result_config["pid"] == os.getpid()

    def test_dead_pid_strips_pid_and_returns_reason(self) -> None:
        """Dead PID → stale; PID key removed; reason returned."""
        executor = _make_executor()
        config = {"pid": 999999, "endpoint": "http://localhost:9000"}
        result_config, stale_reason = executor._prepare_codex_config(AgentType.CODEX_SERVER, config)
        assert stale_reason is not None
        assert "pid" not in result_config
        assert "999999" in stale_reason
        assert "endpoint" in result_config  # other keys preserved

    def test_dead_pid_reason_mentions_process_not_alive(self) -> None:
        """Stale reason contains 'not_alive' for a dead local process."""
        executor = _make_executor()
        config = {"pid": 999999}
        _, stale_reason = executor._prepare_codex_config(AgentType.CODEX_SERVER, config)
        assert stale_reason is not None
        assert "not_alive" in stale_reason

    def test_non_codex_agent_type_returned_unchanged(self) -> None:
        """Non-Codex agent types are not classified — config returned unchanged."""
        executor = _make_executor()
        config = {"pid": os.getpid(), "command": "claude"}
        for agent_type in (
            AgentType.CLI_SUBPROCESS,
            AgentType.OPENHANDS_LOCAL,
            AgentType.OPENHANDS_DOCKER,
            AgentType.USER_MANAGED,
        ):
            result_config, stale_reason = executor._prepare_codex_config(agent_type, config)
            assert stale_reason is None
            assert result_config is config


# ===========================================================================
# _prepare_codex_config — CODEX_SERVER_REMOTE
# ===========================================================================


class TestPrepareCodexConfigRemote:
    """Tests for the deterministic recovery rule for the remote Codex variant."""

    def test_no_session_id_returns_unchanged(self) -> None:
        """No session_id in config → nothing to classify, config unchanged."""
        executor = _make_executor()
        config = {"base_url": "https://codex.example.com"}
        result_config, stale_reason = executor._prepare_codex_config(
            AgentType.CODEX_SERVER_REMOTE, config
        )
        assert stale_reason is None
        assert result_config is config

    def test_session_id_without_timestamp_assumed_healthy(self) -> None:
        """session_id present but no session_created_at → unknown age → alive."""
        executor = _make_executor()
        config = {"session_id": "sess-abc", "base_url": "https://codex.example.com"}
        result_config, stale_reason = executor._prepare_codex_config(
            AgentType.CODEX_SERVER_REMOTE, config
        )
        assert stale_reason is None
        assert result_config["session_id"] == "sess-abc"

    def test_session_id_recent_timestamp_is_healthy(self) -> None:
        """session_created_at within timeout → healthy session, config unchanged."""
        executor = _make_executor()
        recent = _now_utc() - timedelta(minutes=30)
        config = {
            "session_id": "sess-abc",
            "session_created_at": _ts(recent),
            "base_url": "https://codex.example.com",
        }
        result_config, stale_reason = executor._prepare_codex_config(
            AgentType.CODEX_SERVER_REMOTE, config
        )
        assert stale_reason is None
        assert result_config["session_id"] == "sess-abc"
        assert "session_created_at" in result_config

    def test_session_id_expired_timestamp_is_stale(self) -> None:
        """session_created_at beyond default timeout → stale; keys stripped."""
        # Default timeout is 120 minutes; use 200 minutes ago to ensure expiry.
        executor = _make_executor()
        old = _now_utc() - timedelta(minutes=200)
        config = {
            "session_id": "sess-old",
            "session_created_at": _ts(old),
            "base_url": "https://codex.example.com",
        }
        result_config, stale_reason = executor._prepare_codex_config(
            AgentType.CODEX_SERVER_REMOTE, config
        )
        assert stale_reason is not None
        assert "session_id" not in result_config
        assert "session_created_at" not in result_config
        assert "expired" in stale_reason
        # Non-session keys should be preserved.
        assert result_config.get("base_url") == "https://codex.example.com"

    def test_custom_timeout_respected(self) -> None:
        """GlobalConfig.codex_session_timeout_minutes is used for staleness check."""
        # With timeout=10 minutes, a session created 15 minutes ago is stale.
        config_obj = GlobalConfig(agents=AgentsConfig(codex_session_timeout_minutes=10))
        executor = _make_executor(global_config=config_obj)
        old = _now_utc() - timedelta(minutes=15)
        config = {
            "session_id": "sess-custom",
            "session_created_at": _ts(old),
        }
        result_config, stale_reason = executor._prepare_codex_config(
            AgentType.CODEX_SERVER_REMOTE, config
        )
        assert stale_reason is not None
        assert "session_id" not in result_config

    def test_custom_timeout_healthy(self) -> None:
        """Session created within custom timeout window is considered healthy."""
        config_obj = GlobalConfig(agents=AgentsConfig(codex_session_timeout_minutes=60))
        executor = _make_executor(global_config=config_obj)
        recent = _now_utc() - timedelta(minutes=30)
        config = {
            "session_id": "sess-recent",
            "session_created_at": _ts(recent),
        }
        result_config, stale_reason = executor._prepare_codex_config(
            AgentType.CODEX_SERVER_REMOTE, config
        )
        assert stale_reason is None
        assert result_config["session_id"] == "sess-recent"

    def test_malformed_timestamp_treated_as_stale(self) -> None:
        """Unparseable session_created_at → invalid_session_created_at stale reason."""
        executor = _make_executor()
        config = {
            "session_id": "sess-bad",
            "session_created_at": "not-a-timestamp",
        }
        result_config, stale_reason = executor._prepare_codex_config(
            AgentType.CODEX_SERVER_REMOTE, config
        )
        assert stale_reason is not None
        assert "invalid" in stale_reason
        assert "session_id" not in result_config

    def test_non_string_timestamp_treated_as_stale(self) -> None:
        """Non-string session_created_at (e.g. int) → invalid stale reason."""
        executor = _make_executor()
        config = {
            "session_id": "sess-bad",
            "session_created_at": 12345,  # not a str or datetime
        }
        result_config, stale_reason = executor._prepare_codex_config(
            AgentType.CODEX_SERVER_REMOTE, config
        )
        assert stale_reason is not None
        assert "session_id" not in result_config

    def test_stale_session_reason_mentions_expired(self) -> None:
        """Stale reason for expired session mentions 'expired'."""
        executor = _make_executor()
        old = _now_utc() - timedelta(minutes=200)
        config = {"session_id": "sess-exp", "session_created_at": _ts(old)}
        _, stale_reason = executor._prepare_codex_config(AgentType.CODEX_SERVER_REMOTE, config)
        assert stale_reason is not None
        assert "expired" in stale_reason

    def test_healthy_session_preserves_all_keys(self) -> None:
        """Healthy session: all config keys are preserved in returned config."""
        executor = _make_executor()
        recent = _now_utc() - timedelta(minutes=10)
        config = {
            "session_id": "sess-ok",
            "session_created_at": _ts(recent),
            "base_url": "https://codex.example.com",
            "model": "gpt-4o",
            "callback_channel": "rest",
        }
        result_config, stale_reason = executor._prepare_codex_config(
            AgentType.CODEX_SERVER_REMOTE, config
        )
        assert stale_reason is None
        assert result_config == config

    def test_stale_session_preserves_non_session_keys(self) -> None:
        """Stale session: non-session keys are preserved; session keys stripped."""
        executor = _make_executor()
        old = _now_utc() - timedelta(minutes=200)
        config = {
            "session_id": "sess-old",
            "session_created_at": _ts(old),
            "base_url": "https://codex.example.com",
            "model": "gpt-4o",
            "timeout": 300.0,
        }
        result_config, stale_reason = executor._prepare_codex_config(
            AgentType.CODEX_SERVER_REMOTE, config
        )
        assert stale_reason is not None
        assert result_config.get("base_url") == "https://codex.example.com"
        assert result_config.get("model") == "gpt-4o"
        assert result_config.get("timeout") == 300.0


# ===========================================================================
# check_agent_alive — CODEX_SERVER (local)
# ===========================================================================


class TestCheckAgentAliveCodexLocal:
    """AgentMonitor.check_agent_alive for CODEX_SERVER agent type."""

    @pytest.mark.asyncio
    async def test_codex_server_alive_pid(self, db_setup: async_sessionmaker[AsyncSession]) -> None:
        """CODEX_SERVER with a live PID → alive."""
        monitor = AgentMonitor(db_setup)
        run = _create_test_run(
            run_id="r1",
            agent_type=AgentType.CODEX_SERVER,
            agent_config={"pid": os.getpid()},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is True

    @pytest.mark.asyncio
    async def test_codex_server_dead_pid(self, db_setup: async_sessionmaker[AsyncSession]) -> None:
        """CODEX_SERVER with a dead PID → dead."""
        monitor = AgentMonitor(db_setup)
        run = _create_test_run(
            run_id="r2",
            agent_type=AgentType.CODEX_SERVER,
            agent_config={"pid": 999999},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is False

    @pytest.mark.asyncio
    async def test_codex_server_no_pid(self, db_setup: async_sessionmaker[AsyncSession]) -> None:
        """CODEX_SERVER with no PID in config → dead."""
        monitor = AgentMonitor(db_setup)
        run = _create_test_run(
            run_id="r3",
            agent_type=AgentType.CODEX_SERVER,
            agent_config={},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is False


# ===========================================================================
# check_agent_alive — CODEX_SERVER_REMOTE
# ===========================================================================


class TestCheckAgentAliveCodexRemote:
    """AgentMonitor.check_agent_alive for CODEX_SERVER_REMOTE agent type."""

    @pytest.mark.asyncio
    async def test_no_session_id_is_dead(self, db_setup: async_sessionmaker[AsyncSession]) -> None:
        """CODEX_SERVER_REMOTE with no session_id → dead."""
        monitor = AgentMonitor(db_setup)
        run = _create_test_run(
            run_id="r4",
            agent_type=AgentType.CODEX_SERVER_REMOTE,
            agent_config={"base_url": "https://codex.example.com"},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is False

    @pytest.mark.asyncio
    async def test_session_id_without_timestamp_is_alive(
        self, db_setup: async_sessionmaker[AsyncSession]
    ) -> None:
        """CODEX_SERVER_REMOTE with session_id but no timestamp → alive (assume healthy)."""
        monitor = AgentMonitor(db_setup)
        run = _create_test_run(
            run_id="r5",
            agent_type=AgentType.CODEX_SERVER_REMOTE,
            agent_config={"session_id": "sess-xyz"},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is True

    @pytest.mark.asyncio
    async def test_recent_session_is_alive(
        self, db_setup: async_sessionmaker[AsyncSession]
    ) -> None:
        """CODEX_SERVER_REMOTE with recent session_created_at → alive."""
        monitor = AgentMonitor(db_setup)
        recent = _now_utc() - timedelta(minutes=30)
        run = _create_test_run(
            run_id="r6",
            agent_type=AgentType.CODEX_SERVER_REMOTE,
            agent_config={"session_id": "sess-ok", "session_created_at": _ts(recent)},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is True

    @pytest.mark.asyncio
    async def test_expired_session_is_dead(
        self, db_setup: async_sessionmaker[AsyncSession]
    ) -> None:
        """CODEX_SERVER_REMOTE with old session_created_at → dead."""
        config = GlobalConfig(agents=AgentsConfig(codex_session_timeout_minutes=120))
        monitor = AgentMonitor(db_setup, global_config=config)
        old = _now_utc() - timedelta(minutes=200)
        run = _create_test_run(
            run_id="r7",
            agent_type=AgentType.CODEX_SERVER_REMOTE,
            agent_config={"session_id": "sess-old", "session_created_at": _ts(old)},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is False

    @pytest.mark.asyncio
    async def test_custom_timeout_within_range_is_alive(
        self, db_setup: async_sessionmaker[AsyncSession]
    ) -> None:
        """CODEX_SERVER_REMOTE session within custom timeout → alive."""
        config = GlobalConfig(agents=AgentsConfig(codex_session_timeout_minutes=60))
        monitor = AgentMonitor(db_setup, global_config=config)
        recent = _now_utc() - timedelta(minutes=30)
        run = _create_test_run(
            run_id="r8",
            agent_type=AgentType.CODEX_SERVER_REMOTE,
            agent_config={"session_id": "sess-ok", "session_created_at": _ts(recent)},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is True

    @pytest.mark.asyncio
    async def test_custom_timeout_beyond_range_is_dead(
        self, db_setup: async_sessionmaker[AsyncSession]
    ) -> None:
        """CODEX_SERVER_REMOTE session beyond custom timeout → dead."""
        config = GlobalConfig(agents=AgentsConfig(codex_session_timeout_minutes=10))
        monitor = AgentMonitor(db_setup, global_config=config)
        old = _now_utc() - timedelta(minutes=15)
        run = _create_test_run(
            run_id="r9",
            agent_type=AgentType.CODEX_SERVER_REMOTE,
            agent_config={"session_id": "sess-exp", "session_created_at": _ts(old)},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is False

    @pytest.mark.asyncio
    async def test_malformed_timestamp_is_dead(
        self, db_setup: async_sessionmaker[AsyncSession]
    ) -> None:
        """CODEX_SERVER_REMOTE with unparseable session_created_at → dead."""
        monitor = AgentMonitor(db_setup)
        run = _create_test_run(
            run_id="r10",
            agent_type=AgentType.CODEX_SERVER_REMOTE,
            agent_config={"session_id": "sess-bad", "session_created_at": "not-a-date"},
        )
        run.status = RunStatus.ACTIVE
        assert await monitor.check_agent_alive(run) is False


# ===========================================================================
# Dead-agent monitoring integration — on_agent_died for Codex variants
# ===========================================================================


@pytest.mark.asyncio
async def test_on_agent_died_codex_server_transitions_to_paused() -> None:
    """AgentMonitor.on_agent_died transitions a CODEX_SERVER run to PAUSED."""
    from orchestrator.db.connection import create_engine, create_session_factory, init_db
    from orchestrator.db.repositories import RunRepository

    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    try:
        monitor = AgentMonitor(session_factory)

        async with session_factory() as session:
            repo = RunRepository(session)
            run = _create_test_run(
                run_id="run-cs",
                agent_type=AgentType.CODEX_SERVER,
                agent_config={"pid": 999999},
            )
            run.status = RunStatus.ACTIVE
            await repo.save(run)
            await session.commit()

        await monitor.on_agent_died(
            run_id="run-cs",
            agent_type=AgentType.CODEX_SERVER,
            reason="local_codex_process_not_alive",
        )

        async with session_factory() as session:
            repo = RunRepository(session)
            updated = await repo.get("run-cs")
            assert updated.status == RunStatus.PAUSED
            assert updated.pause_reason == "local_codex_process_not_alive"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_on_agent_died_codex_server_remote_transitions_to_paused() -> None:
    """AgentMonitor.on_agent_died transitions a CODEX_SERVER_REMOTE run to PAUSED."""
    from orchestrator.db.connection import create_engine, create_session_factory, init_db
    from orchestrator.db.repositories import RunRepository

    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    try:
        monitor = AgentMonitor(session_factory)

        old = _now_utc() - timedelta(hours=3)
        async with session_factory() as session:
            repo = RunRepository(session)
            run = _create_test_run(
                run_id="run-csr",
                agent_type=AgentType.CODEX_SERVER_REMOTE,
                agent_config={"session_id": "sess-old", "session_created_at": _ts(old)},
            )
            run.status = RunStatus.ACTIVE
            await repo.save(run)
            await session.commit()

        await monitor.on_agent_died(
            run_id="run-csr",
            agent_type=AgentType.CODEX_SERVER_REMOTE,
            reason="remote_codex_session_expired",
        )

        async with session_factory() as session:
            repo = RunRepository(session)
            updated = await repo.get("run-csr")
            assert updated.status == RunStatus.PAUSED
            assert updated.pause_reason == "remote_codex_session_expired"
    finally:
        await engine.dispose()


# ===========================================================================
# Lifecycle: spawn_for_run includes both Codex variants
# ===========================================================================


def test_spawn_for_run_codex_server_returns_false_when_disabled() -> None:
    """spawn_for_run returns False when spawning is disabled for CODEX_SERVER."""
    executor = AgentExecutor(session_factory=None, spawn_agents=False)  # type: ignore[arg-type]
    spawned = executor.spawn_for_run("run-id", AgentType.CODEX_SERVER, {})
    assert spawned is False


def test_spawn_for_run_codex_server_remote_returns_false_when_disabled() -> None:
    """spawn_for_run returns False when spawning is disabled for CODEX_SERVER_REMOTE."""
    executor = AgentExecutor(session_factory=None, spawn_agents=False)  # type: ignore[arg-type]
    spawned = executor.spawn_for_run("run-id", AgentType.CODEX_SERVER_REMOTE, {})
    assert spawned is False


def test_is_running_returns_false_before_spawn() -> None:
    """is_running returns False for a run that has not been spawned."""
    executor = AgentExecutor(session_factory=None, spawn_agents=False)  # type: ignore[arg-type]
    assert executor.is_running("run-id") is False


def test_prepare_codex_config_is_idempotent_for_no_session() -> None:
    """Calling _prepare_codex_config twice with no session → same stable result."""
    executor = _make_executor()
    config = {"base_url": "https://codex.example.com"}
    r1, reason1 = executor._prepare_codex_config(AgentType.CODEX_SERVER_REMOTE, config)
    r2, reason2 = executor._prepare_codex_config(AgentType.CODEX_SERVER_REMOTE, r1)
    assert reason1 is None
    assert reason2 is None
    assert r1 == r2


def test_prepare_codex_config_stale_then_clean_is_idempotent() -> None:
    """After stripping stale session keys the cleaned config classifies as no-session."""
    executor = _make_executor()
    old = _now_utc() - timedelta(minutes=200)
    config = {"session_id": "sess-old", "session_created_at": _ts(old)}
    cleaned, reason = executor._prepare_codex_config(AgentType.CODEX_SERVER_REMOTE, config)
    assert reason is not None  # stale

    # Second pass on already-cleaned config should be stable (no session to classify).
    cleaned2, reason2 = executor._prepare_codex_config(AgentType.CODEX_SERVER_REMOTE, cleaned)
    assert reason2 is None
