"""Task state machine transitions (pure functions)."""

from dataclasses import dataclass
from datetime import datetime

from orchestrator.config.enums import TaskStatus
from orchestrator.state.models import Attempt, TaskState
from orchestrator.workflow.gates import GateResult, evaluate_checklist_gate
from orchestrator.workflow.grades import GradeResult, evaluate_grades

VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.BUILDING},
    TaskStatus.BUILDING: {TaskStatus.VERIFYING, TaskStatus.FAILED},
    TaskStatus.VERIFYING: {TaskStatus.COMPLETED, TaskStatus.BUILDING, TaskStatus.FAILED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
}


@dataclass
class TransitionResult:
    """Result of a state transition."""

    success: bool
    new_status: TaskStatus
    gate_result: GateResult | None = None
    grade_result: GradeResult | None = None
    error: str | None = None


def transition_to_building(task: TaskState, now: datetime) -> TransitionResult:
    """Start building (from PENDING or VERIFYING for revision).

    Creates a new Attempt and sets status to BUILDING.
    """
    if task.status not in (TaskStatus.PENDING, TaskStatus.VERIFYING):
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot start building from {task.status.value}",
        )

    attempt_num = len(task.attempts) + 1
    task.attempts.append(Attempt(attempt_num=attempt_num, started_at=now))
    task.current_attempt = attempt_num
    task.status = TaskStatus.BUILDING
    return TransitionResult(success=True, new_status=TaskStatus.BUILDING)


def transition_to_verifying(task: TaskState) -> TransitionResult:
    """Move to verification (requires checklist gate pass)."""
    if task.status != TaskStatus.BUILDING:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot verify from {task.status.value}",
        )

    gate_result = evaluate_checklist_gate(task.checklist)
    if not gate_result.passed:
        return TransitionResult(
            success=False,
            new_status=TaskStatus.BUILDING,
            gate_result=gate_result,
            error="Checklist gate failed",
        )

    task.status = TaskStatus.VERIFYING
    return TransitionResult(success=True, new_status=TaskStatus.VERIFYING, gate_result=gate_result)


def transition_after_verification(task: TaskState, now: datetime) -> TransitionResult:
    """Complete verification - to COMPLETED, revision (BUILDING), or FAILED."""
    if task.status != TaskStatus.VERIFYING:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot complete verification from {task.status.value}",
        )

    grade_result = evaluate_grades(task.checklist)

    # Mark current attempt complete
    if task.attempts:
        task.attempts[-1].completed_at = now
        task.attempts[-1].outcome = "passed" if grade_result.passed else "revision_needed"

    if grade_result.passed:
        task.status = TaskStatus.COMPLETED
        return TransitionResult(
            success=True, new_status=TaskStatus.COMPLETED, grade_result=grade_result
        )

    # Check retry limit
    if task.current_attempt >= task.max_attempts:
        task.status = TaskStatus.FAILED
        if task.attempts:
            task.attempts[-1].outcome = "failed"
        return TransitionResult(
            success=True,
            new_status=TaskStatus.FAILED,
            grade_result=grade_result,
            error=f"Max attempts ({task.max_attempts}) reached",
        )

    # Start revision - create new attempt
    new_attempt_num = task.current_attempt + 1
    task.attempts.append(Attempt(attempt_num=new_attempt_num, started_at=now))
    task.current_attempt = new_attempt_num
    task.status = TaskStatus.BUILDING
    return TransitionResult(success=True, new_status=TaskStatus.BUILDING, grade_result=grade_result)
