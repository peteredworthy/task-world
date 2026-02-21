"""Tests for CodexServerAgent event streaming/polling transport implementation.

Exercises the execute() event loop using an injected fake HTTP transport.
No real Codex process is started — dependency injection only (no mocking).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from orchestrator.agents.codex_server import CodexServerAgent
from orchestrator.agents.errors import AgentNotAvailableError
from orchestrator.agents.types import ExecutionContext, ExecutionResult
from orchestrator.config.enums import ChecklistStatus


# ---------------------------------------------------------------------------
# Fake transport
# ---------------------------------------------------------------------------


class _FakeCodexTransport(httpx.AsyncBaseTransport):
    """Real fake httpx transport that simulates the Codex app server HTTP API.

    Routes:
    - POST /sessions → returns session_id
    - GET /sessions/{id}/events → returns the configured event list

    Uses dependency injection only; no mocking.
    """

    def __init__(
        self,
        events: list[dict[str, Any]],
        session_id: str = "fake-session-001",
    ) -> None:
        self._events = events
        self._session_id = session_id
        self.requests_made: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        self.requests_made.append(f"{method} {path}")

        if method == "POST" and path.endswith("/sessions"):
            return httpx.Response(
                200,
                content=json.dumps({"session_id": self._session_id}).encode(),
                headers={"content-type": "application/json"},
                request=request,
            )

        if method == "GET" and "/events" in path:
            return httpx.Response(
                200,
                content=json.dumps(self._events).encode(),
                headers={"content-type": "application/json"},
                request=request,
            )

        return httpx.Response(404, content=b"not found", request=request)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-transport-test",
        task_id="task-transport-test",
        working_dir="/tmp/transport-test",
        prompt="Test the transport.",
        requirements=["R-01: implement polling", "R-02: route events"],
    )


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


async def _noop_grade(req_id: str, grade: str, reason: str | None) -> None:
    pass


def _make_agent(
    events: list[dict[str, Any]],
    session_id: str = "fake-session-001",
) -> tuple[CodexServerAgent, _FakeCodexTransport]:
    """Create an agent with a fake transport returning the given events."""
    transport = _FakeCodexTransport(events, session_id=session_id)
    client = httpx.AsyncClient(transport=transport)
    agent = CodexServerAgent(_http_client=client)
    return agent, transport


# ---------------------------------------------------------------------------
# Requirement 1: execute() streams or polls events and routes tool-call events
# ---------------------------------------------------------------------------


async def test_execute_polls_session_events_endpoint() -> None:
    """execute() makes a GET request to the events endpoint after session creation."""
    events: list[dict[str, Any]] = [{"type": "complete", "status": "completed"}]
    agent, transport = _make_agent(events)

    await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    # Must have POSTed /sessions and then GETted /sessions/{id}/events
    assert any("POST" in req and "/sessions" in req for req in transport.requests_made)
    assert any("GET" in req and "/events" in req for req in transport.requests_made)


async def test_execute_routes_tool_call_update_checklist_to_callback() -> None:
    """A tool_call event for update_checklist fires the checklist callback."""
    events: list[dict[str, Any]] = [
        {
            "type": "tool_call",
            "tool_name": "update_checklist",
            "args": {"req_id": "R-01", "status": "done", "note": "completed"},
        },
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)
    received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def capture_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append((req_id, status, note))

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=capture_checklist,
        on_submit=_noop_submit,
    )

    assert received == [("R-01", ChecklistStatus.DONE, "completed")]
    assert isinstance(result, ExecutionResult)


async def test_execute_routes_tool_call_submit_to_callback() -> None:
    """A tool_call event for submit fires the submit callback."""
    events: list[dict[str, Any]] = [
        {"type": "tool_call", "tool_name": "submit", "args": {}},
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)
    submitted: list[bool] = []

    async def capture_submit() -> None:
        submitted.append(True)

    await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=capture_submit,
    )

    assert submitted == [True]


async def test_execute_routes_tool_call_grade_to_callback_in_verifier_phase() -> None:
    """A tool_call event for grade fires the grade callback in verifier phase."""
    events: list[dict[str, Any]] = [
        {
            "type": "tool_call",
            "tool_name": "grade",
            "args": {"req_id": "R-01", "grade": "A", "grade_reason": "Excellent"},
        },
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)
    grades: list[tuple[str, str, str | None]] = []

    async def capture_grade(req_id: str, grade: str, reason: str | None) -> None:
        grades.append((req_id, grade, reason))

    await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=capture_grade,
    )

    assert grades == [("R-01", "A", "Excellent")]


async def test_execute_silently_drops_disallowed_tool_call_events() -> None:
    """Disallowed tool_call events are silently dropped; execution continues."""
    events: list[dict[str, Any]] = [
        {"type": "tool_call", "tool_name": "bash", "args": {"command": "echo hi"}},
        {"type": "tool_call", "tool_name": "submit", "args": {}},
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)
    submitted: list[bool] = []

    async def capture_submit() -> None:
        submitted.append(True)

    # Should not raise despite disallowed tool; submit still fires
    await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=capture_submit,
    )

    assert submitted == [True]


# ---------------------------------------------------------------------------
# Requirement 2: tool-call event from fake server fires the matching callback
# ---------------------------------------------------------------------------


async def test_execute_tool_call_event_fires_matching_callback() -> None:
    """A tool-call event received from the fake server causes the matching callback to fire."""
    events: list[dict[str, Any]] = [
        {
            "type": "tool_call",
            "tool_name": "update_checklist",
            "args": {"req_id": "R-02", "status": "blocked", "note": "needs clarification"},
        },
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)
    received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append((req_id, status, note))

    await agent.execute(
        context=_ctx(),
        on_checklist_update=capture,
        on_submit=_noop_submit,
    )

    assert len(received) == 1
    assert received[0] == ("R-02", ChecklistStatus.BLOCKED, "needs clarification")


async def test_execute_multiple_tool_call_events_fire_in_order() -> None:
    """Multiple tool_call events from the fake server fire callbacks in event order."""
    events: list[dict[str, Any]] = [
        {
            "type": "tool_call",
            "tool_name": "update_checklist",
            "args": {"req_id": "R-01", "status": "done"},
        },
        {
            "type": "tool_call",
            "tool_name": "update_checklist",
            "args": {"req_id": "R-02", "status": "done"},
        },
        {"type": "tool_call", "tool_name": "submit", "args": {}},
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)
    checklist_calls: list[str] = []
    submitted: list[bool] = []

    async def capture_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        checklist_calls.append(req_id)

    async def capture_submit() -> None:
        submitted.append(True)

    await agent.execute(
        context=_ctx(),
        on_checklist_update=capture_checklist,
        on_submit=capture_submit,
    )

    assert checklist_calls == ["R-01", "R-02"]
    assert submitted == [True]


# ---------------------------------------------------------------------------
# Requirement 3: ExecutionResult with output_lines from output events
# ---------------------------------------------------------------------------


async def test_execute_output_event_populates_output_lines() -> None:
    """An output event appends text to ExecutionResult.output_lines."""
    events: list[dict[str, Any]] = [
        {"type": "output", "text": "Step 1 complete"},
        {"type": "output", "text": "Step 2 complete"},
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    assert "Step 1 complete" in result.output_lines
    assert "Step 2 complete" in result.output_lines


async def test_execute_output_event_invokes_on_output_callback() -> None:
    """An output event also calls on_output with the text lines."""
    events: list[dict[str, Any]] = [
        {"type": "output", "text": "Hello from agent"},
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)
    output_received: list[list[str]] = []

    async def capture_output(lines: list[str]) -> None:
        output_received.append(lines)

    await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_output=capture_output,
    )

    assert ["Hello from agent"] in output_received


async def test_execute_returns_execution_result_with_output_lines() -> None:
    """execute() returns ExecutionResult with output_lines populated from output events."""
    events: list[dict[str, Any]] = [
        {"type": "output", "text": "line one"},
        {"type": "output", "text": "line two"},
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert result.output_lines == ["line one", "line two"]


async def test_execute_returns_execution_result_with_empty_output_when_no_output_events() -> None:
    """ExecutionResult.output_lines is empty when there are no output events."""
    events: list[dict[str, Any]] = [
        {"type": "tool_call", "tool_name": "submit", "args": {}},
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert result.output_lines == []


async def test_execute_breaks_loop_on_terminal_complete_event() -> None:
    """execute() stops processing events after a terminal 'complete' event."""
    events: list[dict[str, Any]] = [
        {"type": "output", "text": "before terminal"},
        {"type": "complete", "status": "completed"},
        {"type": "output", "text": "after terminal — must not appear"},
    ]
    agent, _ = _make_agent(events)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    assert "before terminal" in result.output_lines
    assert "after terminal — must not appear" not in result.output_lines


async def test_execute_mixed_events_produces_correct_output_and_callbacks() -> None:
    """Mixed tool_call and output events are all processed correctly."""
    events: list[dict[str, Any]] = [
        {"type": "output", "text": "starting work"},
        {
            "type": "tool_call",
            "tool_name": "update_checklist",
            "args": {"req_id": "R-01", "status": "done"},
        },
        {"type": "output", "text": "work complete"},
        {"type": "tool_call", "tool_name": "submit", "args": {}},
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)
    checklist_calls: list[str] = []
    submitted: list[bool] = []

    async def capture_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        checklist_calls.append(req_id)

    async def capture_submit() -> None:
        submitted.append(True)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=capture_checklist,
        on_submit=capture_submit,
    )

    assert result.output_lines == ["starting work", "work complete"]
    assert checklist_calls == ["R-01"]
    assert submitted == [True]


# ---------------------------------------------------------------------------
# Required: test_execute_posts_to_sessions_endpoint
# ---------------------------------------------------------------------------


class _CapturingCodexTransport(_FakeCodexTransport):
    """Fake transport that also stores full httpx.Request objects for inspection."""

    def __init__(
        self,
        events: list[dict[str, Any]],
        session_id: str = "fake-session-001",
    ) -> None:
        super().__init__(events, session_id)
        self.captured_requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured_requests.append(request)
        return await super().handle_async_request(request)


async def test_execute_posts_to_sessions_endpoint() -> None:
    """execute() POSTs to /sessions with correct Content-Type header and non-empty body."""
    events: list[dict[str, Any]] = [{"type": "complete", "status": "completed"}]
    transport = _CapturingCodexTransport(events)
    client = httpx.AsyncClient(transport=transport)
    agent = CodexServerAgent(_http_client=client)

    await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    session_posts = [
        r
        for r in transport.captured_requests
        if r.method == "POST" and r.url.path.endswith("/sessions")
    ]
    assert session_posts, "No POST /sessions request was made"

    post_req = session_posts[0]
    content_type = post_req.headers.get("content-type", "")
    assert "application/json" in content_type, f"Expected application/json, got {content_type!r}"
    assert len(post_req.content) > 0, "POST /sessions body was empty"


# ---------------------------------------------------------------------------
# Required: test_execute_routes_update_checklist_tool_call
# ---------------------------------------------------------------------------


async def test_execute_routes_update_checklist_tool_call() -> None:
    """Fake server returns an update_checklist tool-call event; on_checklist_update is invoked."""
    events: list[dict[str, Any]] = [
        {
            "type": "tool_call",
            "tool_name": "update_checklist",
            "args": {"req_id": "R-01", "status": "done", "note": "requirement met"},
        },
        {"type": "complete", "status": "completed"},
    ]
    agent, _ = _make_agent(events)
    received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append((req_id, status, note))

    await agent.execute(
        context=_ctx(),
        on_checklist_update=capture,
        on_submit=_noop_submit,
    )

    assert len(received) == 1
    req_id, status, note = received[0]
    assert req_id == "R-01"
    assert status == ChecklistStatus.DONE
    assert note is not None


# ---------------------------------------------------------------------------
# Required: test_execute_raises_agent_not_available_on_connect_error
# ---------------------------------------------------------------------------


class _ConnectErrorTransport(httpx.AsyncBaseTransport):
    """Transport that always raises httpx.ConnectError to simulate an unreachable server."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")


async def test_execute_raises_agent_not_available_on_connect_error() -> None:
    """When the Codex server is unreachable, execute() raises AgentNotAvailableError."""
    transport = _ConnectErrorTransport()
    client = httpx.AsyncClient(transport=transport)
    agent = CodexServerAgent(_http_client=client)

    with pytest.raises(AgentNotAvailableError):
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
