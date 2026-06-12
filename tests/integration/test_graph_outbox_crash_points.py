from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import (
    EventV2Model,
    GraphOutboxModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import (
    GraphController,
    GraphEventStore,
    OutboxAppendError,
    OutboxDispatcher,
    OutboxItem,
    StaleProjectionError,
    recover,
)
from orchestrator.graph_runtime.controller import rebuild_projection
from orchestrator.graph_runtime.outbox import append_outbox_rows


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class SequentialIds:
    def __init__(self) -> None:
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value


class FixedSequenceIds:
    def __init__(self, values: list[str]) -> None:
        self._values = list(values)

    def next_id(self, prefix: str = "") -> str:
        if not self._values:
            raise AssertionError(f"no id configured for prefix {prefix}")
        return self._values.pop(0)


class RecordingExecutor:
    def __init__(self, call_log: list[str], *, fail_on_calls: set[int] | None = None) -> None:
        self._call_log = call_log
        self._fail_on_calls = fail_on_calls or set()
        self._calls = 0

    async def dispatch(self, item: OutboxItem) -> None:
        self._calls += 1
        self._call_log.append(item.event_id)
        if self._calls in self._fail_on_calls:
            raise RuntimeError(f"dispatch failed at call {self._calls}")


class VisibilityAssertingExecutor:
    def __init__(self, db_path: Path, call_log: list[str]) -> None:
        self._db_path = db_path
        self._call_log = call_log

    async def dispatch(self, item: OutboxItem) -> None:
        own_engine = create_engine(self._db_path)
        try:
            own_session_factory = create_session_factory(own_engine)
            async with own_session_factory() as session:
                events = await GraphEventStore(session).read_run(item.run_id)
                outbox_row = await session.execute(
                    select(GraphOutboxModel).where(GraphOutboxModel.event_id == item.event_id)
                )
                event_rows = await session.execute(
                    select(EventV2Model).where(EventV2Model.aggregate_id == item.run_id)
                )
                visible_outbox_row = outbox_row.scalar_one_or_none()
                visible_event_rows = list(event_rows.scalars())

            assert any(event.event_id == item.event_id for event in events)
            assert visible_outbox_row is not None
            assert len(visible_event_rows) >= 1
            self._call_log.append(item.event_id)
        finally:
            await own_engine.dispose()


class SimulatedProcessCrash(BaseException):
    pass


class CrashOnceAfterSideEffectExecutor:
    def __init__(self, call_log: list[str]) -> None:
        self._call_log = call_log
        self._calls = 0

    async def dispatch(self, item: OutboxItem) -> None:
        self._calls += 1
        self._call_log.append(item.event_id)
        if self._calls == 1:
            raise SimulatedProcessCrash("process died before outbox completion")


@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def file_db_with_path(
    tmp_path: Path,
) -> AsyncGenerator[tuple[Path, AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    db_path = tmp_path / "graph-visibility.db"
    engine = create_engine(db_path)
    await init_db(engine)
    yield db_path, engine, create_session_factory(engine)
    await engine.dispose()


def _event(event_id: str, run_id: str, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        causation_id="test",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


async def _seed_runnable_worker(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> list[EventEnvelope]:
    events = [
        _event(
            f"{run_id}-run-active",
            run_id,
            "run_lifecycle_changed",
            {"from_state": "queued", "to_state": "active"},
        ),
        _event(
            f"{run_id}-worker-created",
            run_id,
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "planned",
                "task_region_id": "task-1",
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["src/**"]}],
            },
        ),
    ]
    async with session_factory() as session:
        async with session.begin():
            return await GraphEventStore(session).append_events(run_id, 0, events)


async def _read_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> list[EventEnvelope]:
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _outbox_statuses(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[str]:
    async with session_factory() as session:
        result = await session.execute(
            select(GraphOutboxModel.status).order_by(GraphOutboxModel.outbox_id)
        )
        return [str(status) for status in result.scalars()]


async def _outbox_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[GraphOutboxModel]:
    async with session_factory() as session:
        result = await session.execute(
            select(GraphOutboxModel).order_by(GraphOutboxModel.outbox_id)
        )
        return list(result.scalars())


async def _outbox_count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        result = await session.execute(select(func.count(GraphOutboxModel.outbox_id)))
        return int(result.scalar_one())


@pytest.mark.asyncio
async def test_crash_before_append_no_events_no_outbox_no_dispatch(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "crash-before-append"
    await _seed_runnable_worker(session_factory, run_id)
    call_log: list[str] = []
    clock = FixedClock()
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    controller = GraphController(session_factory, clock, SequentialIds(), dispatcher=dispatcher)

    with pytest.raises(StaleProjectionError):
        await controller.handle_command(run_id, 1, "schedule_tick", {"lease_seconds": 60})

    events = await _read_events(session_factory, run_id)
    assert [event.event_id for event in events] == [
        f"{run_id}-run-active",
        f"{run_id}-worker-created",
    ]
    assert await _outbox_count(session_factory) == 0
    assert call_log == []


@pytest.mark.asyncio
async def test_crash_after_append_before_outbox_starts_agent_restarts_dispatch(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "crash-after-append"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    controller = GraphController(session_factory, clock, SequentialIds(), auto_dispatch=False)

    result = await controller.handle_command(run_id, 2, "schedule_tick", {"lease_seconds": 60})
    assert [item.status for item in result.outbox_items] == ["pending"]

    call_log: list[str] = []
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    report = await recover(session_factory, dispatcher, run_id=run_id)
    await dispatcher.dispatch_pending()

    assert len(report.redispatched) == 1
    redispatched = report.redispatched[0]
    assert redispatched.run_id == run_id
    assert redispatched.kind == "agent_dispatch"
    assert redispatched.payload["run_id"] == run_id
    assert redispatched.payload["node_id"] == "worker-1"
    assert redispatched.payload["lease_id"] == result.outbox_items[0].payload["lease_id"]
    assert redispatched.payload["generation"] == 1
    assert redispatched.payload["classification"] == "agent_dispatch_pending"
    assert call_log == [result.outbox_items[0].event_id]
    assert await _outbox_statuses(session_factory) == ["completed"]


@pytest.mark.asyncio
async def test_crash_after_agent_starts_before_start_ack_reports_awaiting_start_ack(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "crash-after-agent-start"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    call_log: list[str] = []
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    controller = GraphController(
        session_factory,
        clock,
        SequentialIds(),
        dispatcher=dispatcher,
    )

    await controller.handle_command(run_id, 2, "schedule_tick", {"lease_seconds": 60})
    assert len(call_log) == 1

    restarted_dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    report = await recover(session_factory, restarted_dispatcher, run_id=run_id)
    second_report = await recover(session_factory, restarted_dispatcher, run_id=run_id)

    assert len(call_log) == 1
    assert report.redispatched == []
    assert report.awaiting_start_ack == [
        {
            "run_id": run_id,
            "lease_id": "lease-3",
            "node_id": "worker-1",
            "generation": 1,
            "execution_id": "exec-4",
            "classification": "awaiting_start_ack",
        }
    ]
    assert report.awaiting_start_ack == second_report.awaiting_start_ack
    lease_id = str(report.awaiting_start_ack[0]["lease_id"])
    projection = rebuild_projection(await _read_events(session_factory, run_id))
    assert projection["leases"][lease_id]["state"] == "active"
    assert projection["node_states"]["worker-1"] == "leased"


@pytest.mark.asyncio
async def test_crash_point_4_agent_died_revokes_lease_and_allows_release(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "agent-dies-controller-command"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    call_log: list[str] = []
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    controller = GraphController(
        session_factory,
        clock,
        SequentialIds(),
        dispatcher=dispatcher,
    )

    first = await controller.handle_command(run_id, 2, "schedule_tick", {"lease_seconds": 60})
    lease_id = str(first.outbox_items[0].payload["lease_id"])
    execution_id = str(first.outbox_items[0].payload["execution_id"])
    started = await controller.handle_command(
        run_id,
        first.projection_position,
        "acknowledge_start",
        {
            "node_id": "worker-1",
            "lease_id": lease_id,
            "lease_generation": 1,
            "execution_id": execution_id,
        },
    )

    died = await controller.handle_command(
        run_id,
        started.projection_position,
        "agent_died",
        {"lease_id": lease_id, "execution_id": execution_id, "reason": "process_exited"},
    )
    projection_after_death = rebuild_projection(await _read_events(session_factory, run_id))
    relearnt = await controller.handle_command(
        run_id,
        died.projection_position,
        "schedule_tick",
        {"lease_seconds": 60},
    )
    projection_after_relearn = rebuild_projection(await _read_events(session_factory, run_id))

    assert [event.event_type for event in died.events] == [
        "agent_died",
        "lease_revoked",
        "runtime_retry_scheduled",
        "node_state_changed",
    ]
    assert projection_after_death["leases"][lease_id]["state"] == "revoked"
    assert projection_after_death["node_states"]["worker-1"] == "ready"
    assert any(event.event_type == "runtime_retry_scheduled" for event in died.events)
    assert [event.event_type for event in relearnt.events] == [
        "node_ready",
        "lease_granted",
        "agent_dispatch_requested",
        "node_state_changed",
    ]
    new_lease_id = str(relearnt.outbox_items[0].payload["lease_id"])
    assert new_lease_id != lease_id
    assert projection_after_relearn["leases"][new_lease_id]["state"] == "active"
    assert call_log == [first.outbox_items[0].event_id, relearnt.outbox_items[0].event_id]
    assert await _outbox_statuses(session_factory) == ["completed", "completed"]


@pytest.mark.asyncio
async def test_duplicate_dispatch_pending_invokes_executor_once(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "duplicate-dispatch"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    controller = GraphController(session_factory, clock, SequentialIds(), auto_dispatch=False)
    await controller.handle_command(run_id, 2, "schedule_tick", {"lease_seconds": 60})

    call_log: list[str] = []
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    await dispatcher.dispatch_pending()
    await dispatcher.dispatch_pending()

    assert len(call_log) == 1
    assert await _outbox_statuses(session_factory) == ["completed"]


@pytest.mark.asyncio
async def test_restart_mid_dispatching_row_is_retried_idempotently(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "restart-mid-dispatch"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    controller = GraphController(session_factory, clock, SequentialIds(), auto_dispatch=False)
    result = await controller.handle_command(run_id, 2, "schedule_tick", {"lease_seconds": 60})

    call_log: list[str] = []
    crashing_dispatcher = OutboxDispatcher(
        session_factory,
        CrashOnceAfterSideEffectExecutor(call_log),
        clock,
    )

    with pytest.raises(SimulatedProcessCrash):
        await crashing_dispatcher.dispatch_pending()

    rows_after_crash = await _outbox_rows(session_factory)
    assert len(rows_after_crash) == 1
    assert rows_after_crash[0].event_id == result.outbox_items[0].event_id
    assert rows_after_crash[0].status == "dispatching"
    assert rows_after_crash[0].attempts == 1
    assert call_log == [result.outbox_items[0].event_id]

    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)
    report = await recover(session_factory, dispatcher, run_id=run_id)
    rows_after_recovery = await _outbox_rows(session_factory)

    assert len(report.redispatched) == 1
    assert call_log == [result.outbox_items[0].event_id, result.outbox_items[0].event_id]
    assert rows_after_recovery[0].status == "completed"
    assert rows_after_recovery[0].attempts == 2


@pytest.mark.asyncio
async def test_events_and_outbox_rows_commit_atomically_on_outbox_failure(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "atomic-outbox-failure"
    clock = FixedClock()
    dispatch_event = _event(
        "dispatch-event-collision",
        run_id,
        "agent_dispatch_requested",
        {"lease_id": "lease-1", "node_id": "worker-1"},
    )

    async with session_factory() as session:
        async with session.begin():
            session.add(
                GraphOutboxModel(
                    event_id=dispatch_event.event_id,
                    run_id=run_id,
                    kind="agent_dispatch",
                    payload={"event_id": dispatch_event.event_id},
                    status="pending",
                    attempts=0,
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )

    with pytest.raises(OutboxAppendError):
        async with session_factory() as session:
            async with session.begin():
                stored = await GraphEventStore(session).append_events(run_id, 0, [dispatch_event])
                await append_outbox_rows(session, stored, clock)

    assert await _read_events(session_factory, run_id) == []
    assert await _outbox_count(session_factory) == 1


@pytest.mark.asyncio
async def test_controller_does_not_start_side_effect_before_commit(
    file_db_with_path: tuple[Path, AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    db_path, _, session_factory = file_db_with_path
    run_id = "no-side-effect-before-commit"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    call_log: list[str] = []
    dispatcher = OutboxDispatcher(
        session_factory,
        VisibilityAssertingExecutor(db_path, call_log),
        clock,
    )
    controller = GraphController(
        session_factory,
        clock,
        SequentialIds(),
        dispatcher=dispatcher,
    )

    result = await controller.handle_command(run_id, 2, "schedule_tick", {"lease_seconds": 60})

    assert call_log == [result.outbox_items[0].event_id]
    assert await _outbox_statuses(session_factory) == ["completed"]


@pytest.mark.asyncio
async def test_controller_rolls_back_events_when_dispatch_outbox_insert_fails(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "controller-atomic-outbox-failure"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    collision_event_id = "event-dispatch-collision"
    call_log: list[str] = []
    dispatcher = OutboxDispatcher(session_factory, RecordingExecutor(call_log), clock)

    async with session_factory() as session:
        async with session.begin():
            session.add(
                GraphOutboxModel(
                    event_id=collision_event_id,
                    run_id=run_id,
                    kind="agent_dispatch",
                    payload={"event_id": collision_event_id},
                    status="pending",
                    attempts=0,
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )

    controller = GraphController(
        session_factory,
        clock,
        FixedSequenceIds(
            [
                "event-ready",
                "event-ready-state",
                "lease-1",
                "exec-1",
                "event-lease-granted",
                "event-leased-state",
                collision_event_id,
            ]
        ),
        dispatcher=dispatcher,
    )

    with pytest.raises(OutboxAppendError):
        await controller.handle_command(run_id, 2, "schedule_tick", {"lease_seconds": 60})

    events = await _read_events(session_factory, run_id)
    outbox_rows = await _outbox_rows(session_factory)
    assert [event.event_id for event in events] == [
        f"{run_id}-run-active",
        f"{run_id}-worker-created",
    ]
    assert len(outbox_rows) == 1
    assert outbox_rows[0].event_id == collision_event_id
    assert call_log == []


@pytest.mark.asyncio
async def test_agent_dispatch_requested_event_envelope_is_persisted_exactly(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "dispatch-envelope"
    await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    controller = GraphController(session_factory, clock, SequentialIds(), auto_dispatch=False)

    result = await controller.handle_command(run_id, 2, "schedule_tick", {"lease_seconds": 60})
    read_back = await _read_events(session_factory, run_id)
    lease_event = next(event for event in read_back if event.event_type == "lease_granted")
    dispatch_event = next(
        event for event in read_back if event.event_type == "agent_dispatch_requested"
    )

    assert dispatch_event.event_type == "agent_dispatch_requested"
    assert dispatch_event.run_id == run_id
    assert dispatch_event.position == lease_event.position + 1
    assert dispatch_event.actor.kind == "controller"
    assert dispatch_event.causation_id == "schedule_tick"
    assert dispatch_event.schema_version == 1
    assert dispatch_event.timestamp == clock.now()
    assert dispatch_event.payload == {
        "lease_granted_event_id": lease_event.event_id,
        "lease_id": lease_event.payload["lease_id"],
        "node_id": "worker-1",
        "generation": 1,
        "execution_id": lease_event.payload["execution_id"],
        "base_snapshot_id": "S0",
        "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["src/**"]}],
    }
    assert result.outbox_items[0].event_id == dispatch_event.event_id


@pytest.mark.asyncio
async def test_controller_round_trip_projection_matches_in_memory_projection(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = file_db
    run_id = "controller-round-trip"
    seed_events = await _seed_runnable_worker(session_factory, run_id)
    clock = FixedClock()
    controller = GraphController(session_factory, clock, SequentialIds(), auto_dispatch=False)

    result = await controller.handle_command(run_id, 2, "schedule_tick", {"lease_seconds": 60})
    read_back = await _read_events(session_factory, run_id)

    assert read_back == seed_events + result.events
    assert rebuild_projection(read_back) == rebuild_projection(seed_events + result.events)
