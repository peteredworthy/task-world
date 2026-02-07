"""Task API endpoints."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from orchestrator.api.deps import get_current_user, get_routine_dirs, get_workflow_service
from orchestrator.api.schemas.tasks import (
    AgentLogsResponse,
    ApproveTaskRequest,
    AttemptSchema,
    CallbackInstructions,
    ChecklistItemSchema,
    GradeSnapshotItemSchema,
    PromptResponse,
    RejectTaskRequest,
    SetGradeRequest,
    TaskDetailResponse,
    TransitionResponse,
    UpdateChecklistRequest,
)
from orchestrator.config.enums import ChecklistStatus, RoutineSource, TaskStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.routines.discovery import discover_routines
from orchestrator.routines.errors import RoutineNotFoundError
from orchestrator.state.errors import TaskNotFoundError
from orchestrator.workflow.errors import InvalidTransitionError
from orchestrator.workflow.prompts import generate_builder_prompt, generate_verifier_prompt
from orchestrator.workflow.service import WorkflowService

router = APIRouter(prefix="/api/runs", tags=["tasks"])


@router.get("/{run_id}/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    run_id: str,
    task_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> TaskDetailResponse:
    """Get task detail with checklist and attempts."""
    task = await service.get_task(run_id, task_id)
    return TaskDetailResponse(
        id=task.id,
        config_id=task.config_id,
        title=task.title,
        status=task.status.value,
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
                agent_type=att.agent_type.value if att.agent_type else None,
                agent_model=att.agent_model,
                agent_settings=att.agent_settings,
                error=att.error,
                has_output=bool(att.agent_output),
            )
            for att in task.attempts
        ],
        current_attempt=task.current_attempt,
        max_attempts=task.max_attempts,
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
) -> TransitionResponse:
    """Submit task for verification."""
    result = await service.submit_for_verification(run_id, task_id)
    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )


@router.post(
    "/{run_id}/tasks/{task_id}/complete-verification",
    response_model=TransitionResponse,
)
async def complete_verification(
    run_id: str,
    task_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> TransitionResponse:
    """Complete verification phase."""
    result = await service.complete_verification(run_id, task_id)
    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )


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
    request: Request, run_id: str, task_id: str
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
- POST {base_url}/api/runs/{run_id}/tasks/{task_id}/complete-verification → Complete verification phase"""

    mcp_instructions = f"""## Orchestrator MCP Server
Connect to: {base_url}/mcp/sse
Run ID: {run_id}, Task ID: {task_id}

Available MCP tools:
- orchestrator_get_requirements(run_id, task_id) → Get checklist items
- orchestrator_update_checklist(run_id, task_id, req_id, status, note?) → Mark requirement done/blocked
- orchestrator_submit(run_id, task_id) → Submit task for verification"""

    return CallbackInstructions(
        run_id=run_id,
        task_id=task_id,
        api_base_url=base_url,
        rest_instructions=rest_instructions,
        mcp_instructions=mcp_instructions,
    )


@router.get("/{run_id}/tasks/{task_id}/prompt", response_model=PromptResponse)
async def get_task_prompt(
    request: Request,
    run_id: str,
    task_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    routine_dirs: Annotated[list[tuple[Path, RoutineSource]], Depends(get_routine_dirs)],
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
    task_config = None
    step_context: str | None = None
    for step in routine_config.steps:
        for task in step.tasks:
            if task.id == task_state.config_id:
                task_config = task
                step_context = step.step_context
                break
        if task_config is not None:
            break
    if task_config is None:
        raise TaskNotFoundError(run_id, task_id)

    callback = _build_callback_instructions(request, run_id, task_id)

    if task_state.status == TaskStatus.BUILDING:
        prompt = generate_builder_prompt(
            task_config, task_state, run.config, step_context=step_context
        )
        return PromptResponse(
            system=prompt.system, user=prompt.user, phase="building", callback=callback
        )
    else:
        # TaskStatus.VERIFYING
        prompt = generate_verifier_prompt(task_config, task_state, step_context=step_context)
        return PromptResponse(
            system=prompt.system, user=prompt.user, phase="verifying", callback=callback
        )


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
    return AgentLogsResponse(
        run_id=run_id,
        task_id=task_id,
        attempt_num=attempt_num,
        output=output,
        error=attempt.error,
        line_count=len(output.split("\n")) if output else 0,
    )


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
