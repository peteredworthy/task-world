"""Pure helpers for executor pre-run health checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

DEFAULT_HEALTH_CHECK_COMMAND = "uv run pytest --tb=no -q"


@dataclass(frozen=True)
class HealthCheckCommandResult:
    """Result of executing a configured project health-check command."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


def parse_health_check_command(config_data: Any) -> str | None:
    """Return the configured health-check command from parsed YAML data.

    Missing or malformed configs use the convention default. ``test_command:
    null`` intentionally disables the check.
    """
    if not isinstance(config_data, dict) or "test_command" not in config_data:
        return DEFAULT_HEALTH_CHECK_COMMAND
    data = cast(dict[str, Any], config_data)
    raw = data["test_command"]
    return str(raw) if raw is not None else None


def format_health_check_failure(
    command: str,
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> str:
    """Format a non-zero health-check result for run pause messages."""
    output = (stdout + stderr).strip()
    return (
        "Pre-run health check failed.\n"
        f"Command: {command}\n"
        f"Exit code: {returncode}\n"
        f"Output:\n{output}"
    )


def format_health_check_timeout(command: str) -> str:
    """Format a health-check timeout message."""
    return f"Pre-run health check timed out.\nCommand: {command}"
