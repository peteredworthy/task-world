"""Task API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from orchestrator.api.deps import get_workflow_service
from orchestrator.api.schemas.tasks import (
    AttemptSchema,
    ChecklistItemSchema,
    SetGradeRequest,
    TaskDetailResponse,
    TransitionResponse,
    UpdateChecklistRequest,
)
from orchestrator.config.enums import ChecklistStatus
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
                outcome=att.outcome,
                metrics=att.metrics.model_dump(mode="json"),
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
