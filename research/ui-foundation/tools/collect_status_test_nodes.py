from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, cast

import yaml

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))
from snapshot_resolver import resolve_effective_snapshot


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
    return cast(dict[str, object], resolve_effective_snapshot(cast(dict[str, Any], evidence)))


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _exercised_locators(root: Path) -> list[str]:
    scope = _load_yaml(root / "catalog/status-scope.yaml")
    raw_items = scope.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("STATUS_SCOPE_INVALID")
    locators: list[str] = []
    for raw_item in cast(list[Any], raw_items):
        if not isinstance(raw_item, dict):
            raise ValueError("STATUS_SCOPE_INVALID")
        item = cast(dict[str, object], raw_item)
        path = item.get("path")
        identifier = item.get("id")
        if not isinstance(path, str):
            raise ValueError("STATUS_SCOPE_INVALID")
        document = _load_yaml(root / path)
        record = (
            document
            if document.get("id") == identifier
            else next(
                (
                    cast(dict[str, object], candidate)
                    for candidate in cast(list[Any], document.get("items", []))
                    if isinstance(candidate, dict)
                    and cast(dict[str, object], candidate).get("id") == identifier
                ),
                None,
            )
        )
        if not isinstance(record, dict):
            raise ValueError(f"STATUS_SCOPE_RECORD_MISSING:{identifier}")
        bounded_values: object = record.get("bounded_test_locators") or []
        exercised_values: object = record.get("test_locators") or []
        if not isinstance(bounded_values, list) or not isinstance(exercised_values, list):
            raise ValueError(f"EXERCISED_TEST_LOCATORS_INVALID:{identifier}")
        values = list(cast(list[Any], bounded_values))
        if record.get("test_status") == "exercised":
            values.extend(cast(list[Any], exercised_values))
        if not values:
            continue
        if not values or not all(isinstance(value, str) for value in values):
            raise ValueError(f"EXERCISED_TEST_LOCATORS_INVALID:{identifier}")
        locators.extend(cast(list[str], values))
    return sorted(set(locators))


def _safe_path(repository: Path, value: str) -> Path:
    path = Path(value)
    candidate = (repository / path).resolve()
    if path.is_absolute() or ".." in path.parts or not candidate.is_relative_to(repository):
        raise ValueError(f"UNSAFE_PATH:{value}")
    return candidate


def _source_hashes(
    snapshot: dict[str, object], repository: Path, referenced_paths: set[str]
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    raw_files = snapshot.get("files", [])
    if not isinstance(raw_files, list):
        raise ValueError("SNAPSHOT_FILE_INVALID")
    for raw_item in cast(list[Any], raw_files):
        if (
            isinstance(raw_item, dict)
            and isinstance(cast(dict[str, object], raw_item).get("path"), str)
            and isinstance(cast(dict[str, object], raw_item).get("sha256"), str)
        ):
            item = cast(dict[str, object], raw_item)
            path = cast(str, item["path"])
            hashes[path] = cast(str, item["sha256"])
    for path, expected in hashes.items():
        candidate = _safe_path(repository, path)
        if not candidate.is_file():
            raise ValueError(f"SOURCE_FILE_MISSING:{path}")
        content = candidate.read_bytes()
        current = hashlib.sha256(content).hexdigest()
        if path in referenced_paths:
            hashes[path] = current
        elif current != expected:
            raise ValueError(f"STALE_ACTIVE_HASH:{path}")
    for path in referenced_paths - hashes.keys():
        candidate = _safe_path(repository, path)
        if not candidate.is_file():
            raise ValueError(f"SOURCE_FILE_MISSING:{path}")
        hashes[path] = hashlib.sha256(candidate.read_bytes()).hexdigest()
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
    locators = _exercised_locators(root)
    if not locators:
        raise ValueError("NO_EXERCISED_TEST_LOCATORS")
    referenced_paths = {locator.partition("::")[0] for locator in locators}
    for path in referenced_paths:
        _safe_path(repository, path)
    hashes = _source_hashes(snapshot, repository, referenced_paths)
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
        _atomic_write(output, yaml.safe_dump(value, sort_keys=False).encode())
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
