"""Run API endpoints."""

import asyncio
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api.deps import (
    get_agent_executor,
    get_event_store,
    get_global_config,
    get_run_repository,
    get_routine_dirs,
    get_session,
    get_session_factory,
    get_workflow_service,
)
from orchestrator.envfiles.resolution import resolve_env_specs
from orchestrator.agents.executor import AgentExecutor
from orchestrator.api.schemas.activity import ActivityEvent, ActivityResponse
from orchestrator.api.schemas.runs import (
    AgentCancelledRequest,
    AttemptOutcome,
    BackMergeResponse,
    BackwardTransitionRequest,
    BranchStatusResponse,
    CreateRunRequest,
    GradeSummaryItem,
    GuidanceResponse,
    MergeBackRequest,
    MergeBackResponse,
    ResumeRunRequest,
    RunListResponse,
    RunResponse,
    StepSummary,
    TaskSummary,
    get_agent_display_name,
    get_agent_icon,
)
from orchestrator.api.schemas.steps import (
    HumanApprovalRequest,
    HumanApprovalResponse,
    StepResponse,
)
from orchestrator.config.enums import AgentType, GateType, RoutineSource, RunStatus, TaskStatus
from orchestrator.config.global_config import GlobalConfig
from orchestrator.config.models import RoutineConfig
from orchestrator.db.event_store import EventStore
from orchestrator.db.repositories import RunRepository
from orchestrator.metrics.cost import estimate_cost
from orchestrator.routines.discovery import discover_routines
from orchestrator.routines.errors import RoutineNotFoundError
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.errors import StepNotFoundError
from orchestrator.state.models import HumanApproval, Run
from orchestrator.workflow.service import WorkflowService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _run_to_response(run: Run) -> RunResponse:
    """Convert domain Run to API response."""
    # Parse routine config if available for gate information
    routine_config: RoutineConfig | None = None
    if run.routine_embedded is not None:
        routine_config = RoutineConfig.model_validate(run.routine_embedded)

    steps = [
        StepSummary(
            id=step.id,
            config_id=step.config_id,
            title=step.title,
            completed=step.completed,
            tasks=[
                TaskSummary(
                    id=task.id,
                    config_id=task.config_id,
                    title=task.title,
                    status=task.status.value,
                    current_attempt=task.current_attempt,
                    max_attempts=task.max_attempts,
                    grade_summary=[
                        GradeSummaryItem(
                            grade=item.grade,
                            priority=item.priority.value,
                        )
                        for item in task.checklist
                    ],
                    attempts_summary=[
                        AttemptOutcome(
                            attempt_num=att.attempt_num,
                            outcome=att.outcome,
                        )
                        for att in task.attempts
                    ],
                    pending_action_type=task.pending_action_type,
                    pending_clarification_count=None,  # Will be populated by async route if needed
                )
                for task in step.tasks
            ],
            has_approval_gate=(
                routine_config is not None
                and any(
                    s.id == step.config_id
                    and s.gate is not None
                    and s.gate.type == GateType.HUMAN_APPROVAL
                    for s in routine_config.steps
                )
            ),
            approval_status=(
                "approved"
                if step.human_approval is not None
                else "pending"
                if routine_config is not None
                and any(
                    s.id == step.config_id
                    and s.gate is not None
                    and s.gate.type == GateType.HUMAN_APPROVAL
                    for s in routine_config.steps
                )
                and not step.completed
                else None
            ),
        )
        for step in run.steps
    ]

    # Cost estimation: The Run model doesn't currently track which LLM model
    # was used, so we default to gpt-4o for estimation purposes. This gives
    # users a rough cost estimate based on token usage.
    estimated_cost_usd = None
    cost_disclaimer = None

    if run.total_tokens_read > 0 or run.total_tokens_write > 0 or run.total_tokens_cache > 0:
        cost_estimate = estimate_cost(
            tokens_read=run.total_tokens_read,
            tokens_write=run.total_tokens_write,
            tokens_cache=run.total_tokens_cache,
            model="gpt-4o",
        )
        if cost_estimate:
            estimated_cost_usd = cost_estimate.total_usd
            cost_disclaimer = (
                "Estimate only, based on gpt-4o pricing. "
                "Actual costs may vary depending on model used. " + cost_estimate.disclaimer
            )

    from orchestrator.api.schemas.runs import EnvFileSpecSchema

    # Compute relative worktree path from CWD
    worktree_relative_path: str | None = None
    if run.worktree_path:
        try:
            worktree_relative_path = str(Path(run.worktree_path).relative_to(Path.cwd()))
        except ValueError:
            # worktree_path is not relative to cwd, use as-is
            worktree_relative_path = run.worktree_path

    return RunResponse(
        id=run.id,
        repo_name=run.repo_name,
        status=run.status.value,
        pause_reason=run.pause_reason,
        routine_id=run.routine_id,
        routine_sha=run.routine_sha,
        routine_source=run.routine_source.value if run.routine_source else None,
        routine_embedded=run.routine_embedded,
        routine_path=run.routine_path,
        routine_commit=run.routine_commit,
        agent_type=run.agent_type.value if run.agent_type else None,
        agent_type_display=get_agent_display_name(run.agent_type, run.agent_config),
        agent_icon=get_agent_icon(run.agent_type),
        agent_config=run.agent_config,
        worktree_enabled=run.worktree_enabled,
        worktree_path=run.worktree_path,
        worktree_relative_path=worktree_relative_path,
        source_branch=run.source_branch,
        merge_strategy=run.merge_strategy,
        config=run.config,
        env_file_specs=[
            EnvFileSpecSchema(path=spec.relative_path, promote_on_success=spec.promote_on_success)
            for spec in run.env_file_specs
        ],
        env_source_dir=run.env_source_dir,
        steps=steps,
        current_step_index=run.current_step_index,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        agent_started_at=run.agent_started_at,
        total_tokens_read=run.total_tokens_read,
        total_tokens_write=run.total_tokens_write,
        total_tokens_cache=run.total_tokens_cache,
        total_duration_ms=run.total_duration_ms,
        total_num_actions=run.total_num_actions,
        estimated_cost_usd=estimated_cost_usd,
        cost_disclaimer=cost_disclaimer,
    )


@router.post("", response_model=RunResponse, status_code=201)
async def create_run(
    request: CreateRunRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    routine_dirs: Annotated[list[tuple[Path, RoutineSource]], Depends(get_routine_dirs)],
) -> RunResponse:
    """Create a new run from a routine (by ID or embedded inline)."""
    if request.routine_embedded is not None:
        # Inline/embedded routine: parse and validate the provided dict
        try:
            routine_config = RoutineConfig.model_validate(request.routine_embedded)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=[
                    {"loc": e.get("loc", []), "msg": e.get("msg", ""), "type": e.get("type", "")}
                    for e in exc.errors()
                ],
            ) from exc
        run = create_run_from_routine(
            routine=routine_config,
            repo_name=request.repo_name,
            source_branch=request.branch,
            config=request.config if request.config else None,
            routine_source=RoutineSource.EMBEDDED,
        )
        run.routine_embedded = request.routine_embedded
    else:
        # Lookup routine by ID from discovered routines
        found = discover_routines(routine_dirs)
        routine_config = None
        source = RoutineSource.LOCAL
        for routine in found:
            if routine.config.id == request.routine_id:
                routine_config = routine.config
                source = routine.source
                break

        if routine_config is None:
            raise RoutineNotFoundError(request.routine_id or "")

        run = create_run_from_routine(
            routine=routine_config,
            repo_name=request.repo_name,
            source_branch=request.branch,
            config=request.config if request.config else None,
            routine_source=source,
        )
        # Store routine config for auto-verify and prompt generation
        run.routine_embedded = routine_config.model_dump(mode="json", by_alias=True)

    if request.merge_strategy is not None:
        run.merge_strategy = request.merge_strategy

    if request.agent_type is not None:
        run.agent_type = AgentType(request.agent_type)

    if request.agent_config:
        run.agent_config = request.agent_config

    # Resolve env file specs from routine config and request overrides
    if request.env_files and request.env_files.files is not None:
        request_specs = [f.model_dump() for f in request.env_files.files]
    else:
        request_specs = None

    env_specs = resolve_env_specs(
        routine_specs=routine_config.env_files if routine_config.env_files else None,
        request_specs=request_specs,
    )

    # Store resolved env file specs on the run
    run.env_file_specs = env_specs
    if request.env_files and request.env_files.source_dir:
        run.env_source_dir = request.env_files.source_dir

    created = await service.create_run(run)
    return _run_to_response(created)


@router.get("", response_model=RunListResponse)
async def list_runs(
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    config: Annotated[GlobalConfig, Depends(get_global_config)],
    repo_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    recent_hours: int | None = Query(default=None),
    limit: int | None = Query(default=None, description="Maximum number of runs to return"),
) -> RunListResponse:
    """List runs with optional filters.

    When no filters are specified, returns the most recent runs up to
    dashboard.max_recent_runs from global config (unless overridden by limit parameter).
    """
    if recent_hours is not None:
        runs = await service.list_runs_recent(recent_hours)
    elif repo_name is not None and status is not None:
        runs = await service.list_runs_by_repo_and_status(repo_name, RunStatus(status))
    elif repo_name is not None:
        runs = await service.list_runs_by_repo(repo_name)
    elif status is not None:
        runs = await service.list_runs_by_status(RunStatus(status))
    else:
        # Apply max_recent_runs from config when no other filters are specified
        effective_limit = limit if limit is not None else config.dashboard.max_recent_runs
        runs = await service.list_runs(limit=effective_limit)

    return RunListResponse(runs=[_run_to_response(r) for r in runs])


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> RunResponse:
    """Get a run by ID."""
    run = await service.get_run(run_id)
    return _run_to_response(run)


@router.post("/{run_id}/start", response_model=RunResponse)
async def start_run(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    executor: Annotated[AgentExecutor, Depends(get_agent_executor)],
) -> RunResponse:
    """Start a run (DRAFT -> ACTIVE).

    For managed agents (CLI, OpenHands), this also spawns the agent process
    in the background. For user-managed/external agents, the agent should
    poll the /tasks/{id}/prompt endpoint to get work.
    """
    logger.info(f"API: Starting run {run_id}")
    run = await executor.start_run_with_agent(run_id, service)
    logger.info(
        f"API: Run {run_id} started - status={run.status.value}, "
        f"agent_type={run.agent_type.value if run.agent_type else 'none'}, "
        f"agent_spawned={executor.is_running(run_id)}"
    )
    return _run_to_response(run)


@router.post("/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    executor: Annotated[AgentExecutor, Depends(get_agent_executor)],
) -> RunResponse:
    """Cancel a run (ACTIVE/PAUSED -> FAILED)."""
    # Cancel any running agent first
    await executor.cancel_run(run_id)
    run = await service.cancel_run(run_id)
    return _run_to_response(run)


@router.post("/{run_id}/pause", response_model=RunResponse)
async def pause_run(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    executor: Annotated[AgentExecutor, Depends(get_agent_executor)],
) -> RunResponse:
    """Pause a run (ACTIVE -> PAUSED)."""
    # Cancel any running agent first
    await executor.cancel_run(run_id)
    run = await service.pause_run(run_id)
    return _run_to_response(run)


@router.post("/{run_id}/resume", response_model=RunResponse)
async def resume_run(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    executor: Annotated[AgentExecutor, Depends(get_agent_executor)],
    request: ResumeRunRequest | None = None,
) -> RunResponse:
    """Resume a run (PAUSED -> ACTIVE), optionally changing the agent.

    For managed agents (CLI, OpenHands), this also spawns the agent process
    in the background. For user-managed/external agents, the agent should
    poll the /tasks/{id}/prompt endpoint to get work.
    """
    agent_type = AgentType(request.agent_type) if request and request.agent_type else None
    agent_config = request.agent_config if request and request.agent_config else None
    resume_strategy = request.resume_strategy if request else None

    run = await service.resume_run(
        run_id,
        agent_type=agent_type,
        agent_config=agent_config,
        resume_strategy=resume_strategy,
    )

    # Spawn agent if this is a managed agent type
    if run.agent_type is not None:
        spawned = executor.spawn_for_run(run.id, run.agent_type, run.agent_config)
        if spawned:
            logger.info(f"API: Spawned {run.agent_type.value} agent for resumed run {run_id}")

    return _run_to_response(run)


@router.delete("/{run_id}", status_code=204)
async def delete_run(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> None:
    """Delete a run."""
    # Fetch run to check status
    run = await service.get_run(run_id)

    # Reject deletion if run is ACTIVE or PAUSED
    if run.status in (RunStatus.ACTIVE, RunStatus.PAUSED):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete run with status {run.status.value}. Cancel or complete the run first.",
        )

    await service.delete_run(run_id)


@router.get("/{run_id}/activity", response_model=ActivityResponse)
async def get_activity(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    event_store: Annotated[EventStore, Depends(get_event_store)],
    after: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    event_type: str | None = Query(default=None),
) -> ActivityResponse:
    """Get the activity log for a run.

    Returns a paginated, optionally filtered list of events enriched with
    step/task titles resolved from the current run state.
    """
    # Validate run exists (raises RunNotFoundError → 404)
    run = await service.get_run(run_id)

    # Build lookup maps: task_id → (task_title, step_title)
    task_lookup: dict[str, tuple[str, str]] = {}
    step_lookup: dict[str, str] = {}
    for step in run.steps:
        step_title = step.title or step.config_id
        step_lookup[step.id] = step_title
        for task in step.tasks:
            task_title = task.title or task.config_id
            task_lookup[task.id] = (task_title, step_title)

    # Fetch limit+1 to determine has_more
    rows = await event_store.get_events_paginated(
        run_id,
        after=after,
        limit=limit + 1,
        event_type=event_type,
    )

    has_more = len(rows) > limit
    rows = rows[:limit]

    events: list[ActivityEvent] = []
    for row in rows:
        payload = row["payload"]
        task_id = payload.get("task_id")
        step_id = payload.get("step_id")

        task_title: str | None = None
        step_title: str | None = None

        if task_id and task_id in task_lookup:
            task_title, step_title = task_lookup[task_id]
        elif step_id and step_id in step_lookup:
            step_title = step_lookup[step_id]

        events.append(
            ActivityEvent(
                id=row["id"],
                event_type=row["event_type"],
                timestamp=row["timestamp"],
                payload=payload,
                task_title=task_title,
                step_title=step_title,
            )
        )

    return ActivityResponse(run_id=run_id, events=events, has_more=has_more)


@router.get("/{run_id}/activity/stream")
async def stream_activity(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    since_id: int | None = Query(default=None, description="Resume from this event ID (exclusive)"),
    event_type: str | None = Query(default=None, description="Filter by event type"),
    once: bool = Query(
        default=False, description="Yield all existing events and stop (for testing)"
    ),
) -> StreamingResponse:
    """Stream activity events as Server-Sent Events (SSE).

    Clients can reconnect with since_id to resume from the last received event.
    Events are sent in SSE format:

        data: {"id": 123, "event_type": "task_started", "timestamp": "...", ...}

    Args:
        run_id: The run to stream events for
        since_id: Resume streaming from events after this ID (for reconnection)
        event_type: Optional filter to only stream specific event types
        once: If true, yield all existing events and stop (useful for testing with ASGI transport)
    """
    # Validate run exists BEFORE returning StreamingResponse (raises RunNotFoundError → 404)
    run = await service.get_run(run_id)

    async def event_generator():
        """Generate SSE-formatted events."""
        # Build lookup maps for enrichment
        task_lookup: dict[str, tuple[str, str]] = {}
        step_lookup: dict[str, str] = {}
        for step in run.steps:
            step_title = step.title or step.config_id
            step_lookup[step.id] = step_title
            for task in step.tasks:
                task_title = task.title or task.config_id
                task_lookup[task.id] = (task_title, step_title)

        last_id = since_id
        poll_interval = 0.5  # Poll every 500ms for new events

        try:
            while True:
                # Use a fresh session per poll to avoid holding a long-lived
                # connection that goes stale on server restart/reload.
                async with session_factory() as session:
                    store = EventStore(session)
                    rows = await store.get_events_paginated(
                        run_id,
                        after=last_id,
                        limit=100,
                        event_type=event_type,
                    )

                # Stream each event as SSE (outside the session context)
                if rows:
                    for row in rows:
                        payload = row["payload"]
                        task_id = payload.get("task_id")
                        step_id = payload.get("step_id")

                        task_title: str | None = None
                        step_title: str | None = None

                        if task_id and task_id in task_lookup:
                            task_title, step_title = task_lookup[task_id]
                        elif step_id and step_id in step_lookup:
                            step_title = step_lookup[step_id]

                        event = ActivityEvent(
                            id=row["id"],
                            event_type=row["event_type"],
                            timestamp=row["timestamp"],
                            payload=payload,
                            task_title=task_title,
                            step_title=step_title,
                        )

                        # Format as SSE (note: double newline ends the event)
                        event_json = event.model_dump_json()
                        # StreamingResponse needs bytes, not str
                        yield f"data: {event_json}\n\n".encode("utf-8")

                        last_id = row["id"]

                # If once=true, stop after first poll
                if once:
                    break

                # Wait before polling again
                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            # Client disconnected - clean up gracefully
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("/{run_id}/steps/{step_id}/approve", response_model=StepResponse)
async def approve_step(
    run_id: str,
    step_id: str,
    approval: HumanApprovalRequest,
    repository: Annotated[RunRepository, Depends(get_run_repository)],
    session: Annotated[AsyncSession, Depends(get_session)],
    executor: Annotated[AgentExecutor, Depends(get_agent_executor)],
) -> StepResponse:
    """Human approval for a step gate.

    Records the approval and re-evaluates the step gate. If the gate now passes,
    the run can proceed to the next step. For managed agents, re-spawns the
    agent loop so execution continues.
    """
    # Get the run
    run = await repository.get(run_id)

    # Find the step
    step = None
    for s in run.steps:
        if s.id == step_id:
            step = s
            break

    if step is None:
        raise StepNotFoundError(step_id)

    # Create approval record
    from datetime import datetime, timezone

    human_approval = HumanApproval(
        approved_by=approval.approved_by,
        approved_at=datetime.now(timezone.utc),
        comment=approval.comment,
    )

    # Update step with approval
    step.human_approval = human_approval

    # Save the run and commit
    await repository.save(run)
    await session.commit()

    # Re-spawn agent if run is active and uses a managed agent type
    if (
        run.status == RunStatus.ACTIVE
        and run.agent_type is not None
        and not executor.is_running(run_id)
    ):
        spawned = executor.spawn_for_run(run_id, run.agent_type, run.agent_config)
        if spawned:
            logger.info(
                f"API: Re-spawned {run.agent_type.value} agent after step approval for run {run_id}"
            )

    # Build response
    approval_response = None
    if step.human_approval:
        approval_response = HumanApprovalResponse(
            approved_by=step.human_approval.approved_by,
            approved_at=step.human_approval.approved_at,
            comment=step.human_approval.comment,
        )

    return StepResponse(
        id=step.id,
        config_id=step.config_id,
        title=step.title,
        completed=step.completed,
        human_approval=approval_response,
    )


@router.get("/{run_id}/guidance", response_model=GuidanceResponse)
async def get_guidance(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    repository: Annotated[RunRepository, Depends(get_run_repository)],
    routine_dirs: Annotated[list[tuple[Path, RoutineSource]], Depends(get_routine_dirs)],
) -> GuidanceResponse:
    """Get aggregate guidance for external agents.

    Returns:
    - Current task prompt (if a task is in progress)
    - MCP URL for callbacks
    - Expected actions list
    """
    from orchestrator.workflow.prompts import generate_builder_prompt, generate_verifier_prompt

    run = await service.get_run(run_id)

    # Find the current task (first non-terminal task in current step)
    current_task = None
    if run.current_step_index < len(run.steps):
        step = run.steps[run.current_step_index]
        for task in step.tasks:
            if task.status in (TaskStatus.BUILDING, TaskStatus.VERIFYING):
                current_task = task
                break

    prompt_text = None
    phase = None
    task_id = None

    if current_task is not None:
        task_id = current_task.id
        # Resolve routine config for prompt generation
        routine_config: RoutineConfig | None = None
        if run.routine_embedded is not None:
            routine_config = RoutineConfig.model_validate(run.routine_embedded)
        else:
            if run.routine_id is not None:
                found = discover_routines(routine_dirs)
                for routine in found:
                    if routine.config.id == run.routine_id:
                        routine_config = routine.config
                        break

        if routine_config is not None:
            # Find task config
            # First, find which step contains this task to disambiguate config lookup
            step_config_id: str | None = None
            for step in run.steps:
                for task in step.tasks:
                    if task.id == current_task.id:
                        step_config_id = step.config_id
                        break
                if step_config_id is not None:
                    break

            task_config = None
            step_context: str | None = None
            for step in routine_config.steps:
                if step_config_id is not None and step.id != step_config_id:
                    continue
                for task in step.tasks:
                    if task.id == current_task.config_id:
                        task_config = task
                        step_context = step.step_context
                        break
                if task_config is not None:
                    break

            if task_config is not None:
                if current_task.status == TaskStatus.BUILDING:
                    prompt = generate_builder_prompt(
                        task_config, current_task, run.config, step_context=step_context
                    )
                    phase = "building"
                    prompt_text = f"{prompt.system}\n\n{prompt.user}"
                elif current_task.status == TaskStatus.VERIFYING:
                    prompt = generate_verifier_prompt(
                        task_config, current_task, step_context=step_context
                    )
                    phase = "verifying"
                    prompt_text = f"{prompt.system}\n\n{prompt.user}"

    # Build MCP URL - in production this would be from the request, but for guidance
    # we'll use a placeholder that the client can resolve
    mcp_url = "/mcp/sse"

    # Expected actions based on current state
    expected_actions = []
    if current_task is not None:
        if current_task.status == TaskStatus.BUILDING:
            expected_actions = [
                f"Mark requirements as done: PATCH /api/runs/{run_id}/tasks/{task_id}/checklist/{{req_id}}",
                f"Submit for verification: POST /api/runs/{run_id}/tasks/{task_id}/submit",
            ]
        elif current_task.status == TaskStatus.VERIFYING:
            expected_actions = [
                f"Set grades: PUT /api/runs/{run_id}/tasks/{task_id}/checklist/{{req_id}}/grade",
                f"Complete verification: POST /api/runs/{run_id}/tasks/{task_id}/complete-verification",
            ]
    else:
        expected_actions = ["No active task - run may be complete or waiting for step approval"]

    return GuidanceResponse(
        run_id=run_id,
        task_id=task_id,
        prompt=prompt_text,
        phase=phase,
        mcp_url=mcp_url,
        expected_actions=expected_actions,
    )


@router.post("/{run_id}/agent-started", response_model=RunResponse)
async def agent_started(
    run_id: str,
    repository: Annotated[RunRepository, Depends(get_run_repository)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunResponse:
    """Mark that user has started their external agent.

    Sets the agent_started_at timestamp on the run.
    """
    from datetime import datetime, timezone

    run = await repository.get(run_id)

    # Set agent_started_at timestamp
    run.agent_started_at = datetime.now(timezone.utc)
    run.updated_at = datetime.now(timezone.utc)

    # Save the run (flushes to DB)
    await repository.save(run)

    # Commit to ensure persistence
    await session.commit()

    return _run_to_response(run)


@router.post("/{run_id}/agent-cancelled", response_model=RunResponse)
async def agent_cancelled(
    run_id: str,
    request: AgentCancelledRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> RunResponse:
    """Cancel waiting for external agent.

    Transitions the run to FAILED with a cancellation reason.
    """
    # Cancel the run (this will transition to FAILED)
    run = await service.cancel_run(run_id)

    # Note: The cancellation reason could be stored in a future field like
    # `cancellation_reason` on the Run model if needed for audit trails

    return _run_to_response(run)


@router.post("/{run_id}/transition-back", response_model=RunResponse)
async def transition_back(
    run_id: str,
    request: BackwardTransitionRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> RunResponse:
    """Transition backward to an earlier step.

    Resets tasks in skipped steps (from target to current) to PENDING status.
    """
    run = await service.transition_backward(run_id, request.target_step_index, request.reason)
    return _run_to_response(run)


@router.get("/{run_id}/branch-status", response_model=BranchStatusResponse)
async def get_branch_status_endpoint(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> BranchStatusResponse:
    """Get branch status for a run (ahead/behind counts, merge-ability).

    Requires: run has worktree_path and source_branch set.
    """
    from orchestrator.git.branch_ops import get_branch_status

    run = await service.get_run(run_id)

    if not run.worktree_path or not run.source_branch:
        raise HTTPException(
            status_code=400,
            detail="Run does not have a worktree or source branch configured",
        )

    # Derive the run branch name from the worktree convention
    run_branch = f"orchestrator/run-{run.id}"

    status = get_branch_status(Path(run.worktree_path), run_branch, run.source_branch)

    return BranchStatusResponse(
        behind_count=status.behind_count,
        ahead_count=status.ahead_count,
        can_merge_cleanly=status.can_merge_cleanly,
        has_conflicts=status.has_conflicts,
        source_branch=run.source_branch,
        run_branch=run_branch,
    )


@router.post("/{run_id}/back-merge", response_model=BackMergeResponse)
async def back_merge_endpoint(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> BackMergeResponse:
    """Pull source branch changes into run branch.

    Allowed when run is ACTIVE or PAUSED.
    """
    from orchestrator.git.branch_ops import back_merge

    run = await service.get_run(run_id)

    if run.status not in (RunStatus.ACTIVE, RunStatus.PAUSED):
        raise HTTPException(
            status_code=409,
            detail=f"Back-merge only allowed for ACTIVE or PAUSED runs, got {run.status.value}",
        )

    if not run.worktree_path or not run.source_branch:
        raise HTTPException(
            status_code=400,
            detail="Run does not have a worktree or source branch configured",
        )

    sha = back_merge(Path(run.worktree_path), run.source_branch)

    return BackMergeResponse(
        merge_commit=sha,
        message=f"Merged {run.source_branch} into run branch",
    )


@router.post("/{run_id}/merge-back", response_model=MergeBackResponse)
async def merge_back_endpoint(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    config: Annotated[GlobalConfig, Depends(get_global_config)],
    request: MergeBackRequest | None = None,
) -> MergeBackResponse:
    """Merge run branch back into source branch.

    Allowed when run is COMPLETED.
    """
    from orchestrator.git.branch_ops import merge_back

    run = await service.get_run(run_id)

    if run.status != RunStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Merge-back only allowed for COMPLETED runs, got {run.status.value}",
        )

    if not run.worktree_path or not run.source_branch:
        raise HTTPException(
            status_code=400,
            detail="Run does not have a worktree or source branch configured",
        )

    strategy = (request.strategy if request and request.strategy else None) or run.merge_strategy
    dirty_action = request.dirty_action if request else None
    run_branch = f"orchestrator/run-{run.id}"

    # merge_back operates on the main repo in the repos directory
    repo_path = config.paths.get_repos_path() / run.repo_name
    worktree_path = Path(run.worktree_path) if run.worktree_path else None
    sha = merge_back(
        repo_path,
        run_branch,
        run.source_branch,
        strategy=strategy,
        worktree_path=worktree_path,
        dirty_action=dirty_action,
    )

    return MergeBackResponse(
        merge_commit=sha,
        strategy=strategy,
        message=f"Merged {run_branch} into {run.source_branch} via {strategy}",
    )
