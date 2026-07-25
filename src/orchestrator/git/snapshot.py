"""Git-native worktree snapshots."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from orchestrator.git.errors import GitCommandError, WorktreeError

SNAPSHOT_REF_PREFIX = "refs/orchestrator/snapshots"

SNAPSHOT_REF_LIST_FORMAT = "--format=%(refname) %(objectname) %(tree)"

# Seam for running one git command, so callers (and tests) can supply their own
# runner instead of reaching into the module. Signature mirrors ``_run_git``.
GitRunner = Callable[[Path, list[str], dict[str, str]], "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class SnapshotRef:
    """One entry of the snapshot ref listing."""

    ref: str
    commit_sha: str
    tree_sha: str


def parse_snapshot_refs(output: str) -> list[SnapshotRef]:
    """Parse ``for-each-ref`` output into ref/commit/tree triples.

    Pure. ``tree_sha`` is empty when the ref does not point at a commit (or the
    ``%(tree)`` atom produced nothing), which the caller resolves separately.
    Git refs cannot contain spaces, so splitting on space is unambiguous.
    """
    refs: list[SnapshotRef] = []
    for line in output.splitlines():
        fields = line.split(" ")
        if len(fields) < 2 or not fields[0] or not fields[1]:
            continue
        refs.append(
            SnapshotRef(
                ref=fields[0],
                commit_sha=fields[1],
                tree_sha=fields[2] if len(fields) > 2 else "",
            )
        )
    return refs


def match_snapshot_by_tree(
    refs: Iterable[SnapshotRef],
    tree_sha: str,
) -> tuple[SnapshotRef | None, list[SnapshotRef]]:
    """Find the snapshot ref whose tree equals ``tree_sha``.

    Pure. Returns the match (if the listing alone settles it) plus the refs
    whose tree the listing did not report, which are the only ones a caller
    ever needs to resolve individually.
    """
    unresolved: list[SnapshotRef] = []
    for entry in refs:
        if not entry.tree_sha:
            unresolved.append(entry)
        elif entry.tree_sha == tree_sha:
            return entry, []
    return None, unresolved


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
    run_git: GitRunner | None = None,
) -> SnapshotResult:
    """Capture the current worktree in a snapshot ref without touching HEAD or the index.

    ``run_git`` injects the git runner; it defaults to running git directly.
    """
    git = run_git or _run_git
    path = _require_worktree_path(worktree_path)
    env = _git_env()

    with tempfile.TemporaryDirectory(prefix="orchestrator-snapshot-index-") as tmpdir:
        index_path = Path(tmpdir) / "index"
        indexed_env = {**env, "GIT_INDEX_FILE": str(index_path)}
        git(path, ["add", "-A"], indexed_env)
        force_paths = _safe_pathspecs(force_include_paths or [])
        excluded_paths = _safe_pathspecs(exclude_paths or [])
        for batch in _pathspec_batches(force_paths):
            git(path, ["add", "-f", "--", *batch], indexed_env)
        for batch in _pathspec_batches(excluded_paths):
            git(
                path,
                [
                    "rm",
                    "--cached",
                    "-r",
                    "--ignore-unmatch",
                    "--",
                    *batch,
                ],
                indexed_env,
            )
        tree_sha = git(path, ["write-tree"], indexed_env).stdout.strip()

    existing = _find_snapshot_by_tree(path, tree_sha, env=env, run_git=git)
    if existing is not None:
        snapshot_id, commit_sha, ref = existing
        return SnapshotResult(
            id=snapshot_id,
            tree_sha=tree_sha,
            commit_sha=commit_sha,
            ref=ref,
        )

    commit_sha = git(path, ["commit-tree", tree_sha, "-m", message], env).stdout.strip()
    snapshot_id = uuid.uuid4().hex
    ref = f"{SNAPSHOT_REF_PREFIX}/{snapshot_id}"
    git(path, ["update-ref", ref, commit_sha], env)
    return SnapshotResult(id=snapshot_id, tree_sha=tree_sha, commit_sha=commit_sha, ref=ref)


def restore(worktree_path: str | Path, snapshot_id: str) -> None:
    """Restore a snapshot into the worktree without moving HEAD or the index."""
    path = _require_worktree_path(worktree_path)
    ref = f"{SNAPSHOT_REF_PREFIX}/{_validate_snapshot_id(snapshot_id)}"
    env = _git_env()
    commit = _run_git(path, ["rev-parse", "--verify", ref], env).stdout.strip()

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


def delete_snapshot_ref(worktree_path: str | Path, snapshot_id: str) -> bool:
    """Delete a snapshot ref if it exists, leaving objects and worktree untouched."""
    path = _require_worktree_path(worktree_path)
    ref = f"{SNAPSHOT_REF_PREFIX}/{_validate_snapshot_id(snapshot_id)}"
    env = _git_env()
    exists = subprocess.run(
        [_git_executable(), "rev-parse", "--verify", "--quiet", ref],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=False,
    )
    if exists.returncode != 0:
        return False
    _run_git(path, ["update-ref", "-d", ref], env)
    return True


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


def _run_git(cwd: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
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
    cwd: Path,
    tree_sha: str,
    *,
    env: dict[str, str],
    run_git: GitRunner,
) -> tuple[str, str, str] | None:
    # The %(tree) atom reports every snapshot commit's tree from the single
    # for-each-ref call. Resolving trees with a `git show` per ref instead made
    # each capture spawn one process per existing snapshot, so a run's captures
    # cost O(snapshots^2) processes overall.
    listing = run_git(
        cwd,
        ["for-each-ref", SNAPSHOT_REF_LIST_FORMAT, SNAPSHOT_REF_PREFIX],
        env,
    ).stdout
    match, unresolved = match_snapshot_by_tree(parse_snapshot_refs(listing), tree_sha)
    if match is None:
        # Only refs the listing could not settle (not commits) cost extra work.
        for entry in unresolved:
            resolved = run_git(cwd, ["show", "-s", "--format=%T", entry.commit_sha], env)
            if resolved.stdout.strip() == tree_sha:
                match = entry
                break
    if match is None:
        return None
    return (
        match.ref.removeprefix(f"{SNAPSHOT_REF_PREFIX}/"),
        match.commit_sha,
        match.ref,
    )


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


# Keep each ``git`` argv well under the OS ARG_MAX (1 MB on macOS) so a worktree
# with very many force-included/excluded pathspecs cannot overflow execve. The
# budget is conservative: it leaves ample headroom for the fixed git prefix and
# the inherited environment.
_MAX_PATHSPEC_BYTES_PER_BATCH = 96 * 1024
_MAX_PATHSPECS_PER_BATCH = 2000


def _pathspec_batches(pathspecs: list[str]) -> list[list[str]]:
    """Split pathspecs into argv-safe batches (by byte budget and count)."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_bytes = 0
    for spec in pathspecs:
        spec_bytes = len(spec.encode("utf-8")) + 1  # +1 for the argv separator
        if current and (
            current_bytes + spec_bytes > _MAX_PATHSPEC_BYTES_PER_BATCH
            or len(current) >= _MAX_PATHSPECS_PER_BATCH
        ):
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(spec)
        current_bytes += spec_bytes
    if current:
        batches.append(current)
    return batches
