"""Unit tests for SignalConsumer startup redelivery."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

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


@dataclass
class ServiceRun:
    agent_runner_type: Any = None
    agent_runner_config: dict[str, Any] = field(default_factory=dict)


class RecordingWorkflowService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.run = ServiceRun()

    async def apply_start_run(self, run_id: str) -> ServiceRun:
        self.calls.append(("apply_start_run", (run_id,), {}))
        return self.run

    async def apply_resume_run(
        self,
        run_id: str,
        *,
        agent_runner_type: Any = None,
        agent_runner_config: dict[str, Any] | None = None,
        resume_strategy: str | None = None,
    ) -> ServiceRun:
        self.calls.append(
            (
                "apply_resume_run",
                (run_id,),
                {
                    "agent_runner_type": agent_runner_type,
                    "agent_runner_config": agent_runner_config,
                    "resume_strategy": resume_strategy,
                },
            )
        )
        return self.run

    async def apply_pause_run(
        self,
        run_id: str,
        *,
        reason: str,
        error_detail: str | None = None,
    ) -> ServiceRun:
        self.calls.append(
            ("apply_pause_run", (run_id,), {"reason": reason, "error_detail": error_detail})
        )
        return self.run

    async def apply_cancel_run(self, run_id: str, *, reason: str | None = None) -> ServiceRun:
        self.calls.append(("apply_cancel_run", (run_id,), {"reason": reason}))
        return self.run

    async def apply_submission(self, run_id: str, task_id: str) -> ServiceRun:
        self.calls.append(("apply_submission", (run_id, task_id), {}))
        return self.run

    async def apply_verification(self, run_id: str, task_id: str) -> ServiceRun:
        self.calls.append(("apply_verification", (run_id, task_id), {}))
        return self.run


class ServiceFactory:
    def __init__(self, service: RecordingWorkflowService) -> None:
        self.service = service

    async def __call__(self, session: Any) -> RecordingWorkflowService:
        return self.service


def _calls(service: RecordingWorkflowService, name: str) -> list[tuple[tuple[Any, ...], dict]]:
    return [(args, kwargs) for call_name, args, kwargs in service.calls if call_name == name]


def _consumer(session_factory: async_sessionmaker, service: RecordingWorkflowService):
    return SignalConsumer(session_factory, ServiceFactory(service))


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


@pytest.mark.asyncio
async def test_startup_redelivery_processes_crashed_signal(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    crashed_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig_id = await _insert_signal(
        session_factory,
        run_id="run-crashed",
        signal_type=WorkflowSignal.PAUSE,
        payload={"reason": "manual"},
        delivered_at=crashed_at,
        handled_at=None,
    )

    assert not has_active_workflow("run-crashed")
    await consumer._redeliver_on_startup()

    assert (await _get_signal(session_factory, sig_id)).handled_at is not None
    assert _calls(service, "apply_pause_run") == [
        (("run-crashed",), {"reason": "manual", "error_detail": None})
    ]


@pytest.mark.asyncio
async def test_startup_redelivery_skips_active_runs(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    crashed_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig_id = await _insert_signal(
        session_factory,
        run_id="run-active",
        signal_type=WorkflowSignal.PAUSE,
        payload={"reason": "manual"},
        delivered_at=crashed_at,
        handled_at=None,
    )
    register_active_run("run-active")

    try:
        await consumer._redeliver_on_startup()

        assert (await _get_signal(session_factory, sig_id)).handled_at is None
        assert _calls(service, "apply_pause_run") == []
    finally:
        unregister_active_run("run-active")


@pytest.mark.asyncio
async def test_startup_redelivery_ignores_already_handled_and_fresh(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    completed_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    handled_id = await _insert_signal(
        session_factory,
        run_id="run-done",
        signal_type=WorkflowSignal.PAUSE,
        payload={"reason": "handled"},
        delivered_at=completed_at,
        handled_at=completed_at,
    )
    fresh_id = await _insert_signal(
        session_factory,
        run_id="run-fresh",
        signal_type=WorkflowSignal.PAUSE,
        payload={"reason": "fresh"},
        delivered_at=None,
        handled_at=None,
    )

    await consumer._redeliver_on_startup()

    assert (await _get_signal(session_factory, handled_id)).handled_at is not None
    assert (await _get_signal(session_factory, fresh_id)).handled_at is None
    assert _calls(service, "apply_pause_run") == []


@pytest.mark.asyncio
async def test_startup_redelivery_multiple_signals_ordered_by_pk(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    crashed_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
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

    await consumer._redeliver_on_startup()

    assert id_a < id_b
    assert [args[0] for args, _ in _calls(service, "apply_pause_run")] == ["run-A", "run-B"]


@pytest.mark.asyncio
async def test_startup_redelivery_updates_delivered_at(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
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
    delivered_naive = (
        sig.delivered_at.replace(tzinfo=None) if sig.delivered_at.tzinfo else sig.delivered_at
    )
    assert delivered_naive.year >= 2025
    assert sig.handled_at is not None


@pytest.mark.asyncio
async def test_consumer_start_triggers_redelivery(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = SignalConsumer(
        session_factory,
        ServiceFactory(service),
        poll_interval=100.0,
    )
    crashed_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig_id = await _insert_signal(
        session_factory,
        run_id="run-cr",
        signal_type=WorkflowSignal.PAUSE,
        payload={"reason": "srv"},
        delivered_at=crashed_at,
        handled_at=None,
    )

    await consumer.start()
    await consumer.stop()

    assert (await _get_signal(session_factory, sig_id)).handled_at is not None
    assert _calls(service, "apply_pause_run") == [
        (("run-cr",), {"reason": "srv", "error_detail": None})
    ]
