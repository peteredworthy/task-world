"""Repository discovery module."""

from orchestrator.repos.discovery import (
    branch_count,
    get_repo,
    list_branches,
    list_repos,
    match_branches,
)
from orchestrator.repos.errors import BranchNotFoundError, RepoNotFoundError
from orchestrator.repos.models import BranchInfo, RepoInfo

__all__ = [
    "BranchInfo",
    "BranchNotFoundError",
    "RepoInfo",
    "RepoNotFoundError",
    "branch_count",
    "get_repo",
    "list_branches",
    "list_repos",
    "match_branches",
]
