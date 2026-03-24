"""Git operations: branch, conflict, and prune operations."""

from orchestrator.git.ops.branch_ops import (
    BackMergeResult,
    BranchStatus,
    RevertBackMergeResult,
    back_merge,
    get_branch_status,
    merge_back,
    revert_back_merge,
)
from orchestrator.git.ops.conflict_ops import (
    BlockResolution,
    get_conflict_blocks,
    get_conflict_files,
    resolve_conflict,
)

__all__ = [
    "BackMergeResult",
    "BlockResolution",
    "BranchStatus",
    "RevertBackMergeResult",
    "back_merge",
    "get_branch_status",
    "get_conflict_blocks",
    "get_conflict_files",
    "merge_back",
    "resolve_conflict",
    "revert_back_merge",
]
