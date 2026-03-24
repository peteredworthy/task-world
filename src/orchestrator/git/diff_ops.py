"""Diff generation functions for the review subsystem."""

import asyncio
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.git.diff_models import CommitInfo, FileStatus, ModifiedFile
from orchestrator.git.errors import GitCommandError


def _run_git_sync(args: list[str], cwd: Path) -> str:
    """Run a git command synchronously and return stdout.

    Raises GitCommandError on non-zero exit.
    """
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise GitCommandError(" ".join(cmd), e.returncode, e.stderr) from e


async def get_branch_diff(worktree_path: Path, base_sha: str, head_sha: str) -> str:
    """Return unified diff text for the full branch range.

    Args:
        worktree_path: Path to the git worktree
        base_sha: Base commit SHA
        head_sha: Head commit SHA

    Returns:
        Unified diff text as a string
    """
    return await asyncio.to_thread(
        _run_git_sync,
        ["diff", f"{base_sha}..{head_sha}"],
        worktree_path,
    )


async def get_commit_diff(worktree_path: Path, commit_sha: str) -> str:
    """Return unified diff text for a single commit.

    Args:
        worktree_path: Path to the git worktree
        commit_sha: The commit SHA to diff

    Returns:
        Unified diff text as a string including commit metadata
    """
    return await asyncio.to_thread(
        _run_git_sync,
        ["show", commit_sha],
        worktree_path,
    )


async def get_task_diff(worktree_path: Path, start_sha: str, end_sha: str) -> str:
    """Return unified diff text for a task's commit range.

    Args:
        worktree_path: Path to the git worktree
        start_sha: Start commit SHA (exclusive)
        end_sha: End commit SHA (inclusive)

    Returns:
        Unified diff text as a string
    """
    return await asyncio.to_thread(
        _run_git_sync,
        ["diff", f"{start_sha}..{end_sha}"],
        worktree_path,
    )


async def get_modified_files(
    worktree_path: Path, base_sha: str, head_sha: str
) -> list[ModifiedFile]:
    """Return list of changed files with stats.

    Args:
        worktree_path: Path to the git worktree
        base_sha: Base commit SHA
        head_sha: Head commit SHA

    Returns:
        List of ModifiedFile objects with path, status, additions, deletions
    """
    name_status_output, numstat_output = await asyncio.gather(
        asyncio.to_thread(
            _run_git_sync,
            ["diff", "--name-status", f"{base_sha}..{head_sha}"],
            worktree_path,
        ),
        asyncio.to_thread(
            _run_git_sync,
            ["diff", "--numstat", f"{base_sha}..{head_sha}"],
            worktree_path,
        ),
    )

    # Parse name-status: "M\tfile.py", "A\tfile.py", "D\tfile.py", "R100\told.py\tnew.py"
    status_map: dict[str, FileStatus] = {}
    for line in name_status_output.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        status_code = parts[0]
        if status_code.startswith("R"):
            # Renamed: use the new path
            path = parts[2] if len(parts) > 2 else parts[1]
            status_map[path] = FileStatus.RENAMED
        elif status_code == "A":
            status_map[parts[1]] = FileStatus.ADDED
        elif status_code == "D":
            status_map[parts[1]] = FileStatus.DELETED
        else:
            status_map[parts[1]] = FileStatus.MODIFIED

    # Parse numstat: "10\t5\tfile.py" (additions deletions path)
    result: list[ModifiedFile] = []
    for line in numstat_output.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        # Binary files show "-" for additions/deletions
        additions = int(parts[0]) if parts[0] != "-" else 0
        deletions = int(parts[1]) if parts[1] != "-" else 0
        path = parts[2]
        status = status_map.get(path, FileStatus.MODIFIED)
        result.append(
            ModifiedFile(
                path=path,
                status=status,
                additions=additions,
                deletions=deletions,
            )
        )

    return result


async def get_commit_log(worktree_path: Path, base_sha: str, head_sha: str) -> list[CommitInfo]:
    """Return commit history from base to head in reverse chronological order.

    Args:
        worktree_path: Path to the git worktree
        base_sha: Base commit SHA (exclusive)
        head_sha: Head commit SHA (inclusive)

    Returns:
        List of CommitInfo objects in reverse chronological order (newest first)
    """
    # Use ASCII unit separator (0x1F) to delimit fields within a commit record
    field_sep = "\x1f"
    format_str = f"%H{field_sep}%h{field_sep}%s{field_sep}%an{field_sep}%at"

    output = await asyncio.to_thread(
        _run_git_sync,
        ["log", f"{base_sha}..{head_sha}", f"--format={format_str}"],
        worktree_path,
    )

    commits: list[CommitInfo] = []
    for line in output.strip().splitlines():
        if not line:
            continue
        parts = line.split(field_sep)
        if len(parts) < 5:
            continue
        sha, short_sha, message, author, timestamp_str = parts[:5]
        timestamp = datetime.fromtimestamp(int(timestamp_str), tz=timezone.utc)
        commits.append(
            CommitInfo(
                sha=sha,
                short_sha=short_sha,
                message=message,
                author=author,
                timestamp=timestamp,
            )
        )

    return commits
