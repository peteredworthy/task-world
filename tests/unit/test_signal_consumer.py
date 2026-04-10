"""Unit tests for SignalConsumer.

Covers:
- FIFO ordering per run_id (signals processed in PK order)
- delivered_at stamped before handler invocation
- handled_at stamped after successful handler completion
- Error path leaves handled_at NULL (eligible for redelivery)
- All signal types with active and inactive RunWorkflow paths
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
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
    """In-memory SQLite engine with the schema created."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


def _make_service(
    start_run_result=None,
    resume_run_result=None,
) -> Any:
    """Build a minimal mock WorkflowService."""
    svc = MagicMock()

    run_stub = MagicMock()
    run_stub.agent_type = None
    run_stub.agent_config = {}

    # Public lifecycle methods (kept for backward compat with some tests)
    svc.start_run = AsyncMock(return_value=start_run_result or run_stub)
    svc.resume_run = AsyncMock(return_value=resume_run_result or run_stub)
    svc.pause_run = AsyncMock(return_value=MagicMock())
    svc.cancel_run = AsyncMock(return_value=MagicMock())
    # _apply_* methods called by the consumer (Phase 3)
    svc.apply_start_run = AsyncMock(return_value=start_run_result or run_stub)
    svc.apply_resume_run = AsyncMock(return_value=resume_run_result or run_stub)
    svc.apply_pause_run = AsyncMock(return_value=MagicMock())
    svc.apply_cancel_run = AsyncMock(return_value=MagicMock())
    svc.submit_for_verification = AsyncMock(return_value=MagicMock())
    svc.complete_verification = AsyncMock(return_value=MagicMock())
    svc.apply_submission = AsyncMock(return_value=MagicMock())
    svc.apply_verification = AsyncMock(return_value=MagicMock())
    return svc


async def _insert_signal(
    session_factory: async_sessionmaker,
    run_id: str,
    signal_type: WorkflowSignal,
    payload: dict | None = None,
    delivered_at: datetime | None = None,
    handled_at: datetime | None = None,
) -> int:
    """Insert a PendingSignalModel and return its PK."""
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
# FIFO ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fifo_ordering_per_run_id(session_factory):
    """Signals for a run are processed in ascending PK order."""
    call_order: list[WorkflowSignal] = []
    service = _make_service()

    # Capture which signal types are called (PAUSE and CANCEL in sequence)
    async def capture_pause(*args, **kwargs):
        call_order.append(WorkflowSignal.PAUSE)

    async def capture_cancel(*args, **kwargs):
        call_order.append(WorkflowSignal.CANCEL)

    service.apply_pause_run = AsyncMock(side_effect=capture_pause)
    service.apply_cancel_run = AsyncMock(side_effect=capture_cancel)

    create_service = AsyncMock(return_value=service)

    consumer = SignalConsumer(session_factory, create_service)

    # Insert signals in a specific order — PAUSE first (lower PK), CANCEL second
    id_pause = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.PAUSE, payload={"reason": "manual"}
    )
    id_cancel = await _insert_signal(session_factory, "run-1", WorkflowSignal.CANCEL)

    # Process both via _process_run (serial per run_id)
    await consumer._process_run("run-1")

    assert call_order == [WorkflowSignal.PAUSE, WorkflowSignal.CANCEL], (
        "Signals must be processed FIFO by PK"
    )

    # Both signals should be handled
    sig_pause = await _get_signal(session_factory, id_pause)
    sig_cancel = await _get_signal(session_factory, id_cancel)
    assert sig_pause.handled_at is not None
    assert sig_cancel.handled_at is not None


@pytest.mark.asyncio
async def test_fifo_ordering_multiple_runs_independent(session_factory):
    """Signals for different run_ids are independent — each run has its own FIFO."""
    call_order: list[tuple[str, WorkflowSignal]] = []
    service = _make_service()

    async def capture_pause(run_id, *args, **kwargs):
        call_order.append((run_id, WorkflowSignal.PAUSE))

    service.apply_pause_run = AsyncMock(side_effect=capture_pause)

    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    await _insert_signal(session_factory, "run-A", WorkflowSignal.PAUSE, {"reason": "a"})
    await _insert_signal(session_factory, "run-B", WorkflowSignal.PAUSE, {"reason": "b"})

    # Process each run separately (as _tick would do)
    await consumer._process_run("run-A")
    await consumer._process_run("run-B")

    run_a_calls = [x for x in call_order if x[0] == "run-A"]
    run_b_calls = [x for x in call_order if x[0] == "run-B"]
    assert len(run_a_calls) == 1
    assert len(run_b_calls) == 1


# ---------------------------------------------------------------------------
# Delivery tracking (R3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivered_at_set_before_handler(session_factory):
    """delivered_at is stamped BEFORE the handler is invoked."""
    delivered_at_during_handler: datetime | None = None
    service = _make_service()

    async def check_delivered_at(run_id, *args, **kwargs):
        nonlocal delivered_at_during_handler
        async with session_factory() as s:
            result = await s.execute(
                select(PendingSignalModel).where(PendingSignalModel.run_id == run_id)
            )
            row = result.scalar_one()
            delivered_at_during_handler = row.delivered_at

    service.apply_pause_run = AsyncMock(side_effect=check_delivered_at)
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    sig_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.PAUSE, {"reason": "test"}
    )

    # Verify delivered_at is initially None
    initial = await _get_signal(session_factory, sig_id)
    assert initial.delivered_at is None

    await consumer._dispatch_signal_by_id(sig_id)

    # delivered_at was set when handler ran
    assert delivered_at_during_handler is not None, "delivered_at must be set before handler"


@pytest.mark.asyncio
async def test_handled_at_set_after_success(session_factory):
    """handled_at is stamped AFTER successful handler completion."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    sig_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.PAUSE, {"reason": "test"}
    )

    await consumer._dispatch_signal_by_id(sig_id)

    sig = await _get_signal(session_factory, sig_id)
    assert sig.delivered_at is not None, "delivered_at must be set"
    assert sig.handled_at is not None, "handled_at must be set after success"
    # handled_at >= delivered_at
    assert sig.handled_at >= sig.delivered_at


@pytest.mark.asyncio
async def test_error_leaves_handled_at_null(session_factory):
    """When handler raises, handled_at stays NULL (eligible for redelivery)."""
    service = _make_service()
    service.apply_pause_run = AsyncMock(side_effect=RuntimeError("simulated failure"))
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    sig_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.PAUSE, {"reason": "test"}
    )

    await consumer._dispatch_signal_by_id(sig_id)

    sig = await _get_signal(session_factory, sig_id)
    assert sig.delivered_at is not None, "delivered_at must still be set"
    assert sig.handled_at is None, "handled_at must stay NULL on error"


# ---------------------------------------------------------------------------
# Signal handlers — inactive RunWorkflow path (no active workflow)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_start_inactive_path(session_factory):
    """RUN_START: calls start_run, registers workflow in active_workflows."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    sig_id = await _insert_signal(session_factory, "run-1", WorkflowSignal.RUN_START)

    await consumer._dispatch_signal_by_id(sig_id)

    service.apply_start_run.assert_awaited_once_with("run-1")
    assert "run-1" in consumer._active_workflows
    assert has_active_workflow("run-1")

    # cleanup
    unregister_active_run("run-1")


@pytest.mark.asyncio
async def test_resume_inactive_path(session_factory):
    """RESUME: calls resume_run, registers workflow in active_workflows."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    sig_id = await _insert_signal(session_factory, "run-1", WorkflowSignal.RESUME)

    await consumer._dispatch_signal_by_id(sig_id)

    service.apply_resume_run.assert_awaited_once_with(
        "run-1", agent_type=None, agent_config=None, resume_strategy=None
    )
    assert "run-1" in consumer._active_workflows
    assert has_active_workflow("run-1")

    # cleanup
    unregister_active_run("run-1")


@pytest.mark.asyncio
async def test_pause_no_active_workflow(session_factory):
    """PAUSE without active workflow: calls pause_run directly."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    sig_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.PAUSE, {"reason": "manual_pause"}
    )

    await consumer._dispatch_signal_by_id(sig_id)

    service.apply_pause_run.assert_awaited_once_with(
        "run-1", reason="manual_pause", error_detail=None
    )
    assert "run-1" not in consumer._active_workflows


@pytest.mark.asyncio
async def test_cancel_no_active_workflow(session_factory):
    """CANCEL without active workflow: calls cancel_run directly."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    sig_id = await _insert_signal(session_factory, "run-1", WorkflowSignal.CANCEL)

    await consumer._dispatch_signal_by_id(sig_id)

    service.apply_cancel_run.assert_awaited_once_with("run-1", reason=None)


@pytest.mark.asyncio
async def test_activity_completed_no_active_workflow(session_factory):
    """ACTIVITY_COMPLETED without active workflow: calls apply_submission."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    sig_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_COMPLETED, {"task_id": "task-42"}
    )

    await consumer._dispatch_signal_by_id(sig_id)

    service.apply_submission.assert_awaited_once_with("run-1", "task-42")


@pytest.mark.asyncio
async def test_activity_verified_no_active_workflow(session_factory):
    """ACTIVITY_VERIFIED without active workflow: calls apply_verification."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    sig_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_VERIFIED, {"task_id": "task-99"}
    )

    await consumer._dispatch_signal_by_id(sig_id)

    service.apply_verification.assert_awaited_once_with("run-1", "task-99")


# ---------------------------------------------------------------------------
# Signal handlers — active RunWorkflow path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_with_active_workflow(session_factory):
    """PAUSE with active workflow: unregisters workflow, calls pause_run."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    # Simulate an active workflow for run-1
    from orchestrator.workflow import RunWorkflow

    wf = RunWorkflow(run_id="run-1")
    consumer._active_workflows["run-1"] = wf
    register_active_run("run-1")

    sig_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.PAUSE, {"reason": "user_pause"}
    )

    await consumer._dispatch_signal_by_id(sig_id)

    # Workflow must be unregistered
    assert "run-1" not in consumer._active_workflows
    assert not has_active_workflow("run-1")
    # _apply_pause_run called (direct DB path)
    service.apply_pause_run.assert_awaited_once_with(
        "run-1", reason="user_pause", error_detail=None
    )


@pytest.mark.asyncio
async def test_cancel_with_active_workflow(session_factory):
    """CANCEL with active workflow: unregisters workflow, calls cancel_run."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    from orchestrator.workflow import RunWorkflow

    wf = RunWorkflow(run_id="run-1")
    consumer._active_workflows["run-1"] = wf
    register_active_run("run-1")

    sig_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.CANCEL, {"reason": "user_cancel"}
    )

    await consumer._dispatch_signal_by_id(sig_id)

    assert "run-1" not in consumer._active_workflows
    assert not has_active_workflow("run-1")
    service.apply_cancel_run.assert_awaited_once_with("run-1", reason="user_cancel")


@pytest.mark.asyncio
async def test_activity_completed_with_active_workflow(session_factory):
    """ACTIVITY_COMPLETED with active workflow: delegates to workflow handler."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    from orchestrator.workflow import RunWorkflow

    wf = RunWorkflow(run_id="run-1")
    wf.handle_activity_completed = AsyncMock(return_value=False)
    consumer._active_workflows["run-1"] = wf

    sig_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_COMPLETED, {"task_id": "task-7"}
    )

    await consumer._dispatch_signal_by_id(sig_id)

    wf.handle_activity_completed.assert_awaited_once()
    # Direct service call should NOT happen
    service.submit_for_verification.assert_not_awaited()


@pytest.mark.asyncio
async def test_activity_verified_with_active_workflow(session_factory):
    """ACTIVITY_VERIFIED with active workflow: delegates to workflow handler."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    from orchestrator.workflow import RunWorkflow

    wf = RunWorkflow(run_id="run-1")
    wf.handle_activity_verified = AsyncMock(return_value=False)
    consumer._active_workflows["run-1"] = wf

    sig_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_VERIFIED, {"task_id": "task-8"}
    )

    await consumer._dispatch_signal_by_id(sig_id)

    wf.handle_activity_verified.assert_awaited_once()
    service.complete_verification.assert_not_awaited()


# ---------------------------------------------------------------------------
# find_pending_run_ids — only returns undelivered signals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_pending_run_ids_excludes_delivered(session_factory):
    """_find_pending_run_ids only returns run_ids with undelivered signals."""
    await _insert_signal(session_factory, "run-new", WorkflowSignal.PAUSE, {"reason": "x"})
    await _insert_signal(
        session_factory,
        "run-delivered",
        WorkflowSignal.PAUSE,
        {"reason": "y"},
        delivered_at=datetime.now(timezone.utc),
    )
    await _insert_signal(
        session_factory,
        "run-handled",
        WorkflowSignal.PAUSE,
        {"reason": "z"},
        delivered_at=datetime.now(timezone.utc),
        handled_at=datetime.now(timezone.utc),
    )

    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    run_ids = await consumer._find_pending_run_ids()

    assert "run-new" in run_ids
    assert "run-delivered" not in run_ids
    assert "run-handled" not in run_ids


# ---------------------------------------------------------------------------
# Pause default reason
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_default_reason(session_factory):
    """PAUSE with no payload uses 'signal_pause' as default reason."""
    service = _make_service()
    create_service = AsyncMock(return_value=service)
    consumer = SignalConsumer(session_factory, create_service)

    sig_id = await _insert_signal(session_factory, "run-1", WorkflowSignal.PAUSE)

    await consumer._dispatch_signal_by_id(sig_id)

    service.apply_pause_run.assert_awaited_once_with(
        "run-1", reason="signal_pause", error_detail=None
    )
