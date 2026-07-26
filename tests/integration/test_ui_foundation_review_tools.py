import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

import pytest
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


def write_review_foundation(
    tmp_path: Path,
    items: list[dict[str, object]],
    priorities: list[dict[str, object]] | None = None,
) -> Path:
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
    questions = []
    for item in items:
        question = {
            key: value
            for key, value in item.items()
            if key
            not in {
                "downstream_dependency_count",
                "authority_risk",
                "capability_impact",
            }
        }
        question.setdefault("affected_ids", [])
        questions.append(question)
    priority_items = priorities
    if priority_items is None:
        priority_items = [
            {
                "id": item["id"],
                "downstream_dependency_count": item["downstream_dependency_count"],
                "authority_risk": item["authority_risk"],
                "capability_impact": item["capability_impact"],
                "basis": f"Test priority for {item['id']}.",
            }
            for item in items
        ]
    write_yaml(root / "catalog/questions.yaml", {"schema_version": "1", "items": questions})
    write_yaml(
        root / "catalog/review-priorities.yaml",
        {"schema_version": "1", "methodology": "Test methodology.", "items": priority_items},
    )
    write_yaml(root / "catalog/conflicts.yaml", {"schema_version": "1", "items": []})
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": []})
    schemas = root / "schemas"
    schemas.mkdir(exist_ok=True)
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


def test_current_review_priority_catalog_loads_with_exact_ordering() -> None:
    batches = load_tool("build_review").select_review_items(REPO_ROOT / "research/ui-foundation")

    assert [[item.id for item in batch] for batch in batches] == [
        ["Q-5", "Q-4", "Q-1", "Q-2", "Q-3"]
    ]


def test_review_selection_rejects_missing_priority(tmp_path: Path) -> None:
    root = write_review_foundation(
        tmp_path,
        [
            {
                "id": "Q-01",
                "blocking": True,
                "status": "open",
                "downstream_dependency_count": 2,
                "authority_risk": 1,
                "capability_impact": 1,
            },
            {
                "id": "Q-02",
                "blocking": True,
                "status": "open",
                "downstream_dependency_count": 1,
                "authority_risk": 1,
                "capability_impact": 1,
            },
        ],
        priorities=[
            {
                "id": "Q-01",
                "downstream_dependency_count": 2,
                "authority_risk": 1,
                "capability_impact": 1,
                "basis": "Only one priority is intentionally present.",
            }
        ],
    )

    try:
        load_tool("build_review").select_review_items(root)
    except ValueError as error:
        assert str(error) == "REVIEW_PRIORITY_MISSING:Q-02"
    else:
        raise AssertionError("missing review priority was accepted")


@pytest.mark.parametrize(
    ("priorities", "expected"),
    [
        (
            [
                {
                    "id": "Q-01",
                    "downstream_dependency_count": 1,
                    "authority_risk": 1,
                    "capability_impact": 1,
                    "basis": "First duplicate row.",
                },
                {
                    "id": "Q-01",
                    "downstream_dependency_count": 1,
                    "authority_risk": 1,
                    "capability_impact": 1,
                    "basis": "Second duplicate row.",
                },
            ],
            "REVIEW_PRIORITY_DUPLICATE:Q-01",
        ),
        (
            [
                {
                    "id": "Q-01",
                    "downstream_dependency_count": 1,
                    "authority_risk": 1,
                    "capability_impact": 1,
                    "basis": "Required row.",
                },
                {
                    "id": "Q-02",
                    "downstream_dependency_count": 1,
                    "authority_risk": 1,
                    "capability_impact": 1,
                    "basis": "Extra row.",
                },
            ],
            "REVIEW_PRIORITY_EXTRA:Q-02",
        ),
        (
            [
                {
                    "id": "Q-01",
                    "downstream_dependency_count": 1,
                    "authority_risk": 4,
                    "capability_impact": 1,
                    "basis": "Out-of-range authority risk.",
                }
            ],
            "REVIEW_PRIORITY_INVALID",
        ),
    ],
)
def test_review_selection_rejects_duplicate_extra_and_invalid_priorities(
    tmp_path: Path, priorities: list[dict[str, object]], expected: str
) -> None:
    root = write_review_foundation(
        tmp_path,
        [
            {
                "id": "Q-01",
                "blocking": True,
                "status": "open",
                "downstream_dependency_count": 1,
                "authority_risk": 1,
                "capability_impact": 1,
            }
        ],
        priorities=priorities,
    )

    with pytest.raises(ValueError, match=f"^{expected}$"):
        load_tool("build_review").select_review_items(root)


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

    assert [path.name for path in paths] == [
        "phase-3-reality-capability-01.html",
        "phase-3-reality-capability-02.html",
    ]
    assert all(path.is_file() for path in paths)
    assert "snapshot-test" in paths[0].read_text(encoding="utf-8")


def test_build_review_projects_canonical_conflict_evidence_and_capability(tmp_path: Path) -> None:
    root = write_review_foundation(
        tmp_path,
        [
            {
                "id": "Q-01",
                "title": "Resolve canonical identity",
                "blocking": True,
                "status": "open",
                "affected_ids": ["ENT-5", "CAP-1"],
                "settlement_method": "Adopt one identity.",
                "downstream_dependency_count": 1,
                "authority_risk": 1,
                "capability_impact": 1,
            }
        ],
    )
    evidence_path = root / "catalog/evidence.yaml"
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["items"] = [
        {
            "id": "EVD-1",
            "source_label": "Attempt persistence audit",
            "path": "agent-reports/01-domain-persistence.md#identity",
            "symbol": "Attempt.id",
        }
    ]
    write_yaml(evidence_path, evidence)
    write_yaml(
        root / "catalog/conflicts.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CON-1",
                    "title": "Attempt identities disagree",
                    "status": "unresolved",
                    "affected_ids": ["ENT-5"],
                    "claims": [
                        {"proposition": "Use persisted id."},
                        {"proposition": "Use public attempt id."},
                    ],
                    "decisive_evidence_ids": ["EVD-1"],
                }
            ],
        },
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CAP-1",
                    "title": "Attempt identity",
                    "capability_status": "gap",
                    "definition": "No canonical identity conversion exists.",
                    "confidence": "medium",
                }
            ],
        },
    )

    content = load_tool("build_review").build_review(root)[0].read_text(encoding="utf-8")

    assert "Attempt identities disagree" in content
    assert "Use persisted id." in content
    assert "Attempt persistence audit" in content
    assert "agent-reports/01-domain-persistence.md#identity" in content
    assert "Attempt.id" in content
    assert "Attempt identity" in content
    assert '"capability_status": "gap"' in content
    assert "No canonical identity conversion exists." in content

    conflicts = yaml.safe_load((root / "catalog/conflicts.yaml").read_text(encoding="utf-8"))
    conflicts["items"][0]["title"] = "Revised attempt identity conflict"
    write_yaml(root / "catalog/conflicts.yaml", conflicts)
    evidence["items"][0]["source_label"] = "Revised persistence audit"
    write_yaml(evidence_path, evidence)
    capabilities = yaml.safe_load((root / "capabilities/registry.yaml").read_text(encoding="utf-8"))
    capabilities["items"][0]["title"] = "Revised attempt identity"
    write_yaml(root / "capabilities/registry.yaml", capabilities)

    changed_content = load_tool("build_review").build_review(root)[0].read_text(encoding="utf-8")

    assert "Revised attempt identity conflict" in changed_content
    assert "Revised persistence audit" in changed_content
    assert "Revised attempt identity" in changed_content
    assert "Attempt identities disagree" not in changed_content


def test_build_review_rejects_unresolved_conflict_evidence_without_a_catalog_record(
    tmp_path: Path,
) -> None:
    root = write_review_foundation(
        tmp_path,
        [
            {
                "id": "Q-01",
                "blocking": True,
                "status": "open",
                "affected_ids": ["ENT-5"],
                "downstream_dependency_count": 1,
                "authority_risk": 1,
                "capability_impact": 1,
            }
        ],
    )
    write_yaml(
        root / "catalog/conflicts.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CON-1",
                    "title": "Attempt identities disagree",
                    "status": "unresolved",
                    "affected_ids": ["ENT-5"],
                    "claims": [{"proposition": "Use persisted id."}],
                    "decisive_evidence_ids": ["EVD-404"],
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="^REVIEW_EVIDENCE_MISSING:EVD-404$"):
        load_tool("build_review").build_review(root)


@pytest.mark.parametrize("status", ["invented", None])
def test_build_review_rejects_invalid_or_missing_conflict_status(
    tmp_path: Path, status: str | None
) -> None:
    root = write_review_foundation(
        tmp_path,
        [
            {
                "id": "Q-01",
                "blocking": True,
                "status": "open",
                "affected_ids": ["ENT-5"],
                "downstream_dependency_count": 1,
                "authority_risk": 1,
                "capability_impact": 1,
            }
        ],
    )
    conflict = {
        "id": "CON-1",
        "title": "Invalid conflict status",
        "affected_ids": ["ENT-5"],
        "claims": [{"proposition": "A claim."}],
        "decisive_evidence_ids": [],
    }
    if status is not None:
        conflict["status"] = status
    write_yaml(
        root / "catalog/conflicts.yaml",
        {
            "schema_version": "1",
            "items": [conflict],
        },
    )

    with pytest.raises(ValueError, match="^REVIEW_CONFLICT_STATUS_INVALID:CON-1$"):
        load_tool("build_review").build_review(root)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("capability_status", "invented", "REVIEW_CAPABILITY_STATUS_INVALID:CAP-1"),
        ("capability_status", None, "REVIEW_CAPABILITY_STATUS_INVALID:CAP-1"),
        ("confidence", "certain", "REVIEW_CAPABILITY_CONFIDENCE_INVALID:CAP-1"),
        ("confidence", None, "REVIEW_CAPABILITY_CONFIDENCE_INVALID:CAP-1"),
    ],
)
def test_build_review_rejects_invalid_capability_classification_and_confidence(
    tmp_path: Path, field: str, value: str | None, expected: str
) -> None:
    root = write_review_foundation(
        tmp_path,
        [
            {
                "id": "Q-01",
                "blocking": True,
                "status": "open",
                "affected_ids": ["CAP-1"],
                "downstream_dependency_count": 1,
                "authority_risk": 1,
                "capability_impact": 1,
            }
        ],
    )
    capability = {
        "id": "CAP-1",
        "title": "Capability",
        "capability_status": "gap",
        "definition": "A canonical capability.",
        "confidence": "medium",
    }
    if value is None:
        del capability[field]
    else:
        capability[field] = value
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [capability]})

    with pytest.raises(ValueError, match=f"^{expected}$"):
        load_tool("build_review").build_review(root)


def test_build_review_removes_only_obsolete_managed_batches(tmp_path: Path) -> None:
    items = [
        {
            "id": f"Q-{index:02d}",
            "blocking": True,
            "status": "open",
            "downstream_dependency_count": 14 - index,
            "authority_risk": 3,
            "capability_impact": 3,
        }
        for index in range(1, 14)
    ]
    root = write_review_foundation(tmp_path, items)
    build_review = load_tool("build_review").build_review
    assert [path.name for path in build_review(root)] == [
        "phase-3-reality-capability-01.html",
        "phase-3-reality-capability-02.html",
    ]
    index = root / "reviews/index.html"

    write_review_foundation(tmp_path, items[:1])
    paths = build_review(root)

    assert [path.name for path in paths] == ["phase-3-reality-capability-01.html"]
    assert not (root / "reviews/phase-3-reality-capability-02.html").exists()
    assert "phase-3-reality-capability-01.html" in index.read_text(encoding="utf-8")


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
