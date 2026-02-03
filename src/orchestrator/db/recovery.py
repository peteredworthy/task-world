"""Event replay for crash recovery.

Reconstructs Run state by replaying persisted events in order.
"""

from datetime import datetime
from typing import Any

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.state.models import Run


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
            _apply_task_status_changed(run, payload)
        elif event_type in ("checklist_gate_evaluated", "grades_evaluated"):
            # Informational events — actual state changes come from status events
            pass

    return run


def _apply_run_status_changed(run: Run, payload: dict[str, Any], timestamp: datetime) -> None:
    """Apply a run_status_changed event."""
    new_status = RunStatus(payload["new_status"])
    run.status = new_status

    if new_status == RunStatus.ACTIVE and run.started_at is None:
        run.started_at = timestamp


def _apply_task_status_changed(run: Run, payload: dict[str, Any]) -> None:
    """Apply a task_status_changed event."""
    task_id = payload["task_id"]
    new_status = TaskStatus(payload["new_status"])

    for step in run.steps:
        for task in step.tasks:
            if task.id == task_id:
                task.status = new_status
                # Increment current_attempt each time task transitions to BUILDING
                if new_status == TaskStatus.BUILDING:
                    task.current_attempt += 1
                return
