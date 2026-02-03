"""Run API endpoints."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from orchestrator.api.deps import get_routine_dirs, get_workflow_service
from orchestrator.api.schemas.runs import (
    CreateRunRequest,
    RunListResponse,
    RunResponse,
    StepSummary,
    TaskSummary,
)
from orchestrator.config.enums import AgentType, RoutineSource, RunStatus
from orchestrator.routines.discovery import discover_routines
from orchestrator.routines.errors import RoutineNotFoundError
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import Run
from orchestrator.workflow.service import WorkflowService

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _run_to_response(run: Run) -> RunResponse:
    """Convert domain Run to API response."""
    steps = [
        StepSummary(
            id=step.id,
            config_id=step.config_id,
            completed=step.completed,
            tasks=[
                TaskSummary(
                    id=task.id,
                    config_id=task.config_id,
                    status=task.status.value,
                    current_attempt=task.current_attempt,
                    max_attempts=task.max_attempts,
                )
                for task in step.tasks
            ],
        )
        for step in run.steps
    ]

    return RunResponse(
        id=run.id,
        project_id=run.project_id,
        status=run.status.value,
        routine_id=run.routine_id,
        routine_sha=run.routine_sha,
        routine_source=run.routine_source.value if run.routine_source else None,
        agent_type=run.agent_type.value if run.agent_type else None,
        agent_config=run.agent_config,
        worktree_enabled=run.worktree_enabled,
        worktree_path=run.worktree_path,
        config=run.config,
        steps=steps,
        current_step_index=run.current_step_index,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        total_tokens_read=run.total_tokens_read,
        total_tokens_write=run.total_tokens_write,
        total_tokens_cache=run.total_tokens_cache,
        total_duration_ms=run.total_duration_ms,
    )


@router.post("", response_model=RunResponse, status_code=201)
async def create_run(
    request: CreateRunRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    routine_dirs: Annotated[list[tuple[Path, RoutineSource]], Depends(get_routine_dirs)],
) -> RunResponse:
    """Create a new run from a routine."""
    found = discover_routines(routine_dirs)
    routine_config = None
    source = RoutineSource.LOCAL
    for routine in found:
        if routine.config.id == request.routine_id:
            routine_config = routine.config
            source = routine.source
            break

    if routine_config is None:
        raise RoutineNotFoundError(request.routine_id)

    run = create_run_from_routine(
        routine=routine_config,
        project_id=request.project_id,
        config=request.config if request.config else None,
        routine_source=source,
    )

    if request.agent_type is not None:
        run.agent_type = AgentType(request.agent_type)

    if request.agent_config:
        run.agent_config = request.agent_config

    created = await service.create_run(run)
    return _run_to_response(created)


@router.get("", response_model=RunListResponse)
async def list_runs(
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> RunListResponse:
    """List runs with optional filters."""
    if project_id is not None and status is not None:
        runs = await service.list_runs_by_project_and_status(project_id, RunStatus(status))
    elif project_id is not None:
        runs = await service.list_runs_by_project(project_id)
    elif status is not None:
        runs = await service.list_runs_by_status(RunStatus(status))
    else:
        runs = await service.list_runs()

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
) -> RunResponse:
    """Start a run (DRAFT -> ACTIVE)."""
    run = await service.start_run(run_id)
    return _run_to_response(run)


@router.post("/{run_id}/pause", response_model=RunResponse)
async def pause_run(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> RunResponse:
    """Pause a run (ACTIVE -> PAUSED)."""
    run = await service.pause_run(run_id)
    return _run_to_response(run)


@router.post("/{run_id}/resume", response_model=RunResponse)
async def resume_run(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> RunResponse:
    """Resume a run (PAUSED -> ACTIVE)."""
    run = await service.resume_run(run_id)
    return _run_to_response(run)


@router.delete("/{run_id}", status_code=204)
async def delete_run(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> None:
    """Delete a run."""
    await service.delete_run(run_id)
