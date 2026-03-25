"""Git diff operations and models."""

from orchestrator.git.diff.cached_diff_ops import CachedDiffOps, DiffOps, GitDiffOps
from orchestrator.git.diff.diff_ops import (
    get_branch_diff,
    get_commit_diff,
    get_commit_log,
    get_modified_files,
    get_task_diff,
)
from orchestrator.git.diff.lru_cache import Cache, LRUCache
from orchestrator.git.diff.models import (
    CommitInfo,
    DiffResult,
    DiffScope,
    FileStatus,
    ModifiedFile,
)

__all__ = [
    "Cache",
    "CachedDiffOps",
    "CommitInfo",
    "DiffOps",
    "DiffResult",
    "DiffScope",
    "FileStatus",
    "GitDiffOps",
    "LRUCache",
    "ModifiedFile",
    "get_branch_diff",
    "get_commit_diff",
    "get_commit_log",
    "get_modified_files",
    "get_task_diff",
]
