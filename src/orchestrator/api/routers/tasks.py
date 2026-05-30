"""Task API endpoints."""

import glob as glob_mod
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.runners import get_agent_system_prompt, resolve_agent_name
from orchestrator.api.deps import (
    get_current_user,
    get_routine_dirs,
    get_run_repository,
    get_runner_executor,
    get_session,
    get_signal_transport,
    get_summary_caches,
    get_workflow_service,
)
from orchestrator.api.schemas.tasks import (
    ActionLogEntrySchema,
    ActionLogSchema,
    AgentLogsResponse,
    ApproveTaskRequest,
    ForceAcceptTaskRequest,
    AttemptSchema,
    CallbackInstructions,
    ChecklistItemSchema,
    GradeSnapshotItemSchema,
    ModelTokenUsageSchema,
    PromptResponse,
    RejectTaskRequest,
    SetGradeRequest,
    TaskDetailResponse,
    FanOutChildSummarySchema,
    ToolResultDetailSchema,
    ToolUseDetailSchema,
    TurnMetricsSchema,
    TransitionResponse,
    UpdateChecklistRequest,
)
from orchestrator.config.enums import ChecklistStatus, RoutineSource, RunStatus, TaskStatus
from orchestrator.config.models import MCPServerConfig, RoutineConfig
from orchestrator.db import RunRepository, commit_with_event_outbox
from orchestrator.git import WorktreeCommitError
from orchestrator.config import discover_routines, RoutineNotFoundError
from orchestrator.state.errors import ChecklistItemNotFoundError, TaskNotFoundError
from orchestrator.workflow import (
    ArtifactRegistry,
    ClarificationRequest,
    ClarificationResponse,
    decisions_from_config,
    resolve_artifact_path,
    GateBlockedError,
    InvalidTransitionError,
    TaskContextBuilder,
    generate_builder_prompt,
    generate_verifier_prompt,
    SummaryCache,
    derive_output_path,
    resolve_template,
    SignalTransport,
    WorkflowSignal,
)
from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.workflow.service import WorkflowService
from orchestrator.workflow.service import find_task_config

router = APIRouter(prefix="/api/runs", tags=["tasks"])


def _infer_fan_out_child_status(parent_status: TaskStatus) -> str:
    if parent_status in (TaskStatus.COMPLETED, TaskStatus.VERIFYING):
        return TaskStatus.COMPLETED.value
    if parent_status == TaskStatus.FAILED:
        return TaskStatus.FAILED.value
    if parent_status == TaskStatus.FAN_OUT_RUNNING:
        return TaskStatus.BUILDING.value
    return TaskStatus.PENDING.value


def _looks_like_ndjson_agent_stream(output: str) -> bool:
    """Heuristic for legacy raw CLI streams that should be reparsed."""
    if '"type":"item.completed"' in output:
        return True
    if '"type":"thread.started"' in output:
        return True
    if '"type":"message.created"' in output:
        return True
    return False


def _parse_action_log_from_raw(output: str, agent_settings: dict[str, Any]) -> Any | None:
    """Best-effort parser for raw agent stream output."""
    command = str(agent_settings.get("command", "")).strip().lower()
    parser: Any | None = None

    if command == "codex":
        from orchestrator.runners import CodexStreamParser

        parser = CodexStreamParser()
    elif command == "claude":
        from orchestrator.runners import ClaudeStreamParser

        parser = ClaudeStreamParser()
    else:
        return None

    for line in output.splitlines():
        parser.parse_line(line)
    parsed = parser.finalize()
    if not parsed.entries:
        return None
    return parsed


@router.get("/{run_id}/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    run_id: str,
    task_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> TaskDetailResponse:
    """Get task detail with checklist and attempts."""
    task = await service.get_task(run_id, task_id)
    run = await service.get_run(run_id)

    persisted_fan_out_children: list[FanOutChildSummarySchema] = []
    for step in run.steps:
        for step_task in step.tasks:
            if step_task.parent_task_id == task.id:
                persisted_fan_out_children.append(
                    FanOutChildSummarySchema(
                        id=step_task.id,
                        title=step_task.title,
                        status=step_task.status.value,
                        current_attempt=step_task.current_attempt,
                        fan_out_input=step_task.fan_out_input,
                        fan_out_output=step_task.fan_out_output,
                        is_synthetic=False,
                    )
                )

    fan_out_children = persisted_fan_out_children
    if (
        not fan_out_children
        and task.status == TaskStatus.PENDING
        and run.routine_embedded is not None
        and run.worktree_path
    ):
        routine_config = RoutineConfig.model_validate(run.routine_embedded)
        step_config_id: str | None = None
        for step in run.steps:
            if any(step_task.id == task.id for step_task in step.tasks):
                step_config_id = step.config_id
                break

        task_config = find_task_config(routine_config, task.config_id, step_config_id)
        if task_config is not None and task_config.fan_out is not None:
            variables = {k: str(v) for k, v in run.config.items() if v is not None}
            input_glob = resolve_template(task_config.fan_out.input_glob, variables=variables)
            pattern = str(Path(run.worktree_path) / input_glob)
            matched_files = sorted(glob_mod.glob(pattern, recursive=True))
            inferred_status = _infer_fan_out_child_status(task.status)
            fan_out_children = [
                FanOutChildSummarySchema(
                    id=None,
                    title=f"{task.title} [{Path(abs_path).name}]",
                    status=inferred_status,
                    current_attempt=1 if inferred_status != TaskStatus.PENDING.value else 0,
                    fan_out_input=str(Path(abs_path).relative_to(run.worktree_path)),
                    fan_out_output=derive_output_path(
                        task_config.fan_out.output_pattern,
                        str(Path(abs_path).relative_to(run.worktree_path)),
                        variables,
                    ),
                    is_synthetic=True,
                )
                for abs_path in matched_files
            ]

    return TaskDetailResponse(
        id=task.id,
        config_id=task.config_id,
        title=task.title,
        status=task.status.value,
        complexity=task.complexity,
        checklist=[
            ChecklistItemSchema(
                req_id=item.req_id,
                desc=item.desc,
                priority=item.priority.value,
                status=item.status.value,
                note=item.note,
                grade=item.grade,
                grade_reason=item.grade_reason,
            )
            for item in task.checklist
        ],
        attempts=[
            AttemptSchema(
                id=att.id,
                attempt_num=att.attempt_num,
                started_at=att.started_at,
                completed_at=att.completed_at,
                builder_prompt=att.builder_prompt,
                verifier_prompt=att.verifier_prompt,
                verifier_comment=att.verifier_comment,
                outcome=att.outcome,
                metrics=att.metrics.model_dump(mode="json"),
                grade_snapshot=[
                    GradeSnapshotItemSchema(
                        req_id=gs.req_id,
                        grade=gs.grade,
                        grade_reason=gs.grade_reason,
                    )
                    for gs in att.grade_snapshot
                ],
                auto_verify_results=att.auto_verify_results,
                token_usage_by_model=[
                    ModelTokenUsageSchema(
                        model=u.model,
                        cache_read_tokens=u.cache_read_tokens,
                        cache_creation_tokens=u.cache_creation_tokens,
                        input_tokens=u.input_tokens,
                        output_tokens=u.output_tokens,
                        cost_per_m_cache_read=u.cost_per_m_cache_read,
                        cost_per_m_cache_creation=u.cost_per_m_cache_creation,
                        cost_per_m_input=u.cost_per_m_input,
                        cost_per_m_output=u.cost_per_m_output,
                        total_cost_usd=round(u.total_cost_usd, 6),
                    )
                    for u in att.token_usage_by_model
                ],
                agent_runner_type=att.agent_runner_type.value if att.agent_runner_type else None,
                agent_model=att.agent_model,
                agent_settings=att.agent_settings,
                error=att.error,
                has_output=bool(att.agent_output),
                has_action_log=bool(att.action_log),
                start_commit=att.start_commit,
                end_commit=att.end_commit,
            )
            for att in task.attempts
        ],
        current_attempt=task.current_attempt,
        max_attempts=task.max_attempts,
        parent_task_id=task.parent_task_id,
        fan_out_index=task.fan_out_index,
        fan_out_input=task.fan_out_input,
        fan_out_output=task.fan_out_output,
        fan_out_children=fan_out_children,
    )


@router.post("/{run_id}/tasks/{task_id}/start", response_model=TransitionResponse)
async def start_task(
    run_id: str,
    task_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> TransitionResponse:
    """Start building a task."""
    result = await service.start_task(run_id, task_id)
    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )


@router.post("/{run_id}/tasks/{task_id}/submit", response_model=TransitionResponse)
async def submit_task(
    run_id: str,
    task_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    signal_transport: Annotated[SignalTransport, Depends(get_signal_transport)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TransitionResponse:
    """Submit task for verification (BUILDING → VERIFYING).

    Runs pre-submission checks (auto-verify + checklist gate) synchronously.
    On success, enqueues an ACTIVITY_COMPLETED signal and returns the current
    outcome. The actual BUILDING → VERIFYING state transition is applied when
    the signal is processed.

    On failure, returns error details to the agent without changing state.
    """
    try:
        result = await service.check_submission(run_id, task_id)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except GateBlockedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except WorktreeCommitError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not result.success:
        raise HTTPException(
            status_code=422,
            detail=result.error or "Submission check failed",
        )

    # Gate passed — enqueue signal for the BUILDING → VERIFYING transition.
    # Skip for idempotent (already VERIFYING) and recovery (already handled) cases.
    if result.new_status == TaskStatus.BUILDING:
        await signal_transport.enqueue(
            run_id,
            WorkflowSignal.ACTIVITY_COMPLETED,
            payload={"task_id": task_id},
        )
        await commit_with_event_outbox(session)

    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )


@router.post(
    "/{run_id}/tasks/{task_id}/complete-verification",
    response_model=TransitionResponse,
)
async def complete_verification_endpoint(
    run_id: str,
    task_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    signal_transport: Annotated[SignalTransport, Depends(get_signal_transport)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TransitionResponse:
    """Complete verification phase and transition task to its outcome state.

    Validates that the run and task are in states that allow completing
    verification.  On success, enqueues an ACTIVITY_VERIFIED signal; the actual
    grade evaluation and VERIFYING → outcome transition happen when the signal
    is processed.
    """
    try:
        result = await service.check_verification(run_id, task_id)
    except StaleDataError:
        raise HTTPException(status_code=409, detail="Concurrent modification — please retry")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not result.success:
        raise HTTPException(
            status_code=422,
            detail=result.error or "Verification check failed",
        )

    # Enqueue signal only if task is still awaiting verification outcome
    if result.new_status == TaskStatus.VERIFYING:
        await signal_transport.enqueue(
            run_id,
            WorkflowSignal.ACTIVITY_VERIFIED,
            payload={"task_id": task_id},
        )
        await commit_with_event_outbox(session)

    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )


class CompleteRecoveryRequest(BaseModel):
    outcome: str  # "retry", "skip", or "abandon"
    notes: str = ""


@router.post(
    "/{run_id}/tasks/{task_id}/complete-recovery",
    response_model=TransitionResponse,
)
async def complete_recovery(
    run_id: str,
    task_id: str,
    request: CompleteRecoveryRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> TransitionResponse:
    """Complete recovery phase by specifying the recovery outcome."""
    outcome = request.outcome
    notes = request.notes
    if outcome == "retry":
        result = await service.complete_recovery_retry(run_id, task_id, notes)
    elif outcome == "skip":
        result = await service.complete_recovery_skip(run_id, task_id, notes)
    elif outcome == "abandon":
        result = await service.complete_recovery_abandon(run_id, task_id, notes)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid outcome {outcome!r}. Must be one of: retry, skip, abandon",
        )
    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )


@router.post(
    "/{run_id}/tasks/{task_id}/retry",
)
async def retry_fan_out_child(
    run_id: str,
    task_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> dict[str, str]:
    """Retry a failed fan-out child task.

    Resets the child to PENDING and its parent to FAN_OUT_RUNNING.
    If the run is active it will be paused so the executor restarts
    from the correct step on resume.
    """
    run = await service.retry_fan_out_child(run_id, task_id)
    return {
        "status": run.status.value,
        "message": (
            "Child task reset to pending. "
            + (
                "Run paused — resume to re-execute the fan-out."
                if run.status == RunStatus.PAUSED
                else "Resume the run to re-execute the fan-out."
            )
        ),
    }


@router.patch(
    "/{run_id}/tasks/{task_id}/checklist/{req_id}",
    response_model=ChecklistItemSchema,
)
async def update_checklist_item(
    run_id: str,
    task_id: str,
    req_id: str,
    request: UpdateChecklistRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> ChecklistItemSchema:
    """Update a checklist item status."""
    item = await service.update_checklist_item(
        run_id,
        task_id,
        req_id,
        ChecklistStatus(request.status),
        request.note,
    )
    return ChecklistItemSchema(
        req_id=item.req_id,
        desc=item.desc,
        priority=item.priority.value,
        status=item.status.value,
        note=item.note,
        grade=item.grade,
        grade_reason=item.grade_reason,
    )


@router.put(
    "/{run_id}/tasks/{task_id}/checklist/{req_id}/grade",
    response_model=ChecklistItemSchema,
)
async def set_grade(
    run_id: str,
    task_id: str,
    req_id: str,
    request: SetGradeRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> ChecklistItemSchema:
    """Set a grade on a checklist item."""
    item = await service.set_grade(
        run_id,
        task_id,
        req_id,
        request.grade,
        request.grade_reason,
    )
    return ChecklistItemSchema(
        req_id=item.req_id,
        desc=item.desc,
        priority=item.priority.value,
        status=item.status.value,
        note=item.note,
        grade=item.grade,
        grade_reason=item.grade_reason,
    )


def _build_callback_instructions(
    request: Request,
    run_id: str,
    task_id: str,
    mcp_servers: list[MCPServerConfig] | None = None,
) -> CallbackInstructions:
    """Build callback instructions for external agents."""
    # Determine base URL from request
    base_url = str(request.base_url).rstrip("/")

    rest_instructions = f"""## Orchestrator REST API
Base URL: {base_url}
Run ID: {run_id}, Task ID: {task_id}

Endpoints:
- GET  {base_url}/api/runs/{run_id}/tasks/{task_id}          → Get current task state
- PATCH {base_url}/api/runs/{run_id}/tasks/{task_id}/checklist/{{req_id}}  → Mark requirement done/blocked
  Body: {{"status": "done"}} or {{"status": "blocked", "note": "reason"}}
- POST {base_url}/api/runs/{run_id}/tasks/{task_id}/submit   → Submit task for verification
- PUT  {base_url}/api/runs/{run_id}/tasks/{task_id}/checklist/{{req_id}}/grade → Set grade on requirement
  Body: {{"grade": "A", "grade_reason": "optional reason"}}
- POST {base_url}/api/runs/{run_id}/tasks/{task_id}/complete-verification → Complete verification phase
- POST {base_url}/api/runs/{run_id}/tasks/{task_id}/escalate → Flag a requirement as unfulfillable (pauses run)
  Body: {{"requirement_id": "R1", "reason": "explanation of why it cannot be fulfilled"}}"""

    mcp_instructions = f"""## Orchestrator MCP Server
Connect to: {base_url}/mcp/sse
Run ID: {run_id}, Task ID: {task_id}

Available MCP tools:
- orchestrator_get_requirements(run_id, task_id) → Get checklist items
- orchestrator_update_checklist(run_id, task_id, req_id, status, note?) → Mark requirement done/blocked
- orchestrator_escalate_requirement(run_id, task_id, requirement_id, reason) → Flag requirement as unfulfillable (pauses run)
- orchestrator_submit(run_id, task_id) → Submit task for verification"""

    return CallbackInstructions(
        run_id=run_id,
        task_id=task_id,
        api_base_url=base_url,
        rest_instructions=rest_instructions,
        mcp_instructions=mcp_instructions,
        mcp_servers=mcp_servers,
    )


def _find_clarification_line_range(
    clarifications_path: str, clarification_number: int
) -> tuple[str, int, int] | None:
    """Find the line range for a clarification section in the artifact file."""
    path = Path(clarifications_path)
    if not path.exists():
        return None

    lines = path.read_text().splitlines()
    section_prefix = f"## Clarification {clarification_number} "
    start_line: int | None = None

    for idx, line in enumerate(lines, start=1):
        if line.startswith(section_prefix):
            start_line = idx
            break

    if start_line is None:
        return None

    end_line = len(lines)
    for idx, line in enumerate(lines[start_line:], start=start_line + 1):
        if line.startswith("## Clarification "):
            end_line = idx - 1
            break

    return (clarifications_path, start_line, end_line)


async def _get_builder_clarification_context(
    repo: RunRepository,
    run_id: str,
    task_id: str,
    routine_config: RoutineConfig,
    run_config: dict[str, str],
    worktree_path: str | None,
) -> tuple[str | None, tuple[str, int, int] | None, list[str] | None, str | None]:
    """Resolve clarification context for resumed builder prompts."""
    clarifications_path: str | None = None
    if routine_config.clarifications is not None:
        relative = resolve_artifact_path(routine_config.clarifications.artifact_path, run_config)
        clarifications_path = (
            str(Path(worktree_path) / relative) if worktree_path is not None else relative
        )

    history = await repo.get_clarification_history(run_id, task_id)
    latest_with_response: tuple[int, ClarificationRequest, ClarificationResponse] | None = None
    for idx, pair in enumerate(history, start=1):
        req, resp = pair
        if resp is not None:
            latest_with_response = (idx, req, resp)

    if latest_with_response is None:
        return clarifications_path, None, None, None

    clarification_number, request, response = latest_with_response
    skipped_ids = {answer.question_id for answer in response.answers if answer.skipped}
    skipped_questions = (
        [question.question for question in request.questions if question.id in skipped_ids]
        if skipped_ids
        else None
    )

    skip_reason: str | None = None
    for answer in response.answers:
        if answer.skipped and answer.skip_reason:
            skip_reason = answer.skip_reason
            break

    clarification_line_range: tuple[str, int, int] | None = None
    if clarifications_path is not None:
        clarification_line_range = _find_clarification_line_range(
            clarifications_path, clarification_number
        )

    return clarifications_path, clarification_line_range, skipped_questions, skip_reason


@router.get("/{run_id}/tasks/{task_id}/prompt", response_model=PromptResponse)
async def get_task_prompt(
    request: Request,
    run_id: str,
    task_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    repo: Annotated[RunRepository, Depends(get_run_repository)],
    routine_dirs: Annotated[list[tuple[Path, RoutineSource]], Depends(get_routine_dirs)],
    session: Annotated[AsyncSession, Depends(get_session)],
    summary_caches: Annotated[dict[str, Any], Depends(get_summary_caches)],
) -> PromptResponse:
    """Get the appropriate prompt for a task based on its current status.

    Returns the builder prompt when the task is in BUILDING state,
    or the verifier prompt when the task is in VERIFYING state.
    Includes callback instructions for external agents.
    Raises InvalidTransitionError for other states.
    """
    run = await service.get_run(run_id)
    task_state = await service.get_task(run_id, task_id)

    # Only BUILDING and VERIFYING states have prompts
    if task_state.status not in (TaskStatus.BUILDING, TaskStatus.VERIFYING):
        raise InvalidTransitionError(task_state.status.value, "prompt_generation")

    # Resolve routine config: prefer embedded, fall back to discovery
    routine_config: RoutineConfig | None = None
    if run.routine_embedded is not None:
        routine_config = RoutineConfig.model_validate(run.routine_embedded)
    else:
        if run.routine_id is None:
            raise RoutineNotFoundError("unknown")
        found = discover_routines(routine_dirs)
        for routine in found:
            if routine.config.id == run.routine_id:
                routine_config = routine.config
                break
    if routine_config is None:
        raise RoutineNotFoundError(run.routine_id or "unknown")

    # Find the task config and its step context
    # First, find which step contains this task to disambiguate config lookup
    step_config_id: str | None = None
    for step in run.steps:
        for task in step.tasks:
            if task.id == task_state.id:
                step_config_id = step.config_id
                break
        if step_config_id is not None:
            break

    task_config = None
    step_context: str | None = None
    mcp_servers: list[MCPServerConfig] | None = None
    step_builder_agent: str | None = None
    step_verifier_agent: str | None = None
    for step in routine_config.steps:
        if step_config_id is not None and step.id != step_config_id:
            continue
        for task in step.tasks:
            if task.id == task_state.config_id:
                task_config = task
                step_context = step.step_context
                mcp_servers = task.mcp_servers if task.mcp_servers is not None else step.mcp_servers
                step_builder_agent = step.builder_agent
                step_verifier_agent = step.verifier_agent
                break
        if task_config is not None:
            break
    if task_config is None:
        raise TaskNotFoundError(run_id, task_id)

    callback = _build_callback_instructions(request, run_id, task_id, mcp_servers=mcp_servers)

    # Build artifact context if the task has context_from entries
    run_config = dict(run.config)
    if task_config.context_from:
        worktree_path = Path(run.worktree_path) if run.worktree_path else None
        context_builder = TaskContextBuilder(ArtifactRegistry(), worktree_path=worktree_path)
        # Use a run-scoped SummaryCache so repeated prompt calls for the same
        # run reuse cached summaries instead of re-generating them each time.
        if run_id not in summary_caches:
            summary_caches[run_id] = SummaryCache()
        summary_cache = summary_caches[run_id]
        artifact_context = await context_builder.build_context(
            run_id=run_id,
            context_sources=task_config.context_from,
            variables=run.config,
            summary_cache=summary_cache,
        )
        # Merge artifact context into run config so {{var}} substitution picks it up.
        # Also expose keys under "context.<name>" namespace for templates using {{context.foo}}.
        run_config.update(artifact_context)
        run_config.update({f"context.{k}": v for k, v in artifact_context.items()})

    if task_state.status == TaskStatus.BUILDING:
        (
            clarifications_path,
            clarification_line_range,
            skipped_questions,
            skip_reason,
        ) = await _get_builder_clarification_context(
            repo=repo,
            run_id=run_id,
            task_id=task_id,
            routine_config=routine_config,
            run_config=run.config,
            worktree_path=run.worktree_path,
        )
        decisions = decisions_from_config(run.config)
        prompt = generate_builder_prompt(
            task_config,
            task_state,
            run_config,
            step_context=step_context,
            clarifications_path=clarifications_path,
            clarification_line_range=clarification_line_range,
            skipped_questions=skipped_questions,
            skip_reason=skip_reason,
            decisions=decisions,
        )
        agent_name = resolve_agent_name(
            "builder",
            task_config.builder_agent,
            step_builder_agent,
            routine_config.builder_agent,
        )
        agent_system_prompt = await get_agent_system_prompt(session, agent_name)
        system = (
            agent_system_prompt + "\n\n---\n\n" + prompt.system
            if agent_system_prompt
            else prompt.system
        )
        return PromptResponse(system=system, user=prompt.user, phase="building", callback=callback)
    else:
        # TaskStatus.VERIFYING
        prompt = generate_verifier_prompt(task_config, task_state, step_context=step_context)
        agent_name = resolve_agent_name(
            "verifier",
            task_config.verifier_agent,
            step_verifier_agent,
            routine_config.verifier_agent,
        )
        agent_system_prompt = await get_agent_system_prompt(session, agent_name)
        system = (
            agent_system_prompt + "\n\n---\n\n" + prompt.system
            if agent_system_prompt
            else prompt.system
        )
        return PromptResponse(system=system, user=prompt.user, phase="verifying", callback=callback)


@router.get("/{run_id}/tasks/{task_id}/attempts/{attempt_num}/logs")
async def get_attempt_logs(
    run_id: str,
    task_id: str,
    attempt_num: int,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> AgentLogsResponse:
    """Get agent output logs for a specific attempt."""
    run = await service.get_run(run_id)

    # Find the task
    task = None
    for step in run.steps:
        for t in step.tasks:
            if t.id == task_id:
                task = t
                break
        if task:
            break

    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Find the attempt
    attempt = None
    for att in task.attempts:
        if att.attempt_num == attempt_num:
            attempt = att
            break

    if attempt is None:
        raise HTTPException(status_code=404, detail=f"Attempt {attempt_num} not found")

    output = attempt.agent_output
    action_log = attempt.action_log
    # Backfill structured logs from raw NDJSON for older attempts that were
    # captured before robust parser coverage for newer event formats.
    if output and _looks_like_ndjson_agent_stream(output):
        should_reparse = action_log is None or len(action_log.entries) <= 2
        if should_reparse:
            parsed = _parse_action_log_from_raw(output, attempt.agent_settings)
            if parsed is not None and (
                action_log is None or len(parsed.entries) > len(action_log.entries)
            ):
                action_log = parsed

    # Serialize structured action log if present
    action_log_schema = None
    if action_log:
        al = action_log
        action_log_schema = ActionLogSchema(
            entries=[
                ActionLogEntrySchema(
                    sequence_num=e.sequence_num,
                    kind=e.kind.value,
                    timestamp=e.timestamp,
                    text=e.text,
                    tool_use=ToolUseDetailSchema(
                        tool_use_id=e.tool_use.tool_use_id,
                        tool_name=e.tool_use.tool_name,
                        arguments=e.tool_use.arguments,
                        summary=e.tool_use.summary,
                    )
                    if e.tool_use
                    else None,
                    tool_result=ToolResultDetailSchema(
                        tool_use_id=e.tool_result.tool_use_id,
                        output=e.tool_result.output,
                        exit_code=e.tool_result.exit_code,
                        success=e.tool_result.success,
                        output_length=e.tool_result.output_length,
                    )
                    if e.tool_result
                    else None,
                    metrics=TurnMetricsSchema(
                        input_tokens=e.metrics.input_tokens,
                        output_tokens=e.metrics.output_tokens,
                        cache_read_tokens=e.metrics.cache_read_tokens,
                        cache_creation_tokens=e.metrics.cache_creation_tokens,
                        cost_usd=e.metrics.cost_usd,
                    )
                    if e.metrics
                    else None,
                    raw_type=e.raw_type,
                )
                for e in al.entries
            ],
            session_id=al.session_id,
            agent_model=al.agent_model,
            tools_available=al.tools_available,
            total_turns=al.total_turns,
            total_cost_usd=al.total_cost_usd,
            total_duration_ms=al.total_duration_ms,
            total_input_tokens=al.total_input_tokens,
            total_output_tokens=al.total_output_tokens,
            total_cache_read_tokens=al.total_cache_read_tokens,
            total_cache_creation_tokens=al.total_cache_creation_tokens,
        )

    return AgentLogsResponse(
        run_id=run_id,
        task_id=task_id,
        attempt_num=attempt_num,
        output=output,
        error=attempt.error,
        line_count=len(output.split("\n")) if output else 0,
        action_log=action_log_schema,
    )


class EscalateRequirementRequest(BaseModel):
    requirement_id: str
    reason: str


@router.post("/{run_id}/tasks/{task_id}/escalate", status_code=200)
async def escalate_requirement(
    run_id: str,
    task_id: str,
    request: EscalateRequirementRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> dict[str, str]:
    """Agent flags a requirement as unfulfillable.

    Sets the requirement status to 'escalated' and pauses the run with
    pause_reason='requirement_escalated'. A human can then modify, skip,
    or resume the run.
    """
    try:
        await service.escalate_requirement(run_id, task_id, request.requirement_id, request.reason)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (TaskNotFoundError, ChecklistItemNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "escalated", "pause_reason": "requirement_escalated"}


@router.post("/{run_id}/tasks/{task_id}/approve", response_model=TransitionResponse)
async def approve_task(
    run_id: str,
    task_id: str,
    request: ApproveTaskRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    user: Annotated[str, Depends(get_current_user)],
) -> TransitionResponse:
    """Human approves task verification."""
    result = await service.approve_task(run_id, task_id, user, request.comment)
    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )


@router.post("/{run_id}/tasks/{task_id}/reject", response_model=TransitionResponse)
async def reject_task(
    run_id: str,
    task_id: str,
    request: RejectTaskRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    user: Annotated[str, Depends(get_current_user)],
) -> TransitionResponse:
    """Human rejects task verification."""
    result = await service.reject_task(run_id, task_id, user, request.reason)
    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )


@router.post("/{run_id}/tasks/{task_id}/force-accept", response_model=TransitionResponse)
async def force_accept_task(
    run_id: str,
    task_id: str,
    request: ForceAcceptTaskRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    executor: Annotated[AgentRunnerExecutor, Depends(get_runner_executor)],
    user: Annotated[str, Depends(get_current_user)],
) -> TransitionResponse:
    """Override verification failure and force-complete a task.

    Works from FAILED, BUILDING, or VERIFYING states. Bypasses grade evaluation.
    Re-spawns the executor if the run was reactivated from FAILED state.
    """
    try:
        result = await service.force_accept_task(run_id, task_id, user, request.comment)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # If the run was reactivated (FAILED -> ACTIVE), re-spawn the executor
    if result.success:
        run = await service.get_run(run_id)
        if (
            run.status == RunStatus.ACTIVE
            and run.agent_runner_type is not None
            and not executor.is_running(run_id)
        ):
            executor.spawn_for_run(run_id, run.agent_runner_type, run.agent_runner_config)

    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )
