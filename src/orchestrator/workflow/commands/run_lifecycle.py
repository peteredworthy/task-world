"""Command handlers for run and task entity creation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, Field

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.state import Run
from orchestrator.workflow.events import (
    AttemptUpdated,
    RunCreated,
    RunDeleted,
    RunWorktreeCommitCompleted,
    RunWorktreeCommitFailed,
    RunWorktreeCommitRequested,
    RunWorktreeCreationFailed,
    RunWorktreeCreationRequested,
    RunWorktreeResetCompleted,
    RunWorktreeResetFailed,
    RunWorktreeResetRequested,
    RunWorktreeUpdated,
    StepCreated,
    TaskAttemptCreated,
    TaskCreated,
    TaskStatusChanged,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from orchestrator.db.access.event_store_v2 import SqliteEventStore
    from orchestrator.workflow.events.types import WorkflowEvent


class InitialStepForRunCreate(BaseModel):
    step_id: str
    config_id: str
    title: str
    order_index: int = 0
    condition: dict[str, Any] | None = None
    step_index: int | None = None
    completed: bool = False
    human_approval: dict[str, Any] | None = None
    skipped: bool = False
    skip_reason: str | None = None


class InitialAttemptForRunCreate(BaseModel):
    task_id: str
    attempt_id: str
    attempt_num: int
    started_at: str | None = None
    completed_at: str | None = None
    paused_at: str | None = None
    outcome: str | None = None
    error: str | None = None
    builder_prompt: str | None = None
    verifier_prompt: str | None = None
    verifier_comment: str | None = None
    grade_snapshot: list[dict[str, Any]] | None = None
    auto_verify_results: list[dict[str, Any]] | None = None
    agent_output: str | None = None
    action_log: Any | None = None
    token_usage_by_model: list[dict[str, Any]] | None = None
    runner_type: str | None = None
    agent_model: str | None = None
    agent_settings: dict[str, Any] | None = None
    start_commit: str | None = None
    end_commit: str | None = None
    tokens_read: int = 0
    tokens_write: int = 0
    tokens_cache: int = 0
    duration_ms: int = 0
    num_actions: int = 0


class InitialTaskForRunCreate(BaseModel):
    task_id: str
    step_id: str
    step_index: int = 0
    config_id: str
    title: str
    complexity: str | None = None
    order_index: int = 0
    max_attempts: int = 3
    checklist: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    parent_task_id: str | None = None
    fan_out_index: int | None = None
    fan_out_input: str | None = None
    fan_out_output: str | None = None
    child_id: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    current_attempt: int = 0
    has_verification: bool = True
    pending_action_type: str | None = None
    pending_clarification_id: str | None = None
    attempts: list[InitialAttemptForRunCreate] = Field(
        default_factory=list[InitialAttemptForRunCreate]
    )


class CreateRunCommand(BaseModel):
    run_id: str
    routine_id: str
    project_path: str
    repo_name: str
    status: RunStatus = RunStatus.DRAFT
    pause_reason: str | None = None
    last_error: str | None = None
    execution_mode: str = "legacy"
    config: dict[str, Any] = Field(default_factory=dict)
    parent_run_id: str | None = None
    parent_task_id: str | None = None
    routine_sha: str | None = None
    routine_source: str | None = None
    routine_embedded: dict[str, Any] | None = None
    routine_path: str | None = None
    routine_commit: str | None = None
    parent_slice_id: str | None = None
    oversight_state: dict[str, Any] = Field(default_factory=dict)
    runner_type: str | None = None
    runner_config: dict[str, Any] = Field(default_factory=dict)
    verifier_model: str | None = None
    worktree_enabled: bool = True
    worktree_path: str | None = None
    delete_worktree_on_completion: bool = False
    source_branch: str | None = None
    source_branch_sha: str | None = None
    merge_strategy: str | None = None
    env_file_specs: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    env_source_dir: str | None = None
    current_step_index: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    agent_runner_started_at: str | None = None
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_tokens_cache: int = 0
    total_duration_ms: int = 0
    total_num_actions: int = 0
    token_usage_by_model: list[dict[str, Any]] | None = None
    transition_tracker: dict[str, Any] | None = None
    aggregate_metrics_are_authoritative: bool = False
    run_snapshot: dict[str, Any] = Field(default_factory=dict)
    initial_steps: list[InitialStepForRunCreate] = Field(
        default_factory=list[InitialStepForRunCreate]
    )
    initial_tasks: list[InitialTaskForRunCreate] = Field(
        default_factory=list[InitialTaskForRunCreate]
    )


class DeleteRunCommand(BaseModel):
    run_id: str
    deleted_by: str | None = None
    reason: str | None = None


def _coerce_task_status(value: Any) -> TaskStatus:
    if isinstance(value, TaskStatus):
        return value
    if isinstance(value, str):
        try:
            return TaskStatus(value)
        except ValueError:
            return TaskStatus.PENDING
    return TaskStatus.PENDING


def _snapshot_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], item) for item in cast(list[Any], value) if isinstance(item, dict)]


def _snapshot_metrics(attempt: dict[str, Any]) -> dict[str, Any]:
    raw_metrics = attempt.get("metrics")
    return dict(cast(dict[str, Any], raw_metrics)) if isinstance(raw_metrics, dict) else {}


def _snapshot_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _snapshot_attempt_needs_update(
    attempt: dict[str, Any],
    task_status: TaskStatus,
    metrics: dict[str, Any],
) -> bool:
    evidence_fields = (
        "outcome",
        "error",
        "completed_at",
        "paused_at",
        "builder_prompt",
        "verifier_prompt",
        "verifier_comment",
        "grade_snapshot",
        "auto_verify_results",
        "agent_output",
        "action_log",
        "token_usage_by_model",
        "agent_settings",
        "start_commit",
        "end_commit",
    )
    return (
        any(attempt.get(field) is not None for field in evidence_fields)
        or any(
            metrics.get(field)
            for field in (
                "tokens_read",
                "tokens_write",
                "tokens_cache",
                "duration_ms",
                "num_actions",
            )
        )
        or task_status != TaskStatus.BUILDING
    )


def expand_run_snapshot_for_projection(event: RunCreated) -> "list[WorkflowEvent]":
    """Translate a legacy run snapshot into canonical child projection events."""
    snapshot = event.run_snapshot
    if not snapshot:
        return []

    run_id = str(snapshot.get("id") or event.run_id)
    events: list[WorkflowEvent] = []
    for fallback_step_index, step in enumerate(_snapshot_dicts(snapshot.get("steps"))):
        step_id_value = step.get("id")
        if not step_id_value:
            continue
        step_id = str(step_id_value)
        step_index = step.get("step_index")
        if not isinstance(step_index, int):
            raw_order_index = step.get("order_index")
            step_index = (
                raw_order_index if isinstance(raw_order_index, int) else fallback_step_index
            )
        events.append(
            StepCreated(
                run_id=run_id,
                timestamp=event.timestamp,
                step_id=step_id,
                config_id=str(step.get("config_id") or ""),
                title=str(step.get("title") or ""),
                order_index=step_index,
                condition=step.get("condition")
                if isinstance(step.get("condition"), dict)
                else None,
                step_index=step_index,
                completed=bool(step.get("completed", False)),
                human_approval=step.get("human_approval")
                if isinstance(step.get("human_approval"), dict)
                else None,
                skipped=bool(step.get("skipped", False)),
                skip_reason=step.get("skip_reason"),
            )
        )
        for fallback_task_index, task in enumerate(_snapshot_dicts(step.get("tasks"))):
            task_id_value = task.get("id")
            if not task_id_value:
                continue
            task_id = str(task_id_value)
            task_status = _coerce_task_status(task.get("status"))
            task_order_index = task.get("order_index")
            if not isinstance(task_order_index, int):
                task_order_index = fallback_task_index
            checklist = task.get("checklist")
            checklist_items = (
                cast(list[dict[str, Any]], checklist) if isinstance(checklist, list) else []
            )
            events.append(
                TaskCreated(
                    run_id=run_id,
                    timestamp=event.timestamp,
                    task_id=task_id,
                    step_id=step_id,
                    step_index=step_index,
                    config_id=str(task.get("config_id") or ""),
                    title=str(task.get("title") or ""),
                    complexity=task.get("complexity"),
                    order_index=task_order_index,
                    max_attempts=_snapshot_int(task.get("max_attempts"), 3),
                    checklist=checklist_items,
                    parent_task_id=task.get("parent_task_id"),
                    fan_out_index=task.get("fan_out_index"),
                    fan_out_input=task.get("fan_out_input"),
                    fan_out_output=task.get("fan_out_output"),
                    child_id=task.get("child_id"),
                    status=task_status,
                    current_attempt=_snapshot_int(task.get("current_attempt"), 0),
                    has_verification=bool(task.get("has_verification", True)),
                    pending_action_type=task.get("pending_action_type"),
                    pending_clarification_id=task.get("pending_clarification_id"),
                )
            )
            for attempt in _snapshot_dicts(task.get("attempts")):
                attempt_id_value = attempt.get("id")
                if not attempt_id_value:
                    continue
                attempt_id = str(attempt_id_value)
                metrics = _snapshot_metrics(attempt)
                events.append(
                    TaskAttemptCreated(
                        run_id=run_id,
                        timestamp=event.timestamp,
                        task_id=task_id,
                        attempt_id=attempt_id,
                        attempt_num=_snapshot_int(attempt.get("attempt_num"), 0),
                        runner_type=attempt.get("agent_runner_type"),
                        agent_model=attempt.get("agent_model"),
                        started_at=attempt.get("started_at"),
                        new_task_status=task_status,
                    )
                )
                if _snapshot_attempt_needs_update(attempt, task_status, metrics):
                    agent_output = attempt.get("agent_output")
                    events.append(
                        AttemptUpdated(
                            run_id=run_id,
                            timestamp=event.timestamp,
                            task_id=task_id,
                            attempt_id=attempt_id,
                            error=attempt.get("error"),
                            outcome=attempt.get("outcome"),
                            output_lines=[agent_output] if agent_output is not None else None,
                            builder_prompt=attempt.get("builder_prompt"),
                            verifier_prompt=attempt.get("verifier_prompt"),
                            verifier_comment=attempt.get("verifier_comment"),
                            grade_snapshot=attempt.get("grade_snapshot"),
                            auto_verify_results=attempt.get("auto_verify_results"),
                            action_log=attempt.get("action_log"),
                            token_usage_by_model=attempt.get("token_usage_by_model"),
                            completed_at=attempt.get("completed_at"),
                            paused_at=attempt.get("paused_at"),
                            tokens_read=metrics.get("tokens_read") or None,
                            tokens_write=metrics.get("tokens_write") or None,
                            tokens_cache=metrics.get("tokens_cache") or None,
                            duration_ms=metrics.get("duration_ms") or None,
                            num_actions=metrics.get("num_actions") or None,
                            agent_runner_type=attempt.get("agent_runner_type"),
                            agent_model=attempt.get("agent_model"),
                            agent_settings=attempt.get("agent_settings"),
                            start_commit=attempt.get("start_commit"),
                            end_commit=attempt.get("end_commit"),
                            new_task_status=task_status
                            if task_status != TaskStatus.BUILDING
                            else None,
                            apply_to_run_totals=False,
                        )
                    )
    return events


def build_create_run_command(run: Run, *, project_path: str = "") -> CreateRunCommand:
    """Translate a runtime Run into explicit event-sourced creation metadata."""
    initial_steps: list[InitialStepForRunCreate] = []
    initial_tasks: list[InitialTaskForRunCreate] = []
    for step_index, step in enumerate(run.steps):
        initial_steps.append(
            InitialStepForRunCreate(
                step_id=step.id,
                config_id=step.config_id,
                title=step.title,
                order_index=step_index,
                condition=step.condition,
                step_index=step_index,
                completed=step.completed,
                human_approval=step.human_approval.model_dump(mode="json")
                if step.human_approval
                else None,
                skipped=step.skipped,
                skip_reason=step.skip_reason,
            )
        )
        for task_index, task in enumerate(step.tasks):
            initial_tasks.append(
                InitialTaskForRunCreate(
                    task_id=task.id,
                    step_id=step.id,
                    step_index=step_index,
                    config_id=task.config_id,
                    title=task.title,
                    complexity=task.complexity,
                    order_index=task_index,
                    max_attempts=task.max_attempts,
                    checklist=[item.model_dump(mode="json") for item in task.checklist],
                    parent_task_id=task.parent_task_id,
                    fan_out_index=task.fan_out_index,
                    fan_out_input=task.fan_out_input,
                    fan_out_output=task.fan_out_output,
                    child_id=task.child_id,
                    status=task.status,
                    current_attempt=task.current_attempt,
                    has_verification=task.has_verification,
                    pending_action_type=task.pending_action_type,
                    pending_clarification_id=task.pending_clarification_id,
                    attempts=[
                        InitialAttemptForRunCreate(
                            task_id=task.id,
                            attempt_id=attempt.id,
                            attempt_num=attempt.attempt_num,
                            started_at=attempt.started_at.isoformat()
                            if attempt.started_at
                            else None,
                            completed_at=attempt.completed_at.isoformat()
                            if attempt.completed_at
                            else None,
                            paused_at=attempt.paused_at.isoformat() if attempt.paused_at else None,
                            outcome=attempt.outcome,
                            error=attempt.error,
                            builder_prompt=attempt.builder_prompt,
                            verifier_prompt=attempt.verifier_prompt,
                            verifier_comment=attempt.verifier_comment,
                            grade_snapshot=[
                                item.model_dump(mode="json") for item in attempt.grade_snapshot
                            ]
                            or None,
                            auto_verify_results=attempt.auto_verify_results or None,
                            agent_output=attempt.agent_output,
                            action_log=attempt.action_log.model_dump(mode="json")
                            if attempt.action_log
                            else None,
                            token_usage_by_model=[
                                usage.model_dump(mode="json")
                                for usage in attempt.token_usage_by_model
                            ]
                            or None,
                            runner_type=attempt.agent_runner_type.value
                            if attempt.agent_runner_type
                            else None,
                            agent_model=attempt.agent_model,
                            agent_settings=attempt.agent_settings or None,
                            start_commit=attempt.start_commit,
                            end_commit=attempt.end_commit,
                            tokens_read=attempt.metrics.tokens_read,
                            tokens_write=attempt.metrics.tokens_write,
                            tokens_cache=attempt.metrics.tokens_cache,
                            duration_ms=attempt.metrics.duration_ms,
                            num_actions=attempt.metrics.num_actions,
                        )
                        for attempt in task.attempts
                    ],
                )
            )

    return CreateRunCommand(
        run_id=run.id,
        routine_id=run.routine_id or "",
        project_path=project_path,
        repo_name=run.repo_name,
        status=run.status,
        pause_reason=run.pause_reason,
        last_error=run.last_error,
        execution_mode=run.execution_mode,
        config=run.config,
        parent_run_id=run.parent_run_id,
        parent_task_id=run.parent_task_id,
        routine_sha=run.routine_sha,
        routine_source=run.routine_source.value if run.routine_source else None,
        routine_embedded=run.routine_embedded,
        routine_path=run.routine_path,
        routine_commit=run.routine_commit,
        parent_slice_id=run.parent_slice_id,
        oversight_state=run.oversight_state,
        runner_type=run.agent_runner_type.value if run.agent_runner_type else None,
        runner_config=run.agent_runner_config,
        verifier_model=run.verifier_model,
        worktree_enabled=run.worktree_enabled,
        worktree_path=run.worktree_path,
        delete_worktree_on_completion=run.delete_worktree_on_completion,
        source_branch=run.source_branch,
        source_branch_sha=run.source_branch_sha,
        merge_strategy=run.merge_strategy,
        env_file_specs=[spec.model_dump(mode="json") for spec in run.env_file_specs],
        env_source_dir=run.env_source_dir,
        current_step_index=run.current_step_index,
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        agent_runner_started_at=run.agent_runner_started_at.isoformat()
        if run.agent_runner_started_at
        else None,
        total_tokens_read=run.total_tokens_read,
        total_tokens_write=run.total_tokens_write,
        total_tokens_cache=run.total_tokens_cache,
        total_duration_ms=run.total_duration_ms,
        total_num_actions=run.total_num_actions,
        token_usage_by_model=[usage.model_dump(mode="json") for usage in run.token_usage_by_model]
        or None,
        transition_tracker=run.transition_tracker.model_dump(mode="json")
        if run.transition_tracker
        else None,
        aggregate_metrics_are_authoritative=True,
        initial_steps=initial_steps,
        initial_tasks=initial_tasks,
    )


async def handle_create_run(
    cmd: CreateRunCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    legacy_snapshot_only = bool(
        cmd.run_snapshot and not cmd.initial_steps and not cmd.initial_tasks
    )
    event = RunCreated(
        run_id=cmd.run_id,
        routine_id=cmd.routine_id,
        project_path=cmd.project_path,
        repo_name=cmd.repo_name,
        status=cmd.status,
        pause_reason=cmd.pause_reason,
        last_error=cmd.last_error,
        execution_mode=cmd.execution_mode,
        config=cmd.config,
        parent_run_id=cmd.parent_run_id,
        parent_task_id=cmd.parent_task_id,
        routine_sha=cmd.routine_sha,
        routine_source=cmd.routine_source,
        routine_embedded=cmd.routine_embedded,
        routine_path=cmd.routine_path,
        routine_commit=cmd.routine_commit,
        parent_slice_id=cmd.parent_slice_id,
        oversight_state=cmd.oversight_state,
        runner_type=cmd.runner_type,
        runner_config=cmd.runner_config,
        verifier_model=cmd.verifier_model,
        worktree_enabled=cmd.worktree_enabled,
        worktree_path=cmd.worktree_path,
        delete_worktree_on_completion=cmd.delete_worktree_on_completion,
        source_branch=cmd.source_branch,
        source_branch_sha=cmd.source_branch_sha,
        merge_strategy=cmd.merge_strategy,
        env_file_specs=cmd.env_file_specs,
        env_source_dir=cmd.env_source_dir,
        current_step_index=cmd.current_step_index,
        created_at=cmd.created_at,
        updated_at=cmd.updated_at,
        started_at=cmd.started_at,
        completed_at=cmd.completed_at,
        agent_runner_started_at=cmd.agent_runner_started_at,
        total_tokens_read=cmd.total_tokens_read,
        total_tokens_write=cmd.total_tokens_write,
        total_tokens_cache=cmd.total_tokens_cache,
        total_duration_ms=cmd.total_duration_ms,
        total_num_actions=cmd.total_num_actions,
        token_usage_by_model=cmd.token_usage_by_model,
        transition_tracker=cmd.transition_tracker,
        run_snapshot=cmd.run_snapshot if legacy_snapshot_only else {},
    )

    if legacy_snapshot_only:
        await event_store.append([event])
        return [event]

    events: list[WorkflowEvent] = [event]
    for step in cmd.initial_steps:
        events.append(
            StepCreated(
                run_id=cmd.run_id,
                step_id=step.step_id,
                config_id=step.config_id,
                title=step.title,
                order_index=step.order_index,
                condition=step.condition,
                step_index=step.step_index,
                completed=step.completed,
                human_approval=step.human_approval,
                skipped=step.skipped,
                skip_reason=step.skip_reason,
            )
        )
    for task in cmd.initial_tasks:
        events.append(
            TaskCreated(
                run_id=cmd.run_id,
                task_id=task.task_id,
                step_id=task.step_id,
                step_index=task.step_index,
                config_id=task.config_id,
                title=task.title,
                complexity=task.complexity,
                order_index=task.order_index,
                max_attempts=task.max_attempts,
                checklist=task.checklist,
                parent_task_id=task.parent_task_id,
                fan_out_index=task.fan_out_index,
                fan_out_input=task.fan_out_input,
                fan_out_output=task.fan_out_output,
                child_id=task.child_id,
                status=task.status,
                current_attempt=task.current_attempt,
                has_verification=task.has_verification,
                pending_action_type=task.pending_action_type,
                pending_clarification_id=task.pending_clarification_id,
            )
        )
        for attempt in task.attempts:
            events.append(
                TaskAttemptCreated(
                    run_id=cmd.run_id,
                    task_id=attempt.task_id,
                    attempt_id=attempt.attempt_id,
                    attempt_num=attempt.attempt_num,
                    runner_type=attempt.runner_type,
                    agent_model=attempt.agent_model,
                    started_at=attempt.started_at,
                    new_task_status=task.status,
                )
            )
            if (
                attempt.outcome is not None
                or attempt.error is not None
                or attempt.completed_at is not None
                or attempt.paused_at is not None
                or attempt.builder_prompt is not None
                or attempt.verifier_prompt is not None
                or attempt.verifier_comment is not None
                or attempt.grade_snapshot is not None
                or attempt.auto_verify_results is not None
                or attempt.agent_output is not None
                or attempt.action_log is not None
                or attempt.token_usage_by_model is not None
                or attempt.agent_settings is not None
                or attempt.start_commit is not None
                or attempt.end_commit is not None
                or attempt.tokens_read
                or attempt.tokens_write
                or attempt.tokens_cache
                or attempt.duration_ms
                or attempt.num_actions
                or task.status != TaskStatus.BUILDING
            ):
                events.append(
                    AttemptUpdated(
                        run_id=cmd.run_id,
                        task_id=attempt.task_id,
                        attempt_id=attempt.attempt_id,
                        error=attempt.error,
                        outcome=attempt.outcome,
                        output_lines=[attempt.agent_output]
                        if attempt.agent_output is not None
                        else None,
                        builder_prompt=attempt.builder_prompt,
                        verifier_prompt=attempt.verifier_prompt,
                        verifier_comment=attempt.verifier_comment,
                        grade_snapshot=attempt.grade_snapshot,
                        auto_verify_results=attempt.auto_verify_results,
                        action_log=attempt.action_log,
                        token_usage_by_model=attempt.token_usage_by_model,
                        completed_at=attempt.completed_at,
                        paused_at=attempt.paused_at,
                        tokens_read=attempt.tokens_read or None,
                        tokens_write=attempt.tokens_write or None,
                        tokens_cache=attempt.tokens_cache or None,
                        duration_ms=attempt.duration_ms or None,
                        num_actions=attempt.num_actions or None,
                        agent_runner_type=attempt.runner_type,
                        agent_model=attempt.agent_model,
                        agent_settings=attempt.agent_settings,
                        start_commit=attempt.start_commit,
                        end_commit=attempt.end_commit,
                        new_task_status=task.status if task.status != TaskStatus.BUILDING else None,
                        apply_to_run_totals=not cmd.aggregate_metrics_are_authoritative,
                    )
                )
        if not task.attempts and task.status != TaskStatus.PENDING:
            events.append(
                TaskStatusChanged(
                    run_id=cmd.run_id,
                    event_type="task_status_changed",
                    task_id=task.task_id,
                    old_status=TaskStatus.PENDING,
                    new_status=task.status,
                )
            )

    await event_store.append(events)
    return events


async def handle_delete_run(
    cmd: DeleteRunCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunDeleted(
        run_id=cmd.run_id,
        deleted_by=cmd.deleted_by,
        reason=cmd.reason,
    )
    await event_store.append([event])
    return [event]


class UpdateRunWorktreeCommand(BaseModel):
    run_id: str
    worktree_path: str
    source_branch_sha: str | None = None


class RequestRunWorktreeCreationCommand(BaseModel):
    run_id: str
    repo_name: str
    source_branch: str


class FailRunWorktreeCreationCommand(BaseModel):
    run_id: str
    error: str


class RequestRunWorktreeResetCommand(BaseModel):
    run_id: str
    worktree_path: str
    reset_type: str
    target_ref: str | None = None
    branch_name: str | None = None
    head_before: str | None = None
    reason: str | None = None


class CompleteRunWorktreeResetCommand(BaseModel):
    run_id: str
    worktree_path: str
    reset_type: str
    target_ref: str | None = None
    branch_name: str | None = None
    head_before: str | None = None
    head_after: str | None = None
    reason: str | None = None


class FailRunWorktreeResetCommand(BaseModel):
    run_id: str
    worktree_path: str
    reset_type: str
    error: str
    target_ref: str | None = None
    branch_name: str | None = None
    head_before: str | None = None
    reason: str | None = None


class RequestRunWorktreeCommitCommand(BaseModel):
    run_id: str
    task_id: str
    attempt_id: str | None = None
    worktree_path: str
    commit_type: str
    message: str
    reason: str | None = None
    head_before: str | None = None


class CompleteRunWorktreeCommitCommand(BaseModel):
    run_id: str
    task_id: str
    attempt_id: str | None = None
    worktree_path: str
    commit_type: str
    message: str
    created_commit: bool = False
    reason: str | None = None
    head_before: str | None = None
    head_after: str | None = None
    commit_sha: str | None = None


class FailRunWorktreeCommitCommand(BaseModel):
    run_id: str
    task_id: str
    attempt_id: str | None = None
    worktree_path: str
    commit_type: str
    message: str
    error: str
    reason: str | None = None
    head_before: str | None = None


async def handle_request_run_worktree_creation(
    cmd: RequestRunWorktreeCreationCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunWorktreeCreationRequested(
        run_id=cmd.run_id,
        repo_name=cmd.repo_name,
        source_branch=cmd.source_branch,
    )
    await event_store.append([event])
    return [event]


async def handle_fail_run_worktree_creation(
    cmd: FailRunWorktreeCreationCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunWorktreeCreationFailed(
        run_id=cmd.run_id,
        error=cmd.error,
    )
    await event_store.append([event])
    return [event]


async def handle_request_run_worktree_commit(
    cmd: RequestRunWorktreeCommitCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunWorktreeCommitRequested(
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        attempt_id=cmd.attempt_id,
        worktree_path=cmd.worktree_path,
        commit_type=cmd.commit_type,
        message=cmd.message,
        reason=cmd.reason,
        head_before=cmd.head_before,
    )
    await event_store.append([event])
    return [event]


async def handle_complete_run_worktree_commit(
    cmd: CompleteRunWorktreeCommitCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunWorktreeCommitCompleted(
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        attempt_id=cmd.attempt_id,
        worktree_path=cmd.worktree_path,
        commit_type=cmd.commit_type,
        message=cmd.message,
        created_commit=cmd.created_commit,
        reason=cmd.reason,
        head_before=cmd.head_before,
        head_after=cmd.head_after,
        commit_sha=cmd.commit_sha,
    )
    await event_store.append([event])
    return [event]


async def handle_fail_run_worktree_commit(
    cmd: FailRunWorktreeCommitCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunWorktreeCommitFailed(
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        attempt_id=cmd.attempt_id,
        worktree_path=cmd.worktree_path,
        commit_type=cmd.commit_type,
        message=cmd.message,
        error=cmd.error,
        reason=cmd.reason,
        head_before=cmd.head_before,
    )
    await event_store.append([event])
    return [event]


async def handle_request_run_worktree_reset(
    cmd: RequestRunWorktreeResetCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunWorktreeResetRequested(
        run_id=cmd.run_id,
        worktree_path=cmd.worktree_path,
        reset_type=cmd.reset_type,
        target_ref=cmd.target_ref,
        branch_name=cmd.branch_name,
        head_before=cmd.head_before,
        reason=cmd.reason,
    )
    await event_store.append([event])
    return [event]


async def handle_complete_run_worktree_reset(
    cmd: CompleteRunWorktreeResetCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunWorktreeResetCompleted(
        run_id=cmd.run_id,
        worktree_path=cmd.worktree_path,
        reset_type=cmd.reset_type,
        target_ref=cmd.target_ref,
        branch_name=cmd.branch_name,
        head_before=cmd.head_before,
        head_after=cmd.head_after,
        reason=cmd.reason,
    )
    await event_store.append([event])
    return [event]


async def handle_fail_run_worktree_reset(
    cmd: FailRunWorktreeResetCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunWorktreeResetFailed(
        run_id=cmd.run_id,
        worktree_path=cmd.worktree_path,
        reset_type=cmd.reset_type,
        error=cmd.error,
        target_ref=cmd.target_ref,
        branch_name=cmd.branch_name,
        head_before=cmd.head_before,
        reason=cmd.reason,
    )
    await event_store.append([event])
    return [event]


async def handle_update_run_worktree(
    cmd: UpdateRunWorktreeCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = RunWorktreeUpdated(
        run_id=cmd.run_id,
        worktree_path=cmd.worktree_path,
        source_branch_sha=cmd.source_branch_sha,
    )
    await event_store.append([event])
    return [event]


class CreateTaskCommand(BaseModel):
    run_id: str
    task_id: str
    step_id: str
    step_index: int
    config_id: str
    title: str
    complexity: str | None = None
    order_index: int = 0
    max_attempts: int = 3
    checklist: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    parent_task_id: str | None = None
    fan_out_index: int | None = None
    fan_out_input: str | None = None
    fan_out_output: str | None = None
    child_id: str | None = None
    has_verification: bool = True


async def handle_create_task(
    cmd: CreateTaskCommand,
    event_store: "SqliteEventStore",
    session: "AsyncSession",
) -> "list[WorkflowEvent]":
    event = TaskCreated(
        run_id=cmd.run_id,
        task_id=cmd.task_id,
        step_id=cmd.step_id,
        step_index=cmd.step_index,
        config_id=cmd.config_id,
        title=cmd.title,
        complexity=cmd.complexity,
        order_index=cmd.order_index,
        max_attempts=cmd.max_attempts,
        checklist=cmd.checklist,
        parent_task_id=cmd.parent_task_id,
        fan_out_index=cmd.fan_out_index,
        fan_out_input=cmd.fan_out_input,
        fan_out_output=cmd.fan_out_output,
        child_id=cmd.child_id,
        has_verification=cmd.has_verification,
    )
    await event_store.append([event])
    return [event]
