"""Auto-verification command execution and evaluation."""

import asyncio
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from orchestrator.config.models import AutoVerifyConfig


class AutoVerifyResult(BaseModel):
    """Result of running a single auto-verify command."""

    item_id: str
    cmd: str
    passed: bool
    exit_code: int
    output: str  # last N lines (tail_lines from config)


class AutoVerifyRunner(Protocol):
    """Protocol for running auto-verify commands."""

    async def run_command(self, cmd: str, cwd: Path, tail_lines: int) -> tuple[int, str]: ...


class LocalAutoVerifyRunner:
    """Run auto-verify commands locally via subprocess."""

    async def run_command(self, cmd: str, cwd: Path, tail_lines: int) -> tuple[int, str]:
        """Execute command and return (exit_code, last N lines of output)."""
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        # Take last N lines
        lines = output.splitlines()
        tail = "\n".join(lines[-tail_lines:]) if len(lines) > tail_lines else output
        return proc.returncode or 0, tail


def _resolve_variables(template: str, variables: dict[str, Any]) -> str:
    """Resolve {{variable}} placeholders in a template string."""
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


async def run_auto_verify(
    config: AutoVerifyConfig,
    runner: AutoVerifyRunner,
    cwd: Path,
    variables: dict[str, Any] | None = None,
) -> list[AutoVerifyResult]:
    """Run all auto-verify commands and collect results."""
    results: list[AutoVerifyResult] = []
    for item in config.items:
        cmd = _resolve_variables(item.cmd, variables) if variables else item.cmd
        exit_code, output = await runner.run_command(cmd, cwd, config.tail_lines)
        results.append(
            AutoVerifyResult(
                item_id=item.id,
                cmd=cmd,
                passed=(exit_code == 0),
                exit_code=exit_code,
                output=output,
            )
        )
    return results


def evaluate_auto_verify(
    config: AutoVerifyConfig,
    results: list[AutoVerifyResult],
) -> tuple[bool, list[str]]:
    """Evaluate auto-verify results. Pure function.

    Returns (all_must_passed, list_of_failing_must_item_ids).
    Only items with must=True cause failure.
    """
    must_items = {item.id for item in config.items if item.must}
    failures: list[str] = []
    for result in results:
        if not result.passed and result.item_id in must_items:
            failures.append(result.item_id)
    return (len(failures) == 0, failures)
