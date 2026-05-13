"""Slow CLIAgent checks against real external CLI agents.

These are not E2E tests: they exercise one runner against real Claude/Codex
CLI binaries, without a running orchestrator server.
"""

import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from orchestrator.config import ChecklistStatus
from orchestrator.config.models import NudgerConfig
from orchestrator.runners import CLIAgent
from orchestrator.runners.types import ChecklistUpdateCallback, ExecutionContext, SubmitCallback

_needs_claude = pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not found")
_needs_codex = pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not found")


def _make_context(working_dir: str, prompt: str = "hello") -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir=working_dir,
        prompt=prompt,
        requirements=["R1"],
    )


def _noop_callbacks() -> tuple[ChecklistUpdateCallback, SubmitCallback]:
    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        pass

    return on_update, on_submit


@pytest.mark.slow
@pytest.mark.timeout(120)
@_needs_claude
async def test_claude_creates_file(tmp_path: Path) -> None:
    """Claude CLI creates a file when asked."""
    agent = CLIAgent(
        command="claude",
        model="claude-haiku-4-5-20251001",
        args=[
            "-p",
            "--dangerously-skip-permissions",
            f"Create a file called hello.txt in {tmp_path} with the content 'hello from claude'. "
            "Do not output anything else.",
        ],
        nudger_config=NudgerConfig(output_timeout=timedelta(seconds=120)),
    )
    on_update, on_submit = _noop_callbacks()

    result = await agent.execute(_make_context(working_dir=str(tmp_path)), on_update, on_submit)

    assert result.success is True
    assert (tmp_path / "hello.txt").exists()


@pytest.mark.slow
@pytest.mark.timeout(120)
@_needs_codex
async def test_codex_creates_file(tmp_path: Path) -> None:
    """Codex CLI creates a file when asked."""
    agent = CLIAgent(
        command="codex",
        model="gpt-5.2-codex",
        args=[
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            f"Create a file called hello.txt in {tmp_path} with the content 'hello from codex'. "
            "Do not output anything else.",
        ],
        nudger_config=NudgerConfig(output_timeout=timedelta(seconds=120)),
    )
    on_update, on_submit = _noop_callbacks()

    result = await agent.execute(_make_context(working_dir=str(tmp_path)), on_update, on_submit)

    assert result.success is True
    assert (tmp_path / "hello.txt").exists()


@pytest.mark.slow
@pytest.mark.timeout(120)
@_needs_claude
async def test_claude_simple_output(tmp_path: Path) -> None:
    """Claude CLI prints a specific string when asked."""
    agent = CLIAgent(
        command="claude",
        model="claude-haiku-4-5-20251001",
        args=[
            "-p",
            "--dangerously-skip-permissions",
            "Print exactly the text 'ORCHESTRATOR_TEST_OK' and nothing else.",
        ],
        nudger_config=NudgerConfig(output_timeout=timedelta(seconds=120)),
    )
    on_update, on_submit = _noop_callbacks()

    result = await agent.execute(_make_context(working_dir=str(tmp_path)), on_update, on_submit)

    assert result.success is True
