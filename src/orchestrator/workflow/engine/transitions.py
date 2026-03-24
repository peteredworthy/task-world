"""Task state machine transitions (pure functions)."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast, Protocol

from orchestrator.config.enums import ChecklistStatus, Priority, RunStatus, TaskStatus
from orchestrator.config.models import RoutineConfig, StepConfig
from orchestrator.state._utils import generate_id
from orchestrator.state.models import (
    Attempt,
    ChecklistItem,
    GradeSnapshotItem,
    Run,
    StepState,
    TaskState,
    TransitionTracker,
)
from orchestrator.workflow.condition_evaluator import (
    ConditionEvaluator,
    ConditionEvalError,
    StepOutcome,
)
from orchestrator.workflow.errors import GateBlockedError
from orchestrator.workflow.events import StepSkipped, WorkflowEvent
from orchestrator.workflow.gates import GateResult, evaluate_checklist_gate
from orchestrator.workflow.grades import GradeResult, evaluate_grades


class Clock(Protocol):
    """Protocol for injectable clock."""

    def now(self) -> datetime: ...


class EventEmitter(Protocol):
    """Protocol for injectable event emitter."""

    def emit(self, event: WorkflowEvent) -> None: ...


VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.BUILDING, TaskStatus.FAN_OUT_RUNNING},
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
        TaskStatus.RECOVERING,
    },
    TaskStatus.RECOVERING: {
        TaskStatus.BUILDING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.PENDING_USER_ACTION,
    },
    TaskStatus.FAN_OUT_RUNNING: {
        TaskStatus.VERIFYING,
        TaskStatus.COMPLETED,
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
    """Start building (from PENDING, BUILDING for pre-gate revision, VERIFYING for revision, RECOVERING, or PENDING_USER_ACTION).

    Creates a new Attempt and sets status to BUILDING.
    """
    if task.status not in (
        TaskStatus.PENDING,
        TaskStatus.BUILDING,
        TaskStatus.VERIFYING,
        TaskStatus.PENDING_USER_ACTION,
        TaskStatus.RECOVERING,
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


def transition_to_recovering(task: TaskState, failure_reason: str) -> TransitionResult:
    """Transition to RECOVERING state for recovery agent intervention.

    Valid from: VERIFYING (when validation scripts crash or max attempts exceeded).
    Stores the failure reason in the current attempt's verifier_comment.
    """
    if task.status != TaskStatus.VERIFYING:
        return TransitionResult(
            success=False,
            new_status=task.status,
            error=f"Cannot recover from {task.status.value}",
        )

    task.status = TaskStatus.RECOVERING
    if task.attempts:
        task.attempts[-1].verifier_comment = failure_reason
    return TransitionResult(success=True, new_status=TaskStatus.RECOVERING)


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

        # Start new attempt - clear stale builder notes
        for item in task.checklist:
            item.note = None
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

    # If a verifier has started grading (at least one grade exists), block
    # premature submission when not all CRITICAL/EXPECTED items are graded.
    # This prevents the task from transitioning to FAILED due to ungraded
    # items when the verifier agent submits before finishing all grades.
    # When NO grades exist at all (auto-complete path), skip this check.
    has_any_grade = any(item.grade is not None for item in task.checklist)
    if has_any_grade:
        ungraded = [
            item.req_id
            for item in task.checklist
            if item.grade is None and item.priority in (Priority.CRITICAL, Priority.EXPECTED)
        ]
        if ungraded:
            return TransitionResult(
                success=False,
                new_status=task.status,
                error=(
                    f"Cannot complete verification: {len(ungraded)} requirement(s) "
                    f"not yet graded ({', '.join(ungraded)}). "
                    f"Grade all CRITICAL and EXPECTED requirements before submitting."
                ),
            )

    # Auto-complete path: when no verifier rubric ran (no grades exist at all),
    # auto-grade checklist items based on their self-reported status.
    # Items marked "done" by the builder get grade "A"; items still "open" or
    # "blocked" stay ungraded so evaluate_grades correctly fails them.
    # Block this path entirely when no verification was configured on the task.
    has_any_grade = any(item.grade is not None for item in task.checklist)
    if not has_any_grade:
        if not task.has_verification:
            return TransitionResult(
                success=False,
                new_status=task.status,
                error=(
                    "Cannot auto-complete: task has no verification configured "
                    "(no auto_verify items and no verifier rubric). "
                    "Add auto_verify items or a verifier rubric to the task config."
                ),
            )
        for item in task.checklist:
            if item.status == ChecklistStatus.DONE:
                item.grade = "A"
                item.grade_reason = "Auto-graded (builder self-reported done, no verifier rubric)"
            elif item.status == ChecklistStatus.NOT_APPLICABLE:
                item.grade = "A"
                item.grade_reason = "Marked not applicable by builder"

    grade_result = evaluate_grades(task.checklist)

    # Snapshot checklist grades and builder notes into the current attempt
    if task.attempts:
        task.attempts[-1].grade_snapshot = [
            GradeSnapshotItem(
                req_id=item.req_id,
                grade=item.grade,
                grade_reason=item.grade_reason,
                note=item.note,
            )
            for item in task.checklist
        ]

    # Mark current attempt complete
    if task.attempts:
        task.attempts[-1].completed_at = now
        task.attempts[-1].outcome = "passed" if grade_result.passed else "revision_needed"

    # Synthesize verifier_comment from grade results so builder gets feedback on retry.
    # Only populate if not already set (e.g. by auto-verify or recovery agent).
    if not grade_result.passed and task.attempts and not task.attempts[-1].verifier_comment:
        lines: list[str] = []
        if grade_result.failing_items:
            lines.append("The following requirements did not meet the grade threshold:")
            for item in grade_result.failing_items:
                lines.append(f"  - {item}")
        if grade_result.revision_guidance:
            lines.append("")
            lines.append("Verifier feedback:")
            for g in grade_result.revision_guidance:
                lines.append(f"  - {g}")
        if lines:
            task.attempts[-1].verifier_comment = "\n".join(lines)

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

    # Start revision - clear stale builder notes and create new attempt
    for item in task.checklist:
        item.note = None
    new_attempt_num = task.current_attempt + 1
    task.attempts.append(Attempt(attempt_num=new_attempt_num, started_at=now))
    task.current_attempt = new_attempt_num
    task.status = TaskStatus.BUILDING
    return TransitionResult(success=True, new_status=TaskStatus.BUILDING, grade_result=grade_result)


# --- Step and Run completion (pure functions) ---

_TERMINAL_TASK_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED}


def is_step_complete(step: StepState) -> bool:
    """A step is complete when every non-child task has reached a terminal status.

    Child tasks (parent_task_id set) are managed by the fan-out executor and
    contribute to their parent's state, not directly to step completion.
    FAN_OUT_RUNNING is non-terminal (parent still executing children).
    """
    if not step.tasks:
        return True
    top_level = [t for t in step.tasks if t.parent_task_id is None]
    if not top_level:
        return True
    return all(t.status in _TERMINAL_TASK_STATUSES for t in top_level)


def step_has_failure(step: StepState) -> bool:
    """Return True if any non-child task in the step has FAILED status."""
    return any(t.status == TaskStatus.FAILED for t in step.tasks if t.parent_task_id is None)


def check_step_progression(
    run: Run,
    routine_config: RoutineConfig | None = None,
    clock: Clock | None = None,
    emitter: EventEmitter | None = None,
    worktree_path: Path | None = None,
    run_config: dict[str, Any] | None = None,
) -> bool:
    """Check and advance step progression after a task status change.

    Marks the current step as completed if all its tasks are terminal,
    then advances ``current_step_index`` past any already-completed steps.
    Stops advancing if the completed step contains a failed task (fail-fast).

    If routine_config is provided, evaluates step conditions and skips steps
    when their conditions are False. Pauses the run if a manual gate (when: "manual")
    is encountered or if condition evaluation raises an error.

    Handles consecutive false-condition steps by evaluating and skipping them
    in sequence until a true-condition step or end of steps is reached.

    Args:
        run: The run state to progress.
        routine_config: The routine config to look up step conditions (optional).
        clock: Clock for generating event timestamps (optional).
        emitter: Event emitter for emitting events (optional).
        worktree_path: Path to worktree for artifact evaluation (optional).
        run_config: Run configuration variables for condition evaluation (optional).

    Returns True if any step was newly marked completed.
    """
    changed = False
    while run.current_step_index < len(run.steps):
        step = run.steps[run.current_step_index]

        # Before working on this step, check if repeat_for needs expansion
        # (applies to all steps including the first one)
        if not step.completed and not step.skipped and routine_config is not None:
            step_config = _find_step_config(routine_config, step.config_id)
            if (
                step_config is not None
                and step_config.condition is not None
                and step_config.condition.repeat_for is not None
            ):
                # Check if this step has already been expanded (has injected_vars)
                has_injected_vars = step.condition is not None and "injected_vars" in step.condition

                if not has_injected_vars:
                    # First time seeing this repeat_for - expand it
                    try:
                        repeat_for_expr = step_config.condition.repeat_for
                        var_name, var_path = _parse_repeat_for_expression(repeat_for_expr)
                        items = _get_variable_value_for_repeat(var_path, run_config or {}, run)

                        # Validate that items is a list
                        if not isinstance(items, list):
                            run.status = RunStatus.PAUSED
                            run.pause_reason = "repeat_for_invalid_type"
                            run.last_error = (
                                f"repeat_for variable '{var_path}' resolved to "
                                f"{type(items).__name__}, expected list"
                            )
                            if clock is not None and emitter is not None:
                                from orchestrator.workflow.events import RunStatusChanged

                                emitter.emit(
                                    RunStatusChanged(
                                        timestamp=clock.now(),
                                        run_id=run.id,
                                        event_type="run_status_changed",
                                        old_status=RunStatus.ACTIVE,
                                        new_status=RunStatus.PAUSED,
                                    )
                                )
                            break

                        # Create N step copies
                        items_list: list[Any] = cast(list[Any], items)
                        if items_list:  # Only expand if list is non-empty
                            copies = _create_repeat_step_copies(step, items_list, var_name)

                            # Replace original step with copies in run.steps
                            run.steps[run.current_step_index : run.current_step_index + 1] = copies

                            # Persist expanded steps to DB immediately via the caller's update
                            changed = True

                            # Continue to next iteration to process the first copy
                            continue
                        else:
                            # Empty list: mark step as skipped with reason "empty list"
                            step.skipped = True
                            step.skip_reason = "empty list"
                            step.completed = True
                            changed = True
                            if clock is not None and emitter is not None:
                                emitter.emit(
                                    StepSkipped(
                                        timestamp=clock.now(),
                                        run_id=run.id,
                                        step_index=run.current_step_index,
                                        step_id=step.id,
                                        condition=f"repeat_for '{repeat_for_expr}'",
                                        skip_reason="empty list",
                                    )
                                )
                            # Move to next step
                            if run.current_step_index < len(run.steps) - 1:
                                run.current_step_index += 1
                            else:
                                # At last step, advance past it
                                run.current_step_index += 1
                            continue

                    except ValueError as e:
                        run.status = RunStatus.PAUSED
                        run.pause_reason = "repeat_for_resolution_error"
                        run.last_error = f"repeat_for resolution error: {str(e)}"
                        if clock is not None and emitter is not None:
                            from orchestrator.workflow.events import RunStatusChanged

                            emitter.emit(
                                RunStatusChanged(
                                    timestamp=clock.now(),
                                    run_id=run.id,
                                    event_type="run_status_changed",
                                    old_status=RunStatus.ACTIVE,
                                    new_status=RunStatus.PAUSED,
                                )
                            )
                        break

        # Before working on this step, check if its condition should skip it
        # (applies to all steps including the first one)
        # Skip condition evaluation if any task has already started (gate already passed)
        any_task_started = any(t.status != TaskStatus.PENDING for t in step.tasks)
        if (
            not step.completed
            and not step.skipped
            and not any_task_started
            and routine_config is not None
        ):
            step_config = _find_step_config(routine_config, step.config_id)
            if step_config is not None and step_config.condition is not None:
                condition = step_config.condition
                if condition.when is not None:
                    # Special case: manual gate
                    if condition.when == "manual":
                        run.status = RunStatus.PAUSED
                        run.pause_reason = "manual_gate"
                        if clock is not None and emitter is not None:
                            from orchestrator.workflow.events import RunStatusChanged

                            emitter.emit(
                                RunStatusChanged(
                                    timestamp=clock.now(),
                                    run_id=run.id,
                                    event_type="run_status_changed",
                                    old_status=RunStatus.ACTIVE,
                                    new_status=RunStatus.PAUSED,
                                )
                            )
                        break

                    # Evaluate the condition for the current step
                    try:
                        evaluator = ConditionEvaluator()
                        variables: dict[str, Any] = dict(run_config) if run_config else {}

                        # If step has injected_vars (from repeat_for expansion), merge them into variables
                        if step.condition is not None and "injected_vars" in step.condition:
                            injected = step.condition.get("injected_vars", {})
                            if isinstance(injected, dict):
                                variables.update(cast(dict[str, Any], injected))

                        step_outcomes = _build_step_outcomes(run)
                        result = evaluator.evaluate(condition.when, variables, step_outcomes)

                        if result is False:
                            # Skip this step - mark as skipped and completed without doing work
                            step.skipped = True
                            step.skip_reason = f"Condition '{condition.when}' evaluated to false"
                            step.completed = True
                            changed = True
                            if clock is not None and emitter is not None:
                                emitter.emit(
                                    StepSkipped(
                                        timestamp=clock.now(),
                                        run_id=run.id,
                                        step_index=run.current_step_index,
                                        step_id=step.id,
                                        condition=condition.when,
                                        skip_reason=step.skip_reason,
                                    )
                                )
                            # Move to next step
                            if run.current_step_index < len(run.steps) - 1:
                                run.current_step_index += 1
                            else:
                                # At last step, advance past it
                                run.current_step_index += 1
                            continue
                        elif result is None:
                            # Manual gate from evaluator
                            run.status = RunStatus.PAUSED
                            run.pause_reason = "manual_gate"
                            if clock is not None and emitter is not None:
                                from orchestrator.workflow.events import RunStatusChanged

                                emitter.emit(
                                    RunStatusChanged(
                                        timestamp=clock.now(),
                                        run_id=run.id,
                                        event_type="run_status_changed",
                                        old_status=RunStatus.ACTIVE,
                                        new_status=RunStatus.PAUSED,
                                    )
                                )
                            break
                        # result is True - proceed normally
                    except ConditionEvalError as e:
                        run.status = RunStatus.PAUSED
                        run.pause_reason = "condition_eval_error"
                        run.last_error = f"Condition evaluation error: {e.message}"
                        if clock is not None and emitter is not None:
                            from orchestrator.workflow.events import RunStatusChanged

                            emitter.emit(
                                RunStatusChanged(
                                    timestamp=clock.now(),
                                    run_id=run.id,
                                    event_type="run_status_changed",
                                    old_status=RunStatus.ACTIVE,
                                    new_status=RunStatus.PAUSED,
                                )
                            )
                        break

        if not step.completed and is_step_complete(step):
            step.completed = True
            changed = True
        if not step.completed:
            # Step not complete, can't advance
            break

        # Step is complete - check for fail-fast
        if step_has_failure(step):
            break

        # Try to advance to next step
        if run.current_step_index >= len(run.steps) - 1:
            # We're on the last step - evaluate its condition if present and not yet evaluated
            if not step.skipped and routine_config is not None:
                step_config = _find_step_config(routine_config, step.config_id)
                if step_config is not None and step_config.condition is not None:
                    condition = step_config.condition
                    if condition.when is not None:
                        # Special case: manual gate
                        if condition.when == "manual":
                            run.status = RunStatus.PAUSED
                            run.pause_reason = "manual_gate"
                            if clock is not None and emitter is not None:
                                from orchestrator.workflow.events import RunStatusChanged

                                emitter.emit(
                                    RunStatusChanged(
                                        timestamp=clock.now(),
                                        run_id=run.id,
                                        event_type="run_status_changed",
                                        old_status=RunStatus.ACTIVE,
                                        new_status=RunStatus.PAUSED,
                                    )
                                )
                            break

                        # Evaluate the condition for the last step
                        try:
                            evaluator = ConditionEvaluator()
                            variables = run_config or {}
                            step_outcomes = _build_step_outcomes(run)
                            result = evaluator.evaluate(condition.when, variables, step_outcomes)

                            if result is False:
                                # Skip the last step
                                step.skipped = True
                                step.skip_reason = (
                                    f"Condition '{condition.when}' evaluated to false"
                                )
                                changed = True
                                if clock is not None and emitter is not None:
                                    emitter.emit(
                                        StepSkipped(
                                            timestamp=clock.now(),
                                            run_id=run.id,
                                            step_index=run.current_step_index,
                                            step_id=step.id,
                                            condition=condition.when,
                                            skip_reason=step.skip_reason,
                                        )
                                    )
                                # Advance past the last step so the while loop exits
                                run.current_step_index += 1
                                continue
                            elif result is None:
                                # Manual gate from evaluator
                                run.status = RunStatus.PAUSED
                                run.pause_reason = "manual_gate"
                                if clock is not None and emitter is not None:
                                    from orchestrator.workflow.events import RunStatusChanged

                                    emitter.emit(
                                        RunStatusChanged(
                                            timestamp=clock.now(),
                                            run_id=run.id,
                                            event_type="run_status_changed",
                                            old_status=RunStatus.ACTIVE,
                                            new_status=RunStatus.PAUSED,
                                        )
                                    )
                                break
                            # result is True - proceed normally
                        except ConditionEvalError as e:
                            run.status = RunStatus.PAUSED
                            run.pause_reason = "condition_eval_error"
                            run.last_error = f"Condition evaluation error: {e.message}"
                            if clock is not None and emitter is not None:
                                from orchestrator.workflow.events import RunStatusChanged

                                emitter.emit(
                                    RunStatusChanged(
                                        timestamp=clock.now(),
                                        run_id=run.id,
                                        event_type="run_status_changed",
                                        old_status=RunStatus.ACTIVE,
                                        new_status=RunStatus.PAUSED,
                                    )
                                )
                            break
            # All steps done (no more steps to advance to)
            break
        else:
            # Not the last step - advance to the next step
            run.current_step_index += 1
            next_step = run.steps[run.current_step_index]

            # Evaluate the next step's condition if we have routine config
            if routine_config is not None:
                step_config = _find_step_config(routine_config, next_step.config_id)

                if step_config is not None and step_config.condition is not None:
                    condition = step_config.condition

                    # Evaluate condition.when if present
                    if condition.when is not None:
                        # Special case: manual gate
                        if condition.when == "manual":
                            # Pause the run for manual gate
                            run.status = RunStatus.PAUSED
                            run.pause_reason = "manual_gate"
                            if clock is not None and emitter is not None:
                                from orchestrator.workflow.events import RunStatusChanged

                                emitter.emit(
                                    RunStatusChanged(
                                        timestamp=clock.now(),
                                        run_id=run.id,
                                        event_type="run_status_changed",
                                        old_status=RunStatus.ACTIVE,
                                        new_status=RunStatus.PAUSED,
                                    )
                                )
                            break

                        # Evaluate the condition expression
                        try:
                            evaluator = ConditionEvaluator()
                            variables = run_config or {}
                            step_outcomes = _build_step_outcomes(run)
                            result = evaluator.evaluate(condition.when, variables, step_outcomes)

                            if result is False:
                                # Skip this step and continue to next
                                next_step.skipped = True
                                next_step.skip_reason = (
                                    f"Condition '{condition.when}' evaluated to false"
                                )
                                # Mark as completed so the while loop can continue advancing
                                next_step.completed = True
                                changed = True
                                if clock is not None and emitter is not None:
                                    emitter.emit(
                                        StepSkipped(
                                            timestamp=clock.now(),
                                            run_id=run.id,
                                            step_index=run.current_step_index,
                                            step_id=next_step.id,
                                            condition=condition.when,
                                            skip_reason=next_step.skip_reason,
                                        )
                                    )
                                # Continue to evaluate next step in the while loop
                                continue
                            elif result is None:
                                # Manual gate (None from evaluator)
                                run.status = RunStatus.PAUSED
                                run.pause_reason = "manual_gate"
                                if clock is not None and emitter is not None:
                                    from orchestrator.workflow.events import RunStatusChanged

                                    emitter.emit(
                                        RunStatusChanged(
                                            timestamp=clock.now(),
                                            run_id=run.id,
                                            event_type="run_status_changed",
                                            old_status=RunStatus.ACTIVE,
                                            new_status=RunStatus.PAUSED,
                                        )
                                    )
                                break
                            # If result is True, proceed normally (don't skip)
                        except ConditionEvalError as e:
                            # Pause the run with error detail
                            run.status = RunStatus.PAUSED
                            run.pause_reason = "condition_eval_error"
                            run.last_error = f"Condition evaluation error: {e.message}"
                            if clock is not None and emitter is not None:
                                from orchestrator.workflow.events import RunStatusChanged

                                emitter.emit(
                                    RunStatusChanged(
                                        timestamp=clock.now(),
                                        run_id=run.id,
                                        event_type="run_status_changed",
                                        old_status=RunStatus.ACTIVE,
                                        new_status=RunStatus.PAUSED,
                                    )
                                )
                            break
    return changed


def _find_step_config(routine_config: RoutineConfig, step_config_id: str) -> StepConfig | None:
    """Find a step config by its config_id in the routine."""
    for step in routine_config.steps:
        if step.id == step_config_id:
            return step
    return None


def _build_step_outcomes(run: Run) -> dict[str, StepOutcome]:
    """Build StepOutcome objects for all completed/skipped steps in the run.

    This provides context for condition evaluation about previous steps.
    """
    outcomes: dict[str, StepOutcome] = {}
    for step in run.steps:
        if step.completed or step.skipped:
            has_failures = step_has_failure(step) if step.completed else False
            all_passed = (
                not has_failures
                and all(
                    t.status == TaskStatus.COMPLETED for t in step.tasks if t.parent_task_id is None
                )
                if step.completed
                else False
            )
            any_completed = any(
                t.status == TaskStatus.COMPLETED for t in step.tasks if t.parent_task_id is None
            )
            outcomes[step.config_id] = StepOutcome(
                has_failures=has_failures,
                all_passed=all_passed,
                any_completed=any_completed,
                completed=step.completed,
                skipped=step.skipped,
            )
    return outcomes


def _parse_repeat_for_expression(repeat_for: str) -> tuple[str, str]:
    """Parse a repeat_for expression to extract variable name and path.

    Args:
        repeat_for: Expression like "item in context.items" or "env in config.environments"

    Returns:
        Tuple of (variable_name, variable_path)

    Raises:
        ValueError: If expression is malformed
    """
    parts = repeat_for.strip().split()
    if len(parts) < 3 or parts[1].lower() != "in":
        raise ValueError(
            f"Invalid repeat_for expression: '{repeat_for}'. "
            f"Expected format: 'var_name in context.path' or 'var_name in config.path'"
        )
    var_name = parts[0]
    var_path = " ".join(parts[2:])  # Handle paths with spaces (unlikely but safe)
    return var_name, var_path


def _get_variable_value_for_repeat(var_path: str, run_config: dict[str, Any], run: Run) -> Any:
    """Resolve a variable value for repeat_for expansion.

    Supports resolving from:
    1. Run configuration using "context.*" paths
    2. Prior step outputs using "steps.STEP_ID.*" paths

    The variable is accessed from the run_config dictionary first, then from prior
    step outputs if not found in run_config.

    Args:
        var_path: Variable path like "context.items" (resolves from run_config) or
                  "steps.S1.output" (resolves from step outputs)
        run_config: Run configuration dict
        run: The run state with steps and their outputs

    Returns:
        The resolved variable value

    Raises:
        ValueError: If variable cannot be resolved or is not a valid path
    """
    # Handle direct config references
    parts = var_path.strip().split(".")
    if not parts:
        raise ValueError(f"Invalid variable path: {var_path}")

    # Try to resolve from run_config first (context.*)
    if parts[0] == "context":
        # "context.x" resolves from run_config
        value: Any = run_config
        for part in parts[1:]:
            if not isinstance(value, dict):
                raise ValueError(
                    f"Cannot access {part} on {type(value).__name__} (resolving '{var_path}')"
                )
            value_dict: dict[str, Any] = cast(dict[str, Any], value)
            value = value_dict.get(part)
        if value is None:
            raise ValueError(f"Variable not found in context: {var_path}")
        return value

    # Try to resolve from prior step outputs (steps.STEP_ID.output)
    if parts[0] == "steps":
        if len(parts) < 3:
            raise ValueError(
                f"Invalid steps path: '{var_path}'. "
                f"Expected format: 'steps.STEP_ID.output' or 'steps.STEP_ID.task_outputs'"
            )

        step_config_id = parts[1]
        property_name = parts[2]

        # Find the completed step with this config_id
        matching_step = None
        for step in run.steps:
            if step.config_id == step_config_id:
                matching_step = step
                break

        if matching_step is None:
            raise ValueError(f"Step with config_id '{step_config_id}' not found in run")

        if not matching_step.completed:
            raise ValueError(
                f"Step '{step_config_id}' is not yet completed, cannot access its outputs"
            )

        # Extract the outputs based on the property name
        if property_name == "output":
            # Return list of all agent outputs from completed tasks in the step
            outputs: list[str] = []
            for task in matching_step.tasks:
                # Skip child tasks (from fan-out)
                if task.parent_task_id is not None:
                    continue
                # Get the most recent completed attempt's output
                if task.status == TaskStatus.COMPLETED and task.attempts:
                    for attempt in reversed(task.attempts):
                        if attempt.agent_output:
                            outputs.append(attempt.agent_output)
                            break
            return outputs

        elif property_name == "task_outputs":
            # Return dict of {task_id: output} for all tasks in the step
            task_outputs: dict[str, str] = {}
            for task in matching_step.tasks:
                if task.parent_task_id is not None:
                    continue
                if task.status == TaskStatus.COMPLETED and task.attempts:
                    for attempt in reversed(task.attempts):
                        if attempt.agent_output:
                            task_outputs[task.config_id] = attempt.agent_output
                            break
            return task_outputs

        else:
            raise ValueError(
                f"Unsupported property on step output: '{property_name}'. "
                f"Expected 'output' or 'task_outputs'"
            )

    raise ValueError(
        f"Unsupported variable path: '{var_path}'. "
        f"Expected 'context.*' for run config or 'steps.*' for prior step outputs."
    )


def _create_repeat_step_copies(
    original_step: StepState,
    items: list[Any],
    var_name: str,
) -> list[StepState]:
    """Create N copies of a step for each item in a list.

    Args:
        original_step: The original StepState to copy
        items: List of items to iterate over
        var_name: Name of the variable to inject (e.g., "item")

    Returns:
        List of N new StepState objects with injected item and item_index
    """
    import copy

    copies: list[StepState] = []
    count = len(items)

    for index, item in enumerate(items):
        # Create a deep copy of the original step
        step_copy = copy.deepcopy(original_step)

        # Generate new ID: {original_id}-{index}
        step_copy.id = f"{original_step.id}-{index}"

        # Update title: {original_title} [{index + 1}/{count}]
        step_copy.title = f"{original_step.title} [{index + 1}/{count}]"

        # Generate unique IDs for each task copy to avoid PK collisions
        # when multiple copies are persisted to the DB.
        for task in step_copy.tasks:
            task.id = generate_id()
            # Also regenerate attempt IDs to avoid collisions
            for attempt in task.attempts:
                attempt.id = generate_id()

        # Create injected variables dict in step condition if not present
        if step_copy.condition is None:
            step_copy.condition = {}

        # Store injected variables for template substitution
        # These will be available during prompt building
        if "injected_vars" not in step_copy.condition:
            step_copy.condition["injected_vars"] = {}

        step_copy.condition["injected_vars"][var_name] = item
        step_copy.condition["injected_vars"]["item_index"] = index

        copies.append(step_copy)

    return copies


def check_run_completion(run: Run, now: datetime) -> RunStatus | None:
    """Check if a run should auto-transition to COMPLETED or FAILED.

    Returns the new RunStatus if a transition should occur, or None if
    the run should remain in its current status.

    Triggers on ACTIVE runs when either:
    - All steps are completed (normal completion)
    - A completed step contains a failed task (fail-fast)
    """
    if run.status != RunStatus.ACTIVE:
        return None

    # Fail-fast: check if any completed step has a failed task
    has_failure = False
    for step in run.steps:
        if step.completed and step_has_failure(step):
            has_failure = True
            break

    if has_failure:
        # A step completed with failures — fail the run immediately
        run.status = RunStatus.FAILED
        run.completed_at = now
        return RunStatus.FAILED

    if not all(step.completed for step in run.steps):
        return None

    # All steps done with no failures
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
