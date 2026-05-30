"""Unit tests for SignalConsumer startup redelivery."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.db import Base
from orchestrator.db import EventV2Model
from orchestrator.workflow import (
    SignalConsumer,
    WorkflowSignal,
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


async def _insert_signal_event(
    session_factory: async_sessionmaker,
    run_id: str,
    signal_type: WorkflowSignal,
    payload: dict | None = None,
) -> int:
    """Insert a SignalEnqueued event into events_v2, return the event position."""
    from orchestrator.db import SqliteEventStore
    from orchestrator.workflow import SignalEnqueued

    async with session_factory() as session:
        store = SqliteEventStore(session)
        event = SignalEnqueued(
            run_id=run_id,
            event_type="signal_enqueued",
            signal_type=signal_type.value,
            payload=payload,
        )
        stored = await store.append([event])
        await session.commit()
        return stored[0].position


async def _get_processed_positions(session_factory: async_sessionmaker, run_id: str) -> set[int]:
    """Return the set of enqueued_positions that have been processed for a run."""
    async with session_factory() as session:
        result = await session.execute(
            select(EventV2Model.payload).where(
                EventV2Model.aggregate_id == run_id,
                EventV2Model.event_type == "signal_processed",
            )
        )
        rows = list(result.scalars())
    positions = set()
    for p in rows:
        data = json.loads(p)
        pos = data.get("enqueued_position")
        if isinstance(pos, int):
            positions.add(pos)
    return positions


@pytest.mark.asyncio
async def test_startup_redelivery_processes_pending_signal(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    pos = await _insert_signal_event(
        session_factory, "run-crashed", WorkflowSignal.PAUSE, {"reason": "manual"}
    )

    await consumer._redeliver_on_startup()

    processed = await _get_processed_positions(session_factory, "run-crashed")
    assert pos in processed
    assert _calls(service, "apply_pause_run") == [
        (("run-crashed",), {"reason": "manual", "error_detail": None})
    ]


@pytest.mark.asyncio
async def test_startup_redelivery_skips_active_runs(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    pos = await _insert_signal_event(
        session_factory, "run-active", WorkflowSignal.PAUSE, {"reason": "manual"}
    )

    # Mark run as active in the projector (simulates an in-flight executor)
    consumer._projector._active.add("run-active")

    await consumer._redeliver_on_startup()

    processed = await _get_processed_positions(session_factory, "run-active")
    assert pos not in processed
    assert _calls(service, "apply_pause_run") == []


@pytest.mark.asyncio
async def test_startup_redelivery_ignores_processed_signals(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)

    from orchestrator.db import SqliteEventStore
    from orchestrator.workflow import SignalProcessed

    pos_done = await _insert_signal_event(
        session_factory, "run-done", WorkflowSignal.PAUSE, {"reason": "handled"}
    )
    async with session_factory() as session:
        store = SqliteEventStore(session)
        await store.append(
            [
                SignalProcessed(
                    run_id="run-done",
                    event_type="signal_processed",
                    enqueued_position=pos_done,
                )
            ]
        )
        await session.commit()

    await consumer._redeliver_on_startup()

    assert _calls(service, "apply_pause_run") == []


@pytest.mark.asyncio
async def test_startup_redelivery_multiple_runs_in_order(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)

    pos_a = await _insert_signal_event(
        session_factory, "run-A", WorkflowSignal.PAUSE, {"reason": "a"}
    )
    pos_b = await _insert_signal_event(
        session_factory, "run-B", WorkflowSignal.PAUSE, {"reason": "b"}
    )

    await consumer._redeliver_on_startup()

    assert pos_a < pos_b
    assert [args[0] for args, _ in _calls(service, "apply_pause_run")] == ["run-A", "run-B"]


@pytest.mark.asyncio
async def test_consumer_start_triggers_redelivery(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = SignalConsumer(
        session_factory,
        ServiceFactory(service),
        poll_interval=100.0,
    )
    pos = await _insert_signal_event(
        session_factory, "run-cr", WorkflowSignal.PAUSE, {"reason": "srv"}
    )

    await consumer.start()
    await consumer.stop()

    processed = await _get_processed_positions(session_factory, "run-cr")
    assert pos in processed
    assert _calls(service, "apply_pause_run") == [
        (("run-cr",), {"reason": "srv", "error_detail": None})
    ]
