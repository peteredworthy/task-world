"""Tests for the workflow engine."""

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.config import ChecklistStatus, Priority, RunStatus, TaskStatus
from orchestrator.state.models import (
    ChecklistItem,
    Run,
    StepState,
    TaskState,
)
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow import WorkflowEngine
from orchestrator.workflow import GateBlockedError, InvalidTransitionError
from orchestrator.workflow import (
    GradesEvaluated,
    RunStatusChanged,
    StepCompleted,
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
        repo_name="proj-1",
        source_branch="main",
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

    # Leave checklist open - should raise GateBlockedError
    with pytest.raises(GateBlockedError) as exc_info:
        engine.submit_for_verification("run-1", "task-1")
    assert exc_info.value.gate_name == "checklist"
    assert len(exc_info.value.blocking_items) > 0


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


def test_pause_already_paused_is_idempotent() -> None:
    """Pausing an already-paused run should be a no-op, not raise an error."""
    run = _make_run(status=RunStatus.PAUSED)
    engine, _, _, emitter = _engine(run)

    result = engine.pause_run("run-1")
    assert result.status == RunStatus.PAUSED
    # No event should be emitted — nothing changed
    assert len(emitter.events) == 0


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
        "RunStatusChanged",  # start_run (DRAFT -> ACTIVE)
        "TaskStatusChanged",  # start_task
        "ChecklistGateEvaluated",  # submit_for_verification (gate)
        "TaskStatusChanged",  # submit_for_verification (status)
        "GradesEvaluated",  # complete_verification (grades)
        "TaskStatusChanged",  # complete_verification (task status)
        "StepCompleted",  # step completion cascade
        "RunStatusChanged",  # run completion cascade (ACTIVE -> COMPLETED)
    ]


def test_complete_verification_advances_step() -> None:
    """When all tasks in step 1 complete, step index advances to step 2."""
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        started_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        checklist=[
                            ChecklistItem(req_id="R1", desc="Req 1", priority=Priority.CRITICAL),
                        ],
                    ),
                ],
            ),
            StepState(
                id="step-2",
                config_id="S-02",
                tasks=[
                    TaskState(
                        id="task-2",
                        config_id="T-02",
                        checklist=[
                            ChecklistItem(req_id="R2", desc="Req 2", priority=Priority.CRITICAL),
                        ],
                    ),
                ],
            ),
        ],
    )
    engine, _, _, emitter = _engine(run)

    # Complete task-1 in step-1
    engine.start_task("run-1", "task-1")
    task1 = run.steps[0].tasks[0]
    for item in task1.checklist:
        item.status = ChecklistStatus.DONE
        item.grade = "A"
    engine.submit_for_verification("run-1", "task-1")
    engine.complete_verification("run-1", "task-1")

    # Step 1 should now be completed, step index should be 1
    assert run.steps[0].completed is True
    assert run.current_step_index == 1
    # Run should still be ACTIVE (step 2 not done)
    assert run.status == RunStatus.ACTIVE

    # StepCompleted event should have been emitted
    step_events = [e for e in emitter.events if isinstance(e, StepCompleted)]
    assert len(step_events) == 1
    assert step_events[0].step_index == 0


def test_run_auto_completes_when_all_steps_done() -> None:
    """Run transitions to COMPLETED when all tasks in all steps are done."""
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        started_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        checklist=[
                            ChecklistItem(req_id="R1", desc="Req 1", priority=Priority.CRITICAL),
                        ],
                    ),
                ],
            ),
            StepState(
                id="step-2",
                config_id="S-02",
                tasks=[
                    TaskState(
                        id="task-2",
                        config_id="T-02",
                        checklist=[
                            ChecklistItem(req_id="R2", desc="Req 2", priority=Priority.CRITICAL),
                        ],
                    ),
                ],
            ),
        ],
    )
    engine, _, clock, emitter = _engine(run)

    # Complete task-1 in step-1
    engine.start_task("run-1", "task-1")
    task1 = run.steps[0].tasks[0]
    for item in task1.checklist:
        item.status = ChecklistStatus.DONE
        item.grade = "A"
    engine.submit_for_verification("run-1", "task-1")
    clock.advance(timedelta(minutes=5))
    engine.complete_verification("run-1", "task-1")

    assert run.status == RunStatus.ACTIVE  # Not done yet

    # Complete task-2 in step-2
    engine.start_task("run-1", "task-2")
    task2 = run.steps[1].tasks[0]
    for item in task2.checklist:
        item.status = ChecklistStatus.DONE
        item.grade = "A"
    engine.submit_for_verification("run-1", "task-2")
    clock.advance(timedelta(minutes=5))
    engine.complete_verification("run-1", "task-2")

    # Now run should be COMPLETED
    assert run.steps[0].completed is True
    assert run.steps[1].completed is True
    assert run.status == RunStatus.COMPLETED
    assert run.completed_at is not None

    # Final event should be RunStatusChanged to COMPLETED
    run_events = [e for e in emitter.events if isinstance(e, RunStatusChanged)]
    assert run_events[-1].new_status == RunStatus.COMPLETED


def test_grades_evaluated_event_includes_grade_details() -> None:
    """GradesEvaluated event should include full grade details for each checklist item."""
    run = _make_run()
    engine, _, _, emitter = _engine(run)
    engine.start_run("run-1")
    engine.start_task("run-1", "task-1")

    task = run.steps[0].tasks[0]
    for item in task.checklist:
        item.status = ChecklistStatus.DONE
        item.grade = "B"
        item.grade_reason = "Decent work"

    engine.submit_for_verification("run-1", "task-1")
    engine.complete_verification("run-1", "task-1")

    grade_events = [e for e in emitter.events if isinstance(e, GradesEvaluated)]
    assert len(grade_events) == 1
    event = grade_events[0]
    assert len(event.grade_details) == 1
    assert event.grade_details[0].req_id == "R1"
    assert event.grade_details[0].grade == "B"
    assert event.grade_details[0].grade_reason == "Decent work"


def test_run_auto_fails_when_task_fails() -> None:
    """Run transitions to FAILED when a task fails and all steps are done."""
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        started_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        max_attempts=1,
                        checklist=[
                            ChecklistItem(req_id="R1", desc="Req 1", priority=Priority.CRITICAL),
                        ],
                    ),
                ],
            ),
        ],
    )
    engine, _, _, _ = _engine(run)

    engine.start_task("run-1", "task-1")
    task1 = run.steps[0].tasks[0]
    for item in task1.checklist:
        item.status = ChecklistStatus.DONE
        item.grade = "F"  # Failing grade, max_attempts=1 -> FAILED
    engine.submit_for_verification("run-1", "task-1")
    engine.complete_verification("run-1", "task-1")

    assert task1.status == TaskStatus.FAILED
    assert run.steps[0].completed is True  # Step is done (all tasks terminal)
    assert run.status == RunStatus.FAILED
    assert run.completed_at is not None


# --- B1: cancel_run tests ---


def test_cancel_run_from_active() -> None:
    """ACTIVE -> FAILED via cancel_run succeeds."""
    run = _make_run(status=RunStatus.ACTIVE)
    engine, _, clock, emitter = _engine(run)

    result = engine.cancel_run("run-1")
    assert result.status == RunStatus.FAILED
    assert result.completed_at == clock.now()

    assert len(emitter.events) == 1
    event = emitter.events[0]
    assert isinstance(event, RunStatusChanged)
    assert event.old_status == RunStatus.ACTIVE
    assert event.new_status == RunStatus.FAILED


def test_cancel_run_from_paused() -> None:
    """PAUSED -> FAILED via cancel_run succeeds."""
    run = _make_run(status=RunStatus.PAUSED)
    engine, _, clock, emitter = _engine(run)

    result = engine.cancel_run("run-1")
    assert result.status == RunStatus.FAILED
    assert result.completed_at == clock.now()

    assert len(emitter.events) == 1
    event = emitter.events[0]
    assert isinstance(event, RunStatusChanged)
    assert event.old_status == RunStatus.PAUSED
    assert event.new_status == RunStatus.FAILED


def test_cancel_run_from_completed_raises() -> None:
    """cancel_run from COMPLETED raises InvalidTransitionError."""
    run = _make_run(status=RunStatus.COMPLETED)
    engine, _, _, _ = _engine(run)

    with pytest.raises(InvalidTransitionError):
        engine.cancel_run("run-1")


def test_cancel_run_from_draft_raises() -> None:
    """cancel_run from DRAFT raises InvalidTransitionError."""
    run = _make_run(status=RunStatus.DRAFT)
    engine, _, _, _ = _engine(run)

    with pytest.raises(InvalidTransitionError):
        engine.cancel_run("run-1")


def test_start_task_populates_agent_snapshot() -> None:
    """start_task populates agent_type, agent_model, agent_settings on new attempt."""
    from orchestrator.config import AgentRunnerType

    run = _make_run(status=RunStatus.ACTIVE)
    run.agent_type = AgentRunnerType.CLI_SUBPROCESS
    run.agent_config = {
        "model": "claude-sonnet-4-5-20250514",
        "temperature": 0.7,
        "max_tokens": 4096,
        "api_key": "sk-secret123",
        "callback_channel": "rest",
    }

    engine, manager, _, _ = _engine(run)

    # Start the task (creates first attempt)
    engine.start_task("run-1", "task-1")

    # Verify attempt was created with agent snapshot
    task = manager.get_task("run-1", "task-1")
    assert len(task.attempts) == 1

    attempt = task.attempts[0]
    assert attempt.agent_type == AgentRunnerType.CLI_SUBPROCESS
    assert attempt.agent_model == "claude-sonnet-4-5-20250514"
    assert attempt.agent_settings["model"] == "claude-sonnet-4-5-20250514"
    assert attempt.agent_settings["temperature"] == 0.7
    assert attempt.agent_settings["max_tokens"] == 4096
    assert attempt.agent_settings["callback_channel"] == "rest"
    # API key should be excluded
    assert "api_key" not in attempt.agent_settings


def test_complete_verification_revision_populates_agent_snapshot() -> None:
    """complete_verification revision creates new attempt with agent snapshot."""
    from orchestrator.config import AgentRunnerType

    run = _make_run(status=RunStatus.ACTIVE)
    run.agent_type = AgentRunnerType.OPENHANDS_LOCAL
    run.agent_config = {
        "model": "gpt-4o",
        "temperature": 0.5,
        "password": "secret-password",
    }

    engine, manager, _, _ = _engine(run)

    # Start task and move to VERIFYING
    engine.start_task("run-1", "task-1")
    task = manager.get_task("run-1", "task-1")

    # Mark checklist as done so gate passes
    task.checklist[0].status = ChecklistStatus.DONE

    engine.submit_for_verification("run-1", "task-1")

    # Set grade to trigger revision
    task.checklist[0].grade = "fail"
    task.checklist[0].grade_reason = "Not good enough"

    # Complete verification (should create revision attempt)
    engine.complete_verification("run-1", "task-1")

    # Verify two attempts were created
    task = manager.get_task("run-1", "task-1")
    assert len(task.attempts) == 2

    # Check first attempt
    first_attempt = task.attempts[0]
    assert first_attempt.agent_type == AgentRunnerType.OPENHANDS_LOCAL
    assert first_attempt.agent_model == "gpt-4o"

    # Check second attempt (revision)
    second_attempt = task.attempts[1]
    assert second_attempt.agent_type == AgentRunnerType.OPENHANDS_LOCAL
    assert second_attempt.agent_model == "gpt-4o"
    assert second_attempt.agent_settings["model"] == "gpt-4o"
    assert second_attempt.agent_settings["temperature"] == 0.5
    # Password should be excluded
    assert "password" not in second_attempt.agent_settings
