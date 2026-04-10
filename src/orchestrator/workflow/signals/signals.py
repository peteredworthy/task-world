"""Signal queue for workflow control signals.

Provides a DB-backed signal queue that allows external callers (API routes)
to send control signals (pause/resume/cancel) to active RunWorkflow instances.

The transport is abstracted so that the DB polling implementation can be
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
    from sqlalchemy.ext.asyncio import AsyncSession


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


class DbSignalTransport(SignalTransport):
    """DB-polling signal transport.

    Uses SQLAlchemy async session to read/write the pending_signals table.
    Can be swapped for a LISTEN/NOTIFY transport without changing SignalQueue
    or RunWorkflow.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        run_id: str,
        signal_type: WorkflowSignal,
        payload: dict[str, Any] | None = None,
    ) -> PendingSignal:
        from orchestrator.db import PendingSignalModel

        now = datetime.now(timezone.utc)
        model = PendingSignalModel(
            run_id=run_id,
            signal_type=signal_type.value,
            payload=json.dumps(payload) if payload is not None else None,
            created_at=now,
            delivered_at=None,
            handled_at=None,
        )
        self._session.add(model)
        await self._session.flush()
        return PendingSignal(
            id=model.id,
            run_id=run_id,
            signal_type=signal_type,
            payload=payload,
            created_at=now,
            delivered_at=None,
            handled_at=None,
        )

    async def drain(self, run_id: str) -> list[PendingSignal]:
        from sqlalchemy import select

        from orchestrator.db import PendingSignalModel

        now = datetime.now(timezone.utc)
        stmt = (
            select(PendingSignalModel)
            .where(
                PendingSignalModel.run_id == run_id,
                PendingSignalModel.handled_at.is_(None),
            )
            .order_by(PendingSignalModel.id)
        )
        result = await self._session.execute(stmt)
        models = list(result.scalars().all())

        signals: list[PendingSignal] = []
        for model in models:
            model.handled_at = now
            payload = json.loads(model.payload) if model.payload is not None else None
            signals.append(
                PendingSignal(
                    id=model.id,
                    run_id=model.run_id,
                    signal_type=WorkflowSignal(model.signal_type),
                    payload=payload,
                    created_at=model.created_at,
                    delivered_at=model.delivered_at,
                    handled_at=now,
                )
            )

        if models:
            await self._session.flush()

        return signals


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
