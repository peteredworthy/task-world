"""Integration tests for EventStore and PersistentEventEmitter."""

from datetime import datetime, timezone

import pytest
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import EventStore
from orchestrator.db import RunModel
from orchestrator.workflow.event_logger import PersistentEventEmitter
from orchestrator.workflow.events import (
    ChecklistGateEvaluated,
    GradesEvaluated,
    RunStatusChanged,
    TaskStatusChanged,
    WorkflowEvent,
)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def session_with_run(session: AsyncSession) -> AsyncSession:
    """Session with a run already inserted for FK constraints."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    run = RunModel(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status="draft",
        runner_config={},
        config={},
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()
    return session


@pytest.fixture
def store(session_with_run: AsyncSession) -> EventStore:
    return EventStore(session_with_run)


NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


async def test_append_and_retrieve(store: EventStore) -> None:
    event = RunStatusChanged(
        timestamp=NOW,
        run_id="run-1",
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
    )
    await store.append(event)

    events = await store.get_events_for_run("run-1")
    assert len(events) == 1
    assert events[0]["type"] == "run_status_changed"
    assert events[0]["payload"]["run_id"] == "run-1"
    assert events[0]["payload"]["old_status"] == "draft"
    assert events[0]["payload"]["new_status"] == "active"


async def test_order_preserved(store: EventStore) -> None:
    events = [
        RunStatusChanged(
            timestamp=NOW,
            run_id="run-1",
            event_type="run_status_changed",
            old_status=RunStatus.DRAFT,
            new_status=RunStatus.ACTIVE,
        ),
        TaskStatusChanged(
            timestamp=NOW,
            run_id="run-1",
            event_type="task_status_changed",
            task_id="task-1",
            old_status=TaskStatus.PENDING,
            new_status=TaskStatus.BUILDING,
        ),
        TaskStatusChanged(
            timestamp=NOW,
            run_id="run-1",
            event_type="task_status_changed",
            task_id="task-1",
            old_status=TaskStatus.BUILDING,
            new_status=TaskStatus.VERIFYING,
        ),
    ]
    for event in events:
        await store.append(event)

    loaded = await store.get_events_for_run("run-1")
    assert len(loaded) == 3
    assert loaded[0]["type"] == "run_status_changed"
    assert loaded[1]["payload"]["new_status"] == "building"
    assert loaded[2]["payload"]["new_status"] == "verifying"


async def test_filter_by_run_id(session: AsyncSession) -> None:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    for run_id in ["run-a", "run-b"]:
        session.add(
            RunModel(
                id=run_id,
                repo_name="proj-1",
                source_branch="main",
                status="draft",
                runner_config={},
                config={},
                created_at=now,
                updated_at=now,
            )
        )
    await session.flush()

    store = EventStore(session)
    await store.append(
        RunStatusChanged(
            timestamp=now,
            run_id="run-a",
            event_type="run_status_changed",
            old_status=RunStatus.DRAFT,
            new_status=RunStatus.ACTIVE,
        )
    )
    await store.append(
        RunStatusChanged(
            timestamp=now,
            run_id="run-b",
            event_type="run_status_changed",
            old_status=RunStatus.DRAFT,
            new_status=RunStatus.ACTIVE,
        )
    )

    a_events = await store.get_events_for_run("run-a")
    b_events = await store.get_events_for_run("run-b")
    assert len(a_events) == 1
    assert len(b_events) == 1
    assert a_events[0]["payload"]["run_id"] == "run-a"
    assert b_events[0]["payload"]["run_id"] == "run-b"


async def test_all_event_types_serialize(store: EventStore) -> None:
    events: list[WorkflowEvent] = [
        RunStatusChanged(
            timestamp=NOW,
            run_id="run-1",
            event_type="run_status_changed",
            old_status=RunStatus.DRAFT,
            new_status=RunStatus.ACTIVE,
        ),
        TaskStatusChanged(
            timestamp=NOW,
            run_id="run-1",
            event_type="task_status_changed",
            task_id="t1",
            old_status=TaskStatus.PENDING,
            new_status=TaskStatus.BUILDING,
        ),
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

    for event in events:
        await store.append(event)

    loaded = await store.get_events_for_run("run-1")
    assert len(loaded) == 4
    assert loaded[0]["type"] == "run_status_changed"
    assert loaded[1]["type"] == "task_status_changed"
    assert loaded[2]["type"] == "checklist_gate_evaluated"
    assert loaded[2]["payload"]["passed"] is True
    assert loaded[3]["type"] == "grades_evaluated"
    assert loaded[3]["payload"]["failing_items"] == ["R1: Grade D below A"]


async def test_batch_persist(store: EventStore) -> None:
    events = [
        RunStatusChanged(
            timestamp=NOW,
            run_id="run-1",
            event_type="run_status_changed",
            old_status=RunStatus.DRAFT,
            new_status=RunStatus.ACTIVE,
        ),
        TaskStatusChanged(
            timestamp=NOW,
            run_id="run-1",
            event_type="task_status_changed",
            task_id="t1",
            old_status=TaskStatus.PENDING,
            new_status=TaskStatus.BUILDING,
        ),
    ]

    await store.append_batch(events)

    loaded = await store.get_events_for_run("run-1")
    assert len(loaded) == 2


async def test_persistent_emitter(store: EventStore) -> None:
    emitter = PersistentEventEmitter(store)

    event = RunStatusChanged(
        timestamp=NOW,
        run_id="run-1",
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
    )
    await emitter.emit(event)

    loaded = await store.get_events_for_run("run-1")
    assert len(loaded) == 1


async def test_persistent_emitter_batch(store: EventStore) -> None:
    emitter = PersistentEventEmitter(store)

    events: list[WorkflowEvent] = [
        RunStatusChanged(
            timestamp=NOW,
            run_id="run-1",
            event_type="run_status_changed",
            old_status=RunStatus.DRAFT,
            new_status=RunStatus.ACTIVE,
        ),
        TaskStatusChanged(
            timestamp=NOW,
            run_id="run-1",
            event_type="task_status_changed",
            task_id="t1",
            old_status=TaskStatus.PENDING,
            new_status=TaskStatus.BUILDING,
        ),
    ]
    await emitter.emit_batch(events)

    loaded = await store.get_events_for_run("run-1")
    assert len(loaded) == 2


async def test_persistent_emitter_listeners(store: EventStore) -> None:
    emitter = PersistentEventEmitter(store)
    received: list[WorkflowEvent] = []

    def on_event(event: WorkflowEvent) -> None:
        received.append(event)

    emitter.add_listener(on_event)

    event = RunStatusChanged(
        timestamp=NOW,
        run_id="run-1",
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
    )
    await emitter.emit(event)

    loaded = await store.get_events_for_run("run-1")
    assert len(loaded) == 1
    assert len(received) == 1
    assert received[0] is event


async def test_persistent_emitter_batch_notifies_listeners(store: EventStore) -> None:
    emitter = PersistentEventEmitter(store)
    received: list[WorkflowEvent] = []

    def on_event(event: WorkflowEvent) -> None:
        received.append(event)

    emitter.add_listener(on_event)

    events: list[WorkflowEvent] = [
        RunStatusChanged(
            timestamp=NOW,
            run_id="run-1",
            event_type="run_status_changed",
            old_status=RunStatus.DRAFT,
            new_status=RunStatus.ACTIVE,
        ),
        TaskStatusChanged(
            timestamp=NOW,
            run_id="run-1",
            event_type="task_status_changed",
            task_id="t1",
            old_status=TaskStatus.PENDING,
            new_status=TaskStatus.BUILDING,
        ),
    ]
    await emitter.emit_batch(events)

    loaded = await store.get_events_for_run("run-1")
    assert len(loaded) == 2
    assert len(received) == 2


async def test_empty_batch(store: EventStore) -> None:
    emitter = PersistentEventEmitter(store)
    await emitter.emit_batch([])
    loaded = await store.get_events_for_run("run-1")
    assert loaded == []


async def test_empty_run_returns_empty_list(store: EventStore) -> None:
    """get_events_for_run for a run with no events returns []."""
    events = await store.get_events_for_run("run-1")
    assert events == []


async def test_event_payload_roundtrips(store: EventStore) -> None:
    """Complex payload with nested dicts/enums survives serialization."""
    event = ChecklistGateEvaluated(
        timestamp=NOW,
        run_id="run-1",
        event_type="checklist_gate_evaluated",
        task_id="task-1",
        passed=False,
        blocking_items=["R1", "R2"],
    )
    await store.append(event)

    grades_event = GradesEvaluated(
        timestamp=NOW,
        run_id="run-1",
        event_type="grades_evaluated",
        task_id="task-1",
        passed=True,
        failing_items=[],
    )
    await store.append(grades_event)

    events = await store.get_events_for_run("run-1")
    assert len(events) == 2

    gate_payload = events[0]["payload"]
    assert gate_payload["passed"] is False
    assert gate_payload["blocking_items"] == ["R1", "R2"]
    assert gate_payload["task_id"] == "task-1"

    grades_payload = events[1]["payload"]
    assert grades_payload["passed"] is True
    assert grades_payload["failing_items"] == []
