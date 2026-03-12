"""Tests for the pre-run health check in AgentRunnerExecutor.

All four scenarios call ``_run_project_health_check`` directly — no background
executor loop, no polling, no sleeps.  The method is a pure
"config → subprocess → result" function, so we only need to verify its return
value for each config variant.

Covers four scenarios:
1. Failing test_command → returns error string with command, exit code, output
2. Passing test_command → returns None (success)
3. test_command: null → returns None (skipped)
4. No .task-world/config.yaml → falls back to default command
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestrator.runners.executor import AgentRunnerExecutor


@pytest.fixture
def executor() -> AgentRunnerExecutor:
    # _run_project_health_check doesn't touch the DB, so a mock session_factory suffices.
    return AgentRunnerExecutor(session_factory=MagicMock(), spawn_agents=False)


# ---------------------------------------------------------------------------
# Scenario 1: Failing test_command returns error details
# ---------------------------------------------------------------------------


async def test_failing_tests_block_task_start(
    executor: AgentRunnerExecutor,
    tmp_path: Path,
) -> None:
    """When test_command exits non-zero, _run_project_health_check returns an error."""
    task_world = tmp_path / ".task-world"
    task_world.mkdir()
    (task_world / "config.yaml").write_text("test_command: 'exit 1'\n")

    result = await executor._run_project_health_check(str(tmp_path))

    assert result is not None, "Expected error string when test_command fails"
    assert "health check failed" in result.lower()
    assert "exit 1" in result


# ---------------------------------------------------------------------------
# Scenario 2: Passing test_command returns None
# ---------------------------------------------------------------------------


async def test_passing_tests_allow_task_start(
    executor: AgentRunnerExecutor,
    tmp_path: Path,
) -> None:
    """When test_command exits 0, _run_project_health_check returns None."""
    task_world = tmp_path / ".task-world"
    task_world.mkdir()
    (task_world / "config.yaml").write_text("test_command: 'true'\n")

    result = await executor._run_project_health_check(str(tmp_path))

    assert result is None, (
        f"Expected None (health check passed) when test_command succeeds, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: test_command: null skips the health check
# ---------------------------------------------------------------------------


async def test_null_test_command_skips_health_check(
    executor: AgentRunnerExecutor,
    tmp_path: Path,
) -> None:
    """When test_command is null the health check is skipped entirely."""
    task_world = tmp_path / ".task-world"
    task_world.mkdir()
    (task_world / "config.yaml").write_text("test_command: null\n")

    result = await executor._run_project_health_check(str(tmp_path))

    assert result is None, (
        f"Expected None (health check skipped) when test_command is null, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 4: No .task-world/config.yaml → default convention command used
# ---------------------------------------------------------------------------


async def test_no_config_file_uses_default_command(
    executor: AgentRunnerExecutor,
    tmp_path: Path,
) -> None:
    """When .task-world/config.yaml is absent the default 'uv run pytest --tb=no -q' is used."""
    assert not (tmp_path / ".task-world" / "config.yaml").exists()

    result = await executor._run_project_health_check(str(tmp_path))

    assert result is not None, (
        "Expected a non-None error when default pytest fails on empty directory"
    )
    assert "uv run pytest" in result, (
        f"Error message should include the default command 'uv run pytest', got: {result!r}"
    )
