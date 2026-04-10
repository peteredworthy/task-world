"""Tests for ``CodexServerAgent``: builder/verifier × REST/MCP channels.

Covers all four cells of the 2×2 matrix for ``CodexServerAgent`` (local):

    ┌─────────────────┬───────────────┬───────────────┐
    │                 │ callback=REST │ callback=MCP  │
    ├─────────────────┼───────────────┼───────────────┤
    │ builder phase   │     (1)       │     (2)       │
    │ verifier phase  │     (3)       │     (4)       │
    └─────────────────┴───────────────┴───────────────┘

Asserts:
- ``TOOL_ALLOWLIST`` matches the canonical constant.
- Builder-phase prompt structure is correct regardless of channel.
- Verifier-phase prompt structure is correct regardless of channel.
- ``_route_tool_call`` dispatches callbacks correctly in all four matrix cells.
"""

from __future__ import annotations

import pytest

from orchestrator.runners import CodexServerAgent
from orchestrator.runners import CODEX_SERVER_TOOL_ALLOWLIST
from orchestrator.runners.types import ExecutionContext
from orchestrator.config import ChecklistStatus

# ---------------------------------------------------------------------------
# Test fixtures / constants
# ---------------------------------------------------------------------------

_CALLBACK_CHANNELS = ["rest", "mcp"]


def _local_agent(callback_channel: str = "rest") -> CodexServerAgent:
    return CodexServerAgent(callback_channel=callback_channel)


def _ctx(
    prompt: str = "Do the task.",
    requirements: list[str] | None = None,
    api_base_url: str | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-parity",
        task_id="task-parity",
        working_dir="/tmp/parity",
        prompt=prompt,
        requirements=requirements or ["R-01: requirement one", "R-02: requirement two"],
        api_base_url=api_base_url,
    )


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


async def _noop_grade(req_id: str, grade: str, reason: str | None) -> None:
    pass


# ===========================================================================
# 1. Allow-list: local agent
# ===========================================================================


def test_local_allowlist_matches_common_constant() -> None:
    """Local agent allow-list must equal the canonical CODEX_SERVER_TOOL_ALLOWLIST."""
    assert CodexServerAgent.TOOL_ALLOWLIST == CODEX_SERVER_TOOL_ALLOWLIST


def test_allowlist_contains_expected_tools() -> None:
    """v1 allow-list contains the expected orchestrator callback tools."""
    expected = frozenset(
        {"update_checklist", "grade", "submit", "request_clarification", "complete_recovery"}
    )
    assert CodexServerAgent.TOOL_ALLOWLIST == expected


# ===========================================================================
# 2. Prompt parity: builder phase (cells 1 & 2)
# ===========================================================================


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
def test_local_builder_prompt_contains_update_checklist_rest_mcp(channel: str) -> None:
    """Local agent builder prompt has update_checklist for both REST and MCP."""
    prompt = _local_agent(channel)._build_prompt(_ctx(), is_verifier=False)
    assert "update_checklist" in prompt


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
def test_local_builder_prompt_excludes_grade_instructions_rest_mcp(channel: str) -> None:
    """Local agent builder prompt excludes verifier-only grading instructions."""
    prompt = _local_agent(channel)._build_prompt(_ctx(), is_verifier=False)
    assert "Grade EVERY requirement" not in prompt


# ===========================================================================
# 3. Prompt parity: verifier phase (cells 3 & 4)
# ===========================================================================


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
def test_local_verifier_prompt_contains_grade_tool_rest_mcp(channel: str) -> None:
    """Local agent verifier prompt mentions grade for both REST and MCP."""
    prompt = _local_agent(channel)._build_prompt(_ctx(), is_verifier=True)
    assert "grade" in prompt


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
def test_local_verifier_prompt_contains_grading_workflow_rest_mcp(channel: str) -> None:
    """Local agent verifier prompt includes grading workflow instructions."""
    prompt = _local_agent(channel)._build_prompt(_ctx(), is_verifier=True)
    assert "Grade EVERY requirement" in prompt


# ===========================================================================
# 4. Callback dispatch: all four matrix cells
# ===========================================================================


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_local_update_checklist_dispatched_builder_rest_mcp(channel: str) -> None:
    """Cell (1,2): local agent dispatches update_checklist in builder phase."""
    agent = _local_agent(callback_channel=channel)
    received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append((req_id, status, note))

    await agent._route_tool_call(
        tool_name="update_checklist",
        args={"req_id": "R-01", "status": "done", "note": channel},
        on_checklist_update=capture,
        on_submit=_noop_submit,
    )
    assert received == [("R-01", ChecklistStatus.DONE, channel)]


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_local_grade_dispatched_verifier_rest_mcp(channel: str) -> None:
    """Cell (3,4): local agent dispatches grade in verifier phase."""
    agent = _local_agent(callback_channel=channel)
    grades: list[tuple[str, str, str | None]] = []

    async def capture(req_id: str, grade: str, reason: str | None) -> None:
        grades.append((req_id, grade, reason))

    await agent._route_tool_call(
        tool_name="grade",
        args={"req_id": "R-01", "grade": "A", "grade_reason": channel},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=capture,
    )
    assert grades == [("R-01", "A", channel)]


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_local_submit_dispatched_builder_rest_mcp(channel: str) -> None:
    """Local agent: submit dispatches correctly in builder phase for both channels."""
    agent = _local_agent(callback_channel=channel)
    submitted: list[bool] = []

    async def capture() -> None:
        submitted.append(True)

    await agent._route_tool_call(
        tool_name="submit",
        args={},
        on_checklist_update=_noop_checklist,
        on_submit=capture,
    )
    assert submitted == [True]


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_local_request_clarification_handled_rest_mcp(channel: str) -> None:
    """Local agent: request_clarification does not raise for both channels."""
    agent = _local_agent(callback_channel=channel)
    await agent._route_tool_call(
        tool_name="request_clarification",
        args={"question": "What does R-01 require?"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )


# ===========================================================================
# 5. Allow-list enforcement: disallowed tools rejected in all four cells
# ===========================================================================


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
@pytest.mark.parametrize(
    "disallowed_tool",
    ["bash", "read_file", "write_file", "execute_command", "shell", "SUBMIT", "GRADE", ""],
)
async def test_local_rejects_disallowed_tools_rest_mcp(channel: str, disallowed_tool: str) -> None:
    """Local agent rejects disallowed tools for both REST and MCP."""
    agent = _local_agent(callback_channel=channel)
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await agent._route_tool_call(
            tool_name=disallowed_tool,
            args={},
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_disallowed_tool_does_not_invoke_checklist_callback_rest_mcp(
    channel: str,
) -> None:
    """Disallowed tool rejection precedes any callback invocation (both channels)."""
    called: list[bool] = []

    async def should_not_be_called(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        called.append(True)

    with pytest.raises(ValueError):
        await _local_agent(channel)._route_tool_call(
            tool_name="bash",
            args={},
            on_checklist_update=should_not_be_called,
            on_submit=_noop_submit,
        )
    assert called == []
