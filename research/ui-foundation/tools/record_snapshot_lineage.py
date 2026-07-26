from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, cast

import yaml

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))
from snapshot_resolver import (
    RESERVED_SELF_PATHS,
    resolve_effective_snapshot,
    snapshots_from_evidence,
)


def _load(path: Path) -> dict[str, Any]:
    value: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"YAML_MAPPING_REQUIRED:{path}")
    return cast(dict[str, Any], value)


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _entry_digest(entry: dict[str, Any]) -> str:
    return _digest({key: value for key, value in entry.items() if key != "lineage_entry_digest"})


def _snapshots(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return snapshots_from_evidence(evidence)


def _safe_path(repository: Path, value: str) -> Path:
    path = Path(value)
    candidate = (repository / path).resolve()
    if path.is_absolute() or ".." in path.parts or not candidate.is_relative_to(repository):
        raise ValueError(f"UNSAFE_PATH:{value}")
    return candidate


def _dependent_status_bytes(
    root: Path, snapshot_id: str, effective: dict[str, dict[str, Any]], declared_paths: set[str]
) -> dict[str, bytes]:
    repository = root.parents[1].resolve()
    generated: dict[str, bytes] = {}
    for status_path in (
        root / "catalog/status-test-nodes.yaml",
        root / "catalog/status-evidence-reviews.yaml",
    ):
        if not status_path.exists():
            continue
        status = _load(status_path)
        target = (
            status.get("metadata") if status_path.name == "status-evidence-reviews.yaml" else status
        )
        if isinstance(target, dict):
            target["active_snapshot_id"] = snapshot_id
        if status_path.name == "status-test-nodes.yaml":
            for item in status.get("entries", []):
                if isinstance(item, dict):
                    item["active_snapshot_id"] = snapshot_id
        final_bytes = yaml.safe_dump(status, sort_keys=False).encode()
        current_bytes = status_path.read_bytes()
        relative = status_path.resolve().relative_to(repository).as_posix()
        if final_bytes != current_bytes and (
            relative in declared_paths
            or (
                relative in effective
                and hashlib.sha256(current_bytes).hexdigest() == effective[relative].get("sha256")
            )
        ):
            generated[relative] = final_bytes
    return generated


@contextmanager
def _lock(path: Path) -> Any:
    import fcntl

    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class FilesystemPublisher:
    """Same-directory atomic publisher with rollback recovery for interrupted generations."""

    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def recover(self) -> None:
        if not self.marker.exists():
            return
        values = json.loads(self.marker.read_text(encoding="utf-8"))
        for raw_path, encoded in values["before"].items():
            path = Path(raw_path)
            previous = base64.b64decode(encoded)
            self._replace(path, previous)
        self.marker.unlink()

    def _replace(self, path: Path, content: bytes) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def publish(self, values: dict[Path, bytes], lineage_path: Path) -> None:
        before = {str(path): base64.b64encode(path.read_bytes()).decode() for path in values}
        self._replace(self.marker, json.dumps({"before": before}).encode())
        try:
            for path, content in values.items():
                if path != lineage_path:
                    self._replace(path, content)
            self._replace(lineage_path, values[lineage_path])
        except OSError:
            self.recover()
            raise
        self.marker.unlink()


def record(
    root: Path,
    snapshot_id: str,
    audited_at: str,
    paths: list[str],
    removals: list[str],
    publisher: FilesystemPublisher | None = None,
) -> None:
    lock_path = root / "catalog/.snapshot-lineage.lock"
    with _lock(lock_path):
        effective_publisher = publisher or FilesystemPublisher(
            root / "catalog/.snapshot-lineage.transaction.json"
        )
        effective_publisher.recover()
        _record_locked(root, snapshot_id, audited_at, paths, removals, effective_publisher)


def _record_locked(
    root: Path,
    snapshot_id: str,
    audited_at: str,
    paths: list[str],
    removals: list[str],
    publisher: FilesystemPublisher,
) -> None:
    evidence_path = root / "catalog/evidence.yaml"
    lineage_path = root / "catalog/snapshot-lineage.yaml"
    evidence, lineage = _load(evidence_path), _load(lineage_path)
    if RESERVED_SELF_PATHS.intersection(paths + removals):
        raise ValueError("SNAPSHOT_SELF_REFERENCE")
    snapshots = _snapshots(evidence)
    raw_entries = lineage.get("entries")
    if not isinstance(raw_entries, list) or not all(
        isinstance(entry, dict) for entry in cast(list[Any], raw_entries)
    ):
        raise ValueError("LINEAGE_INVALID")
    entries = cast(list[dict[str, Any]], raw_entries)
    active_id = evidence.get("active_snapshot_id")
    active = next((snapshot for snapshot in snapshots if snapshot.get("id") == active_id), None)
    if not isinstance(active, dict) or not isinstance(active_id, str):
        raise ValueError("ACTIVE_SNAPSHOT_INVALID")
    identifiers = {snapshot.get("id") for snapshot in snapshots} | {
        entry.get("snapshot_id") for entry in entries
    }
    if not snapshot_id or snapshot_id in identifiers:
        raise ValueError("SNAPSHOT_ID_REUSED")
    if any(entry.get("parent_snapshot_id") == active_id for entry in entries):
        raise ValueError("PARENT_NOT_LEAF")
    active_entry = next((entry for entry in entries if entry.get("snapshot_id") == active_id), None)
    if not isinstance(active_entry, dict) or active_entry.get("status") != "active":
        raise ValueError("ACTIVE_LINEAGE_INVALID")
    effective = {record["path"]: record for record in resolve_effective_snapshot(evidence)["files"]}
    requested = paths + removals
    if len(requested) != len(set(requested)):
        raise ValueError("DELTA_PATH_DUPLICATE")
    repository = root.parents[1].resolve()
    changed: set[str] = set()
    for path, record in effective.items():
        candidate = _safe_path(repository, path)
        if not candidate.is_file() or hashlib.sha256(
            candidate.read_bytes()
        ).hexdigest() != record.get("sha256"):
            changed.add(path)
    if not changed and not any(path not in effective for path in paths) and not removals:
        raise ValueError("NO_OP_DELTA")
    generated = _dependent_status_bytes(root, snapshot_id, effective, set(paths))
    automatic_generated_paths = {
        path
        for path in generated
        if path in effective
        and hashlib.sha256(_safe_path(repository, path).read_bytes()).hexdigest()
        == effective[path].get("sha256")
    }
    expected_requested = changed - automatic_generated_paths
    expected_requested.update(path for path in paths if path not in effective)
    caller_requested = set(requested) - automatic_generated_paths
    if caller_requested != expected_requested:
        raise ValueError("UNREQUESTED_DRIFT")
    record_bytes: dict[str, bytes] = {}
    for path in paths:
        candidate = _safe_path(repository, path)
        if not candidate.is_file():
            raise ValueError(f"SOURCE_FILE_MISSING:{path}")
        record_bytes[path] = candidate.read_bytes()
    record_bytes.update(generated)
    records: list[dict[str, Any]] = [
        {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "audited_at": audited_at,
        }
        for path, content in sorted(record_bytes.items())
    ]
    for path in sorted(removals):
        _safe_path(repository, path)
        if path not in effective or (repository / path).exists():
            raise ValueError(f"INVALID_TOMBSTONE:{path}")
        records.append({"path": path, "tombstone": True})
    if not records:
        raise ValueError("NO_OP_DELTA")
    snapshot = {"id": snapshot_id, "parent_snapshot_id": active_id, "files": records}
    evidence.setdefault("snapshots", []).append(snapshot)
    evidence["active_snapshot_id"] = snapshot_id
    active_entry["status"] = "historical"
    active_entry["lineage_entry_digest"] = _entry_digest(active_entry)
    entry = {
        "snapshot_id": snapshot_id,
        "parent_snapshot_id": active_id,
        "snapshot_digest": _digest(snapshot),
        "predecessor_lineage_digest": active_entry["lineage_entry_digest"],
        "status": "active",
    }
    entry["lineage_entry_digest"] = _entry_digest(entry)
    entries.append(entry)
    values = {**{_safe_path(repository, path): content for path, content in generated.items()}}
    values[evidence_path] = yaml.safe_dump(evidence, sort_keys=False).encode()
    values[lineage_path] = yaml.safe_dump(lineage, sort_keys=False).encode()
    publisher.publish(values, lineage_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Append one bounded evidence snapshot delta.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--audited-at", required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--remove", action="append", default=[])
    arguments = parser.parse_args()
    try:
        record(
            arguments.root.resolve(),
            arguments.snapshot_id,
            arguments.audited_at,
            arguments.path,
            arguments.remove,
        )
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
