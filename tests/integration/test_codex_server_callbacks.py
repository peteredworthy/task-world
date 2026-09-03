"""Integration-level callback tests for the local CodexServerAgent.

Tests that the allow-listed callback tools are dispatched correctly using
real agent objects — no mocking.

This file provides the explicit integration target for:

    uv run pytest tests/integration/test_codex_server_callbacks.py -v

Auto-verify filter: codex_server and callbacks and local
"""

from __future__ import annotations

import pytest

from orchestrator.runners import CodexServerAgent, SubmissionAcknowledgement
from orchestrator.runners import CODEX_SERVER_TOOL_ALLOWLIST
from orchestrator.runners.types import ExecutionContext
from orchestrator.config import ChecklistStatus

# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------


def _local() -> CodexServerAgent:
    return CodexServerAgent()


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


def test_integration_allowlist_has_expected_tools() -> None:
    """The canonical allow-list contains the expected v1 orchestrator callback tools."""
    assert "update_checklist" in CODEX_SERVER_TOOL_ALLOWLIST
    assert "grade" in CODEX_SERVER_TOOL_ALLOWLIST
    assert "submit" in CODEX_SERVER_TOOL_ALLOWLIST
    assert "request_clarification" in CODEX_SERVER_TOOL_ALLOWLIST
    assert "complete_recovery" in CODEX_SERVER_TOOL_ALLOWLIST


# ---------------------------------------------------------------------------
# update_checklist
# ---------------------------------------------------------------------------


async def test_integration_local_update_checklist_done() -> None:
    """Local agent: update_checklist with 'done' dispatches correctly."""
    agent = _local()
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await agent._route_tool_call(
        "update_checklist",
        {"req_id": "R-01", "status": "done", "note": None},
        capture,
        _noop_submit,
    )
    assert received == [ChecklistStatus.DONE]


async def test_integration_local_update_checklist_blocked() -> None:
    """Local agent: 'blocked' status dispatched correctly."""
    agent = _local()
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
# submit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("disposition", "message"),
    [
        ("rejected", "submission rejected: acceptance command failed"),
        ("durably_staged", "durably staged; pending runner completion and not yet accepted"),
        ("finalized_accepted", "submission is durably finalized and accepted"),
    ],
)
async def test_integration_local_submit_dispatched_with_three_way_acknowledgement(
    disposition: str,
    message: str,
) -> None:
    """Local agent returns the exact typed submission disposition."""
    agent = _local()
    submitted: list[bool] = []

    async def capture() -> SubmissionAcknowledgement:
        submitted.append(True)
        return SubmissionAcknowledgement.model_validate(
            {
                "disposition": disposition,
                "message": message,
                "execution_id": "execution-1",
                "graph_position": 12,
            }
        )

    result = await agent._route_tool_call("submit", {}, _noop_checklist, capture)
    assert submitted == [True]
    assert f'"disposition":"{disposition}"' in result
    assert message in result


# ---------------------------------------------------------------------------
# grade: dispatched in verifier phase, ignored in builder phase
# ---------------------------------------------------------------------------


async def test_integration_local_grade_dispatched_verifier() -> None:
    """Local agent: grade dispatched when on_grade is provided (verifier phase)."""
    agent = _local()
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


async def test_integration_local_grade_no_op_in_builder() -> None:
    """Local agent: grade is silently ignored (no error) in builder phase."""
    agent = _local()
    await agent._route_tool_call(
        "grade",
        {"req_id": "R-01", "grade": "A"},
        _noop_checklist,
        _noop_submit,
        on_grade=None,
    )


# ---------------------------------------------------------------------------
# request_clarification
# ---------------------------------------------------------------------------


async def test_integration_local_request_clarification_handled() -> None:
    """Local agent: request_clarification is handled without raising."""
    agent = _local()
    await agent._route_tool_call(
        "request_clarification",
        {"question": "What does R-01 require?"},
        _noop_checklist,
        _noop_submit,
    )


# ---------------------------------------------------------------------------
# Allow-list enforcement: disallowed tools rejected before callbacks run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "disallowed_tool",
    ["bash", "read_file", "write_file", "execute_command", "shell", "SUBMIT", "GRADE", ""],
)
async def test_integration_local_rejects_disallowed_tool(disallowed_tool: str) -> None:
    """Local agent rejects any disallowed tool call."""
    agent = _local()
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await agent._route_tool_call(disallowed_tool, {}, _noop_checklist, _noop_submit)


async def test_integration_disallowed_tool_does_not_invoke_any_callback() -> None:
    """Disallowed tool rejection precedes all callback invocations."""
    checklist_called: list[bool] = []
    submit_called: list[bool] = []

    async def cb_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        checklist_called.append(True)

    async def cb_submit() -> None:
        submit_called.append(True)

    with pytest.raises(ValueError):
        await _local()._route_tool_call("bash", {}, cb_checklist, cb_submit)

    assert checklist_called == [], "No checklist callback must fire on rejected tool"
    assert submit_called == [], "No submit callback must fire on rejected tool"
