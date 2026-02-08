"""Git utility functions."""

import subprocess
from pathlib import Path


def get_head_commit(path: Path) -> str | None:
    """Get the HEAD commit SHA for a path.

    Args:
        path: Path to a git repository or worktree

    Returns:
        The HEAD commit SHA as a string, or None if not a git repo or error
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
