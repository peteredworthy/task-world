"""Integration tests for WebSocket support."""

import json
import time
from datetime import datetime, timezone

from starlette.testclient import TestClient

from orchestrator.api.app import create_app
from orchestrator.api.websocket import ConnectionManager
from orchestrator.config.enums import RunStatus
from orchestrator.workflow.events import RunStatusChanged


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
    # No connections, should not fail
    await manager.broadcast_event(event)


def test_websocket_connect_disconnect() -> None:
    """Test basic WebSocket connect and disconnect."""
    app = create_app(db_path=":memory:")

    # Use Starlette's sync TestClient for WebSocket testing
    with TestClient(app) as client:
        with client.websocket_connect("/ws/runs/run-1"):
            # Connection established - just close cleanly
            pass


def test_websocket_receives_broadcast() -> None:
    """Test that a connected WebSocket receives broadcast messages."""
    app = create_app(db_path=":memory:")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/runs/run-1") as ws:
            manager: ConnectionManager = app.state.connection_manager

            # Run broadcast in a sync-friendly way
            import asyncio

            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                manager.broadcast_to_run("run-1", {"event": "test", "data": "hello"})
            )
            loop.close()

            data = ws.receive_text()
            parsed = json.loads(data)
            assert parsed["event"] == "test"
            assert parsed["data"] == "hello"


def test_websocket_cross_run_isolation() -> None:
    """Messages for run-1 should not be sent to run-2 subscribers."""
    app = create_app(db_path=":memory:")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/runs/run-1") as ws1:
            manager: ConnectionManager = app.state.connection_manager

            # Broadcast to run-2 (ws1 is on run-1)
            import asyncio

            loop = asyncio.new_event_loop()
            loop.run_until_complete(manager.broadcast_to_run("run-2", {"event": "for-run-2"}))
            # Also broadcast to run-1 so ws1 gets something
            loop.run_until_complete(manager.broadcast_to_run("run-1", {"event": "for-run-1"}))
            loop.close()

            data = ws1.receive_text()
            parsed = json.loads(data)
            # ws1 should only get the run-1 message
            assert parsed["event"] == "for-run-1"


def test_multiple_subscribers() -> None:
    """Multiple WebSocket clients for the same run all receive broadcasts."""
    app = create_app(db_path=":memory:")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/runs/run-1") as ws1:
            with client.websocket_connect("/ws/runs/run-1") as ws2:
                manager: ConnectionManager = app.state.connection_manager

                import asyncio

                loop = asyncio.new_event_loop()
                loop.run_until_complete(manager.broadcast_to_run("run-1", {"event": "hello"}))
                loop.close()

                data1 = json.loads(ws1.receive_text())
                data2 = json.loads(ws2.receive_text())
                assert data1["event"] == "hello"
                assert data2["event"] == "hello"


def test_per_client_throttle() -> None:
    """Each client is throttled independently — rapid broadcasts are dropped per client."""
    app = create_app(db_path=":memory:")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/runs/run-1") as ws:
            manager: ConnectionManager = app.state.connection_manager

            import asyncio

            loop = asyncio.new_event_loop()

            # First broadcast should go through
            loop.run_until_complete(manager.broadcast_to_run("run-1", {"seq": 1}))
            data = json.loads(ws.receive_text())
            assert data["seq"] == 1

            # Second broadcast immediately after should be throttled (dropped)
            loop.run_until_complete(manager.broadcast_to_run("run-1", {"seq": 2}))

            # Wait for throttle interval to pass
            time.sleep(0.15)

            # Third broadcast should go through after the throttle window
            loop.run_until_complete(manager.broadcast_to_run("run-1", {"seq": 3}))
            data = json.loads(ws.receive_text())
            # Should receive seq 3, not seq 2 (which was dropped)
            assert data["seq"] == 3

            loop.close()


def test_per_client_throttle_independent() -> None:
    """Two clients on the same run throttle independently."""
    app = create_app(db_path=":memory:")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/runs/run-1") as ws1:
            manager: ConnectionManager = app.state.connection_manager

            import asyncio

            loop = asyncio.new_event_loop()

            # Broadcast to establish ws1's throttle timestamp
            loop.run_until_complete(manager.broadcast_to_run("run-1", {"seq": 1}))
            data1 = json.loads(ws1.receive_text())
            assert data1["seq"] == 1

            # Wait for throttle to pass for ws1
            time.sleep(0.15)

            # Now connect ws2 — it has no throttle history yet
            with client.websocket_connect("/ws/runs/run-1") as ws2:
                # Both clients should receive this broadcast:
                # ws1 because throttle has passed, ws2 because it's new
                loop.run_until_complete(manager.broadcast_to_run("run-1", {"seq": 2}))
                d1 = json.loads(ws1.receive_text())
                d2 = json.loads(ws2.receive_text())
                assert d1["seq"] == 2
                assert d2["seq"] == 2

            loop.close()
