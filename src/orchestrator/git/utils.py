"""Git utility functions."""

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from orchestrator.git.errors import WorktreeCommitError, WorktreeResetError

logger = logging.getLogger(__name__)

GIT_QUICK_TIMEOUT_SECONDS = 30
GIT_ADD_TIMEOUT_SECONDS = 300
GIT_COMMIT_TIMEOUT_SECONDS = 30 * 60


@dataclass(frozen=True)
class WorktreeResetResult:
    worktree_path: str
    target_ref: str | None = None
    branch_name: str | None = None
    head_before: str | None = None
    head_after: str | None = None


@dataclass(frozen=True)
class WorktreeCommitResult:
    worktree_path: str
    commit_message: str
    created_commit: bool
    head_before: str | None = None
    head_after: str | None = None
    commit_sha: str | None = None


def _run_git_reset_command(
    worktree_path: Path, args: list[str]
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            [_git_executable(), *args],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise WorktreeResetError(str(worktree_path), str(exc)) from exc

    if result.returncode != 0:
        command = "git " + " ".join(args)
        detail = result.stderr.strip() or result.stdout.strip() or f"{command} failed"
        raise WorktreeResetError(str(worktree_path), detail)
    return result


def _run_git_commit_command(
    worktree_path: Path, args: list[str]
) -> subprocess.CompletedProcess[str]:
    timeout = _timeout_for_commit_command(args)
    try:
        result = subprocess.run(
            [_git_executable(), *args],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise WorktreeCommitError(str(worktree_path), str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise WorktreeCommitError(
            str(worktree_path),
            _format_commit_timeout_error(args, timeout),
        ) from exc

    if result.returncode != 0:
        command = "git " + " ".join(args)
        detail = result.stderr.strip() or result.stdout.strip() or f"{command} failed"
        raise WorktreeCommitError(str(worktree_path), detail)
    return result


def _timeout_for_commit_command(args: list[str]) -> int:
    """Return a timeout for git commands used by auto-commit.

    `git commit` runs hooks in this repository, and those hooks may run the full
    validation suite. Keep status checks fast, but give hook-driven commits
    enough time to finish.
    """
    command = args[0] if args else ""
    if command == "commit":
        return GIT_COMMIT_TIMEOUT_SECONDS
    if command == "add":
        return GIT_ADD_TIMEOUT_SECONDS
    return GIT_QUICK_TIMEOUT_SECONDS


def _git_executable() -> str:
    git = shutil.which("git")
    if git is None:
        return "git"
    resolved = Path(git).resolve()
    if resolved.name == "git-wrapper.sh":
        system_git = shutil.which("git", path="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")
        if system_git is not None:
            return system_git
    return git


def _format_commit_timeout_error(args: list[str], timeout: int) -> str:
    command = "git " + " ".join(args)
    if args and args[0] == "commit":
        return (
            f"{command} timed out after {timeout} seconds. The auto-commit step "
            "runs git hooks, which may include the full test suite; increase "
            "GIT_COMMIT_TIMEOUT_SECONDS if this repository needs more time."
        )
    return f"{command} timed out after {timeout} seconds"


def _require_worktree_path(worktree_path: str | Path) -> Path:
    path = Path(worktree_path)
    if not path.exists() or not path.is_dir():
        raise WorktreeResetError(str(path), "worktree path does not exist")
    return path


def reset_worktree_changes(worktree_path: str | Path) -> WorktreeResetResult:
    """Discard uncommitted tracked and untracked files in a worktree.

    The operation is idempotent: running it again on an already-clean worktree
    leaves the worktree unchanged.
    """
    path = _require_worktree_path(worktree_path)
    head_before = get_head_commit(path)
    _run_git_reset_command(path, ["reset", "--hard", "HEAD"])
    _run_git_reset_command(path, ["clean", "-fd"])
    return WorktreeResetResult(
        worktree_path=str(path),
        head_before=head_before,
        head_after=get_head_commit(path),
    )


def reset_worktree_to_ref(
    worktree_path: str | Path,
    *,
    branch_name: str,
    target_ref: str,
) -> WorktreeResetResult:
    """Move branch_name to target_ref and discard uncommitted work.

    The operation is idempotent for the same branch/ref pair.
    """
    path = _require_worktree_path(worktree_path)
    head_before = get_head_commit(path)
    _run_git_reset_command(path, ["reset", "--hard", "HEAD"])
    _run_git_reset_command(path, ["clean", "-fd"])
    _run_git_reset_command(path, ["checkout", "-f", "-B", branch_name, target_ref])
    _run_git_reset_command(path, ["reset", "--hard", target_ref])
    _run_git_reset_command(path, ["clean", "-fd"])
    return WorktreeResetResult(
        worktree_path=str(path),
        target_ref=target_ref,
        branch_name=branch_name,
        head_before=head_before,
        head_after=get_head_commit(path),
    )


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
        return commit_uncommitted_changes_or_raise(path, message).created_commit
    except WorktreeCommitError as e:
        logger.warning(str(e))
        return False


def commit_uncommitted_changes_or_raise(
    path: Path, message: str = "Auto-commit uncommitted builder changes"
) -> WorktreeCommitResult:
    """Stage and commit uncommitted work, raising on git failures."""
    if not path.exists() or not path.is_dir():
        raise WorktreeCommitError(str(path), "worktree path does not exist")

    head_before = get_head_commit(path)
    status = _run_git_commit_command(path, ["status", "--porcelain"])
    if not status.stdout.strip():
        return WorktreeCommitResult(
            worktree_path=str(path),
            commit_message=message,
            created_commit=False,
            head_before=head_before,
            head_after=head_before,
            commit_sha=None,
        )

    logger.info(f"Found uncommitted changes in {path}, auto-committing")
    _run_git_commit_command(path, ["add", "-A"])
    try:
        _run_git_commit_command(path, ["commit", "-m", message])
    except WorktreeCommitError as exc:
        # Formatting hooks (e.g. ruff-format) may rewrite files and fail the
        # first commit attempt; the files are already fixed, so re-stage and
        # retry once.
        if "files were modified by this hook" not in str(exc):
            raise
        logger.info(f"Commit hooks modified files in {path}, retrying commit once")
        _run_git_commit_command(path, ["add", "-A"])
        _run_git_commit_command(path, ["commit", "-m", message])
    head_after = get_head_commit(path)
    logger.info(f"Auto-committed uncommitted changes in {path}")
    return WorktreeCommitResult(
        worktree_path=str(path),
        commit_message=message,
        created_commit=True,
        head_before=head_before,
        head_after=head_after,
        commit_sha=head_after,
    )
