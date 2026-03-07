"""Callback-specific tests for CodexServerAgent.

Tests that the allow-listed callback tools are dispatched correctly and that
disallowed tool invocations are rejected before any callback is invoked.

Filter: pytest -k 'codex_server and callbacks'
"""

from __future__ import annotations

import pytest

from orchestrator.runners.codex_server import CodexServerAgent
from orchestrator.runners.types import ExecutionContext
from orchestrator.config.enums import ChecklistStatus


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-cb",
        task_id="task-cb",
        working_dir="/tmp/cb",
        prompt="Run callbacks.",
        requirements=["R-01: do a thing"],
    )


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


# ---------------------------------------------------------------------------
# Allow-listed callbacks are dispatched correctly
# ---------------------------------------------------------------------------


async def test_codex_server_callbacks_update_checklist_dispatched() -> None:
    """update_checklist callback is invoked with correct args."""
    agent = CodexServerAgent()
    received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append((req_id, status, note))

    await agent._route_tool_call(
        tool_name="update_checklist",
        args={"req_id": "R-01", "status": "done", "note": "finished"},
        on_checklist_update=capture,
        on_submit=_noop_submit,
    )
    assert received == [("R-01", ChecklistStatus.DONE, "finished")]


async def test_codex_server_callbacks_update_checklist_blocked_status() -> None:
    """update_checklist dispatches BLOCKED status correctly."""
    agent = CodexServerAgent()
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await agent._route_tool_call(
        tool_name="update_checklist",
        args={"req_id": "R-01", "status": "blocked", "note": None},
        on_checklist_update=capture,
        on_submit=_noop_submit,
    )
    assert received == [ChecklistStatus.BLOCKED]


async def test_codex_server_callbacks_update_checklist_not_applicable_status() -> None:
    """update_checklist dispatches NOT_APPLICABLE status correctly."""
    agent = CodexServerAgent()
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await agent._route_tool_call(
        tool_name="update_checklist",
        args={"req_id": "R-01", "status": "not_applicable", "note": "N/A"},
        on_checklist_update=capture,
        on_submit=_noop_submit,
    )
    assert received == [ChecklistStatus.NOT_APPLICABLE]


async def test_codex_server_callbacks_submit_dispatched() -> None:
    """submit callback is invoked when submit tool is called."""
    agent = CodexServerAgent()
    submitted: list[bool] = []

    async def capture_submit() -> None:
        submitted.append(True)

    await agent._route_tool_call(
        tool_name="submit",
        args={},
        on_checklist_update=_noop_checklist,
        on_submit=capture_submit,
    )
    assert submitted == [True]


async def test_codex_server_callbacks_grade_dispatched_in_verifier_phase() -> None:
    """grade callback is invoked in verifier phase (on_grade provided)."""
    agent = CodexServerAgent()
    grades: list[tuple[str, str, str | None]] = []

    async def capture_grade(req_id: str, grade: str, reason: str | None) -> None:
        grades.append((req_id, grade, reason))

    await agent._route_tool_call(
        tool_name="grade",
        args={"req_id": "R-01", "grade": "A", "grade_reason": "Excellent work"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=capture_grade,
    )
    assert grades == [("R-01", "A", "Excellent work")]


async def test_codex_server_callbacks_grade_ignored_in_builder_phase() -> None:
    """grade tool call is silently ignored when on_grade is None (builder phase)."""
    agent = CodexServerAgent()
    # No error should be raised; grade is a no-op in builder phase.
    await agent._route_tool_call(
        tool_name="grade",
        args={"req_id": "R-01", "grade": "B"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=None,
    )


async def test_codex_server_callbacks_request_clarification_does_not_raise() -> None:
    """request_clarification is allow-listed and handled without error."""
    agent = CodexServerAgent()
    await agent._route_tool_call(
        tool_name="request_clarification",
        args={"question": "What does R-01 require exactly?"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )


# ---------------------------------------------------------------------------
# Disallowed tool invocations are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "disallowed_tool",
    [
        "bash",
        "read_file",
        "write_file",
        "execute_command",
        "delete_file",
        "shell",
        "list_files",
        "arbitrary_tool",
        "",
        "SUBMIT",
        "UPDATE_CHECKLIST",
        "GRADE",
    ],
)
async def test_codex_server_callbacks_disallowed_tool_raises_value_error(
    disallowed_tool: str,
) -> None:
    """Disallowed tool invocations raise ValueError with allow-list message."""
    agent = CodexServerAgent()
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await agent._route_tool_call(
            tool_name=disallowed_tool,
            args={},
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


async def test_codex_server_callbacks_disallowed_tool_does_not_invoke_checklist_callback() -> None:
    """Disallowed tool call raises before the checklist callback is invoked."""
    agent = CodexServerAgent()
    called: list[bool] = []

    async def should_not_be_called(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        called.append(True)

    with pytest.raises(ValueError):
        await agent._route_tool_call(
            tool_name="bash",
            args={"command": "echo hi"},
            on_checklist_update=should_not_be_called,
            on_submit=_noop_submit,
        )
    assert called == [], "Disallowed tool must not trigger checklist callback"


async def test_codex_server_callbacks_disallowed_tool_does_not_invoke_submit_callback() -> None:
    """Disallowed tool call raises before the submit callback is invoked."""
    agent = CodexServerAgent()
    called: list[bool] = []

    async def should_not_be_called() -> None:
        called.append(True)

    with pytest.raises(ValueError):
        await agent._route_tool_call(
            tool_name="delete_file",
            args={"path": "/tmp/test"},
            on_checklist_update=_noop_checklist,
            on_submit=should_not_be_called,
        )
    assert called == [], "Disallowed tool must not trigger submit callback"


async def test_codex_server_callbacks_disallowed_tool_does_not_invoke_grade_callback() -> None:
    """Disallowed tool call raises before the grade callback is invoked."""
    agent = CodexServerAgent()
    called: list[bool] = []

    async def should_not_be_called(req_id: str, grade: str, reason: str | None) -> None:
        called.append(True)

    with pytest.raises(ValueError):
        await agent._route_tool_call(
            tool_name="write_file",
            args={"path": "/tmp/x", "content": "y"},
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
            on_grade=should_not_be_called,
        )
    assert called == [], "Disallowed tool must not trigger grade callback"


# ---------------------------------------------------------------------------
# Builder vs verifier phase — only allow-listed tools accepted in both
# ---------------------------------------------------------------------------


async def test_codex_server_callbacks_builder_phase_accepts_update_checklist() -> None:
    """Builder phase: update_checklist is allowed and dispatched."""
    agent = CodexServerAgent()
    received: list[bool] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(True)

    await agent._route_tool_call(
        tool_name="update_checklist",
        args={"req_id": "R-01", "status": "done"},
        on_checklist_update=capture,
        on_submit=_noop_submit,
        on_grade=None,  # builder phase
    )
    assert received == [True]


async def test_codex_server_callbacks_verifier_phase_accepts_grade() -> None:
    """Verifier phase: grade is allowed and dispatched when on_grade is set."""
    agent = CodexServerAgent()
    received: list[bool] = []

    async def capture_grade(req_id: str, grade: str, reason: str | None) -> None:
        received.append(True)

    await agent._route_tool_call(
        tool_name="grade",
        args={"req_id": "R-01", "grade": "A"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=capture_grade,  # verifier phase
    )
    assert received == [True]
