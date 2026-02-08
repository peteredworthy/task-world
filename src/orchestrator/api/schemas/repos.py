"""API schemas for repos endpoints."""

from typing import Any

from pydantic import BaseModel


class RepoResponse(BaseModel):
    """Response schema for a repository."""

    name: str
    path: str
    default_branch: str


class ReposListResponse(BaseModel):
    """Response schema for listing repositories."""

    repos: list[RepoResponse]


class BranchResponse(BaseModel):
    """Response schema for a branch."""

    name: str
    is_remote: bool
    commit: str


class BranchesListResponse(BaseModel):
    """Response schema for listing branches."""

    branches: list[BranchResponse]
    total: int
    truncated: bool


class BranchCountResponse(BaseModel):
    """Response schema for branch count."""

    count: int
    pattern: str


class ProjectRoutineResponse(BaseModel):
    """Response schema for a project routine."""

    id: str
    name: str
    description: str | None
    source: str  # "PROJECT"
    path: str  # Relative path within repo
    commit: str  # Commit SHA where routine was read
    has_scaffolding: bool
    config: dict[str, Any]  # Full routine config


class ProjectRoutinesListResponse(BaseModel):
    """Response schema for listing project routines."""

    routines: list[ProjectRoutineResponse]
    branch: str
    commit: str
