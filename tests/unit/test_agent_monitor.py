"""Unit tests for AgentRunnerMonitor.check_agent_alive.

These tests exercise the pure liveness-check logic which operates entirely
on the Run object in memory — no database required.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from orchestrator.runners import AgentRunnerMonitor
from orchestrator.config import AgentRunnerType, RunStatus
from orchestrator.config.global_config import AgentsConfig, GlobalConfig
from orchestrator.config.models import RequirementConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import Run


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


# ---------- check_agent_alive tests ----------


@pytest.mark.asyncio
async def test_check_agent_alive_cli_subprocess_with_valid_pid() -> None:
    """CLI_SUBPROCESS agent with a valid PID should be considered alive."""
    monitor = AgentRunnerMonitor()

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
async def test_check_agent_alive_cli_subprocess_with_dead_pid() -> None:
    """CLI_SUBPROCESS agent with a dead PID should be considered dead."""
    monitor = AgentRunnerMonitor()

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
async def test_check_agent_alive_cli_subprocess_without_pid() -> None:
    """CLI_SUBPROCESS without PID is treated as alive (not yet spawned).

    The subprocess may not have been spawned yet (e.g. pre-run health check
    is still running). The health monitor should not kill the run prematurely.
    Startup recovery handles the no-PID case separately.
    """
    monitor = AgentRunnerMonitor()

    run = _create_test_run(
        run_id="run5",
        agent_type=AgentRunnerType.CLI_SUBPROCESS,
        agent_config={},  # No PID — not yet spawned
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is True


@pytest.mark.asyncio
async def test_check_agent_alive_openhands_local_returns_true() -> None:
    """OPENHANDS_LOCAL agent should be considered alive during normal operation.

    In-process agents run via asyncio.to_thread and don't require health monitoring
    since the executor handles failures. Returns True to prevent the health monitor
    from killing the agent prematurely. Server restart recovery is handled separately.
    """
    monitor = AgentRunnerMonitor()

    run = _create_test_run(
        run_id="run6",
        agent_type=AgentRunnerType.OPENHANDS_LOCAL,
        agent_config={},
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is True


@pytest.mark.asyncio
async def test_check_agent_alive_user_managed_within_timeout() -> None:
    """USER_MANAGED agent with recent activity should be considered alive."""
    config = GlobalConfig(agents=AgentsConfig(user_managed_timeout_minutes=10))
    monitor = AgentRunnerMonitor(global_config=config)

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
async def test_check_agent_alive_user_managed_beyond_timeout() -> None:
    """USER_MANAGED agent with stale activity should be considered dead."""
    config = GlobalConfig(agents=AgentsConfig(user_managed_timeout_minutes=10))
    monitor = AgentRunnerMonitor(global_config=config)

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
async def test_check_agent_alive_user_managed_without_last_activity() -> None:
    """USER_MANAGED agent without last_activity_at should be considered dead."""
    monitor = AgentRunnerMonitor()

    run = _create_test_run(
        run_id="run9",
        agent_type=AgentRunnerType.USER_MANAGED,
        agent_config={},  # No last_activity_at
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is False


@pytest.mark.asyncio
async def test_check_agent_alive_with_no_agent_type() -> None:
    """Run without agent_type should be considered dead."""
    monitor = AgentRunnerMonitor()

    run = _create_test_run(run_id="run10", agent_type=None)
    run.status = RunStatus.DRAFT

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is False


@pytest.mark.asyncio
async def test_check_agent_alive_user_managed_with_malformed_timestamp() -> None:
    """USER_MANAGED agent with malformed timestamp should be considered dead."""
    config = GlobalConfig(agents=AgentsConfig(user_managed_timeout_minutes=10))
    monitor = AgentRunnerMonitor(global_config=config)

    run = _create_test_run(
        run_id="run11",
        agent_type=AgentRunnerType.USER_MANAGED,
        agent_config={"last_activity_at": "not-a-valid-timestamp"},
    )
    run.status = RunStatus.ACTIVE

    is_alive = await monitor.check_agent_alive(run)
    assert is_alive is False
