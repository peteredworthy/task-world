import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "research/ui-foundation/tools/validate.py"


def write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def append_yaml_item(path: Path, item: dict[str, object]) -> None:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {"items": []}
    value["items"].append(item)
    write_yaml(path, value)


def write_minimal_foundation(tmp_path: Path) -> Path:
    root = tmp_path / "research/ui-foundation"
    for relative in (
        "catalog/ids.yaml",
        "catalog/claims.yaml",
        "catalog/invariants.yaml",
        "catalog/conflicts.yaml",
        "catalog/questions.yaml",
        "catalog/decisions.yaml",
        "capabilities/registry.yaml",
        "reality/domain-model.yaml",
        "reality/relationships.yaml",
        "reality/state-model.yaml",
        "reality/permissions.yaml",
        "reality/evidence/inventory.yaml",
    ):
        write_yaml(root / relative, {"schema_version": "1", "items": []})
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [],
        },
    )
    return root


def run_validator(root: Path, phase: int = 2) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(root), "--phase", str(phase)],
        check=False,
        capture_output=True,
        text=True,
    )


def issue_codes(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [line.split(":", 1)[0] for line in result.stderr.splitlines()]


def load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ui_foundation_validate", VALIDATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_valid_phase_zero(tmp_path: Path) -> Path:
    root = write_minimal_foundation(tmp_path)
    for relative in (
        "index.md",
        "status.md",
        "source-map.md",
        "decision-log.md",
        "open-questions.md",
        "capabilities/gaps.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("complete\n", encoding="utf-8")
    write_yaml(root / "catalog/scope.yaml", {"schema_version": "1", "items": []})
    review = root / "reviews/index.html"
    review.parent.mkdir(parents=True, exist_ok=True)
    review.write_text("Semantic foundation, not a product mockup.", encoding="utf-8")
    return root


def run_report_validator(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--report", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_validator_rejects_duplicate_ids(tmp_path: Path) -> None:
    root = write_minimal_foundation(tmp_path)
    append_yaml_item(root / "catalog/claims.yaml", {"id": "CAP-01"})
    append_yaml_item(root / "catalog/questions.yaml", {"id": "CAP-01"})
    result = run_validator(root)
    assert result.returncode == 1
    assert "ID_DUPLICATE" in result.stderr


def test_validator_rejects_incomplete_derived_claim(tmp_path: Path) -> None:
    root = write_minimal_foundation(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CAP-01",
                    "capability_status": "derived",
                    "derivation_id": "DRV-01",
                }
            ],
        },
    )
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {"id": "DRV-01", "inputs": ["CAP-02"], "output_type": "string"},
    )
    result = run_validator(root)
    assert result.returncode == 1
    assert "DERIVATION_UNKNOWN_BEHAVIOR_MISSING" in result.stderr


def test_validator_rejects_current_claim_without_implementation_evidence(
    tmp_path: Path,
) -> None:
    root = write_minimal_foundation(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CAP-01",
                    "capability_status": "current",
                    "evidence_ids": ["EVD-01"],
                }
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"files": []},
            "items": [{"id": "EVD-01", "source_kind": "product-documentation"}],
        },
    )
    result = run_validator(root)
    assert result.returncode == 1
    assert "CURRENT_IMPLEMENTATION_EVIDENCE_MISSING" in result.stderr


def test_report_validator_requires_handoff_sections(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# Report\n\n## Purpose\nOnly one section.\n", encoding="utf-8")
    result = run_report_validator(report)
    assert result.returncode == 1
    assert "REPORT_SECTION_MISSING" in result.stderr


def test_valid_phase_zero_package_succeeds(tmp_path: Path) -> None:
    result = run_validator(write_valid_phase_zero(tmp_path), phase=0)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_validator_rejects_malformed_items_and_semantic_fields(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(root / "catalog/claims.yaml", {"schema_version": "1", "items": "bad"})
    write_yaml(
        root / "capabilities/registry.yaml", {"schema_version": "1", "items": [{"id": "CAP-01"}]}
    )
    result = run_validator(root, phase=0)
    assert result.returncode == 1
    assert set(issue_codes(result)) == {"CANONICAL_DOCUMENT_INVALID", "SEMANTIC_ITEM_INVALID"}


def test_validator_rejects_invalid_status_and_schema_contract(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CAP-01",
                    "title": "Capability",
                    "definition": "Definition",
                    "implementation_status": "invented",
                    "test_status": "exercised",
                    "documentation_status": "documented",
                    "capability_status": "current",
                    "confidence": 1,
                    "confidence_basis": "Evidence",
                    "evidence_ids": [],
                    "conflict_ids": [],
                    "question_ids": [],
                    "limitations": [],
                    "prohibited_interpretations": [],
                }
            ],
        },
    )
    schema = json.loads(
        (REPO_ROOT / "research/ui-foundation/schemas/semantic-item.schema.json").read_text()
    )
    schema["properties"]["implementation_status"]["enum"] = ["invented"]
    schemas = root / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "semantic-item.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    result = run_validator(root, phase=0)
    assert {"SEMANTIC_ITEM_INVALID", "SCHEMA_CONTRACT_INVALID"} <= set(issue_codes(result))


def test_current_capability_requires_reachable_and_exercised_evidence(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    item = {
        "id": "CAP-01",
        "title": "Capability",
        "definition": "Definition",
        "implementation_status": "present",
        "test_status": "exercised",
        "documentation_status": "documented",
        "capability_status": "current",
        "confidence": 1,
        "confidence_basis": "Evidence",
        "evidence_ids": ["EVD-01", "EVD-02"],
        "conflict_ids": [],
        "question_ids": [],
        "limitations": [],
        "prohibited_interpretations": [],
    }
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {"id": "EVD-01", "source_kind": "implementation", "reachable": False},
                {"id": "EVD-02", "source_kind": "test", "test_status": "contradicted"},
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert {"CURRENT_IMPLEMENTATION_EVIDENCE_MISSING", "CURRENT_EXERCISED_EVIDENCE_MISSING"} <= set(
        issue_codes(result)
    )


def test_validator_rejects_authority_conflicts_and_current_future_leakage(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    base = {
        "title": "Capability",
        "definition": "Definition",
        "test_status": "unknown",
        "documentation_status": "documented",
        "confidence": 1,
        "confidence_basis": "Evidence",
        "evidence_ids": [],
        "question_ids": [],
        "limitations": [],
        "prohibited_interpretations": [],
    }
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                base
                | {
                    "id": "CAP-01",
                    "implementation_status": "absent",
                    "capability_status": "current",
                    "conflict_ids": ["CON-01"],
                },
                base
                | {
                    "id": "CAP-02",
                    "implementation_status": "present",
                    "capability_status": "proposed",
                    "conflict_ids": [],
                },
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert {"CURRENT_CONFLICTING", "CURRENT_FUTURE_LEAKAGE", "FUTURE_CURRENT_LEAKAGE"} <= set(
        issue_codes(result)
    )


def test_current_action_cannot_substitute_proposed_role_for_enforced_authority(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "present",
            "command_id": "CMD-01",
            "enforced_authorization": "absent",
            "proposed_role_policy": "operator",
            "transition": {"from_state_ids": ["STA-01"], "to_state_ids": ["STA-02"]},
        },
    )
    result = run_validator(root, phase=0)
    assert "AUTHORITY_CONFLICT" in issue_codes(result)


def test_feedback_schema_contract_requires_export_and_history_fields(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    schema = json.loads(
        (REPO_ROOT / "research/ui-foundation/schemas/review-feedback.schema.json").read_text()
    )
    schema["required"].remove("source_snapshot")
    schema["properties"]["response_history"]["items"]["required"].remove("note")
    schema["properties"]["response_history"]["items"]["properties"]["response"]["enum"] = ["maybe"]
    schemas = root / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "review-feedback.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    result = run_validator(root, phase=0)
    assert issue_codes(result).count("SCHEMA_CONTRACT_INVALID") == 3


def test_validator_rejects_unsafe_and_unreadable_evidence_paths_and_accumulates(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    directory = root.parents[1] / "source-directory"
    directory.mkdir()
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {"path": "../../secret", "sha256": "0" * 64},
                    {"path": str(tmp_path / "absolute"), "sha256": "0" * 64},
                    {"path": "source-directory", "sha256": "0" * 64},
                ],
            },
            "items": [],
        },
    )
    result = run_validator(root, phase=0)
    assert issue_codes(result).count("SOURCE_PATH_UNSAFE") == 2
    assert "SOURCE_READ_ERROR" in issue_codes(result)


def test_implemented_action_requires_resolved_command_and_legal_transition(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/state-model.yaml",
        {"schema_version": "1", "items": [{"id": "STA-01"}], "transitions": []},
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "present",
            "command_id": "CMD-99",
            "transition": {"from_state_ids": [], "to_state_ids": ["STA-02"]},
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "ACTION_COMMAND_UNRESOLVED",
        "ACTION_TRANSITION_EMPTY",
        "STATE_UNKNOWN",
        "ACTION_TRANSITION_UNREACHABLE",
    } <= set(issue_codes(result))


def test_implemented_action_accepts_resolved_command_and_singular_legal_transition(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    state = {
        "id": "STA-01",
        "title": "Ready",
        "definition": "Ready state",
        "implementation_status": "present",
        "test_status": "exercised",
        "documentation_status": "documented",
        "confidence": 1,
        "confidence_basis": "Evidence",
        "evidence_ids": [],
        "conflict_ids": [],
        "question_ids": [],
        "limitations": [],
        "prohibited_interpretations": [],
    }
    write_yaml(
        root / "reality/state-model.yaml",
        {
            "schema_version": "1",
            "items": [state, state | {"id": "STA-02", "title": "Done"}],
            "transitions": [{"from_state_id": "STA-01", "to_state_id": "STA-02"}],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "command", "reachable": True}],
        },
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "present",
            "command_id": "EVD-01",
            "transition": {"from_state_id": "STA-01", "to_state_id": "STA-02"},
        },
    )
    result = run_validator(root, phase=0)
    assert not {
        "ACTION_COMMAND_UNRESOLVED",
        "ACTION_TRANSITION_EMPTY",
        "STATE_UNKNOWN",
        "ACTION_TRANSITION_UNREACHABLE",
    } & set(issue_codes(result))


def test_absent_intervention_requires_complete_requirement_record(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "absent",
            "capability_status": "gap",
            "executable": False,
        },
    )
    result = run_validator(root, phase=0)
    assert issue_codes(result).count("ABSENT_INTERVENTION_REQUIREMENT_MISSING") == 5


def test_phase_three_requires_review_items_with_canonical_evidence(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    batch = root / "reviews/phase-3-reality-capability-01.html"
    batch.write_text(
        '<article data-item-id="CAP-99" data-evidence-ids="EVD-99"></article>', encoding="utf-8"
    )
    result = run_validator(root, phase=3)
    assert {"REVIEW_REFERENCE_UNRESOLVED", "REVIEW_EVIDENCE_UNRESOLVED"} <= set(issue_codes(result))


def test_phase_three_rejects_review_batch_without_items(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    batch = root / "reviews/phase-3-reality-capability-01.html"
    batch.write_text("<html></html>", encoding="utf-8")
    result = run_validator(root, phase=3)
    assert "REVIEW_ITEMS_MISSING" in issue_codes(result)


def test_report_headings_must_match_exactly(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("## Purposeful\n", encoding="utf-8")
    result = run_report_validator(report)
    assert issue_codes(result).count("REPORT_SECTION_MISSING") == 9


def test_validate_foundation_rejects_invalid_direct_phase(tmp_path: Path) -> None:
    module = load_validator()
    issues = module.validate_foundation(write_valid_phase_zero(tmp_path), 4)
    assert [issue.code for issue in issues] == ["PHASE_INVALID"]
