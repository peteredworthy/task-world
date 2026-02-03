"""Event store for persisting workflow events."""

import dataclasses
import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.models import EventModel
from orchestrator.workflow.events import WorkflowEvent


def _serialize_event(event: WorkflowEvent) -> dict[str, Any]:
    """Serialize a WorkflowEvent to a JSON-compatible dict."""
    data = dataclasses.asdict(event)
    # Convert enums and datetimes via JSON round-trip
    return json.loads(json.dumps(data, default=str))


class EventStore:
    """Persistent storage for workflow events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: WorkflowEvent) -> None:
        """Persist a single event."""
        model = EventModel(
            run_id=event.run_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            payload=_serialize_event(event),
        )
        self._session.add(model)
        await self._session.flush()

    async def append_batch(self, events: Sequence[WorkflowEvent]) -> None:
        """Persist a batch of events."""
        models = [
            EventModel(
                run_id=event.run_id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                payload=_serialize_event(event),
            )
            for event in events
        ]
        self._session.add_all(models)
        await self._session.flush()

    async def get_events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Get all events for a run in order."""
        result = await self._session.execute(
            select(EventModel).where(EventModel.run_id == run_id).order_by(EventModel.id)
        )
        return [
            {"type": e.event_type, "timestamp": e.timestamp, "payload": e.payload}
            for e in result.scalars()
        ]
