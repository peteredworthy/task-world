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

from orchestrator.git import SnapshotResult, WorktreeError, delete_snapshot_ref, snapshot
from orchestrator.graph import (
    FileStateClassification,
    FileStatePath,
    FileStatePathKind,
    FileStatePolicy,
    WorktreeStatus,
    classify_file_state,
    default_file_state_policy,
    secret_name_matches,
)


@dataclass(frozen=True)
class FileStateBoundaryResult:
    classification: FileStateClassification
    output_record: dict[str, object] | None
    rejection_record: dict[str, object] | None
    snapshot_result: SnapshotResult | None


@dataclass(frozen=True)
class CleanupApplication:
    cleanup_id: str
    superseding_file_state_record: dict[str, object]
    deleted_snapshot_ref: bool


def collect_worktree_status(
    worktree_path: str | Path,
    policy: FileStatePolicy | None = None,
) -> WorktreeStatus:
    """Collect git worktree status plus metadata needed by the pure classifier."""
    path = Path(worktree_path)
    active_policy = policy or default_file_state_policy()
    result = _run_git(path, ["status", "--porcelain=v2", "--ignored=matching"])
    tracked: list[FileStatePath] = []
    untracked: list[FileStatePath] = []
    ignored: list[FileStatePath] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        prefix = line[0]
        if prefix == "?":
            relpath = line[2:]
            untracked.append(_path_with_metadata(path, relpath, "untracked", active_policy))
        elif prefix == "!":
            relpath = line[2:]
            ignored.extend(_ignored_paths_with_metadata(path, relpath, active_policy))
        elif prefix in {"1", "2", "u"}:
            status, relpath = _tracked_status_and_path(line)
            tracked.append(
                _path_with_metadata(path, relpath, "tracked", active_policy, status=status)
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
) -> FileStateBoundaryResult:
    """Collect, classify, and snapshot the worker boundary."""
    active_policy = policy or default_file_state_policy()
    status = collect_worktree_status(worktree_path, active_policy)
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

    # Ignored-but-accepted files (residue, and tool caches like an in-worktree
    # .venv classified by slice 2.4) are force-included so the snapshot is a
    # faithful, restorable copy of the boundary. A real .venv holds tens of
    # thousands of files, so this list can be huge — `snapshot()` batches the
    # `git add` to stay under ARG_MAX (otherwise execve raised an opaque E2BIG
    # OSError that the codex runner further mislabelled as a transport error).
    force_include_paths = [
        entry.path
        for entry in classification.paths
        if entry.source == "ignored"
        and not entry.rejected
        and not (Path(worktree_path) / entry.path).is_dir()
    ]
    snap = snapshot(
        worktree_path,
        f"graph file-state boundary {run_id}/{node_id}/{execution_id}",
        force_include_paths=force_include_paths,
    )
    output_record = _file_state_output_record(
        classification=classification,
        snapshot_result=snap,
        node_id=node_id,
        execution_id=execution_id,
        base_snapshot_id=base_snapshot_id,
    )
    return FileStateBoundaryResult(
        classification=classification,
        output_record=output_record,
        rejection_record=None,
        snapshot_result=snap,
    )


def apply_cleanup_requested(
    *,
    worktree_path: str | Path,
    cleanup_request: dict[str, object],
    compromised_record: dict[str, object],
) -> CleanupApplication:
    """Re-snapshot without gatekeeper-secret paths and delete the compromised ref."""
    cleanup_id = str(cleanup_request.get("cleanup_id", ""))
    paths = _cleanup_paths(cleanup_request)
    old_snapshot_id = str(cleanup_request.get("snapshot_id") or compromised_record["snapshot_id"])
    snap = snapshot(
        worktree_path,
        f"graph file-state cleanup {cleanup_id}",
        exclude_paths=paths,
    )
    deleted = delete_snapshot_ref(worktree_path, old_snapshot_id)
    return CleanupApplication(
        cleanup_id=cleanup_id,
        superseding_file_state_record=_cleanup_superseding_record(
            compromised_record=compromised_record,
            cleanup_id=cleanup_id,
            excluded_paths=paths,
            snapshot_result=snap,
        ),
        deleted_snapshot_ref=deleted,
    )


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
        "tracked": [
            entry.to_record() for entry in classification.paths if entry.source == "tracked"
        ],
        "untracked": [
            entry.to_record() for entry in classification.paths if entry.source == "untracked"
        ],
        "ignored": [
            entry.to_record() for entry in classification.paths if entry.source == "ignored"
        ],
        "external": [
            entry.to_record()
            for entry in classification.paths
            if entry.classification == "external_artifact"
        ],
        "classifications": entries,
        "residue": [entry.to_record() for entry in classification.residue],
        "rejected_paths": [],
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
    for key in (
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
    fields = line.split(" ", maxsplit=8)
    if len(fields) >= 9:
        return fields[1], fields[8]
    return "modified", line.rsplit(" ", maxsplit=1)[-1]


def _path_with_metadata(
    worktree_path: Path,
    relpath: str,
    kind: str,
    policy: FileStatePolicy,
    *,
    status: str | None = None,
) -> FileStatePath:
    normalized = relpath.strip()
    full_path = worktree_path / normalized
    repo_escape = _repo_escape(worktree_path, normalized, full_path)
    size_bytes: int | None = None
    entropy: float | None = None
    content_hash: str | None = None
    if full_path.is_file():
        size_bytes = full_path.stat().st_size
        if secret_name_matches(normalized, policy):
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


def _ignored_paths_with_metadata(
    worktree_path: Path,
    relpath: str,
    policy: FileStatePolicy,
) -> list[FileStatePath]:
    normalized = relpath.strip()
    full_path = worktree_path / normalized
    if not full_path.is_dir() or full_path.is_symlink():
        return [_path_with_metadata(worktree_path, normalized, "ignored", policy)]

    # Git may report an ignored directory as one status entry. The boundary must
    # classify every file so nested secret-like paths cannot be force-included
    # through a bare directory pathspec.
    paths: list[FileStatePath] = []
    for root, dirs, files in os.walk(full_path, followlinks=False):
        dirs.sort()
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
                        "ignored",
                        policy,
                    )
                )
        for filename in sorted(files):
            file_path = Path(root) / filename
            paths.append(
                _path_with_metadata(
                    worktree_path,
                    file_path.relative_to(worktree_path).as_posix(),
                    "ignored",
                    policy,
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
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise WorktreeError(f"Failed to run git {' '.join(args)}: {exc}") from exc
    if result.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def _git_executable() -> str:
    git = shutil.which("git")
    if git is None:
        raise WorktreeError("git executable not found")
    return git
