"""Thin integration coverage for executor health-check command execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from orchestrator.runners.executor import AgentRunnerExecutor


async def test_health_check_runs_configured_shell_command(tmp_path: Path) -> None:
    task_world = tmp_path / ".task-world"
    task_world.mkdir()
    (task_world / "config.yaml").write_text("test_command: 'true'\n")
    executor = AgentRunnerExecutor(session_factory=cast(Any, object()), spawn_agents=False)

    result = await executor._run_project_health_check(str(tmp_path))

    assert result is None
