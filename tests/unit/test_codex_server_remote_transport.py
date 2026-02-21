"""Tests for CodexServerRemoteAgent JSON-RPC WebSocket transport.

Exercises the execute() notification loop using injected fake transports.
No real Codex server is started — dependency injection only (no mocking).

Remote-specific contract (over local transport tests):
- Bearer token must NOT appear in any error message (risk R-05).
- WebSocket handshake failure → AgentExecutionError (token-safe message).
- Unreachable endpoint → AgentNotAvailableError.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import websockets.exceptions

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


class _FakeWebSocketTransport:
    """Real fake transport implementing ``JsonRpcTransport`` for test injection.

    Constructed with a list of messages to return from recv() in order.
    No mocking — this is a real object using asyncio queues.
    """

    def __init__(self, recv_sequence: list[dict[str, Any]]) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for msg in recv_sequence:
            self._queue.put_nowait(msg)
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    async def recv(self) -> dict[str, Any]:
        return await self._queue.get()

    async def close(self) -> None:
        pass


class _FailingWebSocketTransport:
    """Fake transport whose first send() raises OSError (simulates unreachable server)."""

    async def send(self, message: dict[str, Any]) -> None:
        raise OSError("Connection refused")

    async def recv(self) -> dict[str, Any]:
        raise OSError("Not connected")

    async def close(self) -> None:
        pass


class _AuthErrorWebSocketTransport:
    """Fake transport whose first send() raises an auth-flavored handshake error.

    In the real WebSocket flow, auth errors happen as InvalidHandshake during
    the connection upgrade, not during send().  This fake raises InvalidHandshake
    on the first send() to simulate an auth failure reaching the operation loop.

    Used to verify that error messages do not leak the bearer token.
    """

    def __init__(self, token: str) -> None:
        self._token = token

    async def send(self, message: dict[str, Any]) -> None:
        # Simulate an auth error that contains the token — the agent
        # must sanitise this before surfacing it.
        raise websockets.exceptions.InvalidHandshake(f"401 Unauthorized: token={self._token!r}")

    async def recv(self) -> dict[str, Any]:
        raise OSError("Not connected")

    async def close(self) -> None:
        pass


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


def _initialize_response(req_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"userAgent": "test/1.0.0"},
    }


def _thread_start_response(req_id: int = 2) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "thread": {
                "id": "thr_remote001",
                "preview": "",
                "modelProvider": "openai",
                "createdAt": 0,
            }
        },
    }


def _turn_start_response(req_id: int = 3) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "turn": {
                "id": "turn_remote001",
                "status": "inProgress",
                "items": [],
                "error": None,
            }
        },
    }


def _turn_completed(status: str = "completed") -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "turn/completed",
        "params": {
            "turn": {
                "id": "turn_remote001",
                "status": status,
                "items": [],
                "error": None,
            }
        },
    }


def _tool_call_request(
    tool_name: str,
    args: dict[str, Any],
    req_id: int = 10,
) -> dict[str, Any]:
    """item/tool/call server request (has both ``method`` and ``id``)."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "item/tool/call",
        "params": {"tool": tool_name, "arguments": args},
    }


def _agent_message_delta(text: str) -> dict[str, Any]:
    """item/agentMessage/delta notification (``params.delta`` is a plain string)."""
    return {
        "jsonrpc": "2.0",
        "method": "item/agentMessage/delta",
        "params": {"delta": text},
    }


def _make_agent(
    notifications: list[dict[str, Any]],
    token: str = _TOKEN,
) -> tuple[CodexServerRemoteAgent, _FakeWebSocketTransport]:
    """Return (agent, transport) with injected fake transport."""
    recv_sequence: list[dict[str, Any]] = [
        _initialize_response(req_id=1),
        _thread_start_response(req_id=2),
        _turn_start_response(req_id=3),
        *notifications,
    ]
    transport = _FakeWebSocketTransport(recv_sequence)
    agent = CodexServerRemoteAgent(
        base_url=_BASE_URL,
        api_key=token,
        _environ={},
        _transport=transport,
    )
    return agent, transport


# ---------------------------------------------------------------------------
# 1. update_checklist tool-call routing
# ---------------------------------------------------------------------------


async def test_remote_execute_routes_update_checklist_tool_call() -> None:
    """item/tool/call for update_checklist fires on_checklist_update."""
    notifications = [
        _tool_call_request(
            "update_checklist", {"req_id": "R-01", "status": "done", "note": "requirement met"}
        ),
        _turn_completed(),
    ]
    agent, _ = _make_agent(notifications)
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
# 2. submit tool-call routing
# ---------------------------------------------------------------------------


async def test_remote_execute_routes_submit_tool_call() -> None:
    """item/tool/call for submit fires on_submit."""
    notifications = [
        _tool_call_request("submit", {}),
        _turn_completed(),
    ]
    agent, _ = _make_agent(notifications)
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
# 3. ExecutionResult on terminal event
# ---------------------------------------------------------------------------


async def test_remote_execute_returns_result_on_terminal_event() -> None:
    """execute() returns an ExecutionResult when the server sends turn/completed."""
    notifications = [
        _agent_message_delta("work done"),
        _turn_completed(),
    ]
    agent, _ = _make_agent(notifications)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert "work done" in result.output_lines


# ---------------------------------------------------------------------------
# 4. Unreachable server → AgentNotAvailableError
# ---------------------------------------------------------------------------


async def test_remote_execute_raises_agent_not_available_on_connect_error() -> None:
    """When the transport raises OSError, execute() raises AgentNotAvailableError."""
    transport = _FailingWebSocketTransport()
    agent = CodexServerRemoteAgent(
        base_url=_BASE_URL,
        api_key=_TOKEN,
        _environ={},
        _transport=transport,
    )

    with pytest.raises(AgentNotAvailableError):
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


# ---------------------------------------------------------------------------
# 5. Auth failure → AgentExecutionError (not AgentNotAvailableError)
# ---------------------------------------------------------------------------


async def test_remote_execute_raises_agent_execution_error_on_auth_failure() -> None:
    """When the transport raises an auth error, execute() raises AgentExecutionError."""
    transport = _AuthErrorWebSocketTransport(token=_TOKEN)
    agent = CodexServerRemoteAgent(
        base_url=_BASE_URL,
        api_key=_TOKEN,
        _environ={},
        _transport=transport,
    )

    with pytest.raises(AgentExecutionError):
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


# ---------------------------------------------------------------------------
# 6. Bearer token NOT in error message on auth failure (risk R-05)
# ---------------------------------------------------------------------------


async def test_remote_execute_bearer_token_not_in_error_message_on_auth_failure() -> None:
    """The AgentExecutionError raised on auth failure must not expose the raw token.

    Token leakage risk R-05: if the bearer token were included in the error
    message, it could appear in logs, tracebacks, or API responses.
    """
    secret_token = "sk-super-secret-token-do-not-leak"  # pragma: allowlist secret
    transport = _AuthErrorWebSocketTransport(token=secret_token)
    agent = CodexServerRemoteAgent(
        base_url=_BASE_URL,
        api_key=secret_token,
        _environ={},
        _transport=transport,
    )

    with pytest.raises((AgentExecutionError, AgentNotAvailableError)) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )

    error_message = str(exc_info.value)
    assert secret_token not in error_message, (
        f"Bearer token leaked into error message: {error_message!r}"
    )
