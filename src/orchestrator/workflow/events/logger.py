"""Persistent events_v2 emitter for workflow events."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from orchestrator.workflow.events import WorkflowEvent


class PersistentEventEmitter:
    """EventEmitter that persists events to events_v2.

    Persists each event via SqliteEventStore, then notifies registered listeners.
    Listeners are synchronous callbacks (e.g. for WebSocket broadcast scheduling).
    """

    def __init__(
        self,
        event_store: Any,
    ) -> None:
        self._store = event_store
        self._listeners: list[Callable[[WorkflowEvent], None]] = []

    def add_listener(self, listener: Callable[[WorkflowEvent], None]) -> None:
        """Register a listener to be notified after each event is persisted."""
        self._listeners.append(listener)

    async def emit(self, event: WorkflowEvent) -> None:
        """Persist event then notify listeners."""
        await self._store.append(event)
        self.notify_persisted(event)

    def notify_persisted(self, event: WorkflowEvent) -> None:
        """Notify listeners for an event already persisted by another writer."""
        for listener in self._listeners:
            listener(event)

    async def emit_batch(self, events: Sequence[WorkflowEvent]) -> None:
        """Persist a batch of events then notify listeners for each."""
        if events:
            if hasattr(self._store, "append_batch"):
                await self._store.append_batch(list(events))
            else:
                await self._store.append(list(events))
            self.notify_persisted_batch(events)

    def notify_persisted_batch(self, events: Sequence[WorkflowEvent]) -> None:
        """Notify listeners for events already persisted by another writer."""
        for event in events:
            self.notify_persisted(event)
