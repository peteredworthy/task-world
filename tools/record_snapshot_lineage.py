#!/usr/bin/env python3
"""Append a canonical evidence snapshot to the UI-foundation lineage registry."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import yaml


def digest(value: dict[str, object], *, omit_lineage_digest: bool = False) -> str:
    if omit_lineage_digest:
        value = {key: item for key, item in value.items() if key != "lineage_entry_digest"}
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot_id")
    parser.add_argument("--root", type=Path, default=Path("research/ui-foundation"))
    parser.add_argument("--audited-at", required=True)
    arguments = parser.parse_args()
    evidence_path = arguments.root / "catalog/evidence.yaml"
    lineage_path = arguments.root / "catalog/snapshot-lineage.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    lineage = yaml.safe_load(lineage_path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict) or not isinstance(lineage, dict):
        raise ValueError("canonical YAML mappings required")
    snapshots = evidence.get("snapshots")
    active_id = evidence.get("active_snapshot_id")
    if not isinstance(snapshots, list) or not isinstance(active_id, str):
        raise ValueError("evidence snapshots required")
    if any(
        isinstance(item, dict) and item.get("id") == arguments.snapshot_id for item in snapshots
    ):
        raise ValueError("duplicate snapshot ID")
    parent_snapshot = next(
        (item for item in snapshots if isinstance(item, dict) and item.get("id") == active_id), None
    )
    entries = lineage.get("entries")
    if not isinstance(parent_snapshot, dict) or not isinstance(entries, list):
        raise ValueError("active snapshot and lineage entries required")
    if any(
        isinstance(entry, dict) and entry.get("snapshot_id") == arguments.snapshot_id
        for entry in entries
    ):
        raise ValueError("duplicate snapshot ID")
    parent = active_id
    parent_entry = next(
        (
            entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("snapshot_id") == parent
        ),
        None,
    )
    if not isinstance(parent_entry, dict):
        raise ValueError("unknown parent")
    if parent_entry.get("status") == "active":
        raise ValueError("active parent must be made historical by an explicit registry migration")
    repository = arguments.root.parents[1]
    snapshots_by_id = {
        item["id"]: item
        for item in snapshots
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    effective_records: dict[str, dict[str, object]] = {}
    current: dict[str, object] | None = parent_snapshot
    visited: set[str] = set()
    while (
        current is not None and isinstance(current.get("id"), str) and current["id"] not in visited
    ):
        visited.add(current["id"])
        for record in current.get("files", []):
            if isinstance(record, dict) and isinstance(record.get("path"), str):
                effective_records.setdefault(record["path"], record)
        parent_id = current.get("parent_snapshot_id")
        current = snapshots_by_id.get(parent_id) if isinstance(parent_id, str) else None
    files: list[dict[str, object]] = []
    for path in sorted(effective_records):
        record = effective_records[path]
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError("parent snapshot file record invalid")
        content = (repository / path).read_bytes()
        files.append(
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "audited_at": arguments.audited_at,
            }
        )
    snapshot: dict[str, object] = {
        "id": arguments.snapshot_id,
        "parent_snapshot_id": parent,
        "provenance": "Append-only snapshot lineage refresh.",
        "audited_at": arguments.audited_at,
        "files": files,
    }
    predecessor = (
        entries[-1].get("lineage_entry_digest")
        if entries and isinstance(entries[-1], dict)
        else None
    )
    entry: dict[str, object] = {
        "snapshot_id": arguments.snapshot_id,
        "parent_snapshot_id": parent,
        "snapshot_digest": digest(snapshot),
        "predecessor_lineage_digest": predecessor,
        "status": "active",
    }
    entry["lineage_entry_digest"] = digest(entry, omit_lineage_digest=True)
    snapshots.append(snapshot)
    evidence["active_snapshot_id"] = arguments.snapshot_id
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")
    with lineage_path.open("a", encoding="utf-8") as stream:
        yaml.safe_dump([entry], stream, sort_keys=False)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"record_snapshot_lineage: {error}", file=sys.stderr)
        raise SystemExit(1)
