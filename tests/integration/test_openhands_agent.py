"""Integration tests for OpenHands agent.

Error-path tests that only need the SDK installed run here. Live execution
coverage that requires OPENAI_API_KEY lives in tests/slow.

LocalConversation runs entirely in-process — no remote server required.
"""

import os

import pytest

from orchestrator.runners.errors import AgentNotAvailableError
from orchestrator.runners import OpenHandsAgent, _SDK_AVAILABLE  # pyright: ignore[reportPrivateUsage]
from orchestrator.runners.types import ExecutionContext
from orchestrator.config import ChecklistStatus


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
    """check_health still returns True without API key (local LLM supported)."""
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        agent = OpenHandsAgent(api_key="")
        # API key is not required when using a local LLM
        assert await agent.check_health() == _SDK_AVAILABLE
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved
