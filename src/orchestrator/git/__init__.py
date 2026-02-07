"""Git integration for orchestrator."""

from orchestrator.git.branch_ops import BranchStatus, back_merge, get_branch_status, merge_back
from orchestrator.git.errors import (
    BranchError,
    BranchNotFoundError,
    GitError,
    MergeConflictError,
    WorktreeError,
)
from orchestrator.git.project_init import InitializedProject, init_project
from orchestrator.git.worktree import WorktreeInfo, WorktreeManager

__all__ = [
    "BranchError",
    "BranchNotFoundError",
    "BranchStatus",
    "GitError",
    "InitializedProject",
    "MergeConflictError",
    "WorktreeError",
    "WorktreeInfo",
    "WorktreeManager",
    "back_merge",
    "get_branch_status",
    "init_project",
    "merge_back",
]
