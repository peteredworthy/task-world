"""Git utility functions."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


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


def commit_uncommitted_changes(
    path: Path, message: str = "Auto-commit uncommitted builder changes"
) -> bool:
    """Stage and commit any uncommitted changes (tracked or untracked) in a worktree.

    Some CLI agents (e.g. codex) may create/modify files without committing.
    This ensures those changes are captured in a commit before the verifier
    checks out the end_commit, which would otherwise destroy uncommitted work.

    Args:
        path: Path to a git repository or worktree
        message: Commit message to use

    Returns:
        True if a commit was created, False if there was nothing to commit
    """
    try:
        # Check for any changes (staged, unstaged, or untracked)
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )
        if not status.stdout.strip():
            return False

        logger.info(f"Found uncommitted changes in {path}, auto-committing")

        # Stage everything
        subprocess.run(
            ["git", "add", "-A"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )

        # Commit
        subprocess.run(
            ["git", "commit", "-m", message, "--no-verify"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )

        logger.info(f"Auto-committed uncommitted changes in {path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed to auto-commit in {path}: {e.stderr}")
        return False
