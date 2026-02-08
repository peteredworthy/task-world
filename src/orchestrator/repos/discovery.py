"""Repository discovery functions."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from orchestrator.repos.errors import RepoNotFoundError
from orchestrator.repos.models import BranchInfo, RepoInfo


def list_repos(repos_dir: Path) -> list[RepoInfo]:
    """List all git repositories in the repos directory.

    Scans repos_dir for subdirectories that are git repositories.
    Returns repos sorted by name.
    """
    if not repos_dir.exists():
        return []

    repos: list[RepoInfo] = []
    for entry in repos_dir.iterdir():
        if entry.is_dir() and (entry / ".git").exists():
            try:
                default_branch = _get_default_branch(entry)
                repos.append(
                    RepoInfo(
                        name=entry.name,
                        path=entry,
                        default_branch=default_branch,
                    )
                )
            except subprocess.CalledProcessError:
                # Skip repos with git errors
                continue

    return sorted(repos, key=lambda r: r.name)


def get_repo(repos_dir: Path, name: str) -> RepoInfo:
    """Get information about a specific repository.

    Args:
        repos_dir: The repos directory
        name: Name of the repository (directory name)

    Returns:
        RepoInfo for the repository

    Raises:
        RepoNotFoundError: If the repository doesn't exist
    """
    repo_path = repos_dir / name
    if not repo_path.exists() or not (repo_path / ".git").exists():
        raise RepoNotFoundError(name)

    default_branch = _get_default_branch(repo_path)
    return RepoInfo(
        name=name,
        path=repo_path,
        default_branch=default_branch,
    )


def list_branches(
    repo_path: Path,
    pattern: str = "",
    include_remote: bool = True,
    local_only: bool = False,
    limit: int = 0,
) -> list[BranchInfo]:
    """List branches in a repository.

    Args:
        repo_path: Path to the git repository
        pattern: Optional glob pattern to filter branches (e.g., "feat*", "*/auth")
        include_remote: Whether to include remote tracking branches (deprecated, use local_only)
        local_only: If True, only list local branches (takes precedence over include_remote)
        limit: Maximum number of branches to return (0 for no limit)

    Returns:
        List of BranchInfo, sorted by name
    """
    # local_only takes precedence over include_remote
    if local_only:
        include_remote = False

    branches: list[BranchInfo] = []

    # Get local branches
    result = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short) %(objectname:short)", "refs/heads/"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            name, commit = parts[0], parts[1]
            branches.append(BranchInfo(name=name, is_remote=False, commit=commit))

    # Get remote branches
    if include_remote:
        result = subprocess.run(
            [
                "git",
                "for-each-ref",
                "--format=%(refname:short) %(objectname:short)",
                "refs/remotes/",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                name, commit = parts[0], parts[1]
                # Skip HEAD reference
                if name.endswith("/HEAD"):
                    continue
                branches.append(BranchInfo(name=name, is_remote=True, commit=commit))

    # Apply pattern filter
    if pattern:
        branches = [b for b in branches if fnmatch.fnmatch(b.name, pattern)]

    # Sort by name
    branches = sorted(branches, key=lambda b: b.name)

    # Apply limit
    if limit > 0:
        branches = branches[:limit]

    return branches


def branch_count(repo_path: Path, pattern: str = "", include_remote: bool = True) -> int:
    """Count branches matching a pattern.

    More efficient than list_branches when only count is needed.

    Args:
        repo_path: Path to the git repository
        pattern: Optional glob pattern to filter branches
        include_remote: Whether to include remote tracking branches

    Returns:
        Number of matching branches
    """
    # For simplicity, we'll use list_branches
    # Could be optimized with git command if performance is critical
    return len(list_branches(repo_path, pattern, include_remote))


def match_branches(branches: list[str], pattern: str) -> list[str]:
    """Match branch names using glob patterns.

    Examples:
        "feat*" matches "feature/auth", "feat-123"
        "*/auth" matches "feature/auth", "bugfix/auth"
        "release-*" matches "release-1.0", "release-2.0"

    Args:
        branches: List of branch names
        pattern: Glob pattern to match

    Returns:
        List of matching branch names
    """
    if not pattern:
        return branches
    return [b for b in branches if fnmatch.fnmatch(b, pattern)]


def _get_default_branch(repo_path: Path) -> str:
    """Get the default branch name for a repository.

    Tries to determine from symbolic-ref HEAD, falls back to "main".
    """
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        # Fallback if HEAD is detached or other error
        return "main"
