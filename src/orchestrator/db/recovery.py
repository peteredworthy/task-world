"""Event replay for crash recovery.

Reconstructs Run state by replaying persisted events in order.
"""

from datetime import datetime
from typing import Any

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.state.models import Attempt, GradeSnapshotItem, Run


def replay_events(run: Run, events: list[dict[str, Any]]) -> Run:
    """Replay events onto a Run to reconstruct its state.

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
        elif event_type == "grades_evaluated":
            _apply_grades_evaluated(run, payload)
        elif event_type == "checklist_gate_evaluated":
            # Informational — actual state changes come from status events
            pass
        elif event_type == "agent_output":
            # Informational — output is persisted on the attempt directly
            pass
        elif event_type == "agent_error":
            _apply_agent_error(run, payload)

    return run


def _apply_run_status_changed(run: Run, payload: dict[str, Any], timestamp: datetime) -> None:
    """Apply a run_status_changed event."""
    new_status = RunStatus(payload["new_status"])
    run.status = new_status

    if new_status == RunStatus.ACTIVE and run.started_at is None:
        run.started_at = timestamp
    elif new_status in (RunStatus.COMPLETED, RunStatus.FAILED):
        run.completed_at = timestamp


def _apply_step_completed(run: Run, payload: dict[str, Any]) -> None:
    """Apply a step_completed event."""
    step_index = payload.get("step_index")
    step_id = payload.get("step_id", "")

    # Find by index first, fall back to id
    if step_index is not None and 0 <= step_index < len(run.steps):
        run.steps[step_index].completed = True
        # Advance current_step_index past completed steps
        while (
            run.current_step_index < len(run.steps) - 1
            and run.steps[run.current_step_index].completed
        ):
            run.current_step_index += 1
    else:
        for step in run.steps:
            if step.id == step_id:
                step.completed = True
                break


def _apply_task_status_changed(run: Run, payload: dict[str, Any], timestamp: datetime) -> None:
    """Apply a task_status_changed event."""
    task_id = payload["task_id"]
    new_status = TaskStatus(payload["new_status"])

    for step in run.steps:
        for task in step.tasks:
            if task.id == task_id:
                task.status = new_status
                if new_status == TaskStatus.BUILDING:
                    task.current_attempt += 1
                    task.attempts.append(
                        Attempt(
                            attempt_num=task.current_attempt,
                            started_at=timestamp,
                        )
                    )
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
                return


def _apply_grades_evaluated(run: Run, payload: dict[str, Any]) -> None:
    """Apply a grades_evaluated event — snapshot grades onto the current attempt."""
    task_id = payload.get("task_id", "")
    grade_details = payload.get("grade_details", [])
    if not grade_details:
        return

    for step in run.steps:
        for task in step.tasks:
            if task.id == task_id and task.attempts:
                task.attempts[-1].grade_snapshot = [
                    GradeSnapshotItem(
                        req_id=d.get("req_id", ""),
                        grade=d.get("grade"),
                        grade_reason=d.get("grade_reason"),
                    )
                    for d in grade_details
                ]
                return


def _apply_agent_error(run: Run, payload: dict[str, Any]) -> None:
    """Apply an agent_error event — store error on the current attempt."""
    task_id = payload.get("task_id", "")
    error_message = payload.get("error_message", "")
    if not task_id or not error_message:
        return

    for step in run.steps:
        for task in step.tasks:
            if task.id == task_id and task.attempts:
                task.attempts[-1].error = error_message
                return
