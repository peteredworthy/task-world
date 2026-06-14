"""Unit tests for codex_server token capture from thread/tokenUsage/updated."""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.runners import CodexServerAgent, extract_metrics_and_usage
from orchestrator.runners.types import ExecutionContext
from orchestrator.config.enums import ChecklistStatus


# ---------------------------------------------------------------------------
# Fake transport for testing
# ---------------------------------------------------------------------------


class FakeTokenUsageTransport:
    """Hand-written fake transport that replays a recorded stream of token usage events.

    No mocks — just a pure recording/playback fake injected via constructor.
    """

    def __init__(self, recorded_stream: list[dict[str, Any]]) -> None:
        """Initialize with a pre-recorded stream of JSON-RPC messages."""
        self._stream = recorded_stream
        self._index = 0
        self._sent: list[dict[str, Any]] = []

    async def send(self, message: dict[str, Any]) -> None:
        """Record sent messages (for inspection in tests)."""
        self._sent.append(message)

    async def recv(self) -> dict[str, Any]:
        """Return the next message from the recorded stream."""
        if self._index >= len(self._stream):
            raise EOFError("End of recorded stream")
        msg = self._stream[self._index]
        self._index += 1
        return msg

    async def close(self) -> None:
        """No-op close."""
        pass


# ---------------------------------------------------------------------------
# Test: session accumulates token usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_accumulates_token_usage() -> None:
    """Agent accumulates token usage from thread/tokenUsage/updated events."""
    # Build a recorded stream: initialize response, thread/start response,
    # turn/start response, N token updates, and a final turn/completed.
    recorded_stream = [
        # initialize response
        {"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}},
        # thread/start response
        {"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-123"}}},
        # turn/start response
        {"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-456"}}},
        # First token usage update (cumulative)
        {
            "jsonrpc": "2.0",
            "method": "thread/tokenUsage/updated",
            "params": {
                "total_token_usage": {
                    "inputTokens": 1000,
                    "cachedInputTokens": 200,
                    "outputTokens": 100,
                    "reasoningOutputTokens": 20,
                }
            },
        },
        # Second token usage update (cumulative - higher values)
        {
            "jsonrpc": "2.0",
            "method": "thread/tokenUsage/updated",
            "params": {
                "total_token_usage": {
                    "inputTokens": 2500,
                    "cachedInputTokens": 1200,
                    "outputTokens": 450,
                    "reasoningOutputTokens": 120,
                }
            },
        },
        # Agent message delta (just to show mixed events)
        {
            "jsonrpc": "2.0",
            "method": "item/agentMessage/delta",
            "params": {"delta": "Working on it...\n"},
        },
        # Final turn/completed (with empty usage — updates should win)
        {
            "jsonrpc": "2.0",
            "method": "turn/completed",
            "params": {"turn": {"status": "completed", "usage": {}}},
        },
    ]

    transport = FakeTokenUsageTransport(recorded_stream)
    agent = CodexServerAgent(model="gpt-5.3-codex", _transport=transport)

    ctx = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp/work",
        prompt="Do the work.",
        requirements=["R-01: do this"],
    )

    # Dummy callbacks
    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        pass

    result = await agent.execute(ctx, on_checklist_update, on_submit)

    # Assert final action_log totals equal the cumulative usage (second update)
    assert result.action_log is not None
    assert result.action_log.total_input_tokens == 2500
    # Reasoning folded into output: 450 + 120 = 570
    assert result.action_log.total_output_tokens == 570
    assert result.action_log.total_cache_read_tokens == 1200
    # All values are nonzero
    assert result.action_log.total_input_tokens > 0
    assert result.action_log.total_output_tokens > 0
    assert result.action_log.total_cache_read_tokens > 0


# ---------------------------------------------------------------------------
# Test: extract_metrics_and_usage returns nonzero for codex
# ---------------------------------------------------------------------------


def test_extract_metrics_and_usage_nonzero_for_codex() -> None:
    """extract_metrics_and_usage returns a nonzero ModelTokenUsage for a codex result."""
    from orchestrator.runners import build_execution_result

    # Build a result as if it came from a session with token updates
    result = build_execution_result(
        output_lines=["hello\n", "world\n"],
        duration_ms=5000,
        tokens_read=2500,
        tokens_write=570,  # 450 + 120 reasoning
        tokens_cache=1200,
        num_actions=3,
        agent_model="gpt-5.3-codex",
    )

    metrics, usage_list = extract_metrics_and_usage(result)

    # Metrics should reflect the totals
    assert metrics.tokens_read == 2500
    assert metrics.tokens_write == 570
    assert metrics.tokens_cache == 1200

    # Should have one ModelTokenUsage entry for the codex model
    assert len(usage_list) == 1
    usage = usage_list[0]
    assert usage.model == "gpt-5.3-codex"
    assert usage.input_tokens == 2500
    assert usage.output_tokens == 570
    assert usage.cache_read_tokens == 1200
    # All nonzero
    assert usage.input_tokens > 0
    assert usage.output_tokens > 0
    assert usage.cache_read_tokens > 0
