"""Git operations: branch, conflict, and prune operations."""

from orchestrator.git.ops.branch_ops import (
    BackMergeResult,
    BranchStatus,
    ParentChildMergeResult,
    RevertBackMergeResult,
    back_merge,
    get_branch_status,
    merge_child_into_parent,
    merge_back,
    revert_back_merge,
)
from orchestrator.git.ops.conflict_ops import (
    BlockResolution,
    ConflictBlock,
    get_conflict_blocks,
    get_conflict_files,
    parse_conflict_blocks,
    resolve_conflict,
)
from orchestrator.git.ops.prune_ops import (
    FileSelectionEntry,
    Hunk,
    PruneStats,
    apply_prune,
    compute_selection_preview,
    preview_prune,
    prune_hunks,
    prune_lines,
    revert_file,
)

__all__ = [
    "BackMergeResult",
    "BlockResolution",
    "BranchStatus",
    "ConflictBlock",
    "FileSelectionEntry",
    "Hunk",
    "ParentChildMergeResult",
    "PruneStats",
    "RevertBackMergeResult",
    "apply_prune",
    "back_merge",
    "compute_selection_preview",
    "get_branch_status",
    "get_conflict_blocks",
    "get_conflict_files",
    "merge_child_into_parent",
    "merge_back",
    "parse_conflict_blocks",
    "preview_prune",
    "prune_hunks",
    "prune_lines",
    "resolve_conflict",
    "revert_back_merge",
    "revert_file",
]
