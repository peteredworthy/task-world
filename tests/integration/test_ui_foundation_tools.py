import importlib.util
import json
from pathlib import Path
import shutil
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
    schemas = root / "schemas"
    schemas.mkdir(parents=True)
    for name in ("semantic-item.schema.json", "review-feedback.schema.json"):
        shutil.copyfile(REPO_ROOT / "research/ui-foundation/schemas" / name, schemas / name)
    return root


def semantic_item(identifier: str, **overrides: object) -> dict[str, object]:
    return {
        "id": identifier,
        "title": identifier,
        "definition": "Definition",
        "implementation_status": "unknown",
        "test_status": "unknown",
        "documentation_status": "unknown",
        "confidence": 1,
        "confidence_basis": "Evidence",
        "evidence_ids": [],
        "conflict_ids": [],
        "question_ids": [],
        "limitations": [],
        "prohibited_interpretations": [],
    } | overrides


def present_action(command_id: str, transition: dict[str, object]) -> dict[str, object]:
    return {
        "id": "ACT-01",
        "implementation_status": "present",
        "capability_status": "current",
        "executable": True,
        "command_id": command_id,
        "actor": "operator",
        "permission_requirements": ["run.write"],
        "preconditions": ["run active"],
        "expected_source_version": "v1",
        "required_input": {"reason": "text"},
        "validation": ["reason nonempty"],
        "durable_effect": "records command",
        "resulting_state_id": "STA-02",
        "failure_modes": ["stale"],
        "stale_state_behavior": "reject",
        "idempotency": "command id",
        "retry_behavior": "safe with same id",
        "reversibility": "irreversible",
        "audit_evidence_ids": ["EVD-01"],
        "transition": transition,
    }


def run_report_validator(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--report", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_validator_rejects_duplicate_ids(tmp_path: Path) -> None:
    root = write_minimal_foundation(tmp_path)
    append_yaml_item(root / "catalog/claims.yaml", semantic_item("CAP-01"))
    append_yaml_item(root / "capabilities/registry.yaml", semantic_item("CAP-01"))
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
                semantic_item(
                    "CAP-01",
                    implementation_status="present",
                    test_status="exercised",
                    documentation_status="documented",
                    capability_status="current",
                    evidence_ids=["EVD-01"],
                )
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
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
            "items": [
                {
                    "id": "CMD-01",
                    "source_kind": "command",
                    "implementation_status": "present",
                    "reachable": True,
                },
                {"id": "EVD-01", "source_kind": "implementation", "reachable": True},
            ],
        },
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        present_action("CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"}),
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


def test_every_phase_requires_both_schema_files(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    (root / "schemas/semantic-item.schema.json").unlink()
    (root / "schemas/review-feedback.schema.json").unlink()
    for phase in range(4):
        result = run_validator(root, phase=phase)
        assert issue_codes(result).count("REQUIRED_SCHEMA_MISSING") == 2


def test_semantic_schema_requires_the_complete_semantic_contract(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    path = root / "schemas/semantic-item.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["required"].remove("confidence_basis")
    path.write_text(json.dumps(schema), encoding="utf-8")
    result = run_validator(root, phase=0)
    assert "SCHEMA_CONTRACT_INVALID" in issue_codes(result)


def test_malformed_typed_action_derivation_transition_and_snapshot_are_rejected(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {"id": "ACT-01", "implementation_status": "sometimes", "actor": ["operator"]},
    )
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {"id": "DRV-01", "status": "maybe", "inputs": "CAP-01"},
    )
    write_yaml(
        root / "reality/state-model.yaml",
        {
            "schema_version": "1",
            "items": [],
            "transitions": [{"from_state_id": ["STA-01"], "to_state_id": "STA-02"}],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": [{"path": 7, "sha256": False}]},
            "items": [],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "ACTION_CONTRACT_INVALID",
        "DERIVATION_CONTRACT_INVALID",
        "STATE_TRANSITION_INVALID",
        "SOURCE_SNAPSHOT_INVALID",
    } <= set(issue_codes(result))


def test_current_capability_rejects_nonreachable_kinds_contradiction_and_unresolved_conflict(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    current = semantic_item(
        "CAP-01",
        implementation_status="present",
        test_status="exercised",
        documentation_status="documented",
        capability_status="current",
        evidence_ids=["EVD-01", "EVD-02", "EVD-03"],
        conflict_ids=["CON-01"],
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [current]})
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {"id": "EVD-01", "source_kind": "executable-schema", "reachable": True},
                {"id": "EVD-02", "source_kind": "test", "test_status": "exercised"},
                {"id": "EVD-03", "source_kind": "documentation", "test_status": "contradicted"},
            ],
        },
    )
    write_yaml(
        root / "catalog/conflicts.yaml",
        {"schema_version": "1", "items": [{"id": "CON-01", "status": "unresolved"}]},
    )
    result = run_validator(root, phase=0)
    assert {
        "CURRENT_IMPLEMENTATION_EVIDENCE_MISSING",
        "CURRENT_EVIDENCE_CONTRADICTED",
        "CURRENT_CONFLICT_UNRESOLVED",
    } <= set(issue_codes(result))


def test_derived_capability_inputs_must_resolve_to_current_capabilities(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    proposed = semantic_item("CAP-01", capability_status="proposed")
    derived = semantic_item("CAP-02", capability_status="derived", derivation_id="DRV-01")
    write_yaml(
        root / "capabilities/registry.yaml",
        {"schema_version": "1", "items": [proposed, derived]},
    )
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {
            "id": "DRV-01",
            "status": "admitted",
            "inputs": ["CAP-01"],
            "algorithm": "identity",
            "output_type": "string",
            "unknown_behavior": "unknown",
            "failure_behavior": "unknown",
            "freshness": "snapshot",
            "recomputation_behavior": "recompute when inputs change",
            "implementation_evidence_ids": ["EVD-01"],
            "limitations": ["none"],
            "prohibited_interpretations": ["causal"],
        },
    )
    result = run_validator(root, phase=0)
    assert "DERIVATION_INPUT_NOT_CURRENT" in issue_codes(result)


def test_present_action_requires_typed_command_namespace_actor_permissions_and_fields(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "command",
                    "implementation_status": "present",
                    "reachable": True,
                }
            ],
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
    assert "ACTION_COMMAND_WRONG_NAMESPACE" in issue_codes(result)
    assert "ACTION_CONTRACT_INVALID" in issue_codes(result)


def test_command_must_be_implemented_and_reachable(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "CMD-01",
                    "source_kind": "command",
                    "implementation_status": "absent",
                    "reachable": False,
                }
            ],
        },
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "present",
            "command_id": "CMD-01",
            "transition": {"from_state_id": "STA-01", "to_state_id": "STA-02"},
        },
    )
    result = run_validator(root, phase=0)
    assert "ACTION_COMMAND_UNAVAILABLE" in issue_codes(result)


def test_present_action_resolves_result_state_and_audit_evidence(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    states = [
        semantic_item("STA-01"),
        semantic_item("STA-02"),
    ]
    write_yaml(
        root / "reality/state-model.yaml",
        {
            "schema_version": "1",
            "items": states,
            "transitions": [{"from_state_id": "STA-01", "to_state_id": "STA-02"}],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "CMD-01",
                    "source_kind": "command",
                    "implementation_status": "present",
                    "reachable": True,
                }
            ],
        },
    )
    action = present_action("CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"})
    action["resulting_state_id"] = "STA-99"
    action["audit_evidence_ids"] = ["EVD-99"]
    write_yaml(root / "reality/actions/ACT-01.yaml", action)
    result = run_validator(root, phase=0)
    assert {
        "STATE_UNKNOWN",
        "ACTION_AUDIT_EVIDENCE_UNRESOLVED",
    } <= set(issue_codes(result))


def test_source_snapshot_rejects_symlink_escape(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    repository_root = root.parents[1]
    (repository_root / "escape.txt").symlink_to(outside)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {
                        "path": "escape.txt",
                        "sha256": "2bb80d537b1da3e38bd30361aa855686bde0ba0d5a73ccba1cac4843f89a253b",
                        "audited_at": "2026-07-23T00:00:00Z",
                    }
                ],
            },
            "items": [],
        },
    )
    result = run_validator(root, phase=0)
    assert "SOURCE_PATH_UNSAFE" in issue_codes(result)


def test_each_review_item_requires_its_own_nonempty_evidence_set(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/claims.yaml",
        {
            "schema_version": "1",
            "items": [semantic_item("CAP-01"), semantic_item("CAP-02")],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "documentation"}],
        },
    )
    batch = root / "reviews/phase-3-reality-capability-01.html"
    batch.write_text(
        '<article data-item-id="CAP-01" data-evidence-ids=""></article>'
        '<article data-item-id="CAP-02" data-evidence-ids="EVD-01"></article>',
        encoding="utf-8",
    )
    result = run_validator(root, phase=3)
    assert "REVIEW_EVIDENCE_MISSING" in issue_codes(result)


def test_unresolved_or_weak_causality_cannot_retain_causal_label(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    relationship = semantic_item(
        "REL-01",
        relationship_type="causal",
        epistemic_status="inferred",
        evidence_ids=["EVD-01"],
    )
    write_yaml(
        root / "reality/relationships.yaml",
        {"schema_version": "1", "items": [relationship]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "implementation",
                    "evidence_type": "temporal-observation",
                }
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "CAUSAL_EPISTEMIC_INSUFFICIENT",
        "CAUSAL_MECHANISM_EVIDENCE_MISSING",
        "CAUSAL_LABEL_UNRESOLVED",
    } <= set(issue_codes(result))


def test_non_mapping_action_and_derivation_roots_are_never_skipped(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    for index, value in enumerate(([], "scalar", None), start=1):
        write_yaml(root / f"reality/actions/ACT-0{index}.yaml", value)
        write_yaml(root / f"capabilities/derivations/DRV-0{index}.yaml", value)
    result = run_validator(root, phase=0)
    assert issue_codes(result).count("ACTION_CONTRACT_INVALID") == 3
    assert issue_codes(result).count("DERIVATION_CONTRACT_INVALID") == 3


def test_derived_capability_requires_admitted_derivation_and_qualifying_evidence(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("CAP-01", capability_status="derived", derivation_id="DRV-01"),
                semantic_item("CAP-02", capability_status="derived", derivation_id="DRV-02"),
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "documentation",
                    "reachable": True,
                }
            ],
        },
    )
    contract = {
        "status": "admitted",
        "inputs": ["CAP-03"],
        "algorithm": "identity",
        "output_type": "string",
        "unknown_behavior": "unknown",
        "failure_behavior": "unknown",
        "freshness": "snapshot",
        "recomputation_behavior": "when inputs change",
        "implementation_evidence_ids": ["EVD-01"],
        "limitations": [],
        "prohibited_interpretations": [],
    }
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {"id": "DRV-01"} | contract,
    )
    write_yaml(
        root / "capabilities/derivations/DRV-02.yaml",
        {"id": "DRV-02"} | contract | {"status": "rejected"},
    )
    result = run_validator(root, phase=0)
    assert {
        "DERIVATION_NOT_ADMITTED",
        "DERIVATION_IMPLEMENTATION_EVIDENCE_INVALID",
    } <= set(issue_codes(result))


def test_action_status_compatibility_and_absent_requirement_purity(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    present = present_action("CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"}) | {
        "capability_status": "proposed",
        "executable": True,
    }
    absent = {
        "id": "ACT-02",
        "implementation_status": "absent",
        "capability_status": "gap",
        "executable": False,
        "required_outcome": "Intervene",
        "source_demand_ids": ["scope.action"],
        "implementation_constraints": ["none"],
        "required_evidence": ["command design"],
        "unresolved_command_decisions": ["authority"],
        "command_id": "CMD-01",
        "transition": {"from_state_id": "STA-01", "to_state_id": "STA-02"},
        "durable_effect": "mutates state",
        "retry_behavior": "retry",
        "idempotency": "keyed",
        "reversibility": "irreversible",
        "audit_evidence_ids": ["EVD-01"],
    }
    write_yaml(root / "reality/actions/ACT-01.yaml", present)
    write_yaml(root / "reality/actions/ACT-02.yaml", absent)
    result = run_validator(root, phase=0)
    assert "ACTION_STATUS_INCOMPATIBLE" in issue_codes(result)
    assert "ABSENT_INTERVENTION_COMPLETED_SEMANTICS" in issue_codes(result)


def test_action_resulting_state_must_match_legal_transition_target(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/state-model.yaml",
        {
            "schema_version": "1",
            "items": [semantic_item("STA-01"), semantic_item("STA-02")],
            "transitions": [{"from_state_id": "STA-01", "to_state_id": "STA-02"}],
        },
    )
    action = present_action("CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"})
    action["resulting_state_id"] = "STA-01"
    write_yaml(root / "reality/actions/ACT-01.yaml", action)
    result = run_validator(root, phase=0)
    assert "ACTION_RESULT_STATE_MISMATCH" in issue_codes(result)


def test_question_references_use_only_typed_question_namespace(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/questions.yaml",
        {"schema_version": "1", "items": [{"id": "Q-01"}]},
    )
    write_yaml(
        root / "catalog/decisions.yaml",
        {"schema_version": "1", "items": [{"id": "DEC-01"}]},
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [semantic_item("CAP-01", question_ids=["Q-01", "Q-99", "DEC-01"])],
        },
    )
    result = run_validator(root, phase=0)
    assert "QUESTION_REFERENCE_WRONG_NAMESPACE" in issue_codes(result)
    assert "QUESTION_REFERENCE_UNRESOLVED" in issue_codes(result)


def test_current_action_status_requires_present_and_executable_in_both_directions(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    absent_current = {
        "id": "ACT-01",
        "implementation_status": "absent",
        "capability_status": "current",
        "executable": False,
        "required_outcome": "Intervene",
        "source_demand_ids": ["scope.action"],
        "implementation_constraints": ["none"],
        "required_evidence": ["command design"],
        "unresolved_command_decisions": ["authority"],
    }
    present_nonexecutable = present_action(
        "CMD-01", {"from_state_id": "STA-01", "to_state_id": "STA-02"}
    ) | {"executable": False}
    write_yaml(root / "reality/actions/ACT-01.yaml", absent_current)
    write_yaml(root / "reality/actions/ACT-02.yaml", present_nonexecutable | {"id": "ACT-02"})
    result = run_validator(root, phase=0)
    assert issue_codes(result).count("ACTION_STATUS_INCOMPATIBLE") == 2


def test_derived_classification_rejects_all_conflicting_semantic_evidence(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    current_input = semantic_item(
        "CAP-01",
        implementation_status="present",
        test_status="exercised",
        documentation_status="documented",
        capability_status="current",
        evidence_ids=["EVD-01", "EVD-02"],
    )
    derived = semantic_item(
        "CAP-02",
        capability_status="derived",
        derivation_id="DRV-01",
        test_status="contradicted",
        documentation_status="conflicting",
        conflict_ids=["CON-01"],
        evidence_ids=["EVD-03"],
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {"schema_version": "1", "items": [current_input, derived]},
    )
    write_yaml(
        root / "catalog/conflicts.yaml",
        {"schema_version": "1", "items": [{"id": "CON-01", "status": "unresolved"}]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {"id": "EVD-01", "source_kind": "implementation", "reachable": True},
                {"id": "EVD-02", "source_kind": "test", "test_status": "exercised"},
                {
                    "id": "EVD-03",
                    "source_kind": "documentation",
                    "test_status": "contradicted",
                },
            ],
        },
    )
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {
            "id": "DRV-01",
            "status": "admitted",
            "inputs": ["CAP-01"],
            "algorithm": "identity",
            "output_type": "string",
            "unknown_behavior": "unknown",
            "failure_behavior": "unknown",
            "freshness": "snapshot",
            "recomputation_behavior": "when inputs change",
            "implementation_evidence_ids": ["EVD-01"],
            "limitations": ["none"],
            "prohibited_interpretations": ["causal"],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "DERIVED_CONFLICT_UNRESOLVED",
        "DERIVED_EVIDENCE_CONTRADICTED",
        "DERIVED_CONFLICTING",
    } <= set(issue_codes(result))


def test_unresolved_conflict_requires_distinct_claims_evidence_and_affected_ids(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/conflicts.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CON-01",
                    "status": "unresolved",
                    "claims": [{"proposition": "same"}, {"proposition": "same"}],
                    "claim_evidence": [{"claim_index": 0, "evidence_ids": ["EVD-01"]}],
                    "affected_ids": [],
                    "settlement_method": "decide",
                }
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "CONFLICT_CLAIMS_NOT_DISTINCT",
        "CONFLICT_EVIDENCE_INSUFFICIENT",
        "CONFLICT_AFFECTED_IDS_MISSING",
    } <= set(issue_codes(result))


def test_conflicting_semantic_item_requires_conflict_or_question_reference(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [semantic_item("ENT-01", documentation_status="conflicting")],
        },
    )
    result = run_validator(root, phase=0)
    assert "CONFLICTING_SEMANTIC_REFERENCE_MISSING" in issue_codes(result)


def test_scope_demand_requires_substantive_finding_not_delegation_assignment(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "key": "demand.one",
                    "source": "docs/jtbd/jobs.md",
                    "source_anchor": "J1",
                    "demand_type": "claim",
                    "label": "Demand",
                    "audit_owner": "graph-runtime",
                    "downstream_jobs": ["J1"],
                    "blocking": True,
                    "phase_1_finding": {"evidence_ids": ["EVD-01"], "status": "found"},
                }
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "path": "agent-reports/00-delegation-plan.md#Key findings",
                }
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert "SCOPE_FINDING_NOT_SUBSTANTIVE" in issue_codes(result)


def test_validator_rejects_unlinked_conflicts_questions_snapshots_and_weak_direct_evidence(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/conflicts.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CON-01",
                    "status": "unresolved",
                    "claims": [{"proposition": "one"}, {"proposition": "two"}],
                    "claim_evidence": [
                        {"claim_index": 0, "evidence_ids": ["EVD-01"]},
                        {"claim_index": 1, "evidence_ids": ["EVD-02"]},
                    ],
                    "affected_ids": ["ENT-01"],
                    "settlement_method": "settle",
                }
            ],
        },
    )
    write_yaml(
        root / "catalog/questions.yaml",
        {
            "schema_version": "1",
            "items": [
                {"id": "Q-01", "status": "open", "blocking": True, "affected_ids": ["ENT-01"]}
            ],
        },
    )
    write_yaml(
        root / "reality/domain-model.yaml",
        {"schema_version": "1", "items": [semantic_item("ENT-01", capability_status="current")]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "snapshots": [{"id": "snapshot-test", "files": []}],
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "implementation",
                    "snapshot_id": "missing",
                    "snapshot_path": "no.py",
                },
                {
                    "id": "EVD-02",
                    "source_kind": "test",
                    "test_status": "exercised",
                    "path": "tests/x.py",
                    "symbol": "test_x",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "no.py",
                },
                {
                    "id": "CMD-01",
                    "source_kind": "command",
                    "implementation_status": "present",
                    "reachable": True,
                    "test_evidence_ids": ["EVD-01"],
                },
            ],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "CONFLICT_BACKLINK_MISSING",
        "QUESTION_BACKLINK_MISSING",
        "UNRESOLVED_ADMISSION_BLOCKED",
        "EVIDENCE_SNAPSHOT_UNRESOLVED",
        "EVIDENCE_SNAPSHOT_PATH_UNRESOLVED",
        "COMMAND_TEST_EVIDENCE_INVALID",
    } <= set(issue_codes(result))


def test_unresolved_conflict_blocks_affected_current_action(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/conflicts.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "CON-01",
                    "status": "unresolved",
                    "claims": [{"proposition": "a"}, {"proposition": "b"}],
                    "claim_evidence": [{"evidence_ids": []}, {"evidence_ids": []}],
                    "affected_ids": ["ACT-01"],
                    "settlement_method": "settle",
                }
            ],
        },
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml",
        {
            "id": "ACT-01",
            "implementation_status": "present",
            "capability_status": "current",
            "conflict_ids": ["CON-01"],
        },
    )
    result = run_validator(root, phase=0)
    assert "UNRESOLVED_ACTION_ADMISSION_BLOCKED" in issue_codes(result)


def test_snapshot_coverage_rejects_hash_valid_but_incomplete_patterns(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    repository = root.parents[1]
    (repository / "src").mkdir()
    (repository / "src/required.py").write_text("x = 1\n", encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "phase1",
                "include_patterns": ["src/**/*.py"],
                "expected_count": 1,
                "covered_count": 1,
                "files": [],
            },
            "items": [],
        },
    )
    result = run_validator(root, phase=0)
    assert "SOURCE_SNAPSHOT_COVERAGE_MISSING" in issue_codes(result)
