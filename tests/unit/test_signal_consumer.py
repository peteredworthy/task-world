"""Unit tests for SignalConsumer using concrete recording fakes."""

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
    RunWorkflow,
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
    def __init__(self, *, fail_methods: set[str] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.fail_methods = fail_methods or set()
        self.run = ServiceRun()

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
        if name in self.fail_methods:
            raise RuntimeError(f"{name} failed")

    async def apply_start_run(self, run_id: str) -> ServiceRun:
        self._record("apply_start_run", run_id)
        return self.run

    async def apply_resume_run(
        self,
        run_id: str,
        *,
        agent_runner_type: Any = None,
        agent_runner_config: dict[str, Any] | None = None,
        resume_strategy: str | None = None,
    ) -> ServiceRun:
        self._record(
            "apply_resume_run",
            run_id,
            agent_runner_type=agent_runner_type,
            agent_runner_config=agent_runner_config,
            resume_strategy=resume_strategy,
        )
        return self.run

    async def apply_pause_run(
        self,
        run_id: str,
        *,
        reason: str,
        error_detail: str | None = None,
    ) -> ServiceRun:
        self._record("apply_pause_run", run_id, reason=reason, error_detail=error_detail)
        return self.run

    async def apply_cancel_run(self, run_id: str, *, reason: str | None = None) -> ServiceRun:
        self._record("apply_cancel_run", run_id, reason=reason)
        return self.run

    async def apply_submission(self, run_id: str, task_id: str) -> ServiceRun:
        self._record("apply_submission", run_id, task_id)
        return self.run

    async def apply_verification(self, run_id: str, task_id: str) -> ServiceRun:
        self._record("apply_verification", run_id, task_id)
        return self.run


class ServiceFactory:
    def __init__(self, service: RecordingWorkflowService) -> None:
        self.service = service
        self.calls = 0

    async def __call__(self, session: Any) -> RecordingWorkflowService:
        self.calls += 1
        return self.service


class RecordingWorkflow(RunWorkflow):
    def __init__(self, run_id: str) -> None:
        super().__init__(run_id=run_id)
        self.completed_payloads: list[dict[str, Any] | None] = []
        self.verified_payloads: list[dict[str, Any] | None] = []

    async def handle_activity_completed(
        self,
        session: Any,
        service: Any,
        payload: dict[str, Any] | None,
    ) -> None:
        self.completed_payloads.append(payload)

    async def handle_activity_verified(
        self,
        session: Any,
        service: Any,
        payload: dict[str, Any] | None,
    ) -> None:
        self.verified_payloads.append(payload)


def _calls(service: RecordingWorkflowService, name: str) -> list[tuple[tuple[Any, ...], dict]]:
    return [(args, kwargs) for call_name, args, kwargs in service.calls if call_name == name]


def _consumer(
    session_factory: async_sessionmaker,
    service: RecordingWorkflowService | None = None,
) -> SignalConsumer:
    return SignalConsumer(session_factory, ServiceFactory(service or RecordingWorkflowService()))


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
async def test_fifo_ordering_per_run_id(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    id_pause = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.PAUSE, payload={"reason": "manual"}
    )
    id_cancel = await _insert_signal(session_factory, "run-1", WorkflowSignal.CANCEL)

    await consumer._process_run("run-1")

    assert [name for name, _, _ in service.calls] == ["apply_pause_run", "apply_cancel_run"]
    assert (await _get_signal(session_factory, id_pause)).handled_at is not None
    assert (await _get_signal(session_factory, id_cancel)).handled_at is not None


@pytest.mark.asyncio
async def test_delivered_at_set_before_handler(session_factory) -> None:
    delivered_at_during_handler: datetime | None = None

    class InspectingService(RecordingWorkflowService):
        async def apply_pause_run(
            self,
            run_id: str,
            *,
            reason: str,
            error_detail: str | None = None,
        ) -> ServiceRun:
            nonlocal delivered_at_during_handler
            async with session_factory() as session:
                result = await session.execute(
                    select(PendingSignalModel).where(PendingSignalModel.run_id == run_id)
                )
                delivered_at_during_handler = result.scalar_one().delivered_at
            return await super().apply_pause_run(run_id, reason=reason, error_detail=error_detail)

    consumer = _consumer(session_factory, InspectingService())
    sig_id = await _insert_signal(session_factory, "run-1", WorkflowSignal.PAUSE)

    await consumer._dispatch_signal_by_id(sig_id)

    sig = await _get_signal(session_factory, sig_id)
    assert delivered_at_during_handler is not None
    assert sig.handled_at is not None
    assert sig.handled_at >= sig.delivered_at


@pytest.mark.asyncio
async def test_error_leaves_handled_at_null(session_factory) -> None:
    service = RecordingWorkflowService(fail_methods={"apply_pause_run"})
    consumer = _consumer(session_factory, service)
    sig_id = await _insert_signal(session_factory, "run-1", WorkflowSignal.PAUSE)

    await consumer._dispatch_signal_by_id(sig_id)

    sig = await _get_signal(session_factory, sig_id)
    assert sig.delivered_at is not None
    assert sig.handled_at is None


@pytest.mark.asyncio
async def test_run_start_and_resume_register_workflows(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    start_id = await _insert_signal(session_factory, "run-start", WorkflowSignal.RUN_START)
    resume_id = await _insert_signal(session_factory, "run-resume", WorkflowSignal.RESUME)

    try:
        await consumer._dispatch_signal_by_id(start_id)
        await consumer._dispatch_signal_by_id(resume_id)

        assert _calls(service, "apply_start_run") == [(("run-start",), {})]
        assert _calls(service, "apply_resume_run") == [
            (
                ("run-resume",),
                {
                    "agent_runner_type": None,
                    "agent_runner_config": None,
                    "resume_strategy": None,
                },
            )
        ]
        assert "run-start" in consumer._active_workflows
        assert "run-resume" in consumer._active_workflows
        assert has_active_workflow("run-start")
        assert has_active_workflow("run-resume")
    finally:
        unregister_active_run("run-start")
        unregister_active_run("run-resume")


@pytest.mark.asyncio
async def test_pause_and_cancel_unregister_active_workflow(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    consumer._active_workflows["run-1"] = RunWorkflow(run_id="run-1")
    register_active_run("run-1")
    pause_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.PAUSE, {"reason": "user_pause"}
    )

    await consumer._dispatch_signal_by_id(pause_id)

    assert "run-1" not in consumer._active_workflows
    assert not has_active_workflow("run-1")
    assert _calls(service, "apply_pause_run") == [
        (("run-1",), {"reason": "user_pause", "error_detail": None})
    ]

    consumer._active_workflows["run-2"] = RunWorkflow(run_id="run-2")
    register_active_run("run-2")
    cancel_id = await _insert_signal(
        session_factory, "run-2", WorkflowSignal.CANCEL, {"reason": "user_cancel"}
    )

    await consumer._dispatch_signal_by_id(cancel_id)

    assert "run-2" not in consumer._active_workflows
    assert not has_active_workflow("run-2")
    assert _calls(service, "apply_cancel_run") == [(("run-2",), {"reason": "user_cancel"})]


@pytest.mark.asyncio
async def test_activity_signals_use_service_without_active_workflow(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    completed_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_COMPLETED, {"task_id": "task-42"}
    )
    verified_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_VERIFIED, {"task_id": "task-99"}
    )

    await consumer._dispatch_signal_by_id(completed_id)
    await consumer._dispatch_signal_by_id(verified_id)

    assert _calls(service, "apply_submission") == [(("run-1", "task-42"), {})]
    assert _calls(service, "apply_verification") == [(("run-1", "task-99"), {})]


@pytest.mark.asyncio
async def test_activity_signals_delegate_to_active_workflow(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    workflow = RecordingWorkflow(run_id="run-1")
    consumer._active_workflows["run-1"] = workflow
    completed_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_COMPLETED, {"task_id": "task-7"}
    )
    verified_id = await _insert_signal(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_VERIFIED, {"task_id": "task-8"}
    )

    await consumer._dispatch_signal_by_id(completed_id)
    await consumer._dispatch_signal_by_id(verified_id)

    assert workflow.completed_payloads == [{"task_id": "task-7"}]
    assert workflow.verified_payloads == [{"task_id": "task-8"}]
    assert _calls(service, "apply_submission") == []
    assert _calls(service, "apply_verification") == []


@pytest.mark.asyncio
async def test_find_pending_run_ids_excludes_delivered(session_factory) -> None:
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

    run_ids = await _consumer(session_factory)._find_pending_run_ids()

    assert "run-new" in run_ids
    assert "run-delivered" not in run_ids
    assert "run-handled" not in run_ids


@pytest.mark.asyncio
async def test_pause_default_reason(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    sig_id = await _insert_signal(session_factory, "run-1", WorkflowSignal.PAUSE)

    await consumer._dispatch_signal_by_id(sig_id)

    assert _calls(service, "apply_pause_run") == [
        (("run-1",), {"reason": "signal_pause", "error_detail": None})
    ]
