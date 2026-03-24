"""Event store for persisting workflow events."""

import dataclasses
import json
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.recovery.event_journal import (
    JsonlEventJournal,
    make_journal_entry,
    resolve_default_journal_path_from_session,
)
from orchestrator.db.orm.models import EventModel
from orchestrator.time_utils import ensure_utc, format_utc_datetime
from orchestrator.workflow.events import WorkflowEvent

logger = logging.getLogger(__name__)


def _serialize_event(event: WorkflowEvent) -> dict[str, Any]:
    """Serialize a WorkflowEvent to a JSON-compatible dict."""
    data = dataclasses.asdict(event)

    # Convert enums and datetimes via JSON round-trip, preserving UTC timestamp shape.
    def _json_default(obj: object) -> str:
        if isinstance(obj, datetime):
            return format_utc_datetime(obj)
        if hasattr(obj, "value"):
            return obj.value  # type: ignore[return-value]
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    return json.loads(json.dumps(data, default=_json_default))


class EventStore:
    """Persistent storage for workflow events."""

    def __init__(self, session: AsyncSession, journal: JsonlEventJournal | None = None) -> None:
        self._session = session
        if journal is not None:
            self._journal = journal
        else:
            journal_path = resolve_default_journal_path_from_session(session)
            self._journal = JsonlEventJournal(journal_path) if journal_path is not None else None

    async def append(self, event: WorkflowEvent) -> None:
        """Persist a single event."""
        payload = _serialize_event(event)
        model = EventModel(
            run_id=event.run_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            payload=payload,
        )
        self._session.add(model)
        await self._session.flush()
        await self._append_journal_entries(
            [
                make_journal_entry(
                    run_id=event.run_id,
                    event_type=event.event_type,
                    timestamp=event.timestamp,
                    payload=payload,
                )
            ]
        )

    async def append_batch(self, events: Sequence[WorkflowEvent]) -> None:
        """Persist a batch of events."""
        serialized_payloads = [_serialize_event(event) for event in events]
        models = [
            EventModel(
                run_id=event.run_id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                payload=serialized_payloads[idx],
            )
            for idx, event in enumerate(events)
        ]
        self._session.add_all(models)
        await self._session.flush()
        await self._append_journal_entries(
            [
                make_journal_entry(
                    run_id=event.run_id,
                    event_type=event.event_type,
                    timestamp=event.timestamp,
                    payload=serialized_payloads[idx],
                )
                for idx, event in enumerate(events)
            ]
        )

    async def get_events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Get all events for a run in order."""
        result = await self._session.execute(
            select(EventModel).where(EventModel.run_id == run_id).order_by(EventModel.id)
        )
        return [
            {"type": e.event_type, "timestamp": ensure_utc(e.timestamp), "payload": e.payload}
            for e in result.scalars()
        ]

    async def get_events_paginated(
        self,
        run_id: str,
        *,
        after: int | None = None,
        limit: int = 200,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get events for a run with cursor pagination and optional filtering.

        Args:
            run_id: The run to query events for.
            after: Cursor — only return events with id > after.
            limit: Maximum number of events to return.
            event_type: If provided, only return events of this type.

        Returns:
            List of event dicts including the ``id`` field.
        """
        stmt = select(EventModel).where(EventModel.run_id == run_id)

        if after is not None:
            stmt = stmt.where(EventModel.id > after)

        if event_type is not None:
            stmt = stmt.where(EventModel.event_type == event_type)

        stmt = stmt.order_by(EventModel.id).limit(limit)

        result = await self._session.execute(stmt)
        return [
            {
                "id": e.id,
                "event_type": e.event_type,
                "timestamp": ensure_utc(e.timestamp),
                "payload": e.payload,
            }
            for e in result.scalars()
        ]

    async def _append_journal_entries(self, entries: list[dict[str, Any]]) -> None:
        if self._journal is None or not entries:
            return
        try:
            await self._journal.append_events(entries)
        except Exception as exc:
            # Journal is durability hardening; DB event persistence remains source
            # of truth for online operation when filesystem is unavailable.
            logger.warning("Failed to append to event journal: %s", exc)
