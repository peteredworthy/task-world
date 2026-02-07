"""Task state machine transitions (pure functions)."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from orchestrator.config.enums import ChecklistStatus, Priority, RunStatus, TaskStatus
from orchestrator.config.models import StepConfig
from orchestrator.state.models import (
    Attempt,
    ChecklistItem,
    GradeSnapshotItem,
    Run,
    StepState,
    TaskState,
    TransitionTracker,
)
from orchestrator.workflow.errors import GateBlockedError
from orchestrator.workflow.gates import GateResult, evaluate_checklist_gate
from orchestrator.workflow.grades import GradeResult, evaluate_grades

VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.BUILDING},
    TaskStatus.BUILDING: {TaskStatus.VERIFYING, TaskStatus.PENDING_USER_ACTION, TaskStatus.FAILED},
    TaskStatus.PENDING_USER_ACTION: {
        TaskStatus.BUILDING,
        TaskStatus.VERIFYING,
        TaskStatus.COMPLETED,
    },
    TaskStatus.VERIFYING: {
        TaskStatus.COMPLETED,
        TaskStatus.BUILDING,
        TaskStatus.PENDING_USER_ACTION,
        TaskStatus.FAILED,
    },
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
    """Start building (from PENDING, VERIFYING for revision, or PENDING_USER_ACTION).

    Creates a new Attempt and sets status to BUILDING.
    """
    if task.status not in (
        TaskStatus.PENDING,
        TaskStatus.VERIFYING,
        TaskStatus.PENDING_USER_ACTION,
    ):
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
    """Move to verification from BUILDING or PENDING_USER_ACTION (requires checklist gate pass).

    Raises:
        GateBlockedError: If the checklist gate does not pass.
    """
    if task.status not in (TaskStatus.BUILDING, TaskStatus.PENDING_USER_ACTION):
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot verify from {task.status.value}",
        )

    gate_result = evaluate_checklist_gate(task.checklist)
    if not gate_result.passed:
        raise GateBlockedError("checklist", gate_result.blocking_items)

    task.status = TaskStatus.VERIFYING
    return TransitionResult(success=True, new_status=TaskStatus.VERIFYING, gate_result=gate_result)


def transition_to_pending_clarification(
    task: TaskState,
    request_id: str,
) -> TransitionResult:
    """Transition to PENDING_USER_ACTION for clarification.

    Valid from: BUILDING
    """
    if task.status != TaskStatus.BUILDING:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot request clarification from {task.status.value}",
        )

    task.status = TaskStatus.PENDING_USER_ACTION
    task.pending_action_type = "clarification"
    task.pending_clarification_id = request_id
    return TransitionResult(success=True, new_status=TaskStatus.PENDING_USER_ACTION)


def transition_from_clarification(
    task: TaskState,
) -> TransitionResult:
    """Resume from clarification - back to BUILDING.

    Valid from: PENDING_USER_ACTION (clarification)
    """
    if task.status != TaskStatus.PENDING_USER_ACTION:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot resume from {task.status.value}",
        )
    if task.pending_action_type != "clarification":
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Not a clarification action: {task.pending_action_type}",
        )

    task.status = TaskStatus.BUILDING
    task.pending_action_type = None
    task.pending_clarification_id = None
    return TransitionResult(success=True, new_status=TaskStatus.BUILDING)


def transition_to_pending_approval(
    task: TaskState,
) -> TransitionResult:
    """Transition to PENDING_USER_ACTION for approval.

    Valid from: VERIFYING (after auto_verify passes)
    """
    if task.status != TaskStatus.VERIFYING:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot await approval from {task.status.value}",
        )

    task.status = TaskStatus.PENDING_USER_ACTION
    task.pending_action_type = "approval"
    return TransitionResult(success=True, new_status=TaskStatus.PENDING_USER_ACTION)


def transition_from_approval(
    task: TaskState,
    approved: bool,
    now: datetime,
) -> TransitionResult:
    """Complete approval - to COMPLETED or back to BUILDING.

    Valid from: PENDING_USER_ACTION (approval)
    """
    if task.status != TaskStatus.PENDING_USER_ACTION:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot complete approval from {task.status.value}",
        )
    if task.pending_action_type != "approval":
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Not an approval action: {task.pending_action_type}",
        )

    task.pending_action_type = None

    if approved:
        task.status = TaskStatus.COMPLETED
        if task.attempts:
            task.attempts[-1].completed_at = now
            task.attempts[-1].outcome = "passed"
        return TransitionResult(success=True, new_status=TaskStatus.COMPLETED)
    else:
        # Rejection - back to building for revision
        if task.current_attempt >= task.max_attempts:
            task.status = TaskStatus.FAILED
            if task.attempts:
                task.attempts[-1].completed_at = now
                task.attempts[-1].outcome = "failed"
            return TransitionResult(
                success=True,
                new_status=TaskStatus.FAILED,
                error=f"Max attempts ({task.max_attempts}) reached",
            )

        # Start new attempt
        new_attempt_num = task.current_attempt + 1
        task.attempts.append(Attempt(attempt_num=new_attempt_num, started_at=now))
        task.current_attempt = new_attempt_num
        task.status = TaskStatus.BUILDING
        return TransitionResult(success=True, new_status=TaskStatus.BUILDING)


def transition_after_verification(task: TaskState, now: datetime) -> TransitionResult:
    """Complete verification - to COMPLETED, revision (BUILDING), or FAILED."""
    if task.status != TaskStatus.VERIFYING:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot complete verification from {task.status.value}",
        )

    grade_result = evaluate_grades(task.checklist)

    # Snapshot checklist grades into the current attempt
    if task.attempts:
        task.attempts[-1].grade_snapshot = [
            GradeSnapshotItem(
                req_id=item.req_id,
                grade=item.grade,
                grade_reason=item.grade_reason,
            )
            for item in task.checklist
        ]

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


# --- Step and Run completion (pure functions) ---

_TERMINAL_TASK_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED}


def is_step_complete(step: StepState) -> bool:
    """A step is complete when every task has reached a terminal status."""
    if not step.tasks:
        return True
    return all(t.status in _TERMINAL_TASK_STATUSES for t in step.tasks)


def check_step_progression(run: Run) -> bool:
    """Check and advance step progression after a task status change.

    Marks the current step as completed if all its tasks are terminal,
    then advances ``current_step_index`` past any already-completed steps.

    Returns True if any step was newly marked completed.
    """
    changed = False
    while run.current_step_index < len(run.steps):
        step = run.steps[run.current_step_index]
        if not step.completed and is_step_complete(step):
            step.completed = True
            changed = True
        if step.completed and run.current_step_index < len(run.steps) - 1:
            run.current_step_index += 1
        else:
            break
    return changed


def check_run_completion(run: Run, now: datetime) -> RunStatus | None:
    """Check if a run should auto-transition to COMPLETED or FAILED.

    Returns the new RunStatus if a transition should occur, or None if
    the run should remain in its current status.

    Only acts on ACTIVE runs where every step is completed.
    """
    if run.status != RunStatus.ACTIVE:
        return None
    if not all(step.completed for step in run.steps):
        return None

    # All steps done — determine final status
    all_tasks = [t for s in run.steps for t in s.tasks]
    has_failure = any(t.status == TaskStatus.FAILED for t in all_tasks)

    new_status = RunStatus.FAILED if has_failure else RunStatus.COMPLETED
    run.status = new_status
    run.completed_at = now
    return new_status


# --- Backward Transitions ---


def evaluate_condition(
    condition: str,
    checklist: list[ChecklistItem],
    run: Run,
    worktree_path: Path | None = None,
) -> bool:
    """Evaluate a named condition.

    Args:
        condition: The condition identifier to evaluate
        checklist: The checklist items for the current task
        run: The run state (for artifact checking)
        worktree_path: Optional path to the worktree for artifact checks

    Returns:
        True if the condition is met, False otherwise
    """
    # Built-in conditions
    if condition == "has_unresolved_conflicts":
        # Check if CONFLICTS.md exists and has unresolved items
        if worktree_path is None:
            return False
        conflicts_path = worktree_path / "CONFLICTS.md"
        if not conflicts_path.exists():
            return False
        # Simple heuristic: file exists and contains "[ ]" (unresolved items)
        content = conflicts_path.read_text()
        return "[ ]" in content

    if condition == "has_open_questions":
        # Check if design-questions.md exists and has unanswered questions
        if worktree_path is None:
            return False
        questions_path = worktree_path / "design-questions.md"
        if not questions_path.exists():
            return False
        # Simple heuristic: file exists and contains "[ ]" (open questions)
        content = questions_path.read_text()
        return "[ ]" in content

    if condition == "checklist_incomplete":
        # Any CRITICAL items not done
        return any(
            item.priority == Priority.CRITICAL and item.status != ChecklistStatus.DONE
            for item in checklist
        )

    # Custom conditions via checklist items with special IDs
    if condition.startswith("checklist:"):
        item_id = condition.split(":", 1)[1]
        item = next((i for i in checklist if i.req_id == item_id), None)
        return item is not None and item.status != ChecklistStatus.DONE

    return False


def evaluate_transition_conditions(
    step_config: StepConfig,
    current_step: StepState,
    checklist: list[ChecklistItem],
    run: Run,
    worktree_path: Path | None = None,
) -> tuple[str | None, str | None]:
    """Evaluate transition conditions and return target step ID.

    Args:
        step_config: The step configuration with transition rules
        current_step: The current step state
        checklist: The checklist items for evaluation
        run: The run state
        worktree_path: Optional path to the worktree

    Returns:
        A tuple of (target_step_id, message). Returns (None, None) if should proceed normally.
    """
    if step_config.transitions is None:
        return None, None

    # Initialize transition tracker if not present
    if run.transition_tracker is None:
        run.transition_tracker = TransitionTracker()

    # Evaluate conditions in order
    for cond in step_config.transitions.on_condition:
        # Check max iterations
        if not run.transition_tracker.can_transition(
            step_config.id, cond.target, cond.max_iterations
        ):
            continue  # Max iterations reached, skip this condition

        # Evaluate the condition
        if evaluate_condition(cond.condition, checklist, run, worktree_path):
            # Record the transition
            run.transition_tracker.record_transition(step_config.id, cond.target)
            return cond.target, cond.message

    # No conditions met, use on_complete if specified
    return step_config.transitions.on_complete, None
