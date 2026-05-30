"""Async workflow service wiring WorkflowEngine to persistent storage."""

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import (
    AgentRunnerType,
    ChecklistStatus,
    GateType,
    RunStatus,
    TaskStatus,
)
from orchestrator.config.global_config import GlobalConfig
from orchestrator.config.models import AutoVerifyConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.db import (
    AttemptModel,
    RunModel,
    RunRepository,
    SqliteEventStore,
    TaskModel,
    commit_with_event_outbox,
    create_wired_event_store_v2,
)
from orchestrator.workflow import (
    CompleteRunWorktreeCommitCommand,
    CompleteRunWorktreeResetCommand,
    DeleteRunCommand,
    FailRunWorktreeCommitCommand,
    FailRunWorktreeResetCommand,
    RecordClarificationRequestCommand,
    RecordTaskRevertedCommand,
    RequestRunWorktreeCommitCommand,
    RequestRunWorktreeCreationCommand,
    RequestRunWorktreeResetCommand,
    SetChecklistGradeCommand,
    UpdateChecklistItemCommand,
    UpdateLatestAttemptCommand,
    UpdateParentOversightFactsCommand,
    UpdateRunStatusCommand,
    UpdateRunWorktreeCommand,
    durable_parent_oversight_patch,
    FailRunWorktreeCreationCommand,
    handle_complete_run_worktree_commit,
    handle_create_run,
    handle_complete_run_worktree_reset,
    handle_delete_run,
    handle_fail_run_worktree_commit,
    handle_fail_run_worktree_creation,
    handle_fail_run_worktree_reset,
    handle_record_clarification_request,
    handle_record_task_reverted,
    handle_request_run_worktree_commit,
    handle_request_run_worktree_creation,
    handle_request_run_worktree_reset,
    handle_set_checklist_grade,
    handle_update_checklist_item,
    handle_update_latest_attempt,
    handle_update_parent_oversight_facts,
    handle_update_run_status,
    handle_update_run_worktree,
)
from orchestrator.workflow.commands.attempt_and_fanout import (
    CreateFanOutChildrenCommand,
    CreateTaskAttemptCommand,
    ResetFanOutChildrenCommand,
    RetryFanOutChildCommand,
    handle_create_fan_out_children,
    handle_create_task_attempt,
    handle_reset_fan_out_children,
    handle_retry_fan_out_child,
)
from orchestrator.workflow.commands.status_mutations import (
    UpdateTaskStatusCommand,
    handle_update_task_status,
)
from orchestrator.workflow.commands.clarifications import (
    RecordApprovalDecisionCommand,
    RecordClarificationResponseCommand,
    handle_record_approval_decision,
    handle_record_clarification_response,
)
from orchestrator.state.models import Attempt, ChecklistItem, Run, StepState, TaskState
from orchestrator.state.session import SessionStateManager
from orchestrator.state.errors import (
    ChecklistItemNotFoundError,
    RunNotFoundError,
    TaskNotFoundError,
)
from orchestrator.workflow.agent.auto_verify import (
    AutoVerifyResult,
    AutoVerifyRunner,
    evaluate_auto_verify,
    has_crashes,
    run_auto_verify,
)
from orchestrator.workflow.agent.clarifications import (
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
from orchestrator.workflow.agent.prompts import generate_builder_prompt, generate_recovery_prompt
from orchestrator.workflow.agent.templates import resolve_template
from orchestrator.workflow.engine.errors import GateBlockedError, InvalidTransitionError
from orchestrator.workflow.engine.gates import evaluate_checklist_gate
from orchestrator.workflow.events.logger import PersistentEventEmitter
from orchestrator.workflow import (
    EventSignalTransport,
    SignalQueue,
    SignalTransport,
    WorkflowSignal,
    build_create_run_command,
)
from orchestrator.workflow import (
    AgentChangedEvent,
    AttemptUpdated,
    ApprovalDecision,
    AutoVerifyCompleted,
    BufferingEmitter,
    ChildCompleted,
    ChildFailed,
    ChildSpawned,
    FanOutCompleted,
    FanOutSpawned,
    RunStepBackward,
    RunStatusChanged,
    TaskReverted,
    TaskStatusChanged,
    WorkflowEvent,
)
from orchestrator.workflow.locks import LockManager
from orchestrator.workflow.engine.transitions import (
    TransitionResult,
    check_run_completion,
    transition_from_approval,
    transition_from_clarification,
    transition_to_building,
    transition_to_pending_clarification,
    transition_to_recovering,
)
from orchestrator.workflow.completion import handle_run_completion
from orchestrator.workflow.delegation import (
    DelegateCommand,
    DelegateResultEnvelope,
    DelegatedWork,
    DelegationDecision,
    DelegationRecorder,
    FanOutDelegationPolicy,
    SuperParentDelegationPolicy,
    build_fan_out_facts,
    work_from_fan_out_child,
)
from orchestrator.workflow.oversight import validate_run_evidence_items
from orchestrator.workflow.parent_oversight import (
    ChildRunResolutionResult,
    ParentOversightService,
)
from orchestrator.git import (
    ParentChildMergeResult,
    WorktreeCommitError,
    WorktreeResetError,
    commit_uncommitted_changes_or_raise,
    get_head_commit,
    reset_worktree_changes,
    reset_worktree_to_ref,
)
from orchestrator.git.worktree import WorktreeManager
from orchestrator.envfiles.lifecycle import EnvFileLifecycle


_SELF_PAUSING_REASONS: frozenset[str] = frozenset(
    {
        "server_shutdown",
        "executor_not_started",
        "executor_exited",
        "executor_crash",
        "no_executor_running",
        "agent_not_running_on_startup",
        "rate_limit",
        "recovery_loop",
    }
)


# Cascade pause reasons: mirror parent intent. Errors keep the literal
# `parent_<reason>` so retryability checks remain stable; human-actionable
# pauses get a clearer label so children + dashboards can distinguish
# "human is reviewing parent" from "parent crashed".
_HUMAN_ACTIONABLE_CASCADE_REASONS: dict[str, str] = {
    "requirement_escalated": "parent_escalated_requirement",
    "awaiting_clarification": "parent_awaiting_clarification",
    "manual_pause": "parent_paused_manual",
    "gate_blocked": "parent_gate_blocked",
}


def _cascade_reason_for(parent_reason: str) -> str:
    """Map a parent's pause_reason to the child's cascade pause_reason."""
    mapped = _HUMAN_ACTIONABLE_CASCADE_REASONS.get(parent_reason)
    if mapped is not None:
        return mapped
    return f"parent_{parent_reason}"


@dataclass
class RecoveryResult:
    """Result of a run recovery operation.

    Returned by WorkflowService.recover_run(); translated to RecoverResponse
    by the API layer (api/routers/runs.py).
    """

    run_id: str
    status: str
    pause_reason: str | None = None
    current_step_index: int | None = None


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


def resolve_task_config(
    run: Run, task_config_id: str, step_config_id: str | None = None
) -> TaskConfig | None:
    """Resolve the TaskConfig for a task from the run's routine_embedded."""
    if run.routine_embedded is None:
        return None
    routine_config = RoutineConfig.model_validate(run.routine_embedded)
    return find_task_config(routine_config, task_config_id, step_config_id)


def resolve_step_config_id_for_task(run: Run, task_id: str) -> str | None:
    """Find the routine step config id for a runtime task id."""
    for step in run.steps:
        for task in step.tasks:
            if task.id == task_id:
                return step.config_id
    return None


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

    Pattern for legacy engine-backed mutations:
    1. Load Run from RunRepository into a temporary SessionStateManager
    2. Create BufferingEmitter, create WorkflowEngine(state, clock, emitter)
    3. Call engine method (sync)
    4. Persist the updated projection state
    5. event_emitter.emit_batch(buffered_events) (flushes events)
    6. session.commit() (atomic)
    """

    def __init__(
        self,
        session: AsyncSession,
        repo: RunRepository | None = None,
        event_emitter: PersistentEventEmitter | None = None,
        clock: Clock | None = None,
        auto_verify_runner: AutoVerifyRunner | None = None,
        lock_manager: LockManager | None = None,
        global_config: GlobalConfig | None = None,
        env_lifecycle: EnvFileLifecycle | None = None,
        signal_transport: SignalTransport | None = None,
        super_parent_policy: SuperParentDelegationPolicy | None = None,
        fan_out_policy: FanOutDelegationPolicy | None = None,
        event_store_v2: SqliteEventStore | None = None,
    ) -> None:
        self._session = session
        self._repo = repo or RunRepository(session)
        if event_store_v2 is None:
            self._store_v2 = create_wired_event_store_v2(session)
        else:
            self._store_v2 = event_store_v2
        self._event_emitter = event_emitter or PersistentEventEmitter(self._store_v2)
        self._clock = clock or _ServiceClock()
        self._auto_verify_runner = auto_verify_runner
        self._lock_manager = lock_manager
        self._global_config = global_config
        self._env_lifecycle = env_lifecycle
        self._signal_transport = signal_transport
        self._super_parent_policy = super_parent_policy or SuperParentDelegationPolicy()
        self._fan_out_policy = fan_out_policy or FanOutDelegationPolicy()
        self._delegation_recorder = DelegationRecorder(self._clock)
        self._parent_oversight = ParentOversightService(
            self._session,
            self._repo,
            self._event_emitter,
            self._clock,
            global_config=self._global_config,
            super_parent_policy=self._super_parent_policy,
            signal_transport=self._signal_transport,
        )

    async def _update_parent_oversight_facts(
        self,
        run_id: str,
        state: dict[str, Any],
    ) -> None:
        """Persist only durable workflow-owned oversight facts."""
        patch = durable_parent_oversight_patch(state)
        await handle_update_parent_oversight_facts(
            UpdateParentOversightFactsCommand(run_id=run_id, patch=patch),
            self._store_v2,
            self._session,
        )

    def _build_engine(
        self, run: Run
    ) -> tuple[WorkflowEngine, SessionStateManager, BufferingEmitter]:
        """Create an engine with a temporary in-memory state manager and buffering emitter."""
        state = SessionStateManager()
        state.add_run(run)
        buffer = BufferingEmitter()
        engine = WorkflowEngine(
            state,
            clock=self._clock,
            emitter=buffer,
            lock_manager=self._lock_manager,
            auto_complete_runs=False,
        )
        return engine, state, buffer

    def _attach_task_projection_payloads(
        self,
        state: SessionStateManager,
        run_id: str,
        events: list[WorkflowEvent],
    ) -> list[WorkflowEvent]:
        """Add read-model payloads to core task events emitted by WorkflowEngine."""
        projected_events: list[WorkflowEvent] = []
        for event in events:
            projected_events.append(event)
            if not isinstance(event, (AutoVerifyCompleted, TaskStatusChanged)) or not event.task_id:
                continue
            task = state.get_task(run_id, event.task_id)
            if isinstance(event, TaskStatusChanged):
                event.current_attempt = task.current_attempt
                event.attempt_snapshots = [
                    attempt.model_dump(mode="json") for attempt in task.attempts
                ]
                projected_events.extend(self._explicit_attempt_updates_from_snapshots(event))
            else:
                event.current_attempt = task.current_attempt
                event.checklist = [item.model_dump(mode="json") for item in task.checklist]
                event.latest_attempt_snapshot = (
                    task.attempts[-1].model_dump(mode="json") if task.attempts else None
                )
                update = self._explicit_attempt_update_from_snapshot(
                    event.run_id,
                    event.task_id,
                    event.timestamp,
                    event.latest_attempt_snapshot,
                )
                if update is not None:
                    projected_events.append(update)
        return projected_events

    def _explicit_attempt_updates_from_snapshots(
        self, event: TaskStatusChanged
    ) -> list[AttemptUpdated]:
        """Build focused attempt updates for fields otherwise buried in task snapshots."""
        updates: list[AttemptUpdated] = []
        for snapshot in event.attempt_snapshots:
            update = self._explicit_attempt_update_from_snapshot(
                event.run_id,
                event.task_id,
                event.timestamp,
                snapshot,
            )
            if update is not None:
                updates.append(update)
        return updates

    def _explicit_attempt_update_from_snapshot(
        self,
        run_id: str,
        task_id: str,
        timestamp: datetime,
        snapshot: dict[str, Any] | None,
    ) -> AttemptUpdated | None:
        """Return a focused attempt update when a snapshot has durable fields."""
        if not snapshot:
            return None
        attempt_id = snapshot.get("id")
        if not attempt_id:
            return None
        update = AttemptUpdated(
            timestamp=timestamp,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            verifier_comment=snapshot.get("verifier_comment"),
            grade_snapshot=snapshot.get("grade_snapshot") or None,
            agent_runner_type=snapshot.get("agent_runner_type"),
            agent_model=snapshot.get("agent_model"),
            agent_settings=snapshot.get("agent_settings") or None,
            start_commit=snapshot.get("start_commit"),
            end_commit=snapshot.get("end_commit"),
        )
        if (
            update.verifier_comment is not None
            or update.grade_snapshot is not None
            or update.agent_runner_type is not None
            or update.agent_model is not None
            or update.agent_settings is not None
            or update.start_commit is not None
            or update.end_commit is not None
        ):
            return update
        return None

    async def _persist(
        self, state: SessionStateManager, run_id: str, buffer: BufferingEmitter
    ) -> Run:
        """Append buffered events, let projectors update read models, then commit."""
        run = state.get_run(run_id)
        self._parent_oversight.strip_computed_oversight_for_persist(run)
        parent_run_id = run.parent_run_id
        events = self._attach_task_projection_payloads(state, run_id, buffer.drain())
        if events:
            await self._store_v2.append(events)
            self._event_emitter.notify_persisted_batch(events)
        if parent_run_id is not None:
            await self._refresh_parent_oversight_without_commit(parent_run_id)
        await commit_with_event_outbox(self._session)
        return await self._repo.get(run_id)

    async def save_run_with_oversight_terminal_guard(self, run: Run) -> Run:
        """Persist a run after applying any super-parent terminal guard."""
        persisted_status = await self._session.scalar(
            select(RunModel.status).where(RunModel.id == run.id)
        )
        old_status = RunStatus(persisted_status) if persisted_status is not None else run.status
        _, state, buffer = self._build_engine(run)
        await self._resolve_run_completion_transition(
            run,
            state,
            buffer,
            old_status=old_status,
        )
        return await self._persist(state, run.id, buffer)

    def _sanitize_agent_runner_config(self, agent_runner_config: dict[str, Any]) -> dict[str, Any]:
        """Sanitize agent runner config by removing sensitive keys.

        Creates a copy with settings like model, temperature, max_tokens, nudge settings,
        but excludes API keys, tokens, passwords, and other secrets.

        Args:
            agent_runner_config: The agent runner configuration dict

        Returns:
            A sanitized copy of the config without sensitive keys
        """
        sensitive_keys = {"api_key", "api_token", "password", "secret", "auth_token"}
        sanitized: dict[str, Any] = {}
        for key, value in agent_runner_config.items():
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

    def _get_signal_queue(self) -> SignalQueue:
        """Return a SignalQueue backed by the injected transport or EventSignalTransport."""
        if self._signal_transport is not None:
            return SignalQueue(self._signal_transport)
        from orchestrator.db import RunLifecycleProjector

        projector = RunLifecycleProjector()
        transport = EventSignalTransport(self._store_v2, projector)
        return SignalQueue(transport)

    # --- Delegating to WorkflowEngine ---

    async def cancel_run(self, run_id: str, reason: str | None = None) -> Run:
        """Cancel a run (ACTIVE/PAUSED -> FAILED) via signal queue.

        Enqueues a CANCEL signal; the consumer applies the DB transition.
        Returns the run in its current (pre-transition) state.
        """
        run = await self._repo.get(run_id)
        # Idempotency: if run is already in a terminal state, return it as-is.
        if run.status in (RunStatus.FAILED, RunStatus.COMPLETED):
            return run
        # DRAFT runs cannot be cancelled.
        if run.status == RunStatus.DRAFT:
            raise InvalidTransitionError(run.status.value, "failed")
        queue = self._get_signal_queue()
        payload: dict[str, Any] | None = {"reason": reason} if reason else None
        await queue.enqueue(run_id, WorkflowSignal.CANCEL, payload)
        await commit_with_event_outbox(self._session)
        return run

    async def apply_cancel_run(self, run_id: str, reason: str | None = None) -> Run:
        """Cancel a run (ACTIVE/PAUSED -> FAILED) via event append and projection.

        Called by the signal consumer and internal executor code.
        Handles worktree cleanup if the run has a worktree configured.
        """
        run = await self._repo.get(run_id)

        # Idempotency: if run is already in a terminal state, return it as-is.
        if run.status in (RunStatus.FAILED, RunStatus.COMPLETED):
            return run
        if run.status not in (RunStatus.ACTIVE, RunStatus.PAUSED, RunStatus.STOPPING):
            raise InvalidTransitionError(run.status.value, RunStatus.FAILED.value)

        await self._pause_or_cancel_run_for_parent_control(
            run,
            action="cancel",
            reason=reason or "cancel",
        )

        events = await handle_update_run_status(
            UpdateRunStatusCommand(
                run_id=run_id,
                old_status=run.status,
                new_status=RunStatus.FAILED,
                pause_reason=run.pause_reason,
                last_error=run.last_error,
                timestamp=self._clock.now(),
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(events[0])
        await commit_with_event_outbox(self._session)
        result = await self._repo.get(run_id)

        # Call env_lifecycle hook for run_end if run was cancelled
        if (
            self._env_lifecycle is not None
            and result.status == RunStatus.FAILED
            and result.worktree_path
            and result.env_file_specs
        ):
            worktree_path = Path(result.worktree_path)
            await self._env_lifecycle.on_run_end(
                run_id=run_id,
                repo_name=result.repo_name,
                worktree_path=worktree_path,
                success=False,
            )

        # Handle completion actions for cancelled (FAILED) runs
        if result.status == RunStatus.FAILED:
            worktree_manager = self._create_worktree_manager(result)
            if worktree_manager is not None:
                handle_run_completion(result, worktree_manager)

        return result

    async def start_run(self, run_id: str) -> Run:
        """Start a run (DRAFT -> ACTIVE) via signal queue.

        Enqueues a RUN_START signal; the consumer applies the DB transition.
        Returns the run in its current (pre-transition) state.
        """
        run = await self._repo.get(run_id)
        if run.status != RunStatus.DRAFT:
            raise InvalidTransitionError(run.status.value, "start_run (requires DRAFT)")
        queue = self._get_signal_queue()
        await queue.enqueue(run_id, WorkflowSignal.RUN_START)
        await commit_with_event_outbox(self._session)
        return run

    async def apply_start_run(self, run_id: str) -> Run:
        """Start a run (DRAFT -> ACTIVE) via event append and projection.

        Called by the signal consumer and internal executor code.
        """
        import logging

        logger = logging.getLogger(__name__)

        run = await self._repo.get(run_id)
        logger.info(
            f"Starting run {run_id}: agent_runner_type={run.agent_runner_type}, "
            f"repo={run.repo_name}, routine={run.routine_id}"
        )

        if run.status != RunStatus.DRAFT:
            raise InvalidTransitionError(run.status.value, RunStatus.ACTIVE.value)

        now = self._clock.now()
        events = await handle_update_run_status(
            UpdateRunStatusCommand(
                run_id=run_id,
                old_status=run.status,
                new_status=RunStatus.ACTIVE,
                timestamp=now,
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(events[0])
        await commit_with_event_outbox(self._session)
        result = await self._repo.get(run_id)

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

        return result

    async def apply_stop_run(self, run_id: str) -> Run:
        """Transition a run from ACTIVE to STOPPING via the event stream.

        Called from pause_run() to make the stop observable before the
        PAUSE signal is processed by the consumer.
        """
        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(run.status.value, RunStatus.STOPPING.value)
        events = await handle_update_run_status(
            UpdateRunStatusCommand(
                run_id=run_id,
                old_status=run.status,
                new_status=RunStatus.STOPPING,
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(events[0])
        await commit_with_event_outbox(self._session)
        return await self._repo.get(run_id)

    async def _pause_or_cancel_run_for_parent_control(
        self,
        parent: Run,
        *,
        action: Literal["pause", "cancel"],
        reason: str,
        error_detail: str | None = None,
    ) -> None:
        """Pause/cancel active/suspending child runs when a parent run is controlled."""
        # System-wide pauses (server shutdown, rate limits, executor crashes) hit
        # every run's asyncio loop independently; each loop self-pauses with the
        # correct reason. Cascading from the parent would clobber that with a
        # `parent_*` prefix that downstream recovery paths do not recognize.
        if action == "pause" and reason in _SELF_PAUSING_REASONS:
            return

        children = await self._repo.list_child_runs(parent.id, include_action_logs=False)
        control_reason = _cascade_reason_for(reason)

        for child in children:
            if child.status not in (RunStatus.ACTIVE, RunStatus.STOPPING):
                continue
            try:
                if action == "pause":
                    await self._pause_child_run(child, control_reason, error_detail)
                else:
                    await self._cancel_child_run(child, control_reason)
            except InvalidTransitionError:
                # Child states can change while the parent is being controlled;
                # do not fail parent control because one child raced to terminal.
                continue

    async def pause_run(
        self,
        run_id: str,
        reason: str = "manual_pause",
        error_detail: str | None = None,
    ) -> Run:
        """Pause a run (ACTIVE -> STOPPING -> PAUSED) via signal queue.

        Immediately transitions ACTIVE → STOPPING so the stop is observable,
        then enqueues a PAUSE signal for the consumer to apply STOPPING → PAUSED.
        Returns the run in STOPPING state.
        Raises InvalidTransitionError if the run is not ACTIVE.
        """
        run = await self._repo.get(run_id)
        if run.status != RunStatus.ACTIVE:
            raise InvalidTransitionError(run.status.value, "paused")
        # Immediately visible: ACTIVE → STOPPING
        stopping_run = await self.apply_stop_run(run_id)
        queue = self._get_signal_queue()
        payload: dict[str, Any] = {"reason": reason}
        if error_detail:
            payload["error_detail"] = error_detail
        await queue.enqueue(run_id, WorkflowSignal.PAUSE, payload)
        await commit_with_event_outbox(self._session)
        return stopping_run

    async def _pause_child_run(
        self,
        child: Run,
        reason: str,
        error_detail: str | None = None,
    ) -> None:
        """Pause a single child run via event append and projection.

        Also enqueues a PAUSE signal on the child's queue so the child's
        RunWorkflow can observe the cascade and exit its execution loop on
        the next iteration. Without the signal the child's loop only
        notices the cascade when it next reads run state from the DB,
        which can be a long time if it is mid-subprocess (e.g. waiting on
        an LLM turn) — a window during which the child's nudger may kill
        the subprocess for spurious "stuck" reasons.
        """
        if child.status not in (RunStatus.ACTIVE, RunStatus.STOPPING):
            raise InvalidTransitionError(child.status.value, RunStatus.PAUSED.value)

        now = self._clock.now()
        current_status = child.status
        if current_status == RunStatus.ACTIVE:
            events = await handle_update_run_status(
                UpdateRunStatusCommand(
                    run_id=child.id,
                    old_status=RunStatus.ACTIVE,
                    new_status=RunStatus.STOPPING,
                    timestamp=now,
                ),
                self._store_v2,
                self._session,
            )
            self._event_emitter.notify_persisted(events[0])
            current_status = RunStatus.STOPPING

        events = await handle_update_run_status(
            UpdateRunStatusCommand(
                run_id=child.id,
                old_status=current_status,
                new_status=RunStatus.PAUSED,
                pause_reason=reason,
                last_error=error_detail,
                timestamp=now,
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(events[0])

        for step in child.steps:
            for task in step.tasks:
                if task.parent_task_id is not None:
                    continue
                if task.status not in (TaskStatus.BUILDING, TaskStatus.VERIFYING):
                    continue
                latest_attempt = max(
                    task.attempts,
                    key=lambda attempt: attempt.attempt_num,
                    default=None,
                )
                if latest_attempt is None or latest_attempt.completed_at is not None:
                    continue
                await handle_update_latest_attempt(
                    UpdateLatestAttemptCommand(
                        run_id=child.id,
                        task_id=task.id,
                        attempt_id=latest_attempt.id,
                        outcome="paused",
                        paused_at=now.isoformat(),
                    ),
                    self._store_v2,
                    self._session,
                )

        if child.parent_run_id is not None:
            await self._refresh_parent_oversight_without_commit(child.parent_run_id)
        await commit_with_event_outbox(self._session)

        # Best-effort PAUSE signal so the child's loop exits cleanly between
        # iterations. Failures here are non-fatal — the DB state change above
        # is the source of truth.
        import logging as _logging

        _cascade_logger = _logging.getLogger(__name__)
        try:
            queue = self._get_signal_queue()
            await queue.enqueue(
                child.id,
                WorkflowSignal.PAUSE,
                {"reason": reason, "cascade_from_parent": True},
            )
        except Exception:
            _cascade_logger.debug(
                f"Run {child.id}: failed to enqueue cascade PAUSE signal "
                "(child DB state already paused)"
            )

    async def _cancel_child_run(self, child: Run, reason: str) -> None:
        """Cancel a single child run via event append and projection."""
        if child.status not in (RunStatus.ACTIVE, RunStatus.PAUSED, RunStatus.STOPPING):
            raise InvalidTransitionError(child.status.value, RunStatus.FAILED.value)
        events = await handle_update_run_status(
            UpdateRunStatusCommand(
                run_id=child.id,
                old_status=child.status,
                new_status=RunStatus.FAILED,
                pause_reason=child.pause_reason,
                last_error=child.last_error,
                timestamp=self._clock.now(),
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(events[0])
        if child.parent_run_id is not None:
            await self._refresh_parent_oversight_without_commit(child.parent_run_id)
        await commit_with_event_outbox(self._session)

    async def apply_pause_run(
        self,
        run_id: str,
        reason: str = "manual_pause",
        error_detail: str | None = None,
    ) -> Run:
        """Pause a run (ACTIVE/STOPPING -> PAUSED) via event append and projection.

        Called by the signal consumer and internal executor code.
        """
        run = await self._repo.get(run_id)
        if run.status == RunStatus.PAUSED:
            return run
        if run.status not in (RunStatus.ACTIVE, RunStatus.STOPPING):
            raise InvalidTransitionError(run.status.value, RunStatus.PAUSED.value)

        await self._pause_or_cancel_run_for_parent_control(
            run,
            action="pause",
            reason=reason,
            error_detail=error_detail,
        )

        now = self._clock.now()
        events = await handle_update_run_status(
            UpdateRunStatusCommand(
                run_id=run_id,
                old_status=run.status,
                new_status=RunStatus.PAUSED,
                pause_reason=reason,
                last_error=error_detail,
                timestamp=now,
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(events[0])

        for step in run.steps:
            for task in step.tasks:
                if task.parent_task_id is not None:
                    continue
                if task.status not in (TaskStatus.BUILDING, TaskStatus.VERIFYING):
                    continue
                latest_attempt = max(
                    task.attempts,
                    key=lambda attempt: attempt.attempt_num,
                    default=None,
                )
                if latest_attempt is None or latest_attempt.completed_at is not None:
                    continue
                await handle_update_latest_attempt(
                    UpdateLatestAttemptCommand(
                        run_id=run_id,
                        task_id=task.id,
                        attempt_id=latest_attempt.id,
                        outcome="paused",
                        paused_at=now.isoformat(),
                    ),
                    self._store_v2,
                    self._session,
                )

        await commit_with_event_outbox(self._session)
        return await self._repo.get(run_id)

    async def resume_run(
        self,
        run_id: str,
        agent_runner_type: AgentRunnerType | None = None,
        agent_runner_config: dict[str, object] | None = None,
        resume_strategy: str | None = None,
    ) -> Run:
        """Resume a run (PAUSED -> ACTIVE) via signal queue.

        Enqueues a RESUME signal; the consumer applies the DB transition.
        Returns the run in its current (pre-transition) state.
        Raises InvalidTransitionError if the run is not in a resumable state.
        """
        run = await self._repo.get(run_id)
        if run.status != RunStatus.PAUSED:
            raise InvalidTransitionError(run.status.value, "active")
        queue = self._get_signal_queue()
        payload: dict[str, Any] = {}
        if agent_runner_type is not None:
            payload["agent_runner_type"] = agent_runner_type.value
        if agent_runner_config is not None:
            payload["agent_runner_config"] = agent_runner_config
        if resume_strategy is not None:
            payload["resume_strategy"] = resume_strategy
        await queue.enqueue(run_id, WorkflowSignal.RESUME, payload or None)
        await commit_with_event_outbox(self._session)
        return run

    async def apply_resume_run(
        self,
        run_id: str,
        agent_runner_type: AgentRunnerType | None = None,
        agent_runner_config: dict[str, object] | None = None,
        resume_strategy: str | None = None,
    ) -> Run:
        """Resume a run (PAUSED -> ACTIVE).

        Called by the signal consumer and internal executor code.

        Args:
            run_id: The run ID
            agent_runner_type: Optional new agent runner type to use
            agent_runner_config: Optional new agent runner config to use
            resume_strategy: "continue" (default) or "revert" to reset current phase

        Returns:
            The updated run
        """
        run = await self._repo.get(run_id)

        # Apply revert strategy if requested
        if resume_strategy == "revert":
            if run.status != RunStatus.PAUSED:
                raise InvalidTransitionError(run.status.value, RunStatus.ACTIVE.value)
            for step in run.steps:
                for task in step.tasks:
                    if task.status in (TaskStatus.BUILDING, TaskStatus.VERIFYING):
                        reverted_from = task.status
                        if (
                            task.status == TaskStatus.BUILDING
                            and task.attempts
                            and task.attempts[-1].start_commit
                            and run.worktree_path
                        ):
                            await self._run_event_sourced_worktree_reset(
                                run_id=run_id,
                                worktree_path=run.worktree_path,
                                reset_type="checkout_ref",
                                target_ref=task.attempts[-1].start_commit,
                                branch_name=f"orchestrator/run-{run.id}",
                                reason="resume_revert_phase_start",
                            )
                        self._revert_task_to_phase_start(task, run, self._clock.now())
                        events = await handle_record_task_reverted(
                            RecordTaskRevertedCommand(
                                run_id=run_id,
                                task_id=task.id,
                                reverted_from_status=reverted_from,
                                task_snapshot=task.model_dump(mode="json"),
                            ),
                            self._store_v2,
                            self._session,
                        )
                        self._event_emitter.notify_persisted(events[0])
                        break  # Only revert the first active task
                else:
                    continue
                break

            if agent_runner_type is not None or agent_runner_config is not None:
                old_agent = run.agent_runner_type
                old_config = run.agent_runner_config or {}

                # Determine new agent runner type: use provided type or keep existing
                new_agent = agent_runner_type if agent_runner_type is not None else old_agent
                new_config = agent_runner_config if agent_runner_config is not None else old_config

                if (old_agent != new_agent or old_config != new_config) and new_agent is not None:
                    event = AgentChangedEvent(
                        timestamp=self._clock.now(),
                        run_id=run_id,
                        event_type="agent_changed",
                        old_agent=old_agent or AgentRunnerType.CLI_SUBPROCESS,
                        new_agent=new_agent,
                        old_agent_runner_config=old_config,
                        new_agent_runner_config=new_config,
                        reason="user_changed_on_resume",
                    )
                    await self._store_v2.append([event])
                    self._event_emitter.notify_persisted(event)

            events = await handle_update_run_status(
                UpdateRunStatusCommand(
                    run_id=run_id,
                    old_status=run.status,
                    new_status=RunStatus.ACTIVE,
                    pause_reason=None,
                    last_error=None,
                    timestamp=self._clock.now(),
                ),
                self._store_v2,
                self._session,
            )
            self._event_emitter.notify_persisted(events[0])
            await commit_with_event_outbox(self._session)
            return await self._repo.get(run_id)

        if run.status != RunStatus.PAUSED:
            raise InvalidTransitionError(run.status.value, RunStatus.ACTIVE.value)

        # For continue strategy: clear paused_at/outcome on paused attempts so they
        # can continue where they left off.
        # Skip fan-out children — they are managed by the executor directly.
        for step in run.steps:
            for task in step.tasks:
                if task.parent_task_id is not None:
                    continue
                if task.status not in (TaskStatus.BUILDING, TaskStatus.VERIFYING):
                    continue
                latest_attempt = max(
                    task.attempts,
                    key=lambda attempt: attempt.attempt_num,
                    default=None,
                )
                if latest_attempt is None or latest_attempt.outcome != "paused":
                    continue
                await handle_update_latest_attempt(
                    UpdateLatestAttemptCommand(
                        run_id=run_id,
                        task_id=task.id,
                        attempt_id=latest_attempt.id,
                        clear_paused_state=True,
                    ),
                    self._store_v2,
                    self._session,
                )

        if agent_runner_type is not None or agent_runner_config is not None:
            old_agent = run.agent_runner_type
            old_config = run.agent_runner_config or {}

            # Determine new agent runner type: use provided type or keep existing
            new_agent = agent_runner_type if agent_runner_type is not None else old_agent
            new_config = agent_runner_config if agent_runner_config is not None else old_config

            if (old_agent != new_agent or old_config != new_config) and new_agent is not None:
                event = AgentChangedEvent(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="agent_changed",
                    old_agent=old_agent or AgentRunnerType.CLI_SUBPROCESS,
                    new_agent=new_agent,
                    old_agent_runner_config=old_config,
                    new_agent_runner_config=new_config,
                    reason="user_changed_on_resume",
                )
                await self._store_v2.append([event])
                self._event_emitter.notify_persisted(event)

        events = await handle_update_run_status(
            UpdateRunStatusCommand(
                run_id=run_id,
                old_status=run.status,
                new_status=RunStatus.ACTIVE,
                pause_reason=None,
                last_error=None,
                timestamp=self._clock.now(),
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(events[0])
        await commit_with_event_outbox(self._session)
        return await self._repo.get(run_id)

    async def _run_event_sourced_worktree_reset(
        self,
        *,
        run_id: str,
        worktree_path: str | None,
        reset_type: str,
        reason: str,
        target_ref: str | None = None,
        branch_name: str | None = None,
    ) -> None:
        event_worktree_path = worktree_path or ""
        head_before = get_head_commit(Path(worktree_path)) if worktree_path else None
        request_events = await handle_request_run_worktree_reset(
            RequestRunWorktreeResetCommand(
                run_id=run_id,
                worktree_path=event_worktree_path,
                reset_type=reset_type,
                target_ref=target_ref,
                branch_name=branch_name,
                head_before=head_before,
                reason=reason,
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(request_events[0])
        await commit_with_event_outbox(self._session)

        try:
            if not worktree_path:
                raise WorktreeResetError("", "run has no worktree_path")
            if reset_type == "discard_changes":
                result = reset_worktree_changes(worktree_path)
            else:
                if target_ref is None:
                    raise WorktreeResetError(worktree_path, "target_ref is required")
                if branch_name is None:
                    raise WorktreeResetError(worktree_path, "branch_name is required")
                result = reset_worktree_to_ref(
                    worktree_path,
                    branch_name=branch_name,
                    target_ref=target_ref,
                )
        except WorktreeResetError as exc:
            failed_events = await handle_fail_run_worktree_reset(
                FailRunWorktreeResetCommand(
                    run_id=run_id,
                    worktree_path=event_worktree_path,
                    reset_type=reset_type,
                    error=str(exc),
                    target_ref=target_ref,
                    branch_name=branch_name,
                    head_before=head_before,
                    reason=reason,
                ),
                self._store_v2,
                self._session,
            )
            self._event_emitter.notify_persisted(failed_events[0])
            await commit_with_event_outbox(self._session)
            raise

        complete_events = await handle_complete_run_worktree_reset(
            CompleteRunWorktreeResetCommand(
                run_id=run_id,
                worktree_path=event_worktree_path,
                reset_type=reset_type,
                target_ref=target_ref,
                branch_name=branch_name,
                head_before=result.head_before,
                head_after=result.head_after,
                reason=reason,
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(complete_events[0])
        await commit_with_event_outbox(self._session)

    async def _run_event_sourced_worktree_commit(
        self,
        *,
        run_id: str,
        task_id: str,
        attempt_id: str | None,
        worktree_path: str,
        message: str,
        commit_type: str,
        reason: str,
    ) -> str | None:
        path = Path(worktree_path)
        if not path.exists() or not path.is_dir():
            head_before = None
        else:
            head_before = get_head_commit(path)
        request_events = await handle_request_run_worktree_commit(
            RequestRunWorktreeCommitCommand(
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt_id,
                worktree_path=worktree_path,
                commit_type=commit_type,
                message=message,
                reason=reason,
                head_before=head_before,
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(request_events[0])
        await commit_with_event_outbox(self._session)

        if path.exists() and path.is_dir() and head_before is None:
            complete_events = await handle_complete_run_worktree_commit(
                CompleteRunWorktreeCommitCommand(
                    run_id=run_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    worktree_path=worktree_path,
                    commit_type=commit_type,
                    message=message,
                    created_commit=False,
                    reason=reason,
                    head_before=None,
                    head_after=None,
                    commit_sha=None,
                ),
                self._store_v2,
                self._session,
            )
            self._event_emitter.notify_persisted(complete_events[0])
            await commit_with_event_outbox(self._session)
            return None

        try:
            result = commit_uncommitted_changes_or_raise(path, message)
        except WorktreeCommitError as exc:
            failed_events = await handle_fail_run_worktree_commit(
                FailRunWorktreeCommitCommand(
                    run_id=run_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    worktree_path=worktree_path,
                    commit_type=commit_type,
                    message=message,
                    error=str(exc),
                    reason=reason,
                    head_before=head_before,
                ),
                self._store_v2,
                self._session,
            )
            self._event_emitter.notify_persisted(failed_events[0])
            await commit_with_event_outbox(self._session)
            raise

        complete_events = await handle_complete_run_worktree_commit(
            CompleteRunWorktreeCommitCommand(
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt_id,
                worktree_path=worktree_path,
                commit_type=commit_type,
                message=message,
                created_commit=result.created_commit,
                reason=reason,
                head_before=result.head_before,
                head_after=result.head_after,
                commit_sha=result.commit_sha,
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(complete_events[0])
        await commit_with_event_outbox(self._session)
        return result.head_after

    async def recover_run(
        self,
        run_id: str,
        target_task_id: str,
        additional_attempts: int = 1,
        agent_runner_type: AgentRunnerType | None = None,
        agent_runner_config: dict[str, object] | None = None,
        preserve_checklist: bool = False,
        guidance: str | None = None,
        reset_branch: bool = True,
    ) -> RecoveryResult:
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
        target_original_status = target_task.status
        downstream_original_status_by_id = {task.id: task.status for _, _, task in downstream}
        original_status = run.status
        rewind_from_step_index = max(
            [target_step_index, *(step_index for step_index, _, _ in downstream)]
        )

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

        # Restore worktree to the commit before the target task's first attempt,
        # so the branch is in the same state as when the task was first queued.
        # When reset_branch=False the branch is left as-is ("carry on" mode).
        if reset_branch and run.worktree_path:
            target_ref = restore_commit or run.source_branch
            if target_ref is not None:
                await self._run_event_sourced_worktree_reset(
                    run_id=run_id,
                    worktree_path=run.worktree_path,
                    reset_type="checkout_ref",
                    target_ref=target_ref,
                    branch_name=f"orchestrator/run-{run.id}",
                    reason="recovery_reset_branch",
                )

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
            active_attempt.agent_runner_type = run.agent_runner_type
            active_attempt.agent_model = run.agent_runner_config.get("model")
            active_attempt.agent_settings = self._sanitize_agent_runner_config(
                run.agent_runner_config
            )

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
        run.last_error = None
        run.completed_at = None
        run.updated_at = now

        events_to_emit: list[WorkflowEvent] = [
            RunStepBackward(
                timestamp=now,
                run_id=run_id,
                event_type="run_step_backward",
                from_step_index=rewind_from_step_index,
                to_step_index=target_step_index,
                reason="recovered",
            ),
            TaskReverted(
                timestamp=now,
                run_id=run_id,
                event_type="task_reverted",
                task_id=target_task.id,
                reverted_from_status=target_original_status,
                task_snapshot=target_task.model_dump(mode="json"),
            ),
        ]
        for _, _, task in downstream:
            events_to_emit.append(
                TaskReverted(
                    timestamp=now,
                    run_id=run_id,
                    event_type="task_reverted",
                    task_id=task.id,
                    reverted_from_status=downstream_original_status_by_id[task.id],
                    task_snapshot=task.model_dump(mode="json"),
                )
            )

        old_agent = run.agent_runner_type
        old_agent_runner_config = run.agent_runner_config or {}
        new_agent = agent_runner_type if agent_runner_type is not None else old_agent
        new_agent_runner_config = (
            agent_runner_config if agent_runner_config is not None else old_agent_runner_config
        )
        if agent_runner_type is not None:
            run.agent_runner_type = agent_runner_type
        if agent_runner_config is not None:
            run.agent_runner_config = agent_runner_config

        if (
            old_agent != new_agent or old_agent_runner_config != new_agent_runner_config
        ) and new_agent is not None:
            events_to_emit.append(
                AgentChangedEvent(
                    timestamp=now,
                    run_id=run_id,
                    event_type="agent_changed",
                    old_agent=old_agent or AgentRunnerType.CLI_SUBPROCESS,
                    new_agent=new_agent,
                    old_agent_runner_config=old_agent_runner_config,
                    new_agent_runner_config=new_agent_runner_config,
                    reason="user_changed_on_recovery",
                )
            )

        events_to_emit.append(
            RunStatusChanged(
                timestamp=now,
                run_id=run_id,
                event_type="run_status_changed",
                old_status=original_status,
                new_status=RunStatus.PAUSED,
                pause_reason="recovered",
                last_error=None,
            )
        )

        await self._event_emitter.emit_batch(events_to_emit)
        await commit_with_event_outbox(self._session)

        return RecoveryResult(
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
                attempt.agent_runner_type = run.agent_runner_type
                attempt.agent_model = run.agent_runner_config.get("model")
                attempt.agent_settings = self._sanitize_agent_runner_config(run.agent_runner_config)
                # Revert restores the worktree to the previous start_commit,
                # so the new attempt starts from the same point.
                if len(task.attempts) >= 2:
                    attempt.start_commit = task.attempts[-2].start_commit

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
                attempt.agent_runner_type = run.agent_runner_type
                attempt.agent_model = run.agent_runner_config.get("model")
                attempt.agent_settings = self._sanitize_agent_runner_config(run.agent_runner_config)

            # No checkout needed — worktree is already at end_commit
            # (submit_for_verification auto-commits and captures HEAD).

    def _checkout_on_branch(self, worktree_path: str, run_id: str, commit_sha: str) -> bool:
        """Move the run's branch to a commit without detaching HEAD."""
        import logging

        branch_name = f"orchestrator/run-{run_id}"
        try:
            reset_worktree_to_ref(
                worktree_path,
                branch_name=branch_name,
                target_ref=commit_sha,
            )
        except WorktreeResetError as exc:
            logging.getLogger(__name__).warning(
                f"Failed to checkout -B {branch_name} {commit_sha} in {worktree_path}: {exc}"
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

        from orchestrator.workflow.agent.templates import derive_output_path

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

        existing_children = self._fan_out_children_for_parent(run, parent_task.id)
        if existing_children:
            facts, works = build_fan_out_facts(parent_task, existing_children)
            duplicate_decision = self._fan_out_policy.reduce(facts.model_dump(), works, {})
            oversight_state = self._delegation_recorder.record_decision(
                run.oversight_state,
                duplicate_decision,
            )
            await self._update_parent_oversight_facts(run.id, oversight_state)
            await commit_with_event_outbox(self._session)
            return existing_children

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

            from orchestrator.state._utils import generate_id

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
                child_id=generate_id(),  # Stable UUID for this child (durable across restarts)
            )
            children.append(child)

        # Persist children directly so concurrent child updates don't rewrite the full run graph.
        await handle_create_fan_out_children(
            CreateFanOutChildrenCommand(
                run_id=run_id,
                step_id=parent_step.id,
                parent_task_id=task_id,
                children=[
                    {
                        "id": child.id,
                        "config_id": child.config_id,
                        "title": child.title,
                        "complexity": child.complexity or "standard",
                        "order_index": child.fan_out_index
                        if child.fan_out_index is not None
                        else i,
                        "checklist": [item.model_dump(mode="json") for item in child.checklist],
                        "max_attempts": child.max_attempts,
                        "has_verification": child.has_verification,
                        "fan_out_index": child.fan_out_index,
                        "fan_out_input": child.fan_out_input,
                        "fan_out_output": child.fan_out_output,
                        "child_id": child.child_id,
                    }
                    for i, child in enumerate(children)
                ],
                parent_new_status=TaskStatus.FAN_OUT_RUNNING,
            ),
            self._store_v2,
            self._session,
        )
        if not children:
            await handle_update_task_status(
                UpdateTaskStatusCommand(
                    run_id=run_id,
                    task_id=task_id,
                    old_status=parent_task.status,
                    new_status=TaskStatus.FAN_OUT_RUNNING,
                ),
                self._store_v2,
                self._session,
            )
        await commit_with_event_outbox(self._session)

        refreshed_run = await self._repo.get(run_id)
        refreshed_parent = self._find_task(refreshed_run, task_id)
        refreshed_children = self._fan_out_children_for_parent(refreshed_run, task_id)
        facts, works = build_fan_out_facts(refreshed_parent, refreshed_children)
        oversight_state = self._delegation_recorder.record_decision(
            refreshed_run.oversight_state,
            self._fan_out_policy.reduce(facts.model_dump(), works, {}),
        )
        oversight_state = self._record_fan_out_child_launches(
            oversight_state,
            refreshed_children,
        )
        await self._update_parent_oversight_facts(run_id, oversight_state)
        await commit_with_event_outbox(self._session)

        # Emit FanOutSpawned parent aggregation event + ChildSpawned per-child events.
        # Commit immediately so the write transaction is closed before concurrent child execution.
        if children:
            events_to_emit = [
                FanOutSpawned(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="fan_out_spawned",
                    parent_task_id=task_id,
                    child_count=len(children),
                )
            ] + [
                ChildSpawned(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="child_spawned",
                    parent_task_id=task_id,
                    child_task_id=child.id,
                    child_id=child.child_id or "",
                    fan_out_index=child.fan_out_index or 0,
                    fan_out_input=child.fan_out_input,
                )
                for child in children
            ]
            await self._event_emitter.emit_batch(events_to_emit)
            await commit_with_event_outbox(self._session)

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

        Uses event-sourced parent status, step completion, and run pause
        updates to keep events_v2 replay aligned with the live read model.

        Args:
            run_id: The run ID
            task_id: The parent task ID (must be FAN_OUT_RUNNING)
            all_passed: True if all children completed successfully
            to_verifying: If True and all_passed, move to VERIFYING (for outer LLM verifier)
        """
        import logging
        from orchestrator.workflow import StepCompleted

        logger = logging.getLogger(__name__)

        # Determine new status up front.
        if not all_passed:
            new_status = TaskStatus.FAILED
            pause_run = True
            pause_reason: str | None = "fan_out_child_failed"
        elif to_verifying:
            new_status = TaskStatus.VERIFYING
            pause_run = False
            pause_reason = None
        else:
            new_status = TaskStatus.COMPLETED
            pause_run = False
            pause_reason = None

        # Load just the parent task model with its step and run.
        # Critically: get_task_model does NOT load sibling task rows, so there
        # is no TaskModel.attempts cascade to clobber when we flush.  This avoids
        # the delete-orphan corruption that the old full-run merge
        # approach caused when concurrent child sessions had just committed.
        task_model = await self._repo.get_task_model(task_id)

        old_status_value = str(getattr(task_model, "status"))
        completion_decision = self._fan_out_policy.decision_for_parent_completion(
            old_status_value,
            all_passed=all_passed,
            to_verifying=to_verifying,
        )
        if completion_decision.kind == "stale_command_ignored":
            logger.info(
                f"Run {run_id}: fan-out parent {task_id} already "
                f"{old_status_value}, skipping complete_fan_out_parent"
            )
            return
        if completion_decision.kind == "review":
            raise InvalidTransitionError(
                old_status_value,
                "complete_fan_out_parent (requires FAN_OUT_RUNNING)",
            )

        run_snapshot = await self._repo.get(run_id)
        parent_step_snapshot: StepState | None = None
        step_order_index = 0
        for index, step in enumerate(run_snapshot.steps):
            if any(task.id == task_id for task in step.tasks):
                parent_step_snapshot = step
                step_order_index = index
                break
        if parent_step_snapshot is None:
            raise TaskNotFoundError(run_id, task_id)
        parent_snapshot = self._find_task(run_snapshot, task_id)
        child_snapshots = self._fan_out_children_for_parent(run_snapshot, task_id)
        facts, works = build_fan_out_facts(parent_snapshot, child_snapshots)
        aggregation_decision = self._fan_out_policy.reduce(facts.model_dump(), works, {})
        run_oversight_state = self._delegation_recorder.record_decision(
            run_snapshot.oversight_state,
            aggregation_decision,
        )
        if aggregation_decision.kind == "wait":
            await self._update_parent_oversight_facts(run_id, run_oversight_state)
            await commit_with_event_outbox(self._session)
            return
        if aggregation_decision.kind == "review":
            await self._update_parent_oversight_facts(run_id, run_oversight_state)
            await commit_with_event_outbox(self._session)
            raise InvalidTransitionError(
                old_status_value,
                "complete_fan_out_parent (fan-out state requires review)",
            )
        for child_snapshot in child_snapshots:
            run_oversight_state = self._record_fan_out_child_terminal_result(
                run_oversight_state,
                child_snapshot,
            )
        run_oversight_state = self._delegation_recorder.record_result(
            run_oversight_state,
            DelegateResultEnvelope(
                work_id=task_id,
                generation=parent_snapshot.current_attempt,
                terminal_status="completed" if all_passed else "failed",
                outcome=completion_decision.reason,
                validation_status="valid",
                integration_ready=all_passed,
                reasons=() if all_passed else ("fan_out_child_failed",),
            ),
            completion_decision,
        )
        await self._update_parent_oversight_facts(run_id, run_oversight_state)

        step_id = parent_step_snapshot.id
        old_run_status_value = run_snapshot.status.value

        # Fetch child counts for the FanOutCompleted event via a targeted query.
        completed_count, failed_count = await self._repo.count_fan_out_children(task_id)

        # Emit all events (persisted via event store in the same transaction).
        old_status = TaskStatus(old_status_value)
        old_run_status = RunStatus(old_run_status_value)

        events_to_emit: list[Any] = [
            TaskStatusChanged(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="task_status_changed",
                task_id=task_id,
                old_status=old_status,
                new_status=new_status,
            ),
            FanOutCompleted(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="fan_out_completed",
                parent_task_id=task_id,
                all_passed=all_passed,
                completed_count=completed_count,
                failed_count=failed_count,
            ),
        ]

        if new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            events_to_emit.append(
                StepCompleted(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="step_completed",
                    step_index=step_order_index,
                    step_id=step_id,
                )
            )

        if pause_run:
            events_to_emit.append(
                RunStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="run_status_changed",
                    old_status=old_run_status,
                    new_status=RunStatus.PAUSED,
                    pause_reason=pause_reason,
                )
            )

        await self._event_emitter.emit_batch(events_to_emit)
        await commit_with_event_outbox(self._session)

        logger.info(
            f"Run {run_id}: fan-out parent {task_id} transitioned "
            f"from {old_status_value} to {new_status.value}"
        )

    async def reset_fan_out_children(self, run_id: str, parent_task_id: str) -> None:
        """Reset all children of a fan-out parent to PENDING for re-execution.

        Also sets the parent task status to FAN_OUT_RUNNING.
        """
        run_before = await self._repo.get(run_id)
        retry_children = [
            child
            for child in self._fan_out_children_for_parent(run_before, parent_task_id)
            if child.status == TaskStatus.FAILED
        ]
        await handle_reset_fan_out_children(
            ResetFanOutChildrenCommand(run_id=run_id, parent_task_id=parent_task_id),
            self._store_v2,
            self._session,
        )
        if retry_children:
            run_after = await self._repo.get(run_id)
            state = dict(run_after.oversight_state)
            for child in retry_children:
                state = self._record_fan_out_child_retry(state, child)
            await self._update_parent_oversight_facts(run_id, state)
        await commit_with_event_outbox(self._session)

    async def retry_fan_out_child(self, run_id: str, child_task_id: str) -> Run:
        """Retry a single failed fan-out child task.

        Resets the child to PENDING, parent to FAN_OUT_RUNNING, and the step
        to not-completed.  If the run has advanced past the fan-out step,
        rewinds current_step_index.  If the run is active, pauses it so the
        executor cleanly restarts from the correct step on resume.

        Uses targeted SQL updates (not a full run merge) to avoid clobbering
        concurrent fan-out child sessions.

        Returns the updated run.
        """
        run_before_retry = await self._repo.get(run_id)
        child_before_retry = self._find_task(run_before_retry, child_task_id)
        child_model = await self._repo.get_task_model(child_task_id)
        step_order_index = child_model.step.order_index
        await handle_retry_fan_out_child(
            RetryFanOutChildCommand(
                run_id=run_id,
                child_task_id=child_task_id,
                step_order_index=step_order_index,
            ),
            self._store_v2,
            self._session,
        )

        # Pause the run if active so the executor restarts from the right step
        run = await self._repo.get(run_id)
        oversight_state = self._record_fan_out_child_retry(
            run.oversight_state,
            child_before_retry,
        )
        await self._update_parent_oversight_facts(run_id, oversight_state)
        if run.status == RunStatus.ACTIVE:
            queue = self._get_signal_queue()
            await queue.enqueue(run_id, WorkflowSignal.PAUSE, {"reason": "fan_out_child_retry"})

        # Emit events
        await self._event_emitter.emit_batch(
            [
                TaskStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="task_status_changed",
                    task_id=child_task_id,
                    old_status=TaskStatus.FAILED,
                    new_status=TaskStatus.PENDING,
                ),
            ]
        )

        await commit_with_event_outbox(self._session)
        # Return fresh run state after all changes committed
        return await self._repo.get(run_id)

    async def start_fan_out_parent(self, run_id: str, task_id: str) -> TaskState:
        """Ensure a fan-out parent has an active attempt and FAN_OUT_RUNNING status."""
        run = await self._repo.get(run_id)
        task = self._find_task(run, task_id)
        start_decision = self._fan_out_policy.decision_for_start_parent(run, task)
        if start_decision.kind == "review":
            oversight_state = self._delegation_recorder.record_decision(
                run.oversight_state,
                start_decision,
            )
            await self._update_parent_oversight_facts(run.id, oversight_state)
            await commit_with_event_outbox(self._session)
            if start_decision.reason == "run_not_active":
                raise InvalidTransitionError(
                    run.status.value, "start_fan_out_parent (requires ACTIVE run)"
                )
            if start_decision.reason == "task_is_fan_out_child":
                raise InvalidTransitionError(
                    task.status.value, "start_fan_out_parent (parent only)"
                )

        if task.status == TaskStatus.PENDING:
            await self.start_task(run_id, task_id)
            run = await self._repo.get(run_id)
            task = self._find_task(run, task_id)

        if start_decision.kind == "wait" or task.status == TaskStatus.FAN_OUT_RUNNING:
            oversight_state = self._delegation_recorder.record_decision(
                run.oversight_state,
                start_decision,
            )
            await self._update_parent_oversight_facts(run.id, oversight_state)
            await commit_with_event_outbox(self._session)
            return task

        if task.status != TaskStatus.BUILDING:
            oversight_state = self._delegation_recorder.record_decision(
                run.oversight_state,
                start_decision,
            )
            await self._update_parent_oversight_facts(run.id, oversight_state)
            await commit_with_event_outbox(self._session)
            raise InvalidTransitionError(
                task.status.value,
                "start_fan_out_parent (requires PENDING, BUILDING, or FAN_OUT_RUNNING)",
            )

        status_events = await handle_update_task_status(
            UpdateTaskStatusCommand(
                run_id=run_id,
                task_id=task_id,
                old_status=TaskStatus.BUILDING,
                new_status=TaskStatus.FAN_OUT_RUNNING,
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted_batch(status_events)
        await commit_with_event_outbox(self._session)
        refreshed = await self._repo.get(run_id)
        oversight_state = self._delegation_recorder.record_decision(
            refreshed.oversight_state,
            start_decision,
        )
        await self._update_parent_oversight_facts(refreshed.id, oversight_state)
        await commit_with_event_outbox(self._session)
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

        if task.status == TaskStatus.BUILDING:
            return

        if task.status != TaskStatus.PENDING:
            raise InvalidTransitionError(
                task.status.value,
                "start_fan_out_child_task (requires PENDING child)",
            )

        next_attempt_num = task.current_attempt + 1
        attempt = Attempt(attempt_num=next_attempt_num, started_at=self._clock.now())
        attempt.agent_runner_type = run.agent_runner_type
        attempt.agent_model = run.agent_runner_config.get("model")
        attempt.agent_settings = self._sanitize_agent_runner_config(run.agent_runner_config)

        await handle_create_task_attempt(
            CreateTaskAttemptCommand(
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt.id,
                attempt_num=attempt.attempt_num,
                runner_type=attempt.agent_runner_type.value if attempt.agent_runner_type else None,
                agent_model=attempt.agent_model,
            ),
            self._store_v2,
            self._session,
        )
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
        await commit_with_event_outbox(self._session)

    async def update_child_task_state(
        self,
        run_id: str,
        task_id: str,
        updates: dict[str, Any],
        *,
        parent_task_id: str | None = None,
        child_id: str = "",  # Stable fan-out child UUID (child.child_id)
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
        # status with stale values.  The attempt update command projects only
        # the target attempt and task status, which avoids this clobber.
        task_result = await self._session.execute(
            select(TaskModel.current_attempt).where(TaskModel.id == task_id)
        )
        current_attempt = task_result.scalar_one_or_none()
        if current_attempt is None:
            raise TaskNotFoundError("unknown", task_id)

        attempt_result = await self._session.execute(
            select(AttemptModel.id)
            .where(AttemptModel.task_id == task_id)
            .order_by(AttemptModel.attempt_num.desc())
            .limit(1)
        )
        latest_attempt_id = attempt_result.scalar_one_or_none()
        completed_at = updates.get("completed_at")
        if isinstance(completed_at, datetime):
            completed_at = completed_at.isoformat()
        await handle_update_latest_attempt(
            UpdateLatestAttemptCommand(
                run_id=run_id,
                task_id=task_id,
                attempt_id=latest_attempt_id or "",
                error=updates.get("error") if "error" in updates else None,
                outcome=updates.get("outcome") if "outcome" in updates else None,
                completed_at=completed_at if "completed_at" in updates else None,
                auto_verify_results=updates.get("auto_verify_results")
                if "auto_verify_results" in updates
                else None,
                new_task_status=updates.get("status") if "status" in updates else None,
            ),
            self._store_v2,
            self._session,
        )

        # Flush child lifecycle events in the same transaction to avoid extra write
        # contention in concurrent fan-out (all DB writes committed atomically below).
        if parent_task_id is not None and "status" in updates:
            new_status = updates["status"]
            if new_status == TaskStatus.COMPLETED:
                event = ChildCompleted(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="child_completed",
                    parent_task_id=parent_task_id,
                    child_task_id=task_id,
                    child_id=child_id,
                    fan_out_index=fan_out_index,
                    attempt_num=current_attempt,
                    fan_out_output=fan_out_output,
                )
                await self._store_v2.append([event])
                self._event_emitter.notify_persisted(event)
            elif new_status == TaskStatus.FAILED:
                event = ChildFailed(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="child_failed",
                    parent_task_id=parent_task_id,
                    child_task_id=task_id,
                    child_id=child_id,
                    fan_out_index=fan_out_index,
                    attempt_num=current_attempt,
                    error=updates.get("error"),
                )
                await self._store_v2.append([event])
                self._event_emitter.notify_persisted(event)

        await commit_with_event_outbox(self._session)

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
            attempt.agent_runner_type = None
            attempt.agent_settings = {**attempt.agent_settings, "execution_kind": "script"}

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
            from orchestrator.workflow.engine.transitions import check_step_progression

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
                from orchestrator.workflow import StepCompleted

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

            await self._resolve_run_completion_transition(
                updated_run,
                state,
                buffer,
                old_status=updated_run.status,
            )
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
        if run.status not in (RunStatus.ACTIVE, RunStatus.STOPPING):
            raise InvalidTransitionError(
                run.status.value, "submit_for_verification (requires ACTIVE or STOPPING run)"
            )
        engine, state, buffer = self._build_engine(run)

        # Idempotency: if task is already VERIFYING, return current state without
        # re-running auto-verify or re-advancing the state machine.
        task = state.get_task(run_id, task_id)
        if task.status == TaskStatus.VERIFYING:
            return TransitionResult(success=True, new_status=TaskStatus.VERIFYING)

        # --- Pre-gate auto-verify: run auto-verify before the checklist gate ---
        # If task-level auto-verify items all pass, auto-mark OPEN checklist
        # items as DONE so the gate check succeeds. This prevents agents from
        # needing to explicitly call on_checklist_update() when auto-verify
        # already confirms the work was done.
        task = state.get_task(run_id, task_id)
        step_config_id_pre = resolve_step_config_id_for_task(run, task_id)

        auto_verify_config = resolve_auto_verify_config(run, task.config_id, step_config_id_pre)
        if auto_verify_config is not None and self._auto_verify_runner is not None:
            project_path = _resolve_working_path(run)
            if project_path is not None:
                # Auto-commit any uncommitted changes before running auto-verify
                if run.worktree_path:
                    await self._run_event_sourced_worktree_commit(
                        run_id=run_id,
                        task_id=task_id,
                        attempt_id=task.attempts[-1].id if task.attempts else None,
                        worktree_path=run.worktree_path,
                        message=f"Auto-commit builder changes for task {task_id}",
                        commit_type="builder_submit",
                        reason="pre_auto_verify",
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
                    return TransitionResult(
                        success=True,
                        new_status=TaskStatus.BUILDING,
                        error="Auto-verify must-items failed (pre-gate)",
                    )

        # --- Capture end commit for git tracking (before engine call so it's in the event) ---
        end_commit: str | None = None
        task_pre = state.get_task(run_id, task_id)
        if run.worktree_path and task_pre.attempts:
            # Auto-commit any uncommitted changes left by the builder agent.
            # Some CLI agents (e.g. codex) may not commit their work, and the
            # verifier's git checkout of end_commit would destroy those changes.
            end_commit = await self._run_event_sourced_worktree_commit(
                run_id=run_id,
                task_id=task_id,
                attempt_id=task_pre.attempts[-1].id,
                worktree_path=run.worktree_path,
                message=f"Auto-commit builder changes for task {task_id}",
                commit_type="builder_submit",
                reason="submit_for_verification",
            )

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

        # Idempotency: if task is already in a terminal state (COMPLETED or FAILED),
        # return current state without re-advancing the state machine. Check this
        # before the ACTIVE run guard so that a run that auto-completed still
        # returns success for a duplicate call.
        for _step in run.steps:
            for _task in _step.tasks:
                if _task.id == task_id and _task.status in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                ):
                    return TransitionResult(success=True, new_status=_task.status)

        if run.status not in (RunStatus.ACTIVE, RunStatus.STOPPING, RunStatus.PAUSED):
            raise InvalidTransitionError(
                run.status.value, "complete_verification (requires ACTIVE, STOPPING, or PAUSED run)"
            )

        # Capture which steps were already completed before the engine runs
        prev_completed_step_ids = {s.config_id for s in run.steps if s.completed}

        engine, state, buffer = self._build_engine(run)
        result = engine.complete_verification(run_id, task_id)

        # Get the updated run after engine processing
        updated_run = state.get_run(run_id)
        old_run_status = updated_run.status

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
                    updated_run.status = RunStatus.FAILED
                    updated_run.last_error = f"Step '{step.config_id}' auto-verify failed"
                    updated_run.completed_at = self._clock.now()
                    state.update_run(updated_run)
                    break

        await self._resolve_run_completion_transition(
            updated_run,
            state,
            buffer,
            old_status=old_run_status,
        )
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

    # --- Check/apply split methods for synchronous-check + async-signal pattern ---

    async def check_submission(self, run_id: str, task_id: str) -> TransitionResult:
        """Check submission readiness without transitioning task state.

        Runs auto-verify, auto-marks checklist items, and validates the checklist
        gate.  On success, persists updated checklist and auto-verify results so
        that a subsequent apply_submission call (via signal) can apply the
        BUILDING → VERIFYING transition.

        Returns:
            success=True, new_status=BUILDING  — gate ready; caller should enqueue
                                                 ACTIVITY_COMPLETED signal.
            success=True, new_status=VERIFYING — idempotent; task already VERIFYING.
            success=True, new_status=RECOVERING — crash recovery triggered.
            success=False, new_status=BUILDING — auto-verify must-items failed;
                                                  error details returned to agent.

        Raises:
            InvalidTransitionError: Run is not ACTIVE or STOPPING.
            GateBlockedError: Checklist gate does not pass after auto-verify.
        """
        run = await self._repo.get(run_id)
        if run.status not in (RunStatus.ACTIVE, RunStatus.STOPPING):
            raise InvalidTransitionError(
                run.status.value, "check_submission (requires ACTIVE or STOPPING run)"
            )
        _, state, buffer = self._build_engine(run)

        task = state.get_task(run_id, task_id)
        if task.status == TaskStatus.VERIFYING:
            return TransitionResult(success=True, new_status=TaskStatus.VERIFYING)

        step_config_id_pre = resolve_step_config_id_for_task(run, task_id)

        auto_verify_config = resolve_auto_verify_config(run, task.config_id, step_config_id_pre)
        if auto_verify_config is not None and self._auto_verify_runner is not None:
            project_path = _resolve_working_path(run)
            if project_path is not None:
                if run.worktree_path:
                    await self._run_event_sourced_worktree_commit(
                        run_id=run_id,
                        task_id=task_id,
                        attempt_id=task.attempts[-1].id if task.attempts else None,
                        worktree_path=run.worktree_path,
                        message=f"Auto-commit builder changes for task {task_id}",
                        commit_type="builder_submit",
                        reason="check_submission_pre_auto_verify",
                    )

                av_results = await run_auto_verify(
                    auto_verify_config,
                    self._auto_verify_runner,
                    project_path,
                    variables=run.config,
                )

                if task.attempts:
                    task.attempts[-1].auto_verify_results = [r.model_dump() for r in av_results]

                all_must_passed, failing_must_ids = evaluate_auto_verify(
                    auto_verify_config, av_results
                )

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
                    await self.trigger_recovery(run_id, task_id, crash_detail)
                    return TransitionResult(
                        success=True,
                        new_status=TaskStatus.RECOVERING,
                        error="Auto-verify script crashed; recovery triggered",
                    )

                if all_must_passed:
                    for item in task.checklist:
                        if item.status == ChecklistStatus.OPEN:
                            item.status = ChecklistStatus.DONE
                else:
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
                    return TransitionResult(
                        success=False,
                        new_status=TaskStatus.BUILDING,
                        error="Auto-verify must-items failed (pre-gate)",
                    )

        # Re-fetch task after potential auto-mark updates
        task = state.get_task(run_id, task_id)

        # Validate the checklist gate without transitioning state
        gate_result = evaluate_checklist_gate(task.checklist)
        if not gate_result.passed:
            await self._persist(state, run_id, buffer)
            raise GateBlockedError("checklist", gate_result.blocking_items)

        # Gate passes — persist updated state (auto-verify results, checklist, events)
        await self._persist(state, run_id, buffer)
        return TransitionResult(success=True, new_status=TaskStatus.BUILDING)

    async def apply_submission(self, run_id: str, task_id: str) -> TransitionResult:
        """Apply BUILDING → VERIFYING transition after a validated ACTIVITY_COMPLETED signal.

        Called by the signal handler.  Assumes check_submission has already
        validated the gate and persisted updated checklist state.

        Raises:
            InvalidTransitionError: Run is not ACTIVE or STOPPING.
        """
        run = await self._repo.get(run_id)
        if run.status not in (RunStatus.ACTIVE, RunStatus.STOPPING):
            raise InvalidTransitionError(
                run.status.value, "apply_submission (requires ACTIVE or STOPPING run)"
            )
        engine, state, buffer = self._build_engine(run)

        task = state.get_task(run_id, task_id)
        if task.status == TaskStatus.VERIFYING:
            return TransitionResult(success=True, new_status=TaskStatus.VERIFYING)

        end_commit: str | None = None
        if run.worktree_path and task.attempts:
            end_commit = await self._run_event_sourced_worktree_commit(
                run_id=run_id,
                task_id=task_id,
                attempt_id=task.attempts[-1].id,
                worktree_path=run.worktree_path,
                message=f"Auto-commit builder changes for task {task_id}",
                commit_type="builder_submit",
                reason="apply_submission",
            )

        try:
            result = engine.submit_for_verification(run_id, task_id, end_commit=end_commit)
        except GateBlockedError:
            await self._persist(state, run_id, buffer)
            raise

        if not result.success:
            await self._persist(state, run_id, buffer)
            return result

        task = state.get_task(run_id, task_id)
        if end_commit and task.attempts:
            task.attempts[-1].end_commit = end_commit

        await self._persist(state, run_id, buffer)
        return result

    async def check_verification(self, run_id: str, task_id: str) -> TransitionResult:
        """Validate that verification can be completed; does not change state.

        Called synchronously by the HTTP endpoint before enqueuing
        ACTIVITY_VERIFIED.

        Returns:
            success=True, new_status=VERIFYING   — task ready; enqueue signal.
            success=True, new_status=COMPLETED   — idempotent; already completed.
            success=True, new_status=FAILED      — idempotent; already failed.

        Raises:
            InvalidTransitionError: Run or task is not in a valid state.
            TaskNotFoundError: Task not found in the run.
        """
        run = await self._repo.get(run_id)

        for step in run.steps:
            for task in step.tasks:
                if task.id == task_id and task.status in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                ):
                    return TransitionResult(success=True, new_status=task.status)

        if run.status not in (RunStatus.ACTIVE, RunStatus.STOPPING, RunStatus.PAUSED):
            raise InvalidTransitionError(
                run.status.value,
                "check_verification (requires ACTIVE, STOPPING, or PAUSED run)",
            )

        for step in run.steps:
            for task in step.tasks:
                if task.id == task_id:
                    if task.status != TaskStatus.VERIFYING:
                        raise InvalidTransitionError(
                            task.status.value,
                            "check_verification (task must be VERIFYING)",
                        )
                    return TransitionResult(success=True, new_status=TaskStatus.VERIFYING)

        raise TaskNotFoundError(run_id, task_id)

    async def apply_verification(self, run_id: str, task_id: str) -> TransitionResult:
        """Apply verification outcome after a validated ACTIVITY_VERIFIED signal.

        Called by the signal handler.  Delegates to complete_verification which
        evaluates grades and applies the VERIFYING → outcome transition plus all
        post-transition side effects (step auto-verify, env_lifecycle, worktree
        cleanup).
        """
        return await self.complete_verification(run_id, task_id)

    # --- Direct state operations ---

    async def get_run(self, run_id: str) -> Run:
        """Get a run by ID."""
        return await self._with_current_oversight(await self._repo.get(run_id))

    async def list_runs(self, limit: int | None = None) -> list[Run]:
        """List all runs, optionally limited to the most recent N runs."""
        return await self._with_current_oversight_for_runs(
            await self._repo.list_all(
                limit=limit, include_action_logs=False, include_routine_embedded=False
            )
        )

    async def list_runs_recent(self, hours: int) -> list[Run]:
        """List runs created within the last N hours."""
        return await self._with_current_oversight_for_runs(
            await self._repo.list_recent(
                hours, include_action_logs=False, include_routine_embedded=False
            )
        )

    async def list_repo_names(self) -> list[str]:
        """List unique repository names across all runs."""
        return await self._repo.list_repo_names()

    async def list_runs_by_repo(self, repo_name: str) -> list[Run]:
        """List runs for a repository."""
        return await self._with_current_oversight_for_runs(
            await self._repo.list_by_repo(
                repo_name, include_action_logs=False, include_routine_embedded=False
            )
        )

    async def list_runs_by_status(self, status: RunStatus) -> list[Run]:
        """List runs filtered by status."""
        return await self._with_current_oversight_for_runs(
            await self._repo.list_by_status(
                status, include_action_logs=False, include_routine_embedded=False
            )
        )

    async def list_runs_by_repo_and_status(self, repo_name: str, status: RunStatus) -> list[Run]:
        """List runs filtered by both repository and status."""
        return await self._with_current_oversight_for_runs(
            await self._repo.list_by_repo_and_status(
                repo_name,
                status,
                include_action_logs=False,
                include_routine_embedded=False,
            )
        )

    async def list_child_runs(self, parent_run_id: str) -> list[Run]:
        """List child runs linked to an oversight parent run."""
        await self._repo.get(parent_run_id)
        return await self._repo.list_child_runs(
            parent_run_id, include_action_logs=False, include_routine_embedded=False
        )

    async def get_parent_oversight(self, parent_run_id: str) -> dict[str, Any]:
        """Return current deterministic oversight state for a parent run."""
        return await self._parent_oversight.get_parent_oversight(parent_run_id)

    async def _with_current_oversight(self, run: Run) -> Run:
        """Attach computed oversight to parent runs before returning API data."""
        return await self._parent_oversight.hydrate_if_parent(run)

    async def _with_current_oversight_for_runs(self, runs: list[Run]) -> list[Run]:
        """Attach computed oversight to any parent runs in a response list."""
        return [await self._with_current_oversight(run) for run in runs]

    async def update_parent_oversight(
        self,
        parent_run_id: str,
        *,
        current_understanding: dict[str, Any] | None = None,
        target_inventory: list[dict[str, Any]] | None = None,
        final_validation: dict[str, Any] | None = None,
        decisions: list[dict[str, Any]] | None = None,
    ) -> Run:
        """Persist parent-authored oversight facts, then recompute derived state."""
        return await self._parent_oversight.update_parent_oversight(
            parent_run_id,
            current_understanding=current_understanding,
            target_inventory=target_inventory,
            final_validation=final_validation,
            decisions=decisions,
        )

    def _drop_stale_final_validation(
        self,
        parent: Run,
        oversight_state: dict[str, Any],
    ) -> dict[str, Any]:
        return self._parent_oversight.drop_stale_final_validation(parent, oversight_state)

    async def refresh_parent_oversight(self, parent_run_id: str) -> Run:
        """Recompute and persist the parent oversight snapshot from child state."""
        return await self._parent_oversight.refresh_parent_oversight(parent_run_id)

    async def _refresh_parent_oversight_without_commit(
        self,
        parent_run_id: str,
        *,
        parent: Run | None = None,
    ) -> Run:
        """Recompute and save parent oversight state without committing."""
        return await self._parent_oversight.refresh_parent_oversight_without_commit(
            parent_run_id,
            parent=parent,
        )

    async def _compute_parent_oversight_state(self, parent: Run) -> dict[str, Any]:
        """Compute parent oversight from persisted parent facts plus current children."""
        return await self._parent_oversight.compute_parent_oversight_state(parent)

    def _fan_out_children_for_parent(
        self,
        run: Run,
        parent_task_id: str,
    ) -> list[TaskState]:
        return [
            task
            for step in run.steps
            for task in step.tasks
            if task.parent_task_id == parent_task_id
        ]

    def _fan_out_command_key(self, parent_task_id: str, child_task_id: str, action: str) -> str:
        return f"{parent_task_id}:{child_task_id}:fan-out:{action}"

    def _record_fan_out_child_launches(
        self,
        owner_state: dict[str, Any],
        children: list[TaskState],
    ) -> dict[str, Any]:
        state = dict(owner_state)
        for child in children:
            work = work_from_fan_out_child(child)
            state, _, _ = self._delegation_recorder.apply_command(
                state,
                work,
                DelegateCommand(
                    kind="launch",
                    work_id=child.id,
                    owner_id=work.owner_id,
                    idempotency_key=self._fan_out_command_key(
                        work.owner_id,
                        child.id,
                        "launch",
                    ),
                    expected_generation=work.generation,
                ),
            )
        return state

    def _record_fan_out_child_retry(
        self,
        owner_state: dict[str, Any],
        child: TaskState,
    ) -> dict[str, Any]:
        work = work_from_fan_out_child(child)
        if work.status == "requested":
            work = work.model_copy(update={"status": "review"})
        state, _, _ = self._delegation_recorder.apply_command(
            owner_state,
            work,
            DelegateCommand(
                kind="retry",
                work_id=child.id,
                owner_id=work.owner_id,
                idempotency_key=self._fan_out_command_key(
                    work.owner_id,
                    child.id,
                    f"retry:{work.generation}",
                ),
                expected_generation=work.generation,
            ),
        )
        return state

    def _record_delegate_result_once(
        self,
        owner_state: dict[str, Any],
        result: DelegateResultEnvelope,
        decision: DelegationDecision,
    ) -> dict[str, Any]:
        for item in self._state_dict_list(owner_state.get("delegation_results")):
            if (
                item.get("work_id") == result.work_id
                and item.get("generation") == result.generation
            ):
                return owner_state
        return self._delegation_recorder.record_result(
            owner_state,
            result,
            decision,
        )

    def _fan_out_work_for_command(
        self,
        owner_state: dict[str, Any],
        child: TaskState,
    ) -> DelegatedWork:
        """Build live fan-out work while preserving durable command fences."""
        work = work_from_fan_out_child(child)
        raw_work = owner_state.get("delegated_work")
        if isinstance(raw_work, dict):
            delegated_work = cast(dict[str, Any], raw_work)
            raw_child_work = delegated_work.get(child.id)
            if isinstance(raw_child_work, dict):
                existing = DelegatedWork.model_validate(raw_child_work)
                work = work.model_copy(
                    update={
                        "idempotency_keys": existing.idempotency_keys,
                        "owner_token": existing.owner_token,
                    }
                )
        return work

    def _record_fan_out_child_terminal_result(
        self,
        owner_state: dict[str, Any],
        child: TaskState,
    ) -> dict[str, Any]:
        if child.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            return owner_state
        work = self._fan_out_work_for_command(owner_state, child)
        passed = child.status == TaskStatus.COMPLETED
        command_kind: Literal["integrate", "reject"] = "integrate" if passed else "reject"
        state, _, decision = self._delegation_recorder.apply_command(
            owner_state,
            work,
            DelegateCommand(
                kind=command_kind,
                work_id=child.id,
                owner_id=work.owner_id,
                idempotency_key=self._fan_out_command_key(
                    work.owner_id,
                    child.id,
                    f"{command_kind}:{work.generation}",
                ),
                expected_generation=work.generation,
            ),
        )
        if decision.kind == "stale_command_ignored":
            return state
        return self._record_delegate_result_once(
            state,
            DelegateResultEnvelope(
                work_id=child.id,
                generation=work.generation,
                terminal_status="completed" if passed else "failed",
                outcome="fan_out_child_completed" if passed else "fan_out_child_failed",
                validation_status="valid",
                integration_ready=passed,
                reasons=() if passed else ("fan_out_child_failed",),
            ),
            DelegationDecision(
                kind="complete" if passed else "reject",
                work_id=child.id,
                reason="fan_out_child_completed" if passed else "fan_out_child_failed",
                stable_state=None if passed else "NeedsRevision",
            ),
        )

    def _task_state_from_model(self, task_model: Any) -> TaskState:
        return TaskState(
            id=task_model.id,
            config_id=task_model.config_id,
            title=task_model.title,
            status=TaskStatus(task_model.status),
            current_attempt=task_model.current_attempt,
            parent_task_id=task_model.parent_task_id,
            fan_out_index=task_model.fan_out_index,
            fan_out_input=task_model.fan_out_input,
            fan_out_output=task_model.fan_out_output,
            child_id=task_model.child_id,
        )

    async def accept_child_run(
        self,
        parent_run_id: str,
        child_run_id: str,
        *,
        expected_generation: int | None = None,
        idempotency_key: str | None = None,
        owner_token: str | None = None,
    ) -> ParentChildMergeResult:
        """Accept a completed child by merging it into the parent run branch."""
        return await self._parent_oversight.accept_child_run(
            parent_run_id,
            child_run_id,
            expected_generation=expected_generation,
            idempotency_key=idempotency_key,
            owner_token=owner_token,
        )

    async def resolve_child_run(
        self,
        parent_run_id: str,
        child_run_id: str,
        *,
        resolution: Literal["reject", "abandon"],
        reason: str,
    ) -> ChildRunResolutionResult:
        """Record a parent decision that closes a child without merging it."""
        return await self._parent_oversight.resolve_child_run(
            parent_run_id,
            child_run_id,
            resolution=resolution,
            reason=reason,
        )

    async def create_child_run(
        self,
        parent_run_id: str,
        child_run: Run,
        *,
        parent_slice_id: str,
        next_action_decision: str,
    ) -> Run:
        """Persist a child run and record it in the parent's oversight history."""
        return await self._parent_oversight.create_child_run(
            parent_run_id,
            child_run,
            parent_slice_id=parent_slice_id,
            next_action_decision=next_action_decision,
        )

    def _resolved_child_run_ids(self, parent: Run) -> set[str]:
        """Return child IDs that the parent has explicitly resolved."""
        return self._parent_oversight.resolved_child_run_ids(parent)

    def _max_child_runs_for_parent(self, parent: Run) -> int:
        """Resolve the configured child-run limit for a parent run."""
        return self._parent_oversight.max_child_runs_for_parent(parent)

    def _state_dict_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            cast(dict[str, Any], item) for item in cast(list[Any], value) if isinstance(item, dict)
        ]

    async def _apply_oversight_terminal_guard(
        self,
        run: Run,
        state: SessionStateManager,
        buffer: BufferingEmitter,
        *,
        emit_status_change: bool = True,
    ) -> None:
        await self._parent_oversight.apply_oversight_terminal_guard(
            run,
            state,
            buffer,
            emit_status_change=emit_status_change,
        )

    async def _resolve_run_completion_transition(
        self,
        run: Run,
        state: SessionStateManager,
        buffer: BufferingEmitter,
        *,
        old_status: RunStatus,
    ) -> None:
        """Apply the final run transition after step progression and oversight reduction."""
        if run.status == RunStatus.ACTIVE:
            check_run_completion(run, self._clock.now())

        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
            await self._apply_oversight_terminal_guard(
                run,
                state,
                buffer,
                emit_status_change=False,
            )
            run = state.get_run(run.id)
        else:
            state.update_run(run)

        if run.status != old_status:
            buffer.emit(
                RunStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run.id,
                    event_type="run_status_changed",
                    old_status=old_status,
                    new_status=run.status,
                    pause_reason=run.pause_reason,
                    last_error=run.last_error,
                )
            )

    def _is_oversight_parent_run(self, run: Run) -> bool:
        """Return whether a run is meant to use super-parent terminal guards."""
        return self._parent_oversight.is_oversight_parent_run(run)

    async def wait_for_run_terminal(self, run_id: str, timeout_seconds: float) -> Run:
        """Wait for a run to reach terminal or paused state, then return current state."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while True:
            run = await self._repo.get(run_id)
            if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.PAUSED):
                return run
            if loop.time() >= deadline:
                return run
            await asyncio.sleep(0.25)

    async def record_child_wait_observation(
        self,
        parent_run_id: str,
        child_run_id: str,
        *,
        observed_status: RunStatus,
        phase: Literal["started", "observed"],
        timeout_seconds: float,
        expected_generation: int | None = None,
        owner_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> Run:
        """Persist parent wait intent/observation for child-run recovery."""
        return await self._parent_oversight.record_child_wait_observation(
            parent_run_id,
            child_run_id,
            observed_status=observed_status,
            phase=phase,
            timeout_seconds=timeout_seconds,
            expected_generation=expected_generation,
            owner_token=owner_token,
            idempotency_key=idempotency_key,
        )

    async def collect_run_evidence(self, run_id: str) -> list[dict[str, Any]]:
        """Collect run.evidence.v1 bundles from a run worktree."""
        return await self._parent_oversight.collect_run_evidence(run_id)

    async def collect_validated_run_evidence(
        self,
        run_id: str,
        *,
        expected_slice_id: str | None = None,
        expected_routine_id: str | None = None,
    ) -> dict[str, Any]:
        """Collect run evidence with valid bundles separated from validation failures."""
        raw_items = await self.collect_run_evidence(run_id)
        evidence, invalid_evidence = validate_run_evidence_items(
            raw_items,
            expected_slice_id=expected_slice_id,
            expected_routine_id=expected_routine_id,
        )
        return {
            "run_id": run_id,
            "evidence": evidence,
            "invalid_evidence": [item.model_dump(mode="json") for item in invalid_evidence],
        }

    async def get_task(self, run_id: str, task_id: str) -> TaskState:
        """Get a task by run ID and task ID."""
        run = await self._repo.get(run_id)
        state = SessionStateManager()
        state.add_run(run)
        return state.get_task(run_id, task_id)

    async def create_run(self, run: Run) -> Run:
        """Persist a new run."""
        await handle_create_run(
            build_create_run_command(run),
            self._store_v2,
            self._session,
        )
        await commit_with_event_outbox(self._session)
        return await self._repo.get(run.id)

    async def set_worktree_path(
        self, run_id: str, worktree_path: str, source_branch_sha: str | None = None
    ) -> Run:
        """Set the worktree path on a run after worktree creation."""
        await handle_update_run_worktree(
            UpdateRunWorktreeCommand(
                run_id=run_id,
                worktree_path=worktree_path,
                source_branch_sha=source_branch_sha,
            ),
            self._store_v2,
            self._session,
        )
        await commit_with_event_outbox(self._session)
        return await self._repo.get(run_id)

    async def request_worktree_creation(
        self, run_id: str, repo_name: str, source_branch: str
    ) -> Run:
        """Record that worktree setup is being attempted for a run."""
        await handle_request_run_worktree_creation(
            RequestRunWorktreeCreationCommand(
                run_id=run_id,
                repo_name=repo_name,
                source_branch=source_branch,
            ),
            self._store_v2,
            self._session,
        )
        await commit_with_event_outbox(self._session)
        return await self._repo.get(run_id)

    async def request_worktree_reset(
        self,
        run_id: str,
        *,
        worktree_path: str,
        reset_type: str,
        target_ref: str | None = None,
        branch_name: str | None = None,
        head_before: str | None = None,
        reason: str | None = None,
    ) -> Run:
        """Record that a destructive worktree reset is being attempted."""
        await handle_request_run_worktree_reset(
            RequestRunWorktreeResetCommand(
                run_id=run_id,
                worktree_path=worktree_path,
                reset_type=reset_type,
                target_ref=target_ref,
                branch_name=branch_name,
                head_before=head_before,
                reason=reason,
            ),
            self._store_v2,
            self._session,
        )
        await commit_with_event_outbox(self._session)
        return await self._repo.get(run_id)

    async def complete_worktree_reset(
        self,
        run_id: str,
        *,
        worktree_path: str,
        reset_type: str,
        target_ref: str | None = None,
        branch_name: str | None = None,
        head_before: str | None = None,
        head_after: str | None = None,
        reason: str | None = None,
    ) -> Run:
        """Record that a destructive worktree reset completed."""
        await handle_complete_run_worktree_reset(
            CompleteRunWorktreeResetCommand(
                run_id=run_id,
                worktree_path=worktree_path,
                reset_type=reset_type,
                target_ref=target_ref,
                branch_name=branch_name,
                head_before=head_before,
                head_after=head_after,
                reason=reason,
            ),
            self._store_v2,
            self._session,
        )
        await commit_with_event_outbox(self._session)
        return await self._repo.get(run_id)

    async def fail_worktree_reset(
        self,
        run_id: str,
        *,
        worktree_path: str,
        reset_type: str,
        error: str,
        target_ref: str | None = None,
        branch_name: str | None = None,
        head_before: str | None = None,
        reason: str | None = None,
    ) -> Run:
        """Record a destructive worktree reset failure and keep the run paused."""
        run = await self._repo.get(run_id)
        message = f"Worktree reset failed: {error}"
        await handle_fail_run_worktree_reset(
            FailRunWorktreeResetCommand(
                run_id=run_id,
                worktree_path=worktree_path,
                reset_type=reset_type,
                error=message,
                target_ref=target_ref,
                branch_name=branch_name,
                head_before=head_before,
                reason=reason,
            ),
            self._store_v2,
            self._session,
        )
        status_events = await handle_update_run_status(
            UpdateRunStatusCommand(
                run_id=run_id,
                old_status=run.status,
                new_status=RunStatus.PAUSED,
                pause_reason="worktree_reset_failed",
                last_error=message,
                timestamp=self._clock.now(),
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(status_events[0])
        await commit_with_event_outbox(self._session)
        return await self._repo.get(run_id)

    async def fail_worktree_creation(self, run_id: str, error: str) -> Run:
        """Record worktree setup failure and keep the run out of ACTIVE."""
        run = await self._repo.get(run_id)
        message = f"Worktree setup failed before agent spawn: {error}"
        await handle_fail_run_worktree_creation(
            FailRunWorktreeCreationCommand(run_id=run_id, error=message),
            self._store_v2,
            self._session,
        )
        status_events = await handle_update_run_status(
            UpdateRunStatusCommand(
                run_id=run_id,
                old_status=run.status,
                new_status=RunStatus.PAUSED,
                pause_reason="worktree_setup_failed",
                last_error=message,
                timestamp=self._clock.now(),
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(status_events[0])
        await commit_with_event_outbox(self._session)
        return await self._repo.get(run_id)

    async def delete_run(self, run_id: str) -> None:
        """Delete a run."""
        await self._repo.get(run_id)
        events = await handle_delete_run(
            DeleteRunCommand(run_id=run_id),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(events[0])
        await commit_with_event_outbox(self._session)

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
        await handle_update_checklist_item(
            UpdateChecklistItemCommand(
                run_id=run_id,
                task_id=task_id,
                req_id=resolved_req_id,
                status=status,
                note=note,
            ),
            self._store_v2,
            self._session,
        )
        await commit_with_event_outbox(self._session)
        reloaded = await self._repo.get(run_id)
        updated_task = self._find_task(reloaded, task_id)
        for item in updated_task.checklist:
            if item.req_id == resolved_req_id:
                return item
        raise ChecklistItemNotFoundError(run_id, task_id, resolved_req_id)

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

        if not any(item.req_id == resolved_req_id for item in task.checklist):
            raise ChecklistItemNotFoundError(run_id, task_id, req_id)

        await handle_set_checklist_grade(
            SetChecklistGradeCommand(
                run_id=run_id,
                task_id=task_id,
                req_id=resolved_req_id,
                grade=grade,
                grade_reason=grade_reason,
            ),
            self._store_v2,
            self._session,
        )
        await commit_with_event_outbox(self._session)
        reloaded = await self._repo.get(run_id)
        updated_task = self._find_task(reloaded, task_id)
        for item in updated_task.checklist:
            if item.req_id == resolved_req_id:
                return item
        raise ChecklistItemNotFoundError(run_id, task_id, resolved_req_id)

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

        events = await handle_record_clarification_request(
            RecordClarificationRequestCommand(
                run_id=run_id,
                task_id=task_id,
                request_id=request.id,
                attempt_num=request.attempt_num,
                questions=[q.model_dump(mode="json") for q in questions],
                requested_at=request.created_at,
            ),
            self._store_v2,
            self._session,
        )

        self._event_emitter.notify_persisted(events[0])
        await commit_with_event_outbox(self._session)

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

        from orchestrator.db import ClarificationRequestModel

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

        # Transition back to building. Older runs may have a pending
        # clarification request on a task that already advanced because a later
        # submit bypassed PENDING_USER_ACTION. Record the answer and clear the
        # stale pending marker without reopening a completed/verifying task.
        old_status = task.status
        if task.status == TaskStatus.PENDING_USER_ACTION:
            result = transition_from_clarification(task)
            if not result.success:
                raise InvalidTransitionError(old_status.value, result.new_status.value)
        elif (
            task.pending_action_type == "clarification"
            or task.pending_clarification_id == request_id
        ):
            task.pending_action_type = None
            task.pending_clarification_id = None
            result = TransitionResult(success=True, new_status=task.status)
        else:
            result = transition_from_clarification(task)
            if not result.success:
                raise InvalidTransitionError(old_status.value, result.new_status.value)

        # Compress Q&A into compact decisions (pure function, always available).
        # Raw Q&A is archived in the artifact file; decisions are the compact form
        # passed downstream to prompt assembly and persisted as a run config delta.
        compressed: CompressedDecisions = compress_clarifications(request, response)
        run_config_delta: dict[str, Any] = {}
        if compressed.decisions:
            run_config_delta = {
                "_compressed_decisions": [
                    {
                        "question": d.question,
                        "decision": d.decision,
                        "rationale": d.rationale,
                    }
                    for d in compressed.decisions
                ],
                "_compressed_decisions_request_id": compressed.source_request_id,
            }

        events = await handle_record_clarification_response(
            RecordClarificationResponseCommand(
                run_id=run_id,
                task_id=task_id,
                request_id=request_id,
                response_id=str(uuid4()),
                answers=[answer.model_dump(mode="json") for answer in answers],
                responded_by=responded_by,
                responded_at=now,
                new_status=result.new_status,
                run_config_delta=run_config_delta,
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(events[0])

        await commit_with_event_outbox(self._session)

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
            prompt_config = dict(run.config)
            prompt_config.update(run_config_delta)
            generate_builder_prompt(
                task_config_obj,
                task,
                prompt_config,
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

        events = await handle_record_approval_decision(
            RecordApprovalDecisionCommand(
                run_id=run_id,
                task_id=task_id,
                step_id=step.id,
                approved=True,
                comment=comment,
                decided_by=approved_by,
                decided_at=now,
                new_status=result.new_status,
                current_attempt=task.current_attempt,
                checklist=[item.model_dump(mode="json") for item in task.checklist],
                attempt_snapshots=[attempt.model_dump(mode="json") for attempt in task.attempts],
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(events[0])

        await commit_with_event_outbox(self._session)

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

        events = await handle_record_approval_decision(
            RecordApprovalDecisionCommand(
                run_id=run_id,
                task_id=task_id,
                step_id=step.id,
                approved=False,
                comment=reason,
                decided_by=rejected_by,
                decided_at=now,
                new_status=result.new_status,
                current_attempt=task.current_attempt,
                checklist=[item.model_dump(mode="json") for item in task.checklist],
                attempt_snapshots=[attempt.model_dump(mode="json") for attempt in task.attempts],
            ),
            self._store_v2,
            self._session,
        )
        self._event_emitter.notify_persisted(events[0])

        await commit_with_event_outbox(self._session)

        return result

    async def force_accept_task(
        self,
        run_id: str,
        task_id: str,
        accepted_by: str,
        comment: str | None = None,
    ) -> TransitionResult:
        """Override verification failure and force-complete a task.

        Works from FAILED, BUILDING, or VERIFYING states.
        Bypasses grade evaluation and marks the task COMPLETED.
        Handles step/run completion cascade via the engine.
        Emits ApprovalDecision event with override flag in comment.
        """
        run = await self._repo.get(run_id)
        task = self._find_task(run, task_id)
        step = self._find_step_for_task(run, task_id)
        old_status = task.status
        old_run_status = run.status

        engine, state, buffer = self._build_engine(run)
        result = engine.force_accept(run_id, task_id)
        if not result.success:
            raise InvalidTransitionError(old_status.value, result.new_status.value)

        updated_run = state.get_run(run_id)
        await self._resolve_run_completion_transition(
            updated_run,
            state,
            buffer,
            old_status=old_run_status,
        )
        updated_run = state.get_run(run_id)
        await self._persist(state, run_id, buffer)

        override_comment = f"[force-accepted by {accepted_by}]"
        if comment:
            override_comment += f" {comment}"
        await self._event_emitter.emit(
            ApprovalDecision(
                timestamp=self._clock.now(),
                run_id=run_id,
                event_type="approval_decision",
                task_id=task_id,
                step_id=step.id,
                approved=True,
                comment=override_comment,
                decided_by=accepted_by,
            )
        )

        await commit_with_event_outbox(self._session)

        # env_lifecycle hooks (same as complete_verification)
        if (
            self._env_lifecycle is not None
            and updated_run.worktree_path
            and updated_run.env_file_specs
        ):
            worktree_path = Path(updated_run.worktree_path)
            await self._env_lifecycle.on_task_end(
                run_id=run_id,
                task_id=task_id,
                worktree_path=worktree_path,
            )
            if updated_run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                success = updated_run.status == RunStatus.COMPLETED
                await self._env_lifecycle.on_run_end(
                    run_id=run_id,
                    repo_name=updated_run.repo_name,
                    worktree_path=worktree_path,
                    success=success,
                )

        if updated_run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
            worktree_manager = self._create_worktree_manager(updated_run)
            if worktree_manager is not None:
                handle_run_completion(updated_run, worktree_manager)

        return result

    async def get_pending_actions(
        self,
        run_id: str,
    ) -> list[dict[str, Any]]:
        """Get all pending user actions for a run."""
        run = await self._repo.get(run_id)

        actions: list[dict[str, Any]] = []
        oversight_run = run
        if (
            self._is_oversight_parent_run(run)
            or run.pause_reason == "oversight_children_unresolved"
        ):
            oversight_run = run.model_copy(
                deep=True,
                update={"oversight_state": await self._compute_parent_oversight_state(run)},
            )
        oversight_action = self._pending_oversight_action(oversight_run)
        if oversight_action is not None:
            actions.append(oversight_action)
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

    def _pending_oversight_action(self, run: Run) -> dict[str, Any] | None:
        """Return a run-level pending action for blocked oversight parents."""
        oversight_state = run.oversight_state
        terminal_guard = oversight_state.get("terminal_guard")
        attention_items = oversight_state.get("attention_items")
        blocking_reasons: list[Any] = []
        if isinstance(terminal_guard, dict):
            terminal_guard_dict = cast(dict[str, Any], terminal_guard)
            raw_reasons = terminal_guard_dict.get("blocking_reasons")
            if isinstance(raw_reasons, list):
                blocking_reasons = cast(list[Any], raw_reasons)

        blocked = (
            run.pause_reason == "oversight_children_unresolved"
            or bool(attention_items)
            or (run.status == RunStatus.PAUSED and bool(blocking_reasons))
        )
        if not blocked:
            return None

        return {
            "task_id": "",
            "step_id": "",
            "action_type": "oversight",
            "is_gate_approval": False,
            "approval_prompt": run.last_error
            or "Parent oversight requires human attention before completion can continue.",
            "details": {
                "pause_reason": run.pause_reason,
                "next_parent_action": oversight_state.get("next_parent_action"),
                "blocking_reasons": blocking_reasons,
                "attention_items": attention_items if isinstance(attention_items, list) else [],
                "active_child_run_ids": oversight_state.get("active_child_run_ids", []),
                "paused_child_run_ids": oversight_state.get("paused_child_run_ids", []),
            },
        }

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

        old_run_status = run.status
        should_pause_run = old_run_status == RunStatus.ACTIVE

        task_event = TaskStatusChanged(
            timestamp=self._clock.now(),
            run_id=run_id,
            event_type="task_status_changed",
            task_id=task_id,
            old_status=old_status,
            new_status=TaskStatus.RECOVERING,
            current_attempt=task.current_attempt,
            attempt_snapshots=[attempt.model_dump(mode="json") for attempt in task.attempts],
        )
        events_to_emit: list[WorkflowEvent] = [
            task_event,
            *self._explicit_attempt_updates_from_snapshots(task_event),
        ]
        if should_pause_run:
            events_to_emit.append(
                RunStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="run_status_changed",
                    old_status=old_run_status,
                    new_status=RunStatus.PAUSED,
                    pause_reason="recovery_triggered",
                )
            )

        await self._event_emitter.emit_batch(events_to_emit)
        await commit_with_event_outbox(self._session)
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
            attempt.agent_runner_type = run.agent_runner_type
            attempt.agent_model = run.agent_runner_config.get("model")
            attempt.agent_settings = self._sanitize_agent_runner_config(run.agent_runner_config)
            # Capture start_commit: recovery retry starts from where the previous attempt ended.
            if len(task.attempts) >= 2:
                prev_end = task.attempts[-2].end_commit
                if prev_end:
                    attempt.start_commit = prev_end

        old_run_status = run.status
        should_resume_run = old_run_status == RunStatus.PAUSED

        task_event = TaskStatusChanged(
            timestamp=self._clock.now(),
            run_id=run_id,
            event_type="task_status_changed",
            task_id=task_id,
            old_status=old_status,
            new_status=TaskStatus.BUILDING,
            current_attempt=task.current_attempt,
            attempt_snapshots=[attempt.model_dump(mode="json") for attempt in task.attempts],
        )
        events_to_emit: list[WorkflowEvent] = [
            task_event,
            *self._explicit_attempt_updates_from_snapshots(task_event),
        ]
        if should_resume_run:
            events_to_emit.append(
                RunStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="run_status_changed",
                    old_status=old_run_status,
                    new_status=RunStatus.ACTIVE,
                    pause_reason=None,
                    last_error=None,
                )
            )

        await self._event_emitter.emit_batch(events_to_emit)
        await commit_with_event_outbox(self._session)
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
        now = self._clock.now()
        task.status = TaskStatus.COMPLETED
        if task.attempts:
            task.attempts[-1].outcome = "skipped"
            task.attempts[-1].verifier_comment = notes
            task.attempts[-1].completed_at = now

        task_event = TaskStatusChanged(
            timestamp=now,
            run_id=run_id,
            event_type="task_status_changed",
            task_id=task_id,
            old_status=old_status,
            new_status=TaskStatus.COMPLETED,
            current_attempt=task.current_attempt,
            attempt_snapshots=[attempt.model_dump(mode="json") for attempt in task.attempts],
        )
        events_to_emit: list[WorkflowEvent] = [
            task_event,
            *self._explicit_attempt_updates_from_snapshots(task_event),
        ]

        old_run_status = run.status
        if run.status == RunStatus.PAUSED:
            run.status = RunStatus.ACTIVE
            run.pause_reason = None
            run.last_error = None
            events_to_emit.append(
                RunStatusChanged(
                    timestamp=now,
                    run_id=run_id,
                    event_type="run_status_changed",
                    old_status=old_run_status,
                    new_status=RunStatus.ACTIVE,
                    pause_reason=None,
                    last_error=None,
                )
            )

        # Check step progression to advance to next task
        from orchestrator.workflow.engine.transitions import (
            check_step_progression,
            check_run_completion,
        )
        from orchestrator.workflow import StepCompleted

        # Load routine config if available for condition evaluation
        routine_config = None
        if run.routine_embedded is not None:
            try:
                routine_config = RoutineConfig.model_validate(run.routine_embedded)
            except Exception:
                # If routine config can't be loaded, continue without condition evaluation
                pass

        prev_step_index = run.current_step_index
        buffer = BufferingEmitter()
        step_changed = check_step_progression(
            run,
            routine_config=routine_config,
            clock=self._clock,
            emitter=buffer,
            worktree_path=None,  # Not available in this context
            run_config=run.config,
        )
        events_to_emit.extend(buffer.drain())
        if step_changed:
            last_step_index = min(run.current_step_index, len(run.steps) - 1)
            for i in range(prev_step_index, last_step_index + 1):
                step = run.steps[i]
                if step.completed:
                    events_to_emit.append(
                        StepCompleted(
                            timestamp=self._clock.now(),
                            run_id=run_id,
                            event_type="step_completed",
                            step_index=i,
                            step_id=step.id,
                        )
                    )

        old_status_for_completion = run.status
        new_run_status = check_run_completion(run, self._clock.now())
        if new_run_status is not None:
            events_to_emit.append(
                RunStatusChanged(
                    timestamp=self._clock.now(),
                    run_id=run_id,
                    event_type="run_status_changed",
                    old_status=old_status_for_completion,
                    new_status=new_run_status,
                    pause_reason=run.pause_reason,
                    last_error=run.last_error,
                )
            )

        await self._event_emitter.emit_batch(events_to_emit)
        await commit_with_event_outbox(self._session)
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
        now = self._clock.now()
        task.status = TaskStatus.FAILED
        if task.attempts:
            task.attempts[-1].outcome = "failed"
            task.attempts[-1].verifier_comment = notes
            task.attempts[-1].completed_at = now

        task_event = TaskStatusChanged(
            timestamp=now,
            run_id=run_id,
            event_type="task_status_changed",
            task_id=task_id,
            old_status=old_status,
            new_status=TaskStatus.FAILED,
            current_attempt=task.current_attempt,
            attempt_snapshots=[attempt.model_dump(mode="json") for attempt in task.attempts],
        )
        await self._event_emitter.emit_batch(
            [task_event, *self._explicit_attempt_updates_from_snapshots(task_event)]
        )

        await commit_with_event_outbox(self._session)
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
