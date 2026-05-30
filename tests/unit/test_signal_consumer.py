"""Unit tests for SignalConsumer using concrete recording fakes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.db import Base
from orchestrator.db import EventV2Model
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.workflow import (
    RunWorkflow,
    SignalConsumer,
    WorkflowSignal,
)


@dataclass
class ServiceRun:
    agent_runner_type: Any = None
    agent_runner_config: dict[str, Any] = field(default_factory=dict)
    status: str = "active"


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
        self.run.status = "active"
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

    async def get_run(self, run_id: str) -> ServiceRun:
        self._record("get_run", run_id)
        return self.run


class ServiceFactory:
    def __init__(self, service: RecordingWorkflowService) -> None:
        self.service = service
        self.calls = 0

    async def __call__(self, session: Any) -> RecordingWorkflowService:
        self.calls += 1
        return self.service


class RecordingPreparer:
    def __init__(self, *, result: bool = True) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def __call__(self, run_id: str, payload: dict[str, Any] | None = None) -> bool:
        self.calls.append((run_id, payload))
        return self.result


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
    preparer: RecordingPreparer | None = None,
) -> SignalConsumer:
    return SignalConsumer(
        session_factory,
        ServiceFactory(service or RecordingWorkflowService()),
        workflow_preparer=preparer,
    )


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
    """Return the set of enqueued_positions that have been processed."""
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


async def _get_processed_payloads(session_factory: async_sessionmaker, run_id: str) -> list[dict]:
    """Return SignalProcessed payloads for a run in append order."""
    async with session_factory() as session:
        result = await session.execute(
            select(EventV2Model.payload)
            .where(
                EventV2Model.aggregate_id == run_id,
                EventV2Model.event_type == "signal_processed",
            )
            .order_by(EventV2Model.position)
        )
        rows = list(result.scalars())
    return [json.loads(row) for row in rows]


@pytest.mark.asyncio
async def test_fifo_ordering_per_run_id(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    pos_pause = await _insert_signal_event(
        session_factory, "run-1", WorkflowSignal.PAUSE, payload={"reason": "manual"}
    )
    pos_cancel = await _insert_signal_event(session_factory, "run-1", WorkflowSignal.CANCEL)

    await consumer._process_run("run-1")

    assert [name for name, _, _ in service.calls] == ["apply_pause_run", "apply_cancel_run"]
    processed = await _get_processed_positions(session_factory, "run-1")
    assert pos_pause in processed
    assert pos_cancel in processed


@pytest.mark.asyncio
async def test_signal_processed_committed_after_handler_success(session_factory) -> None:
    """SignalProcessed is appended only after the handler returns successfully."""
    signal_processed_during_handler: bool = False

    class InspectingService(RecordingWorkflowService):
        async def apply_pause_run(
            self,
            run_id: str,
            *,
            reason: str,
            error_detail: str | None = None,
        ) -> ServiceRun:
            nonlocal signal_processed_during_handler
            async with session_factory() as session:
                result = await session.execute(
                    select(EventV2Model).where(
                        EventV2Model.aggregate_id == run_id,
                        EventV2Model.event_type == "signal_processed",
                    )
                )
                signal_processed_during_handler = result.scalar_one_or_none() is not None
            return await super().apply_pause_run(run_id, reason=reason, error_detail=error_detail)

    consumer = _consumer(session_factory, InspectingService())
    pos = await _insert_signal_event(session_factory, "run-1", WorkflowSignal.PAUSE)

    await consumer._process_run("run-1")

    assert signal_processed_during_handler is False
    processed = await _get_processed_payloads(session_factory, "run-1")
    assert len(processed) == 1
    assert processed[0]["enqueued_position"] == pos


@pytest.mark.asyncio
async def test_error_leaves_signal_unprocessed_for_redelivery(session_factory) -> None:
    """On handler failure, no SignalProcessed event is appended."""
    service = RecordingWorkflowService(fail_methods={"apply_pause_run"})
    consumer = _consumer(session_factory, service)
    pos = await _insert_signal_event(session_factory, "run-1", WorkflowSignal.PAUSE)

    await consumer._process_run("run-1")

    processed = await _get_processed_positions(session_factory, "run-1")
    assert pos not in processed
    assert _calls(service, "apply_pause_run") == [
        (("run-1",), {"reason": "signal_pause", "error_detail": None})
    ]

    service.fail_methods.clear()
    await consumer._process_run("run-1")

    processed_after_redelivery = await _get_processed_positions(session_factory, "run-1")
    assert pos in processed_after_redelivery
    assert _calls(service, "apply_pause_run") == [
        (("run-1",), {"reason": "signal_pause", "error_detail": None}),
        (("run-1",), {"reason": "signal_pause", "error_detail": None}),
    ]


@pytest.mark.asyncio
async def test_processed_marker_is_exported_to_jsonl(tmp_path: Path) -> None:
    """SignalConsumer uses a wired event store for SignalProcessed outbox export."""
    db_path = tmp_path / "orchestrator.db"
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)
    try:
        service = RecordingWorkflowService()
        consumer = _consumer(factory, service)
        pos = await _insert_signal_event(factory, "run-1", WorkflowSignal.PAUSE)

        await consumer._process_run("run-1")

        journal_path = tmp_path / ".orchestrator" / "state" / "history.jsonl"
        records = [json.loads(line) for line in journal_path.read_text().splitlines()]
        assert records == [
            {
                "position": pos + 1,
                "aggregate_id": "run-1",
                "event_type": "signal_processed",
                "timestamp": records[0]["timestamp"],
                "payload": {
                    "run_id": "run-1",
                    "event_type": "signal_processed",
                    "enqueued_position": pos,
                    "timestamp": records[0]["payload"]["timestamp"],
                },
            }
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_start_and_resume_register_workflows(session_factory) -> None:
    service = RecordingWorkflowService()
    service.run.status = "paused"
    preparer = RecordingPreparer()
    consumer = _consumer(session_factory, service, preparer)
    await _insert_signal_event(session_factory, "run-start", WorkflowSignal.RUN_START)
    await _insert_signal_event(
        session_factory,
        "run-resume",
        WorkflowSignal.RESUME,
        {"resume_strategy": "reset_worktree"},
    )

    await consumer._process_run("run-start")
    await consumer._process_run("run-resume")

    assert preparer.calls == [
        ("run-start", None),
        ("run-resume", {"resume_strategy": "reset_worktree"}),
    ]
    assert _calls(service, "apply_start_run") == [(("run-start",), {})]
    assert _calls(service, "apply_resume_run") == [
        (
            ("run-resume",),
            {
                "agent_runner_type": None,
                "agent_runner_config": None,
                "resume_strategy": "reset_worktree",
            },
        )
    ]
    assert "run-start" in consumer._active_workflows
    assert "run-resume" in consumer._active_workflows


@pytest.mark.asyncio
async def test_run_start_does_not_activate_when_preparation_fails(session_factory) -> None:
    service = RecordingWorkflowService()
    preparer = RecordingPreparer(result=False)
    consumer = _consumer(session_factory, service, preparer)
    await _insert_signal_event(session_factory, "run-start", WorkflowSignal.RUN_START)

    await consumer._process_run("run-start")

    assert preparer.calls == [("run-start", None)]
    assert _calls(service, "apply_start_run") == []
    assert "run-start" not in consumer._active_workflows


@pytest.mark.asyncio
async def test_pause_and_cancel_remove_active_workflow(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    consumer._active_workflows["run-1"] = RunWorkflow(run_id="run-1")
    await _insert_signal_event(
        session_factory, "run-1", WorkflowSignal.PAUSE, {"reason": "user_pause"}
    )

    await consumer._process_run("run-1")

    assert "run-1" not in consumer._active_workflows
    assert _calls(service, "apply_pause_run") == [
        (("run-1",), {"reason": "user_pause", "error_detail": None})
    ]

    consumer._active_workflows["run-2"] = RunWorkflow(run_id="run-2")
    await _insert_signal_event(
        session_factory, "run-2", WorkflowSignal.CANCEL, {"reason": "user_cancel"}
    )

    await consumer._process_run("run-2")

    assert "run-2" not in consumer._active_workflows
    assert _calls(service, "apply_cancel_run") == [(("run-2",), {"reason": "user_cancel"})]


@pytest.mark.asyncio
async def test_activity_signals_use_service_without_active_workflow(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    await _insert_signal_event(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_COMPLETED, {"task_id": "task-42"}
    )
    await _insert_signal_event(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_VERIFIED, {"task_id": "task-99"}
    )

    await consumer._process_run("run-1")

    assert _calls(service, "apply_submission") == [(("run-1", "task-42"), {})]
    assert _calls(service, "apply_verification") == [(("run-1", "task-99"), {})]


@pytest.mark.asyncio
async def test_stale_activity_signal_for_paused_run_does_not_block_resume(
    session_factory,
) -> None:
    service = RecordingWorkflowService()
    service.run.status = "paused"
    preparer = RecordingPreparer()
    consumer = _consumer(session_factory, service, preparer)
    pos_activity = await _insert_signal_event(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_COMPLETED, {"task_id": "task-42"}
    )
    pos_resume = await _insert_signal_event(
        session_factory, "run-1", WorkflowSignal.RESUME, {"resume_strategy": "continue"}
    )

    await consumer._process_run("run-1")

    assert _calls(service, "apply_submission") == []
    assert _calls(service, "apply_resume_run") == [
        (
            ("run-1",),
            {
                "agent_runner_type": None,
                "agent_runner_config": None,
                "resume_strategy": "continue",
            },
        )
    ]
    processed = await _get_processed_positions(session_factory, "run-1")
    assert pos_activity in processed
    assert pos_resume in processed


@pytest.mark.asyncio
async def test_stale_resume_for_active_run_is_processed_without_reapplying_resume(
    session_factory,
) -> None:
    service = RecordingWorkflowService()
    service.run.status = "active"
    preparer = RecordingPreparer()
    consumer = _consumer(session_factory, service, preparer)
    pos_resume = await _insert_signal_event(
        session_factory, "run-1", WorkflowSignal.RESUME, {"resume_strategy": "continue"}
    )

    await consumer._process_run("run-1")

    assert _calls(service, "apply_resume_run") == []
    assert preparer.calls == []
    assert "run-1" in consumer._active_workflows
    processed = await _get_processed_positions(session_factory, "run-1")
    assert pos_resume in processed


@pytest.mark.asyncio
async def test_activity_signals_delegate_to_active_workflow(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    workflow = RecordingWorkflow(run_id="run-1")
    consumer._active_workflows["run-1"] = workflow
    await _insert_signal_event(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_COMPLETED, {"task_id": "task-7"}
    )
    await _insert_signal_event(
        session_factory, "run-1", WorkflowSignal.ACTIVITY_VERIFIED, {"task_id": "task-8"}
    )

    await consumer._process_run("run-1")

    assert workflow.completed_payloads == [{"task_id": "task-7"}]
    assert workflow.verified_payloads == [{"task_id": "task-8"}]
    assert _calls(service, "apply_submission") == []
    assert _calls(service, "apply_verification") == []


@pytest.mark.asyncio
async def test_find_pending_run_ids_excludes_processed(session_factory) -> None:
    """Only run_ids with unprocessed SignalEnqueued events are returned."""
    from orchestrator.db import SqliteEventStore
    from orchestrator.workflow import SignalProcessed

    # Insert a raw signal event for "run-new"
    await _insert_signal_event(session_factory, "run-new", WorkflowSignal.PAUSE, {"reason": "x"})

    # Insert and immediately process a signal for "run-processed"
    pos_done = await _insert_signal_event(
        session_factory, "run-processed", WorkflowSignal.PAUSE, {"reason": "y"}
    )
    async with session_factory() as session:
        store = SqliteEventStore(session)
        await store.append(
            [
                SignalProcessed(
                    run_id="run-processed",
                    event_type="signal_processed",
                    enqueued_position=pos_done,
                )
            ]
        )
        await session.commit()

    run_ids = await _consumer(session_factory)._find_pending_run_ids()

    assert "run-new" in run_ids
    assert "run-processed" not in run_ids


@pytest.mark.asyncio
async def test_pause_default_reason(session_factory) -> None:
    service = RecordingWorkflowService()
    consumer = _consumer(session_factory, service)
    await _insert_signal_event(session_factory, "run-1", WorkflowSignal.PAUSE)

    await consumer._process_run("run-1")

    assert _calls(service, "apply_pause_run") == [
        (("run-1",), {"reason": "signal_pause", "error_detail": None})
    ]
