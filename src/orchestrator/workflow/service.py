"""Async workflow service wiring WorkflowEngine to persistent storage."""

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.schemas.runs import RecoverResponse
from orchestrator.config.enums import (
    AgentRunnerType,
    ChecklistStatus,
    GateType,
    RunStatus,
    TaskStatus,
)
from orchestrator.config.global_config import GlobalConfig
from orchestrator.config.models import AutoVerifyConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.db.event_store import EventStore
from orchestrator.db.repositories import RunRepository
from orchestrator.state.models import Attempt, ChecklistItem, Run, StepState, TaskState
from orchestrator.state.session import SessionStateManager
from orchestrator.state.errors import RunNotFoundError, TaskNotFoundError
from orchestrator.workflow.auto_verify import (
    AutoVerifyResult,
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
    CompressedDecisions,
    build_artifact_header,
    compress_clarifications,
    format_clarification_artifact,
    resolve_artifact_path,
)
from orchestrator.workflow.engine import Clock, WorkflowEngine
from orchestrator.workflow.prompts import generate_builder_prompt, generate_recovery_prompt
from orchestrator.workflow.templates import resolve_template
from orchestrator.workflow.errors import GateBlockedError, InvalidTransitionError
from orchestrator.workflow.event_logger import PersistentEventEmitter
from orchestrator.workflow.events import (
    AgentChangedEvent,
    ApprovalDecision,
    AutoVerifyCompleted,
    BufferingEmitter,
    ChildCompleted,
    ChildFailed,
    ChildSpawned,
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


def find_step_config(routine_config: RoutineConfig, step_config_id: str) -> StepConfig | None:
    """Find a StepConfig by id within a RoutineConfig. Pure function."""
    for step in routine_config.steps:
        if step.id == step_config_id:
            return step
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

        return WorktreeManager(
            repo_path,
            worktrees_dir,
            server_port=self._global_config.server.port,
            worktree_base_port=self._global_config.server.worktree_base_port,
        )

    # --- Delegating to WorkflowEngine ---

    async def cancel_run(self, run_id: str, reason: str | None = None) -> Run:
        """Cancel a run (ACTIVE/PAUSED -> FAILED).

        If a RunWorkflow is actively executing, enqueues a CANCEL signal so
        the workflow can apply the transition at a safe iteration boundary.
        Otherwise falls back to direct DB mutation.

        Handles worktree cleanup if the run has a worktree configured.
        """
        from orchestrator.workflow.signals import (
            DbSignalTransport,
            SignalQueue,
            WorkflowSignal,
            has_active_workflow,
        )

        if has_active_workflow(run_id):
            transport = DbSignalTransport(self._session)
            queue = SignalQueue(transport)
            payload: dict[str, object] = {}
            if reason is not None:
                payload["reason"] = reason
            await queue.enqueue(run_id, WorkflowSignal.CANCEL, payload or None)
            return await self._repo.get(run_id)

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
            AgentRunnerType.CLI_SUBPROCESS,
            AgentRunnerType.OPENHANDS_LOCAL,
            AgentRunnerType.OPENHANDS_DOCKER,
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
        """Pause a run (ACTIVE -> PAUSED).

        If a RunWorkflow is actively executing for this run, the signal is
        enqueued so the workflow applies the pause at a safe iteration
        boundary.  Otherwise the state change is applied directly to the DB
        (existing behaviour, used for already-paused/queued runs and for
        internal pauses initiated from within the RunWorkflow itself).
        """
        from orchestrator.workflow.signals import (
            DbSignalTransport,
            SignalQueue,
            WorkflowSignal,
            has_active_workflow,
        )

        if has_active_workflow(run_id):
            transport = DbSignalTransport(self._session)
            queue = SignalQueue(transport)
            payload: dict[str, object] = {"reason": reason}
            if error_detail is not None:
                payload["error_detail"] = error_detail
            await queue.enqueue(run_id, WorkflowSignal.PAUSE, payload)
            # Return the current run state (transition happens asynchronously)
            return await self._repo.get(run_id)

        # Direct DB mutation (no active workflow, or internal call after unregister)
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        engine.pause_run(run_id, reason=reason, error_detail=error_detail)
        return await self._persist(state, run_id, buffer)

    async def resume_run(
        self,
        run_id: str,
        agent_type: AgentRunnerType | None = None,
        agent_config: dict[str, object] | None = None,
        resume_strategy: str | None = None,
    ) -> Run:
        """Resume a run (PAUSED -> ACTIVE), optionally changing the agent.

        If a RunWorkflow is already active for this run (unusual — the run
        should be PAUSED when resuming), enqueues a RESUME signal.  In
        practice resume_run is always called on a PAUSED run (no active
        workflow), so this falls through to the direct DB path.

        Args:
            run_id: The run ID
            agent_type: Optional new agent type to use
            agent_config: Optional new agent config to use
            resume_strategy: "continue" (default) or "revert" to reset current phase

        Returns:
            The updated run
        """
        from orchestrator.workflow.signals import (
            DbSignalTransport,
            SignalQueue,
            WorkflowSignal,
            has_active_workflow,
        )

        if has_active_workflow(run_id):
            transport = DbSignalTransport(self._session)
            queue = SignalQueue(transport)
            await queue.enqueue(run_id, WorkflowSignal.RESUME, None)
            return await self._repo.get(run_id)

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
                        old_agent=old_agent or AgentRunnerType.CLI_SUBPROCESS,
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
        agent_type: AgentRunnerType | None = None,
        agent_config: dict[str, object] | None = None,
        preserve_checklist: bool = False,
        guidance: str | None = None,
        reset_branch: bool = True,
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

        # Capture restore point: the commit immediately before the target task's
        # first attempt ran. Use start_commit of the first attempt when available;
        # fall back to the end_commit of the nearest preceding task that has one.
        restore_commit: str | None = None
        if target_task.attempts and target_task.attempts[0].start_commit:
            restore_commit = target_task.attempts[0].start_commit
        if not restore_commit:
            for i in range(target_idx - 1, -1, -1):
                prev_task = ordered_tasks[i][2]
                for attempt in reversed(prev_task.attempts):
                    if attempt.end_commit:
                        restore_commit = attempt.end_commit
                        break
                if restore_commit:
                    break

        now = self._clock.now()

        # Reset target task to BUILDING with a fresh attempt and expanded budget.
        target_task.max_attempts += additional_attempts
        target_task.status = TaskStatus.BUILDING
        target_task.pending_action_type = None
        target_task.pending_clarification_id = None
        # Append user guidance to the last attempt's verifier_comment so the
        # builder prompt picks it up via the reversed-attempt search.
        if guidance and target_task.attempts:
            prev = target_task.attempts[-1]
            human_note = f"\n\n## Human Guidance\n{guidance}"
            if prev.verifier_comment:
                prev.verifier_comment += human_note
            else:
                prev.verifier_comment = human_note.strip()

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

        # Restore worktree to the commit before the target task's first attempt,
        # so the branch is in the same state as when the task was first queued.
        # When reset_branch=False the branch is left as-is ("carry on" mode).
        if reset_branch and run.worktree_path:
            restored = False
            if restore_commit:
                restored = self._checkout_on_branch(run.worktree_path, run.id, restore_commit)
            if not restored and run.source_branch:
                self._checkout_on_branch(run.worktree_path, run.id, run.source_branch)

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

            # Reset worktree to start_commit to undo the failed builder's changes.
            if len(task.attempts) >= 2:
                prev_attempt = task.attempts[-2]
                if prev_attempt.start_commit and run.worktree_path:
                    self._checkout_on_branch(run.worktree_path, run.id, prev_attempt.start_commit)

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

            # No checkout needed — worktree is already at end_commit
            # (submit_for_verification auto-commits and captures HEAD).

    def _checkout_on_branch(self, worktree_path: str, run_id: str, commit_sha: str) -> bool:
        """Move the run's branch to a commit without detaching HEAD."""
        import logging
        import subprocess

        branch_name = f"orchestrator/run-{run_id}"
        result = subprocess.run(
            ["git", "checkout", "-B", branch_name, commit_sha],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logging.getLogger(__name__).warning(
                f"Failed to checkout -B {branch_name} {commit_sha} "
                f"in {worktree_path}: {result.stderr.strip()}"
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

    async def expand_fan_out_task(self, run_id: str, task_id: str) -> list[TaskState]:
        """Expand a fan-out task into parallel child tasks.

        1. Load run, find parent task and its TaskConfig
        2. Resolve input_glob in the worktree
        3. For each matching file, create a child TaskState
        4. Add children to the step's task list
        5. Set parent status to FAN_OUT_RUNNING
        6. Persist and return children

        Returns:
            List of newly created child TaskState objects
        """
        import glob as glob_mod
        import logging

        from orchestrator.workflow.templates import derive_output_path

        logger = logging.getLogger(__name__)

        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(
                run.status.value, "expand_fan_out_task (requires ACTIVE run)"
            )

        if run.routine_embedded is None:
            raise InvalidTransitionError("no routine", "expand_fan_out_task (requires routine)")

        routine_config = RoutineConfig.model_validate(run.routine_embedded)

        # Find the parent task state and its step
        parent_task: TaskState | None = None
        parent_step: StepState | None = None
        step_config_id: str | None = None
        for step in run.steps:
            for task in step.tasks:
                if task.id == task_id:
                    parent_task = task
                    parent_step = step
                    step_config_id = step.config_id
                    break
            if parent_task is not None:
                break

        if parent_task is None or parent_step is None:
            raise TaskNotFoundError(run_id, task_id)

        # Find the task config with fan_out
        task_config = find_task_config(routine_config, parent_task.config_id, step_config_id)
        if task_config is None or task_config.fan_out is None:
            raise InvalidTransitionError(
                "no fan_out config",
                "expand_fan_out_task (requires fan_out in task config)",
            )

        fan_out = task_config.fan_out
        worktree_path = run.worktree_path
        if not worktree_path:
            raise InvalidTransitionError(
                "no worktree", "expand_fan_out_task (requires worktree_path)"
            )

        # Template variables from run config
        variables: dict[str, str] = {k: str(v) for k, v in run.config.items() if v is not None}

        # Resolve input_glob template variables (e.g. {{feature}}) before globbing
        resolved_glob = resolve_template(fan_out.input_glob, variables=variables)
        pattern = str(Path(worktree_path) / resolved_glob)
        matched_files = sorted(glob_mod.glob(pattern, recursive=True))

        if not matched_files:
            logger.warning(
                f"Run {run_id}: fan-out task {task_id}: no files matched "
                f"glob '{resolved_glob}' in {worktree_path}"
            )

        # Create child tasks
        children: list[TaskState] = []
        for index, abs_path in enumerate(matched_files):
            # Convert to relative path within worktree
            rel_path = str(Path(abs_path).relative_to(worktree_path))
            output_path = derive_output_path(fan_out.output_pattern, rel_path, variables)
            input_name = Path(rel_path).name

            from orchestrator.state.models import generate_id

            child = TaskState(
                id=generate_id(),
                config_id=f"{parent_task.config_id}_fan_{index}",
                title=f"{parent_task.title} [{input_name}]",
                status=TaskStatus.PENDING,
                max_attempts=fan_out.max_attempts,
                has_verification=False,
                parent_task_id=parent_task.id,
                fan_out_index=index,
                fan_out_input=rel_path,
                fan_out_output=output_path,
            )
            children.append(child)

        # Persist children directly so concurrent child updates don't rewrite the full run graph.
        await self._repo.create_fan_out_children(
            parent_step.id,
            children,
            parent_status=TaskStatus.FAN_OUT_RUNNING,
        )
        if not children:
            await self._repo.update_task_status(parent_task.id, TaskStatus.FAN_OUT_RUNNING)
        await self._session.commit()

        # Emit ChildSpawned events for each created child and commit immediately
        # so the write transaction is closed before concurrent child execution begins.
        if children:
            await self._event_emitter.emit_batch(
                [
                    ChildSpawned(
                        timestamp=self._clock.now(),
                        run_id=run_id,
                        event_type="child_spawned",
                        parent_task_id=task_id,
                        child_task_id=child.id,
                        fan_out_index=child.fan_out_index or 0,
                        fan_out_input=child.fan_out_input,
                    )
                    for child in children
                ]
            )
            await self._session.commit()

        logger.info(
            f"Run {run_id}: expanded fan-out task {task_id} into "
            f"{len(children)} children from glob '{fan_out.input_glob}'"
        )

        return children

    async def complete_fan_out_parent(
        self,
        run_id: str,
        task_id: str,
        *,
        all_passed: bool,
        to_verifying: bool = False,
    ) -> None:
        """Transition a fan-out parent task after all children finish.

        Args:
            run_id: The run ID
            task_id: The parent task ID (must be FAN_OUT_RUNNING)
            all_passed: True if all children completed successfully
            to_verifying: If True and all_passed, move to VERIFYING (for outer LLM verifier)
        """
        import logging
        from orchestrator.workflow.transitions import (
            check_run_completion,
            check_step_progression,
        )
        from orchestrator.workflow.events import StepCompleted

        logger = logging.getLogger(__name__)

        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)

        parent_task = state.get_task(run_id, task_id)
        if parent_task.status != TaskStatus.FAN_OUT_RUNNING:
            # Already transitioned (e.g. after resume) — skip silently
            if parent_task.status in (TaskStatus.COMPLETED, TaskStatus.VERIFYING):
                logger.info(
                    f"Run {run_id}: fan-out parent {task_id} already "
                    f"{parent_task.status.value}, skipping complete_fan_out_parent"
                )
                return
            raise InvalidTransitionError(
                parent_task.status.value,
                "complete_fan_out_parent (requires FAN_OUT_RUNNING)",
            )

        old_status = parent_task.status

        if not all_passed:
            parent_task.status = TaskStatus.FAILED
            new_status = TaskStatus.FAILED
            # Pause the run
            engine.pause_run(run_id, reason="fan_out_child_failed")
        elif to_verifying:
            parent_task.status = TaskStatus.VERIFYING
            new_status = TaskStatus.VERIFYING
        else:
            parent_task.status = TaskStatus.COMPLETED
            new_status = TaskStatus.COMPLETED

        buffer.emit(
            TaskStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="task_status_changed",
                task_id=task_id,
                old_status=old_status,
                new_status=new_status,
            )
        )

        # Check step/run completion for terminal states
        if new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            updated_run = state.get_run(run_id)
            prev_step_index = updated_run.current_step_index

            # Load routine config if available for condition evaluation
            routine_config = None
            if updated_run.routine_embedded is not None:
                try:
                    routine_config = RoutineConfig.model_validate(updated_run.routine_embedded)
                except Exception:
                    # If routine config can't be loaded, continue without condition evaluation
                    pass

            step_changed = check_step_progression(
                updated_run,
                routine_config=routine_config,
                clock=self._clock,
                emitter=buffer,
                worktree_path=None,  # Service doesn't have worktree path at this level
                run_config=updated_run.config,
            )

            if step_changed:
                for i in range(prev_step_index, updated_run.current_step_index + 1):
                    step = updated_run.steps[i]
                    if step.completed:
                        buffer.emit(
                            StepCompleted(
                                timestamp=self._clock.now(),
                                run_id=run_id,
                                event_type="step_completed",
                                step_index=i,
                                step_id=step.id,
                            )
                        )

                old_run_status = updated_run.status
                new_run_status = check_run_completion(updated_run, self._clock.now())
                if new_run_status is not None:
                    buffer.emit(
                        RunStatusChanged(
                            timestamp=self._clock.now(),
                            run_id=run_id,
                            event_type="run_status_changed",
                            old_status=old_run_status,
                            new_status=new_run_status,
                        )
                    )

            state.update_run(updated_run)

        await self._persist(state, run_id, buffer)

        logger.info(
            f"Run {run_id}: fan-out parent {task_id} transitioned "
            f"from {old_status.value} to {new_status.value}"
        )

    async def reset_fan_out_children(self, run_id: str, parent_task_id: str) -> None:
        """Reset all children of a fan-out parent to PENDING for re-execution.

        Also sets the parent task status to FAN_OUT_RUNNING.
        """
        await self._repo.reset_fan_out_children(parent_task_id)
        await self._session.commit()

    async def start_fan_out_parent(self, run_id: str, task_id: str) -> TaskState:
        """Ensure a fan-out parent has an active attempt and FAN_OUT_RUNNING status."""
        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(
                run.status.value, "start_fan_out_parent (requires ACTIVE run)"
            )

        task = self._find_task(run, task_id)
        if task.parent_task_id is not None:
            raise InvalidTransitionError(task.status.value, "start_fan_out_parent (parent only)")

        if task.status == TaskStatus.PENDING:
            await self.start_task(run_id, task_id)
            run = await self._repo.get(run_id)
            task = self._find_task(run, task_id)

        if task.status == TaskStatus.FAN_OUT_RUNNING:
            return task

        if task.status != TaskStatus.BUILDING:
            raise InvalidTransitionError(
                task.status.value,
                "start_fan_out_parent (requires PENDING, BUILDING, or FAN_OUT_RUNNING)",
            )

        await self._repo.update_task_status(task_id, TaskStatus.FAN_OUT_RUNNING)
        await self._event_emitter.emit_batch(
            [
                TaskStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="task_status_changed",
                    task_id=task_id,
                    old_status=TaskStatus.BUILDING,
                    new_status=TaskStatus.FAN_OUT_RUNNING,
                )
            ]
        )
        await self._session.commit()
        refreshed = await self._repo.get(run_id)
        return self._find_task(refreshed, task_id)

    async def start_fan_out_child_task(self, run_id: str, task_id: str) -> None:
        """Create a new attempt for a persisted fan-out child task."""
        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(
                run.status.value, "start_fan_out_child_task (requires ACTIVE run)"
            )

        task = self._find_task(run, task_id)
        if task.parent_task_id is None:
            raise InvalidTransitionError(task.status.value, "start_fan_out_child_task (child only)")

        next_attempt_num = task.current_attempt + 1
        attempt = Attempt(attempt_num=next_attempt_num, started_at=self._clock.now())
        attempt.agent_type = run.agent_type
        attempt.agent_model = run.agent_config.get("model")
        attempt.agent_settings = self._sanitize_agent_config(run.agent_config)

        await self._repo.create_task_attempt(task_id, attempt, status=TaskStatus.BUILDING)
        await self._event_emitter.emit_batch(
            [
                TaskStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="task_status_changed",
                    task_id=task_id,
                    old_status=task.status,
                    new_status=TaskStatus.BUILDING,
                )
            ]
        )
        await self._session.commit()

    async def update_child_task_state(
        self,
        run_id: str,
        task_id: str,
        updates: dict[str, Any],
        *,
        parent_task_id: str | None = None,
        fan_out_index: int = 0,
        fan_out_output: str | None = None,
    ) -> None:
        """Update a child task's state fields (outcome, error, status, auto_verify_results).

        Loads the run, finds the task, applies the updates dict to the task's
        latest attempt and/or the task itself, then persists.

        Supported keys in ``updates``:
        - ``outcome`` (str): set on latest attempt
        - ``error`` (str): set on latest attempt
        - ``completed_at`` (datetime): set on latest attempt
        - ``auto_verify_results`` (list): set on latest attempt
        - ``status`` (TaskStatus): set on the task itself

        When ``parent_task_id`` is provided, emits ChildCompleted or ChildFailed
        events based on the new status.
        """
        # NOTE: Do NOT load the full run here.  Loading via self._repo.get()
        # pulls all child tasks into the session graph; if two children commit
        # concurrently, the second commit can overwrite the first child's
        # status with stale values.  update_latest_attempt loads only the
        # target task model, which avoids this clobber.
        repo_updates: dict[str, Any] = {}
        for key in ("outcome", "error", "completed_at", "auto_verify_results"):
            if key in updates:
                repo_updates[key] = updates[key]
        if "status" in updates:
            repo_updates["status"] = updates["status"]
        await self._repo.update_latest_attempt(task_id, **repo_updates)

        # Flush child lifecycle events in the same transaction to avoid extra write
        # contention in concurrent fan-out (all DB writes committed atomically below).
        if parent_task_id is not None and "status" in updates:
            new_status = updates["status"]
            if new_status == TaskStatus.COMPLETED:
                await self._event_store.append(
                    ChildCompleted(
                        timestamp=self._clock.now(),
                        run_id=run_id,
                        event_type="child_completed",
                        parent_task_id=parent_task_id,
                        child_task_id=task_id,
                        fan_out_index=fan_out_index,
                        fan_out_output=fan_out_output,
                    )
                )
            elif new_status == TaskStatus.FAILED:
                await self._event_store.append(
                    ChildFailed(
                        timestamp=self._clock.now(),
                        run_id=run_id,
                        event_type="child_failed",
                        parent_task_id=parent_task_id,
                        child_task_id=task_id,
                        fan_out_index=fan_out_index,
                        error=updates.get("error"),
                    )
                )

        await self._session.commit()

    async def start_task(self, run_id: str, task_id: str) -> TransitionResult:
        """Start building a task (PENDING -> BUILDING)."""
        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(run.status.value, "start_task (requires ACTIVE run)")
        engine, state, buffer = self._build_engine(run)

        # Capture start commit before the engine transition so it's available for the event
        start_commit: str | None = None
        if run.worktree_path:
            start_commit = get_head_commit(Path(run.worktree_path))

        result = engine.start_task(run_id, task_id, start_commit=start_commit)

        # Store start commit on the attempt (also available via the emitted event)
        if result.success and start_commit:
            task = state.get_task(run_id, task_id)
            if task.attempts:
                task.attempts[-1].start_commit = start_commit

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

    async def execute_script_task(self, run_id: str, task_id: str) -> TransitionResult:
        """Execute a script-only task.

        Runs the shell script from the task config, captures output, and
        completes or fails the task based on the exit code. Script tasks
        skip the verification phase entirely -- the script result IS the
        verification.

        Flow:
        1. Start the task (PENDING -> BUILDING, creates an Attempt)
        2. Resolve template variables in the script string
        3. Run the script via asyncio.create_subprocess_shell in the worktree
        4. If exit 0: mark task COMPLETED (attempt outcome="passed")
        5. If non-zero: mark task FAILED, pause the run
        """
        import logging

        logger = logging.getLogger(__name__)

        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(
                run.status.value, "execute_script_task (requires ACTIVE run)"
            )

        # Find the TaskConfig from the routine to get the script
        if run.routine_embedded is None:
            raise InvalidTransitionError("no routine", "execute_script_task (requires routine)")

        routine_config = RoutineConfig.model_validate(run.routine_embedded)

        # Find the task state to get config_id
        task_state: TaskState | None = None
        for step in run.steps:
            for task in step.tasks:
                if task.id == task_id:
                    task_state = task
                    break
            if task_state is not None:
                break

        if task_state is None:
            raise TaskNotFoundError(run_id, task_id)

        # Find matching task config
        task_config: TaskConfig | None = None
        for step_cfg in routine_config.steps:
            for tc in step_cfg.tasks:
                if tc.id == task_state.config_id:
                    task_config = tc
                    break
            if task_config is not None:
                break

        if task_config is None or task_config.script is None:
            raise InvalidTransitionError(
                "no script config", "execute_script_task (requires script in task config)"
            )

        # 1. Start the task (creates an Attempt, moves to BUILDING)
        engine, state, buffer = self._build_engine(run)
        start_result = engine.start_task(run_id, task_id)
        if not start_result.success:
            await self._persist(state, run_id, buffer)
            return start_result

        # Tag the attempt as a script execution
        task_in_state = state.get_task(run_id, task_id)
        if task_in_state.attempts:
            attempt = task_in_state.attempts[-1]
            attempt.agent_type = AgentRunnerType.SCRIPT

        await self._persist(state, run_id, buffer)

        # 2. Resolve template variables in the script
        template_vars: dict[str, str] = {k: str(v) for k, v in run.config.items() if v is not None}
        worktree_path = run.worktree_path
        resolved_script = resolve_template(
            task_config.script,
            variables=template_vars,
            worktree_path=worktree_path,
        )

        # 3. Run the script
        logger.info(f"Run {run_id}: executing script task {task_id}: {resolved_script!r}")

        cwd = worktree_path or "."
        try:
            proc = await asyncio.create_subprocess_shell(
                resolved_script,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout_bytes, _ = await proc.communicate()
            output = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            exit_code = proc.returncode or 0
        except Exception as e:
            output = f"Failed to execute script: {e}"
            exit_code = 1

        # Re-load state for the next transition
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        task_in_state = state.get_task(run_id, task_id)

        if exit_code == 0:
            # 4a. Success: store output, mark COMPLETED
            if task_in_state.attempts:
                attempt = task_in_state.attempts[-1]
                attempt.agent_output = output
                attempt.outcome = "passed"
                attempt.completed_at = self._clock.now()

            # Transition: BUILDING -> VERIFYING -> COMPLETED
            # Since script tasks have no verification, we go directly through
            # submit_for_verification and complete_verification via the engine
            from orchestrator.workflow.transitions import (
                check_run_completion,
                check_step_progression,
            )

            task_in_state.status = TaskStatus.COMPLETED
            state.update_run(state.get_run(run_id))

            # Emit task status changed event
            buffer.emit(
                TaskStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="task_status_changed",
                    task_id=task_id,
                    old_status=TaskStatus.BUILDING,
                    new_status=TaskStatus.COMPLETED,
                )
            )

            # Check step/run completion
            updated_run = state.get_run(run_id)
            prev_step_index = updated_run.current_step_index

            # Load routine config if available for condition evaluation
            routine_config = None
            if updated_run.routine_embedded is not None:
                try:
                    routine_config = RoutineConfig.model_validate(updated_run.routine_embedded)
                except Exception:
                    # If routine config can't be loaded, continue without condition evaluation
                    pass

            step_changed = check_step_progression(
                updated_run,
                routine_config=routine_config,
                clock=self._clock,
                emitter=buffer,
                worktree_path=Path(worktree_path) if worktree_path else None,
                run_config=updated_run.config,
            )

            if step_changed:
                from orchestrator.workflow.events import StepCompleted

                for i in range(prev_step_index, updated_run.current_step_index + 1):
                    step = updated_run.steps[i]
                    if step.completed:
                        buffer.emit(
                            StepCompleted(
                                timestamp=self._clock.now(),
                                run_id=run_id,
                                event_type="step_completed",
                                step_index=i,
                                step_id=step.id,
                            )
                        )

                old_run_status = updated_run.status
                new_run_status = check_run_completion(updated_run, self._clock.now())
                if new_run_status is not None:
                    buffer.emit(
                        RunStatusChanged(
                            timestamp=self._clock.now(),
                            run_id=run_id,
                            event_type="run_status_changed",
                            old_status=old_run_status,
                            new_status=new_run_status,
                        )
                    )

            state.update_run(updated_run)
            await self._persist(state, run_id, buffer)

            logger.info(f"Run {run_id}: script task {task_id} completed successfully")
            return TransitionResult(success=True, new_status=TaskStatus.COMPLETED)
        else:
            # 4b. Failure: store output + exit code, mark FAILED, pause run
            if task_in_state.attempts:
                attempt = task_in_state.attempts[-1]
                attempt.agent_output = output
                attempt.error = f"Script exited with code {exit_code}"
                attempt.outcome = "failed"
                attempt.completed_at = self._clock.now()

            task_in_state.status = TaskStatus.FAILED
            state.update_run(state.get_run(run_id))

            buffer.emit(
                TaskStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="task_status_changed",
                    task_id=task_id,
                    old_status=TaskStatus.BUILDING,
                    new_status=TaskStatus.FAILED,
                )
            )

            # Pause the run
            engine.pause_run(run_id, reason="script_failed", error_detail=output)

            await self._persist(state, run_id, buffer)

            logger.warning(f"Run {run_id}: script task {task_id} failed with exit code {exit_code}")
            return TransitionResult(success=True, new_status=TaskStatus.FAILED)

    async def submit_for_verification(self, run_id: str, task_id: str) -> TransitionResult:
        """Submit task for verification (BUILDING -> VERIFYING).

        Runs task-level auto-verify once before the checklist gate. If must-items
        fail, the transition is blocked and the task stays in BUILDING with
        actionable feedback on the current attempt.

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

        auto_verify_config = resolve_auto_verify_config(run, task.config_id, step_config_id_pre)
        if auto_verify_config is not None and self._auto_verify_runner is not None:
            project_path = _resolve_working_path(run)
            if project_path is not None:
                # Auto-commit any uncommitted changes before running auto-verify
                if run.worktree_path:
                    commit_uncommitted_changes(
                        Path(run.worktree_path),
                        f"Auto-commit builder changes for task {task_id}",
                    )

                av_results = await run_auto_verify(
                    auto_verify_config,
                    self._auto_verify_runner,
                    project_path,
                    variables=run.config,
                )

                # Store results in the current attempt (success or failure).
                if task.attempts:
                    task.attempts[-1].auto_verify_results = [r.model_dump() for r in av_results]

                all_must_passed, failing_must_ids = evaluate_auto_verify(
                    auto_verify_config, av_results
                )

                # Emit exactly one auto-verify event per submit attempt.
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

                # Crash detection happens before any phase transition.
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

                if all_must_passed:
                    # Auto-verify confirms work is done — mark OPEN checklist items as DONE
                    # so the checklist gate passes without requiring explicit self-reporting.
                    for item in task.checklist:
                        if item.status == ChecklistStatus.OPEN:
                            item.status = ChecklistStatus.DONE
                else:
                    # must:true items failed — block immediately instead of
                    # falling through to the engine gate.
                    if task.attempts:
                        failing_lines: list[str] = []
                        for av in av_results:
                            if av.item_id not in failing_must_ids:
                                continue
                            output = av.output.strip() if av.output else ""
                            snippet = output if output else "(no command output)"
                            failing_lines.append(
                                f"- [{av.item_id}] command `{av.cmd}` failed "
                                f"(exit {av.exit_code})\n  Output:\n{snippet}"
                            )
                        if failing_lines:
                            task.attempts[-1].verifier_comment = (
                                "Auto-verify failed. Fix the following and resubmit:\n"
                                + "\n".join(failing_lines)
                            )

                    await self._persist(state, run_id, buffer)
                    self._notify_submit(task_id)
                    return TransitionResult(
                        success=True,
                        new_status=TaskStatus.BUILDING,
                        error="Auto-verify must-items failed (pre-gate)",
                    )

        # --- Capture end commit for git tracking (before engine call so it's in the event) ---
        end_commit: str | None = None
        task_pre = state.get_task(run_id, task_id)
        if run.worktree_path and task_pre.attempts:
            worktree_path_obj = Path(run.worktree_path)
            # Auto-commit any uncommitted changes left by the builder agent.
            # Some CLI agents (e.g. codex) may not commit their work, and the
            # verifier's git checkout of end_commit would destroy those changes.
            commit_uncommitted_changes(
                worktree_path_obj, f"Auto-commit builder changes for task {task_id}"
            )
            end_commit = get_head_commit(worktree_path_obj)

        try:
            result = engine.submit_for_verification(run_id, task_id, end_commit=end_commit)
        except GateBlockedError:
            # Persist state to record the gate evaluation event
            await self._persist(state, run_id, buffer)
            raise

        if not result.success:
            await self._persist(state, run_id, buffer)
            return result

        # Store end commit on the attempt
        task = state.get_task(run_id, task_id)
        if end_commit and task.attempts:
            task.attempts[-1].end_commit = end_commit

        await self._persist(state, run_id, buffer)
        self._notify_submit(task_id)
        return result

    async def _run_step_auto_verify(
        self, run: Run, step: "StepState"
    ) -> tuple[bool, list[AutoVerifyResult]]:
        """Run step-level auto-verify items for a newly completed step.

        Returns (all_must_passed, results).
        """
        if run.routine_embedded is None or self._auto_verify_runner is None:
            return True, []

        routine_config = RoutineConfig.model_validate(run.routine_embedded)
        step_config = find_step_config(routine_config, step.config_id)
        if step_config is None or not step_config.step_auto_verify:
            return True, []

        # Build an AutoVerifyConfig from the step-level items
        av_config = AutoVerifyConfig(items=step_config.step_auto_verify)
        cwd = _resolve_working_path(run)
        if cwd is None:
            return True, []

        results = await run_auto_verify(av_config, self._auto_verify_runner, cwd)
        all_must_passed, _ = evaluate_auto_verify(av_config, results)
        return all_must_passed, results

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

        # Capture which steps were already completed before the engine runs
        prev_completed_step_ids = {s.config_id for s in run.steps if s.completed}

        engine, state, buffer = self._build_engine(run)
        result = engine.complete_verification(run_id, task_id)

        # Get the updated run after engine processing
        updated_run = state.get_run(run_id)

        # Run step_auto_verify for any newly completed steps
        if result.success:
            newly_completed = [
                s
                for s in updated_run.steps
                if s.completed and s.config_id not in prev_completed_step_ids
            ]
            for step in newly_completed:
                all_passed, _ = await self._run_step_auto_verify(updated_run, step)
                if not all_passed:
                    # Halt the run: mark it FAILED
                    old_run_status = updated_run.status
                    updated_run.status = RunStatus.FAILED
                    updated_run.last_error = f"Step '{step.config_id}' auto-verify failed"
                    updated_run.completed_at = self._clock.now()
                    state.update_run(updated_run)
                    buffer.emit(
                        RunStatusChanged(
                            timestamp=self._clock.now(),
                            run_id=run_id,
                            event_type="run_status_changed",
                            old_status=old_run_status,
                            new_status=RunStatus.FAILED,
                        )
                    )
                    break

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
        return await self._repo.list_all(limit=limit, include_action_logs=False)

    async def list_runs_recent(self, hours: int) -> list[Run]:
        """List runs created within the last N hours."""
        return await self._repo.list_recent(hours, include_action_logs=False)

    async def list_repo_names(self) -> list[str]:
        """List unique repository names across all runs."""
        return await self._repo.list_repo_names()

    async def list_runs_by_repo(self, repo_name: str) -> list[Run]:
        """List runs for a repository."""
        return await self._repo.list_by_repo(repo_name, include_action_logs=False)

    async def list_runs_by_status(self, status: RunStatus) -> list[Run]:
        """List runs filtered by status."""
        return await self._repo.list_by_status(status, include_action_logs=False)

    async def list_runs_by_repo_and_status(self, repo_name: str, status: RunStatus) -> list[Run]:
        """List runs filtered by both repository and status."""
        return await self._repo.list_by_repo_and_status(
            repo_name, status, include_action_logs=False
        )

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

        # Compress Q&A into compact decisions (pure function, always available).
        # Raw Q&A is archived in the artifact file; decisions are the compact form
        # passed downstream to prompt assembly.
        compressed: CompressedDecisions = compress_clarifications(request, response)

        # Persist compressed decisions in run.config so executor and prompt
        # endpoint can reconstruct them without re-querying clarification history.
        if compressed.decisions:
            run.config["_compressed_decisions"] = [
                {
                    "question": d.question,
                    "decision": d.decision,
                    "rationale": d.rationale,
                }
                for d in compressed.decisions
            ]
            run.config["_compressed_decisions_request_id"] = compressed.source_request_id
            await self._repo.save(run)

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
                decisions=compressed,
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

        # Load routine config if available for condition evaluation
        routine_config = None
        if run.routine_embedded is not None:
            try:
                routine_config = RoutineConfig.model_validate(run.routine_embedded)
            except Exception:
                # If routine config can't be loaded, continue without condition evaluation
                pass

        check_step_progression(
            run,
            routine_config=routine_config,
            clock=self._clock,
            emitter=None,  # Async emitter not compatible with sync protocol
            worktree_path=None,  # Not available in this context
            run_config=run.config,
        )
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
