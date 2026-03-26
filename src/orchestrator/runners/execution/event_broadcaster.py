"""Event emission helpers (persist + WebSocket broadcast).

Extracted from ``AgentRunnerExecutor`` -- preserves the original semantics
where each event opens its own DB session and broadcasts independently of
persistence success.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from orchestrator.workflow import (
    AgentErrorEvent,
    WorkflowEvent,
)
from orchestrator.runners.types import BroadcastCallback

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from orchestrator.state.models import TaskState

logger = logging.getLogger(__name__)


class EventBroadcaster:
    """Persist workflow events to the DB and broadcast via WebSocket."""

    def __init__(
        self,
        session_factory: "async_sessionmaker[AsyncSession]",
        connection_manager: BroadcastCallback | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._connection_manager = connection_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def emit_log_event(self, event: WorkflowEvent) -> None:
        """Persist a log event and broadcast via WebSocket."""
        try:
            async with self._session_factory() as session:
                from orchestrator.db import EventStore

                store = EventStore(session)
                await store.append(event)
                await session.commit()
        except Exception:
            logger.debug(f"Failed to persist log event: {event.event_type}", exc_info=True)

        # Broadcast to WebSocket subscribers regardless of persistence success
        if self._connection_manager is not None:
            try:
                await self._connection_manager.broadcast_event(event)
            except Exception:
                logger.debug(f"Failed to broadcast log event: {event.event_type}", exc_info=True)

    async def emit_health_check_event(self, run_id: str, phase: str, message: str) -> None:
        """Emit a health check event (started/completed/failed)."""
        from orchestrator.workflow import HealthCheckEvent

        event = HealthCheckEvent(
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            event_type="health_check",
            phase=phase,
            message=message,
        )
        await self.emit_log_event(event)

    async def emit_error_event(
        self, run_id: str, task_state: "TaskState", error_type: str, message: str
    ) -> None:
        """Emit an AgentErrorEvent."""
        attempt_num = task_state.current_attempt if task_state.attempts else 0
        event = AgentErrorEvent(
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            event_type="agent_error",
            task_id=task_state.id,
            attempt_num=attempt_num,
            error_type=error_type,
            error_message=message,
        )
        await self.emit_log_event(event)
