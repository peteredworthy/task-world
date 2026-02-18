"""WebSocket connection management for real-time event streaming."""

import asyncio
import dataclasses
import json
import logging
import time
from datetime import datetime
from typing import Any

from fastapi import WebSocket
from orchestrator.workflow.events import ClarificationRequested, ClarificationResponded

# Maximum updates per second per client (throttle interval in seconds)
_THROTTLE_INTERVAL = 0.1  # 10 updates/sec

# Default batch window for batching manager (in seconds)
_DEFAULT_BATCH_WINDOW = 0.1  # 100ms


def _json_default(obj: object) -> str:
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "value"):
        return obj.value  # type: ignore[return-value]
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class ConnectionManager:
    """Manages WebSocket connections with per-run subscriptions and per-client throttling.

    Throttling: At most 10 updates per second per client. If broadcast_to_run is
    called more frequently, the message is dropped for that client. Callers that
    need guaranteed delivery should read from the event store instead.
    """

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self._last_send_time: dict[int, float] = {}

    async def connect(self, run_id: str, websocket: WebSocket) -> None:
        """Accept and register a WebSocket for a run."""
        await websocket.accept()
        if run_id not in self._connections:
            self._connections[run_id] = []
        self._connections[run_id].append(websocket)

    def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket from a run's subscribers."""
        self._last_send_time.pop(id(websocket), None)
        if run_id in self._connections:
            self._connections[run_id] = [
                ws for ws in self._connections[run_id] if ws is not websocket
            ]
            if not self._connections[run_id]:
                del self._connections[run_id]

    async def broadcast_to_run(self, run_id: str, data: dict[str, Any]) -> None:
        """Send data to all WebSocket subscribers for a run.

        Respects the per-client throttle interval — drops messages if called too frequently
        for a given client.
        """
        if run_id not in self._connections:
            return

        now = time.monotonic()
        dead: list[WebSocket] = []
        for ws in self._connections[run_id]:
            ws_id = id(ws)
            last = self._last_send_time.get(ws_id, 0.0)
            if now - last < _THROTTLE_INTERVAL:
                continue  # throttled for this client

            self._last_send_time[ws_id] = now
            try:
                await ws.send_text(json.dumps(data, default=_json_default))
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(run_id, ws)

    async def broadcast_event(self, event: object) -> None:
        """Broadcast a WorkflowEvent to the relevant run's subscribers."""
        if not dataclasses.is_dataclass(event) or isinstance(event, type):
            logging.getLogger(__name__).debug(
                "broadcast_event called with non-dataclass event: %s", type(event).__name__
            )
            return

        if isinstance(event, ClarificationRequested):
            data = {
                "event_type": "clarification_requested",
                "run_id": event.run_id,
                "task_id": event.task_id,
                "request_id": event.request_id,
                "question_count": event.question_count,
            }
            await self.broadcast_to_run(event.run_id, data)
            return

        if isinstance(event, ClarificationResponded):
            data = {
                "event_type": "clarification_responded",
                "run_id": event.run_id,
                "task_id": event.task_id,
                "request_id": event.request_id,
            }
            await self.broadcast_to_run(event.run_id, data)
            return

        data: dict[str, Any] = dataclasses.asdict(event)
        run_id = data.get("run_id", "")
        if run_id:
            await self.broadcast_to_run(run_id, data)


class BatchingConnectionManager(ConnectionManager):
    """ConnectionManager with optional event batching to reduce message floods.

    When batching is enabled, events are collected in a time window (default 100ms)
    and sent as a batch, reducing the number of WebSocket messages under heavy load.

    Batching is per-run and configurable. When disabled, behaves identically to
    ConnectionManager (immediate broadcast with throttling).
    """

    def __init__(
        self, batch_window: float = _DEFAULT_BATCH_WINDOW, batching_enabled: bool = True
    ) -> None:
        super().__init__()
        self._batching_enabled = batching_enabled
        self._batch_window = batch_window
        # Per-run event buffers
        self._event_buffers: dict[str, list[dict[str, Any]]] = {}
        # Per-run timer tasks
        self._timer_tasks: dict[str, asyncio.Task[None]] = {}
        # Lock for thread-safe buffer access
        self._buffer_lock = asyncio.Lock()

    async def broadcast_to_run(self, run_id: str, data: dict[str, Any]) -> None:
        """Send data to all WebSocket subscribers for a run.

        If batching is enabled, adds the event to the buffer and starts/resets the timer.
        If batching is disabled, broadcasts immediately (same as parent class).
        """
        if not self._batching_enabled:
            await super().broadcast_to_run(run_id, data)
            return

        async with self._buffer_lock:
            # Add event to buffer
            if run_id not in self._event_buffers:
                self._event_buffers[run_id] = []
            self._event_buffers[run_id].append(data)

            # Start timer if not already running for this run
            if run_id not in self._timer_tasks or self._timer_tasks[run_id].done():
                self._timer_tasks[run_id] = asyncio.create_task(self._flush_after_window(run_id))

    async def _flush_after_window(self, run_id: str) -> None:
        """Wait for the batch window to expire, then flush all buffered events for a run."""
        await asyncio.sleep(self._batch_window)

        async with self._buffer_lock:
            events = self._event_buffers.get(run_id, [])
            if not events:
                return

            # Clear buffer before sending
            self._event_buffers[run_id] = []

            # Remove completed timer task
            if run_id in self._timer_tasks:
                del self._timer_tasks[run_id]

        # Send batch - wrap events in a batch envelope
        batch_data = {
            "type": "batch",
            "run_id": run_id,
            "events": events,
            "count": len(events),
        }
        await super().broadcast_to_run(run_id, batch_data)

    async def flush_all(self) -> None:
        """Immediately flush all pending batches for all runs.

        Useful for graceful shutdown or testing.
        """
        async with self._buffer_lock:
            run_ids = list(self._event_buffers.keys())

        for run_id in run_ids:
            # Cancel any pending timer
            if run_id in self._timer_tasks and not self._timer_tasks[run_id].done():
                self._timer_tasks[run_id].cancel()
                try:
                    await self._timer_tasks[run_id]
                except asyncio.CancelledError:
                    pass

            async with self._buffer_lock:
                events = self._event_buffers.get(run_id, [])
                if not events:
                    continue

                self._event_buffers[run_id] = []
                if run_id in self._timer_tasks:
                    del self._timer_tasks[run_id]

            # Send batch
            batch_data = {
                "type": "batch",
                "run_id": run_id,
                "events": events,
                "count": len(events),
            }
            await super().broadcast_to_run(run_id, batch_data)

    def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket and clean up any pending timers if no subscribers remain."""
        super().disconnect(run_id, websocket)

        # If no connections remain for this run, cancel pending timer and clear buffer
        if run_id not in self._connections:
            if run_id in self._timer_tasks and not self._timer_tasks[run_id].done():
                self._timer_tasks[run_id].cancel()
            self._timer_tasks.pop(run_id, None)
            self._event_buffers.pop(run_id, None)
