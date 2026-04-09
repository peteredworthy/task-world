"""Integration tests for WebSocket support."""

import asyncio
import json
from datetime import datetime, timezone

from starlette.testclient import TestClient

from orchestrator.api.app import create_app
from orchestrator.config import RunStatus
from orchestrator.api.websocket import BatchingConnectionManager, ConnectionManager
from orchestrator.workflow import ClarificationRequested, ClarificationResponded, RunStatusChanged


class MockWebSocket:
    """Lightweight mock WebSocket for testing ConnectionManager directly."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def accept(self) -> None:
        pass

    async def send_text(self, data: str) -> None:
        self.messages.append(data)


async def test_connection_manager_broadcast() -> None:
    """ConnectionManager broadcasts to correct run subscribers."""
    manager = ConnectionManager()

    # Without any connections, broadcast should not fail
    await manager.broadcast_to_run("run-1", {"test": "data"})


async def test_connection_manager_broadcast_event() -> None:
    """ConnectionManager.broadcast_event serializes dataclass events."""
    manager = ConnectionManager()

    event = RunStatusChanged(
        timestamp=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        run_id="run-1",
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
    )
    ws = MockWebSocket()
    await manager.connect("run-1", ws)  # type: ignore[arg-type]

    await manager.broadcast_event(event)
    assert len(ws.messages) == 1
    payload = json.loads(ws.messages[0])
    assert payload["timestamp"].endswith("Z")


async def test_connection_manager_broadcast_event_clarification_requested_payload() -> None:
    """ClarificationRequested uses minimal websocket payload fields."""
    manager = ConnectionManager()
    ws = MockWebSocket()
    await manager.connect("run-1", ws)  # type: ignore[arg-type]

    event = ClarificationRequested(
        run_id="run-1",
        task_id="task-1",
        request_id="req-1",
        question_count=2,
        questions=[{"id": "q1"}],
    )

    await manager.broadcast_event(event)

    assert len(ws.messages) == 1
    parsed = json.loads(ws.messages[0])
    assert parsed == {
        "event_type": "clarification_requested",
        "run_id": "run-1",
        "task_id": "task-1",
        "request_id": "req-1",
        "question_count": 2,
    }


async def test_connection_manager_broadcast_event_clarification_responded_payload() -> None:
    """ClarificationResponded uses minimal websocket payload fields."""
    manager = ConnectionManager()
    ws = MockWebSocket()
    await manager.connect("run-1", ws)  # type: ignore[arg-type]

    event = ClarificationResponded(
        run_id="run-1",
        task_id="task-1",
        request_id="req-1",
    )

    await manager.broadcast_event(event)

    assert len(ws.messages) == 1
    parsed = json.loads(ws.messages[0])
    assert parsed == {
        "event_type": "clarification_responded",
        "run_id": "run-1",
        "task_id": "task-1",
        "request_id": "req-1",
    }


def test_websocket_connect_disconnect() -> None:
    """Test basic WebSocket connect and disconnect."""
    app = create_app(db_path=":memory:")

    # Use Starlette's sync TestClient for WebSocket testing
    with TestClient(app) as client:
        with client.websocket_connect("/ws/runs/run-1"):
            # Connection established - just close cleanly
            pass


async def test_websocket_receives_broadcast() -> None:
    """Test that a connected WebSocket receives broadcast messages."""
    manager = ConnectionManager()
    ws = MockWebSocket()
    await manager.connect("run-1", ws)  # type: ignore[arg-type]

    await manager.broadcast_to_run("run-1", {"event": "test", "data": "hello"})

    assert len(ws.messages) == 1
    parsed = json.loads(ws.messages[0])
    assert parsed["event"] == "test"
    assert parsed["data"] == "hello"


async def test_websocket_cross_run_isolation() -> None:
    """Messages for run-1 should not be sent to run-2 subscribers."""
    manager = ConnectionManager()
    ws1 = MockWebSocket()
    ws2 = MockWebSocket()
    await manager.connect("run-1", ws1)  # type: ignore[arg-type]
    await manager.connect("run-2", ws2)  # type: ignore[arg-type]

    # Broadcast to run-2 — ws1 (on run-1) should not receive it
    await manager.broadcast_to_run("run-2", {"event": "for-run-2"})
    # Broadcast to run-1 — ws1 should receive it
    await manager.broadcast_to_run("run-1", {"event": "for-run-1"})

    # ws1 only got the run-1 message
    assert len(ws1.messages) == 1
    parsed = json.loads(ws1.messages[0])
    assert parsed["event"] == "for-run-1"

    # ws2 only got the run-2 message
    assert len(ws2.messages) == 1
    parsed2 = json.loads(ws2.messages[0])
    assert parsed2["event"] == "for-run-2"


async def test_multiple_subscribers() -> None:
    """Multiple WebSocket clients for the same run all receive broadcasts."""
    manager = ConnectionManager()
    ws1 = MockWebSocket()
    ws2 = MockWebSocket()
    await manager.connect("run-1", ws1)  # type: ignore[arg-type]
    await manager.connect("run-1", ws2)  # type: ignore[arg-type]

    await manager.broadcast_to_run("run-1", {"event": "hello"})

    assert len(ws1.messages) == 1
    assert len(ws2.messages) == 1
    assert json.loads(ws1.messages[0])["event"] == "hello"
    assert json.loads(ws2.messages[0])["event"] == "hello"


async def test_per_client_throttle() -> None:
    """Rapid broadcasts are throttled per client — only first and post-interval get through."""
    manager = ConnectionManager()
    ws = MockWebSocket()
    await manager.connect("run-1", ws)  # type: ignore[arg-type]

    # First broadcast should go through
    await manager.broadcast_to_run("run-1", {"seq": 1})
    assert len(ws.messages) == 1
    assert json.loads(ws.messages[0])["seq"] == 1

    # Second broadcast immediately after should be throttled (dropped)
    await manager.broadcast_to_run("run-1", {"seq": 2})
    assert len(ws.messages) == 1  # still 1

    # Wait for throttle interval to pass
    await asyncio.sleep(0.11)

    # Third broadcast should go through after the throttle window
    await manager.broadcast_to_run("run-1", {"seq": 3})
    assert len(ws.messages) == 2
    assert json.loads(ws.messages[1])["seq"] == 3


async def test_per_client_throttle_independent() -> None:
    """Two clients on the same run throttle independently."""
    manager = ConnectionManager()
    ws1 = MockWebSocket()
    await manager.connect("run-1", ws1)  # type: ignore[arg-type]

    # Broadcast to establish ws1's throttle timestamp
    await manager.broadcast_to_run("run-1", {"seq": 1})
    assert len(ws1.messages) == 1
    assert json.loads(ws1.messages[0])["seq"] == 1

    # Wait for throttle to pass for ws1
    await asyncio.sleep(0.11)

    # Now connect ws2 — it has no throttle history
    ws2 = MockWebSocket()
    await manager.connect("run-1", ws2)  # type: ignore[arg-type]

    # Both clients should receive this broadcast:
    # ws1 because throttle has passed, ws2 because it's new
    await manager.broadcast_to_run("run-1", {"seq": 2})
    assert len(ws1.messages) == 2
    assert json.loads(ws1.messages[1])["seq"] == 2
    assert len(ws2.messages) == 1
    assert json.loads(ws2.messages[0])["seq"] == 2


# ========== Batching Tests ==========


async def test_batching_manager_disabled_mode() -> None:
    """BatchingConnectionManager with batching disabled behaves like regular ConnectionManager."""
    manager = BatchingConnectionManager(batching_enabled=False)

    # Without any connections, broadcast should not fail
    await manager.broadcast_to_run("run-1", {"test": "data"})


async def test_batching_collects_events_within_window() -> None:
    """Events broadcast within the batch window are collected and sent as a batch."""
    manager = BatchingConnectionManager(batch_window=0.05, batching_enabled=True)

    ws = MockWebSocket()
    await manager.connect("run-1", ws)  # type: ignore[arg-type]

    # Send multiple events rapidly
    await manager.broadcast_to_run("run-1", {"event": "first", "seq": 1})
    await manager.broadcast_to_run("run-1", {"event": "second", "seq": 2})
    await manager.broadcast_to_run("run-1", {"event": "third", "seq": 3})

    # Wait for batch window to expire
    await asyncio.sleep(0.07)

    # Should have received exactly one batch message
    assert len(ws.messages) == 1

    batch = json.loads(ws.messages[0])
    assert batch["type"] == "batch"
    assert batch["run_id"] == "run-1"
    assert batch["count"] == 3
    assert len(batch["events"]) == 3
    assert batch["events"][0]["seq"] == 1
    assert batch["events"][1]["seq"] == 2
    assert batch["events"][2]["seq"] == 3


async def test_batching_multiple_runs_independent() -> None:
    """Events for different runs are batched independently."""
    manager = BatchingConnectionManager(batch_window=0.05, batching_enabled=True)

    ws1 = MockWebSocket()
    ws2 = MockWebSocket()
    await manager.connect("run-1", ws1)  # type: ignore[arg-type]
    await manager.connect("run-2", ws2)  # type: ignore[arg-type]

    # Send events to different runs
    await manager.broadcast_to_run("run-1", {"run": 1, "seq": 1})
    await manager.broadcast_to_run("run-2", {"run": 2, "seq": 1})
    await manager.broadcast_to_run("run-1", {"run": 1, "seq": 2})
    await manager.broadcast_to_run("run-2", {"run": 2, "seq": 2})

    # Wait for batch windows to expire
    await asyncio.sleep(0.07)

    # Each websocket should have received one batch
    assert len(ws1.messages) == 1
    assert len(ws2.messages) == 1

    batch1 = json.loads(ws1.messages[0])
    batch2 = json.loads(ws2.messages[0])

    assert batch1["run_id"] == "run-1"
    assert batch1["count"] == 2
    assert batch2["run_id"] == "run-2"
    assert batch2["count"] == 2


async def test_batching_flush_all() -> None:
    """flush_all() immediately sends all pending batches."""
    manager = BatchingConnectionManager(batch_window=10.0, batching_enabled=True)  # Long window

    ws = MockWebSocket()
    await manager.connect("run-1", ws)  # type: ignore[arg-type]

    # Send events but don't wait for window
    await manager.broadcast_to_run("run-1", {"seq": 1})
    await manager.broadcast_to_run("run-1", {"seq": 2})

    # No messages yet (window hasn't expired)
    assert len(ws.messages) == 0

    # Flush immediately
    await manager.flush_all()

    # Should have received the batch now
    assert len(ws.messages) == 1
    batch = json.loads(ws.messages[0])
    assert batch["count"] == 2


async def test_batching_event_broadcast() -> None:
    """broadcast_event works with batching enabled."""
    manager = BatchingConnectionManager(batch_window=0.05, batching_enabled=True)

    ws = MockWebSocket()
    await manager.connect("run-1", ws)  # type: ignore[arg-type]

    # Send events using broadcast_event
    event1 = RunStatusChanged(
        timestamp=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        run_id="run-1",
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
    )
    event2 = RunStatusChanged(
        timestamp=datetime(2025, 1, 15, 10, 31, 0, tzinfo=timezone.utc),
        run_id="run-1",
        event_type="run_status_changed",
        old_status=RunStatus.ACTIVE,
        new_status=RunStatus.COMPLETED,
    )

    await manager.broadcast_event(event1)
    await manager.broadcast_event(event2)

    # Wait for batch
    await asyncio.sleep(0.07)

    assert len(ws.messages) == 1
    batch = json.loads(ws.messages[0])
    assert batch["count"] == 2
    assert batch["events"][0]["event_type"] == "run_status_changed"
    assert batch["events"][1]["new_status"] == "completed"


async def test_batching_disconnect_cleans_up() -> None:
    """Disconnecting a websocket cleans up buffers and timers."""
    manager = BatchingConnectionManager(batch_window=10.0, batching_enabled=True)

    ws = MockWebSocket()
    await manager.connect("run-1", ws)  # type: ignore[arg-type]

    # Send event to start timer
    await manager.broadcast_to_run("run-1", {"seq": 1})

    # Verify internal state
    assert "run-1" in manager._event_buffers  # pyright: ignore[reportPrivateUsage]
    assert "run-1" in manager._timer_tasks  # pyright: ignore[reportPrivateUsage]

    # Disconnect
    manager.disconnect("run-1", ws)  # type: ignore[arg-type]

    # Verify cleanup
    assert "run-1" not in manager._event_buffers  # pyright: ignore[reportPrivateUsage]
    assert "run-1" not in manager._timer_tasks  # pyright: ignore[reportPrivateUsage]


async def test_batching_respects_per_client_throttle() -> None:
    """Batched messages still respect the per-client throttle from parent class."""
    manager = BatchingConnectionManager(batch_window=0.05, batching_enabled=True)

    ws = MockWebSocket()
    await manager.connect("run-1", ws)  # type: ignore[arg-type]

    # First batch
    await manager.broadcast_to_run("run-1", {"batch": 1})
    await asyncio.sleep(0.06)  # Wait for first batch to send

    assert len(ws.messages) == 1

    # Second batch immediately after - should be throttled
    await manager.broadcast_to_run("run-1", {"batch": 2})
    await asyncio.sleep(0.06)  # Wait for batch window

    # Should still only have one message (second was throttled)
    assert len(ws.messages) == 1

    # Throttle has already passed (0.12s elapsed since first send > 0.1s throttle)
    # Third batch should go through
    await manager.broadcast_to_run("run-1", {"batch": 3})
    await asyncio.sleep(0.06)

    # Should now have two messages total
    assert len(ws.messages) == 2
    batch3 = json.loads(ws.messages[1])
    assert batch3["events"][0]["batch"] == 3
