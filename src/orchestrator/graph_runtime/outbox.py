"""Graph outbox mapping and dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.db import GraphOutboxModel
from orchestrator.graph import EventEnvelope
from orchestrator.graph_runtime.errors import OutboxAppendError

OUTBOX_PENDING = "pending"
OUTBOX_DISPATCHING = "dispatching"
OUTBOX_COMPLETED = "completed"
OUTBOX_FAILED = "failed"


@dataclass(frozen=True)
class OutboxItem:
    outbox_id: int
    event_id: str
    run_id: str
    kind: str
    payload: dict[str, object]
    status: str
    attempts: int
    created_at: datetime
    updated_at: datetime
    last_error: str | None


class SideEffectExecutor(Protocol):
    """Executes an outbox side effect.

    Dispatch is at-least-once and keyed by ``event_id``. Implementations must
    be idempotent for repeated ``event_id`` values because a process can crash
    after the side effect starts but before the outbox row is marked completed.
    """

    async def dispatch(self, item: OutboxItem) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


def outbox_payload_for_event(event: EventEnvelope) -> tuple[str, dict[str, object]] | None:
    """Map accepted graph events to durable side-effect intent.

    The explicit slice-2.1 mapping is:
    ``agent_dispatch_requested`` -> ``agent_dispatch`` and
    ``cleanup_requested`` -> ``snapshot_cleanup``. Rejection/audit events
    intentionally return ``None`` so they are persisted facts only.
    """
    if event.event_type == "agent_dispatch_requested":
        payload: dict[str, object] = {
            "event_id": event.event_id,
            "run_id": event.run_id,
            "classification": "agent_dispatch_pending",
        }
        payload.update(event.payload)
        return "agent_dispatch", payload
    if event.event_type == "cleanup_requested":
        payload = {
            "event_id": event.event_id,
            "run_id": event.run_id,
            "classification": "snapshot_cleanup_pending",
        }
        payload.update(event.payload)
        return "snapshot_cleanup", payload
    return None


async def append_outbox_rows(
    session: AsyncSession,
    events: list[EventEnvelope],
    clock: Clock,
) -> list[OutboxItem]:
    """Insert outbox rows for side-effect-bearing events in the caller transaction."""
    rows: list[GraphOutboxModel] = []
    now = clock.now()
    for event in events:
        mapped = outbox_payload_for_event(event)
        if mapped is None:
            continue
        kind, payload = mapped
        rows.append(
            GraphOutboxModel(
                event_id=event.event_id,
                run_id=event.run_id,
                kind=kind,
                payload=payload,
                status=OUTBOX_PENDING,
                attempts=0,
                created_at=now,
                updated_at=now,
            )
        )

    if not rows:
        return []
    session.add_all(rows)
    try:
        await session.flush()
    except IntegrityError as exc:
        msg = "failed to append graph outbox rows"
        raise OutboxAppendError(msg) from exc
    return [_to_item(row) for row in rows]


class OutboxDispatcher:
    """Deterministic process-now dispatcher for graph outbox rows."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        executor: SideEffectExecutor,
        clock: Clock,
        *,
        max_attempts: int = 3,
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor
        self._clock = clock
        self._max_attempts = max_attempts

    async def dispatch_pending(
        self,
        limit: int | None = None,
        *,
        run_id: str | None = None,
    ) -> list[OutboxItem]:
        """Dispatch pending rows in outbox order and return completed items."""
        await self.reset_dispatching_to_pending(run_id=run_id)
        completed: list[OutboxItem] = []
        remaining = limit
        while True:
            item = await self._claim_next(remaining, run_id=run_id)
            if item is None:
                return completed
            try:
                await self._executor.dispatch(item)
            except Exception as exc:
                await self._mark_failed_attempt(item, exc)
            else:
                completed.append(await self._mark_completed(item))
            if remaining is not None:
                remaining -= 1
                if remaining <= 0:
                    return completed

    async def reset_dispatching_to_pending(self, *, run_id: str | None = None) -> int:
        """Treat startup ``dispatching`` rows as pending for at-least-once retry."""
        async with self._session_factory() as session:
            async with session.begin():
                stmt = (
                    update(GraphOutboxModel)
                    .where(GraphOutboxModel.status == OUTBOX_DISPATCHING)
                    .values(status=OUTBOX_PENDING, updated_at=self._clock.now())
                    .returning(GraphOutboxModel.outbox_id)
                )
                if run_id is not None:
                    stmt = stmt.where(GraphOutboxModel.run_id == run_id)
                result = await session.execute(stmt)
                return len(result.scalars().all())

    async def pending_items(self, *, run_id: str | None = None) -> list[OutboxItem]:
        async with self._session_factory() as session:
            stmt = (
                select(GraphOutboxModel)
                .where(GraphOutboxModel.status.in_([OUTBOX_PENDING, OUTBOX_DISPATCHING]))
                .order_by(GraphOutboxModel.outbox_id)
            )
            if run_id is not None:
                stmt = stmt.where(GraphOutboxModel.run_id == run_id)
            result = await session.execute(stmt)
            return [_to_item(row) for row in result.scalars()]

    async def _claim_next(
        self,
        limit: int | None,
        *,
        run_id: str | None = None,
    ) -> OutboxItem | None:
        async with self._session_factory() as session:
            async with session.begin():
                stmt = (
                    select(GraphOutboxModel)
                    .where(GraphOutboxModel.status == OUTBOX_PENDING)
                    .order_by(GraphOutboxModel.outbox_id)
                    .limit(1)
                )
                if run_id is not None:
                    stmt = stmt.where(GraphOutboxModel.run_id == run_id)
                if limit is not None and limit <= 0:
                    return None
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if row is None:
                    return None
                row.status = OUTBOX_DISPATCHING
                row.attempts += 1
                row.updated_at = self._clock.now()
                row.last_error = None
                await session.flush()
                return _to_item(row)

    async def _mark_completed(self, item: OutboxItem) -> OutboxItem:
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.get(GraphOutboxModel, item.outbox_id)
                if row is None:
                    return item
                if row.status == OUTBOX_COMPLETED:
                    return _to_item(row)
                row.status = OUTBOX_COMPLETED
                row.updated_at = self._clock.now()
                row.last_error = None
                await session.flush()
                return _to_item(row)

    async def _mark_failed_attempt(self, item: OutboxItem, exc: Exception) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.get(GraphOutboxModel, item.outbox_id)
                if row is None or row.status == OUTBOX_COMPLETED:
                    return
                row.status = OUTBOX_FAILED if row.attempts >= self._max_attempts else OUTBOX_PENDING
                row.updated_at = self._clock.now()
                row.last_error = str(exc)


def _to_item(row: GraphOutboxModel) -> OutboxItem:
    return OutboxItem(
        outbox_id=row.outbox_id,
        event_id=row.event_id,
        run_id=row.run_id,
        kind=row.kind,
        payload=dict(row.payload),
        status=row.status,
        attempts=row.attempts,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_error=row.last_error,
    )
