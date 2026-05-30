"""Integration tests for EventSignalTransport with a real migrated DB.

Verifies R2: enqueue() writes SignalEnqueued to events_v2; drain() marks
consumed with SignalProcessed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import SqliteEventStore
from orchestrator.db import EventV2Model
from orchestrator.db import RunLifecycleProjector
from orchestrator.workflow import SignalConsumer
from orchestrator.workflow import (
    EventSignalTransport,
    SignalForInactiveRunError,
    WorkflowSignal,
)


@pytest.fixture
async def engine():
    eng = create_engine(":memory:")
    await init_db(eng)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(engine) -> async_sessionmaker:
    return create_session_factory(engine)


@pytest.fixture
async def session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as s:
        yield s


def _transport(
    session: AsyncSession, projector: RunLifecycleProjector | None = None
) -> EventSignalTransport:
    return EventSignalTransport(
        SqliteEventStore(session),
        projector or RunLifecycleProjector(),
        projector_preloaded=projector is not None,
    )


async def _enqueued_count(session: AsyncSession, run_id: str) -> int:
    result = await session.execute(
        select(EventV2Model).where(
            EventV2Model.aggregate_id == run_id, EventV2Model.event_type == "signal_enqueued"
        )
    )
    return len(list(result.scalars()))


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


@pytest.mark.asyncio
async def test_enqueue_writes_signal_enqueued_to_events_v2(session: AsyncSession) -> None:
    """enqueue() creates a SignalEnqueued row in events_v2."""
    transport = _transport(session)
    signal = await transport.enqueue("run-1", WorkflowSignal.PAUSE, {"reason": "manual"})

    assert signal.id > 0
    assert await _enqueued_count(session, "run-1") == 1
    assert await _event_types(session, "run-1") == ["signal_enqueued"]


@pytest.mark.asyncio
async def test_drain_marks_consumed_with_signal_processed(session: AsyncSession) -> None:
    """drain() appends SignalProcessed events to events_v2 after processing."""
    transport = _transport(session)
    sig_a = await transport.enqueue("run-1", WorkflowSignal.PAUSE, {"reason": "a"})
    sig_b = await transport.enqueue("run-1", WorkflowSignal.CANCEL, {"reason": "b"})

    signals = await transport.drain("run-1")

    assert len(signals) == 2
    assert signals[0].signal_type == WorkflowSignal.PAUSE
    assert signals[1].signal_type == WorkflowSignal.CANCEL

    processed = await _processed_positions(session, "run-1")
    assert sig_a.id in processed
    assert sig_b.id in processed

    assert await _event_types(session, "run-1") == [
        "signal_enqueued",
        "signal_enqueued",
        "signal_processed",
        "signal_processed",
    ]


@pytest.mark.asyncio
async def test_drain_idempotent_after_processed(session: AsyncSession) -> None:
    """Once signals are processed, subsequent drain() calls return empty list."""
    transport = _transport(session)
    await transport.enqueue("run-1", WorkflowSignal.PAUSE)

    first = await transport.drain("run-1")
    second = await transport.drain("run-1")

    assert len(first) == 1
    assert second == []


@pytest.mark.asyncio
async def test_enqueue_raises_for_terminal_run(session: AsyncSession) -> None:
    """enqueue() raises SignalForInactiveRunError for a terminal run."""
    projector = RunLifecycleProjector()
    projector._terminal.add("run-done")
    transport = _transport(session, projector)

    with pytest.raises(SignalForInactiveRunError) as exc_info:
        await transport.enqueue("run-done", WorkflowSignal.PAUSE)

    assert exc_info.value.run_id == "run-done"
    assert await _enqueued_count(session, "run-done") == 0


@pytest.mark.asyncio
async def test_multiple_runs_signals_isolated(session: AsyncSession) -> None:
    """Signals for different run_ids are isolated from each other."""
    transport = _transport(session)
    sig_a = await transport.enqueue("run-A", WorkflowSignal.PAUSE)
    sig_b = await transport.enqueue("run-B", WorkflowSignal.CANCEL)

    drain_a = await transport.drain("run-A")
    drain_b = await transport.drain("run-B")

    assert len(drain_a) == 1 and drain_a[0].run_id == "run-A"
    assert len(drain_b) == 1 and drain_b[0].run_id == "run-B"

    # Only run-A's signal is processed after drain-A
    processed_a = await _processed_positions(session, "run-A")
    assert sig_a.id in processed_a

    # run-B's signal is processed after drain-B
    processed_b = await _processed_positions(session, "run-B")
    assert sig_b.id in processed_b


# ---------------------------------------------------------------------------
# Startup recovery
# ---------------------------------------------------------------------------


@dataclass
class _FakeRun:
    agent_runner_type: Any = None
    agent_runner_config: dict[str, Any] = field(default_factory=dict)


class _RecordingService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._run = _FakeRun()

    async def apply_pause_run(
        self, run_id: str, *, reason: str, error_detail: str | None = None
    ) -> _FakeRun:
        self.calls.append(f"pause:{run_id}")
        return self._run

    async def apply_start_run(self, run_id: str) -> _FakeRun:
        self.calls.append(f"start:{run_id}")
        return self._run

    async def apply_resume_run(self, run_id: str, **_: Any) -> _FakeRun:
        self.calls.append(f"resume:{run_id}")
        return self._run

    async def apply_cancel_run(self, run_id: str, **_: Any) -> _FakeRun:
        self.calls.append(f"cancel:{run_id}")
        return self._run

    async def apply_submission(self, run_id: str, task_id: str) -> _FakeRun:
        self.calls.append(f"submission:{run_id}")
        return self._run

    async def apply_verification(self, run_id: str, task_id: str) -> _FakeRun:
        self.calls.append(f"verification:{run_id}")
        return self._run


@pytest.mark.asyncio
async def test_startup_recovery_redelivers_unprocessed_signal(
    session_factory: async_sessionmaker,
) -> None:
    """SignalConsumer.start() redelivers unprocessed signals from a crashed run.

    Simulates a crash scenario: a SignalEnqueued event exists in events_v2 but
    has no corresponding SignalProcessed event. After start(), the consumer
    replays the signal and appends a SignalProcessed event.
    """
    # Pre-seed a PAUSE signal that was never processed
    async with session_factory() as s:
        store = SqliteEventStore(s)
        from orchestrator.workflow import SignalEnqueued

        stored = await store.append(
            [
                SignalEnqueued(
                    run_id="run-crashed",
                    event_type="signal_enqueued",
                    signal_type="pause",
                    payload={"reason": "crash-test"},
                )
            ]
        )
        enqueued_pos = stored[0].position
        await s.commit()

    svc = _RecordingService()

    async def _create_service(session: AsyncSession) -> _RecordingService:
        return svc

    consumer = SignalConsumer(session_factory, _create_service, poll_interval=100.0)
    await consumer.start()
    await consumer.stop()

    # Verify the signal was marked processed
    async with session_factory() as s:
        processed = await _processed_positions(s, "run-crashed")
    assert enqueued_pos in processed

    # Verify the handler was invoked
    assert any("pause:run-crashed" in c for c in svc.calls)
