"""Workflow engine orchestrating task execution through the state machine."""

from datetime import datetime, timezone
from typing import Any, Protocol

from orchestrator.config.enums import ChecklistStatus, RunStatus, TaskStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.state.models import Run
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow.engine.errors import GateBlockedError, InvalidTransitionError
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
from orchestrator.workflow.engine.transitions import (
    TransitionResult,
    check_run_completion,
    check_step_progression,
    transition_after_verification,
    transition_force_accept,
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

    def stop_run(self, run_id: str) -> Run:
        """Begin graceful shutdown of a run - move from ACTIVE to STOPPING."""
        run = self._state.get_run(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(run.status.value, RunStatus.STOPPING.value)

        old_status = run.status
        run.status = RunStatus.STOPPING
        self._state.update_run(run)

        self._emitter.emit(
            RunStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="run_status_changed",
                old_status=old_status,
                new_status=RunStatus.STOPPING,
            )
        )
        return run

    def cancel_run(self, run_id: str, reason: str | None = None) -> Run:
        """Cancel a run - move from ACTIVE/PAUSED/STOPPING to FAILED."""
        run = self._state.get_run(run_id)
        cancellable = (RunStatus.ACTIVE, RunStatus.PAUSED, RunStatus.STOPPING)
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

    def pause_run(
        self,
        run_id: str,
        reason: str = "manual_pause",
        error_detail: str | None = None,
    ) -> Run:
        """Pause a run - move from ACTIVE/STOPPING to PAUSED. Idempotent if already PAUSED."""
        run = self._state.get_run(run_id)
        if run.status == RunStatus.PAUSED:
            return run
        if run.status not in (RunStatus.ACTIVE, RunStatus.STOPPING):
            raise InvalidTransitionError(run.status.value, RunStatus.PAUSED.value)

        old_status = run.status
        run.status = RunStatus.PAUSED
        run.pause_reason = reason
        run.last_error = error_detail
        self._state.update_run(run)

        self._emitter.emit(
            RunStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="run_status_changed",
                old_status=old_status,
                new_status=RunStatus.PAUSED,
                pause_reason=reason,
                last_error=error_detail,
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
        run.last_error = None  # Clear error detail on resume
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

    def escalate_requirement(
        self,
        run_id: str,
        task_id: str,
        req_id: str,
        reason: str,
    ) -> Run:
        """Flag a requirement as escalated and pause the run.

        Sets the requirement status to 'escalated' and pauses the run with
        pause_reason='requirement_escalated' so a human can modify/skip/resume.
        """
        run = self._state.get_run(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(
                run.status.value, "escalate_requirement (requires ACTIVE run)"
            )

        self._state.update_checklist_item(
            run_id, task_id, req_id, ChecklistStatus.ESCALATED, note=reason
        )

        old_status = run.status
        run.status = RunStatus.PAUSED
        run.pause_reason = "requirement_escalated"
        run.last_error = f"Requirement {req_id} escalated: {reason}"
        self._state.update_run(run)

        self._emitter.emit(
            RunStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="run_status_changed",
                old_status=old_status,
                new_status=RunStatus.PAUSED,
                pause_reason="requirement_escalated",
                last_error=f"Requirement {req_id} escalated: {reason}",
            )
        )
        return run

    def start_task(
        self,
        run_id: str,
        task_id: str,
        agent_id: str = "default",
        start_commit: str | None = None,
    ) -> TransitionResult:
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

        # Advance current_step_index past already-completed steps so the
        # engine stays in sync with executor._find_next_task() which does the
        # same skip.  This is needed after fan-out failures mark a step
        # completed + pause the run without advancing the index.
        effective_step_index = run.current_step_index
        while effective_step_index < len(run.steps) and run.steps[effective_step_index].completed:
            effective_step_index += 1
        if effective_step_index != run.current_step_index:
            run.current_step_index = effective_step_index

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
                    start_commit=start_commit,
                )
            )
        return result

    def submit_for_verification(
        self,
        run_id: str,
        task_id: str,
        end_commit: str | None = None,
    ) -> TransitionResult:
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
                    end_commit=end_commit,
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

            # Load routine config if available for condition evaluation
            routine_config = None
            if run.routine_embedded is not None:
                try:
                    routine_config = RoutineConfig.model_validate(run.routine_embedded)
                except Exception:
                    # If routine config can't be loaded, continue without condition evaluation
                    pass

            step_changed = check_step_progression(
                run,
                routine_config=routine_config,
                clock=self._clock,
                emitter=self._emitter,
                worktree_path=None,  # Engine doesn't have worktree path
                run_config=run.config,
            )

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

    def force_accept(self, run_id: str, task_id: str) -> TransitionResult:
        """Override failed verification and mark task as COMPLETED.

        Bypasses grade evaluation. Handles step/run completion cascade.
        """
        run = self._state.get_run(run_id)
        task = self._state.get_task(run_id, task_id)
        old_status = task.status

        result = transition_force_accept(task, self._clock.now())
        if not result.success:
            return result

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

        prev_step_index = run.current_step_index
        routine_config = None
        if run.routine_embedded is not None:
            try:
                routine_config = RoutineConfig.model_validate(run.routine_embedded)
            except Exception:
                pass

        # If the run is already FAILED (because this task's failure triggered fail-fast),
        # temporarily restore ACTIVE so check_step_progression and check_run_completion
        # can re-evaluate correctly. check_run_completion will set it back to FAILED if
        # other failures remain, or leave it ACTIVE so the run can continue.
        old_run_status = run.status
        reactivated = False
        if run.status == RunStatus.FAILED:
            run.status = RunStatus.ACTIVE
            run.completed_at = None
            reactivated = True

        step_changed = check_step_progression(
            run,
            routine_config=routine_config,
            clock=self._clock,
            emitter=self._emitter,
            worktree_path=None,
            run_config=run.config,
        )

        if step_changed:
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
        elif reactivated and run.status == RunStatus.ACTIVE:
            # Run was re-activated and has more steps to go — emit the status change
            self._emitter.emit(
                RunStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="run_status_changed",
                    old_status=old_run_status,
                    new_status=RunStatus.ACTIVE,
                )
            )

        self._state.update_run(run)
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
