"""Async workflow service wiring WorkflowEngine to persistent storage."""

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.schemas.runs import RecoverResponse
from orchestrator.config.enums import AgentType, ChecklistStatus, GateType, RunStatus, TaskStatus
from orchestrator.config.global_config import GlobalConfig
from orchestrator.config.models import AutoVerifyConfig, RoutineConfig, TaskConfig
from orchestrator.db.event_store import EventStore
from orchestrator.db.repositories import RunRepository
from orchestrator.state.models import Attempt, ChecklistItem, Run, StepState, TaskState
from orchestrator.state.session import SessionStateManager
from orchestrator.state.errors import RunNotFoundError, TaskNotFoundError
from orchestrator.workflow.auto_verify import (
    AutoVerifyRunner,
    evaluate_auto_verify,
    has_crashes,
    run_auto_verify,
)
from orchestrator.workflow.clarifications import (
    ClarificationAnswer,
    ClarificationQuestion,
    ClarificationRequest,
    ClarificationResponse,
    build_artifact_header,
    format_clarification_artifact,
    resolve_artifact_path,
)
from orchestrator.workflow.engine import Clock, WorkflowEngine
from orchestrator.workflow.prompts import generate_builder_prompt, generate_recovery_prompt
from orchestrator.workflow.errors import GateBlockedError, InvalidTransitionError
from orchestrator.workflow.event_logger import PersistentEventEmitter
from orchestrator.workflow.events import (
    AgentChangedEvent,
    ApprovalDecision,
    AutoVerifyCompleted,
    BufferingEmitter,
    ClarificationRequested,
    ClarificationResponded,
    RunStatusChanged,
    TaskReverted,
    TaskStatusChanged,
)
from orchestrator.workflow.locks import LockManager
from orchestrator.workflow.transitions import (
    TransitionResult,
    transition_from_approval,
    transition_from_clarification,
    transition_to_building,
    transition_to_pending_clarification,
    transition_to_recovering,
)
from orchestrator.workflow.completion import handle_run_completion
from orchestrator.git.worktree import WorktreeManager
from orchestrator.git.utils import commit_uncommitted_changes, get_head_commit
from orchestrator.envfiles.lifecycle import EnvFileLifecycle


class SubmitEventRegistry:
    """Shared registry of asyncio.Events for submit notifications.

    This must be a singleton per application so that all WorkflowService
    instances (one per request) share the same events.  A UserManagedAgent
    registers an event here; when *any* WorkflowService instance calls
    ``submit_for_verification``, it notifies through this registry.
    """

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    def register(self, task_id: str) -> asyncio.Event:
        """Register and return an event for *task_id*."""
        event = asyncio.Event()
        self._events[task_id] = event
        return event

    def unregister(self, task_id: str) -> None:
        """Remove a previously registered event."""
        self._events.pop(task_id, None)

    def notify(self, task_id: str) -> None:
        """Set the event for *task_id*, if one is registered."""
        event = self._events.get(task_id)
        if event is not None:
            event.set()


def find_task_config(
    routine_config: RoutineConfig, config_id: str, step_config_id: str | None = None
) -> TaskConfig | None:
    """Find a TaskConfig by config_id within a RoutineConfig. Pure function.

    Args:
        routine_config: The routine configuration to search
        config_id: The task config ID to find (e.g., "T-02")
        step_config_id: Optional step config ID to limit search to a specific step

    Returns:
        The matching TaskConfig, or None if not found
    """
    for step in routine_config.steps:
        # If step_config_id is provided, only search within that step
        if step_config_id is not None and step.id != step_config_id:
            continue
        for task in step.tasks:
            if task.id == config_id:
                return task
    return None


def resolve_auto_verify_config(
    run: Run, task_config_id: str, step_config_id: str | None = None
) -> AutoVerifyConfig | None:
    """Resolve the AutoVerifyConfig for a task from the run's routine_embedded.

    Args:
        run: The run containing the routine configuration
        task_config_id: The task config ID (e.g., "T-02")
        step_config_id: Optional step config ID to limit search to a specific step

    Returns:
        The AutoVerifyConfig for the task, or None if not found or empty
    """
    if run.routine_embedded is None:
        return None
    routine_config = RoutineConfig.model_validate(run.routine_embedded)
    task_config = find_task_config(routine_config, task_config_id, step_config_id)
    if task_config is None:
        return None
    if not task_config.auto_verify.items:
        return None
    return task_config.auto_verify


def _resolve_working_path(run: Run) -> Path | None:
    """Resolve the working directory for auto-verify commands from the run.

    Uses worktree_path if available. Returns None if not set or not a valid directory.
    """
    if run.worktree_path:
        p = Path(run.worktree_path)
        if p.is_dir():
            return p
    return None


class _ServiceClock:
    """Clock for WorkflowService that returns UTC now."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class WorkflowService:
    """Async service that bridges WorkflowEngine (sync) with persistent storage.

    Pattern for each mutation:
    1. Load Run from RunRepository into a temporary SessionStateManager
    2. Create BufferingEmitter, create WorkflowEngine(state, clock, emitter)
    3. Call engine method (sync)
    4. repo.save() (flushes state)
    5. event_emitter.emit_batch(buffered_events) (flushes events)
    6. session.commit() (atomic)
    """

    def __init__(
        self,
        session: AsyncSession,
        repo: RunRepository | None = None,
        event_store: EventStore | None = None,
        event_emitter: PersistentEventEmitter | None = None,
        submit_event_registry: SubmitEventRegistry | None = None,
        clock: Clock | None = None,
        auto_verify_runner: AutoVerifyRunner | None = None,
        lock_manager: LockManager | None = None,
        global_config: GlobalConfig | None = None,
        env_lifecycle: EnvFileLifecycle | None = None,
    ) -> None:
        self._session = session
        self._repo = repo or RunRepository(session)
        self._event_store = event_store or EventStore(session)
        self._event_emitter = event_emitter or PersistentEventEmitter(self._event_store)
        self._clock = clock or _ServiceClock()
        self._submit_registry = submit_event_registry or SubmitEventRegistry()
        self._auto_verify_runner = auto_verify_runner
        self._lock_manager = lock_manager
        self._global_config = global_config
        self._env_lifecycle = env_lifecycle

    def _build_engine(
        self, run: Run
    ) -> tuple[WorkflowEngine, SessionStateManager, BufferingEmitter]:
        """Create an engine with a temporary in-memory state manager and buffering emitter."""
        state = SessionStateManager()
        state.add_run(run)
        buffer = BufferingEmitter()
        engine = WorkflowEngine(
            state, clock=self._clock, emitter=buffer, lock_manager=self._lock_manager
        )
        return engine, state, buffer

    async def _persist(
        self, state: SessionStateManager, run_id: str, buffer: BufferingEmitter
    ) -> Run:
        """Save state and events, then commit."""
        run = state.get_run(run_id)
        await self._repo.save(run)
        events = buffer.drain()
        await self._event_emitter.emit_batch(events)
        await self._session.commit()
        return run

    def _sanitize_agent_config(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        """Sanitize agent config by removing sensitive keys.

        Creates a copy with settings like model, temperature, max_tokens, nudge settings,
        but excludes API keys, tokens, passwords, and other secrets.

        Args:
            agent_config: The agent configuration dict

        Returns:
            A sanitized copy of the config without sensitive keys
        """
        sensitive_keys = {"api_key", "api_token", "password", "secret", "auth_token"}
        sanitized: dict[str, Any] = {}
        for key, value in agent_config.items():
            # Skip sensitive keys (check case-insensitive)
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                continue
            sanitized[key] = value
        return sanitized

    def _create_worktree_manager(self, run: Run) -> WorktreeManager | None:
        """Create a WorktreeManager for a specific run's repository.

        Args:
            run: The run to create a worktree manager for

        Returns:
            WorktreeManager instance or None if global_config is not available
        """
        if self._global_config is None:
            return None

        repos_dir = self._global_config.paths.get_repos_path()
        worktrees_dir = self._global_config.paths.get_worktrees_path()
        repo_path = repos_dir / run.repo_name

        if not repo_path.is_dir():
            return None

        return WorktreeManager(repo_path, worktrees_dir)

    # --- Delegating to WorkflowEngine ---

    async def cancel_run(self, run_id: str, reason: str | None = None) -> Run:
        """Cancel a run (ACTIVE/PAUSED -> FAILED).

        Handles worktree cleanup if the run has a worktree configured.
        """
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        engine.cancel_run(run_id, reason)

        # Get the updated run after engine processing
        updated_run = state.get_run(run_id)

        result = await self._persist(state, run_id, buffer)

        # Call env_lifecycle hook for run_end if run was cancelled
        if (
            self._env_lifecycle is not None
            and updated_run.status == RunStatus.FAILED
            and updated_run.worktree_path
            and updated_run.env_file_specs
        ):
            worktree_path = Path(updated_run.worktree_path)
            await self._env_lifecycle.on_run_end(
                run_id=run_id,
                repo_name=updated_run.repo_name,
                worktree_path=worktree_path,
                success=False,
            )

        # Handle completion actions for cancelled (FAILED) runs
        if updated_run.status == RunStatus.FAILED:
            worktree_manager = self._create_worktree_manager(updated_run)
            if worktree_manager is not None:
                handle_run_completion(updated_run, worktree_manager)

        return result

    async def start_run(self, run_id: str) -> Run:
        """Start a run (DRAFT -> ACTIVE).

        Note: This only changes the run status. For managed agents (CLI, OpenHands),
        the agent must be spawned separately. For user-managed agents, an external
        agent must poll the API.
        """
        import logging

        logger = logging.getLogger(__name__)

        run = await self._repo.get(run_id)
        logger.info(
            f"Starting run {run_id}: agent_type={run.agent_type}, "
            f"repo={run.repo_name}, routine={run.routine_id}"
        )

        engine, state, buffer = self._build_engine(run)
        engine.start_run(run_id)

        # Note: worktree creation is now handled by the caller (API layer)
        # who has access to the repos_dir configuration
        result = await self._persist(state, run_id, buffer)

        # Call env_lifecycle hook if configured and worktree is available
        if self._env_lifecycle is not None and result.worktree_path and result.env_file_specs:
            worktree_path = Path(result.worktree_path)
            source_dir = Path(result.env_source_dir) if result.env_source_dir else None
            await self._env_lifecycle.on_run_start(
                run_id=run_id,
                repo_name=result.repo_name,
                worktree_path=worktree_path,
                env_specs=result.env_file_specs,
                source_dir=source_dir,
            )

        # Warn if using a managed agent that requires spawning
        if run.agent_type in (
            AgentType.CLI_SUBPROCESS,
            AgentType.OPENHANDS_LOCAL,
            AgentType.OPENHANDS_DOCKER,
        ):
            agent_type_str = run.agent_type.value if run.agent_type else "unknown"
            logger.warning(
                f"Run {run_id} started with managed agent {agent_type_str}. "
                f"Agent must be spawned separately (via CLI or agent launcher). "
                f"Run will remain ACTIVE with no progress until agent connects."
            )

        return result

    async def pause_run(
        self,
        run_id: str,
        reason: str = "manual_pause",
        error_detail: str | None = None,
    ) -> Run:
        """Pause a run (ACTIVE -> PAUSED)."""
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        engine.pause_run(run_id, reason=reason, error_detail=error_detail)
        return await self._persist(state, run_id, buffer)

    async def resume_run(
        self,
        run_id: str,
        agent_type: AgentType | None = None,
        agent_config: dict[str, object] | None = None,
        resume_strategy: str | None = None,
    ) -> Run:
        """Resume a run (PAUSED -> ACTIVE), optionally changing the agent.

        Args:
            run_id: The run ID
            agent_type: Optional new agent type to use
            agent_config: Optional new agent config to use
            resume_strategy: "continue" (default) or "revert" to reset current phase

        Returns:
            The updated run
        """
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)

        # Apply revert strategy if requested
        if resume_strategy == "revert":
            for step in run.steps:
                for task in step.tasks:
                    if task.status in (TaskStatus.BUILDING, TaskStatus.VERIFYING):
                        reverted_from = task.status
                        self._revert_task_to_phase_start(task, run, self._clock.now())
                        buffer.emit(
                            TaskReverted(
                                timestamp=self._clock.now(),
                                run_id=run_id,
                                event_type="task_reverted",
                                task_id=task.id,
                                reverted_from_status=reverted_from,
                            )
                        )
                        break  # Only revert the first active task
                else:
                    continue
                break

            # Update the run in the state manager after revert
            state.update_run(run)

        # If agent is being changed (type or config), emit AgentChangedEvent and update run
        if agent_type is not None or agent_config is not None:
            old_agent = run.agent_type
            old_config = run.agent_config or {}

            # Determine new agent type: use provided type or keep existing
            new_agent = agent_type if agent_type is not None else old_agent
            new_config = agent_config if agent_config is not None else old_config

            # Update the run's agent configuration
            run.agent_type = new_agent
            run.agent_config = new_config

            # Emit the agent change event only if either type or config actually changed
            # Only emit if new_agent is not None (required by AgentChangedEvent)
            if (old_agent != new_agent or old_config != new_config) and new_agent is not None:
                buffer.emit(
                    AgentChangedEvent(
                        timestamp=self._clock.now(),
                        run_id=run_id,
                        event_type="agent_changed",
                        old_agent=old_agent or AgentType.CLI_SUBPROCESS,
                        new_agent=new_agent,
                        old_agent_config=old_config,
                        new_agent_config=new_config,
                        reason="user_changed_on_resume",
                    )
                )

            # Update the run in the state manager
            state.update_run(run)

        # Resume the run (PAUSED -> ACTIVE)
        engine.resume_run(run_id)
        return await self._persist(state, run_id, buffer)

    async def recover_run(
        self,
        run_id: str,
        target_task_id: str,
        additional_attempts: int = 1,
        agent_type: AgentType | None = None,
        agent_config: dict[str, object] | None = None,
        preserve_checklist: bool = False,
    ) -> RecoverResponse:
        """Recover a run by rewinding to a target task and pausing.

        Allowed when the run is FAILED or PAUSED. A common scenario for PAUSED:
        a task fails, the run continues to the next task in the step, and the
        user pauses the run to jump back to the failed task instead of waiting
        for the full step to complete.

        Recovery semantics:
        - FAILED or PAUSED runs can be recovered (other statuses -> 409 conflict)
        - Target task is moved to BUILDING with an extra attempt budget
        - Downstream tasks are reset to PENDING with cleared attempts
        - Downstream checklist items are reset to OPEN by default
        - Run is transitioned to PAUSED with pause_reason="recovered"
        """
        run = await self._repo.get(run_id)
        if run.status not in (RunStatus.FAILED, RunStatus.PAUSED):
            raise InvalidTransitionError(run.status.value, RunStatus.PAUSED.value)

        if additional_attempts < 0:
            raise ValueError("additional_attempts must be >= 0")

        ordered_tasks: list[tuple[int, StepState, TaskState]] = []
        for step_index, step in enumerate(run.steps):
            for task in step.tasks:
                ordered_tasks.append((step_index, step, task))

        target_idx = -1
        target_step_index = -1
        target_step: StepState | None = None
        target_task: TaskState | None = None
        for idx, (step_index, step, task) in enumerate(ordered_tasks):
            if task.id == target_task_id:
                target_idx = idx
                target_step_index = step_index
                target_step = step
                target_task = task
                break

        if target_task is None or target_step is None:
            raise TaskNotFoundError(run_id, target_task_id)

        downstream = ordered_tasks[target_idx + 1 :]

        # Capture restore point from DB-recorded builder end_commit before mutation.
        restore_commit: str | None = None
        for attempt in reversed(target_task.attempts):
            if attempt.end_commit:
                restore_commit = attempt.end_commit
                break

        now = self._clock.now()

        # Reset target task to BUILDING with a fresh attempt and expanded budget.
        target_task.max_attempts += additional_attempts
        target_task.status = TaskStatus.BUILDING
        target_task.pending_action_type = None
        target_task.pending_clarification_id = None
        next_attempt_num = len(target_task.attempts) + 1
        target_task.current_attempt = next_attempt_num
        target_task.attempts.append(Attempt(attempt_num=next_attempt_num, started_at=now))
        if target_task.attempts:
            active_attempt = target_task.attempts[-1]
            active_attempt.agent_type = run.agent_type
            active_attempt.agent_model = run.agent_config.get("model")
            active_attempt.agent_settings = self._sanitize_agent_config(run.agent_config)

        # Reset all downstream tasks.
        for _, _, task in downstream:
            task.status = TaskStatus.PENDING
            task.pending_action_type = None
            task.pending_clarification_id = None
            task.current_attempt = 0
            task.attempts = []
            for item in task.checklist:
                item.grade = None
                item.grade_reason = None
                if not preserve_checklist:
                    item.status = ChecklistStatus.OPEN
                    item.note = None

        # Un-complete target step and all downstream steps.
        affected_steps = [target_step, *[step for _, step, _ in downstream]]
        seen_steps: set[str] = set()
        for step in affected_steps:
            if step.id in seen_steps:
                continue
            seen_steps.add(step.id)
            step.completed = False

        run.current_step_index = target_step_index
        run.status = RunStatus.PAUSED
        run.pause_reason = "recovered"
        run.completed_at = None
        run.updated_at = now

        if agent_type is not None:
            run.agent_type = agent_type
        if agent_config is not None:
            run.agent_config = agent_config

        # Restore worktree to target task's end_commit (or source branch head fallback).
        if run.worktree_path:
            restored = False
            if restore_commit:
                restored = self._checkout_commit(run.worktree_path, restore_commit)
            if not restored and run.source_branch:
                self._checkout_commit(run.worktree_path, run.source_branch)

        await self._repo.save(run)
        await self._session.commit()

        return RecoverResponse(
            run_id=run.id,
            status=run.status.value,
            pause_reason=run.pause_reason,
            current_step_index=run.current_step_index,
        )

    def _revert_task_to_phase_start(
        self,
        task: TaskState,
        run: Run,
        now: datetime,
    ) -> None:
        """Revert a task to the clean state at the start of its current phase.

        Closes the current attempt with outcome="reverted" and creates a fresh attempt.
        Resets checklist state based on the current phase (BUILDING or VERIFYING).
        """
        # Close out current attempt with outcome="reverted"
        if task.attempts:
            attempt = task.attempts[-1]
            attempt.completed_at = now
            attempt.outcome = "reverted"

        if task.status == TaskStatus.BUILDING:
            # Reset checklist items to OPEN (clear builder progress)
            for item in task.checklist:
                item.status = ChecklistStatus.OPEN
                item.note = None

            # Create fresh attempt and set status to BUILDING
            result = transition_to_building(task, now)
            if not result.success:
                raise ValueError(f"Failed to revert building task: {result.error}")

            # Populate agent snapshot on new attempt
            if task.attempts:
                attempt = task.attempts[-1]
                attempt.agent_type = run.agent_type
                attempt.agent_model = run.agent_config.get("model")
                attempt.agent_settings = self._sanitize_agent_config(run.agent_config)
                # Revert restores the worktree to the previous start_commit,
                # so the new attempt starts from the same point.
                if len(task.attempts) >= 2:
                    attempt.start_commit = task.attempts[-2].start_commit

            # Checkout start_commit in worktree if available
            if len(task.attempts) >= 2:
                prev_attempt = task.attempts[-2]
                if prev_attempt.start_commit and run.worktree_path:
                    self._checkout_commit(run.worktree_path, prev_attempt.start_commit)

        elif task.status == TaskStatus.VERIFYING:
            # Clear grades and grade_reasons (keep checklist status from builder)
            for item in task.checklist:
                item.grade = None
                item.grade_reason = None

            # Create fresh attempt for verifier
            new_attempt_num = task.current_attempt + 1
            task.attempts.append(Attempt(attempt_num=new_attempt_num, started_at=now))
            task.current_attempt = new_attempt_num

            # Populate agent snapshot
            if task.attempts:
                attempt = task.attempts[-1]
                attempt.agent_type = run.agent_type
                attempt.agent_model = run.agent_config.get("model")
                attempt.agent_settings = self._sanitize_agent_config(run.agent_config)

            # Checkout end_commit from builder attempt if available
            if len(task.attempts) >= 2:
                builder_attempt = task.attempts[-2]
                if builder_attempt.end_commit and run.worktree_path:
                    self._checkout_commit(run.worktree_path, builder_attempt.end_commit)

    def _checkout_commit(self, worktree_path: str, commit_sha: str) -> bool:
        """Checkout a git commit/ref in the worktree. Logs warning on failure."""
        import logging
        import subprocess

        checkout = subprocess.run(
            ["git", "checkout", commit_sha],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        if checkout.returncode != 0:
            logging.getLogger(__name__).warning(
                f"Failed to checkout commit {commit_sha} in {worktree_path}: "
                f"{checkout.stderr.strip()}"
            )
            return False
        return True

    async def transition_backward(
        self, run_id: str, target_step_index: int, reason: str | None = None
    ) -> Run:
        """Transition backward to an earlier step.

        Args:
            run_id: The run ID
            target_step_index: The step index to transition to (must be < current_step_index)
            reason: Optional reason for the backward transition

        Returns:
            The updated run
        """
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        engine.transition_backward(run_id, target_step_index, reason)
        return await self._persist(state, run_id, buffer)

    async def start_task(self, run_id: str, task_id: str) -> TransitionResult:
        """Start building a task (PENDING -> BUILDING)."""
        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(run.status.value, "start_task (requires ACTIVE run)")
        engine, state, buffer = self._build_engine(run)
        result = engine.start_task(run_id, task_id)

        # Capture start commit for git tracking
        if result.success and run.worktree_path:
            task = state.get_task(run_id, task_id)
            if task.attempts:
                worktree_path = Path(run.worktree_path)
                task.attempts[-1].start_commit = get_head_commit(worktree_path)

        await self._persist(state, run_id, buffer)

        # Call env_lifecycle hook if configured and worktree is available
        if (
            self._env_lifecycle is not None
            and result.success
            and run.worktree_path
            and run.env_file_specs
        ):
            worktree_path = Path(run.worktree_path)
            await self._env_lifecycle.on_task_start(
                run_id=run_id,
                task_id=task_id,
                worktree_path=worktree_path,
            )

        return result

    async def submit_for_verification(self, run_id: str, task_id: str) -> TransitionResult:
        """Submit task for verification (BUILDING -> VERIFYING).

        After the engine transitions to VERIFYING, runs auto-verify commands
        if configured in the run's routine_embedded. If any must-items fail,
        the task is transitioned back to BUILDING (revision) and the results
        are stored in the current attempt.

        Raises:
            GateBlockedError: If the checklist gate does not pass.
        """
        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(
                run.status.value, "submit_for_verification (requires ACTIVE run)"
            )
        engine, state, buffer = self._build_engine(run)

        # --- Pre-gate auto-verify: run auto-verify before the checklist gate ---
        # If task-level auto-verify items all pass, auto-mark OPEN checklist
        # items as DONE so the gate check succeeds. This prevents agents from
        # needing to explicitly call on_checklist_update() when auto-verify
        # already confirms the work was done.
        task = state.get_task(run_id, task_id)
        step_config_id_pre = None
        for step in run.steps:
            for t in step.tasks:
                if t.id == task_id:
                    step_config_id_pre = step.config_id
                    break
            if step_config_id_pre is not None:
                break

        pre_av_config = resolve_auto_verify_config(run, task.config_id, step_config_id_pre)
        if pre_av_config is not None and self._auto_verify_runner is not None:
            project_path = _resolve_working_path(run)
            if project_path is not None:
                # Auto-commit any uncommitted changes before running auto-verify
                if run.worktree_path:
                    commit_uncommitted_changes(
                        Path(run.worktree_path),
                        f"Auto-commit builder changes for task {task_id}",
                    )

                pre_av_results = await run_auto_verify(
                    pre_av_config,
                    self._auto_verify_runner,
                    project_path,
                    variables=run.config,
                )
                all_must_passed_pre, failing_must_ids_pre = evaluate_auto_verify(
                    pre_av_config, pre_av_results
                )

                if all_must_passed_pre:
                    # Auto-verify confirms work is done — mark OPEN checklist items as DONE
                    for item in task.checklist:
                        if item.status == ChecklistStatus.OPEN:
                            item.status = ChecklistStatus.DONE
                else:
                    # Must-items failed: emit event, then block the BUILDING->VERIFYING transition
                    buffer.emit(
                        AutoVerifyCompleted(
                            timestamp=self._clock.now(),
                            run_id=run_id,
                            event_type="auto_verify_completed",
                            task_id=task_id,
                            passed=False,
                            failing_must_items=failing_must_ids_pre,
                            results=[r.model_dump() for r in pre_av_results],
                        )
                    )
                    await self._persist(state, run_id, buffer)
                    raise GateBlockedError(
                        gate_name="auto_verify",
                        blocking_items=failing_must_ids_pre,
                    )

        try:
            result = engine.submit_for_verification(run_id, task_id)
        except GateBlockedError:
            # Persist state to record the gate evaluation event
            await self._persist(state, run_id, buffer)
            raise

        if not result.success:
            await self._persist(state, run_id, buffer)
            return result

        # --- Capture end commit for git tracking ---
        task = state.get_task(run_id, task_id)
        if run.worktree_path and task.attempts:
            worktree_path = Path(run.worktree_path)
            # Auto-commit any uncommitted changes left by the builder agent.
            # Some CLI agents (e.g. codex) may not commit their work, and the
            # verifier's git checkout of end_commit would destroy those changes.
            commit_uncommitted_changes(
                worktree_path, f"Auto-commit builder changes for task {task_id}"
            )
            task.attempts[-1].end_commit = get_head_commit(worktree_path)

        # --- Auto-verify phase ---
        # Find which step contains this task to resolve config correctly
        step_config_id = None
        for step in run.steps:
            for t in step.tasks:
                if t.id == task_id:
                    step_config_id = step.config_id
                    break
            if step_config_id is not None:
                break

        auto_verify_config = resolve_auto_verify_config(run, task.config_id, step_config_id)

        if auto_verify_config is not None and self._auto_verify_runner is not None:
            project_path = _resolve_working_path(run)
            if project_path is not None:
                av_results = await run_auto_verify(
                    auto_verify_config,
                    self._auto_verify_runner,
                    project_path,
                    variables=run.config,
                )

                # Store results in the current attempt
                if task.attempts:
                    task.attempts[-1].auto_verify_results = [r.model_dump() for r in av_results]

                all_must_passed, failing_must_ids = evaluate_auto_verify(
                    auto_verify_config, av_results
                )

                # Emit auto-verify event
                buffer.emit(
                    AutoVerifyCompleted(
                        timestamp=self._clock.now(),
                        run_id=run_id,
                        event_type="auto_verify_completed",
                        task_id=task_id,
                        passed=all_must_passed,
                        failing_must_items=failing_must_ids,
                        results=[r.model_dump() for r in av_results],
                    )
                )

                # --- Recovery triggers ---
                # 1) Crash detection: if any verification script crashed,
                #    trigger recovery instead of normal retry/fail flow.
                if has_crashes(av_results):
                    crash_lines: list[str] = []
                    for av in av_results:
                        if av.crashed:
                            crash_lines.append(
                                f"- [{av.item_id}] command `{av.cmd}` CRASHED\n"
                                f"  Error: {av.crash_error or '(unknown)'}"
                            )
                    crash_detail = "Validation script(s) crashed during auto-verify:\n" + "\n".join(
                        crash_lines
                    )
                    await self._persist(state, run_id, buffer)
                    self._notify_submit(task_id)
                    await self.trigger_recovery(run_id, task_id, crash_detail)
                    return TransitionResult(
                        success=True,
                        new_status=TaskStatus.RECOVERING,
                        error="Auto-verify script crashed; recovery triggered",
                    )

                if not all_must_passed:
                    # Store actionable feedback on the completed attempt so the
                    # next builder prompt can include concrete remediation details.
                    if task.attempts:
                        failing_lines: list[str] = []
                        for av in av_results:
                            if av.item_id not in failing_must_ids:
                                continue
                            output = av.output.strip() if av.output else ""
                            snippet = output if output else "(no command output)"
                            failing_lines.append(
                                f"- [{av.item_id}] command `{av.cmd}` failed (exit {av.exit_code})\n"
                                f"  Output:\n{snippet}"
                            )
                        if failing_lines:
                            task.attempts[-1].verifier_comment = (
                                "Auto-verify failed. Fix the following and resubmit:\n"
                                + "\n".join(failing_lines)
                            )

                    # Must-items failed: check max_attempts before retrying
                    run_obj = state.get_run(run_id)
                    old_status = task.status

                    # 2) Max attempts exceeded: trigger recovery instead of failing
                    if task.current_attempt >= task.max_attempts:
                        max_attempts_msg = (
                            f"All {task.max_attempts} revision attempts exhausted. "
                            f"Auto-verify still failing on: "
                            f"{', '.join(failing_must_ids)}."
                        )
                        if task.attempts and task.attempts[-1].verifier_comment:
                            max_attempts_msg += (
                                f"\n\nLast failure details:\n{task.attempts[-1].verifier_comment}"
                            )
                        await self._persist(state, run_id, buffer)
                        self._notify_submit(task_id)
                        await self.trigger_recovery(run_id, task_id, max_attempts_msg)
                        return TransitionResult(
                            success=True,
                            new_status=TaskStatus.RECOVERING,
                            error=f"Max attempts ({task.max_attempts}) exhausted; recovery triggered",
                        )

                    # Finalize the failing attempt before creating a new one
                    if task.attempts:
                        task.attempts[-1].outcome = "failed"
                        task.attempts[-1].completed_at = self._clock.now()

                    rev_result = transition_to_building(task, self._clock.now())
                    if rev_result.success:
                        # Populate agent snapshot on the newly created attempt
                        if task.attempts:
                            attempt = task.attempts[-1]
                            attempt.agent_type = run_obj.agent_type
                            attempt.agent_model = run_obj.agent_config.get("model")
                            attempt.agent_settings = self._sanitize_agent_config(
                                run_obj.agent_config
                            )
                            # Capture start_commit for git tracking: revision starts
                            # from where the previous attempt ended.
                            if len(task.attempts) >= 2:
                                prev_end = task.attempts[-2].end_commit
                                if prev_end:
                                    attempt.start_commit = prev_end

                        buffer.emit(
                            TaskStatusChanged(
                                timestamp=self._clock.now(),
                                run_id=run_id,
                                event_type="task_status_changed",
                                task_id=task_id,
                                old_status=old_status,
                                new_status=rev_result.new_status,
                            )
                        )
                        state.update_run(run_obj)
                    await self._persist(state, run_id, buffer)
                    self._notify_submit(task_id)
                    # Return with the revision status
                    return TransitionResult(
                        success=True,
                        new_status=TaskStatus.BUILDING,
                        gate_result=result.gate_result,
                        error="Auto-verify must-items failed",
                    )

        await self._persist(state, run_id, buffer)
        self._notify_submit(task_id)
        return result

    async def complete_verification(self, run_id: str, task_id: str) -> TransitionResult:
        """Complete verification phase.

        After verification completes, checks if the run has reached a terminal state
        (COMPLETED or FAILED) and handles worktree cleanup if configured.
        """
        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(
                run.status.value, "complete_verification (requires ACTIVE run)"
            )
        engine, state, buffer = self._build_engine(run)
        result = engine.complete_verification(run_id, task_id)

        # Get the updated run after engine processing
        updated_run = state.get_run(run_id)

        await self._persist(state, run_id, buffer)

        # Call env_lifecycle hook for task_end if configured and task completed successfully
        if (
            self._env_lifecycle is not None
            and result.success
            and result.new_status == TaskStatus.COMPLETED
            and updated_run.worktree_path
            and updated_run.env_file_specs
        ):
            worktree_path = Path(updated_run.worktree_path)
            await self._env_lifecycle.on_task_end(
                run_id=run_id,
                task_id=task_id,
                worktree_path=worktree_path,
            )

        # Call env_lifecycle hook for run_end if run reached terminal state
        if (
            self._env_lifecycle is not None
            and updated_run.status in (RunStatus.COMPLETED, RunStatus.FAILED)
            and updated_run.worktree_path
            and updated_run.env_file_specs
        ):
            worktree_path = Path(updated_run.worktree_path)
            success = updated_run.status == RunStatus.COMPLETED
            await self._env_lifecycle.on_run_end(
                run_id=run_id,
                repo_name=updated_run.repo_name,
                worktree_path=worktree_path,
                success=success,
            )

        # Handle completion actions if run reached terminal state
        if updated_run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
            worktree_manager = self._create_worktree_manager(updated_run)
            if worktree_manager is not None:
                handle_run_completion(updated_run, worktree_manager)

        return result

    # --- Direct state operations ---

    async def get_run(self, run_id: str) -> Run:
        """Get a run by ID."""
        return await self._repo.get(run_id)

    async def list_runs(self, limit: int | None = None) -> list[Run]:
        """List all runs, optionally limited to the most recent N runs."""
        return await self._repo.list_all(limit=limit)

    async def list_runs_recent(self, hours: int) -> list[Run]:
        """List runs created within the last N hours."""
        return await self._repo.list_recent(hours)

    async def list_repo_names(self) -> list[str]:
        """List unique repository names across all runs."""
        return await self._repo.list_repo_names()

    async def list_runs_by_repo(self, repo_name: str) -> list[Run]:
        """List runs for a repository."""
        return await self._repo.list_by_repo(repo_name)

    async def list_runs_by_status(self, status: RunStatus) -> list[Run]:
        """List runs filtered by status."""
        return await self._repo.list_by_status(status)

    async def list_runs_by_repo_and_status(self, repo_name: str, status: RunStatus) -> list[Run]:
        """List runs filtered by both repository and status."""
        return await self._repo.list_by_repo_and_status(repo_name, status)

    async def get_task(self, run_id: str, task_id: str) -> TaskState:
        """Get a task by run ID and task ID."""
        run = await self._repo.get(run_id)
        state = SessionStateManager()
        state.add_run(run)
        return state.get_task(run_id, task_id)

    async def create_run(self, run: Run) -> Run:
        """Persist a new run."""
        await self._repo.save(run)
        await self._session.commit()
        return await self._repo.get(run.id)

    async def set_worktree_path(self, run_id: str, worktree_path: str) -> Run:
        """Set the worktree path on a run after worktree creation."""
        run = await self._repo.get(run_id)
        run.worktree_path = worktree_path
        await self._repo.save(run)
        await self._session.commit()
        return run

    async def delete_run(self, run_id: str) -> None:
        """Delete a run."""
        await self._repo.delete(run_id)
        await self._session.commit()

    async def update_checklist_item(
        self,
        run_id: str,
        task_id: str,
        req_id: str,
        status: ChecklistStatus,
        note: str | None = None,
    ) -> ChecklistItem:
        """Update a checklist item status."""
        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(
                run.status.value, "update_checklist_item (requires ACTIVE run)"
            )
        state = SessionStateManager()
        state.add_run(run)
        task = state.get_task(run_id, task_id)

        # B15: Reject updates on completed/failed tasks and during verification
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.VERIFYING):
            raise InvalidTransitionError(
                task.status.value, "update_checklist_item (task is terminal or in verification)"
            )

        resolved_req_id = self._resolve_req_id(run_id, task, req_id)
        item = state.update_checklist_item(run_id, task_id, resolved_req_id, status, note)
        await self._repo.save(state.get_run(run_id))
        await self._session.commit()
        return item

    async def escalate_requirement(
        self,
        run_id: str,
        task_id: str,
        req_id: str,
        reason: str,
    ) -> Run:
        """Flag a requirement as unfulfillable and pause the run."""
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        task = state.get_task(run_id, task_id)
        resolved_req_id = self._resolve_req_id(run_id, task, req_id)
        engine.escalate_requirement(run_id, task_id, resolved_req_id, reason)
        return await self._persist(state, run_id, buffer)

    async def set_grade(
        self,
        run_id: str,
        task_id: str,
        req_id: str,
        grade: str,
        grade_reason: str | None = None,
    ) -> ChecklistItem:
        """Set a grade on a checklist item."""
        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(run.status.value, "set_grade (requires ACTIVE run)")
        state = SessionStateManager()
        state.add_run(run)
        task = state.get_task(run_id, task_id)

        from orchestrator.state.errors import ChecklistItemNotFoundError

        # B5+B15: Only allow grading during VERIFYING phase.
        # Also tolerate terminal states (FAILED/COMPLETED) so that agents
        # can finish recording grades even after complete_verification has
        # already transitioned the task (e.g. parallel tool calls).
        if task.status not in (
            TaskStatus.VERIFYING,
            TaskStatus.FAILED,
            TaskStatus.COMPLETED,
        ):
            raise InvalidTransitionError(
                task.status.value, "set_grade (only allowed in VERIFYING or terminal status)"
            )

        # B16: Validate grade against routine's configured grade_scale
        if run.routine_embedded is not None:
            routine_config = RoutineConfig.model_validate(run.routine_embedded)
            # Find which step contains this task to resolve config correctly
            step_config_id = None
            for step in run.steps:
                for t in step.tasks:
                    if t.id == task_id:
                        step_config_id = step.config_id
                        break
                if step_config_id is not None:
                    break

            task_config = find_task_config(routine_config, task.config_id, step_config_id)
            if task_config is not None:
                grade_scale = task_config.verifier.submission_template.grade_scale
                if grade not in grade_scale:
                    raise ValueError(
                        f"Invalid grade '{grade}'. Must be one of: {', '.join(grade_scale)}"
                    )

        resolved_req_id = self._resolve_req_id(run_id, task, req_id)

        for item in task.checklist:
            if item.req_id == resolved_req_id:
                item.grade = grade
                if grade_reason is not None:
                    item.grade_reason = grade_reason
                await self._repo.save(state.get_run(run_id))
                await self._session.commit()
                return item

        raise ChecklistItemNotFoundError(run_id, task_id, req_id)

    # --- Helper methods ---

    def _find_task(self, run: Run, task_id: str) -> TaskState:
        """Find a task in a run by task_id.

        Raises:
            TaskNotFoundError: If task is not found in the run.
        """
        for step in run.steps:
            for task in step.tasks:
                if task.id == task_id:
                    return task
        raise TaskNotFoundError(run.id, task_id)

    @staticmethod
    def _parse_numeric_req_id(value: str) -> int | None:
        """Parse flexible numeric requirement IDs.

        Accepts forms like ``1``, ``01``, ``R1``, ``r1``, ``R-01``, ``r_001``.
        Returns the numeric portion as int, or None if the value is non-numeric.
        """
        match = re.fullmatch(r"(?i)r?[-_\s]*0*(\d+)", value.strip())
        if match is None:
            return None
        return int(match.group(1))

    def _resolve_req_id(self, run_id: str, task: TaskState, req_id: str) -> str:
        """Resolve flexible req_id inputs to the canonical checklist req_id.

        Resolution order:
        1. Exact match.
        2. Case-insensitive exact match (if unique).
        3. Numeric normalization (e.g. R-01 -> R1, 1 -> R1) if unique.
        """
        from orchestrator.state.errors import ChecklistItemNotFoundError

        # 1) Exact match
        for item in task.checklist:
            if item.req_id == req_id:
                return item.req_id

        # 2) Case-insensitive exact
        lowered = req_id.lower()
        case_matches = [item.req_id for item in task.checklist if item.req_id.lower() == lowered]
        if len(case_matches) == 1:
            return case_matches[0]

        # 3) Numeric normalization
        target_num = self._parse_numeric_req_id(req_id)
        if target_num is not None:
            numeric_matches = [
                item.req_id
                for item in task.checklist
                if self._parse_numeric_req_id(item.req_id) == target_num
            ]
            if len(numeric_matches) == 1:
                return numeric_matches[0]

        raise ChecklistItemNotFoundError(run_id, task.id, req_id)

    def _find_step_for_task(self, run: Run, task_id: str) -> "StepState":
        """Find the step containing a task.

        Raises:
            TaskNotFoundError: If task is not found in the run.
        """
        for step in run.steps:
            for task in step.tasks:
                if task.id == task_id:
                    return step
        raise TaskNotFoundError(run.id, task_id)

    # --- Human interaction methods ---

    async def request_clarification(
        self,
        run_id: str,
        task_id: str,
        questions: list[ClarificationQuestion],
    ) -> ClarificationRequest:
        """Request clarification from human.

        Transitions task to PENDING_USER_ACTION and creates ClarificationRequest.
        Emits ClarificationRequested event.
        """
        import uuid

        run = await self._repo.get(run_id)
        task = self._find_task(run, task_id)

        # Create clarification request
        request = ClarificationRequest(
            id=str(uuid.uuid4()),
            run_id=run_id,
            task_id=task_id,
            attempt_num=task.current_attempt,
            questions=questions,
            created_at=self._clock.now(),
        )

        # Transition task
        old_status = task.status
        result = transition_to_pending_clarification(task, request.id)
        if not result.success:
            raise InvalidTransitionError(old_status.value, result.new_status.value)

        # Persist
        await self._repo.create_clarification_request(request)
        await self._repo.save(run)

        # Emit event
        await self._event_emitter.emit(
            ClarificationRequested(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="clarification_requested",
                task_id=task_id,
                request_id=request.id,
                question_count=len(questions),
            )
        )

        await self._session.commit()

        return request

    async def respond_to_clarification(
        self,
        run_id: str,
        task_id: str,
        request_id: str,
        answers: list[ClarificationAnswer],
        responded_by: str,
    ) -> TransitionResult:
        """Submit answers to clarification request.

        Writes to artifact file, transitions task back to BUILDING.
        Emits ClarificationResponded event.
        """
        from sqlalchemy import func, select as sa_select

        from orchestrator.db.models import ClarificationRequestModel

        run = await self._repo.get(run_id)
        task = self._find_task(run, task_id)

        # Get the request
        request = await self._repo.get_clarification_request(request_id)
        if request is None:
            raise RunNotFoundError(f"Clarification request {request_id} not found")

        # Create response
        now = self._clock.now()
        response = ClarificationResponse(
            request_id=request_id,
            answers=answers,
            responded_at=now,
        )

        # Save response
        await self._repo.save_clarification_response(response)

        # --- Write clarification Q&A to artifact file ---
        # Determine artifact path from routine config
        artifact_path: Path | None = None
        if run.routine_embedded is not None and run.worktree_path:
            routine_config = RoutineConfig.model_validate(run.routine_embedded)
            clarifications_config = routine_config.clarifications
            if clarifications_config is not None:
                raw_path = resolve_artifact_path(clarifications_config.artifact_path, run.config)
                artifact_path = Path(run.worktree_path) / raw_path

        clarification_line_range: tuple[str, int, int] | None = None
        if artifact_path is not None:
            # Determine step_id for the task
            step_id = ""
            for step in run.steps:
                for t in step.tasks:
                    if t.id == task_id:
                        step_id = step.id
                        break
                if step_id:
                    break

            # Count prior clarification requests for clarification_number
            count_result = await self._session.execute(
                sa_select(func.count())
                .select_from(ClarificationRequestModel)
                .where(
                    ClarificationRequestModel.run_id == run_id,
                    ClarificationRequestModel.task_id == task_id,
                )
            )
            clarification_number = count_result.scalar_one()

            # Count current lines before appending
            try:
                with open(artifact_path, "r") as f:
                    current_line_count = sum(1 for _ in f)
            except FileNotFoundError:
                current_line_count = 0

            # Format the artifact section
            text, _, section_line_count = format_clarification_artifact(
                request, response, step_id, clarification_number
            )

            # Write to artifact file (create with header if new)
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            if current_line_count == 0:
                header = build_artifact_header()
                artifact_path.write_text(header)
                current_line_count = header.count("\n") + (0 if header.endswith("\n") else 1)

            with open(artifact_path, "a") as f:
                f.write(text)
                if not text.endswith("\n"):
                    f.write("\n")

            start_line = current_line_count + 1
            end_line = current_line_count + section_line_count
            clarification_line_range = (str(artifact_path), start_line, end_line)

        # Determine skipped questions
        skipped_question_texts: list[str] | None = None
        skip_reason: str | None = None
        skipped_ids = {a.question_id for a in answers if a.skipped}
        if skipped_ids:
            skipped_question_texts = [q.question for q in request.questions if q.id in skipped_ids]
            for a in answers:
                if a.skipped and a.skip_reason:
                    skip_reason = a.skip_reason
                    break

        # Transition back to building
        old_status = task.status
        result = transition_from_clarification(task)
        if not result.success:
            raise InvalidTransitionError(old_status.value, result.new_status.value)

        await self._repo.save(run)

        # Emit event
        await self._event_emitter.emit(
            ClarificationResponded(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="clarification_responded",
                task_id=task_id,
                request_id=request_id,
            )
        )

        await self._session.commit()

        # Build builder prompt with clarification context for downstream use
        task_config_obj: TaskConfig | None = None
        step_context_str: str | None = None
        if run.routine_embedded is not None:
            routine_config = RoutineConfig.model_validate(run.routine_embedded)
            for step in routine_config.steps:
                for tc in step.tasks:
                    if tc.id == task.config_id:
                        task_config_obj = tc
                        step_context_str = step.step_context
                        break
                if task_config_obj is not None:
                    break

        if task_config_obj is not None:
            clarifications_path: str | None = (
                str(artifact_path) if artifact_path is not None else None
            )
            generate_builder_prompt(
                task_config_obj,
                task,
                run.config,
                step_context=step_context_str,
                clarifications_path=clarifications_path,
                clarification_line_range=clarification_line_range,
                skipped_questions=skipped_question_texts,
                skip_reason=skip_reason,
            )

        return result

    async def get_pending_clarification(
        self,
        run_id: str,
        task_id: str,
    ) -> ClarificationRequest | None:
        """Get pending clarification request for a task."""
        return await self._repo.get_pending_clarification(run_id, task_id)

    async def get_clarification_history(
        self,
        run_id: str,
        task_id: str,
    ) -> list[tuple[ClarificationRequest, ClarificationResponse | None]]:
        """Get all clarification rounds for a task in ascending creation order."""
        return await self._repo.get_clarification_history(run_id, task_id)

    async def approve_task(
        self,
        run_id: str,
        task_id: str,
        approved_by: str,
        comment: str | None = None,
    ) -> TransitionResult:
        """Approve a task awaiting human approval.

        Transitions task to COMPLETED.
        Emits ApprovalDecision event.
        """
        run = await self._repo.get(run_id)
        task = self._find_task(run, task_id)
        step = self._find_step_for_task(run, task_id)

        now = self._clock.now()
        old_status = task.status
        result = transition_from_approval(task, approved=True, now=now)
        if not result.success:
            raise InvalidTransitionError(old_status.value, result.new_status.value)

        await self._repo.save(run)

        # Emit event
        await self._event_emitter.emit(
            ApprovalDecision(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="approval_decision",
                task_id=task_id,
                step_id=step.id,
                approved=True,
                comment=comment,
                decided_by=approved_by,
            )
        )

        await self._session.commit()

        return result

    async def reject_task(
        self,
        run_id: str,
        task_id: str,
        rejected_by: str,
        reason: str | None = None,
    ) -> TransitionResult:
        """Reject a task awaiting human approval.

        Transitions task back to BUILDING for revision.
        Emits ApprovalDecision event.
        """
        run = await self._repo.get(run_id)
        task = self._find_task(run, task_id)
        step = self._find_step_for_task(run, task_id)

        now = self._clock.now()
        old_status = task.status
        result = transition_from_approval(task, approved=False, now=now)
        if not result.success:
            raise InvalidTransitionError(old_status.value, result.new_status.value)

        await self._repo.save(run)

        # Emit event
        await self._event_emitter.emit(
            ApprovalDecision(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="approval_decision",
                task_id=task_id,
                step_id=step.id,
                approved=False,
                comment=reason,
                decided_by=rejected_by,
            )
        )

        await self._session.commit()

        return result

    async def get_pending_actions(
        self,
        run_id: str,
    ) -> list[dict[str, Any]]:
        """Get all pending user actions for a run."""
        run = await self._repo.get(run_id)

        actions: list[dict[str, Any]] = []
        current_step_index = run.current_step_index

        # Be resilient to stale indices by skipping completed steps.
        while current_step_index < len(run.steps) and run.steps[current_step_index].completed:
            current_step_index += 1
        if current_step_index >= len(run.steps):
            return actions
        current_step = run.steps[current_step_index]

        # Check step-level human_approval gates for the current step
        if run.routine_embedded is not None:
            routine_config = RoutineConfig.model_validate(run.routine_embedded)
            if current_step.human_approval is None:
                for step_config in routine_config.steps:
                    if step_config.id == current_step.config_id:
                        if (
                            step_config.gate is not None
                            and step_config.gate.type == GateType.HUMAN_APPROVAL
                        ):
                            task_id = current_step.tasks[0].id if current_step.tasks else ""
                            actions.append(
                                {
                                    "task_id": task_id,
                                    "step_id": current_step.id,
                                    "action_type": "approval",
                                    "approval_prompt": step_config.gate.approval_prompt,
                                    "summary_artifact": step_config.gate.summary_artifact,
                                    "is_gate_approval": True,
                                }
                            )
                        break

        # Check task-level PENDING_USER_ACTION in the current step only.
        for task in current_step.tasks:
            if task.status == TaskStatus.PENDING_USER_ACTION:
                action: dict[str, Any] = {
                    "task_id": task.id,
                    "step_id": current_step.id,
                    "action_type": task.pending_action_type,
                    "is_gate_approval": False,
                }

                if task.pending_action_type == "clarification":
                    clarification = await self._repo.get_pending_clarification(run_id, task.id)
                    if clarification:
                        action["clarification_request"] = clarification.model_dump(mode="json")

                actions.append(action)

        return actions

    # --- Recovery methods ---

    async def trigger_recovery(self, run_id: str, task_id: str, failure_context: str) -> None:
        """Trigger recovery for a task that has crashed or exhausted attempts.

        Transitions the task to RECOVERING, generates a recovery prompt,
        pauses the run, and persists the state.

        Args:
            run_id: The run ID.
            task_id: The task ID (must be in VERIFYING state).
            failure_context: Description of the failure (crash logs or max-attempts message).
        """
        import logging

        logger = logging.getLogger(__name__)

        run = await self._repo.get(run_id)
        task = self._find_task(run, task_id)

        # Transition to RECOVERING
        old_status = task.status
        result = transition_to_recovering(task, failure_context)
        if not result.success:
            raise InvalidTransitionError(old_status.value, TaskStatus.RECOVERING.value)

        # Generate recovery prompt and store it in the attempt
        task_config = self._find_task_config_for_task(run, task)
        if task_config is not None and task.attempts:
            recovery_prompt = generate_recovery_prompt(
                task_config, task, failure_context, run.config
            )
            task.attempts[
                -1
            ].builder_prompt = (
                f"[RECOVERY PROMPT]\n\n{recovery_prompt.system}\n\n{recovery_prompt.user}"
            )

        # Pause the run
        if run.status == RunStatus.ACTIVE:
            run.status = RunStatus.PAUSED
            run.pause_reason = "recovery_triggered"

        run.updated_at = self._clock.now()
        await self._repo.save(run)

        # Emit events
        await self._event_emitter.emit(
            TaskStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="task_status_changed",
                task_id=task_id,
                old_status=old_status,
                new_status=TaskStatus.RECOVERING,
            )
        )
        await self._event_emitter.emit(
            RunStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="run_status_changed",
                old_status=RunStatus.ACTIVE,
                new_status=RunStatus.PAUSED,
            )
        )

        await self._session.commit()
        logger.info(
            f"Recovery triggered for task {task_id} in run {run_id}: {failure_context[:100]}"
        )

    async def complete_recovery_retry(
        self, run_id: str, task_id: str, notes: str
    ) -> TransitionResult:
        """Complete recovery by retrying the task.

        Creates a new attempt and transitions back to BUILDING. Resumes the run.

        Args:
            run_id: The run ID.
            task_id: The task ID (must be in RECOVERING state).
            notes: Recovery agent notes explaining the retry decision.

        Returns:
            TransitionResult with new_status=BUILDING.
        """
        run = await self._repo.get(run_id)
        task = self._find_task(run, task_id)

        if task.status != TaskStatus.RECOVERING:
            raise InvalidTransitionError(task.status.value, TaskStatus.BUILDING.value)

        # Store notes in current attempt
        if task.attempts:
            task.attempts[-1].verifier_comment = notes

        # Transition to BUILDING (creates new attempt)
        old_status = task.status
        result = transition_to_building(task, self._clock.now())
        if not result.success:
            raise InvalidTransitionError(old_status.value, TaskStatus.BUILDING.value)

        # Populate agent snapshot on the new attempt
        if task.attempts:
            attempt = task.attempts[-1]
            attempt.agent_type = run.agent_type
            attempt.agent_model = run.agent_config.get("model")
            attempt.agent_settings = self._sanitize_agent_config(run.agent_config)
            # Capture start_commit: recovery retry starts from where the previous attempt ended.
            if len(task.attempts) >= 2:
                prev_end = task.attempts[-2].end_commit
                if prev_end:
                    attempt.start_commit = prev_end

        # Resume the run if paused
        if run.status == RunStatus.PAUSED:
            run.status = RunStatus.ACTIVE
            run.pause_reason = None

        run.updated_at = self._clock.now()
        await self._repo.save(run)

        # Emit events
        await self._event_emitter.emit(
            TaskStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="task_status_changed",
                task_id=task_id,
                old_status=old_status,
                new_status=TaskStatus.BUILDING,
            )
        )

        await self._session.commit()
        return result

    async def complete_recovery_skip(
        self, run_id: str, task_id: str, notes: str
    ) -> TransitionResult:
        """Complete recovery by skipping the task.

        Marks the task as COMPLETED with outcome 'skipped'. Resumes the run
        and advances to the next pending task.

        Args:
            run_id: The run ID.
            task_id: The task ID (must be in RECOVERING state).
            notes: Recovery agent notes explaining the skip decision.

        Returns:
            TransitionResult with new_status=COMPLETED.
        """
        run = await self._repo.get(run_id)
        task = self._find_task(run, task_id)

        if task.status != TaskStatus.RECOVERING:
            raise InvalidTransitionError(task.status.value, TaskStatus.COMPLETED.value)

        old_status = task.status
        task.status = TaskStatus.COMPLETED
        if task.attempts:
            task.attempts[-1].outcome = "skipped"
            task.attempts[-1].verifier_comment = notes
            task.attempts[-1].completed_at = self._clock.now()

        # Resume the run if paused
        if run.status == RunStatus.PAUSED:
            run.status = RunStatus.ACTIVE
            run.pause_reason = None

        # Check step progression to advance to next task
        from orchestrator.workflow.transitions import check_step_progression, check_run_completion

        check_step_progression(run)
        check_run_completion(run, self._clock.now())

        run.updated_at = self._clock.now()
        await self._repo.save(run)

        # Emit events
        await self._event_emitter.emit(
            TaskStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="task_status_changed",
                task_id=task_id,
                old_status=old_status,
                new_status=TaskStatus.COMPLETED,
            )
        )

        await self._session.commit()
        return TransitionResult(success=True, new_status=TaskStatus.COMPLETED)

    async def complete_recovery_abandon(
        self, run_id: str, task_id: str, notes: str
    ) -> TransitionResult:
        """Complete recovery by abandoning (failing) the task.

        Marks the task as FAILED with outcome 'failed'.

        Args:
            run_id: The run ID.
            task_id: The task ID (must be in RECOVERING state).
            notes: Recovery agent notes explaining the abandon decision.

        Returns:
            TransitionResult with new_status=FAILED.
        """
        run = await self._repo.get(run_id)
        task = self._find_task(run, task_id)

        if task.status != TaskStatus.RECOVERING:
            raise InvalidTransitionError(task.status.value, TaskStatus.FAILED.value)

        old_status = task.status
        task.status = TaskStatus.FAILED
        if task.attempts:
            task.attempts[-1].outcome = "failed"
            task.attempts[-1].verifier_comment = notes
            task.attempts[-1].completed_at = self._clock.now()

        run.updated_at = self._clock.now()
        await self._repo.save(run)

        # Emit events
        await self._event_emitter.emit(
            TaskStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="task_status_changed",
                task_id=task_id,
                old_status=old_status,
                new_status=TaskStatus.FAILED,
            )
        )

        await self._session.commit()
        return TransitionResult(success=True, new_status=TaskStatus.FAILED)

    def _find_task_config_for_task(self, run: Run, task: TaskState) -> TaskConfig | None:
        """Find the TaskConfig for a task from the run's routine_embedded.

        Args:
            run: The run containing the routine configuration.
            task: The task state to find config for.

        Returns:
            The TaskConfig, or None if not found.
        """
        if run.routine_embedded is None:
            return None
        routine_config = RoutineConfig.model_validate(run.routine_embedded)
        return find_task_config(routine_config, task.config_id)

    # --- Submit notification bridge ---

    def register_submit_event(self, task_id: str) -> asyncio.Event:
        """Register an asyncio.Event that fires when submit_for_verification is called for this task.

        Used by UserManagedAgent to wait for external submission via REST/MCP.
        Delegates to the shared :class:`SubmitEventRegistry`.
        """
        return self._submit_registry.register(task_id)

    def unregister_submit_event(self, task_id: str) -> None:
        """Remove a previously registered submit event."""
        self._submit_registry.unregister(task_id)

    def _notify_submit(self, task_id: str) -> None:
        """Signal any registered submit event for this task."""
        self._submit_registry.notify(task_id)
