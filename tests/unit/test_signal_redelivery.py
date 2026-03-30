"""Unit tests for SignalConsumer startup redelivery (R4).

Covers:
- Signals with delivered_at set and handled_at NULL are redelivered on startup
- Redelivery only applies to runs with no active RunWorkflow
- Successful redelivery sets handled_at
- Signals for runs with active workflows are skipped during redelivery
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.db import Base, PendingSignalModel
from orchestrator.workflow import (
    SignalConsumer,
    WorkflowSignal,
    has_active_workflow,
    register_active_run,
    unregister_active_run,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


def _make_service() -> MagicMock:
    svc = MagicMock()
    run_stub = MagicMock()
    run_stub.agent_type = None
    run_stub.agent_config = {}
    svc.start_run = AsyncMock(return_value=run_stub)
    svc.resume_run = AsyncMock(return_value=run_stub)
    svc.pause_run = AsyncMock(return_value=MagicMock())
    svc.cancel_run = AsyncMock(return_value=MagicMock())
    # _apply_* methods called by the consumer (Phase 3)
    svc.apply_start_run = AsyncMock(return_value=run_stub)
    svc.apply_resume_run = AsyncMock(return_value=run_stub)
    svc.apply_pause_run = AsyncMock(return_value=MagicMock())
    svc.apply_cancel_run = AsyncMock(return_value=MagicMock())
    svc.submit_for_verification = AsyncMock(return_value=MagicMock())
    svc.complete_verification = AsyncMock(return_value=MagicMock())
    return svc


async def _insert_signal(
    session_factory: async_sessionmaker,
    run_id: str,
    signal_type: WorkflowSignal,
    payload: dict | None = None,
    delivered_at: datetime | None = None,
    handled_at: datetime | None = None,
) -> int:
    async with session_factory() as session:
        model = PendingSignalModel(
            run_id=run_id,
            signal_type=signal_type.value,
            payload=json.dumps(payload) if payload is not None else None,
            created_at=datetime.now(timezone.utc),
            delivered_at=delivered_at,
            handled_at=handled_at,
        )
        session.add(model)
        await session.commit()
        await session.refresh(model)
        return model.id


async def _get_signal(session_factory: async_sessionmaker, signal_id: int) -> PendingSignalModel:
    async with session_factory() as session:
        result = await session.execute(
            select(PendingSignalModel).where(PendingSignalModel.id == signal_id)
        )
        return result.scalar_one()


# ---------------------------------------------------------------------------
# Crash redelivery tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_redelivery_processes_crashed_signal(session_factory):
    """Signal with delivered_at set and handled_at NULL is redelivered on startup."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    # Simulate a crash: delivered_at set but handled_at null
    crashed_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig_id = await _insert_signal(
        session_factory,
        run_id="run-crashed",
        signal_type=WorkflowSignal.PAUSE,
        payload={"reason": "manual"},
        delivered_at=crashed_at,  # Was delivered before crash
        handled_at=None,  # Handler never completed
    )

    # run-crashed has no active workflow → eligible for redelivery
    assert not has_active_workflow("run-crashed")

    await consumer._redeliver_on_startup()

    # Signal should now be handled
    sig = await _get_signal(session_factory, sig_id)
    assert sig.handled_at is not None, "Crashed signal must be handled on redelivery"
    # The service handler should have been called
    service.apply_pause_run.assert_awaited_once_with(
        "run-crashed", reason="manual", error_detail=None
    )


@pytest.mark.asyncio
async def test_startup_redelivery_skips_active_runs(session_factory):
    """Signals for runs with active workflows are NOT redelivered on startup."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    # Insert a crashed signal for a run that now has an active workflow
    crashed_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig_id = await _insert_signal(
        session_factory,
        run_id="run-active",
        signal_type=WorkflowSignal.PAUSE,
        payload={"reason": "manual"},
        delivered_at=crashed_at,
        handled_at=None,
    )

    # Mark run-active as having an active workflow
    register_active_run("run-active")

    try:
        await consumer._redeliver_on_startup()

        # Signal should NOT be processed (active workflow present)
        sig = await _get_signal(session_factory, sig_id)
        assert sig.handled_at is None, "Signal for active run must not be redelivered"
        service.apply_pause_run.assert_not_awaited()
    finally:
        unregister_active_run("run-active")


@pytest.mark.asyncio
async def test_startup_redelivery_ignores_already_handled(session_factory):
    """Signals that are fully handled (handled_at set) are not redelivered."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    completed_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _insert_signal(
        session_factory,
        run_id="run-done",
        signal_type=WorkflowSignal.PAUSE,
        payload={"reason": "manual"},
        delivered_at=completed_at,
        handled_at=completed_at,  # Already handled
    )

    await consumer._redeliver_on_startup()

    # Service should not be called again
    service.apply_pause_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_redelivery_ignores_fresh_signals(session_factory):
    """Signals with neither delivered_at nor handled_at set are not redelivered at startup.

    These are new signals waiting for the normal poll loop.
    """
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    sig_id = await _insert_signal(
        session_factory,
        run_id="run-fresh",
        signal_type=WorkflowSignal.PAUSE,
        payload={"reason": "x"},
        delivered_at=None,
        handled_at=None,
    )

    await consumer._redeliver_on_startup()

    # Not processed by redelivery — handled_at still null
    sig = await _get_signal(session_factory, sig_id)
    assert sig.handled_at is None, "Fresh signals must not be redelivered on startup"
    service.apply_pause_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_redelivery_multiple_signals_ordered_by_pk(session_factory):
    """Multiple crashed signals are redelivered in PK order."""
    call_order: list[str] = []
    service = _make_service()

    async def capture_pause(run_id, *args, **kwargs):
        call_order.append(run_id)

    service.apply_pause_run = AsyncMock(side_effect=capture_pause)
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    crashed_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Insert in order A, B — PKs should reflect insertion order
    id_a = await _insert_signal(
        session_factory,
        "run-A",
        WorkflowSignal.PAUSE,
        {"reason": "a"},
        delivered_at=crashed_at,
    )
    id_b = await _insert_signal(
        session_factory,
        "run-B",
        WorkflowSignal.PAUSE,
        {"reason": "b"},
        delivered_at=crashed_at,
    )

    assert id_a < id_b  # PK ordering should match insertion order

    await consumer._redeliver_on_startup()

    # Both should be handled in PK order
    assert call_order == ["run-A", "run-B"]


@pytest.mark.asyncio
async def test_startup_redelivery_updates_delivered_at(session_factory):
    """Redelivery refreshes delivered_at to current time."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    old_delivered_at = datetime(2020, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
    sig_id = await _insert_signal(
        session_factory,
        run_id="run-old",
        signal_type=WorkflowSignal.CANCEL,
        delivered_at=old_delivered_at,
        handled_at=None,
    )

    await consumer._redeliver_on_startup()

    sig = await _get_signal(session_factory, sig_id)
    assert sig.delivered_at is not None
    # delivered_at must have been updated (not the old 2020 value)
    delivered_naive = (
        sig.delivered_at.replace(tzinfo=None) if sig.delivered_at.tzinfo else sig.delivered_at
    )
    assert delivered_naive.year >= 2025, "delivered_at must be refreshed to current time"
    assert sig.handled_at is not None


@pytest.mark.asyncio
async def test_consumer_start_triggers_redelivery(session_factory):
    """consumer.start() calls _redeliver_on_startup before beginning the poll loop."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service, poll_interval=100.0)

    crashed_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig_id = await _insert_signal(
        session_factory,
        run_id="run-cr",
        signal_type=WorkflowSignal.PAUSE,
        payload={"reason": "srv"},
        delivered_at=crashed_at,
        handled_at=None,
    )

    # Start consumer (with a very long poll interval so it doesn't actually poll)
    await consumer.start()
    await consumer.stop()

    # The crashed signal should have been redelivered during startup
    sig = await _get_signal(session_factory, sig_id)
    assert sig.handled_at is not None, "Crashed signal must be handled during start()"
    service.apply_pause_run.assert_awaited_once_with("run-cr", reason="srv", error_detail=None)
