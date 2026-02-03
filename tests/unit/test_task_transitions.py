"""Tests for task state machine transitions."""

from datetime import datetime, timezone

from orchestrator.config.enums import ChecklistStatus, Priority, TaskStatus
from orchestrator.state.models import Attempt, ChecklistItem, TaskState
from orchestrator.workflow.transitions import (
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
    result = transition_to_verifying(task)
    assert result.success is False
    assert result.new_status == TaskStatus.BUILDING
    assert result.gate_result is not None
    assert result.gate_result.passed is False


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
