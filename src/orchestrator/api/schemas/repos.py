"""API schemas for repos endpoints."""

from typing import Any

from pydantic import model_validator

from orchestrator.api.schemas.base import ApiModel


class RepoResponse(ApiModel):
    """Response schema for a repository."""

    name: str
    path: str
    default_branch: str


class ReposListResponse(ApiModel):
    """Response schema for listing repositories."""

    repos: list[RepoResponse]


class BranchResponse(ApiModel):
    """Response schema for a branch."""

    name: str
    is_remote: bool
    commit: str


class BranchesListResponse(ApiModel):
    """Response schema for listing branches."""

    branches: list[BranchResponse]
    total: int
    truncated: bool


class BranchCountResponse(ApiModel):
    """Response schema for branch count."""

    count: int
    pattern: str


class ProjectRoutineResponse(ApiModel):
    """Response schema for a project routine."""

    id: str
    name: str
    description: str | None
    source: str  # "PROJECT"
    path: str  # Relative path within repo
    commit: str  # Commit SHA where routine was read
    has_scaffolding: bool
    config: dict[str, Any]  # Full routine config


class ProjectRoutinesListResponse(ApiModel):
    """Response schema for listing project routines."""

    routines: list[ProjectRoutineResponse]
    branch: str
    commit: str


class RepoStatsResponse(ApiModel):
    """Response schema for repository statistics."""

    run_count: int


class AddRepoRequest(ApiModel):
    """Request schema for adding a repository."""

    url: str | None = None  # git clone URL (https/ssh)
    path: str | None = None  # filesystem path to existing git repo

    @model_validator(mode="after")
    def check_url_or_path(self) -> "AddRepoRequest":
        if not self.url and not self.path:
            raise ValueError("Either url or path must be provided")
        if self.url and self.path:
            raise ValueError("Provide either url or path, not both")
        return self
