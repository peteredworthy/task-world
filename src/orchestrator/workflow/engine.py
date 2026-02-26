"""Workflow engine orchestrating task execution through the state machine."""

from datetime import datetime, timezone
from typing import Any, Protocol

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.state.models import Run
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow.errors import GateBlockedError, InvalidTransitionError
from orchestrator.workflow.locks import LockManager, TaskLockedError
from orchestrator.workflow.events import (
    ChecklistGateEvaluated,
    GradeDetail,
    GradesEvaluated,
    RunStepBackward,
    RunStatusChanged,
    StepCompleted,
    TaskStatusChanged,
    WorkflowEvent,
)
from orchestrator.workflow.transitions import (
    TransitionResult,
    check_run_completion,
    check_step_progression,
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

    # Sensitive keys that should be excluded from agent_settings snapshot
    _SENSITIVE_KEYS = {"api_key", "api_token", "password", "secret", "auth_token"}

    def __init__(
        self,
        state_manager: SessionStateManager,
        clock: Clock | None = None,
        emitter: EventEmitter | None = None,
        lock_manager: LockManager | None = None,
    ) -> None:
        self._state = state_manager
        self._clock: Clock = clock or DefaultClock()
        self._emitter: EventEmitter = emitter or NoOpEmitter()
        self._lock_manager = lock_manager

    def _extract_model(self, agent_config: dict[str, Any]) -> str | None:
        """Extract model name from agent config.

        Args:
            agent_config: The agent configuration dict

        Returns:
            The model name if present, None otherwise
        """
        return agent_config.get("model")

    def _sanitize_agent_config(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        """Sanitize agent config by removing sensitive keys.

        Creates a copy with settings like model, temperature, max_tokens, nudge settings,
        but excludes API keys, tokens, passwords, and other secrets.

        Args:
            agent_config: The agent configuration dict

        Returns:
            A sanitized copy of the config without sensitive keys
        """
        sanitized: dict[str, Any] = {}
        for key, value in agent_config.items():
            # Skip sensitive keys (check case-insensitive)
            if any(sensitive in key.lower() for sensitive in self._SENSITIVE_KEYS):
                continue
            sanitized[key] = value

        return sanitized

    def cancel_run(self, run_id: str, reason: str | None = None) -> Run:
        """Cancel a run - move from ACTIVE/PAUSED to FAILED."""
        run = self._state.get_run(run_id)
        cancellable = (RunStatus.ACTIVE, RunStatus.PAUSED)
        if run.status not in cancellable:
            raise InvalidTransitionError(run.status.value, RunStatus.FAILED.value)

        old_status = run.status
        run.status = RunStatus.FAILED
        run.completed_at = self._clock.now()
        self._state.update_run(run)

        self._emitter.emit(
            RunStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="run_status_changed",
                old_status=old_status,
                new_status=RunStatus.FAILED,
            )
        )
        return run

    def start_run(self, run_id: str) -> Run:
        """Start a run - move from DRAFT to ACTIVE."""
        run = self._state.get_run(run_id)
        if run.status != RunStatus.DRAFT:
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

    def pause_run(self, run_id: str, reason: str = "manual_pause") -> Run:
        """Pause a run - move from ACTIVE to PAUSED. Idempotent if already PAUSED."""
        run = self._state.get_run(run_id)
        if run.status == RunStatus.PAUSED:
            return run
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(run.status.value, RunStatus.PAUSED.value)

        old_status = run.status
        run.status = RunStatus.PAUSED
        run.pause_reason = reason
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
        run.pause_reason = None  # Clear pause reason on resume
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

    def start_task(self, run_id: str, task_id: str, agent_id: str = "default") -> TransitionResult:
        """Start building a task.

        When a lock_manager is configured, acquires a lock for the given
        agent_id before transitioning.  Raises TaskLockedError if the task
        is already locked by a different agent.
        """
        if self._lock_manager is not None:
            if not self._lock_manager.acquire(task_id, agent_id, self._clock.now()):
                # Find who currently holds the lock
                raise TaskLockedError(task_id, agent_id)

        run = self._state.get_run(run_id)

        # Find which step contains this task
        task_step_index = None
        for step_idx, step in enumerate(run.steps):
            for task in step.tasks:
                if task.id == task_id:
                    task_step_index = step_idx
                    break
            if task_step_index is not None:
                break

        # Reject if task belongs to a future step
        if task_step_index is not None and task_step_index > run.current_step_index:
            raise InvalidTransitionError(
                f"task {task_id} in step {task_step_index}",
                f"start (current step is {run.current_step_index})",
            )

        task = self._state.get_task(run_id, task_id)
        old_status = task.status

        result = transition_to_building(task, self._clock.now())

        if result.success:
            # Populate agent snapshot on the newly created attempt
            if task.attempts:
                attempt = task.attempts[-1]
                attempt.agent_type = run.agent_type
                attempt.agent_model = self._extract_model(run.agent_config)
                attempt.agent_settings = self._sanitize_agent_config(run.agent_config)

            self._state.update_run(run)
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
        """Submit task for verification (builder done).

        Raises:
            GateBlockedError: If the checklist gate does not pass.
        """
        task = self._state.get_task(run_id, task_id)
        old_status = task.status

        try:
            result = transition_to_verifying(task)
        except GateBlockedError as e:
            # Emit gate evaluation event for failed gate
            self._emitter.emit(
                ChecklistGateEvaluated(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="checklist_gate_evaluated",
                    task_id=task_id,
                    passed=False,
                    blocking_items=e.blocking_items,
                )
            )
            raise

        # Emit gate evaluation event for successful gate
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

    def complete_verification(
        self, run_id: str, task_id: str, agent_id: str = "default"
    ) -> TransitionResult:
        """Complete verification phase.

        After the task transition, checks whether the current step is now
        complete (all tasks terminal) and whether the entire run is done.
        When a lock_manager is configured, releases the lock on success.
        """
        run = self._state.get_run(run_id)
        task = self._state.get_task(run_id, task_id)
        old_status = task.status
        old_attempt_count = len(task.attempts)

        result = transition_after_verification(task, self._clock.now())

        # If a new attempt was created (revision), populate agent snapshot
        if result.success and len(task.attempts) > old_attempt_count:
            attempt = task.attempts[-1]
            attempt.agent_type = run.agent_type
            attempt.agent_model = self._extract_model(run.agent_config)
            attempt.agent_settings = self._sanitize_agent_config(run.agent_config)

        if result.grade_result is not None:
            self._emitter.emit(
                GradesEvaluated(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="grades_evaluated",
                    task_id=task_id,
                    passed=result.grade_result.passed,
                    failing_items=result.grade_result.failing_items,
                    grade_details=[
                        GradeDetail(
                            req_id=item.req_id,
                            grade=item.grade,
                            grade_reason=item.grade_reason,
                        )
                        for item in task.checklist
                    ],
                )
            )

        if result.success:
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

            # --- Step and Run completion cascade ---
            prev_step_index = run.current_step_index
            step_changed = check_step_progression(run)

            if step_changed:
                # Emit StepCompleted for each newly completed step
                for i in range(prev_step_index, run.current_step_index + 1):
                    step = run.steps[i]
                    if step.completed:
                        self._emitter.emit(
                            StepCompleted(
                                timestamp=self._clock.now(),
                                run_id=run_id,
                                event_type="step_completed",
                                step_index=i,
                                step_id=step.id,
                            )
                        )

                # Check if the entire run is done
                old_run_status = run.status
                new_run_status = check_run_completion(run, self._clock.now())
                if new_run_status is not None:
                    self._emitter.emit(
                        RunStatusChanged(
                            timestamp=self._clock.now(),
                            run_id=run_id,
                            event_type="run_status_changed",
                            old_status=old_run_status,
                            new_status=new_run_status,
                        )
                    )

            self._state.update_run(run)

            # Release lock only on terminal states (COMPLETED, FAILED).
            # Revisions (back to BUILDING) keep the lock held.
            if self._lock_manager is not None and result.new_status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
            ):
                self._lock_manager.release(task_id, agent_id)

        return result

    def transition_backward(
        self, run_id: str, target_step_index: int, reason: str | None = None
    ) -> Run:
        """Transition backward to an earlier step.

        Args:
            run_id: The run ID
            target_step_index: The step index to transition to (must be < current_step_index)
            reason: Optional reason for the backward transition

        Returns:
            The updated run

        Raises:
            InvalidTransitionError: If target step is invalid or not before current step
        """
        run = self._state.get_run(run_id)

        # Validate target step index
        if target_step_index < 0 or target_step_index >= len(run.steps):
            raise InvalidTransitionError(
                f"step-{run.current_step_index}",
                f"step-{target_step_index} (out of bounds)",
            )

        if target_step_index >= run.current_step_index:
            raise InvalidTransitionError(
                f"step-{run.current_step_index}",
                f"step-{target_step_index} (must be before current)",
            )

        from_step_index = run.current_step_index

        # Reset tasks in skipped steps (from target to previous current) to PENDING
        for step_idx in range(target_step_index, from_step_index + 1):
            if step_idx < len(run.steps):
                step = run.steps[step_idx]
                step.completed = False
                for task in step.tasks:
                    if task.status != TaskStatus.COMPLETED:
                        task.status = TaskStatus.PENDING

        # Set current step index to target
        run.current_step_index = target_step_index
        self._state.update_run(run)

        self._emitter.emit(
            RunStepBackward(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="run_step_backward",
                from_step_index=from_step_index,
                to_step_index=target_step_index,
                reason=reason,
            )
        )

        return run
