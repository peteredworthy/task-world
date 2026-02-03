"""Tests for the workflow engine."""

from datetime import timedelta

import pytest

from orchestrator.config.enums import (
    ChecklistStatus,
    Priority,
    RunStatus,
    TaskStatus,
)
from orchestrator.state.models import (
    ChecklistItem,
    Run,
    StepState,
    TaskState,
)
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow.engine import WorkflowEngine
from orchestrator.workflow.errors import InvalidTransitionError
from orchestrator.workflow.events import (
    RunStatusChanged,
    TaskStatusChanged,
)
from tests.conftest import CollectingEmitter, FakeClock


def _make_run(
    run_id: str = "run-1",
    task_id: str = "task-1",
    status: RunStatus = RunStatus.DRAFT,
) -> Run:
    return Run(
        id=run_id,
        project_id="proj-1",
        status=status,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id=task_id,
                        config_id="T-01",
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Requirement 1",
                                priority=Priority.CRITICAL,
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _engine(
    run: Run,
) -> tuple[WorkflowEngine, SessionStateManager, FakeClock, CollectingEmitter]:
    manager = SessionStateManager()
    manager.add_run(run)
    clock = FakeClock()
    emitter = CollectingEmitter()
    engine = WorkflowEngine(manager, clock=clock, emitter=emitter)
    return engine, manager, clock, emitter


def test_start_run() -> None:
    run = _make_run()
    engine, _manager, clock, emitter = _engine(run)

    result = engine.start_run("run-1")
    assert result.status == RunStatus.ACTIVE
    assert result.started_at == clock.now()

    assert len(emitter.events) == 1
    event = emitter.events[0]
    assert isinstance(event, RunStatusChanged)
    assert event.old_status == RunStatus.DRAFT
    assert event.new_status == RunStatus.ACTIVE


def test_start_run_invalid_status() -> None:
    run = _make_run(status=RunStatus.COMPLETED)
    engine, _, _, _ = _engine(run)

    with pytest.raises(InvalidTransitionError):
        engine.start_run("run-1")


def test_start_task() -> None:
    run = _make_run()
    engine, _, _, emitter = _engine(run)
    engine.start_run("run-1")

    result = engine.start_task("run-1", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING

    # RunStatusChanged + TaskStatusChanged
    assert len(emitter.events) == 2
    assert isinstance(emitter.events[1], TaskStatusChanged)


def test_submit_gate_passes() -> None:
    run = _make_run()
    engine, _, _, _emitter = _engine(run)
    engine.start_run("run-1")
    engine.start_task("run-1", "task-1")

    # Mark checklist done
    task = run.steps[0].tasks[0]
    for item in task.checklist:
        item.status = ChecklistStatus.DONE

    result = engine.submit_for_verification("run-1", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.VERIFYING
    assert result.gate_result is not None
    assert result.gate_result.passed is True


def test_submit_gate_blocks() -> None:
    run = _make_run()
    engine, _, _, _emitter = _engine(run)
    engine.start_run("run-1")
    engine.start_task("run-1", "task-1")

    # Leave checklist open
    result = engine.submit_for_verification("run-1", "task-1")
    assert result.success is False
    assert result.new_status == TaskStatus.BUILDING


def test_complete_verification_passes() -> None:
    run = _make_run()
    engine, _, clock, _emitter = _engine(run)
    engine.start_run("run-1")
    engine.start_task("run-1", "task-1")

    # Mark checklist done with grade
    task = run.steps[0].tasks[0]
    for item in task.checklist:
        item.status = ChecklistStatus.DONE
        item.grade = "A"

    engine.submit_for_verification("run-1", "task-1")
    clock.advance(timedelta(minutes=5))

    result = engine.complete_verification("run-1", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED


def test_complete_verification_revision() -> None:
    run = _make_run()
    engine, _, _clock, _emitter = _engine(run)
    engine.start_run("run-1")
    engine.start_task("run-1", "task-1")

    # Mark checklist done but poor grade
    task = run.steps[0].tasks[0]
    for item in task.checklist:
        item.status = ChecklistStatus.DONE
        item.grade = "D"

    engine.submit_for_verification("run-1", "task-1")

    result = engine.complete_verification("run-1", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING  # Revision


def test_pause_run() -> None:
    run = _make_run(status=RunStatus.ACTIVE)
    engine, _, _, emitter = _engine(run)

    result = engine.pause_run("run-1")
    assert result.status == RunStatus.PAUSED

    assert len(emitter.events) == 1
    event = emitter.events[0]
    assert isinstance(event, RunStatusChanged)
    assert event.old_status == RunStatus.ACTIVE
    assert event.new_status == RunStatus.PAUSED


def test_pause_invalid_status() -> None:
    run = _make_run(status=RunStatus.DRAFT)
    engine, _, _, _ = _engine(run)

    with pytest.raises(InvalidTransitionError):
        engine.pause_run("run-1")


def test_resume_run() -> None:
    run = _make_run(status=RunStatus.PAUSED)
    engine, _, _, emitter = _engine(run)

    result = engine.resume_run("run-1")
    assert result.status == RunStatus.ACTIVE

    assert len(emitter.events) == 1
    event = emitter.events[0]
    assert isinstance(event, RunStatusChanged)
    assert event.old_status == RunStatus.PAUSED
    assert event.new_status == RunStatus.ACTIVE


def test_resume_invalid_status() -> None:
    run = _make_run(status=RunStatus.ACTIVE)
    engine, _, _, _ = _engine(run)

    with pytest.raises(InvalidTransitionError):
        engine.resume_run("run-1")


def test_event_sequence() -> None:
    run = _make_run()
    engine, _, _, emitter = _engine(run)

    engine.start_run("run-1")
    engine.start_task("run-1", "task-1")

    task = run.steps[0].tasks[0]
    for item in task.checklist:
        item.status = ChecklistStatus.DONE
        item.grade = "A"

    engine.submit_for_verification("run-1", "task-1")
    engine.complete_verification("run-1", "task-1")

    event_types = [type(e).__name__ for e in emitter.events]
    assert event_types == [
        "RunStatusChanged",
        "TaskStatusChanged",  # start_task
        "ChecklistGateEvaluated",  # submit_for_verification (gate)
        "TaskStatusChanged",  # submit_for_verification (status)
        "GradesEvaluated",  # complete_verification (grades)
        "TaskStatusChanged",  # complete_verification (status)
    ]
