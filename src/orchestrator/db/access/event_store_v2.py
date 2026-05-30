"""Unified event store backed by the events_v2 SQLite table."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.access.concurrency import ConcurrencyStrategy, RetryWithBackoff
from orchestrator.db.access.event_outbox import EventOutboxObserver, queue_event_outbox
from orchestrator.db.orm.models import EventV2Model
from orchestrator.time_utils import format_utc_datetime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from orchestrator.workflow import WorkflowEvent


@dataclasses.dataclass(frozen=True)
class StoredEvent:
    position: int
    aggregate_id: str
    event_type: str
    payload: str  # raw JSON string
    timestamp: str  # ISO 8601
    version: int


class ActivityEventRow(TypedDict):
    id: int
    event_type: str
    timestamp: datetime
    payload: dict[str, Any]


@runtime_checkable
class EventStore(Protocol):
    async def append(self, events: Sequence[WorkflowEvent]) -> list[StoredEvent]: ...
    async def get_stream(self, aggregate_id: str) -> list[StoredEvent]: ...
    async def get_all(self, after_position: int = 0) -> list[StoredEvent]: ...
    async def get_events_paginated(
        self,
        run_id: str,
        *,
        after: int | None = None,
        limit: int = 200,
        event_type: str | None = None,
    ) -> list[ActivityEventRow]: ...


class SqliteEventStore:
    """EventStore backed by the events_v2 table with optimistic concurrency."""

    def __init__(
        self,
        session: AsyncSession,
        concurrency: ConcurrencyStrategy | None = None,
    ) -> None:
        self._session = session
        self._concurrency = concurrency or RetryWithBackoff()
        self._listeners: list[EventOutboxObserver] = []
        self._projection_listeners: list[Callable[..., Awaitable[None]]] = []

    def add_listener(self, listener: EventOutboxObserver) -> None:
        """Register a post-commit secondary output listener."""
        self._listeners.append(listener)

    def add_projection_listener(self, listener: "Callable[..., Awaitable[None]]") -> None:
        """Register a listener that receives (stored_events, session, workflow_events)."""
        self._projection_listeners.append(listener)

    async def append(self, events: "WorkflowEvent | Sequence[WorkflowEvent]") -> list[StoredEvent]:
        """Append events with optimistic concurrency control.

        Accepts either a single WorkflowEvent or a sequence, so that
        PersistentEventEmitter (which calls append(single_event)) works
        unchanged during the transition period.
        """
        if isinstance(events, (list, tuple)):
            _events: list[WorkflowEvent] = list(events)  # type: ignore[assignment]
        else:
            _events = [events]  # type: ignore[list-item]

        async def _do_append() -> list[EventV2Model]:
            aggregate_ids = {e.run_id for e in _events}
            versions: dict[str, int] = {}
            for agg_id in aggregate_ids:
                result = await self._session.execute(
                    select(EventV2Model.version)
                    .where(EventV2Model.aggregate_id == agg_id)
                    .order_by(EventV2Model.version.desc())
                    .limit(1)
                )
                row: int | None = result.scalar_one_or_none()
                versions[agg_id] = row or 0

            new_models: list[EventV2Model] = []
            for event in _events:
                versions[event.run_id] += 1
                new_models.append(
                    EventV2Model(
                        aggregate_id=event.run_id,
                        event_type=event.event_type,
                        payload=event.model_dump_json(),
                        timestamp=format_utc_datetime(event.timestamp),
                        version=versions[event.run_id],
                    )
                )
            self._session.add_all(new_models)
            try:
                await self._session.flush()
            except Exception:
                # Roll back so the failed models are expelled from the session
                # before the retry.  Without this, pending objects accumulate
                # across attempts and replay the same version conflict every time.
                await self._session.rollback()
                raise
            return new_models

        models = await self._concurrency.execute_with_retry(_do_append)

        stored = [
            StoredEvent(
                position=m.position,
                aggregate_id=m.aggregate_id,
                event_type=m.event_type,
                payload=m.payload,
                timestamp=m.timestamp,
                version=m.version,
            )
            for m in models
        ]
        for listener in self._projection_listeners:
            await listener(stored, self._session, _events)
        for listener in self._listeners:
            queue_event_outbox(self._session, listener, stored)
        return stored

    async def get_stream(self, aggregate_id: str) -> list[StoredEvent]:
        """Return all stored events for an aggregate in position order."""
        result = await self._session.execute(
            select(EventV2Model)
            .where(EventV2Model.aggregate_id == aggregate_id)
            .order_by(EventV2Model.position)
        )
        return [_to_stored(m) for m in result.scalars()]

    async def get_all(self, after_position: int = 0) -> list[StoredEvent]:
        """Return all events after a global position cursor."""
        result = await self._session.execute(
            select(EventV2Model)
            .where(EventV2Model.position > after_position)
            .order_by(EventV2Model.position)
        )
        return [_to_stored(m) for m in result.scalars()]

    async def get_events_paginated(
        self,
        run_id: str,
        *,
        after: int | None = None,
        limit: int = 200,
        event_type: str | None = None,
    ) -> list[ActivityEventRow]:
        """Return activity-feed rows for a run from events_v2.

        The public activity cursor is ``events_v2.position`` so clients can
        resume monotonically across rows written only to the v2 event store.
        """
        stmt = select(EventV2Model).where(EventV2Model.aggregate_id == run_id)

        if after is not None:
            stmt = stmt.where(EventV2Model.position > after)

        if event_type is not None:
            stmt = stmt.where(EventV2Model.event_type == event_type)

        stmt = stmt.order_by(EventV2Model.position).limit(limit)

        result = await self._session.execute(stmt)
        return [_to_activity_row(m) for m in result.scalars()]

    async def append_batch(self, events: "Sequence[WorkflowEvent]") -> list[StoredEvent]:
        """Compatibility alias for append(); used by PersistentEventEmitter.emit_batch."""
        return await self.append(events)


def create_wired_event_store_v2(
    session: "AsyncSession",
    *,
    include_outbox: bool = True,
) -> SqliteEventStore:
    """Create a SqliteEventStore with outbox and projection listeners attached."""
    from orchestrator.db.access.jsonl_outbox import (
        JsonlOutboxObserver,
        resolve_default_journal_path_from_session,
    )
    from orchestrator.db.projections import (
        ProjectionRegistry,
        RunLifecycleProjector,
        RunStateProjector,
        TaskStateProjector,
    )

    store = SqliteEventStore(session)
    journal_path = resolve_default_journal_path_from_session(session)
    if include_outbox and journal_path is not None:
        store.add_listener(JsonlOutboxObserver(journal_path))

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    registry.register(RunLifecycleProjector())
    store.add_projection_listener(registry)
    return store


def _to_stored(m: EventV2Model) -> StoredEvent:
    return StoredEvent(
        position=m.position,
        aggregate_id=m.aggregate_id,
        event_type=m.event_type,
        payload=m.payload,
        timestamp=m.timestamp,
        version=m.version,
    )


def _to_activity_row(m: EventV2Model) -> ActivityEventRow:
    payload = json.loads(m.payload)
    if not isinstance(payload, dict):
        payload = {}
    return {
        "id": m.position,
        "event_type": m.event_type,
        "timestamp": datetime.fromisoformat(m.timestamp.replace("Z", "+00:00")),
        "payload": payload,
    }
