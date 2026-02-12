"""Branch operations: status, back-merge, merge-back."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from orchestrator.git.errors import BranchNotFoundError, GitCommandError, MergeConflictError


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
    if not _branch_exists(repo_path, run_branch):
        raise BranchNotFoundError(run_branch)
    if not _branch_exists(repo_path, source_branch):
        raise BranchNotFoundError(source_branch)

    # Get ahead/behind counts using rev-list --left-right --count
    result = _run_git(
        ["rev-list", "--left-right", "--count", f"{run_branch}...{source_branch}"],
        cwd=repo_path,
    )
    parts = result.stdout.strip().split("\t")
    ahead_count = int(parts[0])
    behind_count = int(parts[1])

    # Check if merge would be clean using merge-tree (git 2.38+)
    can_merge_cleanly = True
    has_conflicts = False

    if behind_count > 0:
        # merge-tree --write-tree returns exit 0 for clean, exit 1 for conflict
        # On conflict, it outputs "CONFLICT" lines in stderr/stdout
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
        elif "CONFLICT" in result.stdout:
            # Some git versions output CONFLICT in stdout even with exit 0
            can_merge_cleanly = False
            has_conflicts = True

    return BranchStatus(
        behind_count=behind_count,
        ahead_count=ahead_count,
        can_merge_cleanly=can_merge_cleanly,
        has_conflicts=has_conflicts,
    )


def back_merge(repo_path: Path, source_branch: str) -> str:
    """Merge source branch into the current branch (in worktree).

    This is run inside the worktree directory to pull updates from
    the source branch into the run branch.

    Args:
        repo_path: Path to the worktree directory
        source_branch: The source branch to merge from

    Returns:
        The merge commit SHA

    Raises:
        BranchNotFoundError: If source branch doesn't exist
        MergeConflictError: If merge has conflicts
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
        # Abort the merge
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        raise MergeConflictError(source_branch, current_branch, conflicting)

    # Return the merge commit SHA
    result = _run_git(["rev-parse", "HEAD"], cwd=repo_path)
    return result.stdout.strip()


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


def merge_back(
    main_repo_path: Path,
    run_branch: str,
    source_branch: str,
    strategy: str = "squash",
    worktree_path: Path | None = None,
) -> str:
    """Merge run branch back into source branch.

    This is run in the main repo directory.

    Args:
        main_repo_path: Path to the main git repository
        run_branch: The run's branch to merge from
        source_branch: The target branch to merge into
        strategy: "squash" or "merge"
        worktree_path: If provided, sync the branch ref to the worktree HEAD first

    Returns:
        The resulting commit SHA

    Raises:
        BranchNotFoundError: If either branch doesn't exist
        MergeConflictError: If merge has conflicts
    """
    if not _branch_exists(main_repo_path, run_branch):
        raise BranchNotFoundError(run_branch)
    if not _branch_exists(main_repo_path, source_branch):
        raise BranchNotFoundError(source_branch)

    # Sync branch ref to worktree HEAD (worktrees may operate detached)
    if worktree_path and worktree_path.exists():
        sync_branch_to_worktree(main_repo_path, run_branch, worktree_path)

    # Checkout the source branch
    _run_git(["checkout", source_branch], cwd=main_repo_path)

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
        raise MergeConflictError(run_branch, source_branch, conflicting)

    # Return the commit SHA
    result = _run_git(["rev-parse", "HEAD"], cwd=main_repo_path)
    return result.stdout.strip()
