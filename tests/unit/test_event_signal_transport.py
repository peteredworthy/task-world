"""Unit tests for EventSignalTransport using a real in-memory SQLite DB."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.config.enums import RunStatus
from orchestrator.db import Base
from orchestrator.db import SqliteEventStore
from orchestrator.db import EventV2Model
from orchestrator.db import RunLifecycleProjector
from orchestrator.workflow import RunStatusChanged, SignalProcessed
from orchestrator.workflow import (
    EventSignalTransport,
    RunWorkflow,
    SignalForInactiveRunError,
    WorkflowSignal,
)


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _transport(
    session: AsyncSession, projector: RunLifecycleProjector | None = None
) -> EventSignalTransport:
    return EventSignalTransport(
        SqliteEventStore(session),
        projector or RunLifecycleProjector(),
        projector_preloaded=projector is not None,
    )


class RecordingSignalService:
    def __init__(self) -> None:
        self.pause_calls = 0

    async def apply_pause_run(self, run_id: str, *, reason: str) -> None:
        self.pause_calls += 1


async def _append_status_changed(
    session: AsyncSession,
    run_id: str,
    new_status: RunStatus,
) -> None:
    store = SqliteEventStore(session)
    await store.append(
        [
            RunStatusChanged(
                run_id=run_id,
                event_type="run_status_changed",
                old_status=RunStatus.DRAFT,
                new_status=new_status,
            )
        ]
    )


async def _enqueued_rows(session: AsyncSession, run_id: str) -> list[EventV2Model]:
    result = await session.execute(
        select(EventV2Model)
        .where(EventV2Model.aggregate_id == run_id, EventV2Model.event_type == "signal_enqueued")
        .order_by(EventV2Model.position)
    )
    return list(result.scalars())


async def _processed_positions(session: AsyncSession, run_id: str) -> set[int]:
    result = await session.execute(
        select(EventV2Model.payload).where(
            EventV2Model.aggregate_id == run_id, EventV2Model.event_type == "signal_processed"
        )
    )
    positions = set()
    for p in result.scalars():
        data = json.loads(p)
        pos = data.get("enqueued_position")
        if isinstance(pos, int):
            positions.add(pos)
    return positions


async def _event_types(session: AsyncSession, run_id: str) -> list[str]:
    result = await session.execute(
        select(EventV2Model.event_type)
        .where(EventV2Model.aggregate_id == run_id)
        .order_by(EventV2Model.position)
    )
    return list(result.scalars())


# ---------------------------------------------------------------------------
# enqueue()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_creates_signal_enqueued_event(session: AsyncSession) -> None:
    transport = _transport(session)
    await transport.enqueue("run-1", WorkflowSignal.PAUSE, {"reason": "manual"})

    rows = await _enqueued_rows(session, "run-1")
    assert len(rows) == 1
    assert rows[0].event_type == "signal_enqueued"
    data = json.loads(rows[0].payload)
    assert data["signal_type"] == "pause"
    assert data["payload"] == {"reason": "manual"}


@pytest.mark.asyncio
async def test_enqueue_returns_pending_signal_with_position_as_id(session: AsyncSession) -> None:
    transport = _transport(session)
    signal = await transport.enqueue("run-1", WorkflowSignal.CANCEL)

    rows = await _enqueued_rows(session, "run-1")
    assert signal.id == rows[0].position
    assert signal.run_id == "run-1"
    assert signal.signal_type == WorkflowSignal.CANCEL
    assert signal.payload is None


@pytest.mark.asyncio
async def test_enqueue_raises_for_terminal_run(session: AsyncSession) -> None:
    projector = RunLifecycleProjector()
    projector._terminal.add("run-done")
    transport = _transport(session, projector)

    with pytest.raises(SignalForInactiveRunError) as exc_info:
        await transport.enqueue("run-done", WorkflowSignal.PAUSE)

    assert exc_info.value.run_id == "run-done"


@pytest.mark.asyncio
async def test_fresh_transport_replays_terminal_run_before_enqueue(
    session: AsyncSession,
) -> None:
    await _append_status_changed(session, "run-done", RunStatus.ACTIVE)
    await _append_status_changed(session, "run-done", RunStatus.COMPLETED)
    transport = _transport(session)

    with pytest.raises(SignalForInactiveRunError) as exc_info:
        await transport.enqueue("run-done", WorkflowSignal.PAUSE)

    assert exc_info.value.run_id == "run-done"


@pytest.mark.asyncio
async def test_enqueue_non_terminal_run_succeeds(session: AsyncSession) -> None:
    projector = RunLifecycleProjector()
    projector._active.add("run-active")
    transport = _transport(session, projector)

    signal = await transport.enqueue("run-active", WorkflowSignal.PAUSE)
    assert signal.run_id == "run-active"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RunStatus.ACTIVE, RunStatus.PAUSED])
async def test_fresh_transport_replays_signalable_run_before_enqueue(
    session: AsyncSession,
    status: RunStatus,
) -> None:
    await _append_status_changed(session, "run-open", status)
    transport = _transport(session)

    signal = await transport.enqueue("run-open", WorkflowSignal.PAUSE)

    assert signal.run_id == "run-open"


@pytest.mark.asyncio
async def test_enqueue_stores_only_signal_enqueued_event(session: AsyncSession) -> None:
    transport = _transport(session)
    await transport.enqueue("run-1", WorkflowSignal.PAUSE)

    assert await _event_types(session, "run-1") == ["signal_enqueued"]


# ---------------------------------------------------------------------------
# drain()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_empty_returns_empty_list(session: AsyncSession) -> None:
    transport = _transport(session)
    result = await transport.drain("run-empty")
    assert result == []


@pytest.mark.asyncio
async def test_drain_returns_unprocessed_signals_fifo(session: AsyncSession) -> None:
    transport = _transport(session)
    await transport.enqueue("run-1", WorkflowSignal.PAUSE, {"reason": "a"})
    await transport.enqueue("run-1", WorkflowSignal.CANCEL, {"reason": "b"})

    signals = await transport.drain("run-1")

    assert len(signals) == 2
    assert signals[0].signal_type == WorkflowSignal.PAUSE
    assert signals[0].payload == {"reason": "a"}
    assert signals[1].signal_type == WorkflowSignal.CANCEL
    assert signals[1].payload == {"reason": "b"}


@pytest.mark.asyncio
async def test_drain_marks_signals_with_processed_events(session: AsyncSession) -> None:
    transport = _transport(session)
    signal = await transport.enqueue("run-1", WorkflowSignal.PAUSE)

    await transport.drain("run-1")

    positions = await _processed_positions(session, "run-1")
    assert signal.id in positions


@pytest.mark.asyncio
async def test_drain_skips_already_processed_signals(session: AsyncSession) -> None:
    store = SqliteEventStore(session)
    transport = _transport(session)

    sig = await transport.enqueue("run-1", WorkflowSignal.PAUSE)

    # Manually insert SignalProcessed to simulate prior processing
    await store.append(
        [
            SignalProcessed(
                run_id="run-1",
                event_type="signal_processed",
                enqueued_position=sig.id,
            )
        ]
    )

    result = await transport.drain("run-1")
    assert result == []


@pytest.mark.asyncio
async def test_drain_only_returns_unprocessed_of_mixed_batch(session: AsyncSession) -> None:
    store = SqliteEventStore(session)
    transport = _transport(session)

    sig_a = await transport.enqueue("run-1", WorkflowSignal.PAUSE)
    sig_b = await transport.enqueue("run-1", WorkflowSignal.RESUME)

    # Mark only sig_a as processed
    await store.append(
        [
            SignalProcessed(
                run_id="run-1",
                event_type="signal_processed",
                enqueued_position=sig_a.id,
            )
        ]
    )

    result = await transport.drain("run-1")
    assert len(result) == 1
    assert result[0].signal_type == WorkflowSignal.RESUME
    assert result[0].id == sig_b.id


@pytest.mark.asyncio
async def test_drain_stores_only_signal_events(session: AsyncSession) -> None:
    transport = _transport(session)
    await transport.enqueue("run-1", WorkflowSignal.PAUSE)
    await transport.drain("run-1")

    assert await _event_types(session, "run-1") == ["signal_enqueued", "signal_processed"]


@pytest.mark.asyncio
async def test_drain_isolates_signals_by_run_id(session: AsyncSession) -> None:
    transport = _transport(session)
    await transport.enqueue("run-A", WorkflowSignal.PAUSE)
    await transport.enqueue("run-B", WorkflowSignal.CANCEL)

    signals_a = await transport.drain("run-A")
    signals_b = await transport.drain("run-B")

    assert len(signals_a) == 1
    assert signals_a[0].run_id == "run-A"
    assert len(signals_b) == 1
    assert signals_b[0].run_id == "run-B"


@pytest.mark.asyncio
async def test_run_workflow_does_not_consume_event_backed_signals(
    session: AsyncSession,
) -> None:
    transport = _transport(session)
    workflow = RunWorkflow(run_id="run-1", transport=transport)
    signal = await transport.enqueue("run-1", WorkflowSignal.PAUSE, {"reason": "manual"})
    await session.commit()

    service = RecordingSignalService()
    should_stop = await workflow.on_signal(session, service)  # type: ignore[arg-type]
    await session.commit()

    assert should_stop is False
    assert service.pause_calls == 0
    assert await _processed_positions(session, "run-1") == set()
    pending = await transport.pending("run-1")
    assert [item.id for item in pending] == [signal.id]
