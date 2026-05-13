"""Unit tests for pre-run health-check parsing and executor wiring."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, cast

from orchestrator.runners import (
    DEFAULT_HEALTH_CHECK_COMMAND,
    HealthCheckCommandResult,
    format_health_check_failure,
    format_health_check_timeout,
    parse_health_check_command,
)
from orchestrator.runners.executor import AgentRunnerExecutor


class RecordingHealthRunner:
    def __init__(self, result: HealthCheckCommandResult | BaseException) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, command: str, project_dir: str) -> HealthCheckCommandResult:
        self.calls.append((command, project_dir))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _executor(runner: RecordingHealthRunner) -> AgentRunnerExecutor:
    return AgentRunnerExecutor(
        session_factory=cast(Any, object()),
        health_check_runner=runner,
        spawn_agents=False,
    )


def test_parse_health_check_command_defaults_for_missing_or_invalid_config() -> None:
    assert parse_health_check_command(None) == DEFAULT_HEALTH_CHECK_COMMAND
    assert parse_health_check_command([]) == DEFAULT_HEALTH_CHECK_COMMAND
    assert parse_health_check_command({}) == DEFAULT_HEALTH_CHECK_COMMAND


def test_parse_health_check_command_accepts_string_and_null() -> None:
    assert parse_health_check_command({"test_command": "uv run pytest tests/unit"}) == (
        "uv run pytest tests/unit"
    )
    assert parse_health_check_command({"test_command": None}) is None
    assert parse_health_check_command({"test_command": 123}) == "123"


def test_format_health_check_failure_includes_command_exit_code_and_output() -> None:
    result = format_health_check_failure("exit 7", 7, "stdout\n", "stderr\n")
    assert "Pre-run health check failed." in result
    assert "Command: exit 7" in result
    assert "Exit code: 7" in result
    assert "stdout" in result
    assert "stderr" in result


def test_format_health_check_timeout_includes_command() -> None:
    assert format_health_check_timeout("slow-test") == (
        "Pre-run health check timed out.\nCommand: slow-test"
    )


async def test_executor_uses_configured_command_with_injected_runner(tmp_path: Path) -> None:
    task_world = tmp_path / ".task-world"
    task_world.mkdir()
    (task_world / "config.yaml").write_text("test_command: 'custom check'\n")
    runner = RecordingHealthRunner(HealthCheckCommandResult(returncode=0))

    result = await _executor(runner)._run_project_health_check(str(tmp_path))

    assert result is None
    assert runner.calls == [("custom check", str(tmp_path))]


async def test_executor_skips_when_command_is_null(tmp_path: Path) -> None:
    task_world = tmp_path / ".task-world"
    task_world.mkdir()
    (task_world / "config.yaml").write_text("test_command: null\n")
    runner = RecordingHealthRunner(HealthCheckCommandResult(returncode=0))

    result = await _executor(runner)._run_project_health_check(str(tmp_path))

    assert result is None
    assert runner.calls == []


async def test_executor_formats_runner_failure(tmp_path: Path) -> None:
    runner = RecordingHealthRunner(
        HealthCheckCommandResult(returncode=1, stdout="bad\n", stderr="worse\n")
    )

    result = await _executor(runner)._run_project_health_check(str(tmp_path))

    assert result is not None
    assert "uv run pytest" in result
    assert "Exit code: 1" in result
    assert "bad" in result
    assert "worse" in result


async def test_executor_formats_timeout(tmp_path: Path) -> None:
    runner = RecordingHealthRunner(subprocess.TimeoutExpired(cmd="slow", timeout=300))

    result = await _executor(runner)._run_project_health_check(str(tmp_path))

    assert result == f"Pre-run health check timed out.\nCommand: {DEFAULT_HEALTH_CHECK_COMMAND}"
