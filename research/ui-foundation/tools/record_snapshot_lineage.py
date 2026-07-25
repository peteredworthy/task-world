from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, cast

import yaml


RESERVED_SELF_PATHS = frozenset(
    {
        "research/ui-foundation/catalog/evidence.yaml",
        "research/ui-foundation/catalog/snapshot-lineage.yaml",
    }
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
    values: list[Any] = [evidence.get("snapshot")]
    registered = evidence.get("snapshots")
    if isinstance(registered, list):
        values.extend(cast(list[Any], registered))
    if not all(isinstance(value, dict) for value in values):
        raise ValueError("SNAPSHOT_INVALID")
    snapshots: list[dict[str, Any]] = []
    for value in values:
        value = cast(dict[str, Any], value)
        if value not in snapshots:
            snapshots.append(value)
    return snapshots


def _effective(
    active: dict[str, Any], snapshots: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    by_id = {snapshot.get("id"): snapshot for snapshot in snapshots}
    if len(by_id) != len(snapshots) or not all(isinstance(identifier, str) for identifier in by_id):
        raise ValueError("SNAPSHOT_ID_DUPLICATE")
    chain: list[dict[str, Any]] = []
    current = active
    visited: set[str] = set()
    while True:
        identifier = current.get("id")
        if not isinstance(identifier, str) or identifier in visited:
            raise ValueError("SNAPSHOT_PARENT_CYCLE")
        visited.add(identifier)
        chain.append(current)
        parent = current.get("parent_snapshot_id")
        if parent is None:
            break
        if not isinstance(parent, str) or parent not in by_id:
            raise ValueError("SNAPSHOT_PARENT_UNKNOWN")
        current = by_id[parent]
    effective: dict[str, dict[str, Any]] = {}
    for snapshot in reversed(chain):
        for raw_record in cast(list[Any], snapshot.get("files", [])):
            if not isinstance(raw_record, dict):
                raise ValueError("SNAPSHOT_FILE_INVALID")
            record = cast(dict[str, Any], raw_record)
            path = record.get("path")
            if not isinstance(path, str):
                raise ValueError("SNAPSHOT_FILE_INVALID")
            if path in RESERVED_SELF_PATHS:
                continue
            if record.get("tombstone") is True:
                if path not in effective:
                    raise ValueError(f"INVALID_TOMBSTONE:{path}")
                effective.pop(path)
            else:
                effective[path] = record
    return effective


def _safe_path(repository: Path, value: str) -> Path:
    path = Path(value)
    candidate = (repository / path).resolve()
    if path.is_absolute() or ".." in path.parts or not candidate.is_relative_to(repository):
        raise ValueError(f"UNSAFE_PATH:{value}")
    return candidate


def _dependent_status_bytes(root: Path, snapshot_id: str) -> dict[str, bytes]:
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
        if final_bytes != status_path.read_bytes():
            relative = status_path.resolve().relative_to(repository).as_posix()
            generated[relative] = final_bytes
    return generated


def record(
    root: Path, snapshot_id: str, audited_at: str, paths: list[str], removals: list[str]
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
    effective = _effective(active, snapshots)
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
    generated = _dependent_status_bytes(root, snapshot_id)
    generated_paths = set(generated)
    expected_requested = changed - generated_paths
    expected_requested.update(
        path for path in paths if path not in effective and path not in generated_paths
    )
    caller_requested = set(requested) - generated_paths
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
    for path, content in generated.items():
        _safe_path(repository, path).write_bytes(content)
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")
    lineage_path.write_text(yaml.safe_dump(lineage, sort_keys=False), encoding="utf-8")


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
