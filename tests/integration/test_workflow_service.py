"""Integration tests for WorkflowService."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.db.event_store import EventStore
from orchestrator.routines.loader import load_routine_from_path
from orchestrator.state.errors import (
    ChecklistItemNotFoundError,
    RunNotFoundError,
    TaskNotFoundError,
)
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
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


@pytest.fixture
def service(session: AsyncSession) -> WorkflowService:
    return WorkflowService(session)


def _make_simple_run() -> Run:
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


async def test_full_lifecycle(service: WorkflowService) -> None:
    """Full lifecycle: create -> start run -> start task -> submit -> verify -> complete."""
    run = _make_simple_run()
    await service.create_run(run)

    # Start run
    started = await service.start_run("run-1")
    assert started.status == RunStatus.ACTIVE

    # Start task
    result = await service.start_task("run-1", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING

    # Update checklist to pass gate
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)

    # Submit for verification
    result = await service.submit_for_verification("run-1", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.VERIFYING

    # Set grade
    item = await service.set_grade("run-1", "task-1", "R1", "A")
    assert item.grade == "A"

    # Complete verification
    result = await service.complete_verification("run-1", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED


async def test_state_survives_restart(session: AsyncSession) -> None:
    """State persists across service instances (simulated restart)."""
    service1 = WorkflowService(session)

    run = _make_simple_run()
    await service1.create_run(run)
    await service1.start_run("run-1")

    # Simulate restart by creating a new service with same session
    service2 = WorkflowService(session)
    loaded = await service2.get_run("run-1")
    assert loaded.status == RunStatus.ACTIVE
    assert loaded.started_at is not None


async def test_events_logged(service: WorkflowService, session: AsyncSession) -> None:
    """Events are persisted to the event store."""
    run = _make_simple_run()
    await service.create_run(run)
    await service.start_run("run-1")
    await service.start_task("run-1", "task-1")

    store = EventStore(session)
    events = await store.get_events_for_run("run-1")
    assert len(events) >= 2
    event_types = [e["type"] for e in events]
    assert "run_status_changed" in event_types
    assert "task_status_changed" in event_types


async def test_error_propagation(service: WorkflowService) -> None:
    """Domain errors propagate correctly."""
    with pytest.raises(RunNotFoundError):
        await service.get_run("nonexistent")

    with pytest.raises(RunNotFoundError):
        await service.start_run("nonexistent")


async def test_task_not_found(service: WorkflowService) -> None:
    run = _make_simple_run()
    await service.create_run(run)

    with pytest.raises(TaskNotFoundError):
        await service.get_task("run-1", "nonexistent-task")


async def test_checklist_item_not_found(service: WorkflowService) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.start_run("run-1")
    await service.start_task("run-1", "task-1")

    with pytest.raises(ChecklistItemNotFoundError):
        await service.update_checklist_item(
            "run-1", "task-1", "nonexistent-req", ChecklistStatus.DONE
        )


async def test_set_grade_not_found(service: WorkflowService) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")

    with pytest.raises(ChecklistItemNotFoundError):
        await service.set_grade("run-1", "task-1", "nonexistent-req", "A")


async def test_multi_step_routine(service: WorkflowService) -> None:
    """Test with a multi-step routine created from YAML."""
    routine = load_routine_from_path(FIXTURES / "valid_complete.yaml")
    run = create_run_from_routine(
        routine=routine,
        repo_name="proj-1",
        source_branch="main",
        config={"feature_name": "auth"},
        routine_source=RoutineSource.LOCAL,
    )

    created = await service.create_run(run)
    assert len(created.steps) == 2
    assert len(created.steps[0].tasks) == 1
    assert len(created.steps[1].tasks) == 2

    await service.start_run(created.id)
    task_id = created.steps[0].tasks[0].id

    result = await service.start_task(created.id, task_id)
    assert result.success is True

    task = await service.get_task(created.id, task_id)
    assert task.status == TaskStatus.BUILDING


async def test_list_runs(service: WorkflowService) -> None:
    run = _make_simple_run()
    await service.create_run(run)

    runs = await service.list_runs()
    assert len(runs) == 1
    assert runs[0].id == "run-1"


async def test_list_runs_by_repo(service: WorkflowService) -> None:
    run = _make_simple_run()
    await service.create_run(run)

    runs = await service.list_runs_by_repo("proj-1")
    assert len(runs) == 1

    runs = await service.list_runs_by_repo("other-project")
    assert len(runs) == 0


async def test_delete_run(service: WorkflowService) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.delete_run("run-1")

    with pytest.raises(RunNotFoundError):
        await service.get_run("run-1")


async def test_revision_cycle(service: WorkflowService) -> None:
    """Test revision: fail grades -> go back to BUILDING -> fix -> pass."""
    run = _make_simple_run()
    await service.create_run(run)
    await service.start_run("run-1")
    await service.start_task("run-1", "task-1")

    # Pass checklist gate
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")

    # Set failing grade
    await service.set_grade("run-1", "task-1", "R1", "D", "Needs improvement")

    # Complete verification -> should trigger revision
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.BUILDING  # Revision

    task = await service.get_task("run-1", "task-1")
    assert task.current_attempt == 2

    # Fix grade and retry
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "A")
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.COMPLETED
