"""Real-SQLite proofs for bounded graph outbox maintenance."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import (
    EventV2Model,
    GraphOutboxModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph_runtime import (
    OUTBOX_MAINTENANCE_BATCH_LIMIT,
    OutboxDispatcher,
    OutboxItem,
    recover,
)

pytestmark = pytest.mark.slow


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 8, 5, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class RecordingExecutor:
    def __init__(self) -> None:
        self.event_ids: list[str] = []

    async def dispatch(self, item: OutboxItem) -> None:
        self.event_ids.append(item.event_id)


@pytest.fixture
async def outbox_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "bounded-outbox.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_reset_dispatching_returns_exact_scalar_count_without_row_materialization(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    cap = OUTBOX_MAINTENANCE_BATCH_LIMIT
    await _seed_rows(sessions, run_id="reset-a", count=cap + 17, status="dispatching")
    await _seed_rows(sessions, run_id="reset-a", count=3, status="pending", start=cap + 17)
    await _seed_rows(sessions, run_id="reset-b", count=11, status="dispatching")
    dispatcher = OutboxDispatcher(sessions, RecordingExecutor(), FixedClock())

    assert await dispatcher.reset_dispatching_to_pending(run_id="reset-a") == cap + 17
    assert await _status_count(sessions, "reset-a", "dispatching") == 0
    assert await _status_count(sessions, "reset-a", "pending") == cap + 20
    assert await _status_count(sessions, "reset-b", "dispatching") == 11
    assert await dispatcher.reset_dispatching_to_pending() == 11


@pytest.mark.asyncio
async def test_pending_and_dispatch_defaults_are_hard_bounded_batches(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    cap = OUTBOX_MAINTENANCE_BATCH_LIMIT
    await _seed_rows(sessions, run_id="bounded-dispatch", count=cap + 17, status="pending")
    executor = RecordingExecutor()
    dispatcher = OutboxDispatcher(sessions, executor, FixedClock())

    pending = await dispatcher.pending_items(run_id="bounded-dispatch")
    assert len(pending) == cap
    assert [item.outbox_id for item in pending] == sorted(item.outbox_id for item in pending)

    completed = await dispatcher.dispatch_pending(run_id="bounded-dispatch")
    assert len(completed) == cap
    assert len(executor.event_ids) == cap
    assert len(await dispatcher.pending_items(run_id="bounded-dispatch")) == 17

    smaller = await dispatcher.dispatch_pending(run_id="bounded-dispatch", limit=7)
    assert len(smaller) == 7
    assert await _status_count(sessions, "bounded-dispatch", "pending") == 10

    with pytest.raises(ValueError, match="outbox batch limit"):
        await dispatcher.pending_items(run_id="bounded-dispatch", limit=cap + 1)
    with pytest.raises(ValueError, match="outbox batch limit"):
        await dispatcher.dispatch_pending(run_id="bounded-dispatch", limit=0)


@pytest.mark.asyncio
async def test_failed_cleanup_requeue_is_one_keyset_batch_without_offset(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    engine, sessions = outbox_db
    cap = OUTBOX_MAINTENANCE_BATCH_LIMIT
    await _seed_rows(
        sessions,
        run_id="bounded-requeue",
        count=cap + 9,
        status="failed",
        kind="snapshot_cleanup",
    )
    statements: list[tuple[str, object]] = []

    def record_sql(
        _connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append((statement, _parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", record_sql)
    try:
        dispatcher = OutboxDispatcher(sessions, RecordingExecutor(), FixedClock())
        first = await dispatcher.requeue_failed_snapshot_cleanups_for_startup(
            run_id="bounded-requeue"
        )
        second = await dispatcher.requeue_failed_snapshot_cleanups_for_startup(
            run_id="bounded-requeue",
            after_outbox_id=first[-1].outbox_id,
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_sql)

    assert len(first) == cap
    assert len(second) == 9
    assert first[-1].outbox_id < second[0].outbox_id
    assert await _status_count(sessions, "bounded-requeue", "failed") == 0
    assert await _event_type_count(sessions, "bounded-requeue", "outbox_requeued") == cap + 9
    outbox_selects = [
        (sql.upper(), parameters)
        for sql, parameters in statements
        if sql.lstrip().upper().startswith("SELECT") and "GRAPH_OUTBOX" in sql.upper()
    ]
    assert outbox_selects
    # SQLite's dialect renders LIMIT-only statements as ``LIMIT ? OFFSET ?``.
    # Every generated offset remains zero; progression is through the id
    # predicate, never through increasingly expensive offset pagination.
    assert all(
        " OFFSET " not in sql or (isinstance(parameters, tuple) and parameters[-1] == 0)
        for sql, parameters in outbox_selects
    )
    assert any("GRAPH_OUTBOX.OUTBOX_ID >" in sql for sql, _ in outbox_selects)


@pytest.mark.asyncio
async def test_recovery_requeues_all_failed_cleanups_but_reports_and_dispatches_bounded_batches(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    cap = OUTBOX_MAINTENANCE_BATCH_LIMIT
    await _seed_rows(
        sessions,
        run_id="recovery-convergence",
        count=cap + 13,
        status="failed",
        kind="snapshot_cleanup",
    )
    executor = RecordingExecutor()
    clock = FixedClock()
    dispatcher = OutboxDispatcher(sessions, executor, clock)

    first = await recover(sessions, dispatcher, run_id="recovery-convergence")

    assert await _status_count(sessions, "recovery-convergence", "failed") == 0
    assert await _event_type_count(sessions, "recovery-convergence", "outbox_requeued") == cap + 13
    assert len(first.pending_cleanups) == cap
    assert first.pending_items_truncated is True
    assert first.redispatched == []
    assert await _status_count(sessions, "recovery-convergence", "pending") == cap + 13

    clock.advance(4)
    second = await recover(sessions, dispatcher, run_id="recovery-convergence")

    assert len(second.pending_cleanups) == cap
    assert second.pending_items_truncated is True
    assert len(second.redispatched) == cap
    assert await _status_count(sessions, "recovery-convergence", "pending") == 13

    third = await recover(sessions, dispatcher, run_id="recovery-convergence")

    assert len(third.pending_cleanups) == 13
    assert third.pending_items_truncated is False
    assert len(third.redispatched) == 13
    assert await _status_count(sessions, "recovery-convergence", "pending") == 0
    assert len(executor.event_ids) == cap + 13


async def _seed_rows(
    sessions: async_sessionmaker[AsyncSession],
    *,
    run_id: str,
    count: int,
    status: str,
    kind: str = "agent_dispatch",
    start: int = 0,
) -> None:
    now = FixedClock().now()
    async with sessions() as session:
        async with session.begin():
            session.add_all(
                [
                    GraphOutboxModel(
                        event_id=f"{run_id}-{start + index}",
                        run_id=run_id,
                        kind=kind,
                        payload={"index": start + index},
                        status=status,
                        attempts=3 if status == "failed" else 0,
                        created_at=now,
                        updated_at=now,
                        next_attempt_at=None,
                        last_error="exhausted" if status == "failed" else None,
                    )
                    for index in range(count)
                ]
            )


async def _status_count(
    sessions: async_sessionmaker[AsyncSession],
    run_id: str,
    status: str,
) -> int:
    async with sessions() as session:
        statement = (
            select(func.count())
            .select_from(GraphOutboxModel)
            .where(GraphOutboxModel.run_id == run_id)
            .where(GraphOutboxModel.status == status)
        )
        return int((await session.execute(statement)).scalar_one())


async def _event_type_count(
    sessions: async_sessionmaker[AsyncSession],
    run_id: str,
    event_type: str,
) -> int:
    async with sessions() as session:
        statement = (
            select(func.count())
            .select_from(EventV2Model)
            .where(EventV2Model.aggregate_id == f"graph:{run_id}")
            .where(EventV2Model.event_type == event_type)
        )
        return int((await session.execute(statement)).scalar_one())
