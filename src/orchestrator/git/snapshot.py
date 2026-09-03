"""Git-native worktree snapshots."""

from __future__ import annotations

import os
import hashlib
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from orchestrator.git.errors import GitCommandError, SnapshotPathLimitError, WorktreeError

SNAPSHOT_REF_PREFIX = "refs/orchestrator/snapshots"
DEFAULT_SNAPSHOT_UNTRACKED_ITEMS = 10_000
DEFAULT_SNAPSHOT_UNTRACKED_BYTES = 256 * 1024

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


@dataclass(frozen=True)
class PreparedSnapshot:
    """An unreachable snapshot commit awaiting durable ownership publication."""

    id: str
    tree_sha: str
    commit_sha: str
    ref: str


@dataclass(frozen=True)
class SnapshotPathMetadata:
    """One path's immutable representation in a prepared snapshot tree."""

    file_type: str
    fingerprint: str


def prepare_snapshot(
    worktree_path: str | Path,
    message: str,
    *,
    snapshot_id: str,
    force_include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    exclude_untracked_cache_paths: list[str] | None = None,
    max_untracked_items: int = DEFAULT_SNAPSHOT_UNTRACKED_ITEMS,
    max_untracked_bytes: int = DEFAULT_SNAPSHOT_UNTRACKED_BYTES,
) -> PreparedSnapshot:
    """Create a tree/commit but never publish a named ref.

    The caller must first persist ownership, then call ``publish_snapshot``.
    An interruption here leaves only an unreachable object, which Git GC may
    safely collect; it can never become a semantic orphan ref.
    """
    path = _require_worktree_path(worktree_path)
    snapshot_id = _validate_snapshot_id(snapshot_id)
    env = _git_env()
    cache_roots = _canonical_cache_roots(exclude_untracked_cache_paths or [])
    cache_excludes = [f":(top,exclude,literal){root}" for root in cache_roots]
    safe_force_paths = _force_paths_outside_cache_roots(force_include_paths or [], cache_roots)
    with tempfile.TemporaryDirectory(prefix="orchestrator-snapshot-index-") as tmpdir:
        index_path = Path(tmpdir) / "index"
        indexed_env = {**env, "GIT_INDEX_FILE": str(index_path)}
        # Build the temporary index without `add -A`: that command walks an
        # unignored cache before any later exclusion can remove it. Tracked
        # updates are index-only; Git itself lists normal untracked files with
        # literal cache exclusions before we add their bounded argv batches.
        if _has_head(path, indexed_env):
            _run_git(path, ["read-tree", "HEAD"], indexed_env)
            _run_git(path, ["add", "-u"], indexed_env)
        untracked_paths = _collect_untracked_paths(
            path,
            ["ls-files", "--others", "--exclude-standard", "-z", "--", ":(top)**", *cache_excludes],
            indexed_env,
            max_items=max_untracked_items,
            max_bytes=max_untracked_bytes,
        )
        for batch in _pathspec_batches([_literal_pathspec(item) for item in untracked_paths]):
            _run_git(path, ["add", "--", *batch], indexed_env)
        for batch in _pathspec_batches(_safe_pathspecs(safe_force_paths)):
            _run_git(path, ["add", "-f", "--", *batch], indexed_env)
        for batch in _pathspec_batches(_safe_pathspecs(exclude_paths or [])):
            _run_git(path, ["rm", "--cached", "-r", "--ignore-unmatch", "--", *batch], indexed_env)
        tree_sha = _run_git(path, ["write-tree"], indexed_env).stdout.strip()
    commit_sha = _run_git(path, ["commit-tree", tree_sha, "-m", message], env).stdout.strip()
    return PreparedSnapshot(
        id=snapshot_id,
        tree_sha=tree_sha,
        commit_sha=commit_sha,
        ref=f"{SNAPSHOT_REF_PREFIX}/{snapshot_id}",
    )


def publish_snapshot(worktree_path: str | Path, prepared: PreparedSnapshot) -> SnapshotResult:
    """CAS-create the exact owned ref, accepting only identical redelivery."""
    path = _require_worktree_path(worktree_path)
    env = _git_env()
    existing = subprocess.run(
        [_git_executable(), "rev-parse", "--verify", "--quiet", prepared.ref],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=False,
    )
    if existing.returncode == 0:
        if existing.stdout.strip() != prepared.commit_sha:
            raise WorktreeError("Snapshot ref already exists with a different commit")
    else:
        _run_git(path, ["update-ref", prepared.ref, prepared.commit_sha, ""], env)
    return SnapshotResult(**prepared.__dict__)


def snapshot_path_metadata(
    worktree_path: str | Path,
    prepared: PreparedSnapshot,
    relative_path: str,
) -> SnapshotPathMetadata | None:
    """Read a literal path from an un-published prepared tree, never the live worktree."""
    path = _require_worktree_path(worktree_path)
    relative_path = _validate_restore_path(relative_path)
    env = _git_env()
    entry = _run_git(
        path,
        ["ls-tree", "-z", prepared.commit_sha, "--", _literal_pathspec(relative_path)],
        env,
    ).stdout.rstrip("\0")
    if not entry:
        return None
    header, _, tree_path = entry.partition("\t")
    fields = header.split(" ")
    if len(fields) != 3 or tree_path != relative_path:
        return None
    mode, object_type, object_id = fields
    if object_type == "blob":
        # Git's text subprocess API cannot safely transport arbitrary blob bytes.
        # Use a binary command only for the immutable object content.
        try:
            result = subprocess.run(
                [_git_executable(), "cat-file", "blob", object_id],
                cwd=path,
                capture_output=True,
                timeout=30,
                env=env,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise WorktreeError(f"Failed to inspect snapshot blob: {exc}") from exc
        if result.returncode != 0:
            raise WorktreeError("Failed to inspect snapshot blob")
        return SnapshotPathMetadata(
            file_type="symlink" if mode == "120000" else "file",
            fingerprint=f"sha256:{hashlib.sha256(result.stdout).hexdigest()}",
        )
    if object_type == "tree":
        return SnapshotPathMetadata(
            file_type="directory",
            fingerprint=f"sha256:{hashlib.sha256(entry.encode()).hexdigest()}",
        )
    return None


def ensure_snapshot_ref(
    worktree_path: str | Path,
    snapshot_id: str,
    *,
    expected_ref: str,
    expected_commit_sha: str,
    expected_tree_sha: str,
) -> SnapshotResult:
    """Recreate a missing *owned* snapshot ref from its persisted exact commit.

    This is intentionally limited to a durable baseline needed for restoration.
    It never discovers a commit by tree and never repairs a changed named ref:
    either the persisted commit still has the persisted tree and is published
    under precisely its owned name, or recovery stops without touching Git.
    """
    path = _require_worktree_path(worktree_path)
    snapshot_id = _validate_snapshot_id(snapshot_id)
    ref = f"{SNAPSHOT_REF_PREFIX}/{snapshot_id}"
    if expected_ref != ref:
        raise WorktreeError("Snapshot recovery ref does not match its snapshot id")
    env = _git_env()
    actual_tree = _run_git(
        path, ["rev-parse", "--verify", f"{expected_commit_sha}^{{tree}}"], env
    ).stdout.strip()
    if actual_tree != expected_tree_sha:
        raise WorktreeError("Snapshot recovery commit does not match owned tree")
    existing = subprocess.run(
        [_git_executable(), "rev-parse", "--verify", "--quiet", ref],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=False,
    )
    if existing.returncode == 0:
        if existing.stdout.strip() != expected_commit_sha:
            raise WorktreeError("Snapshot recovery ref already exists with a different commit")
    else:
        _run_git(path, ["update-ref", ref, expected_commit_sha, ""], env)
    return SnapshotResult(
        id=snapshot_id,
        ref=ref,
        commit_sha=expected_commit_sha,
        tree_sha=expected_tree_sha,
    )


def verify_snapshot_ref(
    worktree_path: str | Path,
    snapshot_id: str,
    *,
    expected_ref: str,
    expected_commit_sha: str,
    expected_tree_sha: str,
) -> SnapshotResult:
    """Verify an exact owned snapshot identity without repairing or publishing it."""
    path = _require_worktree_path(worktree_path)
    snapshot_id = _validate_snapshot_id(snapshot_id)
    ref = f"{SNAPSHOT_REF_PREFIX}/{snapshot_id}"
    if expected_ref != ref:
        raise WorktreeError("Snapshot verification ref does not match its snapshot id")
    env = _git_env()
    actual_commit = _run_git(path, ["rev-parse", "--verify", ref], env).stdout.strip()
    if actual_commit != expected_commit_sha:
        raise WorktreeError("Snapshot verification ref does not match owned commit")
    actual_tree = _run_git(
        path, ["rev-parse", "--verify", f"{actual_commit}^{{tree}}"], env
    ).stdout.strip()
    if actual_tree != expected_tree_sha:
        raise WorktreeError("Snapshot verification commit does not match owned tree")
    return SnapshotResult(
        id=snapshot_id,
        ref=ref,
        commit_sha=actual_commit,
        tree_sha=actual_tree,
    )


@dataclass(frozen=True)
class SelectiveRestoreResult:
    """Accounting for a selective, idempotent snapshot restoration."""

    requested_paths: tuple[str, ...]
    restored_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]


def snapshot(
    worktree_path: str | Path,
    message: str,
    *,
    force_include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    snapshot_id: str | None = None,
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

    requested_id = _validate_snapshot_id(snapshot_id) if snapshot_id is not None else None
    if requested_id is not None:
        requested_ref = _find_snapshot_ref(path, requested_id, env=env, run_git=git)
        if requested_ref is not None and requested_ref.tree_sha != tree_sha:
            raise WorktreeError(f"Snapshot ref {requested_id} already exists with a different tree")
    existing = _find_snapshot_by_tree(path, tree_sha, env=env, run_git=git)
    if existing is not None:
        existing_id, commit_sha, ref = existing
        if requested_id is not None and existing_id != requested_id:
            ref = f"{SNAPSHOT_REF_PREFIX}/{requested_id}"
            existing_ref = _find_snapshot_ref(path, requested_id, env=env, run_git=git)
            if existing_ref is not None and existing_ref.tree_sha != tree_sha:
                raise WorktreeError(
                    f"Snapshot ref {requested_id} already exists with a different tree"
                )
            git(path, ["update-ref", ref, commit_sha], env)
            existing_id = requested_id
        return SnapshotResult(
            id=existing_id,
            tree_sha=tree_sha,
            commit_sha=commit_sha,
            ref=ref,
        )

    commit_sha = git(path, ["commit-tree", tree_sha, "-m", message], env).stdout.strip()
    result_id = requested_id or uuid.uuid4().hex
    ref = f"{SNAPSHOT_REF_PREFIX}/{result_id}"
    git(path, ["update-ref", ref, commit_sha], env)
    return SnapshotResult(id=result_id, tree_sha=tree_sha, commit_sha=commit_sha, ref=ref)


def _find_snapshot_ref(
    cwd: Path, snapshot_id: str, *, env: dict[str, str], run_git: GitRunner
) -> SnapshotRef | None:
    ref = f"{SNAPSHOT_REF_PREFIX}/{snapshot_id}"
    for entry in parse_snapshot_refs(
        run_git(cwd, ["for-each-ref", SNAPSHOT_REF_LIST_FORMAT, ref], env).stdout
    ):
        if entry.ref == ref:
            return entry
    return None


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

    try:
        archive_stderr = archive.communicate(timeout=30)[1]
    except subprocess.TimeoutExpired as exc:
        archive.kill()
        archive.communicate()
        raise WorktreeError(
            f"Failed to restore snapshot {snapshot_id}: git archive timed out"
        ) from exc
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


def restore_paths(
    worktree_path: str | Path,
    snapshot_id: str,
    paths: Iterable[str],
    *,
    expected_tree_sha: str | None = None,
    after_remove: Callable[[str], None] | None = None,
) -> SelectiveRestoreResult:
    """Restore only ``paths`` from a durable snapshot without touching the index.

    A path absent from the baseline is removed. Requested descendants are
    collapsed under their ancestor, which makes retries safe after a crash
    between deleting a changed path and extracting its baseline counterpart.
    The filesystem operations use ``lstat``/``unlink`` so a runner-created
    symlink is never followed outside the worktree.
    """
    path = _require_worktree_path(worktree_path)
    requested = _normalized_restore_paths(paths)
    operational_roots = _collapsed_restore_paths(requested)
    ref = f"{SNAPSHOT_REF_PREFIX}/{_validate_snapshot_id(snapshot_id)}"
    env = _git_env()
    commit = _run_git(path, ["rev-parse", "--verify", ref], env).stdout.strip()
    tree_sha = _run_git(path, ["rev-parse", "--verify", f"{commit}^{{tree}}"], env).stdout.strip()
    if expected_tree_sha is not None and tree_sha != expected_tree_sha:
        raise WorktreeError(f"Snapshot {snapshot_id} tree does not match expected durable baseline")

    baseline_paths = {
        relative_path
        for relative_path in requested
        if _snapshot_contains_path(path, commit, relative_path, env)
    }
    for relative_path in operational_roots:
        baseline_exists = _snapshot_contains_path(path, commit, relative_path, env)
        _ensure_safe_restore_parent(path, relative_path)
        _remove_worktree_path(path / relative_path)
        if after_remove is not None:
            after_remove(relative_path)
        if baseline_exists:
            _extract_snapshot_path(path, commit, relative_path, env, snapshot_id)
    restored = tuple(
        relative_path for relative_path in requested if relative_path in baseline_paths
    )
    removed = tuple(
        relative_path for relative_path in requested if relative_path not in baseline_paths
    )
    return SelectiveRestoreResult(
        requested_paths=tuple(requested),
        restored_paths=restored,
        removed_paths=removed,
    )


def restore_baseline_worktree(
    worktree_path: str | Path,
    snapshot_id: str,
    *,
    expected_tree_sha: str,
) -> SelectiveRestoreResult:
    """Replace the owned worktree contents with its exact durable baseline.

    This compact recovery mode is valid only while the managed executor owns
    the exclusive worktree lock. It preserves ``.git`` and never enumerates or
    serializes changed paths, so an overflow cannot turn into an unbounded
    recovery event.
    """
    path = _require_worktree_path(worktree_path)
    ref = f"{SNAPSHOT_REF_PREFIX}/{_validate_snapshot_id(snapshot_id)}"
    env = _git_env()
    commit = _run_git(path, ["rev-parse", "--verify", ref], env).stdout.strip()
    tree_sha = _run_git(path, ["rev-parse", "--verify", f"{commit}^{{tree}}"], env).stdout.strip()
    if tree_sha != expected_tree_sha:
        raise WorktreeError(f"Snapshot {snapshot_id} tree does not match expected durable baseline")
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name == ".git":
                continue
            _remove_worktree_path(path / entry.name)
    restore(path, snapshot_id)
    return SelectiveRestoreResult((), (), ())


def delete_snapshot_ref(
    worktree_path: str | Path,
    snapshot_id: str,
    *,
    expected_tree_sha: str | None = None,
    expected_ref: str | None = None,
    expected_commit_sha: str | None = None,
) -> bool:
    """Delete exactly one private snapshot ref after verifying its tree identity.

    Supplying ``expected_tree_sha`` is required by managed-runner cleanup.  The
    expected old commit in ``update-ref -d`` prevents a concurrent replacement
    of the same name from being deleted between verification and removal.
    """
    path = _require_worktree_path(worktree_path)
    ref = f"{SNAPSHOT_REF_PREFIX}/{_validate_snapshot_id(snapshot_id)}"
    # Managed cleanup always provides the complete ownership tuple.  Validate
    # it before invoking Git so malformed durable input cannot reach a command.
    if expected_tree_sha is not None or expected_commit_sha is not None:
        if not all((expected_ref, expected_tree_sha, expected_commit_sha)):
            raise WorktreeError("Snapshot cleanup requires complete ownership identity")
        assert expected_ref is not None
        assert expected_tree_sha is not None
        assert expected_commit_sha is not None
        from orchestrator.graph import validate_git_oid, validate_snapshot_ref

        try:
            validate_snapshot_ref(expected_ref, snapshot_id)
            validate_git_oid(expected_tree_sha)
            validate_git_oid(expected_commit_sha)
        except ValueError as exc:
            raise WorktreeError("Snapshot cleanup ref does not match its snapshot id") from exc
    if expected_ref is not None and expected_ref != ref:
        raise WorktreeError("Snapshot cleanup ref does not match its snapshot id")
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
    commit_sha = exists.stdout.strip()
    if expected_commit_sha is not None and commit_sha != expected_commit_sha:
        raise WorktreeError("Snapshot cleanup commit does not match owned snapshot")
    if expected_tree_sha is not None:
        tree_sha = _run_git(
            path, ["rev-parse", "--verify", f"{commit_sha}^{{tree}}"], env
        ).stdout.strip()
        if tree_sha != expected_tree_sha:
            raise WorktreeError("Snapshot cleanup tree does not match owned snapshot")
    _run_git(path, ["update-ref", "-d", ref, commit_sha], env)
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


def _snapshot_contains_path(
    cwd: Path, commit: str, relative_path: str, env: dict[str, str]
) -> bool:
    result = _run_git(
        cwd,
        ["ls-tree", "-r", "-z", commit, "--", _literal_pathspec(relative_path)],
        env,
    )
    return bool(result.stdout)


def _extract_snapshot_path(
    cwd: Path,
    commit: str,
    relative_path: str,
    env: dict[str, str],
    snapshot_id: str,
) -> None:
    try:
        archive = subprocess.Popen(
            [
                _git_executable(),
                "archive",
                "--format=tar",
                commit,
                "--",
                _literal_pathspec(relative_path),
            ],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as exc:
        raise WorktreeError(f"Failed to restore snapshot {snapshot_id}: {exc}") from exc
    try:
        with tempfile.NamedTemporaryFile(
            prefix="orchestrator-restore-archive-", suffix=".tar"
        ) as tarfile_handle:
            if archive.stdout is None:
                raise WorktreeError(
                    f"Failed to restore snapshot {snapshot_id}: archive pipe unavailable"
                )
            shutil.copyfileobj(archive.stdout, tarfile_handle)
            archive.stdout.close()
            try:
                archive_stderr = archive.communicate(timeout=30)[1]
            except subprocess.TimeoutExpired as exc:
                archive.kill()
                archive.communicate()
                raise WorktreeError(
                    f"Failed to restore snapshot {snapshot_id}: git archive timed out"
                ) from exc
            if archive.returncode != 0:
                raise GitCommandError(
                    f"git archive {commit} -- {relative_path}",
                    archive.returncode,
                    archive_stderr.decode("utf-8", errors="replace"),
                )
            tarfile_handle.flush()
            _validate_archive_paths(tarfile_handle.name, relative_path, snapshot_id)
            tar = subprocess.run(
                ["tar", "-x", "-C", str(cwd), "-f", tarfile_handle.name],
                capture_output=True,
                text=False,
                timeout=30,
                env=env,
                check=False,
            )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, tarfile.TarError) as exc:
        if archive.poll() is None:
            archive.kill()
            archive.communicate()
        raise WorktreeError(f"Failed to restore snapshot {snapshot_id}: {exc}") from exc
    if tar.returncode != 0:
        raise WorktreeError(
            f"Failed to restore snapshot {snapshot_id}: "
            f"{tar.stderr.decode('utf-8', errors='replace')}"
        )


def _validate_archive_paths(archive_path: str, selected_root: str, snapshot_id: str) -> None:
    """Reject an archive whose entries escape its selected literal restore root."""
    with tarfile.open(archive_path, mode="r:") as archive:
        for member in archive.getmembers():
            name = member.name.removesuffix("/")
            if (
                not name
                or name.startswith("/")
                or any(part in {"", ".", ".."} for part in name.split("/"))
            ):
                raise WorktreeError(
                    f"Failed to restore snapshot {snapshot_id}: unsafe archive entry"
                )
            # ``git archive -- <nested/path>`` includes directory entries for
            # the selected root's parents.  They are structural ancestors, not
            # escaping payload; accepting them is required to restore a nested
            # cache root such as ``packages/node_modules``.
            is_parent = selected_root.startswith(f"{name}/")
            if name != selected_root and not name.startswith(f"{selected_root}/") and not is_parent:
                raise WorktreeError(
                    f"Failed to restore snapshot {snapshot_id}: archive entry outside selected path"
                )


def _normalized_restore_paths(paths: Iterable[str]) -> list[str]:
    return sorted({_validate_restore_path(value) for value in paths})


def _collapsed_restore_paths(paths: Iterable[str]) -> list[str]:
    normalized = list(paths)
    collapsed: list[str] = []
    for candidate in normalized:
        if not any(candidate.startswith(f"{ancestor}/") for ancestor in collapsed):
            collapsed.append(candidate)
    return collapsed


def _validate_restore_path(value: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or value.startswith("/")
        or value.endswith("/")
        or "\\" in value
        or "//" in value
    ):
        raise WorktreeError(f"Invalid restore path: {value!r}")
    components = value.split("/")
    if any(
        component in {"", ".", ".."} or component.casefold() == ".git" for component in components
    ):
        raise WorktreeError(f"Invalid restore path: {value!r}")
    return value


def _literal_pathspec(relative_path: str) -> str:
    """Render a validated path as literal Git pathspec syntax."""
    return f":(literal){relative_path}"


def _ensure_safe_restore_parent(worktree: Path, relative_path: str) -> None:
    """Replace unsafe parent transitions without ever resolving a symlink target."""
    current = worktree
    for component in relative_path.split("/")[:-1]:
        current /= component
        try:
            current.lstat()
        except FileNotFoundError:
            current.mkdir()
            continue
        if os.path.islink(current) or not os.path.isdir(current):
            _remove_worktree_path(current)
            current.mkdir()


def _remove_worktree_path(target: Path) -> None:
    try:
        target.lstat()
    except FileNotFoundError:
        return
    if os.path.islink(target) or not os.path.isdir(target):
        target.unlink()
        return
    shutil.rmtree(target)


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
            or any(component.casefold() == ".git" for component in normalized.split("/"))
        ):
            continue
        safe.append(f":(literal){normalized}")
    return safe


def _canonical_cache_roots(paths: list[str]) -> list[str]:
    """Validate, deduplicate, and shallow-sort literal cache root paths."""
    roots = [path.removeprefix(":(literal)") for path in _safe_pathspecs(paths)]
    return sorted(set(roots), key=lambda value: (value.count("/"), value))


def _force_paths_outside_cache_roots(paths: list[str], roots: list[str]) -> list[str]:
    """Prevent force-add from defeating cache-root exclusion before staging."""
    result: list[str] = []
    for pathspec in _safe_pathspecs(paths):
        path = pathspec.removeprefix(":(literal)")
        if any(path == root or path.startswith(f"{root}/") for root in roots):
            continue
        result.append(path)
    return result


def _has_head(cwd: Path, env: dict[str, str]) -> bool:
    result = subprocess.run(
        [_git_executable(), "rev-parse", "--verify", "--quiet", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=False,
    )
    return result.returncode == 0


def _collect_untracked_paths(
    cwd: Path, args: list[str], env: dict[str, str], *, max_items: int, max_bytes: int
) -> list[str]:
    """Read NUL-delimited Git paths incrementally before staging any of them."""
    with tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            [_git_executable(), *args], cwd=cwd, stdout=subprocess.PIPE, stderr=stderr_file, env=env
        )
        assert process.stdout is not None
        buffer = b""
        paths: list[str] = []
        total_bytes = 0
        try:
            while chunk := process.stdout.read(8192):
                buffer += chunk
                while b"\0" in buffer:
                    raw, buffer = buffer.split(b"\0", 1)
                    observed = len(paths) + 1
                    if observed > max_items:
                        raise SnapshotPathLimitError(
                            limit=max_items, observed=observed, metric="items"
                        )
                    total_bytes += len(raw)
                    if total_bytes > max_bytes:
                        raise SnapshotPathLimitError(
                            limit=max_bytes, observed=total_bytes, metric="bytes"
                        )
                    paths.append(raw.decode("utf-8", errors="surrogateescape"))
                if len(buffer) > max_bytes:
                    raise SnapshotPathLimitError(
                        limit=max_bytes, observed=len(buffer), metric="bytes"
                    )
            if buffer:
                raise WorktreeError("git ls-files returned malformed NUL path stream")
            process.wait()
            stderr_file.seek(0)
            stderr = stderr_file.read().decode(errors="replace")
            if process.returncode != 0:
                raise GitCommandError("git " + " ".join(args), process.returncode, stderr)
            return paths
        except BaseException:
            process.terminate()
            process.wait()
            raise


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
        # Git paths decoded with surrogateescape must round-trip through argv;
        # ``fsencode`` is the same filesystem encoding subprocess will use.
        spec_bytes = len(os.fsencode(spec)) + 1  # +1 for the argv separator
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
