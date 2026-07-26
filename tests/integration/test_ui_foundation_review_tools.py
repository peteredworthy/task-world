import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def load_tool(name: str) -> ModuleType:
    path = REPO_ROOT / f"research/ui-foundation/tools/{name}.py"
    spec = importlib.util.spec_from_file_location(f"ui_foundation_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_review_foundation(tmp_path: Path, items: list[dict[str, object]]) -> Path:
    root = tmp_path / "research/ui-foundation"
    source = tmp_path / "source.txt"
    source.write_text("snapshot source\n", encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "active_snapshot_id": "snapshot-test",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {
                        "path": "source.txt",
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "audited_at": "2026-07-24T00:00:00Z",
                    }
                ],
            },
            "items": [],
        },
    )
    write_yaml(root / "catalog/questions.yaml", {"schema_version": "1", "items": items})
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": []})
    schemas = root / "schemas"
    schemas.mkdir()
    shutil.copyfile(
        REPO_ROOT / "research/ui-foundation/schemas/review-feedback.schema.json",
        schemas / "review-feedback.schema.json",
    )
    return root


def write_feedback_export(
    tmp_path: Path, source_snapshot: str, history: list[dict[str, str]]
) -> Path:
    path = tmp_path / "feedback.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "review_version": "phase-3-01",
                "batch_id": "01",
                "source_snapshot": source_snapshot,
                "exported_at": "2026-07-23T00:00:00Z",
                "response_history": history,
            }
        ),
        encoding="utf-8",
    )
    return path


def run_feedback_import(root: Path, export: Path) -> subprocess.CompletedProcess[str]:
    tool = REPO_ROOT / "research/ui-foundation/tools/import_feedback.py"
    return subprocess.run(
        [sys.executable, str(tool), "--root", str(root), str(export)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_review_selection_is_deterministic_and_blocker_only(tmp_path: Path) -> None:
    root = write_review_foundation(
        tmp_path,
        [
            {
                "id": "Q-03",
                "blocking": True,
                "downstream_dependency_count": 2,
                "authority_risk": 3,
                "capability_impact": 1,
            },
            {
                "id": "Q-01",
                "blocking": False,
                "downstream_dependency_count": 99,
                "authority_risk": 3,
                "capability_impact": 3,
            },
            {
                "id": "Q-02",
                "blocking": True,
                "downstream_dependency_count": 2,
                "authority_risk": 3,
                "capability_impact": 2,
            },
        ],
    )

    batches = load_tool("build_review").select_review_items(root)

    assert [[item.id for item in batch] for batch in batches] == [["Q-02", "Q-03"]]


def test_review_selection_limits_blocker_batches_to_twelve(tmp_path: Path) -> None:
    root = write_review_foundation(
        tmp_path,
        [
            {
                "id": f"Q-{index:02d}",
                "blocking": index <= 13,
                "downstream_dependency_count": 15 - index,
                "authority_risk": 3,
                "capability_impact": 3,
            }
            for index in range(1, 16)
        ],
    )

    batches = load_tool("build_review").select_review_items(root)

    assert [len(batch) for batch in batches] == [12, 1]
    assert all(item.blocking for batch in batches for item in batch)


def test_build_review_writes_one_static_projection_per_selected_batch(tmp_path: Path) -> None:
    root = write_review_foundation(
        tmp_path,
        [
            {
                "id": f"Q-{index:02d}",
                "blocking": True,
                "downstream_dependency_count": 14 - index,
                "authority_risk": 3,
                "capability_impact": 3,
            }
            for index in range(1, 14)
        ],
    )

    paths = load_tool("build_review").build_review(root)

    assert [path.name for path in paths] == ["batch-01.html", "batch-02.html"]
    assert all(path.is_file() for path in paths)
    assert "snapshot-test" in paths[0].read_text(encoding="utf-8")


def test_review_selection_uses_highest_impact_non_blockers_when_unblocked(
    tmp_path: Path,
) -> None:
    root = write_review_foundation(
        tmp_path,
        [
            {
                "id": f"Q-{index:02d}",
                "blocking": False,
                "downstream_dependency_count": index,
                "authority_risk": 1,
                "capability_impact": 1,
            }
            for index in range(1, 15)
        ],
    )

    batches = load_tool("build_review").select_review_items(root)

    assert [[item.id for item in batch] for batch in batches] == [
        [f"Q-{index:02d}" for index in range(14, 2, -1)]
    ]


def test_feedback_import_rejects_stale_snapshot(tmp_path: Path) -> None:
    root = write_review_foundation(tmp_path, [])
    export = write_feedback_export(tmp_path, "old", [])

    result = run_feedback_import(root, export)

    assert result.returncode != 0
    assert "FEEDBACK_SNAPSHOT_STALE" in result.stderr


def test_feedback_import_preserves_response_history_as_candidate_decisions(
    tmp_path: Path,
) -> None:
    root = write_review_foundation(tmp_path, [])
    history = [
        {
            "item_id": "Q-1",
            "response": "uncertain",
            "note": "Needs authority evidence.",
            "recorded_at": "2026-07-23T00:01:00Z",
        },
        {
            "item_id": "Q-1",
            "response": "revise",
            "note": "Use the narrower interpretation.",
            "recorded_at": "2026-07-23T00:02:00Z",
        },
    ]
    export = write_feedback_export(tmp_path, "snapshot-test", history)

    decisions = load_tool("import_feedback").import_feedback(root, export)

    assert [(item.item_id, item.response, item.note) for item in decisions] == [
        ("Q-1", "uncertain", "Needs authority evidence."),
        ("Q-1", "revise", "Use the narrower interpretation."),
    ]
    assert all(item.source_snapshot == "snapshot-test" for item in decisions)


def test_feedback_import_cannot_mutate_evidence_or_capability_status(tmp_path: Path) -> None:
    root = write_review_foundation(tmp_path, [])
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [{"id": "CAP-1", "capability_status": "unknown"}],
        },
    )
    export = write_feedback_export(
        tmp_path,
        "snapshot-test",
        [
            {
                "item_id": "CAP-1",
                "response": "accept",
                "note": "Treat as current.",
                "recorded_at": "2026-07-23T00:01:00Z",
            }
        ],
    )
    evidence_path = root / "catalog/evidence.yaml"
    capabilities_path = root / "capabilities/registry.yaml"
    evidence_before = evidence_path.read_bytes()
    capabilities_before = capabilities_path.read_bytes()

    load_tool("import_feedback").import_feedback(root, export)

    assert evidence_path.read_bytes() == evidence_before
    assert capabilities_path.read_bytes() == capabilities_before
