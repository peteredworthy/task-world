"""In-memory event store for execution graph tests and scenario fixtures."""

from collections import defaultdict

from orchestrator.graph.models import EventEnvelope


class DuplicateEventError(ValueError):
    """Raised when an event would reuse a run-local stream position."""


class InMemoryEventStore:
    """Append-only in-memory event store keyed by run ID."""

    def __init__(self) -> None:
        self._events_by_run: dict[str, list[EventEnvelope]] = defaultdict(list)
        self._positions: set[tuple[str, int]] = set()

    def append(self, event: EventEnvelope) -> EventEnvelope:
        position = event.position
        if position < 0:
            position = self.snapshot_position(event.run_id) + 1
        key = (event.run_id, position)
        if key in self._positions:
            msg = f"Duplicate event position for run {event.run_id}: {position}"
            raise DuplicateEventError(msg)

        stored = event.model_copy(update={"position": position})
        self._events_by_run[event.run_id].append(stored)
        self._positions.add(key)
        return stored

    def read_from(self, run_id: str, from_position: int = 0) -> list[EventEnvelope]:
        return [
            event
            for event in self._events_by_run.get(run_id, [])
            if event.position >= from_position
        ]

    def snapshot_position(self, run_id: str) -> int:
        events = self._events_by_run.get(run_id, [])
        if not events:
            return -1
        return max(event.position for event in events)
