"""Integration test: full workflow lifecycle from YAML to completion."""

from datetime import timedelta
from pathlib import Path

from orchestrator.config.enums import (
    ChecklistStatus,
    RunStatus,
    TaskStatus,
)
from orchestrator.config.routines.loader import load_routine_from_path
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow.engine import WorkflowEngine
from orchestrator.workflow.events import RunStatusChanged, TaskStatusChanged
from tests.conftest import CollectingEmitter, FakeClock

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


def test_full_lifecycle() -> None:
    """Load routine -> create run -> full builder/verifier lifecycle -> COMPLETED."""
    # 1. Load routine from YAML fixture
    routine = load_routine_from_path(FIXTURES / "valid_simple.yaml")

    # 2. Create run
    run = create_run_from_routine(
        routine=routine,
        repo_name="test-project",
        source_branch="main",
        config={"feature": "auth"},
    )

    # 3. Setup engine with injectable deps
    manager = SessionStateManager()
    manager.add_run(run)
    clock = FakeClock()
    emitter = CollectingEmitter()
    engine = WorkflowEngine(manager, clock=clock, emitter=emitter)

    # 4. Start run
    engine.start_run(run.id)
    assert run.status == RunStatus.ACTIVE

    # 5. Get the task
    task = run.steps[0].tasks[0]
    assert task.status == TaskStatus.PENDING

    # 6. Start task (PENDING -> BUILDING)
    result = engine.start_task(run.id, task.id)
    assert result.success is True
    assert task.status == TaskStatus.BUILDING

    # 7. Mark all checklist items done
    for item in task.checklist:
        item.status = ChecklistStatus.DONE

    # 8. Submit for verification (BUILDING -> VERIFYING)
    clock.advance(timedelta(minutes=10))
    result = engine.submit_for_verification(run.id, task.id)
    assert result.success is True
    assert result.gate_result is not None
    assert result.gate_result.passed is True
    assert task.status == TaskStatus.VERIFYING

    # 9. Set grades on checklist items
    for item in task.checklist:
        item.grade = "A"

    # 10. Complete verification (VERIFYING -> COMPLETED)
    clock.advance(timedelta(minutes=5))
    result = engine.complete_verification(run.id, task.id)
    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED

    # 11. Verify event sequence
    assert len(emitter.events) >= 4
    assert isinstance(emitter.events[0], RunStatusChanged)
    assert emitter.events[0].new_status == RunStatus.ACTIVE

    task_events = [e for e in emitter.events if isinstance(e, TaskStatusChanged)]
    assert len(task_events) == 3
    assert task_events[0].new_status == TaskStatus.BUILDING
    assert task_events[1].new_status == TaskStatus.VERIFYING
    assert task_events[2].new_status == TaskStatus.COMPLETED

    # 12. Verify attempt tracking
    assert len(task.attempts) == 1
    assert task.attempts[0].outcome == "passed"
    assert task.attempts[0].completed_at is not None


def test_revision_lifecycle() -> None:
    """Test that revision (fail -> retry) works end-to-end."""
    routine = load_routine_from_path(FIXTURES / "valid_simple.yaml")
    run = create_run_from_routine(routine=routine, repo_name="test-project", source_branch="main")

    manager = SessionStateManager()
    manager.add_run(run)
    clock = FakeClock()
    emitter = CollectingEmitter()
    engine = WorkflowEngine(manager, clock=clock, emitter=emitter)

    engine.start_run(run.id)
    task = run.steps[0].tasks[0]

    # Attempt 1: build, submit, fail verification
    engine.start_task(run.id, task.id)
    for item in task.checklist:
        item.status = ChecklistStatus.DONE
        item.grade = "D"
        item.grade_reason = "Needs work"

    engine.submit_for_verification(run.id, task.id)
    result = engine.complete_verification(run.id, task.id)
    assert result.new_status == TaskStatus.BUILDING  # Revision started
    assert task.current_attempt == 2

    # Attempt 2: fix grades and pass
    for item in task.checklist:
        item.grade = "A"
        item.grade_reason = None

    engine.submit_for_verification(run.id, task.id)
    clock.advance(timedelta(minutes=5))
    result = engine.complete_verification(run.id, task.id)
    assert result.new_status == TaskStatus.COMPLETED
    assert len(task.attempts) == 2
    assert task.attempts[0].outcome == "revision_needed"
    assert task.attempts[1].outcome == "passed"
