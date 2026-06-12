"""Git-native worktree snapshots."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from orchestrator.git.errors import GitCommandError, WorktreeError

SNAPSHOT_REF_PREFIX = "refs/orchestrator/snapshots"


@dataclass(frozen=True)
class SnapshotResult:
    id: str
    tree_sha: str
    commit_sha: str
    ref: str


def snapshot(
    worktree_path: str | Path,
    message: str,
    *,
    force_include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
) -> SnapshotResult:
    """Capture the current worktree in a snapshot ref without touching HEAD or the index."""
    path = _require_worktree_path(worktree_path)
    env = _git_env()

    with tempfile.TemporaryDirectory(prefix="orchestrator-snapshot-index-") as tmpdir:
        index_path = Path(tmpdir) / "index"
        indexed_env = {**env, "GIT_INDEX_FILE": str(index_path)}
        _run_git(path, ["add", "-A"], env=indexed_env)
        force_paths = _safe_pathspecs(force_include_paths or [])
        excluded_paths = _safe_pathspecs(exclude_paths or [])
        if force_paths:
            _run_git(
                path,
                ["add", "-f", "--", *force_paths],
                env=indexed_env,
            )
        if excluded_paths:
            _run_git(
                path,
                [
                    "rm",
                    "--cached",
                    "-r",
                    "--ignore-unmatch",
                    "--",
                    *excluded_paths,
                ],
                env=indexed_env,
            )
        tree_sha = _run_git(path, ["write-tree"], env=indexed_env).stdout.strip()

    existing = _find_snapshot_by_tree(path, tree_sha, env=env)
    if existing is not None:
        snapshot_id, commit_sha, ref = existing
        return SnapshotResult(
            id=snapshot_id,
            tree_sha=tree_sha,
            commit_sha=commit_sha,
            ref=ref,
        )

    commit_sha = _run_git(path, ["commit-tree", tree_sha, "-m", message], env=env).stdout.strip()
    snapshot_id = uuid.uuid4().hex
    ref = f"{SNAPSHOT_REF_PREFIX}/{snapshot_id}"
    _run_git(path, ["update-ref", ref, commit_sha], env=env)
    return SnapshotResult(id=snapshot_id, tree_sha=tree_sha, commit_sha=commit_sha, ref=ref)


def restore(worktree_path: str | Path, snapshot_id: str) -> None:
    """Restore a snapshot into the worktree without moving HEAD or the index."""
    path = _require_worktree_path(worktree_path)
    ref = f"{SNAPSHOT_REF_PREFIX}/{_validate_snapshot_id(snapshot_id)}"
    env = _git_env()
    commit = _run_git(path, ["rev-parse", "--verify", ref], env=env).stdout.strip()

    archive = _open_git_archive(path, commit, env=env)
    try:
        tar = subprocess.run(
            ["tar", "-x", "-C", str(path)],
            stdin=archive.stdout,
            capture_output=True,
            text=False,
            timeout=30,
            env=env,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        archive.kill()
        raise WorktreeError(f"Failed to restore snapshot {snapshot_id}: {exc}") from exc
    finally:
        if archive.stdout is not None:
            archive.stdout.close()

    archive_stderr = archive.communicate(timeout=30)[1]
    if archive.returncode != 0:
        raise GitCommandError(
            f"git archive {commit}",
            archive.returncode,
            archive_stderr.decode("utf-8", errors="replace"),
        )
    if tar.returncode != 0:
        raise WorktreeError(
            f"Failed to restore snapshot {snapshot_id}: "
            f"{tar.stderr.decode('utf-8', errors='replace')}"
        )


def _require_worktree_path(worktree_path: str | Path) -> Path:
    path = Path(worktree_path)
    if not path.exists() or not path.is_dir():
        raise WorktreeError(f"Worktree path does not exist: {path}")
    return path


def _git_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"}
    }
    env["PRE_COMMIT_ALLOW_NO_CONFIG"] = "1"
    return env


def _run_git(
    cwd: Path, args: list[str], *, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            [_git_executable(), *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise WorktreeError(f"Failed to run git {' '.join(args)}: {exc}") from exc
    if result.returncode != 0:
        raise GitCommandError("git " + " ".join(args), result.returncode, result.stderr)
    return result


def _find_snapshot_by_tree(
    cwd: Path, tree_sha: str, *, env: dict[str, str]
) -> tuple[str, str, str] | None:
    refs = _run_git(
        cwd,
        ["for-each-ref", "--format=%(refname) %(objectname)", SNAPSHOT_REF_PREFIX],
        env=env,
    ).stdout.splitlines()
    for line in refs:
        ref, commit_sha = line.split(" ", maxsplit=1)
        existing_tree = _run_git(cwd, ["show", "-s", "--format=%T", commit_sha], env=env)
        if existing_tree.stdout.strip() == tree_sha:
            return ref.removeprefix(f"{SNAPSHOT_REF_PREFIX}/"), commit_sha, ref
    return None


def _open_git_archive(cwd: Path, commit: str, *, env: dict[str, str]) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(
            [_git_executable(), "archive", "--format=tar", commit],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as exc:
        raise WorktreeError(f"Failed to run git archive: {exc}") from exc


def _git_executable() -> str:
    git = shutil.which("git")
    if git is None:
        raise WorktreeError("git executable not found")
    resolved = Path(git).resolve()
    if resolved.name == "git-wrapper.sh":
        system_git = shutil.which("git", path="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")
        if system_git is not None:
            return system_git
    return git


def _validate_snapshot_id(snapshot_id: str) -> str:
    if (
        not snapshot_id
        or snapshot_id.startswith(".")
        or "/" in snapshot_id
        or "\\" in snapshot_id
        or ".." in snapshot_id
    ):
        raise WorktreeError(f"Invalid snapshot id: {snapshot_id}")
    return snapshot_id


def _safe_pathspecs(paths: list[str]) -> list[str]:
    safe: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/").strip()
        if (
            not normalized
            or normalized.startswith("/")
            or normalized.startswith("../")
            or "/../" in normalized
            or normalized == ".."
        ):
            continue
        safe.append(f":(literal){normalized}")
    return safe
