"""Integration tests for OpenHands agent.

Tests that require OPENAI_API_KEY are marked with the conditional skip.
Error-path tests that only need the SDK installed run unconditionally.

LocalConversation runs entirely in-process — no remote server required.
"""

import os
from pathlib import Path

import pytest

from orchestrator.agents.errors import AgentNotAvailableError
from orchestrator.agents.openhands import OpenHandsAgent
from orchestrator.agents.types import ExecutionContext
from orchestrator.config.enums import ChecklistStatus


def _make_context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="test",
        requirements=["R1"],
    )


async def _noop_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


_needs_api_key = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="No OPENAI_API_KEY",
)


# --- Error-path tests (SDK installed, no server needed) ---


async def test_openhands_missing_api_key_raises() -> None:
    """Missing API key raises AgentNotAvailableError."""
    # Temporarily remove OPENAI_API_KEY so the fallback in __init__ also
    # returns empty (api_key="" is falsy, so it falls back to os.environ).
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        agent = OpenHandsAgent(api_key="")

        with pytest.raises(AgentNotAvailableError, match="OPENAI_API_KEY"):
            await agent.execute(_make_context(), _noop_update, _noop_submit)
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved


async def test_openhands_health_check_no_api_key() -> None:
    """check_health returns False when no API key is set."""
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        agent = OpenHandsAgent(api_key="")
        assert await agent.check_health() is False
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved


# --- Real execution test (requires API key, no server) ---


@pytest.mark.slow
@pytest.mark.timeout(120)
@_needs_api_key
async def test_openhands_executes_file_creation(tmp_path: Path) -> None:
    """OpenHands agent creates a file and uses orchestrator tools.

    Uses LocalConversation which runs in-process — only needs OPENAI_API_KEY.

    Verifies:
    - Agent creates the requested file
    - Agent calls update_checklist to mark requirement as done
    - Agent calls submit when finished
    """
    agent = OpenHandsAgent(max_iterations=30, llm_config={"reasoning_effort": "low"})

    updates: list[tuple[str, ChecklistStatus, str | None]] = []
    submitted = False

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        updates.append((req_id, status, note))

    async def on_submit() -> None:
        nonlocal submitted
        submitted = True

    ctx = ExecutionContext(
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

    result = await agent.execute(ctx, on_update, on_submit)

    # Verify execution succeeded
    assert result.success is True

    # Verify file was created
    assert (tmp_path / "test_output.txt").exists()

    # Verify orchestrator tools were called
    assert len(updates) >= 1, "Agent should have called update_checklist at least once"
    assert any(status == ChecklistStatus.DONE for _, status, _ in updates), (
        f"Agent should have marked a requirement as done, got: {updates}"
    )

    assert submitted is True, "Agent should have called submit when finished"
