"""Slow OpenHands execution test against the real LLM API.

This is not E2E: LocalConversation runs in-process and no orchestrator server
is started. It is split from the normal integration suite because it depends on
external credentials and can take close to the test timeout.
"""

import asyncio
import os
import re
from pathlib import Path

import pytest

from orchestrator.config import ChecklistStatus
from orchestrator.runners import OpenHandsAgent
from orchestrator.runners.errors import AgentExecutionError
from orchestrator.runners.types import ExecutionContext

_SKIP_PATTERNS = re.compile(
    r"insufficient_quota|rate.?limit|billing|exceeded.*quota"
    r"|connection.?error|connect.?timeout|name.?resolution"
    r"|api.?key.*invalid|auth.*error|unauthorized",
    re.IGNORECASE,
)
_needs_api_key = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="No OPENAI_API_KEY",
)


@pytest.mark.slow
@pytest.mark.timeout(120)
@_needs_api_key
async def test_openhands_executes_file_creation(tmp_path: Path) -> None:
    """OpenHands creates a file and calls orchestrator callbacks."""
    agent = OpenHandsAgent(
        max_iterations=30,
        llm_config={"reasoning_effort": "low", "num_retries": 2, "retry_min_wait": 1},
    )

    updates: list[tuple[str, ChecklistStatus, str | None]] = []
    submitted = False

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        updates.append((req_id, status, note))

    async def on_submit() -> None:
        nonlocal submitted
        submitted = True

    context = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir=str(tmp_path),
        prompt=(
            "Create a file called test_output.txt containing the text "
            "'OpenHands was here'.\n\n"
            "After creating the file, you MUST:\n"
            "1. Call update_checklist with req_id='Create test_output.txt' and status='done'\n"
            "2. Call submit to indicate you are finished"
        ),
        requirements=["Create test_output.txt"],
    )

    try:
        result = await asyncio.wait_for(
            agent.execute(context, on_update, on_submit),
            timeout=90,
        )
    except (AgentExecutionError, asyncio.TimeoutError) as exc:
        msg = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, asyncio.TimeoutError):
            pytest.skip("LLM API unavailable: agent execution timed out")
        if _SKIP_PATTERNS.search(msg):
            pytest.skip(f"LLM API unavailable: {msg}")
        raise
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        if _SKIP_PATTERNS.search(msg):
            pytest.skip(f"LLM API unavailable: {msg}")
        raise

    assert result.success is True
    assert (tmp_path / "test_output.txt").exists()
    assert any(status == ChecklistStatus.DONE for _, status, _ in updates)
    assert submitted is True
