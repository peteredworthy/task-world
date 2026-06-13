"""Tests for CodexServerAgent JSON-RPC stdio transport implementation.

Exercises the execute() notification loop using an injected fake transport.
No real Codex process is started — dependency injection only (no mocking).

The fake transport implements the real JSON-RPC 2.0 protocol shape documented
in docs/codex-server-transport/api-contract.md:
  - Responses carry an ``id`` matching the outgoing request.
  - Notifications carry a ``method`` but no ``id``.
  - Tool calls arrive as ``item/tool/call`` server requests (have both ``method`` and ``id``).
  - Agent text arrives as ``item/agentMessage/delta`` notifications (``params.delta`` string).
  - Terminal state is signalled by ``turn/completed``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest

from orchestrator.git import WorktreeCommitError
from orchestrator.runners import CodexServerAgent, RealStdioTransport
from orchestrator.runners.errors import AgentNotAvailableError
from orchestrator.runners.types import ExecutionContext, ExecutionResult
from orchestrator.config import ChecklistStatus
from orchestrator.config.models import MCPServerConfig

# ---------------------------------------------------------------------------
# Fake transport
# ---------------------------------------------------------------------------


class _FakeStdioTransport:
    """Real fake transport implementing ``JsonRpcTransport`` for test injection.

    Constructed with a list of messages to return in order from ``recv()``.
    Outgoing ``send()`` calls are recorded in ``sent`` for assertion.

    No mocking — this is a real object using asyncio queues.
    """

    def __init__(self, recv_sequence: list[dict[str, Any]]) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for msg in recv_sequence:
            self._queue.put_nowait(msg)
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    async def recv(self) -> dict[str, Any]:
        return await self._queue.get()

    async def close(self) -> None:
        self.closed = True


class _FailingStdioTransport:
    """Fake transport whose first send() raises OSError (simulates spawn failure)."""

    async def send(self, message: dict[str, Any]) -> None:
        raise OSError("codex app-server process failed to start")

    async def recv(self) -> dict[str, Any]:
        raise OSError("not connected")

    async def close(self) -> None:
        pass


class _ChunkedFakeStdout:
    """In-memory async stream that returns bytes in fixed-size chunks."""

    def __init__(self, payload: bytes, chunk_size: int = 1024) -> None:
        self._payload = payload
        self._chunk_size = chunk_size
        self._offset = 0

    async def read(self, n: int = 1024) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        read_size = max(1, min(n, self._chunk_size))
        chunk = self._payload[self._offset : self._offset + read_size]
        self._offset += len(chunk)
        return chunk


class _ChunkedFakeProcess:
    """Process shim exposing only ``stdout`` for transport recv-path tests."""

    def __init__(self, payload: bytes, chunk_size: int = 1024) -> None:
        self.stdout = _ChunkedFakeStdout(payload, chunk_size=chunk_size)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(mcp_servers: list[MCPServerConfig] | None = None) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-transport-test",
        task_id="task-transport-test",
        working_dir="/tmp/transport-test",
        prompt="Test the transport.",
        requirements=["R-01: implement polling", "R-02: route events"],
        mcp_servers=mcp_servers,
    )


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


async def _noop_grade(req_id: str, grade: str, reason: str | None) -> None:
    pass


def _initialize_response(req_id: int = 1) -> dict[str, Any]:
    """Standard initialize response."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"userAgent": "test/1.0.0"},
    }


def _thread_start_response(req_id: int = 2) -> dict[str, Any]:
    """Standard thread/start response."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "thread": {
                "id": "thr_test001",
                "preview": "",
                "modelProvider": "openai",
                "createdAt": 0,
            }
        },
    }


def _turn_start_response(req_id: int = 3) -> dict[str, Any]:
    """Standard turn/start response."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "turn": {
                "id": "turn_test001",
                "status": "inProgress",
                "items": [],
                "error": None,
            }
        },
    }


def _turn_completed(
    status: str = "completed",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """turn/completed notification with optional usage data."""
    turn: dict[str, Any] = {
        "id": "turn_test001",
        "status": status,
        "items": [],
        "error": None,
    }
    if usage is not None:
        turn["usage"] = usage
    return {
        "jsonrpc": "2.0",
        "method": "turn/completed",
        "params": {"turn": turn},
    }


def _item_completed(
    item_type: str = "shellCommand",
    item_id: str = "item_001",
) -> dict[str, Any]:
    """item/completed notification for action counting."""
    return {
        "jsonrpc": "2.0",
        "method": "item/completed",
        "params": {
            "item": {
                "id": item_id,
                "type": item_type,
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


def _agent_message_delta(text: str, item_id: str = "item_msg_001") -> dict[str, Any]:
    """item/agentMessage/delta notification (``params.delta`` is a plain string)."""
    return {
        "jsonrpc": "2.0",
        "method": "item/agentMessage/delta",
        "params": {"delta": text},
    }


def _make_agent(
    notifications: list[dict[str, Any]],
) -> tuple[CodexServerAgent, _FakeStdioTransport]:
    """Return (agent, transport) with an injected fake transport.

    The recv_sequence contains: initialize response, thread/start response,
    turn/start response, then the provided notifications.  The agent is
    constructed with ``api_key=None`` so no account/login/start step is
    attempted.
    """
    recv_sequence: list[dict[str, Any]] = [
        _initialize_response(req_id=1),
        _thread_start_response(req_id=2),
        _turn_start_response(req_id=3),
        *notifications,
    ]
    transport = _FakeStdioTransport(recv_sequence)
    agent = CodexServerAgent(api_key=None, _transport=transport, _environ={})
    return agent, transport


# ---------------------------------------------------------------------------
# 1. Protocol handshake: thread/start and turn/start are sent
# ---------------------------------------------------------------------------


async def test_execute_sends_thread_start_request() -> None:
    """execute() sends a thread/start JSON-RPC request to the transport."""
    agent, transport = _make_agent([_turn_completed()])

    await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    methods = [msg.get("method") for msg in transport.sent]
    assert "thread/start" in methods


async def test_execute_sends_turn_start_with_prompt() -> None:
    """execute() sends a turn/start request whose input contains the prompt."""
    agent, transport = _make_agent([_turn_completed()])

    await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    turn_starts = [m for m in transport.sent if m.get("method") == "turn/start"]
    assert turn_starts, "No turn/start message was sent"
    input_items = turn_starts[0].get("params", {}).get("input", [])
    text_items = [item["text"] for item in input_items if item.get("type") == "text"]
    assert any("Test the transport." in t for t in text_items)


# ---------------------------------------------------------------------------
# 2. Tool-call routing
# ---------------------------------------------------------------------------


async def test_execute_routes_tool_call_update_checklist_to_callback() -> None:
    """An item/tool/call for update_checklist fires the checklist callback."""
    notifications = [
        _tool_call_request(
            "update_checklist", {"req_id": "R-01", "status": "done", "note": "completed"}
        ),
        _turn_completed(),
    ]
    agent, _ = _make_agent(notifications)
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
    """An item/tool/call for submit fires the submit callback."""
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


async def test_execute_routes_tool_call_grade_to_callback_in_verifier_phase() -> None:
    """An item/tool/call for grade fires the grade callback in verifier phase."""
    notifications = [
        _tool_call_request("grade", {"req_id": "R-01", "grade": "A", "grade_reason": "Excellent"}),
        _turn_completed(),
    ]
    agent, _ = _make_agent(notifications)
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
    """Disallowed item/tool/call events respond with failure; execution continues."""
    notifications = [
        _tool_call_request("bash", {"command": "echo hi"}, 10),
        _tool_call_request("submit", {}, 11),
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


async def test_execute_submit_commit_failure_feeds_back_and_continues() -> None:
    """A submit whose commit gate fails is rejected with feedback, not crashed.

    Regression: a WorktreeCommitError raised by on_submit (the pre-submit
    ruff/pyright/pytest commit gate) used to bubble up through the generic
    exception handler and kill the codex session (AgentExecutionError →
    run paused as agent_execution_error). The builder-fixable rejection must
    instead be returned to the agent as a failed tool result carrying the hook
    output, so it can fix and resubmit within the same session — mirroring the
    HTTP /submit endpoint's 409 reject-with-feedback.
    """
    notifications = [
        _tool_call_request("submit", {}, 11),
        _turn_completed(),
    ]
    agent, transport = _make_agent(notifications)
    submit_calls: list[bool] = []

    async def failing_submit() -> None:
        submit_calls.append(True)
        raise WorktreeCommitError(
            "/tmp/worktree",
            "pyright..............Failed\n  graph.py:154 error: ...",
        )

    # Must NOT raise — the session continues past the rejected submit.
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=failing_submit,
    )

    assert submit_calls == [True]
    assert isinstance(result, ExecutionResult)
    # A failure tool-call response for the submit request (id=11) was sent back
    # to the agent, carrying the actionable hook output as feedback.
    submit_responses = [m for m in transport.sent if m.get("id") == 11 and "result" in m]
    assert submit_responses, "No tool-call response was sent for the submit request"
    resp = submit_responses[-1]
    assert resp["result"]["success"] is False
    text = resp["result"]["contentItems"][0]["text"]
    assert "Submission rejected" in text
    assert "pyright" in text


async def test_execute_tool_call_event_fires_matching_callback() -> None:
    """A tool-call server request from the fake transport causes the matching callback to fire."""
    notifications = [
        _tool_call_request(
            "update_checklist",
            {"req_id": "R-02", "status": "blocked", "note": "needs clarification"},
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
    assert received[0] == ("R-02", ChecklistStatus.BLOCKED, "needs clarification")


async def test_execute_multiple_tool_call_events_fire_in_order() -> None:
    """Multiple tool-call server requests fire callbacks in arrival order."""
    notifications = [
        _tool_call_request("update_checklist", {"req_id": "R-01", "status": "done"}, 10),
        _tool_call_request("update_checklist", {"req_id": "R-02", "status": "done"}, 11),
        _tool_call_request("submit", {}, 12),
        _turn_completed(),
    ]
    agent, _ = _make_agent(notifications)
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
# 3. Output lines from agent message delta events
# ---------------------------------------------------------------------------


async def test_execute_output_event_populates_output_lines() -> None:
    """item/agentMessage/delta notifications populate ExecutionResult.output_lines."""
    notifications = [
        _agent_message_delta("Step 1 complete\n", "m1"),
        _agent_message_delta("Step 2 complete\n", "m2"),
        _turn_completed(),
    ]
    agent, _ = _make_agent(notifications)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    assert "Step 1 complete" in result.output_lines
    assert "Step 2 complete" in result.output_lines


async def test_execute_output_event_invokes_on_output_callback() -> None:
    """item/agentMessage/delta also calls on_output with the text."""
    notifications = [
        _agent_message_delta("Hello from agent"),
        _turn_completed(),
    ]
    agent, _ = _make_agent(notifications)
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
    """execute() returns ExecutionResult with output_lines from agent message deltas."""
    notifications = [
        _agent_message_delta("line one\n"),
        _agent_message_delta("line two\n"),
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
    assert result.output_lines == ["line one", "line two"]


async def test_execute_returns_execution_result_with_empty_output_when_no_output_events() -> None:
    """ExecutionResult.output_lines is empty when there are no agent message deltas."""
    notifications = [
        _tool_call_request("submit", {}),
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
    assert result.output_lines == []


async def test_execute_breaks_loop_on_turn_completed() -> None:
    """execute() stops processing after turn/completed; subsequent notifications are ignored."""
    notifications = [
        _agent_message_delta("before terminal"),
        _turn_completed(),
        # These must not appear:
        _agent_message_delta("after terminal — must not appear"),
    ]
    agent, _ = _make_agent(notifications)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    assert "before terminal" in result.output_lines
    assert "after terminal — must not appear" not in result.output_lines


async def test_execute_mixed_events_produces_correct_output_and_callbacks() -> None:
    """Mixed tool-call and output notifications are all processed correctly."""
    notifications = [
        _agent_message_delta("starting work\n"),
        _tool_call_request("update_checklist", {"req_id": "R-01", "status": "done"}, 10),
        _agent_message_delta("work complete\n"),
        _tool_call_request("submit", {}, 11),
        _turn_completed(),
    ]
    agent, _ = _make_agent(notifications)
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
# 4. Handshake messages
# ---------------------------------------------------------------------------


async def test_execute_posts_to_sessions_endpoint() -> None:
    """execute() sends a thread/start message with a non-empty userMessage in turn/start."""
    agent, transport = _make_agent([_turn_completed()])

    await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    # thread/start must be sent with cwd and approvalPolicy
    thread_starts = [m for m in transport.sent if m.get("method") == "thread/start"]
    assert thread_starts, "No thread/start message was sent"
    params = thread_starts[0].get("params", {})
    assert params.get("approvalPolicy") == "never"
    assert params.get("cwd") == "/tmp/transport-test"


async def test_execute_passes_worktree_cwd_to_stdio_mcp_server() -> None:
    """Command MCP servers with cwd='worktree' start from the task worktree."""
    agent, transport = _make_agent([_turn_completed()])
    mcp = MCPServerConfig(
        name="codesight",
        command="npx",
        args=["-y", "codesight", "--mcp"],
        cwd="worktree",
    )

    await agent.execute(
        context=_ctx(mcp_servers=[mcp]),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    thread_starts = [m for m in transport.sent if m.get("method") == "thread/start"]
    params = thread_starts[0].get("params", {})
    assert params["mcpServers"] == [
        {
            "name": "codesight",
            "command": "npx",
            "args": ["-y", "codesight", "--mcp"],
            "cwd": "/tmp/transport-test",
        }
    ]


async def test_execute_routes_update_checklist_tool_call() -> None:
    """Fake transport returns an update_checklist item/tool/call; on_checklist_update is invoked."""
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
    assert note is not None


# ---------------------------------------------------------------------------
# 5. Error paths
# ---------------------------------------------------------------------------


async def test_execute_raises_agent_not_available_on_transport_failure() -> None:
    """When the transport raises OSError on send, execute() raises AgentNotAvailableError."""
    transport = _FailingStdioTransport()
    agent = CodexServerAgent(api_key=None, _transport=transport, _environ={})

    with pytest.raises(AgentNotAvailableError):
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


# ---------------------------------------------------------------------------
# 6. Token usage extraction from turn/completed
# ---------------------------------------------------------------------------


async def test_execute_extracts_usage_from_turn_completed() -> None:
    """Token usage in turn/completed is reflected in ExecutionResult.metrics."""
    notifications = [
        _turn_completed(
            usage={
                "input_tokens": 5000,
                "output_tokens": 1200,
                "cache_read_tokens": 300,
            }
        ),
    ]
    agent, _ = _make_agent(notifications)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    assert result.metrics.tokens_read == 5000
    assert result.metrics.tokens_write == 1200
    assert result.metrics.tokens_cache == 300


async def test_execute_zero_usage_when_no_usage_field() -> None:
    """When turn/completed has no usage, metrics default to zero."""
    notifications = [_turn_completed()]
    agent, _ = _make_agent(notifications)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    assert result.metrics.tokens_read == 0
    assert result.metrics.tokens_write == 0
    assert result.metrics.tokens_cache == 0


# ---------------------------------------------------------------------------
# 7. Action counting
# ---------------------------------------------------------------------------


async def test_execute_counts_tool_call_dispatches() -> None:
    """item/tool/call dispatches increment num_actions in metrics."""
    notifications = [
        _tool_call_request("update_checklist", {"req_id": "R-01", "status": "done"}, 10),
        _tool_call_request("submit", {}, 11),
        _turn_completed(),
    ]
    agent, _ = _make_agent(notifications)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    assert result.metrics.num_actions >= 2


async def test_execute_counts_item_completed_as_actions() -> None:
    """item/completed notifications (non-agentMessage) are counted as actions."""
    notifications = [
        _item_completed("shellCommand", "item_001"),
        _item_completed("fileEdit", "item_002"),
        _item_completed("agentMessage", "item_003"),  # Should NOT count
        _turn_completed(),
    ]
    agent, _ = _make_agent(notifications)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    # 2 non-agentMessage item/completed events
    assert result.metrics.num_actions == 2


async def test_execute_combined_metrics() -> None:
    """Full session with tool calls, items, and usage produces correct combined metrics."""
    notifications = [
        _agent_message_delta("working on it\n"),
        _item_completed("shellCommand", "item_001"),
        _tool_call_request("update_checklist", {"req_id": "R-01", "status": "done"}, 10),
        _item_completed("fileEdit", "item_002"),
        _tool_call_request("submit", {}, 11),
        _turn_completed(
            usage={
                "input_tokens": 10000,
                "output_tokens": 2500,
                "cache_read_tokens": 1000,
            }
        ),
    ]
    agent, _ = _make_agent(notifications)
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

    # Verify callbacks fired
    assert checklist_calls == ["R-01"]
    assert submitted == [True]

    # Verify output
    assert "working on it" in result.output_lines

    # Verify metrics: 2 item/completed (non-agentMessage) + 2 tool/call dispatches = 4
    assert result.metrics.num_actions == 4
    assert result.metrics.tokens_read == 10000
    assert result.metrics.tokens_write == 2500
    assert result.metrics.tokens_cache == 1000
    assert result.metrics.duration_ms >= 0


async def test_real_stdio_transport_reads_large_ndjson_lines_without_limit_overrun() -> None:
    """recv() reads large JSON-RPC messages split into small stdout chunks."""
    payload = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"text": "x" * (2 * 1024 * 1024)},
            }
        ).encode()
        + b"\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}).encode()
        + b"\n"
    )
    transport = RealStdioTransport(cast(Any, _ChunkedFakeProcess(payload=payload, chunk_size=1024)))

    first = await transport.recv()
    second = await transport.recv()

    assert first["id"] == 1
    assert second["method"] == "ping"


async def test_real_stdio_transport_discards_oversized_lines_and_recovers() -> None:
    """recv() drops oversized non-delimited lines and continues with following frames."""
    payload = (
        json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"text": "x" * (17 * 1024 * 1024)}}
        ).encode()
        + b"\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}).encode()
        + b"\n"
    )
    transport = RealStdioTransport(cast(Any, _ChunkedFakeProcess(payload=payload, chunk_size=1024)))

    second = await transport.recv()

    assert second["id"] == 2
    assert second["result"]["ok"] is True


async def test_execute_builds_structured_action_log_from_notifications() -> None:
    """execute() persists assistant text and tool activity into action_log entries."""
    notifications = [
        _agent_message_delta("Inspecting repo"),
        {
            "jsonrpc": "2.0",
            "method": "item/completed",
            "params": {
                "item": {
                    "id": "cmd_1",
                    "type": "commandExecution",
                    "command": "rg -n Codex src",
                    "status": "completed",
                    "exitCode": 0,
                    "aggregatedOutput": "src/example.py:1:Codex",
                }
            },
        },
        _tool_call_request("update_checklist", {"req_id": "R-01", "status": "done"}, 10),
        _turn_completed(
            usage={
                "input_tokens": 120,
                "output_tokens": 40,
                "cache_read_tokens": 10,
            }
        ),
    ]
    agent, _ = _make_agent(notifications)

    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )

    assert result.action_log is not None
    entries = result.action_log.entries
    assert [entry.kind.value for entry in entries] == [
        "assistant_text",
        "tool_use",
        "tool_result",
        "tool_use",
        "tool_result",
        "result",
    ]
    assert entries[0].text == "Inspecting repo"
    assert entries[1].tool_use is not None
    assert entries[1].tool_use.tool_name == "bash"
    assert entries[2].tool_result is not None
    assert entries[2].tool_result.output == "src/example.py:1:Codex"
    assert entries[3].tool_use is not None
    assert entries[3].tool_use.tool_name == "update_checklist"
    assert entries[4].tool_result is not None
    assert entries[4].tool_result.success is True
    assert result.action_log.total_input_tokens == 120
    assert result.action_log.total_output_tokens == 40
