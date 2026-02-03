"""Workflow engine orchestrating task execution through the state machine."""

from datetime import datetime, timezone
from typing import Protocol

from orchestrator.config.enums import RunStatus
from orchestrator.state.models import Run
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow.errors import InvalidTransitionError
from orchestrator.workflow.events import (
    ChecklistGateEvaluated,
    GradesEvaluated,
    RunStatusChanged,
    TaskStatusChanged,
    WorkflowEvent,
)
from orchestrator.workflow.transitions import (
    TransitionResult,
    transition_after_verification,
    transition_to_building,
    transition_to_verifying,
)


class Clock(Protocol):
    """Protocol for injectable clock."""

    def now(self) -> datetime: ...


class EventEmitter(Protocol):
    """Protocol for injectable event emitter."""

    def emit(self, event: WorkflowEvent) -> None: ...


class DefaultClock:
    """Default clock using UTC time."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class NoOpEmitter:
    """Event emitter that does nothing."""

    def emit(self, event: WorkflowEvent) -> None:
        pass


class WorkflowEngine:
    """Orchestrates task execution through the state machine.

    The engine coordinates state transitions but does not execute agent calls.
    All state lives in the SessionStateManager.
    """

    def __init__(
        self,
        state_manager: SessionStateManager,
        clock: Clock | None = None,
        emitter: EventEmitter | None = None,
    ) -> None:
        self._state = state_manager
        self._clock: Clock = clock or DefaultClock()
        self._emitter: EventEmitter = emitter or NoOpEmitter()

    def start_run(self, run_id: str) -> Run:
        """Start a run - move from DRAFT/QUEUED to ACTIVE."""
        run = self._state.get_run(run_id)
        if run.status not in (RunStatus.DRAFT, RunStatus.QUEUED):
            raise InvalidTransitionError(run.status.value, RunStatus.ACTIVE.value)

        old_status = run.status
        run.status = RunStatus.ACTIVE
        run.started_at = self._clock.now()
        self._state.update_run(run)

        self._emitter.emit(
            RunStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="run_status_changed",
                old_status=old_status,
                new_status=RunStatus.ACTIVE,
            )
        )
        return run

    def pause_run(self, run_id: str) -> Run:
        """Pause a run - move from ACTIVE to PAUSED."""
        run = self._state.get_run(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(run.status.value, RunStatus.PAUSED.value)

        old_status = run.status
        run.status = RunStatus.PAUSED
        self._state.update_run(run)

        self._emitter.emit(
            RunStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="run_status_changed",
                old_status=old_status,
                new_status=RunStatus.PAUSED,
            )
        )
        return run

    def resume_run(self, run_id: str) -> Run:
        """Resume a run - move from PAUSED to ACTIVE."""
        run = self._state.get_run(run_id)
        if run.status != RunStatus.PAUSED:
            raise InvalidTransitionError(run.status.value, RunStatus.ACTIVE.value)

        old_status = run.status
        run.status = RunStatus.ACTIVE
        self._state.update_run(run)

        self._emitter.emit(
            RunStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="run_status_changed",
                old_status=old_status,
                new_status=RunStatus.ACTIVE,
            )
        )
        return run

    def start_task(self, run_id: str, task_id: str) -> TransitionResult:
        """Start building a task."""
        task = self._state.get_task(run_id, task_id)
        old_status = task.status

        result = transition_to_building(task, self._clock.now())

        if result.success:
            self._state.update_run(self._state.get_run(run_id))
            self._emitter.emit(
                TaskStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="task_status_changed",
                    task_id=task_id,
                    old_status=old_status,
                    new_status=result.new_status,
                )
            )
        return result

    def submit_for_verification(self, run_id: str, task_id: str) -> TransitionResult:
        """Submit task for verification (builder done)."""
        task = self._state.get_task(run_id, task_id)
        old_status = task.status

        result = transition_to_verifying(task)

        if result.gate_result is not None:
            self._emitter.emit(
                ChecklistGateEvaluated(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="checklist_gate_evaluated",
                    task_id=task_id,
                    passed=result.gate_result.passed,
                    blocking_items=result.gate_result.blocking_items,
                )
            )

        if result.success:
            self._state.update_run(self._state.get_run(run_id))
            self._emitter.emit(
                TaskStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="task_status_changed",
                    task_id=task_id,
                    old_status=old_status,
                    new_status=result.new_status,
                )
            )
        return result

    def complete_verification(self, run_id: str, task_id: str) -> TransitionResult:
        """Complete verification phase."""
        task = self._state.get_task(run_id, task_id)
        old_status = task.status

        result = transition_after_verification(task, self._clock.now())

        if result.grade_result is not None:
            self._emitter.emit(
                GradesEvaluated(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="grades_evaluated",
                    task_id=task_id,
                    passed=result.grade_result.passed,
                    failing_items=result.grade_result.failing_items,
                )
            )

        if result.success:
            self._state.update_run(self._state.get_run(run_id))
            self._emitter.emit(
                TaskStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="task_status_changed",
                    task_id=task_id,
                    old_status=old_status,
                    new_status=result.new_status,
                )
            )
        return result
