from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
from typing import Any, cast

import yaml


TOOL_SCHEMA = "status-test-nodes/v1"
COMMAND = [
    "uv",
    "run",
    "--active",
    "pytest",
    "--collect-only",
    "-q",
    "-o",
    "addopts=",
    "-n",
    "0",
]


def _load_yaml(path: Path) -> dict[str, object]:
    value: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"YAML mapping required: {path}")
    return cast(dict[str, object], value)


def _active_snapshot(root: Path) -> dict[str, object]:
    evidence = _load_yaml(root / "catalog/evidence.yaml")
    extra_snapshots = evidence.get("snapshots")
    snapshots: list[object] = [evidence.get("snapshot")]
    if isinstance(extra_snapshots, list):
        snapshots.extend(extra_snapshots)
    active_id = evidence.get("active_snapshot_id")
    if isinstance(active_id, str):
        snapshot = next(
            (item for item in snapshots if isinstance(item, dict) and item.get("id") == active_id),
            None,
        )
    else:
        snapshot = evidence.get("snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("id"), str):
        raise ValueError("ACTIVE_SNAPSHOT_INVALID")
    by_id = {
        item["id"]: item
        for item in snapshots
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    resolved = dict(snapshot)
    files = {
        item["path"]: item
        for item in snapshot.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    parent = snapshot.get("parent_snapshot_id")
    visited = {snapshot["id"]}
    while isinstance(parent, str) and parent in by_id and parent not in visited:
        visited.add(parent)
        parent_snapshot = by_id[parent]
        for item in parent_snapshot.get("files", []):
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                files.setdefault(item["path"], item)
        parent = parent_snapshot.get("parent_snapshot_id")
    resolved["files"] = list(files.values())
    return cast(dict[str, object], resolved)


def _exercised_locators(root: Path) -> list[str]:
    scope = _load_yaml(root / "catalog/status-scope.yaml")
    items = scope.get("items")
    if not isinstance(items, list):
        raise ValueError("STATUS_SCOPE_INVALID")
    locators: list[str] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("STATUS_SCOPE_INVALID")
        document = _load_yaml(root / item["path"])
        identifier = item.get("id")
        record = (
            document
            if document.get("id") == identifier
            else next(
                (
                    candidate
                    for candidate in document.get("items", [])
                    if isinstance(candidate, dict) and candidate.get("id") == identifier
                ),
                None,
            )
        )
        if not isinstance(record, dict):
            raise ValueError(f"STATUS_SCOPE_RECORD_MISSING:{identifier}")
        values = list(record.get("bounded_test_locators") or [])
        if record.get("test_status") == "exercised":
            values.extend(record.get("test_locators") or [])
        if not values:
            continue
        if not values or not all(isinstance(value, str) for value in values):
            raise ValueError(f"EXERCISED_TEST_LOCATORS_INVALID:{identifier}")
        locators.extend(values)
    return sorted(set(locators))


def _source_hashes(snapshot: dict[str, object], repository: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for item in snapshot.get("files", []):
        if (
            isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and isinstance(item.get("sha256"), str)
        ):
            hashes[item["path"]] = item["sha256"]
    for path, expected in hashes.items():
        content = (repository / path).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"STALE_ACTIVE_HASH:{path}")
    return hashes


def _collected_nodes(output: str) -> set[str]:
    return {
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith("tests/") and "::" in line and " " not in line.strip()
    }


def collect(root: Path) -> dict[str, Any]:
    repository = root.parents[1]
    snapshot = _active_snapshot(root)
    hashes = _source_hashes(snapshot, repository)
    locators = _exercised_locators(root)
    if not locators:
        raise ValueError("NO_EXERCISED_TEST_LOCATORS")
    result = subprocess.run(
        [*COMMAND, *locators],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and "not found:" in result.stdout + result.stderr:
        raise ValueError(f"UNCOLLECTED:{result.stderr.strip() or result.stdout.strip()}")
    if result.returncode != 0:
        raise ValueError(f"COLLECTION_ERROR:{result.stderr.strip() or result.stdout.strip()}")
    nodes = _collected_nodes(result.stdout)
    entries: list[dict[str, Any]] = []
    for locator in locators:
        concrete = sorted(
            node for node in nodes if node == locator or node.startswith(f"{locator}[")
        )
        if not concrete:
            raise ValueError(f"UNCOLLECTED:{locator}")
        if any(node.endswith("[NOTSET]") for node in concrete):
            raise ValueError(f"EMPTY_PARAM_ONLY:{locator}")
        source_path = locator.partition("::")[0]
        source_hash = hashes.get(source_path)
        if source_hash is None:
            raise ValueError(f"PATH_NOT_ACTIVE:{source_path}")
        entries.append(
            {
                "base_locator": locator,
                "concrete_node_ids": concrete,
                "source_path": source_path,
                "source_sha256": source_hash,
                "active_snapshot_id": snapshot["id"],
            }
        )
    return {
        "schema_version": "1",
        "tool_schema": TOOL_SCHEMA,
        "command": COMMAND,
        "active_snapshot_id": snapshot["id"],
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        value = collect(arguments.root.resolve())
        output = arguments.root / "catalog/status-test-nodes.yaml"
        output.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
