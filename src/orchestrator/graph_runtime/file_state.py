"""Effectful file-state boundary collection for graph runtime callbacks."""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import cast

from orchestrator.git import (
    PreparedSnapshot,
    SnapshotResult,
    WorktreeError,
    delete_snapshot_ref,
    snapshot,
)
from orchestrator.graph import (
    FileStateRecord,
    FileStateClassification,
    FileStatePath,
    FileStatePathKind,
    FileStatePolicy,
    WorktreeStatus,
    classify_file_state,
    default_file_state_policy,
    secret_name_matches,
)
from orchestrator.graph_runtime.errors import CacheScanBudgetExceededError


@dataclass(frozen=True)
class FileStateBoundaryResult:
    classification: FileStateClassification
    output_record: dict[str, object] | None
    rejection_record: dict[str, object] | None
    snapshot_result: SnapshotResult | None
    force_include_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CleanupApplication:
    cleanup_id: str
    superseding_file_state_record: dict[str, object]
    deleted_snapshot_ref: bool


@dataclass(frozen=True)
class WorktreeFileStateBaseline:
    """The pre-execution status used to isolate an execution's file delta."""

    status: WorktreeStatus
    fingerprints: dict[tuple[str, str], str]


@dataclass
class _CacheScanAccounting:
    """One deterministic budget shared by every cache subtree in one collection.

    An entry is charged when its directory entry is inspected, before any
    symlink metadata/target check. Bytes are charged before a secret-candidate
    content read using the observed regular-file size. This makes exhaustion
    fail closed without returning a partial status manifest.
    """

    max_entries: int
    max_bytes: int
    entries: int = 0
    bytes: int = 0

    def inspect_entry(self, path: Path) -> None:
        observed = self.entries + 1
        if observed > self.max_entries:
            raise CacheScanBudgetExceededError(
                metric="entries",
                limit=self.max_entries,
                observed=observed,
                path=path.as_posix(),
            )
        self.entries = observed

    def inspect_bytes(self, path: Path, size: int) -> None:
        observed = self.bytes + size
        if observed > self.max_bytes:
            raise CacheScanBudgetExceededError(
                metric="bytes",
                limit=self.max_bytes,
                observed=observed,
                path=path.as_posix(),
            )
        self.bytes = observed


def collect_worktree_status(
    worktree_path: str | Path,
    policy: FileStatePolicy | None = None,
) -> WorktreeStatus:
    """Collect git worktree status plus metadata needed by the pure classifier."""
    path = Path(worktree_path)
    active_policy = policy or default_file_state_policy()
    cache_scan = _CacheScanAccounting(
        max_entries=active_policy.scan_budget.max_entries,
        max_bytes=active_policy.scan_budget.max_bytes,
    )
    result = _run_git(path, ["status", "--porcelain=v2", "-z", "--ignored=matching"])
    tracked: list[FileStatePath] = []
    untracked: list[FileStatePath] = []
    ignored: list[FileStatePath] = []
    for line, original_path in _porcelain_v2_records(result.stdout):
        prefix = line[0]
        if prefix == "?":
            relpath = line[2:]
            untracked.extend(
                _paths_with_metadata(path, relpath, "untracked", active_policy, cache_scan)
            )
        elif prefix == "!":
            relpath = line[2:]
            ignored.extend(
                _paths_with_metadata(path, relpath, "ignored", active_policy, cache_scan)
            )
        elif prefix in {"1", "2", "u"}:
            status, relpath = _tracked_status_and_path(line)
            if prefix == "2" and original_path is None and "\t" in relpath:
                relpath, original_path = relpath.split("\t", maxsplit=1)
            tracked.append(
                _path_with_metadata(path, relpath, "tracked", active_policy, status=status)
            )
            if prefix == "2" and status.startswith("R") and original_path is not None:
                tracked.append(
                    _path_with_metadata(
                        path,
                        original_path,
                        "tracked",
                        active_policy,
                        status="renamed_from",
                    )
                )
    return WorktreeStatus(
        tracked_modified=tuple(tracked),
        untracked=tuple(untracked),
        ignored=tuple(ignored),
    )


def capture_file_state_boundary(
    *,
    worktree_path: str | Path,
    run_id: str,
    node_id: str,
    execution_id: str,
    base_snapshot_id: str,
    policy: FileStatePolicy | None = None,
    baseline: WorktreeFileStateBaseline | None = None,
) -> FileStateBoundaryResult:
    """Collect and classify a worker boundary without publishing a snapshot.

    The caller owns the managed snapshot protocol: it prepares the submission
    tree, durably stages its exact identity, and only then publishes the ref.
    Keeping this function ref-free prevents an unowned file-state ref when the
    subsequent callback is rejected or the process stops before staging.
    """
    active_policy = policy or default_file_state_policy()
    status = collect_worktree_status(worktree_path, active_policy)
    if baseline is not None:
        status = _status_since_baseline(worktree_path, status, baseline)
    classification = classify_file_state(status, active_policy)
    if classification.verdict == "rejected":
        rejection_record: dict[str, object] = {
            "record_kind": "file_state_rejected",
            "run_id": run_id,
            "node_id": node_id,
            "execution_id": execution_id,
            "base_snapshot_id": base_snapshot_id,
            "reason": "file_state_rejected",
            "classifications": [entry.to_record() for entry in classification.paths],
            "rejected_paths": [entry.to_record() for entry in classification.rejected_paths],
            "residue": [entry.to_record() for entry in classification.residue],
        }
        return FileStateBoundaryResult(
            classification=classification,
            output_record=None,
            rejection_record=rejection_record,
            snapshot_result=None,
        )

    # Ignored-but-accepted output files are force-included so the snapshot is a
    # faithful, restorable copy of the boundary. Tool caches such as .venv are
    # recorded as file-state evidence but excluded from the snapshot pathspec;
    # otherwise normal dependency directories dominate callback staging.
    force_include_paths = [
        entry.path
        for entry in classification.paths
        if entry.source == "ignored"
        and not entry.rejected
        and entry.classification != "tool_cache"
        and not (Path(worktree_path) / entry.path).is_dir()
        and (Path(worktree_path) / entry.path).exists()
    ]
    return FileStateBoundaryResult(
        classification=classification,
        output_record=None,
        rejection_record=None,
        snapshot_result=None,
        force_include_paths=tuple(force_include_paths),
    )


def file_state_output_record(
    boundary: FileStateBoundaryResult,
    snapshot: PreparedSnapshot | SnapshotResult,
    *,
    node_id: str,
    execution_id: str,
    base_snapshot_id: str,
) -> dict[str, object]:
    """Bind an accepted classification to its already-prepared managed tree."""
    if boundary.classification.verdict == "rejected":
        raise WorktreeError("rejected file-state boundary cannot own a snapshot")
    return _file_state_output_record(
        classification=boundary.classification,
        snapshot_result=SnapshotResult(**snapshot.__dict__),
        node_id=node_id,
        execution_id=execution_id,
        base_snapshot_id=base_snapshot_id,
    )


def capture_worktree_file_state_baseline(
    worktree_path: str | Path,
    policy: FileStatePolicy | None = None,
) -> WorktreeFileStateBaseline:
    """Capture the dirty state that existed before a runner starts.

    A graph worktree is shared across sequential task executions. Existing
    files, including runner residue, are not evidence of the next execution
    and must not be re-submitted or checked against that execution's lease.
    """
    active_policy = policy or default_file_state_policy()
    status = collect_worktree_status(worktree_path, active_policy)
    return WorktreeFileStateBaseline(
        status=status,
        fingerprints=_status_fingerprints(worktree_path, status),
    )


def apply_cleanup_requested(
    *,
    worktree_path: str | Path,
    cleanup_request: dict[str, object],
    compromised_record: dict[str, object] | FileStateRecord,
) -> CleanupApplication:
    """Re-snapshot without gatekeeper-secret paths and delete the compromised ref."""
    compromised_payload = _file_state_record_payload(compromised_record)
    cleanup_id = str(cleanup_request.get("cleanup_id", ""))
    paths = _cleanup_paths(cleanup_request)
    old_snapshot_id = str(cleanup_request.get("snapshot_id") or compromised_payload["snapshot_id"])
    snap = snapshot(
        worktree_path,
        f"graph file-state cleanup {cleanup_id}",
        exclude_paths=paths,
    )
    deleted = delete_snapshot_ref(worktree_path, old_snapshot_id)
    return CleanupApplication(
        cleanup_id=cleanup_id,
        superseding_file_state_record=_cleanup_superseding_record(
            compromised_record=compromised_payload,
            cleanup_id=cleanup_id,
            excluded_paths=paths,
            snapshot_result=snap,
        ),
        deleted_snapshot_ref=deleted,
    )


def _file_state_record_payload(record: dict[str, object] | FileStateRecord) -> dict[str, object]:
    if isinstance(record, FileStateRecord):
        return cast(dict[str, object], record.model_dump(mode="json"))
    return record


def _file_state_output_record(
    *,
    classification: FileStateClassification,
    snapshot_result: SnapshotResult,
    node_id: str,
    execution_id: str,
    base_snapshot_id: str,
) -> dict[str, object]:
    entries = [entry.to_record() for entry in classification.paths]
    return {
        "record_id": f"file-state-{execution_id}",
        "record_kind": "file_state",
        "producer_node_id": node_id,
        "port": "file_state",
        "schema": "FileStateRecord",
        "snapshot_id": snapshot_result.id,
        "base_snapshot_id": base_snapshot_id,
        "verdict": classification.verdict,
        "git": {
            "commit_sha": snapshot_result.commit_sha,
            "tree_sha": snapshot_result.tree_sha,
            "ref": snapshot_result.ref,
            "no_commit_reason": None,
        },
        "paths": entries,
    }


def _cleanup_paths(cleanup_request: dict[str, object]) -> list[str]:
    raw_paths = cleanup_request.get("paths")
    if not isinstance(raw_paths, list):
        return []
    paths: list[str] = []
    for raw_path in cast(list[object], raw_paths):
        if isinstance(raw_path, str) and raw_path:
            paths.append(raw_path)
    return paths


def _cleanup_superseding_record(
    *,
    compromised_record: dict[str, object],
    cleanup_id: str,
    excluded_paths: list[str],
    snapshot_result: SnapshotResult,
) -> dict[str, object]:
    old_record_id = str(compromised_record["record_id"])
    excluded = set(excluded_paths)
    record = dict(compromised_record)
    record["record_id"] = f"{old_record_id}-cleanup"
    record["snapshot_id"] = snapshot_result.id
    record["git"] = {
        "commit_sha": snapshot_result.commit_sha,
        "tree_sha": snapshot_result.tree_sha,
        "ref": snapshot_result.ref,
        "no_commit_reason": None,
    }
    record["supersedes_record_id"] = old_record_id
    record["cleanup_id"] = cleanup_id
    record["cleanup_excluded_paths"] = list(excluded_paths)
    record["compromised"] = False
    record["superseded_pending"] = False
    # New canonical records contain one inventory. Historical records are
    # normalized by FileStateRecord before reaching this path.
    for key in (
        "paths",
        "tracked",
        "untracked",
        "ignored",
        "external",
        "classifications",
        "residue",
        "rejected_paths",
    ):
        value = record.get(key)
        if not isinstance(value, list):
            continue
        retained: list[dict[str, object]] = []
        for entry in cast(list[object], value):
            if not isinstance(entry, dict):
                continue
            typed_entry = dict(cast(dict[str, object], entry))
            if typed_entry.get("path") in excluded:
                continue
            retained.append(typed_entry)
        record[key] = retained
    return record


def _tracked_status_and_path(line: str) -> tuple[str, str]:
    maxsplit = 9 if line.startswith("2 ") else 8
    fields = line.split(" ", maxsplit=maxsplit)
    if len(fields) >= maxsplit + 1:
        return fields[1], fields[maxsplit]
    return "modified", line.rsplit(" ", maxsplit=1)[-1]


def _porcelain_v2_records(output: str) -> list[tuple[str, str | None]]:
    """Parse NUL-delimited porcelain-v2 records, including rename origins."""
    fields = output.split("\0")
    records: list[tuple[str, str | None]] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if not record:
            continue
        original_path: str | None = None
        if record.startswith("2 "):
            if index >= len(fields):
                raise WorktreeError("malformed git porcelain-v2 rename record")
            original_path = fields[index]
            index += 1
        records.append((record, original_path))
    return records


def _path_with_metadata(
    worktree_path: Path,
    relpath: str,
    kind: str,
    policy: FileStatePolicy,
    *,
    status: str | None = None,
    cache_scan: _CacheScanAccounting | None = None,
) -> FileStatePath:
    normalized = relpath.rstrip("/")
    full_path = worktree_path / normalized
    repo_escape = _repo_escape(worktree_path, normalized, full_path)
    size_bytes: int | None = None
    entropy: float | None = None
    content_hash: str | None = None
    # lstat first: never read/hash a link target merely while collecting
    # boundary metadata. The classifier receives the link escape fact instead.
    is_link = full_path.is_symlink()
    if not is_link and full_path.is_file():
        size_bytes = full_path.stat().st_size
        if secret_name_matches(normalized, policy):
            if cache_scan is not None:
                cache_scan.inspect_bytes(full_path, size_bytes)
            data = full_path.read_bytes()
            entropy = _shannon_entropy(data)
        if _declared_external_artifact(normalized, policy):
            content_hash = _sha256_file(full_path)
    return FileStatePath(
        path=normalized,
        kind=cast(FileStatePathKind, kind),
        status=status,
        size_bytes=size_bytes,
        entropy=entropy,
        content_hash=content_hash,
        repo_escape=repo_escape,
        symlink_escape=_symlink_escape(worktree_path, full_path),
    )


def _status_since_baseline(
    worktree_path: str | Path,
    status: WorktreeStatus,
    baseline: WorktreeFileStateBaseline,
) -> WorktreeStatus:
    current = _status_fingerprints(worktree_path, status)
    unchanged = {
        key for key, fingerprint in current.items() if baseline.fingerprints.get(key) == fingerprint
    }

    def changed(paths: tuple[FileStatePath, ...]) -> tuple[FileStatePath, ...]:
        return tuple(path for path in paths if (path.kind, path.path) not in unchanged)

    baseline_only = set(baseline.fingerprints) - set(current)

    def disappeared(
        kind: FileStatePathKind, paths: tuple[FileStatePath, ...]
    ) -> tuple[FileStatePath, ...]:
        return tuple(
            FileStatePath(path=path.path, kind=kind, status=_disappearance_status(path))
            for path in paths
            if (kind, path.path) in baseline_only
        )

    return WorktreeStatus(
        tracked_modified=(
            *changed(status.tracked_modified),
            *disappeared("tracked", baseline.status.tracked_modified),
        ),
        untracked=(
            *changed(status.untracked),
            *disappeared("untracked", baseline.status.untracked),
        ),
        ignored=(*changed(status.ignored), *disappeared("ignored", baseline.status.ignored)),
    )


def _disappearance_status(path: FileStatePath) -> str:
    if path.kind == "tracked":
        return "renamed_away" if path.status == "renamed_from" else "restored"
    return "deleted"


def _status_fingerprints(
    worktree_path: str | Path,
    status: WorktreeStatus,
) -> dict[tuple[str, str], str]:
    root = Path(worktree_path)
    fingerprints: dict[tuple[str, str], str] = {}
    for path in (*status.tracked_modified, *status.untracked, *status.ignored):
        full_path = root / path.path
        fingerprints[(path.kind, path.path)] = _path_fingerprint(full_path, path.status)
    return fingerprints


def _path_fingerprint(path: Path, status: str | None) -> str:
    if path.is_symlink():
        return f"symlink:{path.readlink()}:{status or ''}"
    if path.is_file():
        return f"file:{_sha256_file(path)}:{status or ''}"
    if path.exists():
        return f"directory:{status or ''}"
    return f"missing:{status or ''}"


def _paths_with_metadata(
    worktree_path: Path,
    relpath: str,
    kind: FileStatePathKind,
    policy: FileStatePolicy,
    cache_scan: _CacheScanAccounting,
) -> list[FileStatePath]:
    normalized = relpath.rstrip("/")
    full_path = worktree_path / normalized
    if not full_path.is_dir() or full_path.is_symlink():
        return [_path_with_metadata(worktree_path, normalized, kind, policy)]
    # Git commonly reports the cache root itself as one ignored status entry.
    # Treat it exactly like a nested cache root: keep the bounded root evidence
    # and perform the one security traversal under the same shared budget.
    if _is_declared_tool_cache(normalized, kind, policy):
        paths = [_path_with_metadata(worktree_path, normalized, kind, policy)]
        if _cache_root_requires_security_scan(normalized):
            paths.extend(_cache_security_paths(worktree_path, full_path, kind, policy, cache_scan))
        return paths

    # Git may report an untracked or ignored directory as one status entry. The
    # boundary must classify every file so nested secret-like paths cannot be
    # force-included through a bare directory pathspec.
    paths: list[FileStatePath] = []
    for root, dirs, files in os.walk(full_path, followlinks=False):
        dirs.sort()
        for dirname in list(dirs):
            dir_path = Path(root) / dirname
            relative = dir_path.relative_to(worktree_path).as_posix()
            if not _is_declared_tool_cache(relative, kind, policy):
                continue
            paths.append(_path_with_metadata(worktree_path, relative, kind, policy))
            # Do not materialize an unbounded dependency/cache tree in the
            # normal boundary manifest.  Still inspect every descendant that
            # could be security-relevant: tool-cache precedence must never hide
            # a secret-like file or an escaping symlink.
            if _cache_root_requires_security_scan(relative):
                paths.extend(
                    _cache_security_paths(worktree_path, dir_path, kind, policy, cache_scan)
                )
            dirs.remove(dirname)
        # Symlinked directories appear in `dirs` but are never descended
        # (followlinks=False). Classify the symlink entry itself so a
        # repo-escaping link cannot vanish from the boundary evidence.
        for dirname in list(dirs):
            dir_path = Path(root) / dirname
            if dir_path.is_symlink():
                paths.append(
                    _path_with_metadata(
                        worktree_path,
                        dir_path.relative_to(worktree_path).as_posix(),
                        kind,
                        policy,
                    )
                )
        for filename in sorted(files):
            file_path = Path(root) / filename
            paths.append(
                _path_with_metadata(
                    worktree_path,
                    file_path.relative_to(worktree_path).as_posix(),
                    kind,
                    policy,
                )
            )
    return paths


def _is_declared_tool_cache(path: str, kind: FileStatePathKind, policy: FileStatePolicy) -> bool:
    declaration = next(
        (
            declaration
            for declaration in policy.declarations
            if declaration.classification == "tool_cache"
            and (declaration.source_kinds is None or kind in declaration.source_kinds)
            and _pattern_matches(path, declaration.pattern)
        ),
        None,
    )
    return declaration is not None or any(
        _pattern_matches(path, pattern) for pattern in policy.tool_cache_patterns
    )


def _cache_root_requires_security_scan(path: str) -> bool:
    """Return whether an ignored cache may contain run-owned output.

    Worktree setup creates ``.venv`` before a runner lease begins. Its package
    tree contains ordinary credential-named modules, CA certificates, and
    interpreter symlinks outside the worktree, all of which intentionally trip
    the stricter scan used for agent-owned caches. The environment is excluded
    from snapshots and cannot be accepted as output, so retain only its bounded
    root evidence. Other cache roots still receive the full secret/symlink scan.
    """
    normalized = path.replace("\\", "/").strip("/")
    return normalized != ".venv" and not normalized.endswith("/.venv")


def _cache_security_paths(
    worktree_path: Path,
    cache_root: Path,
    kind: FileStatePathKind,
    policy: FileStatePolicy,
    cache_scan: _CacheScanAccounting,
) -> list[FileStatePath]:
    """Collect only security-relevant descendants of an otherwise bounded cache.

    Names and symlink targets are cheap metadata checks; cache file bytes are
    read only for a secret-like name.  This keeps ordinary cache collection
    bounded while preserving the security classification guarantee.
    """
    paths: list[FileStatePath] = []
    for root, dirs, files in os.walk(cache_root, followlinks=False):
        dirs.sort()
        # os.walk supplies directory and file lists separately. Sort their
        # combined names so which limit is reached never depends on filesystem
        # enumeration order or entry type grouping.
        for name in sorted([*dirs, *files]):
            candidate = Path(root) / name
            cache_scan.inspect_entry(candidate)
            relative = candidate.relative_to(worktree_path).as_posix()
            if candidate.is_symlink() or secret_name_matches(relative, policy):
                paths.append(
                    _path_with_metadata(
                        worktree_path,
                        relative,
                        kind,
                        policy,
                        cache_scan=cache_scan,
                    )
                )
    return paths


def _declared_external_artifact(path: str, policy: FileStatePolicy) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    return any(
        declaration.classification == "external_artifact"
        and (
            _pattern_matches(normalized, declaration.pattern)
            or _pattern_matches(f"{normalized}/", declaration.pattern)
        )
        for declaration in policy.declarations
    )


def _pattern_matches(path: str, pattern: str) -> bool:
    normalized_pattern = pattern.replace("\\", "/").strip("/")
    return (
        fnmatch(path, normalized_pattern)
        or fnmatch(f"{path}/", normalized_pattern)
        or fnmatch(path, normalized_pattern.rstrip("/") + "/**")
    )


def _repo_escape(worktree_path: Path, relpath: str, full_path: Path) -> bool:
    if relpath.startswith("/") or relpath == ".." or relpath.startswith("../") or "/../" in relpath:
        return True
    try:
        full_path.resolve().relative_to(worktree_path.resolve())
    except ValueError:
        return True
    return False


def _symlink_escape(worktree_path: Path, full_path: Path) -> bool:
    if not full_path.is_symlink():
        return False
    try:
        full_path.resolve(strict=False).relative_to(worktree_path.resolve())
    except ValueError:
        return True
    return False


def _shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = {byte: data.count(byte) for byte in set(data)}
    length = len(data)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _run_git(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"}
    }
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
    except (FileNotFoundError, subprocess.TimeoutExpired, UnicodeDecodeError) as exc:
        raise WorktreeError(f"Failed to run git {' '.join(args)}: {exc}") from exc
    if result.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def _git_executable() -> str:
    git = shutil.which("git")
    if git is None:
        raise WorktreeError("git executable not found")
    return git
