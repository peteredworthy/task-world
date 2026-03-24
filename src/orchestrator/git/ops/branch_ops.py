"""Branch operations: status, back-merge, merge-back."""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.git.errors import (
    BranchNotFoundError,
    DirtyWorkingTreeError,
    GitCommandError,
    MergeConflictError,
)


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the result.

    Raises GitCommandError on non-zero exit.
    """
    cmd = ["git"] + args
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e


def _branch_exists(repo_path: Path, branch: str) -> bool:
    """Check if a branch exists."""
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _get_conflict_files(repo_path: Path) -> list[str]:
    """Get list of files with merge conflicts."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return [f for f in result.stdout.strip().split("\n") if f]
    except subprocess.CalledProcessError:
        return []


@dataclass
class BranchStatus:
    """Status of a run branch relative to its source branch."""

    behind_count: int  # commits on source not in run branch
    ahead_count: int  # commits on run branch not in source
    can_merge_cleanly: bool
    has_conflicts: bool
    predicted_conflict_count: int = 0  # number of files predicted to conflict


@dataclass
class BackMergeResult:
    """Result of a back_merge operation when abort_on_conflict=False."""

    status: str  # "clean" | "conflicts"
    merge_commit_sha: str | None = None
    conflict_files: list[str] = field(default_factory=list[str])
    conflict_count: int = 0


@dataclass
class RevertBackMergeResult:
    """Result of a revert_back_merge operation."""

    reverted_commit: str
    new_head: str


def get_branch_status(repo_path: Path, run_branch: str, source_branch: str) -> BranchStatus:
    """Get the status of a run branch relative to its source branch.

    Args:
        repo_path: Path to the git repository (main repo or worktree)
        run_branch: The run's branch name
        source_branch: The source branch to compare against

    Returns:
        BranchStatus with ahead/behind counts and merge-ability info

    Raises:
        BranchNotFoundError: If either branch doesn't exist
    """
    # Try rev-list directly; it fails if either branch is missing.
    # Only fall back to per-branch checks on failure to produce a precise error.
    try:
        result = _run_git(
            ["rev-list", "--left-right", "--count", f"{run_branch}...{source_branch}"],
            cwd=repo_path,
        )
    except GitCommandError:
        if not _branch_exists(repo_path, run_branch):
            raise BranchNotFoundError(run_branch)
        raise BranchNotFoundError(source_branch)
    parts = result.stdout.strip().split("\t")
    ahead_count = int(parts[0])
    behind_count = int(parts[1])

    # Check if merge would be clean using merge-tree (git 2.38+)
    can_merge_cleanly = True
    has_conflicts = False
    predicted_conflict_count = 0

    if behind_count > 0:
        # merge-tree --write-tree returns exit 0 for clean, exit 1 for conflict
        # On conflict, it outputs "CONFLICT" lines in stdout
        result = subprocess.run(
            ["git", "merge-tree", "--write-tree", run_branch, source_branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Non-zero exit = conflicts
            can_merge_cleanly = False
            has_conflicts = True
            # Count CONFLICT lines to get predicted conflict file count
            conflict_lines = [
                line for line in result.stdout.splitlines() if line.startswith("CONFLICT")
            ]
            predicted_conflict_count = len(conflict_lines)
        elif "CONFLICT" in result.stdout:
            # Some git versions output CONFLICT in stdout even with exit 0
            can_merge_cleanly = False
            has_conflicts = True
            conflict_lines = [
                line for line in result.stdout.splitlines() if line.startswith("CONFLICT")
            ]
            predicted_conflict_count = len(conflict_lines)

    return BranchStatus(
        behind_count=behind_count,
        ahead_count=ahead_count,
        can_merge_cleanly=can_merge_cleanly,
        has_conflicts=has_conflicts,
        predicted_conflict_count=predicted_conflict_count,
    )


def back_merge(
    repo_path: Path,
    source_branch: str,
    abort_on_conflict: bool = True,
) -> str | BackMergeResult:
    """Merge source branch into the current branch (in worktree).

    This is run inside the worktree directory to pull updates from
    the source branch into the run branch.

    Args:
        repo_path: Path to the worktree directory
        source_branch: The source branch to merge from
        abort_on_conflict: If True (default), abort the merge and raise
            MergeConflictError on conflict (backward-compatible behavior).
            If False, leave the merge in-progress state and return a
            BackMergeResult with status="conflicts" and the conflict file list.

    Returns:
        When abort_on_conflict=True: the merge commit SHA (str).
        When abort_on_conflict=False: a BackMergeResult with status "clean"
            or "conflicts".

    Raises:
        BranchNotFoundError: If source branch doesn't exist
        MergeConflictError: If merge has conflicts and abort_on_conflict=True
    """
    if not _branch_exists(repo_path, source_branch):
        raise BranchNotFoundError(source_branch)

    # Get current branch name for error messages
    current_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    current_branch = current_result.stdout.strip()

    try:
        _run_git(["merge", source_branch, "--no-edit"], cwd=repo_path)
    except GitCommandError:
        # Check for conflicts
        conflicting = _get_conflict_files(repo_path)
        if abort_on_conflict:
            # Abort the merge and raise (backward-compatible behavior)
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            raise MergeConflictError(source_branch, current_branch, conflicting)
        # Leave merge in-progress; return conflict details
        return BackMergeResult(
            status="conflicts",
            merge_commit_sha=None,
            conflict_files=conflicting,
            conflict_count=len(conflicting),
        )

    # Clean merge — return the merge commit SHA
    sha = _run_git(["rev-parse", "HEAD"], cwd=repo_path).stdout.strip()
    if abort_on_conflict:
        # Original return type for backward compatibility
        return sha
    return BackMergeResult(
        status="clean",
        merge_commit_sha=sha,
        conflict_files=[],
        conflict_count=0,
    )


def revert_back_merge(repo_path: Path, merge_sha: str) -> RevertBackMergeResult:
    """Revert the last back merge commit using git revert.

    Args:
        repo_path: Path to the worktree directory
        merge_sha: SHA of the merge commit to revert

    Returns:
        RevertBackMergeResult with the SHA of the new revert commit and
        the new HEAD SHA.

    Raises:
        GitCommandError: If the git revert operation fails
    """
    # -m 1 selects the first parent (the run branch before the back merge)
    # as the mainline, effectively undoing the merge.
    _run_git(["revert", "--no-edit", "-m", "1", merge_sha], cwd=repo_path)
    new_head = _run_git(["rev-parse", "HEAD"], cwd=repo_path).stdout.strip()
    return RevertBackMergeResult(reverted_commit=merge_sha, new_head=new_head)


def sync_branch_to_worktree(repo_path: Path, branch: str, worktree_path: Path) -> None:
    """Update a branch ref to match the worktree HEAD.

    Worktrees may operate with a detached HEAD, causing the named branch
    to fall behind. This syncs the branch to the worktree's actual HEAD
    so that merge operations use the correct commit.
    """
    wt_head = _run_git(["rev-parse", "HEAD"], cwd=worktree_path).stdout.strip()
    branch_sha = _run_git(["rev-parse", branch], cwd=repo_path).stdout.strip()
    if wt_head != branch_sha:
        _run_git(["branch", "-f", branch, wt_head], cwd=repo_path)


def _get_dirty_files(repo_path: Path) -> list[str]:
    """Get list of dirty (uncommitted) files in the working tree."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        # Each line starts with a 2-char status code + space + filename
        return [line[3:] for line in result.stdout.strip().split("\n") if line.strip()]
    except subprocess.CalledProcessError:
        return []


def merge_back(
    main_repo_path: Path,
    run_branch: str,
    source_branch: str,
    strategy: str = "squash",
    worktree_path: Path | None = None,
    dirty_action: str | None = None,
) -> str:
    """Merge run branch back into source branch.

    This is run in the main repo directory.

    Args:
        main_repo_path: Path to the main git repository
        run_branch: The run's branch to merge from
        source_branch: The target branch to merge into
        strategy: "squash" or "merge"
        worktree_path: If provided, sync the branch ref to the worktree HEAD first
        dirty_action: How to handle dirty working tree. None = raise error,
            "stash" = stash changes, "commit" = auto-commit WIP.

    Returns:
        The resulting commit SHA

    Raises:
        BranchNotFoundError: If either branch doesn't exist
        MergeConflictError: If merge has conflicts
        DirtyWorkingTreeError: If working tree is dirty and dirty_action is None
    """
    if not _branch_exists(main_repo_path, run_branch):
        raise BranchNotFoundError(run_branch)
    if not _branch_exists(main_repo_path, source_branch):
        raise BranchNotFoundError(source_branch)

    # Sync branch ref to worktree HEAD (worktrees may operate detached)
    if worktree_path and worktree_path.exists():
        sync_branch_to_worktree(main_repo_path, run_branch, worktree_path)

    # Check for dirty working tree before checkout
    dirty_files = _get_dirty_files(main_repo_path)
    stashed = False
    if dirty_files:
        if dirty_action is None:
            # Detect current branch for the error
            current = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=main_repo_path,
                capture_output=True,
                text=True,
            )
            current_branch = current.stdout.strip() if current.returncode == 0 else "unknown"
            raise DirtyWorkingTreeError(current_branch, dirty_files)
        elif dirty_action == "stash":
            _run_git(["stash", "push", "-m", "merge-back auto-stash"], cwd=main_repo_path)
            stashed = True
        elif dirty_action == "commit":
            _run_git(["add", "-A"], cwd=main_repo_path)
            _run_git(
                ["commit", "-m", "WIP: auto-commit before merge-back"],
                cwd=main_repo_path,
            )

    # Checkout the source branch
    try:
        _run_git(["checkout", source_branch], cwd=main_repo_path)
    except GitCommandError:
        if stashed:
            _run_git(["stash", "pop"], cwd=main_repo_path)
        raise

    try:
        if strategy == "squash":
            _run_git(["merge", "--squash", run_branch], cwd=main_repo_path)
            # Squash merge requires an explicit commit
            _run_git(
                ["commit", "-m", f"Squash merge from {run_branch}"],
                cwd=main_repo_path,
            )
        else:
            _run_git(["merge", "--no-ff", run_branch, "--no-edit"], cwd=main_repo_path)
    except GitCommandError:
        # Check for conflicts
        conflicting = _get_conflict_files(main_repo_path)
        # Abort the merge
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=main_repo_path,
            capture_output=True,
            text=True,
        )
        if stashed:
            _run_git(["stash", "pop"], cwd=main_repo_path)
        raise MergeConflictError(run_branch, source_branch, conflicting)

    # Pop stash after successful merge
    if stashed:
        _run_git(["stash", "pop"], cwd=main_repo_path)

    # Return the commit SHA
    result = _run_git(["rev-parse", "HEAD"], cwd=main_repo_path)
    return result.stdout.strip()
