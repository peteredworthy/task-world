"""Persistent event emitter for workflow events."""

from collections.abc import Callable, Sequence

from orchestrator.db import EventStore
from orchestrator.workflow.events import WorkflowEvent


class PersistentEventEmitter:
    """EventEmitter that persists events to database.

    Persists each event via the EventStore, then notifies registered listeners.
    Listeners are synchronous callbacks (e.g. for WebSocket broadcast scheduling).
    """

    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store
        self._listeners: list[Callable[[WorkflowEvent], None]] = []

    def add_listener(self, listener: Callable[[WorkflowEvent], None]) -> None:
        """Register a listener to be notified after each event is persisted."""
        self._listeners.append(listener)

    async def emit(self, event: WorkflowEvent) -> None:
        """Persist event then notify listeners."""
        await self._store.append(event)
        for listener in self._listeners:
            listener(event)

    async def emit_batch(self, events: Sequence[WorkflowEvent]) -> None:
        """Persist a batch of events then notify listeners for each."""
        if events:
            await self._store.append_batch(events)
            for event in events:
                for listener in self._listeners:
                    listener(event)
