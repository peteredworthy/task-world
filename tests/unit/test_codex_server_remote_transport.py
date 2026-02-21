"""Tests for CodexServerRemoteAgent event streaming/polling transport.

Exercises the execute() event loop using injected fake HTTP transports.
No real Codex server is started — dependency injection only (no mocking).

Remote-specific contract (over local transport tests):
- Every request carries "Authorization: Bearer <token>".
- ConnectError → AgentNotAvailableError.
- HTTP 401 → AgentExecutionError whose message does NOT contain the token.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from orchestrator.agents.codex_server_remote import CodexServerRemoteAgent
from orchestrator.agents.errors import AgentExecutionError, AgentNotAvailableError
from orchestrator.agents.types import ExecutionContext, ExecutionResult
from orchestrator.config.enums import ChecklistStatus


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://codex.example.com"
_TOKEN = "sk-test-bearer-secret"  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# Fake transports
# ---------------------------------------------------------------------------


class _CapturingRemoteTransport(httpx.AsyncBaseTransport):
    """Fake httpx transport that captures full requests and returns scripted responses.

    Routes:
    - POST /sessions → {"session_id": "fake-session-001"}
    - GET /sessions/{id}/events → configured events list

    Stores captured httpx.Request objects for post-call assertion.
    """

    def __init__(
        self,
        events: list[dict[str, Any]],
        session_id: str = "fake-session-001",
    ) -> None:
        self._events = events
        self._session_id = session_id
        self.captured_requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured_requests.append(request)
        path = request.url.path

        if request.method == "POST" and path.endswith("/sessions"):
            return httpx.Response(
                200,
                content=json.dumps({"session_id": self._session_id}).encode(),
                headers={"content-type": "application/json"},
                request=request,
            )

        if request.method == "GET" and "/events" in path:
            return httpx.Response(
                200,
                content=json.dumps(self._events).encode(),
                headers={"content-type": "application/json"},
                request=request,
            )

        return httpx.Response(404, content=b"not found", request=request)


class _UnauthorizedTransport(httpx.AsyncBaseTransport):
    """Transport that always returns HTTP 401 to simulate a bad/expired bearer token."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            content=b'{"error": "Unauthorized"}',
            headers={"content-type": "application/json"},
            request=request,
        )


class _ConnectErrorTransport(httpx.AsyncBaseTransport):
    """Transport that always raises httpx.ConnectError to simulate an unreachable server."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-remote-transport-test",
        task_id="task-remote-transport-test",
        working_dir="/tmp/remote-transport-test",
        prompt="Test the remote transport.",
        requirements=["R-01: bearer auth", "R-02: route events"],
    )


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


def _make_agent(
    events: list[dict[str, Any]],
    token: str = _TOKEN,
    session_id: str = "fake-session-001",
) -> tuple[CodexServerRemoteAgent, _CapturingRemoteTransport]:
    """Return (agent, transport) with injected capturing transport."""
    transport = _CapturingRemoteTransport(events, session_id=session_id)
    client = httpx.AsyncClient(transport=transport)
    agent = CodexServerRemoteAgent(
        base_url=_BASE_URL,
        api_key=token,
        _environ={},
        _http_client=client,
    )
    return agent, transport


# ---------------------------------------------------------------------------
# 1. Bearer auth header sent on every request
# ---------------------------------------------------------------------------


async def test_remote_execute_sends_bearer_auth_header() -> None:
    """POST /sessions carries Authorization: Bearer <token>.

    This is the primary contract difference between local and remote:
    every outgoing request must include the bearer token in the
    Authorization header.
    """
    events: list[dict[str, Any]] = [{"type": "complete", "status": "completed"}]
    agent, transport = _make_agent(events, token=_TOKEN)

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

    auth_header = session_posts[0].headers.get("authorization", "")
    assert auth_header == f"Bearer {_TOKEN}", f"Expected 'Bearer {_TOKEN}', got {auth_header!r}"


async def test_remote_execute_sends_bearer_auth_on_events_request() -> None:
    """GET /sessions/{id}/events also carries Authorization: Bearer <token>."""
    events: list[dict[str, Any]] = [{"type": "complete", "status": "completed"}]
    agent, transport = _make_agent(events, token=_TOKEN)

    await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    events_gets = [
        r for r in transport.captured_requests if r.method == "GET" and "/events" in r.url.path
    ]
    assert events_gets, "No GET /events request was made"

    auth_header = events_gets[0].headers.get("authorization", "")
    assert auth_header == f"Bearer {_TOKEN}"


# ---------------------------------------------------------------------------
# 2. update_checklist tool-call routing
# ---------------------------------------------------------------------------


async def test_remote_execute_routes_update_checklist_tool_call() -> None:
    """Fake server returns a tool_call event for update_checklist; on_checklist_update fires."""
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
    assert note == "requirement met"


# ---------------------------------------------------------------------------
# 3. submit tool-call routing
# ---------------------------------------------------------------------------


async def test_remote_execute_routes_submit_tool_call() -> None:
    """Fake server returns a tool_call event for submit; on_submit fires."""
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


# ---------------------------------------------------------------------------
# 4. ExecutionResult on terminal event
# ---------------------------------------------------------------------------


async def test_remote_execute_returns_result_on_terminal_event() -> None:
    """execute() returns an ExecutionResult when the server sends a terminal event."""
    events: list[dict[str, Any]] = [
        {"type": "output", "text": "work done"},
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
    assert "work done" in result.output_lines


# ---------------------------------------------------------------------------
# 5. ConnectError → AgentNotAvailableError
# ---------------------------------------------------------------------------


async def test_remote_execute_raises_agent_not_available_on_connect_error() -> None:
    """When the remote server is unreachable, execute() raises AgentNotAvailableError."""
    transport = _ConnectErrorTransport()
    client = httpx.AsyncClient(transport=transport)
    agent = CodexServerRemoteAgent(
        base_url=_BASE_URL,
        api_key=_TOKEN,
        _environ={},
        _http_client=client,
    )

    with pytest.raises(AgentNotAvailableError):
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


# ---------------------------------------------------------------------------
# 6. HTTP 401 → AgentExecutionError
# ---------------------------------------------------------------------------


async def test_remote_execute_raises_agent_execution_error_on_401() -> None:
    """When the server returns HTTP 401, execute() raises AgentExecutionError."""
    transport = _UnauthorizedTransport()
    client = httpx.AsyncClient(transport=transport)
    agent = CodexServerRemoteAgent(
        base_url=_BASE_URL,
        api_key=_TOKEN,
        _environ={},
        _http_client=client,
    )

    with pytest.raises(AgentExecutionError):
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


# ---------------------------------------------------------------------------
# 7. Bearer token NOT in error message on 401 (risk R-05: token leakage)
# ---------------------------------------------------------------------------


async def test_remote_execute_bearer_token_not_in_error_message_on_401() -> None:
    """The AgentExecutionError raised on 401 must not expose the raw token value.

    Token leakage risk R-05: if the bearer token were included in the error
    message, it could appear in logs, tracebacks, or API responses.
    """
    secret_token = "sk-super-secret-token-do-not-leak"  # pragma: allowlist secret
    transport = _UnauthorizedTransport()
    client = httpx.AsyncClient(transport=transport)
    agent = CodexServerRemoteAgent(
        base_url=_BASE_URL,
        api_key=secret_token,
        _environ={},
        _http_client=client,
    )

    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )

    error_message = str(exc_info.value)
    assert secret_token not in error_message, (
        f"Bearer token leaked into error message: {error_message!r}"
    )
