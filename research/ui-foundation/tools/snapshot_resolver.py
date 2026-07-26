from __future__ import annotations

from typing import Any, cast


RESERVED_SELF_PATHS = frozenset(
    {
        "research/ui-foundation/catalog/evidence.yaml",
        "research/ui-foundation/catalog/snapshot-lineage.yaml",
    }
)


def snapshots_from_evidence(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    legacy = evidence.get("snapshot")
    registered = evidence.get("snapshots")
    if not isinstance(legacy, dict) or (
        registered is not None and not isinstance(registered, list)
    ):
        raise ValueError("SNAPSHOT_INVALID")
    legacy_snapshot = cast(dict[str, Any], legacy)
    registered_values = cast(list[Any], registered) if registered is not None else []
    if not all(isinstance(value, dict) for value in registered_values):
        raise ValueError("SNAPSHOT_INVALID")
    registered_snapshots = cast(list[dict[str, Any]], registered_values)
    all_snapshots: list[dict[str, Any]] = [legacy_snapshot, *registered_snapshots]
    identifiers = [snapshot.get("id") for snapshot in all_snapshots]
    if not all(isinstance(identifier, str) and identifier for identifier in identifiers):
        raise ValueError("SNAPSHOT_ID_DUPLICATE")

    registered_by_id: dict[str, dict[str, Any]] = {}
    for snapshot in registered_snapshots:
        identifier = cast(str, snapshot["id"])
        if identifier in registered_by_id:
            raise ValueError("SNAPSHOT_ID_DUPLICATE")
        registered_by_id[identifier] = snapshot

    legacy_id = cast(str, legacy_snapshot["id"])
    registered_legacy = registered_by_id.get(legacy_id)
    if registered_legacy is not None:
        if registered_legacy != legacy_snapshot:
            raise ValueError("SNAPSHOT_ID_DUPLICATE")
        return [
            legacy_snapshot,
            *[snapshot for snapshot in registered_snapshots if snapshot is not registered_legacy],
        ]
    return all_snapshots


def resolve_effective_snapshot(evidence: dict[str, Any]) -> dict[str, Any]:
    snapshots = snapshots_from_evidence(evidence)
    by_id = {cast(str, snapshot["id"]): snapshot for snapshot in snapshots}
    active_id = evidence.get("active_snapshot_id")
    if active_id is None and len(snapshots) == 1:
        active_id = snapshots[0]["id"]
    if not isinstance(active_id, str) or active_id not in by_id:
        raise ValueError("ACTIVE_SNAPSHOT_INVALID")
    _validate_snapshot_graph(snapshots, by_id)
    chain: list[dict[str, Any]] = []
    current = by_id[active_id]
    visited: set[str] = set()
    while True:
        identifier = cast(str, current["id"])
        if identifier in visited:
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
        effective = _apply_snapshot_files(snapshot, effective)
    active = dict(by_id[active_id])
    active["files"] = list(effective.values())
    return active


def _validate_snapshot_graph(
    snapshots: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]
) -> None:
    effective_by_id: dict[str, dict[str, dict[str, Any]]] = {}
    visiting: set[str] = set()

    def validate(identifier: str) -> None:
        if identifier in effective_by_id:
            return
        if identifier in visiting:
            raise ValueError("SNAPSHOT_PARENT_CYCLE")
        visiting.add(identifier)
        snapshot = by_id[identifier]
        parent = snapshot.get("parent_snapshot_id")
        if parent is not None:
            if not isinstance(parent, str) or parent not in by_id:
                raise ValueError("SNAPSHOT_PARENT_UNKNOWN")
            validate(parent)
            effective = dict(effective_by_id[parent])
        else:
            effective = {}
        effective_by_id[identifier] = _apply_snapshot_files(snapshot, effective)
        visiting.remove(identifier)

    for snapshot in snapshots:
        validate(cast(str, snapshot["id"]))


def _apply_snapshot_files(
    snapshot: dict[str, Any], inherited: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    effective = dict(inherited)
    raw_files = snapshot.get("files", [])
    if not isinstance(raw_files, list):
        raise ValueError("SNAPSHOT_FILE_INVALID")
    seen: set[str] = set()
    for raw_value in cast(list[Any], raw_files):
        if not isinstance(raw_value, dict):
            raise ValueError("SNAPSHOT_FILE_INVALID")
        raw_record = cast(dict[str, Any], raw_value)
        path = raw_record.get("path")
        if not isinstance(path, str) or not path or path in seen:
            raise ValueError("SNAPSHOT_FILE_INVALID")
        seen.add(path)
        if raw_record.get("tombstone") is True:
            if set(raw_record) != {"path", "tombstone"} or path not in effective:
                raise ValueError(f"INVALID_TOMBSTONE:{path}")
            effective.pop(path)
        else:
            sha256 = raw_record.get("sha256")
            if not isinstance(sha256, str) or not sha256:
                raise ValueError("SNAPSHOT_FILE_INVALID")
            if path not in RESERVED_SELF_PATHS:
                effective[path] = raw_record
    return effective
