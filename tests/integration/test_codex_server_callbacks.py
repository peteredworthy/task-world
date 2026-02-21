"""Integration-level callback tests for Codex Server agents (local and remote).

Tests that the allow-listed callback tools are dispatched correctly and
identically across both agent variants (local CodexServerAgent and remote
CodexServerRemoteAgent) using real agent objects — no mocking.

This file provides the explicit integration target for:

    uv run pytest tests/integration/test_codex_server_callbacks.py -v

Auto-verify filter: codex_server and callbacks and (local or remote)
"""

from __future__ import annotations

import pytest

from orchestrator.agents.codex_server import CodexServerAgent
from orchestrator.agents.codex_server_common import CODEX_SERVER_TOOL_ALLOWLIST
from orchestrator.agents.codex_server_remote import CodexServerRemoteAgent
from orchestrator.agents.types import ExecutionContext
from orchestrator.config.enums import ChecklistStatus

# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------

_VALID_URL = "https://codex.example.com"
_VALID_KEY = "sk-integration-callback-test"  # pragma: allowlist secret

_CALLBACK_CHANNELS = ["rest", "mcp"]


def _local(channel: str = "rest") -> CodexServerAgent:
    return CodexServerAgent(callback_channel=channel)


def _remote(channel: str = "rest") -> CodexServerRemoteAgent:
    return CodexServerRemoteAgent(
        base_url=_VALID_URL,
        api_key=_VALID_KEY,
        callback_channel=channel,
        _environ={},
    )


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-int-callbacks",
        task_id="task-int-callbacks",
        working_dir="/tmp/int-callbacks",
        prompt="Integration callback test task.",
        requirements=["R-01: first requirement", "R-02: second requirement"],
    )


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


async def _noop_grade(req_id: str, grade: str, reason: str | None) -> None:
    pass


# ---------------------------------------------------------------------------
# Allow-list: common constant is the single source of truth
# ---------------------------------------------------------------------------


def test_integration_both_agents_share_single_allowlist_source() -> None:
    """Both agent types use the same shared CODEX_SERVER_TOOL_ALLOWLIST constant."""
    assert CodexServerAgent.TOOL_ALLOWLIST is CODEX_SERVER_TOOL_ALLOWLIST
    assert CodexServerRemoteAgent.TOOL_ALLOWLIST is CODEX_SERVER_TOOL_ALLOWLIST


def test_integration_allowlist_has_exactly_four_tools() -> None:
    """The canonical allow-list has exactly four v1 orchestrator callback tools."""
    assert len(CODEX_SERVER_TOOL_ALLOWLIST) == 4
    assert "update_checklist" in CODEX_SERVER_TOOL_ALLOWLIST
    assert "grade" in CODEX_SERVER_TOOL_ALLOWLIST
    assert "submit" in CODEX_SERVER_TOOL_ALLOWLIST
    assert "request_clarification" in CODEX_SERVER_TOOL_ALLOWLIST


# ---------------------------------------------------------------------------
# update_checklist: local and remote dispatch identically
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_local_update_checklist_done(channel: str) -> None:
    """Local agent: update_checklist with 'done' dispatches correctly for both channels."""
    agent = _local(channel)
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await agent._route_tool_call(
        "update_checklist",
        {"req_id": "R-01", "status": "done", "note": channel},
        capture,
        _noop_submit,
    )
    assert received == [ChecklistStatus.DONE]


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_remote_update_checklist_done(channel: str) -> None:
    """Remote agent: update_checklist with 'done' dispatches correctly for both channels."""
    agent = _remote(channel)
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await agent._route_tool_call(
        "update_checklist",
        {"req_id": "R-01", "status": "done", "note": channel},
        capture,
        _noop_submit,
    )
    assert received == [ChecklistStatus.DONE]


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_local_update_checklist_blocked(channel: str) -> None:
    """Local agent: 'blocked' status dispatched correctly."""
    agent = _local(channel)
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await agent._route_tool_call(
        "update_checklist",
        {"req_id": "R-01", "status": "blocked", "note": None},
        capture,
        _noop_submit,
    )
    assert received == [ChecklistStatus.BLOCKED]


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_remote_update_checklist_blocked(channel: str) -> None:
    """Remote agent: 'blocked' status dispatched correctly."""
    agent = _remote(channel)
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await agent._route_tool_call(
        "update_checklist",
        {"req_id": "R-01", "status": "blocked", "note": None},
        capture,
        _noop_submit,
    )
    assert received == [ChecklistStatus.BLOCKED]


# ---------------------------------------------------------------------------
# submit: local and remote dispatch identically
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_local_submit_dispatched(channel: str) -> None:
    """Local agent: submit callback fires for both channels."""
    agent = _local(channel)
    submitted: list[bool] = []

    async def capture() -> None:
        submitted.append(True)

    await agent._route_tool_call("submit", {}, _noop_checklist, capture)
    assert submitted == [True]


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_remote_submit_dispatched(channel: str) -> None:
    """Remote agent: submit callback fires for both channels."""
    agent = _remote(channel)
    submitted: list[bool] = []

    async def capture() -> None:
        submitted.append(True)

    await agent._route_tool_call("submit", {}, _noop_checklist, capture)
    assert submitted == [True]


# ---------------------------------------------------------------------------
# grade: dispatched in verifier phase, ignored in builder phase
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_local_grade_dispatched_verifier(channel: str) -> None:
    """Local agent: grade dispatched when on_grade is provided (verifier phase)."""
    agent = _local(channel)
    grades: list[tuple[str, str, str | None]] = []

    async def capture(req_id: str, grade: str, reason: str | None) -> None:
        grades.append((req_id, grade, reason))

    await agent._route_tool_call(
        "grade",
        {"req_id": "R-01", "grade": "A", "grade_reason": "Excellent"},
        _noop_checklist,
        _noop_submit,
        on_grade=capture,
    )
    assert grades == [("R-01", "A", "Excellent")]


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_remote_grade_dispatched_verifier(channel: str) -> None:
    """Remote agent: grade dispatched when on_grade is provided (verifier phase)."""
    agent = _remote(channel)
    grades: list[tuple[str, str, str | None]] = []

    async def capture(req_id: str, grade: str, reason: str | None) -> None:
        grades.append((req_id, grade, reason))

    await agent._route_tool_call(
        "grade",
        {"req_id": "R-01", "grade": "A", "grade_reason": "Excellent"},
        _noop_checklist,
        _noop_submit,
        on_grade=capture,
    )
    assert grades == [("R-01", "A", "Excellent")]


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_local_grade_no_op_in_builder(channel: str) -> None:
    """Local agent: grade is silently ignored (no error) in builder phase."""
    agent = _local(channel)
    await agent._route_tool_call(
        "grade",
        {"req_id": "R-01", "grade": "A"},
        _noop_checklist,
        _noop_submit,
        on_grade=None,
    )


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_remote_grade_no_op_in_builder(channel: str) -> None:
    """Remote agent: grade is silently ignored (no error) in builder phase."""
    agent = _remote(channel)
    await agent._route_tool_call(
        "grade",
        {"req_id": "R-01", "grade": "A"},
        _noop_checklist,
        _noop_submit,
        on_grade=None,
    )


# ---------------------------------------------------------------------------
# request_clarification: handled without error by both agents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_local_request_clarification_handled(channel: str) -> None:
    """Local agent: request_clarification is handled without raising."""
    agent = _local(channel)
    await agent._route_tool_call(
        "request_clarification",
        {"question": "What does R-01 require?"},
        _noop_checklist,
        _noop_submit,
    )


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_remote_request_clarification_handled(channel: str) -> None:
    """Remote agent: request_clarification is handled without raising."""
    agent = _remote(channel)
    await agent._route_tool_call(
        "request_clarification",
        {"question": "What does R-01 require?"},
        _noop_checklist,
        _noop_submit,
    )


# ---------------------------------------------------------------------------
# Allow-list enforcement: disallowed tools rejected before callbacks run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
@pytest.mark.parametrize(
    "disallowed_tool",
    ["bash", "read_file", "write_file", "execute_command", "shell", "SUBMIT", "GRADE", ""],
)
async def test_integration_local_rejects_disallowed_tool(
    channel: str, disallowed_tool: str
) -> None:
    """Local agent rejects any disallowed tool call for both channels."""
    agent = _local(channel)
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await agent._route_tool_call(disallowed_tool, {}, _noop_checklist, _noop_submit)


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
@pytest.mark.parametrize(
    "disallowed_tool",
    ["bash", "read_file", "write_file", "execute_command", "shell", "SUBMIT", "GRADE", ""],
)
async def test_integration_remote_rejects_disallowed_tool(
    channel: str, disallowed_tool: str
) -> None:
    """Remote agent rejects any disallowed tool call for both channels."""
    agent = _remote(channel)
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await agent._route_tool_call(disallowed_tool, {}, _noop_checklist, _noop_submit)


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_disallowed_tool_does_not_invoke_any_callback(
    channel: str,
) -> None:
    """Disallowed tool rejection precedes all callback invocations (both agents, both channels)."""
    checklist_called: list[bool] = []
    submit_called: list[bool] = []

    async def cb_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        checklist_called.append(True)

    async def cb_submit() -> None:
        submit_called.append(True)

    for agent in [_local(channel), _remote(channel)]:
        with pytest.raises(ValueError):
            await agent._route_tool_call("bash", {}, cb_checklist, cb_submit)

    assert checklist_called == [], "No checklist callback must fire on rejected tool"
    assert submit_called == [], "No submit callback must fire on rejected tool"


# ---------------------------------------------------------------------------
# Cross-agent parity: local and remote produce identical callback results
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_local_and_remote_update_checklist_parity(channel: str) -> None:
    """Local and remote agents produce identical update_checklist callback results."""
    local_received: list[tuple[str, ChecklistStatus, str | None]] = []
    remote_received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def local_capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        local_received.append((req_id, status, note))

    async def remote_capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        remote_received.append((req_id, status, note))

    args = {"req_id": "R-01", "status": "done", "note": f"parity-{channel}"}
    await _local(channel)._route_tool_call("update_checklist", args, local_capture, _noop_submit)
    await _remote(channel)._route_tool_call("update_checklist", args, remote_capture, _noop_submit)
    assert local_received == remote_received


@pytest.mark.parametrize("channel", _CALLBACK_CHANNELS)
async def test_integration_local_and_remote_grade_callback_parity(channel: str) -> None:
    """Local and remote agents produce identical grade callback results."""
    local_grades: list[tuple[str, str, str | None]] = []
    remote_grades: list[tuple[str, str, str | None]] = []

    async def local_capture(req_id: str, grade: str, reason: str | None) -> None:
        local_grades.append((req_id, grade, reason))

    async def remote_capture(req_id: str, grade: str, reason: str | None) -> None:
        remote_grades.append((req_id, grade, reason))

    args = {"req_id": "R-01", "grade": "A", "grade_reason": f"parity-{channel}"}
    await _local(channel)._route_tool_call(
        "grade", args, _noop_checklist, _noop_submit, on_grade=local_capture
    )
    await _remote(channel)._route_tool_call(
        "grade", args, _noop_checklist, _noop_submit, on_grade=remote_capture
    )
    assert local_grades == remote_grades
