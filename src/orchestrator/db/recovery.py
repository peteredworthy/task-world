"""Event replay for crash recovery.

Reconstructs Run state by replaying persisted events in order.
"""

from datetime import datetime
from typing import Any

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.state.models import Attempt, GradeSnapshotItem, HumanApproval, Run


# Documents recovery behavior per event type.
RECOVERY_MATRIX: dict[str, str] = {
    "run_status_changed": "recoverable",
    "task_status_changed": "recoverable",
    "step_completed": "recoverable",
    "step_skipped": "recoverable",
    "grades_evaluated": "recoverable",
    "agent_error": "recoverable",
    "auto_verify_completed": "recoverable",
    "clarification_requested": "recoverable",
    "clarification_responded": "recoverable",
    "approval_requested": "recoverable",
    "approval_decision": "recoverable",
    "run_step_backward": "recoverable",
    "task_reverted": "recoverable",
    "checklist_gate_evaluated": "informational",
    "agent_output": "informational",
    "agent_changed": "informational",
    "agent_died": "informational",
    "health_check": "informational",
    "prune_applied": "informational",
    "test_run_started": "informational",
    "test_run_completed": "informational",
    "conflict_resolved": "informational",
    "back_merge_completed": "informational",
    "back_merge_reverted": "informational",
    "agent_fix_started": "informational",
    "agent_fix_completed": "informational",
    "child_spawned": "informational",
    "child_completed": "informational",
    "child_failed": "informational",
}


def _find_task(run: Run, task_id: str):
    """Find a task by ID across all steps. Returns (step, task) or (None, None)."""
    for step in run.steps:
        for task in step.tasks:
            if task.id == task_id:
                return step, task
    return None, None


def replay_events(run: Run, events: list[dict[str, Any]]) -> Run:
    """Replay events onto a Run to reconstruct its state.

    This function is idempotent: replaying the same events twice from the same
    checkpoint produces no additional state changes.

    Args:
        run: A Run in its initial (DRAFT) state, as created by the factory.
        events: Events from ``EventStore.get_events_for_run``, each with
                ``type``, ``timestamp``, and ``payload`` keys.

    Returns:
        The Run with status fields updated to match the event history.
    """
    for event in events:
        event_type = event["type"]
        payload = event["payload"]
        timestamp = event["timestamp"]

        if event_type == "run_status_changed":
            _apply_run_status_changed(run, payload, timestamp)
        elif event_type == "task_status_changed":
            _apply_task_status_changed(run, payload, timestamp)
        elif event_type == "step_completed":
            _apply_step_completed(run, payload)
        elif event_type == "step_skipped":
            _apply_step_skipped(run, payload)
        elif event_type == "grades_evaluated":
            _apply_grades_evaluated(run, payload)
        elif event_type == "agent_error":
            _apply_agent_error(run, payload)
        elif event_type == "auto_verify_completed":
            _apply_auto_verify_completed(run, payload)
        elif event_type == "clarification_requested":
            _apply_clarification_requested(run, payload)
        elif event_type == "clarification_responded":
            _apply_clarification_responded(run, payload)
        elif event_type == "approval_requested":
            _apply_approval_requested(run, payload)
        elif event_type == "approval_decision":
            _apply_approval_decision(run, payload, timestamp)
        elif event_type == "run_step_backward":
            _apply_run_step_backward(run, payload)
        elif event_type == "task_reverted":
            _apply_task_reverted(run, payload)
        elif event_type in (
            "checklist_gate_evaluated",
            "agent_output",
            "agent_changed",
            "agent_died",
            "health_check",
            "prune_applied",
            "test_run_started",
            "test_run_completed",
            "conflict_resolved",
            "back_merge_completed",
            "back_merge_reverted",
            "agent_fix_started",
            "agent_fix_completed",
            "child_spawned",
            "child_completed",
            "child_failed",
        ):
            # Informational events — no state changes needed
            pass

    return run


def _apply_run_status_changed(run: Run, payload: dict[str, Any], timestamp: datetime) -> None:
    """Apply a run_status_changed event."""
    new_status = RunStatus(payload["new_status"])

    # Idempotency: skip if already at target status
    if run.status == new_status:
        return

    run.status = new_status

    if new_status == RunStatus.ACTIVE:
        if run.started_at is None:
            run.started_at = timestamp
        # Clear pause state whenever transitioning to ACTIVE (covers both start and resume)
        run.pause_reason = None
        run.last_error = None
    elif new_status == RunStatus.PAUSED:
        # Apply pause metadata from enriched events (default to None for old events)
        run.pause_reason = payload.get("pause_reason")
        run.last_error = payload.get("last_error")
    elif new_status in (RunStatus.COMPLETED, RunStatus.FAILED):
        run.completed_at = timestamp
        run.pause_reason = None
        run.last_error = None


def _apply_step_completed(run: Run, payload: dict[str, Any]) -> None:
    """Apply a step_completed event."""
    step_index = payload.get("step_index")
    step_id = payload.get("step_id", "")

    # Find by index first, fall back to id
    if step_index is not None and 0 <= step_index < len(run.steps):
        step = run.steps[int(step_index)]
    else:
        step = None
        for s in run.steps:
            if s.id == step_id:
                step = s
                break

    if step is None:
        return

    # Idempotency: skip if step already completed
    if step.completed:
        return

    step.completed = True

    # Advance current_step_index past completed steps (only for index-based lookup)
    if step_index is not None:
        while (
            run.current_step_index < len(run.steps) - 1
            and run.steps[run.current_step_index].completed
        ):
            run.current_step_index += 1


def _apply_step_skipped(run: Run, payload: dict[str, Any]) -> None:
    """Apply a step_skipped event — mark step as skipped with skip_reason."""
    step_index = payload.get("step_index")
    step_id = payload.get("step_id", "")

    # Find by index first, fall back to id
    if step_index is not None and 0 <= step_index < len(run.steps):
        step = run.steps[int(step_index)]
    else:
        step = None
        for s in run.steps:
            if s.id == step_id:
                step = s
                break

    if step is None:
        return

    # Idempotency: skip if step already marked as skipped with same reason
    # Prefer skip_reason field; fall back to legacy reason field for old events
    skip_reason = payload.get("skip_reason") or payload.get("reason")
    if step.skipped and step.skip_reason == skip_reason:
        return

    step.skipped = True
    step.completed = True
    step.skip_reason = skip_reason

    # Advance current_step_index past skipped steps
    if step_index is not None:
        while (
            run.current_step_index < len(run.steps) - 1
            and run.steps[run.current_step_index].completed
        ):
            run.current_step_index += 1


def _apply_task_status_changed(run: Run, payload: dict[str, Any], timestamp: datetime) -> None:
    """Apply a task_status_changed event."""
    task_id = payload["task_id"]
    new_status = TaskStatus(payload["new_status"])

    _step, task = _find_task(run, task_id)
    if task is None:
        return

    # Idempotency: skip if already at target status
    if task.status == new_status:
        if new_status == TaskStatus.BUILDING:
            # Only skip if we already have the expected attempt
            expected_attempt = task.current_attempt
            if expected_attempt > 0 and len(task.attempts) >= expected_attempt:
                return
        else:
            return

    task.status = new_status
    if new_status == TaskStatus.BUILDING:
        task.current_attempt += 1
        task.attempts.append(
            Attempt(
                attempt_num=task.current_attempt,
                started_at=timestamp,
            )
        )
        # Apply start_commit from enriched events (None for old events without this field)
        start_commit = payload.get("start_commit")
        if start_commit and task.attempts:
            task.attempts[-1].start_commit = start_commit
    elif (
        new_status
        in (
            TaskStatus.VERIFYING,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
        )
        and task.attempts
    ):
        task.attempts[-1].completed_at = timestamp
        if new_status == TaskStatus.COMPLETED:
            task.attempts[-1].outcome = "passed"
        elif new_status == TaskStatus.FAILED:
            task.attempts[-1].outcome = "failed"
        # Apply end_commit from enriched events (VERIFYING = after builder done)
        end_commit = payload.get("end_commit")
        if end_commit and new_status == TaskStatus.VERIFYING:
            task.attempts[-1].end_commit = end_commit


def _apply_grades_evaluated(run: Run, payload: dict[str, Any]) -> None:
    """Apply a grades_evaluated event — snapshot grades onto the current attempt."""
    task_id = payload.get("task_id", "")
    grade_details = payload.get("grade_details", [])
    if not grade_details:
        return

    _step, task = _find_task(run, task_id)
    if task is None or not task.attempts:
        return

    # Idempotency: skip if attempt already has same grade snapshot content
    new_snapshot = [
        GradeSnapshotItem(
            req_id=d.get("req_id", ""),
            grade=d.get("grade"),
            grade_reason=d.get("grade_reason"),
        )
        for d in grade_details
    ]
    existing = task.attempts[-1].grade_snapshot
    if len(existing) == len(new_snapshot) and all(
        e.req_id == n.req_id and e.grade == n.grade and e.grade_reason == n.grade_reason
        for e, n in zip(existing, new_snapshot)
    ):
        return

    task.attempts[-1].grade_snapshot = new_snapshot


def _apply_agent_error(run: Run, payload: dict[str, Any]) -> None:
    """Apply an agent_error event — store error on the current attempt."""
    task_id = payload.get("task_id", "")
    error_message = payload.get("error_message", "")
    if not task_id or not error_message:
        return

    _step, task = _find_task(run, task_id)
    if task is None or not task.attempts:
        return

    # Idempotency: skip if attempt already has this error
    if task.attempts[-1].error == error_message:
        return

    task.attempts[-1].error = error_message


def _apply_auto_verify_completed(run: Run, payload: dict[str, Any]) -> None:
    """Apply an auto_verify_completed event — store results on the current attempt."""
    task_id = payload.get("task_id", "")
    results = payload.get("results", [])

    _step, task = _find_task(run, task_id)
    if task is None or not task.attempts:
        return

    # Idempotency: skip if attempt already has auto_verify_results
    if task.attempts[-1].auto_verify_results:
        return

    task.attempts[-1].auto_verify_results = results


def _apply_clarification_requested(run: Run, payload: dict[str, Any]) -> None:
    """Apply a clarification_requested event."""
    task_id = payload.get("task_id", "")
    request_id = payload.get("request_id", "")

    _step, task = _find_task(run, task_id)
    if task is None:
        return

    # Idempotency: skip if already set to same values
    if task.pending_action_type == "clarification" and task.pending_clarification_id == request_id:
        return

    task.pending_action_type = "clarification"
    task.pending_clarification_id = request_id


def _apply_clarification_responded(run: Run, payload: dict[str, Any]) -> None:
    """Apply a clarification_responded event — clear pending clarification."""
    task_id = payload.get("task_id", "")

    _step, task = _find_task(run, task_id)
    if task is None:
        return

    # Idempotency: skip if already cleared
    if task.pending_action_type is None and task.pending_clarification_id is None:
        return

    task.pending_action_type = None
    task.pending_clarification_id = None


def _apply_approval_requested(run: Run, payload: dict[str, Any]) -> None:
    """Apply an approval_requested event — set step's human_approval to pending."""
    step_id = payload.get("step_id", "")

    for step in run.steps:
        if step.id == step_id:
            # Idempotency: skip if already pending
            if step.human_approval is not None:
                return

            # Store pending state using a minimal HumanApproval placeholder.
            # HumanApproval requires approved_by/approved_at but for pending
            # we use sentinel values since the model doesn't have a separate
            # pending type.
            step.human_approval = None  # Will be set by approval_decision
            # We need a way to mark "pending". Since HumanApproval doesn't have
            # a status field, we track this via the absence of a decision.
            # The task spec says to set human_approval to a dict, but the model
            # uses HumanApproval. We leave it as None (pending state is implicit
            # when approval_requested has been seen but approval_decision hasn't).
            return


def _apply_approval_decision(run: Run, payload: dict[str, Any], timestamp: datetime) -> None:
    """Apply an approval_decision event — record the decision on the step."""
    step_id = payload.get("step_id", "")
    approved = payload.get("approved", False)
    comment = payload.get("comment")
    decided_by = payload.get("decided_by", "")

    for step in run.steps:
        if step.id == step_id:
            # Idempotency: skip if already has same decision
            if step.human_approval is not None and step.human_approval.approved_by == decided_by:
                return

            if approved:
                step.human_approval = HumanApproval(
                    approved_by=decided_by,
                    approved_at=timestamp,
                    comment=comment,
                )
            else:
                # Rejection: clear human_approval (step not approved)
                step.human_approval = None
            return


def _apply_run_step_backward(run: Run, payload: dict[str, Any]) -> None:
    """Apply a run_step_backward event — move current_step_index backward."""
    to_step_index = payload.get("to_step_index", 0)

    # Idempotency: skip if already at target index and steps after are not completed
    if run.current_step_index == to_step_index:
        already_clear = all(not step.completed for step in run.steps[to_step_index + 1 :])
        if already_clear:
            return

    run.current_step_index = to_step_index

    # Mark steps after to_step_index as not completed
    for i in range(to_step_index + 1, len(run.steps)):
        run.steps[i].completed = False


def _apply_task_reverted(run: Run, payload: dict[str, Any]) -> None:
    """Apply a task_reverted event — revert task status to PENDING."""
    task_id = payload.get("task_id", "")

    _step, task = _find_task(run, task_id)
    if task is None:
        return

    # Idempotency: skip if already pending
    if task.status == TaskStatus.PENDING:
        return

    task.status = TaskStatus.PENDING
