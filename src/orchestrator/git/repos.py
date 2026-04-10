"""Repository discovery functions and models (consolidated from repos/ module)."""

from __future__ import annotations

import fnmatch
import subprocess
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


class RepoNotFoundError(Exception):
    """Raised when a requested repository is not found."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Repository not found: {name}")


class BranchNotFoundError(Exception):
    """Raised when a requested branch is not found."""

    def __init__(self, repo_name: str, branch_name: str) -> None:
        self.repo_name = repo_name
        self.branch_name = branch_name
        super().__init__(f"Branch '{branch_name}' not found in repository '{repo_name}'")


def list_repos(repos_dir: Path) -> list[RepoInfo]:
    """List all git repositories in the repos directory."""
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
                continue

    return sorted(repos, key=lambda r: r.name)


def get_repo(repos_dir: Path, name: str) -> RepoInfo:
    """Get information about a specific repository."""
    repo_path = repos_dir / name
    if not repo_path.exists() or not (repo_path / ".git").exists():
        raise RepoNotFoundError(name)

    default_branch = _get_default_branch(repo_path)
    return RepoInfo(name=name, path=repo_path, default_branch=default_branch)


def list_branches(
    repo_path: Path,
    pattern: str = "",
    local_only: bool = False,
    limit: int = 0,
) -> list[BranchInfo]:
    """List branches in a repository."""
    branches: list[BranchInfo] = []

    result = subprocess.run(
        [
            "git",
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname:short) %(objectname:short)",
            "refs/heads/",
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
            branches.append(BranchInfo(name=parts[0], is_remote=False, commit=parts[1]))

    if not local_only:
        result = subprocess.run(
            [
                "git",
                "for-each-ref",
                "--sort=-committerdate",
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
                if name.endswith("/HEAD"):
                    continue
                branches.append(BranchInfo(name=name, is_remote=True, commit=commit))

    if pattern:
        branches = [b for b in branches if fnmatch.fnmatch(b.name, pattern)]

    if limit > 0:
        branches = branches[:limit]

    return branches


def branch_count(repo_path: Path, pattern: str = "", local_only: bool = False) -> int:
    """Count branches matching a pattern."""
    return len(list_branches(repo_path, pattern, local_only))


def match_branches(branches: list[str], pattern: str) -> list[str]:
    """Match branch names using glob patterns."""
    if not pattern:
        return branches
    return [b for b in branches if fnmatch.fnmatch(b, pattern)]


def _get_default_branch(repo_path: Path) -> str:
    """Get the default branch name for a repository."""
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
        return "main"
