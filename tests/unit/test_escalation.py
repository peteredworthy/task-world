"""Tests for requirement escalation flow."""

import pytest

from orchestrator.config.enums import ChecklistStatus, Priority, RunStatus
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow.engine import WorkflowEngine
from orchestrator.workflow import InvalidTransitionError
from orchestrator.workflow.events import RunStatusChanged
from tests.conftest import CollectingEmitter, FakeClock


def _make_active_run(run_id: str = "run-1", task_id: str = "task-1") -> Run:
    run = Run(
        id=run_id,
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
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
    return run


def _engine(run: Run) -> tuple[WorkflowEngine, SessionStateManager, CollectingEmitter]:
    manager = SessionStateManager()
    manager.add_run(run)
    clock = FakeClock()
    emitter = CollectingEmitter()
    engine = WorkflowEngine(manager, clock=clock, emitter=emitter)
    return engine, manager, emitter


def test_escalate_requirement_pauses_run() -> None:
    """Escalating a requirement pauses the run with 'requirement_escalated'."""
    run = _make_active_run()
    engine, manager, emitter = _engine(run)

    result = engine.escalate_requirement("run-1", "task-1", "R1", "Cannot be done")

    assert result.status == RunStatus.PAUSED
    assert result.pause_reason == "requirement_escalated"


def test_escalate_requirement_sets_checklist_status() -> None:
    """Escalating a requirement marks it as escalated in the checklist."""
    run = _make_active_run()
    engine, manager, emitter = _engine(run)

    engine.escalate_requirement("run-1", "task-1", "R1", "Cannot be done")

    task = manager.get_task("run-1", "task-1")
    item = next(i for i in task.checklist if i.req_id == "R1")
    assert item.status == ChecklistStatus.ESCALATED


def test_escalate_requirement_emits_event() -> None:
    """Escalating a requirement emits a RunStatusChanged event."""
    run = _make_active_run()
    engine, manager, emitter = _engine(run)

    engine.escalate_requirement("run-1", "task-1", "R1", "Cannot be done")

    status_events = [e for e in emitter.events if isinstance(e, RunStatusChanged)]
    assert len(status_events) == 1
    event = status_events[0]
    assert event.old_status == RunStatus.ACTIVE
    assert event.new_status == RunStatus.PAUSED


def test_escalate_requirement_on_non_active_run_raises() -> None:
    """Escalating a requirement on a non-ACTIVE run raises InvalidTransitionError."""
    run = _make_active_run()
    run.status = RunStatus.PAUSED
    engine, manager, emitter = _engine(run)

    with pytest.raises(InvalidTransitionError):
        engine.escalate_requirement("run-1", "task-1", "R1", "Cannot be done")


def test_escalation_pause_reason_includes_req_id() -> None:
    """The last_error on an escalated run includes the requirement ID."""
    run = _make_active_run()
    engine, manager, emitter = _engine(run)

    result = engine.escalate_requirement("run-1", "task-1", "R1", "Too complex")

    assert "R1" in (result.last_error or "")
    assert "Too complex" in (result.last_error or "")
