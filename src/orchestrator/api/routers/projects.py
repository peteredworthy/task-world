"""Project API endpoints (deprecated - use /api/repos instead)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from orchestrator.api.deps import get_workflow_service
from orchestrator.workflow.service import WorkflowService

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectListResponse(BaseModel):
    """Deprecated: Use /api/repos instead."""

    project_ids: list[str]


@router.get("", response_model=ProjectListResponse, deprecated=True)
async def list_projects(
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> ProjectListResponse:
    """List unique repository names from existing runs.

    Deprecated: Use /api/repos instead for listing available repositories.
    """
    repo_names = await service.list_repo_names()
    return ProjectListResponse(project_ids=repo_names)
