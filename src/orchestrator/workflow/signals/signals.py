"""Signal queue for workflow control signals.

Provides an event-backed signal queue that allows external callers (API routes)
to send control signals (pause/resume/cancel) to active RunWorkflow instances.

The transport is abstracted so that the event polling implementation can be
replaced with PostgreSQL LISTEN/NOTIFY without changing worker code.
"""

from __future__ import annotations

import enum
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orchestrator.db import SqliteEventStore
    from orchestrator.db import RunLifecycleProjector


class WorkflowSignal(enum.Enum):
    """Control signals that can be sent to an active RunWorkflow."""

    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    ACTIVITY_COMPLETED = "activity_completed"
    ACTIVITY_VERIFIED = "activity_verified"
    RUN_START = "run_start"


@dataclass
class PendingSignal:
    """A signal pending consumption by a RunWorkflow."""

    id: int
    run_id: str
    signal_type: WorkflowSignal
    payload: dict[str, Any] | None
    created_at: datetime
    delivered_at: datetime | None = field(default=None)
    handled_at: datetime | None = field(default=None)


class SignalTransport(ABC):
    """Abstract transport for signal queue operations.

    Implementations can use DB polling (default) or PostgreSQL LISTEN/NOTIFY
    for lower-latency delivery — worker code remains unchanged either way.
    """

    @abstractmethod
    async def enqueue(
        self,
        run_id: str,
        signal_type: WorkflowSignal,
        payload: dict[str, Any] | None = None,
    ) -> PendingSignal:
        """Persist a new signal for the given run."""
        ...

    @abstractmethod
    async def drain(self, run_id: str) -> list[PendingSignal]:
        """Return all unprocessed signals for run_id in FIFO order.

        Marks each returned signal as processed so it is consumed exactly once.
        """
        ...


class InMemorySignalTransport(SignalTransport):
    """In-memory signal transport for testing. Stores signals in a list."""

    def __init__(self) -> None:
        self._queue: list[PendingSignal] = []
        self._next_id: int = 1

    async def enqueue(
        self,
        run_id: str,
        signal_type: WorkflowSignal,
        payload: dict[str, Any] | None = None,
    ) -> PendingSignal:
        now = datetime.now(timezone.utc)
        signal = PendingSignal(
            id=self._next_id,
            run_id=run_id,
            signal_type=signal_type,
            payload=payload,
            created_at=now,
            delivered_at=None,
            handled_at=None,
        )
        self._next_id += 1
        self._queue.append(signal)
        return signal

    async def drain(self, run_id: str) -> list[PendingSignal]:
        now = datetime.now(timezone.utc)
        pending = [s for s in self._queue if s.run_id == run_id and s.handled_at is None]
        result: list[PendingSignal] = []
        for signal in pending:
            signal.handled_at = now
            result.append(signal)
        return result


class SignalForInactiveRunError(Exception):
    """Raised when a signal is enqueued for a run in a terminal state."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"Run {run_id!r} is in a terminal state and cannot receive signals")
        self.run_id = run_id


class EventSignalTransport(SignalTransport):
    """Event-sourced signal transport backed by the events_v2 table.

    enqueue() appends a SignalEnqueued event; drain() queries for unprocessed
    SignalEnqueued events and appends SignalProcessed events to mark them
    consumed.
    """

    def __init__(
        self,
        event_store: SqliteEventStore,
        projector: RunLifecycleProjector,
        *,
        projector_preloaded: bool = False,
    ) -> None:
        self._store = event_store
        self._projector = projector
        self._projector_rebuilt = projector_preloaded

    async def _ensure_projector_rebuilt(self) -> None:
        """Hydrate the lifecycle projector from existing run status events."""
        if self._projector_rebuilt:
            return

        from sqlalchemy import select

        from orchestrator.db import EventV2Model
        from orchestrator.workflow import deserialize_event
        from orchestrator.workflow import RunStatusChanged

        session = self._store._session  # pyright: ignore[reportPrivateUsage]
        result = await session.execute(
            select(EventV2Model)
            .where(EventV2Model.event_type == "run_status_changed")
            .order_by(EventV2Model.position)
        )

        events: list[RunStatusChanged] = []
        for row in result.scalars():
            event = deserialize_event(row.event_type, row.payload)
            if isinstance(event, RunStatusChanged):
                events.append(event)

        await self._projector.rebuild(events, session)
        self._projector_rebuilt = True

    async def enqueue(
        self,
        run_id: str,
        signal_type: WorkflowSignal,
        payload: dict[str, Any] | None = None,
    ) -> PendingSignal:
        await self._ensure_projector_rebuilt()
        if self._projector.is_terminal(run_id):
            raise SignalForInactiveRunError(run_id)

        from orchestrator.workflow import SignalEnqueued

        now = datetime.now(timezone.utc)
        event = SignalEnqueued(
            run_id=run_id,
            event_type="signal_enqueued",
            signal_type=signal_type.value,
            payload=payload,
            timestamp=now,
        )
        stored = await self._store.append([event])
        return PendingSignal(
            id=stored[0].position,
            run_id=run_id,
            signal_type=signal_type,
            payload=payload,
            created_at=now,
        )

    async def drain(self, run_id: str) -> list[PendingSignal]:
        from sqlalchemy import select

        from orchestrator.db import EventV2Model

        session = self._store._session  # pyright: ignore[reportPrivateUsage]

        # Fetch all SignalEnqueued events for this run (FIFO order)
        result = await session.execute(
            select(EventV2Model)
            .where(
                EventV2Model.aggregate_id == run_id,
                EventV2Model.event_type == "signal_enqueued",
            )
            .order_by(EventV2Model.position)
        )
        enqueued_rows = list(result.scalars())

        if not enqueued_rows:
            return []

        # Fetch all SignalProcessed events for this run
        result2 = await session.execute(
            select(EventV2Model.payload).where(
                EventV2Model.aggregate_id == run_id,
                EventV2Model.event_type == "signal_processed",
            )
        )
        processed_positions = self._processed_positions(list(result2.scalars()))

        # Filter to unprocessed signals
        unprocessed = [e for e in enqueued_rows if e.position not in processed_positions]

        if not unprocessed:
            return []

        await self.mark_processed(run_id, [e.position for e in unprocessed])
        return self._signals_from_rows(run_id, unprocessed)

    async def pending(self, run_id: str) -> list[PendingSignal]:
        """Return unprocessed signals for run_id in FIFO order without acknowledging them."""
        from sqlalchemy import select

        from orchestrator.db import EventV2Model

        session = self._store._session  # pyright: ignore[reportPrivateUsage]

        result = await session.execute(
            select(EventV2Model)
            .where(
                EventV2Model.aggregate_id == run_id,
                EventV2Model.event_type == "signal_enqueued",
            )
            .order_by(EventV2Model.position)
        )
        enqueued_rows = list(result.scalars())

        if not enqueued_rows:
            return []

        result2 = await session.execute(
            select(EventV2Model.payload).where(
                EventV2Model.aggregate_id == run_id,
                EventV2Model.event_type == "signal_processed",
            )
        )
        processed_positions = self._processed_positions(list(result2.scalars()))
        unprocessed = [e for e in enqueued_rows if e.position not in processed_positions]
        return self._signals_from_rows(run_id, unprocessed)

    async def mark_processed(self, run_id: str, positions: int | list[int]) -> None:
        """Append SignalProcessed events for unprocessed enqueued positions."""
        from sqlalchemy import select

        from orchestrator.db import EventV2Model
        from orchestrator.workflow import SignalProcessed

        requested_positions = [positions] if isinstance(positions, int) else positions
        if not requested_positions:
            return

        session = self._store._session  # pyright: ignore[reportPrivateUsage]
        result = await session.execute(
            select(EventV2Model.payload).where(
                EventV2Model.aggregate_id == run_id,
                EventV2Model.event_type == "signal_processed",
            )
        )
        processed_positions = self._processed_positions(list(result.scalars()))
        unprocessed_positions = [
            position for position in requested_positions if position not in processed_positions
        ]
        if not unprocessed_positions:
            return

        now = datetime.now(timezone.utc)
        processed_events = [
            SignalProcessed(
                run_id=run_id,
                event_type="signal_processed",
                enqueued_position=position,
                timestamp=now,
            )
            for position in unprocessed_positions
        ]
        await self._store.append(processed_events)

    def _processed_positions(self, processed_payloads: list[str]) -> set[int]:
        processed_positions: set[int] = set()
        for p in processed_payloads:
            try:
                data = json.loads(p)
                pos = data.get("enqueued_position")
                if isinstance(pos, int):
                    processed_positions.add(pos)
            except (json.JSONDecodeError, AttributeError):
                pass
        return processed_positions

    def _signals_from_rows(self, run_id: str, rows: list[Any]) -> list[PendingSignal]:
        now = datetime.now(timezone.utc)
        signals: list[PendingSignal] = []
        for e in rows:
            payload_data = json.loads(e.payload)
            raw_signal_type = payload_data.get("signal_type", "")
            try:
                sig_type = WorkflowSignal(raw_signal_type)
            except ValueError:
                continue
            sig_payload = payload_data.get("payload")
            try:
                created_at = datetime.fromisoformat(e.timestamp)
            except ValueError:
                created_at = now
            signals.append(
                PendingSignal(
                    id=e.position,
                    run_id=run_id,
                    signal_type=sig_type,
                    payload=sig_payload,
                    created_at=created_at,
                )
            )

        return signals


class SignalQueue:
    """High-level signal queue with pluggable transport.

    Wraps a SignalTransport to provide a stable API for enqueueing and
    draining signals.  Swap the transport (DB polling → LISTEN/NOTIFY)
    without touching callers.
    """

    def __init__(self, transport: SignalTransport) -> None:
        self._transport = transport

    async def enqueue(
        self,
        run_id: str,
        signal_type: WorkflowSignal,
        payload: dict[str, Any] | None = None,
    ) -> PendingSignal:
        """Enqueue a control signal for the given run."""
        return await self._transport.enqueue(run_id, signal_type, payload)

    async def drain(self, run_id: str) -> list[PendingSignal]:
        """Return and consume all unprocessed signals for run_id (FIFO order).

        Delegates to the transport which marks each signal's processed_at
        timestamp to guarantee exactly-once consumption.
        """
        return await self._transport.drain(run_id)
