"""Integration tests for SqliteEventStore and PersistentEventEmitter."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import RunStatus, TaskStatus
from orchestrator.db import (
    SqliteEventStore,
    StoredEvent,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.workflow import (
    ChecklistGateEvaluated,
    GradesEvaluated,
    PersistentEventEmitter,
    RunStatusChanged,
    TaskStatusChanged,
    WorkflowEvent,
)

NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def store(session: AsyncSession) -> SqliteEventStore:
    return SqliteEventStore(session)


def _payload(event: StoredEvent) -> dict[str, Any]:
    payload = json.loads(event.payload)
    assert isinstance(payload, dict)
    return payload


def _run_event(run_id: str = "run-1") -> RunStatusChanged:
    return RunStatusChanged(
        timestamp=NOW,
        run_id=run_id,
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
    )


def _task_event(
    run_id: str = "run-1",
    task_id: str = "task-1",
    old_status: TaskStatus = TaskStatus.PENDING,
    new_status: TaskStatus = TaskStatus.BUILDING,
) -> TaskStatusChanged:
    return TaskStatusChanged(
        timestamp=NOW,
        run_id=run_id,
        event_type="task_status_changed",
        task_id=task_id,
        old_status=old_status,
        new_status=new_status,
    )


async def test_append_and_retrieve(store: SqliteEventStore) -> None:
    await store.append(_run_event())

    events = await store.get_stream("run-1")
    assert len(events) == 1
    assert events[0].event_type == "run_status_changed"
    payload = _payload(events[0])
    assert payload["run_id"] == "run-1"
    assert payload["old_status"] == "draft"
    assert payload["new_status"] == "active"


async def test_order_preserved(store: SqliteEventStore) -> None:
    await store.append(
        [
            _run_event(),
            _task_event(),
            _task_event(old_status=TaskStatus.BUILDING, new_status=TaskStatus.VERIFYING),
        ]
    )

    loaded = await store.get_stream("run-1")
    assert len(loaded) == 3
    assert loaded[0].event_type == "run_status_changed"
    assert _payload(loaded[1])["new_status"] == "building"
    assert _payload(loaded[2])["new_status"] == "verifying"


async def test_filter_by_run_id(store: SqliteEventStore) -> None:
    await store.append([_run_event("run-a"), _run_event("run-b")])

    a_events = await store.get_stream("run-a")
    b_events = await store.get_stream("run-b")
    assert len(a_events) == 1
    assert len(b_events) == 1
    assert _payload(a_events[0])["run_id"] == "run-a"
    assert _payload(b_events[0])["run_id"] == "run-b"


async def test_all_event_types_serialize(store: SqliteEventStore) -> None:
    events: list[WorkflowEvent] = [
        _run_event(),
        _task_event("run-1", "t1"),
        ChecklistGateEvaluated(
            timestamp=NOW,
            run_id="run-1",
            event_type="checklist_gate_evaluated",
            task_id="t1",
            passed=True,
            blocking_items=[],
        ),
        GradesEvaluated(
            timestamp=NOW,
            run_id="run-1",
            event_type="grades_evaluated",
            task_id="t1",
            passed=False,
            failing_items=["R1: Grade D below A"],
        ),
    ]

    await store.append(events)

    loaded = await store.get_stream("run-1")
    assert len(loaded) == 4
    assert loaded[0].event_type == "run_status_changed"
    assert loaded[1].event_type == "task_status_changed"
    assert loaded[2].event_type == "checklist_gate_evaluated"
    assert _payload(loaded[2])["passed"] is True
    assert loaded[3].event_type == "grades_evaluated"
    assert _payload(loaded[3])["failing_items"] == ["R1: Grade D below A"]


async def test_batch_persist(store: SqliteEventStore) -> None:
    await store.append([_run_event(), _task_event("run-1", "t1")])

    loaded = await store.get_stream("run-1")
    assert len(loaded) == 2


async def test_persistent_emitter(store: SqliteEventStore) -> None:
    emitter = PersistentEventEmitter(store)

    await emitter.emit(_run_event())

    loaded = await store.get_stream("run-1")
    assert len(loaded) == 1


async def test_persistent_emitter_batch(store: SqliteEventStore) -> None:
    emitter = PersistentEventEmitter(store)

    await emitter.emit_batch([_run_event(), _task_event("run-1", "t1")])

    loaded = await store.get_stream("run-1")
    assert len(loaded) == 2


async def test_persistent_emitter_listeners(store: SqliteEventStore) -> None:
    emitter = PersistentEventEmitter(store)
    received: list[WorkflowEvent] = []
    emitter.add_listener(received.append)

    event = _run_event()
    await emitter.emit(event)

    loaded = await store.get_stream("run-1")
    assert len(loaded) == 1
    assert received == [event]


async def test_persistent_emitter_batch_notifies_listeners(store: SqliteEventStore) -> None:
    emitter = PersistentEventEmitter(store)
    received: list[WorkflowEvent] = []
    emitter.add_listener(received.append)

    events: list[WorkflowEvent] = [_run_event(), _task_event("run-1", "t1")]
    await emitter.emit_batch(events)

    loaded = await store.get_stream("run-1")
    assert len(loaded) == 2
    assert received == events


async def test_empty_batch(store: SqliteEventStore) -> None:
    emitter = PersistentEventEmitter(store)
    await emitter.emit_batch([])
    loaded = await store.get_stream("run-1")
    assert loaded == []


async def test_empty_run_returns_empty_list(store: SqliteEventStore) -> None:
    events = await store.get_stream("run-1")
    assert events == []


async def test_event_payload_roundtrips(store: SqliteEventStore) -> None:
    await store.append(
        [
            ChecklistGateEvaluated(
                timestamp=NOW,
                run_id="run-1",
                event_type="checklist_gate_evaluated",
                task_id="task-1",
                passed=False,
                blocking_items=["R1", "R2"],
            ),
            GradesEvaluated(
                timestamp=NOW,
                run_id="run-1",
                event_type="grades_evaluated",
                task_id="task-1",
                passed=True,
                failing_items=[],
            ),
        ]
    )

    events = await store.get_stream("run-1")
    assert len(events) == 2

    gate_payload = _payload(events[0])
    assert gate_payload["passed"] is False
    assert gate_payload["blocking_items"] == ["R1", "R2"]
    assert gate_payload["task_id"] == "task-1"

    grades_payload = _payload(events[1])
    assert grades_payload["passed"] is True
    assert grades_payload["failing_items"] == []
