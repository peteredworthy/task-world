"""Tests for task state machine transitions."""

from datetime import datetime, timezone

import pytest

from orchestrator.config.enums import ChecklistStatus, Priority, RunStatus, TaskStatus
from orchestrator.state.models import Attempt, ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.errors import GateBlockedError
from orchestrator.workflow.transitions import (
    check_run_completion,
    check_step_progression,
    is_step_complete,
    transition_after_verification,
    transition_to_building,
    transition_to_verifying,
)

NOW = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc)


def _task(
    status: TaskStatus = TaskStatus.PENDING,
    max_attempts: int = 3,
    checklist: list[ChecklistItem] | None = None,
) -> TaskState:
    return TaskState(
        id="task-1",
        config_id="T-01",
        status=status,
        max_attempts=max_attempts,
        checklist=checklist or [],
    )


def _done_checklist() -> list[ChecklistItem]:
    return [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.DONE,
            grade="A",
        ),
    ]


def _failing_checklist() -> list[ChecklistItem]:
    return [
        ChecklistItem(
            req_id="R1",
            desc="Req 1",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.DONE,
            grade="D",
            grade_reason="Needs improvement",
        ),
    ]


# --- transition_to_building ---


def test_pending_to_building() -> None:
    task = _task(status=TaskStatus.PENDING)
    result = transition_to_building(task, NOW)
    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING
    assert task.status == TaskStatus.BUILDING
    assert len(task.attempts) == 1
    assert task.attempts[0].attempt_num == 1
    assert task.attempts[0].started_at == NOW
    assert task.current_attempt == 1


def test_building_from_invalid_state() -> None:
    task = _task(status=TaskStatus.COMPLETED)
    result = transition_to_building(task, NOW)
    assert result.success is False
    assert result.error is not None


def test_building_from_verifying_for_revision() -> None:
    task = _task(status=TaskStatus.VERIFYING)
    task.attempts.append(Attempt(attempt_num=1, started_at=NOW))
    task.current_attempt = 1
    result = transition_to_building(task, LATER)
    assert result.success is True
    assert task.current_attempt == 2
    assert len(task.attempts) == 2


# --- transition_to_verifying ---


def test_building_to_verifying_gate_passes() -> None:
    task = _task(
        status=TaskStatus.BUILDING,
        checklist=_done_checklist(),
    )
    result = transition_to_verifying(task)
    assert result.success is True
    assert result.new_status == TaskStatus.VERIFYING
    assert result.gate_result is not None
    assert result.gate_result.passed is True


def test_building_to_verifying_gate_blocks() -> None:
    task = _task(
        status=TaskStatus.BUILDING,
        checklist=[
            ChecklistItem(
                req_id="R1",
                desc="Req 1",
                priority=Priority.CRITICAL,
                status=ChecklistStatus.OPEN,
            ),
        ],
    )
    # Should raise GateBlockedError when checklist gate fails
    with pytest.raises(GateBlockedError) as exc_info:
        transition_to_verifying(task)
    assert exc_info.value.gate_name == "checklist"
    assert len(exc_info.value.blocking_items) > 0
    # Task status should remain BUILDING
    assert task.status == TaskStatus.BUILDING


def test_verifying_from_invalid_state() -> None:
    task = _task(status=TaskStatus.PENDING)
    result = transition_to_verifying(task)
    assert result.success is False
    assert result.error is not None


# --- transition_after_verification ---


def test_verification_passes() -> None:
    task = _task(status=TaskStatus.VERIFYING, checklist=_done_checklist())
    task.attempts.append(Attempt(attempt_num=1, started_at=NOW))
    task.current_attempt = 1

    result = transition_after_verification(task, LATER)
    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED
    assert task.attempts[-1].completed_at == LATER
    assert task.attempts[-1].outcome == "passed"


def test_verification_fails_with_retries() -> None:
    task = _task(status=TaskStatus.VERIFYING, max_attempts=3, checklist=_failing_checklist())
    task.attempts.append(Attempt(attempt_num=1, started_at=NOW))
    task.current_attempt = 1

    result = transition_after_verification(task, LATER)
    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING  # Revision
    assert task.current_attempt == 2
    assert len(task.attempts) == 2  # Original + revision
    assert task.attempts[0].outcome == "revision_needed"


def test_verification_fails_max_attempts() -> None:
    task = _task(status=TaskStatus.VERIFYING, max_attempts=1, checklist=_failing_checklist())
    task.attempts.append(Attempt(attempt_num=1, started_at=NOW))
    task.current_attempt = 1

    result = transition_after_verification(task, LATER)
    assert result.success is True
    assert result.new_status == TaskStatus.FAILED
    assert task.status == TaskStatus.FAILED
    assert task.attempts[-1].outcome == "failed"
    assert result.error is not None
    assert "Max attempts" in result.error


def test_verification_from_invalid_state() -> None:
    task = _task(status=TaskStatus.BUILDING)
    result = transition_after_verification(task, NOW)
    assert result.success is False
    assert result.error is not None


def test_attempt_numbering_through_lifecycle() -> None:
    """Full lifecycle: build -> verify(fail) -> rebuild -> verify(pass)."""
    task = _task(
        status=TaskStatus.PENDING,
        max_attempts=3,
        checklist=_failing_checklist(),
    )

    # Start building (attempt 1)
    transition_to_building(task, NOW)
    assert task.current_attempt == 1

    # Mark checklist done for gate
    for item in task.checklist:
        item.status = ChecklistStatus.DONE

    # Submit for verification
    transition_to_verifying(task)
    assert task.status == TaskStatus.VERIFYING

    # Verification fails -> revision (attempt 2)
    transition_after_verification(task, LATER)
    assert task.status == TaskStatus.BUILDING
    assert task.current_attempt == 2

    # Fix the grade for pass
    for item in task.checklist:
        item.grade = "A"
        item.grade_reason = None

    # Submit again
    transition_to_verifying(task)

    # Now should pass
    result = transition_after_verification(task, LATER)
    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED
    assert len(task.attempts) == 2  # attempt 1 (failed) + attempt 2 (passed)


def test_grade_result_returned() -> None:
    task = _task(status=TaskStatus.VERIFYING, checklist=_done_checklist())
    task.attempts.append(Attempt(attempt_num=1, started_at=NOW))
    task.current_attempt = 1

    result = transition_after_verification(task, LATER)
    assert result.grade_result is not None
    assert result.grade_result.passed is True


# --- grade snapshots ---


def test_grade_snapshot_captured_on_pass() -> None:
    """Passing verification snapshots grades into the attempt."""
    task = _task(status=TaskStatus.VERIFYING, checklist=_done_checklist())
    task.attempts.append(Attempt(attempt_num=1, started_at=NOW))
    task.current_attempt = 1

    transition_after_verification(task, LATER)
    snapshot = task.attempts[0].grade_snapshot
    assert len(snapshot) == 1
    assert snapshot[0].req_id == "R1"
    assert snapshot[0].grade == "A"
    assert snapshot[0].grade_reason is None


def test_grade_snapshot_captured_on_revision() -> None:
    """Failed verification also snapshots grades before creating revision attempt."""
    task = _task(status=TaskStatus.VERIFYING, max_attempts=3, checklist=_failing_checklist())
    task.attempts.append(Attempt(attempt_num=1, started_at=NOW))
    task.current_attempt = 1

    transition_after_verification(task, LATER)
    # Attempt 1 (the failed one) should have the snapshot
    snapshot = task.attempts[0].grade_snapshot
    assert len(snapshot) == 1
    assert snapshot[0].req_id == "R1"
    assert snapshot[0].grade == "D"
    assert snapshot[0].grade_reason == "Needs improvement"
    # Attempt 2 (revision) should not yet have a snapshot
    assert task.attempts[1].grade_snapshot == []


def test_grade_snapshot_per_attempt_through_lifecycle() -> None:
    """Each attempt preserves its own independent grade snapshot."""
    task = _task(
        status=TaskStatus.PENDING,
        max_attempts=3,
        checklist=[
            ChecklistItem(
                req_id="R1",
                desc="Req 1",
                priority=Priority.CRITICAL,
                status=ChecklistStatus.DONE,
                grade="D",
                grade_reason="Bad",
            ),
        ],
    )

    # Attempt 1: build -> verify (fail)
    transition_to_building(task, NOW)
    transition_to_verifying(task)
    transition_after_verification(task, LATER)
    assert task.status == TaskStatus.BUILDING  # revision

    # Fix grade for attempt 2
    task.checklist[0].grade = "A"
    task.checklist[0].grade_reason = "Fixed"

    # Attempt 2: verify (pass)
    transition_to_verifying(task)
    transition_after_verification(task, LATER)
    assert task.status == TaskStatus.COMPLETED

    # Verify independent snapshots
    snap1 = task.attempts[0].grade_snapshot
    assert snap1[0].grade == "D"
    assert snap1[0].grade_reason == "Bad"

    snap2 = task.attempts[1].grade_snapshot
    assert snap2[0].grade == "A"
    assert snap2[0].grade_reason == "Fixed"


def test_grade_snapshot_on_max_attempts_failure() -> None:
    """Grade snapshot captured even when task reaches max attempts and fails."""
    task = _task(status=TaskStatus.VERIFYING, max_attempts=1, checklist=_failing_checklist())
    task.attempts.append(Attempt(attempt_num=1, started_at=NOW))
    task.current_attempt = 1

    transition_after_verification(task, LATER)
    assert task.status == TaskStatus.FAILED
    snapshot = task.attempts[0].grade_snapshot
    assert len(snapshot) == 1
    assert snapshot[0].grade == "D"


# --- is_step_complete ---


def test_step_complete_all_tasks_completed() -> None:
    step = StepState(
        id="step-1",
        config_id="S-01",
        tasks=[
            TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED),
            TaskState(id="t2", config_id="T-02", status=TaskStatus.COMPLETED),
        ],
    )
    assert is_step_complete(step) is True


def test_step_complete_mixed_terminal() -> None:
    step = StepState(
        id="step-1",
        config_id="S-01",
        tasks=[
            TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED),
            TaskState(id="t2", config_id="T-02", status=TaskStatus.FAILED),
        ],
    )
    assert is_step_complete(step) is True


def test_step_not_complete_task_building() -> None:
    step = StepState(
        id="step-1",
        config_id="S-01",
        tasks=[
            TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED),
            TaskState(id="t2", config_id="T-02", status=TaskStatus.BUILDING),
        ],
    )
    assert is_step_complete(step) is False


def test_step_not_complete_task_pending() -> None:
    step = StepState(
        id="step-1",
        config_id="S-01",
        tasks=[
            TaskState(id="t1", config_id="T-01", status=TaskStatus.PENDING),
        ],
    )
    assert is_step_complete(step) is False


def test_step_complete_empty_tasks() -> None:
    step = StepState(id="step-1", config_id="S-01", tasks=[])
    assert is_step_complete(step) is True


# --- check_step_progression ---


def test_step_progression_advances_index() -> None:
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        current_step_index=0,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED)],
            ),
            StepState(
                id="step-2",
                config_id="S-02",
                tasks=[TaskState(id="t2", config_id="T-02", status=TaskStatus.PENDING)],
            ),
        ],
    )
    changed = check_step_progression(run)
    assert changed is True
    assert run.steps[0].completed is True
    assert run.current_step_index == 1


def test_step_progression_no_change_when_not_done() -> None:
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        current_step_index=0,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[TaskState(id="t1", config_id="T-01", status=TaskStatus.BUILDING)],
            ),
        ],
    )
    changed = check_step_progression(run)
    assert changed is False
    assert run.steps[0].completed is False
    assert run.current_step_index == 0


def test_step_progression_advances_past_multiple_complete() -> None:
    """If steps 0 and 1 are both complete, index should advance to 2."""
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        current_step_index=0,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED)],
            ),
            StepState(
                id="step-2",
                config_id="S-02",
                tasks=[TaskState(id="t2", config_id="T-02", status=TaskStatus.COMPLETED)],
            ),
            StepState(
                id="step-3",
                config_id="S-03",
                tasks=[TaskState(id="t3", config_id="T-03", status=TaskStatus.PENDING)],
            ),
        ],
    )
    changed = check_step_progression(run)
    assert changed is True
    assert run.steps[0].completed is True
    assert run.steps[1].completed is True
    assert run.steps[2].completed is False
    assert run.current_step_index == 2


def test_step_progression_stays_on_last_step() -> None:
    """When the last step completes, index stays at len-1."""
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        current_step_index=0,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED)],
            ),
        ],
    )
    changed = check_step_progression(run)
    assert changed is True
    assert run.steps[0].completed is True
    assert run.current_step_index == 0  # Can't advance past the last step


def test_step_progression_stops_on_failed_task() -> None:
    """Fail-fast: don't advance past a step containing a failed task."""
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        current_step_index=0,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED),
                    TaskState(id="t2", config_id="T-02", status=TaskStatus.FAILED),
                ],
            ),
            StepState(
                id="step-2",
                config_id="S-02",
                tasks=[TaskState(id="t3", config_id="T-03", status=TaskStatus.PENDING)],
            ),
        ],
    )
    changed = check_step_progression(run)
    assert changed is True
    assert run.steps[0].completed is True
    assert run.current_step_index == 0  # Stays on step 0, does NOT advance


# --- check_run_completion ---


def test_run_fails_fast_on_step_with_failure() -> None:
    """Fail-fast: run transitions to FAILED when a completed step has a failed task,
    even if later steps are incomplete."""
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                completed=True,
                tasks=[
                    TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED),
                    TaskState(id="t2", config_id="T-02", status=TaskStatus.FAILED),
                ],
            ),
            StepState(
                id="step-2",
                config_id="S-02",
                completed=False,
                tasks=[TaskState(id="t3", config_id="T-03", status=TaskStatus.PENDING)],
            ),
        ],
    )
    result = check_run_completion(run, NOW)
    assert result == RunStatus.FAILED
    assert run.status == RunStatus.FAILED
    assert run.completed_at == NOW


# --- check_run_completion ---


def test_run_completes_when_all_steps_done() -> None:
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                completed=True,
                tasks=[TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED)],
            ),
        ],
    )
    result = check_run_completion(run, NOW)
    assert result == RunStatus.COMPLETED
    assert run.status == RunStatus.COMPLETED
    assert run.completed_at == NOW


def test_run_fails_when_any_task_failed() -> None:
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                completed=True,
                tasks=[
                    TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED),
                    TaskState(id="t2", config_id="T-02", status=TaskStatus.FAILED),
                ],
            ),
        ],
    )
    result = check_run_completion(run, NOW)
    assert result == RunStatus.FAILED
    assert run.status == RunStatus.FAILED
    assert run.completed_at == NOW


def test_run_no_completion_if_step_incomplete() -> None:
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                completed=True,
                tasks=[TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED)],
            ),
            StepState(
                id="step-2",
                config_id="S-02",
                completed=False,
                tasks=[TaskState(id="t2", config_id="T-02", status=TaskStatus.BUILDING)],
            ),
        ],
    )
    result = check_run_completion(run, NOW)
    assert result is None
    assert run.status == RunStatus.ACTIVE


def test_run_no_completion_if_not_active() -> None:
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.PAUSED,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                completed=True,
                tasks=[TaskState(id="t1", config_id="T-01", status=TaskStatus.COMPLETED)],
            ),
        ],
    )
    result = check_run_completion(run, NOW)
    assert result is None
    assert run.status == RunStatus.PAUSED
