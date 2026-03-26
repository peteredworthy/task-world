"""Integration tests for event replay recovery."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
    load_routine_from_path,
)
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import EventStore
from orchestrator.db import replay_events
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import (
    ChecklistItem,
    Run,
    StepState,
    TaskState,
)
from orchestrator.workflow.service import WorkflowService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _make_run() -> Run:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.DRAFT,
        routine_id="simple-routine",
        routine_source=RoutineSource.LOCAL,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.PENDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Complete the task",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


async def test_recovery_from_events(session: AsyncSession) -> None:
    """Create run, perform actions, clear in-memory state, replay events, verify state."""
    # Setup: Create and run through part of the workflow
    service = WorkflowService(session)
    run = _make_run()
    await service.create_run(run)
    await service.start_run("run-1")
    await service.start_task("run-1", "task-1")

    # Verify current state before "crash"
    current = await service.get_run("run-1")
    assert current.status == RunStatus.ACTIVE
    task = current.steps[0].tasks[0]
    assert task.status == TaskStatus.BUILDING

    # Simulate crash: get events from the store, then create a fresh run
    store = EventStore(session)
    events = await store.get_events_for_run("run-1")
    assert len(events) >= 2

    # Create a fresh run (initial state, as if just created from routine)
    fresh_run = _make_run()
    assert fresh_run.status == RunStatus.DRAFT
    assert fresh_run.steps[0].tasks[0].status == TaskStatus.PENDING

    # Recovery: replay events to reconstruct state
    recovered = replay_events(fresh_run, events)

    assert recovered.status == RunStatus.ACTIVE
    assert recovered.started_at is not None
    assert recovered.steps[0].tasks[0].status == TaskStatus.BUILDING
    assert recovered.steps[0].tasks[0].current_attempt == 1


async def test_recovery_full_lifecycle(session: AsyncSession) -> None:
    """Full lifecycle through to COMPLETED, then recover via events."""
    service = WorkflowService(session)
    run = _make_run()
    await service.create_run(run)
    await service.start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "A")
    await service.complete_verification("run-1", "task-1")

    # Verify final state — run auto-completes when all tasks are done
    final = await service.get_run("run-1")
    assert final.status == RunStatus.COMPLETED
    assert final.completed_at is not None
    assert final.steps[0].completed is True
    assert final.steps[0].tasks[0].status == TaskStatus.COMPLETED

    # Replay events on a fresh run
    store = EventStore(session)
    events = await store.get_events_for_run("run-1")
    fresh = _make_run()
    recovered = replay_events(fresh, events)

    assert recovered.status == RunStatus.COMPLETED
    assert recovered.started_at is not None
    assert recovered.steps[0].tasks[0].status == TaskStatus.COMPLETED
    assert recovered.steps[0].tasks[0].current_attempt == 1


async def test_recovery_revision_cycle(session: AsyncSession) -> None:
    """Revision cycle: fail -> retry -> pass, then recover via events."""
    service = WorkflowService(session)
    run = _make_run()
    await service.create_run(run)
    await service.start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "D", "Needs work")
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.BUILDING  # Revision

    # Fix and pass
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "A")
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.COMPLETED

    # Replay
    store = EventStore(session)
    events = await store.get_events_for_run("run-1")
    fresh = _make_run()
    recovered = replay_events(fresh, events)

    assert recovered.status == RunStatus.COMPLETED
    assert recovered.started_at is not None
    assert recovered.steps[0].tasks[0].status == TaskStatus.COMPLETED
    # Two building transitions: initial + revision
    assert recovered.steps[0].tasks[0].current_attempt == 2


async def test_recovery_preserves_grade_snapshots(session: AsyncSession) -> None:
    """Grade snapshots survive event replay recovery across revision cycles."""
    service = WorkflowService(session)
    run = _make_run()
    await service.create_run(run)
    await service.start_run("run-1")

    # Attempt 1: build, verify with bad grade -> revision
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "D", "Needs work")
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.BUILDING

    # Attempt 2: fix grade, pass
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "A", "Great")
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.COMPLETED

    # Verify live state has snapshots
    live = await service.get_run("run-1")
    live_task = live.steps[0].tasks[0]
    assert len(live_task.attempts) == 2
    assert live_task.attempts[0].grade_snapshot[0].grade == "D"
    assert live_task.attempts[0].grade_snapshot[0].grade_reason == "Needs work"
    assert live_task.attempts[1].grade_snapshot[0].grade == "A"
    assert live_task.attempts[1].grade_snapshot[0].grade_reason == "Great"

    # Replay events on fresh run
    store = EventStore(session)
    events = await store.get_events_for_run("run-1")
    fresh = _make_run()
    recovered = replay_events(fresh, events)

    recovered_task = recovered.steps[0].tasks[0]
    assert len(recovered_task.attempts) == 2
    assert recovered_task.attempts[0].grade_snapshot[0].grade == "D"
    assert recovered_task.attempts[0].grade_snapshot[0].grade_reason == "Needs work"
    assert recovered_task.attempts[1].grade_snapshot[0].grade == "A"
    assert recovered_task.attempts[1].grade_snapshot[0].grade_reason == "Great"


async def test_recovery_with_routine_fixture(session: AsyncSession) -> None:
    """Recovery works with runs created from actual YAML routines."""
    routine = load_routine_from_path(FIXTURES / "valid_simple.yaml")
    run = create_run_from_routine(
        routine=routine,
        repo_name="proj-1",
        source_branch="main",
        routine_source=RoutineSource.LOCAL,
    )

    service = WorkflowService(session)
    await service.create_run(run)
    await service.start_run(run.id)

    task_id = run.steps[0].tasks[0].id
    await service.start_task(run.id, task_id)

    store = EventStore(session)
    events = await store.get_events_for_run(run.id)

    # Create a fresh run from the same routine
    fresh = create_run_from_routine(
        routine=routine,
        repo_name="proj-1",
        source_branch="main",
        routine_source=RoutineSource.LOCAL,
    )
    # Transplant the same IDs so event replay can find the right entities
    fresh.id = run.id
    fresh.steps[0].id = run.steps[0].id
    fresh.steps[0].tasks[0].id = task_id

    recovered = replay_events(fresh, events)
    assert recovered.status == RunStatus.ACTIVE
    assert recovered.started_at is not None
    assert recovered.steps[0].tasks[0].status == TaskStatus.BUILDING
    assert recovered.steps[0].tasks[0].current_attempt == 1
