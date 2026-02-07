"""Project API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from orchestrator.api.deps import get_workflow_service
from orchestrator.workflow.service import WorkflowService

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectListResponse(BaseModel):
    project_ids: list[str]


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> ProjectListResponse:
    """List unique project IDs from existing runs."""
    project_ids = await service.list_project_ids()
    return ProjectListResponse(project_ids=project_ids)
