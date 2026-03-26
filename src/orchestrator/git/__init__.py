"""Git integration for orchestrator."""

from orchestrator.git.diff import (
    Cache,
    CachedDiffOps,
    CommitInfo,
    DiffOps,
    DiffResult,
    DiffScope,
    FileStatus,
    GitDiffOps,
    LRUCache,
    ModifiedFile,
    get_branch_diff,
    get_commit_diff,
    get_commit_log,
    get_modified_files,
    get_task_diff,
)
from orchestrator.git.errors import (
    BranchError,
    BranchNotFoundError,
    GitCommandError,
    GitError,
    MergeConflictError,
    WorktreeError,
)
from orchestrator.git.ops import (
    BackMergeResult,
    BlockResolution,
    BranchStatus,
    FileSelectionEntry,
    Hunk,
    PruneStats,
    RevertBackMergeResult,
    apply_prune,
    back_merge,
    compute_selection_preview,
    get_branch_status,
    get_conflict_blocks,
    get_conflict_files,
    merge_back,
    parse_conflict_blocks,
    preview_prune,
    prune_hunks,
    prune_lines,
    resolve_conflict,
    revert_back_merge,
    revert_file,
)
from orchestrator.git.ops.conflict_ops import (
    _apply_resolutions,  # pyright: ignore[reportPrivateUsage]
)
from orchestrator.git.ops.prune_ops import (
    _build_hunk_reverse_patch,  # pyright: ignore[reportPrivateUsage]
    _build_line_reverse_patch,  # pyright: ignore[reportPrivateUsage]
    _count_selected_hunk_lines,  # pyright: ignore[reportPrivateUsage]
    _count_selected_range_lines,  # pyright: ignore[reportPrivateUsage]
    _file_exists_at_ref,  # pyright: ignore[reportPrivateUsage]
    _parse_diff_sections,  # pyright: ignore[reportPrivateUsage]
    _parse_file_diff_hunks,  # pyright: ignore[reportPrivateUsage]
    _parse_hunk_header,  # pyright: ignore[reportPrivateUsage]
)
from orchestrator.git.project_init import InitializedProject, init_project
from orchestrator.git.repos import (
    BranchInfo,
    RepoInfo,
    RepoNotFoundError,
    branch_count,
    get_repo,
    list_branches,
    list_repos,
)
from orchestrator.git.testing import TestRunResult, TestRunner, TestSummary
from orchestrator.git.worktree import WorktreeInfo, WorktreeManager

__all__ = [
    "_apply_resolutions",
    "_build_hunk_reverse_patch",
    "_build_line_reverse_patch",
    "_count_selected_hunk_lines",
    "_count_selected_range_lines",
    "_file_exists_at_ref",
    "_parse_diff_sections",
    "_parse_file_diff_hunks",
    "_parse_hunk_header",
    "BackMergeResult",
    "BlockResolution",
    "CachedDiffOps",
    "DiffOps",
    "BranchError",
    "BranchInfo",
    "BranchNotFoundError",
    "BranchStatus",
    "Cache",
    "CommitInfo",
    "DiffResult",
    "DiffScope",
    "FileStatus",
    "GitCommandError",
    "GitDiffOps",
    "GitError",
    "InitializedProject",
    "LRUCache",
    "MergeConflictError",
    "ModifiedFile",
    "RepoInfo",
    "RepoNotFoundError",
    "RevertBackMergeResult",
    "TestRunResult",
    "TestRunner",
    "TestSummary",
    "WorktreeError",
    "WorktreeInfo",
    "WorktreeManager",
    "FileSelectionEntry",
    "Hunk",
    "PruneStats",
    "apply_prune",
    "back_merge",
    "branch_count",
    "compute_selection_preview",
    "get_branch_diff",
    "get_branch_status",
    "get_commit_diff",
    "get_commit_log",
    "get_conflict_blocks",
    "get_conflict_files",
    "get_modified_files",
    "get_repo",
    "get_task_diff",
    "init_project",
    "list_branches",
    "list_repos",
    "merge_back",
    "parse_conflict_blocks",
    "preview_prune",
    "prune_hunks",
    "prune_lines",
    "resolve_conflict",
    "revert_back_merge",
    "revert_file",
]
