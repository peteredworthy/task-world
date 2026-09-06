"""Graph outbox mapping and dispatcher."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, TypeVar, cast
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.db import GraphOutboxModel
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime.store import GraphEventStore
from orchestrator.graph_runtime.errors import OutboxAppendError

logger = logging.getLogger(__name__)

OUTBOX_PENDING = "pending"
OUTBOX_DISPATCHING = "dispatching"
OUTBOX_COMPLETED = "completed"
OUTBOX_FAILED = "failed"
OUTBOX_MAINTENANCE_BATCH_LIMIT = 100

_T = TypeVar("_T")


def _is_sqlite_locked(exc: OperationalError) -> bool:
    """True for transient SQLite write-contention errors worth retrying."""
    message = str(getattr(exc, "orig", exc)).lower()
    return "database is locked" in message or "database is busy" in message


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
    next_attempt_at: datetime | None
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
    ``agent_dispatch_requested`` -> ``agent_dispatch``,
    ``cleanup_requested`` -> ``snapshot_cleanup``,
    ``runner_submission_staged`` -> ``snapshot_publish``, and
    ``runner_recovery_requested`` -> ``runner_recovery``. Rejection/audit
    events intentionally return ``None`` so they are persisted facts only.
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
    if event.event_type == "runner_recovery_requested":
        payload = {
            "event_id": event.event_id,
            "run_id": event.run_id,
            "classification": "runner_recovery_pending",
        }
        payload.update(event.payload)
        return "runner_recovery", payload
    if event.event_type == "validation_environment_blockage_resolution_requested":
        payload = {
            "event_id": event.event_id,
            "run_id": event.run_id,
            "classification": "validation_environment_resolution_pending",
        }
        payload.update(event.payload)
        return "validation_environment_resolution", payload
    if event.event_type == "runner_completion_witnessed":
        return (
            "snapshot_publish",
            {
                "event_id": event.event_id,
                "run_id": event.run_id,
                "classification": "completion_witness_snapshot_publish_pending",
                "snapshot_id": event.payload["final_snapshot_id"],
                "snapshot_ref": event.payload["final_snapshot_ref"],
                "commit_sha": event.payload["final_commit_sha"],
                "tree_sha": event.payload["final_tree_sha"],
            },
        )
    if event.event_type == "runner_submission_staged":
        # The managed ref is recovery evidence even when no accepted
        # FileStateRecord will ultimately take ownership of it.
        payload = {
            "event_id": event.event_id,
            "run_id": event.run_id,
            "classification": "snapshot_publish_pending",
            "snapshot_id": event.payload["staged_snapshot_id"],
            "snapshot_ref": event.payload["staged_snapshot_ref"],
            "commit_sha": event.payload["staged_commit_sha"],
            "tree_sha": event.payload["staged_tree_sha"],
        }
        return "snapshot_publish", payload
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
                next_attempt_at=None,
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
        retry_base_seconds: float = 2.0,
        retry_factor: float = 4.0,
        retry_cap_seconds: float = 60.0,
        retry_jitter_seconds: float = 1.0,
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor
        self._clock = clock
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_factor = retry_factor
        self._retry_cap_seconds = retry_cap_seconds
        self._retry_jitter_seconds = retry_jitter_seconds

    async def dispatch_pending(
        self,
        limit: int | None = None,
        *,
        run_id: str | None = None,
        allowed_kinds: frozenset[str] | None = None,
    ) -> list[OutboxItem]:
        """Dispatch one bounded batch in outbox order and return completed items.

        Omitting ``limit`` uses :data:`OUTBOX_MAINTENANCE_BATCH_LIMIT`.  An
        explicit limit may make the batch smaller, but cannot exceed that cap.
        The eligible upper bound is captured before dispatch starts. Side
        effects can append follow-on rows (including snapshot work requiring a
        lock held by a newly-launched agent); those rows belong to the next
        tick. This prevents one call from chasing new work and blocking the
        driver's lease-maintenance pass behind the agent it just started.
        """
        batch_limit = _bounded_batch_limit(limit)
        await self.reset_dispatching_to_pending(run_id=run_id)
        through_outbox_id = await self._pending_upper_bound(
            run_id=run_id,
            allowed_kinds=allowed_kinds,
        )
        if through_outbox_id is None:
            return []
        completed: list[OutboxItem] = []
        remaining = batch_limit
        while True:
            item = await self._claim_next(
                remaining,
                run_id=run_id,
                allowed_kinds=allowed_kinds,
                through_outbox_id=through_outbox_id,
            )
            if item is None:
                return completed
            try:
                await self._executor.dispatch(item)
            except Exception as exc:
                logger.warning(
                    "Graph outbox dispatch failed: run=%s outbox_id=%s kind=%s attempt=%s error=%s",
                    item.run_id,
                    item.outbox_id,
                    item.kind,
                    item.attempts + 1,
                    exc,
                )
                await self._mark_failed_attempt(item, exc)
            else:
                completed.append(await self._mark_completed(item))
            remaining -= 1
            if remaining <= 0:
                return completed

    async def _pending_upper_bound(
        self,
        *,
        run_id: str | None,
        allowed_kinds: frozenset[str] | None,
    ) -> int | None:
        async def _op() -> int | None:
            async with self._session_factory() as session:
                stmt = select(func.max(GraphOutboxModel.outbox_id)).where(
                    GraphOutboxModel.status == OUTBOX_PENDING,
                    or_(
                        GraphOutboxModel.next_attempt_at.is_(None),
                        GraphOutboxModel.next_attempt_at <= self._clock.now(),
                    ),
                )
                if run_id is not None:
                    stmt = stmt.where(GraphOutboxModel.run_id == run_id)
                if allowed_kinds is not None:
                    stmt = stmt.where(GraphOutboxModel.kind.in_(allowed_kinds))
                value = cast(int | None, (await session.execute(stmt)).scalar_one())
                return int(value) if value is not None else None

        return await self._retry_locked(_op)

    async def reset_dispatching_to_pending(self, *, run_id: str | None = None) -> int:
        """Treat startup ``dispatching`` rows as pending for at-least-once retry."""

        async def _op() -> int:
            async with self._session_factory() as session:
                async with session.begin():
                    count_stmt = (
                        select(func.count())
                        .select_from(GraphOutboxModel)
                        .where(GraphOutboxModel.status == OUTBOX_DISPATCHING)
                    )
                    update_stmt = (
                        update(GraphOutboxModel)
                        .where(GraphOutboxModel.status == OUTBOX_DISPATCHING)
                        .values(
                            status=OUTBOX_PENDING,
                            updated_at=self._clock.now(),
                            next_attempt_at=None,
                        )
                    )
                    if run_id is not None:
                        count_stmt = count_stmt.where(GraphOutboxModel.run_id == run_id)
                        update_stmt = update_stmt.where(GraphOutboxModel.run_id == run_id)
                    count = int((await session.execute(count_stmt)).scalar_one())
                    if count:
                        await session.execute(update_stmt)
                    return count

        return await self._retry_locked(_op)

    async def requeue_failed_snapshot_cleanups_for_startup(
        self,
        *,
        run_id: str | None = None,
        immediate: bool = False,
        after_outbox_id: int | None = None,
        limit: int = OUTBOX_MAINTENANCE_BATCH_LIMIT,
    ) -> list[OutboxItem]:
        """Requeue one bounded, audited restart epoch for managed cleanup only.

        Failed agent dispatches and other side effects deliberately remain
        failed.  A snapshot cleanup is idempotent and is the sole operation
        safe to retry automatically after process restart.  The retained error
        and append-only audit fact preserve the previous delivery epoch.

        One call processes at most ``limit`` rows after ``after_outbox_id``.
        Startup recovery advances that keyset cursor until the fixed-size
        batches converge; this method never materializes every failed cleanup.
        """
        batch_limit = _bounded_batch_limit(limit)
        requeued: list[OutboxItem] = []
        async with self._session_factory() as session:
            async with session.begin():
                stmt = (
                    select(GraphOutboxModel)
                    .where(GraphOutboxModel.status == OUTBOX_FAILED)
                    .where(GraphOutboxModel.kind == "snapshot_cleanup")
                    .order_by(GraphOutboxModel.outbox_id)
                    .limit(batch_limit)
                )
                if run_id is not None:
                    stmt = stmt.where(GraphOutboxModel.run_id == run_id)
                if after_outbox_id is not None:
                    stmt = stmt.where(GraphOutboxModel.outbox_id > after_outbox_id)
                rows = list((await session.execute(stmt)).scalars())
                store = GraphEventStore(session)
                for row in rows:
                    previous_attempts = row.attempts
                    previous_error = row.last_error
                    now = self._clock.now()
                    row.status = OUTBOX_PENDING
                    row.attempts = 0
                    row.updated_at = now
                    # Terminal ownership must converge before startup returns;
                    # active runs retain their normal deterministic backoff.
                    row.next_attempt_at = None if immediate else now + self._retry_delay(row)
                    position = await store.current_position(row.run_id)
                    await store.append_events(
                        row.run_id,
                        position,
                        [
                            EventEnvelope(
                                event_id=f"outbox-startup-requeued-{uuid4().hex}",
                                run_id=row.run_id,
                                position=-1,
                                event_type="outbox_requeued",
                                schema_version=1,
                                actor=Actor(
                                    kind=ActorKind.SYSTEM,
                                    id="startup-cleanup-recovery",
                                    role="system",
                                ),
                                causation_id=row.event_id,
                                timestamp=now,
                                payload={
                                    "run_id": row.run_id,
                                    "outbox_id": row.outbox_id,
                                    "event_id": row.event_id,
                                    "kind": row.kind,
                                    "previous_status": OUTBOX_FAILED,
                                    "previous_attempts": previous_attempts,
                                    "previous_last_error": previous_error,
                                    "operator": "startup-cleanup-recovery",
                                    "graph_position": position + 1,
                                },
                            )
                        ],
                    )
                    requeued.append(_to_item(row))
        return requeued

    async def pending_items(
        self,
        *,
        run_id: str | None = None,
        after_outbox_id: int | None = None,
        limit: int = OUTBOX_MAINTENANCE_BATCH_LIMIT,
    ) -> list[OutboxItem]:
        """Return one bounded keyset page of pending or dispatching rows."""
        batch_limit = _bounded_batch_limit(limit)
        async with self._session_factory() as session:
            stmt = (
                select(GraphOutboxModel)
                .where(GraphOutboxModel.status.in_([OUTBOX_PENDING, OUTBOX_DISPATCHING]))
                .order_by(GraphOutboxModel.outbox_id)
                .limit(batch_limit)
            )
            if run_id is not None:
                stmt = stmt.where(GraphOutboxModel.run_id == run_id)
            if after_outbox_id is not None:
                stmt = stmt.where(GraphOutboxModel.outbox_id > after_outbox_id)
            result = await session.execute(stmt)
            return [_to_item(row) for row in result.scalars()]

    async def has_pending_items_after(
        self,
        outbox_id: int,
        *,
        run_id: str | None = None,
    ) -> bool:
        """Probe for a later pending row without decoding another payload."""
        async with self._session_factory() as session:
            stmt = (
                select(GraphOutboxModel.outbox_id)
                .where(GraphOutboxModel.status.in_([OUTBOX_PENDING, OUTBOX_DISPATCHING]))
                .where(GraphOutboxModel.outbox_id > outbox_id)
                .order_by(GraphOutboxModel.outbox_id)
                .limit(1)
            )
            if run_id is not None:
                stmt = stmt.where(GraphOutboxModel.run_id == run_id)
            return (await session.execute(stmt)).scalar_one_or_none() is not None

    async def earliest_pending_retry_at(self, *, run_id: str | None = None) -> datetime | None:
        """Return the earliest deferred pending retry time after ``clock.now()``."""
        async with self._session_factory() as session:
            stmt = (
                select(GraphOutboxModel.next_attempt_at)
                .where(GraphOutboxModel.status == OUTBOX_PENDING)
                .where(GraphOutboxModel.next_attempt_at.is_not(None))
                .where(GraphOutboxModel.next_attempt_at > self._clock.now())
                .order_by(GraphOutboxModel.next_attempt_at, GraphOutboxModel.outbox_id)
                .limit(1)
            )
            if run_id is not None:
                stmt = stmt.where(GraphOutboxModel.run_id == run_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def _claim_next(
        self,
        limit: int | None,
        *,
        run_id: str | None = None,
        allowed_kinds: frozenset[str] | None = None,
        through_outbox_id: int | None = None,
    ) -> OutboxItem | None:
        # Safe to retry on a lock: the claim transaction rolls back whole, so a
        # retried attempt re-selects the same still-pending row (at-least-once).
        async def _op() -> OutboxItem | None:
            async with self._session_factory() as session:
                async with session.begin():
                    stmt = (
                        select(GraphOutboxModel)
                        .where(GraphOutboxModel.status == OUTBOX_PENDING)
                        .where(
                            or_(
                                GraphOutboxModel.next_attempt_at.is_(None),
                                GraphOutboxModel.next_attempt_at <= self._clock.now(),
                            )
                        )
                        .order_by(GraphOutboxModel.outbox_id)
                        .limit(1)
                    )
                    if run_id is not None:
                        stmt = stmt.where(GraphOutboxModel.run_id == run_id)
                    if allowed_kinds is not None:
                        stmt = stmt.where(GraphOutboxModel.kind.in_(allowed_kinds))
                    if through_outbox_id is not None:
                        stmt = stmt.where(GraphOutboxModel.outbox_id <= through_outbox_id)
                    if limit is not None and limit <= 0:
                        return None
                    result = await session.execute(stmt)
                    row = result.scalar_one_or_none()
                    if row is None:
                        return None
                    row.status = OUTBOX_DISPATCHING
                    row.attempts += 1
                    row.updated_at = self._clock.now()
                    row.next_attempt_at = None
                    await session.flush()
                    return _to_item(row)

        return await self._retry_locked(_op)

    async def _retry_locked(
        self,
        op: Callable[[], Awaitable[_T]],
        *,
        attempts: int = 5,
        base_delay: float = 0.05,
    ) -> _T:
        """Retry a bookkeeping transaction on transient SQLite lock errors.

        Success-path bookkeeping (``_mark_completed``) commits outside the
        dispatch try/except, so a transient ``database is locked`` here would
        otherwise escape ``dispatch_pending`` and kill the whole drive loop.
        WAL + ``busy_timeout`` on the engine make locks rare and mostly
        self-resolving; this exponential-backoff retry absorbs the residue so a
        write-contention blip does not strand the run.
        """
        for attempt in range(attempts):
            try:
                return await op()
            except OperationalError as exc:
                if not _is_sqlite_locked(exc) or attempt == attempts - 1:
                    raise
                delay = base_delay * (2**attempt)
                logger.warning(
                    "OutboxDispatcher: transient DB lock during bookkeeping, "
                    "retrying in %.2fs (attempt %d/%d)",
                    delay,
                    attempt + 1,
                    attempts,
                )
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _mark_completed(self, item: OutboxItem) -> OutboxItem:
        async def _op() -> OutboxItem:
            async with self._session_factory() as session:
                async with session.begin():
                    row = await session.get(GraphOutboxModel, item.outbox_id)
                    if row is None:
                        return item
                    if row.status == OUTBOX_COMPLETED:
                        return _to_item(row)
                    row.status = OUTBOX_COMPLETED
                    row.updated_at = self._clock.now()
                    row.next_attempt_at = None
                    await session.flush()
                    return _to_item(row)

        return await self._retry_locked(_op)

    async def _mark_failed_attempt(self, item: OutboxItem, exc: Exception) -> None:
        async def _op() -> None:
            async with self._session_factory() as session:
                async with session.begin():
                    row = await session.get(GraphOutboxModel, item.outbox_id)
                    if row is None or row.status == OUTBOX_COMPLETED:
                        return
                    now = self._clock.now()
                    exhausted = row.attempts >= self._max_attempts
                    row.status = OUTBOX_FAILED if exhausted else OUTBOX_PENDING
                    row.updated_at = now
                    row.next_attempt_at = None if exhausted else now + self._retry_delay(row)
                    row.last_error = str(exc)

        await self._retry_locked(_op)

    def _retry_delay(self, row: GraphOutboxModel) -> timedelta:
        attempt_index = max(row.attempts - 1, 0)
        scheduled = self._retry_base_seconds * (self._retry_factor**attempt_index)
        jitter = _stable_jitter_seconds(
            row.event_id,
            row.attempts,
            max_seconds=self._retry_jitter_seconds,
        )
        capped = min(scheduled + jitter, self._retry_cap_seconds)
        return timedelta(seconds=capped)


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
        next_attempt_at=row.next_attempt_at,
        last_error=row.last_error,
    )


def _stable_jitter_seconds(event_id: str, attempts: int, *, max_seconds: float) -> float:
    if max_seconds <= 0:
        return 0.0
    digest = hashlib.sha256(f"{event_id}:{attempts}".encode("utf-8")).digest()
    fraction = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
    return fraction * max_seconds


def _bounded_batch_limit(limit: int | None) -> int:
    batch_limit = OUTBOX_MAINTENANCE_BATCH_LIMIT if limit is None else limit
    if not 1 <= batch_limit <= OUTBOX_MAINTENANCE_BATCH_LIMIT:
        raise ValueError(
            f"outbox batch limit must be between 1 and {OUTBOX_MAINTENANCE_BATCH_LIMIT}"
        )
    return batch_limit
