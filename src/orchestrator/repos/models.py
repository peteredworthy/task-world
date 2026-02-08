"""Models for repo discovery."""

from pathlib import Path

from pydantic import BaseModel


class RepoInfo(BaseModel):
    """Information about a discovered git repository."""

    name: str  # Directory name
    path: Path  # Full path to the repo
    default_branch: str  # HEAD branch (e.g., "main", "master")

    model_config = {"arbitrary_types_allowed": True}


class BranchInfo(BaseModel):
    """Information about a branch in a repository."""

    name: str  # Branch name (e.g., "main", "feature/auth")
    is_remote: bool  # True if this is a remote tracking branch
    commit: str  # HEAD commit SHA for this branch
