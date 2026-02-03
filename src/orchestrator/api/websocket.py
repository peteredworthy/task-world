"""WebSocket connection management for real-time event streaming."""

import dataclasses
import json
import time
from datetime import datetime
from typing import Any

from fastapi import WebSocket

# Maximum updates per second per client (throttle interval in seconds)
_THROTTLE_INTERVAL = 0.1  # 10 updates/sec


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
            return

        data: dict[str, Any] = dataclasses.asdict(event)
        run_id = data.get("run_id", "")
        if run_id:
            await self.broadcast_to_run(run_id, data)
