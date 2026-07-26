from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = REPO_ROOT / "research/ui-foundation/tools/collect_status_test_nodes.py"
VALIDATOR = REPO_ROOT / "research/ui-foundation/tools/validate.py"


def write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def write_status_repository(tmp_path: Path, source: str, locator: str) -> tuple[Path, Path]:
    repository = tmp_path / "repo"
    root = repository / "research/ui-foundation"
    test_path = repository / locator.partition("::")[0]
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(source, encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-active",
                "files": [
                    {
                        "path": locator.partition("::")[0],
                        "sha256": hashlib.sha256(test_path.read_bytes()).hexdigest(),
                        "audited_at": "2026-07-24T00:00:00Z",
                    }
                ],
            },
            "items": [],
        },
    )
    write_yaml(
        root / "catalog/status-scope.yaml",
        {
            "schema_version": "1",
            "items": [{"id": "STA-1", "path": "reality/state-model.yaml"}],
        },
    )
    write_yaml(
        root / "reality/state-model.yaml",
        {
            "schema_version": "1",
            "items": [{"id": "STA-1", "test_status": "exercised", "test_locators": [locator]}],
        },
    )
    return repository, root


def collect(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(COLLECTOR), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def manifest(root: Path) -> dict[str, object]:
    return yaml.safe_load((root / "catalog/status-test-nodes.yaml").read_text(encoding="utf-8"))


def test_collector_writes_sorted_top_level_class_and_parametrized_nodes(tmp_path: Path) -> None:
    repository, root = write_status_repository(
        tmp_path,
        "import pytest\n\ndef test_top_level():\n    assert True\n\n"
        "class TestStatus:\n    def test_method(self):\n        assert True\n\n"
        "@pytest.mark.parametrize('value', [1, 2])\n"
        "def test_parametrized(value):\n    assert value\n",
        "tests/test_status_nodes.py::test_top_level",
    )
    state = yaml.safe_load((root / "reality/state-model.yaml").read_text(encoding="utf-8"))
    state["items"][0]["test_locators"] = [
        "tests/test_status_nodes.py::TestStatus::test_method",
        "tests/test_status_nodes.py::test_parametrized",
        "tests/test_status_nodes.py::test_top_level",
    ]
    write_yaml(root / "reality/state-model.yaml", state)

    result = collect(root)

    assert result.returncode == 0, result.stderr
    entries = manifest(root)["entries"]
    assert [entry["base_locator"] for entry in entries] == [
        "tests/test_status_nodes.py::TestStatus::test_method",
        "tests/test_status_nodes.py::test_parametrized",
        "tests/test_status_nodes.py::test_top_level",
    ]
    assert entries[1]["concrete_node_ids"] == [
        "tests/test_status_nodes.py::test_parametrized[1]",
        "tests/test_status_nodes.py::test_parametrized[2]",
    ]
    assert manifest(root)["active_snapshot_id"] == "snapshot-active"
    assert manifest(root)["command"] == [
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
    assert repository.exists()


def test_collector_refreshes_hash_for_referenced_test_drift(tmp_path: Path) -> None:
    repository, root = write_status_repository(
        tmp_path,
        "def test_refreshable():\n    assert True\n",
        "tests/test_refreshable.py::test_refreshable",
    )
    test_path = repository / "tests/test_refreshable.py"
    test_path.write_text("def test_refreshable():\n    assert 1 == 1\n", encoding="utf-8")

    result = collect(root)

    assert result.returncode == 0, result.stderr
    entry = manifest(root)["entries"][0]
    assert entry["source_sha256"] == hashlib.sha256(test_path.read_bytes()).hexdigest()


def test_collector_rejects_drift_for_unreferenced_active_file(tmp_path: Path) -> None:
    repository, root = write_status_repository(
        tmp_path,
        "def test_stable():\n    assert True\n",
        "tests/test_stable.py::test_stable",
    )
    unrelated_path = repository / "tests/test_unrelated.py"
    unrelated_path.write_text("def test_unrelated():\n    assert True\n", encoding="utf-8")
    evidence = yaml.safe_load((root / "catalog/evidence.yaml").read_text(encoding="utf-8"))
    evidence["snapshot"]["files"].append(
        {
            "path": "tests/test_unrelated.py",
            "sha256": hashlib.sha256(unrelated_path.read_bytes()).hexdigest(),
            "audited_at": "2026-07-24T00:00:00Z",
        }
    )
    write_yaml(root / "catalog/evidence.yaml", evidence)
    unrelated_path.write_text("def test_unrelated():\n    assert False\n", encoding="utf-8")

    result = collect(root)

    assert result.returncode == 1
    assert "STALE_ACTIVE_HASH:tests/test_unrelated.py" in result.stderr


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            lambda evidence: evidence["snapshot"].update({"parent_snapshot_id": "missing"}),
            "SNAPSHOT_PARENT_UNKNOWN",
        ),
        (
            lambda evidence: evidence["snapshot"].update({"parent_snapshot_id": "snapshot-active"}),
            "SNAPSHOT_PARENT_CYCLE",
        ),
        (
            lambda evidence: evidence.update(
                {
                    "snapshots": [
                        dict(evidence["snapshot"]),
                        dict(evidence["snapshot"]),
                    ]
                }
            ),
            "SNAPSHOT_ID_DUPLICATE",
        ),
        (
            lambda evidence: evidence.update(
                {
                    "active_snapshot_id": "snapshot-active",
                    "snapshots": [
                        {
                            "id": "detached",
                            "parent_snapshot_id": "missing",
                            "files": [],
                        }
                    ],
                }
            ),
            "SNAPSHOT_PARENT_UNKNOWN",
        ),
        (
            lambda evidence: evidence.update(
                {
                    "active_snapshot_id": "snapshot-active",
                    "snapshots": [
                        {"id": "detached-a", "parent_snapshot_id": "detached-b", "files": []},
                        {"id": "detached-b", "parent_snapshot_id": "detached-a", "files": []},
                    ],
                }
            ),
            "SNAPSHOT_PARENT_CYCLE",
        ),
        (
            lambda evidence: evidence.update(
                {
                    "active_snapshot_id": "snapshot-active",
                    "snapshots": [{"id": "detached", "files": [{"path": "missing"}]}],
                }
            ),
            "SNAPSHOT_FILE_INVALID",
        ),
        (
            lambda evidence: evidence.update(
                {
                    "active_snapshot_id": "snapshot-active",
                    "snapshots": [
                        {
                            "id": "detached",
                            "parent_snapshot_id": "snapshot-active",
                            "files": [{"path": "missing", "tombstone": True}],
                        }
                    ],
                }
            ),
            "INVALID_TOMBSTONE:missing",
        ),
        (
            lambda evidence: evidence["snapshot"].update(
                {
                    "files": [
                        {
                            "path": "research/ui-foundation/catalog/evidence.yaml",
                            "tombstone": True,
                        }
                    ]
                }
            ),
            "INVALID_TOMBSTONE:research/ui-foundation/catalog/evidence.yaml",
        ),
    ],
)
def test_collector_rejects_invalid_snapshot_graph_without_replacing_output(
    tmp_path: Path, mutation: object, error: str
) -> None:
    _, root = write_status_repository(
        tmp_path, "def test_valid():\n    assert True\n", "tests/test_valid.py::test_valid"
    )
    output = root / "catalog/status-test-nodes.yaml"
    output.write_text("sentinel\n", encoding="utf-8")
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    assert callable(mutation)
    mutation(evidence)
    write_yaml(evidence_path, evidence)

    result = collect(root)

    assert result.returncode == 1
    assert error in result.stderr
    assert output.read_text(encoding="utf-8") == "sentinel\n"


def test_collector_resolves_tombstone_then_readded_file(tmp_path: Path) -> None:
    repository, root = write_status_repository(
        tmp_path, "def test_valid():\n    assert True\n", "tests/test_valid.py::test_valid"
    )
    source = repository / "tests/test_valid.py"
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["snapshot"]["id"] = "root"
    evidence["snapshots"] = [
        {
            "id": "leaf",
            "parent_snapshot_id": "root",
            "files": [{"path": "tests/test_valid.py", "tombstone": True}],
        },
        {
            "id": "readded",
            "parent_snapshot_id": "leaf",
            "files": [
                {
                    "path": "tests/test_valid.py",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "audited_at": "2026-07-24T00:00:00Z",
                }
            ],
        },
    ]
    evidence["active_snapshot_id"] = "readded"
    write_yaml(evidence_path, evidence)

    result = collect(root)

    assert result.returncode == 0, result.stderr
    assert manifest(root)["active_snapshot_id"] == "readded"


def test_collector_rejects_invalid_tombstone_without_replacing_output(tmp_path: Path) -> None:
    _, root = write_status_repository(
        tmp_path, "def test_valid():\n    assert True\n", "tests/test_valid.py::test_valid"
    )
    output = root / "catalog/status-test-nodes.yaml"
    output.write_text("sentinel\n", encoding="utf-8")
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["snapshot"]["files"] = [{"path": "tests/missing.py", "tombstone": True}]
    write_yaml(evidence_path, evidence)

    result = collect(root)

    assert result.returncode == 1
    assert "INVALID_TOMBSTONE:tests/missing.py" in result.stderr
    assert output.read_text(encoding="utf-8") == "sentinel\n"


def test_collector_ignores_legacy_self_records_but_not_ordinary_files(tmp_path: Path) -> None:
    repository, root = write_status_repository(
        tmp_path,
        "def test_stable():\n    assert True\n",
        "tests/test_stable.py::test_stable",
    )
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    for relative in (
        "research/ui-foundation/catalog/evidence.yaml",
        "research/ui-foundation/catalog/snapshot-lineage.yaml",
    ):
        self_path = repository / relative
        self_path.parent.mkdir(parents=True, exist_ok=True)
        if not self_path.exists():
            self_path.write_text("entries: []\n", encoding="utf-8")
        evidence["snapshot"]["files"].append(
            {
                "path": relative,
                "sha256": hashlib.sha256(self_path.read_bytes()).hexdigest(),
                "audited_at": "2026-07-24T00:00:00Z",
            }
        )
    write_yaml(evidence_path, evidence)

    result = collect(root)

    assert result.returncode == 0, result.stderr


def test_collector_emits_new_referenced_test_for_snapshot_addition(tmp_path: Path) -> None:
    repository, root = write_status_repository(
        tmp_path,
        "def test_existing():\n    assert True\n",
        "tests/test_existing.py::test_existing",
    )
    new_locator = "tests/test_new.py::test_new"
    new_path = repository / "tests/test_new.py"
    new_path.write_text("def test_new():\n    assert True\n", encoding="utf-8")
    state = yaml.safe_load((root / "reality/state-model.yaml").read_text(encoding="utf-8"))
    state["items"][0]["test_locators"].append(new_locator)
    write_yaml(root / "reality/state-model.yaml", state)

    result = collect(root)

    assert result.returncode == 0, result.stderr
    entries = {entry["base_locator"]: entry for entry in manifest(root)["entries"]}
    assert (
        entries[new_locator]["source_sha256"] == hashlib.sha256(new_path.read_bytes()).hexdigest()
    )


def test_collector_rejects_ast_visible_noncollectable_and_collection_errors(tmp_path: Path) -> None:
    _, disabled_root = write_status_repository(
        tmp_path / "disabled",
        "__test__ = False\n\ndef test_hidden():\n    assert True\n",
        "tests/test_disabled.py::test_hidden",
    )
    disabled = collect(disabled_root)
    _, constructor_root = write_status_repository(
        tmp_path / "constructor",
        "class TestWithConstructor:\n    def __init__(self): pass\n    def test_hidden(self): pass\n",
        "tests/test_constructor.py::TestWithConstructor::test_hidden",
    )
    constructor = collect(constructor_root)
    _, broken_root = write_status_repository(
        tmp_path / "broken",
        "raise RuntimeError('collection failure')\n",
        "tests/test_broken.py::test_broken",
    )
    broken = collect(broken_root)

    assert disabled.returncode == 1 and "UNCOLLECTED" in disabled.stderr
    assert constructor.returncode == 1 and "UNCOLLECTED" in constructor.stderr
    assert broken.returncode == 1 and "COLLECTION_ERROR" in broken.stderr


def test_collector_rejects_empty_parametrization_only(tmp_path: Path) -> None:
    _, root = write_status_repository(
        tmp_path,
        "import pytest\n\n@pytest.mark.parametrize('value', [])\ndef test_empty(value):\n    pass\n",
        "tests/test_empty.py::test_empty",
    )

    result = collect(root)

    assert result.returncode == 1
    assert "EMPTY_PARAM_ONLY" in result.stderr


def test_validator_manifest_rejects_mixed_duplicate_stale_and_inactive_entries(
    tmp_path: Path,
) -> None:
    _, root = write_status_repository(
        tmp_path, "def test_valid():\n    assert True\n", "tests/test_valid.py::test_valid"
    )
    collected = collect(root)
    assert collected.returncode == 0, collected.stderr
    value = manifest(root)
    entry = value["entries"][0]
    value["entries"] = [
        entry,
        dict(entry),
        {
            **entry,
            "base_locator": "tests/not-active.py::test_not_active",
            "source_path": "tests/not-active.py",
            "concrete_node_ids": ["tests/not-active.py::test_not_active"],
        },
    ]
    value["entries"][0]["concrete_node_ids"] = [
        "tests/test_valid.py::test_valid",
        "tests/test_valid.py::test_valid",
    ]
    value["entries"][0]["source_sha256"] = "0" * 64
    write_yaml(root / "catalog/status-test-nodes.yaml", value)

    import importlib.util

    spec = importlib.util.spec_from_file_location("status_manifest_validator", VALIDATOR)
    assert spec and spec.loader
    validator = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = validator
    spec.loader.exec_module(validator)
    package = validator.load_foundation(root)
    issues = validator._validate_status_test_manifest(
        package,
        "snapshot-active",
        {
            "tests/test_valid.py": hashlib.sha256(
                (root.parents[1] / "tests/test_valid.py").read_bytes()
            ).hexdigest()
        },
        {"tests/test_valid.py::test_valid"},
    )
    codes = {issue.code for issue in issues}
    for code in (
        "STATUS_TEST_MANIFEST_DUPLICATE_LOCATOR",
        "STATUS_TEST_MANIFEST_DUPLICATE_NODE",
        "STATUS_TEST_MANIFEST_STALE_HASH",
        "STATUS_TEST_MANIFEST_PATH_NOT_ACTIVE",
        "STATUS_TEST_MANIFEST_UNKNOWN_BASE",
    ):
        assert code in codes
