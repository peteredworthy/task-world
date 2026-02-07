"""Git versioning for routine files."""

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RoutineVersion:
    """Git version information for a routine file.

    Attributes:
        sha: Git commit SHA of the last commit that touched this file
        dirty: True if the file has uncommitted changes
        path: Absolute path to the routine file
    """

    sha: str
    dirty: bool
    path: Path


def get_routine_version(routine_path: Path) -> RoutineVersion:
    """Get git version information for a routine file.

    Args:
        routine_path: Path to the routine file

    Returns:
        RoutineVersion with SHA, dirty flag, and path

    Raises:
        ValueError: If routine is not in a git repository or has no history
    """
    repo_root = find_git_root(routine_path)
    if repo_root is None:
        raise ValueError(f"Routine {routine_path} is not in a git repository")

    # Get SHA of last commit touching this file
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", str(routine_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    sha = result.stdout.strip()

    if not sha:
        raise ValueError(f"Routine {routine_path} has no git history")

    # Check if file is dirty
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", str(routine_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    dirty = len(result.stdout.strip()) > 0

    return RoutineVersion(sha=sha, dirty=dirty, path=routine_path)


def find_git_root(path: Path) -> Path | None:
    """Find the git repository root containing the given path.

    Walks up the directory tree from the given path until it finds a .git
    directory or reaches the filesystem root.

    Args:
        path: Starting path (file or directory)

    Returns:
        Path to the git repository root, or None if not in a git repo
    """
    current = path.resolve()

    # If it's a file, start from its parent directory
    if current.is_file():
        current = current.parent

    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent

    return None
