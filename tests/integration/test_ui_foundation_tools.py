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


def test_graph_node_state_contract_rejects_pending_alias_and_missing_node_states(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    state_path = root / "reality/state-model.yaml"
    state_model = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    for item in state_model["items"]:
        if item["id"] == "STA-71":
            item["id"] = "STA-28"
            item["title"] = "Graph node pending"
    state_model["items"] = [
        item for item in state_model["items"] if item["id"] not in {"STA-72", "STA-73"}
    ]
    state_path.write_text(yaml.safe_dump(state_model, sort_keys=False), encoding="utf-8")

    validator = load_validator()
    issues = validator.validate_graph_node_state_contract(root)

    assert {"GRAPH_NODE_STATE_ALIAS", "GRAPH_NODE_STATE_COVERAGE_MISMATCH"} <= {
        issue.code for issue in issues
    }


def test_graph_node_state_contract_rejects_inactive_links_without_ledger_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    ids_path = root / "catalog/ids.yaml"
    ids = yaml.safe_load(ids_path.read_text(encoding="utf-8"))
    allocation = next(item for item in ids["items"] if item["canonical_id"] == "STA-28")
    allocation["status"] = "rejected"
    allocation.pop("history", None)
    ids_path.write_text(yaml.safe_dump(ids, sort_keys=False), encoding="utf-8")
    action_path = root / "reality/actions/act-41-graph-approved-approval-node-outcome.yaml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    action["transition"] = {"from_state_id": "STA-28", "to_state_id": "STA-33"}
    action_path.write_text(yaml.safe_dump(action, sort_keys=False), encoding="utf-8")

    validator = load_validator()
    issues = validator.validate_graph_node_state_contract(root)

    codes = {issue.code for issue in issues}
    assert "RETIRED_SEMANTIC_ID_HISTORY_MISSING" in codes
    assert "INACTIVE_STATE_REFERENCE" in codes


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


def test_derivation_rejects_unrelated_current_contract_and_evidence_chain(tmp_path: Path) -> None:
    """A command validator cannot stand in for prompt size evidence or input."""
    root = write_valid_phase_zero(tmp_path)
    current = semantic_item(
        "CAP-69",
        capability_status="current",
        implementation_status="present",
        output_contract={
            "semantic_type": "CommandValidation",
            "fields": ["valid"],
            "role": "validator",
        },
        evidence_ids=["EVD-105"],
    )
    derived = semantic_item(
        "CAP-30",
        capability_status="derived",
        derivation_id="DRV-30",
        evidence_ids=["EVD-105"],
    )
    write_yaml(
        root / "capabilities/registry.yaml", {"schema_version": "1", "items": [current, derived]}
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-105", "source_kind": "implementation", "reachable": True}],
        },
    )
    write_yaml(
        root / "capabilities/derivations/DRV-30.yaml",
        {
            "id": "DRV-30",
            "status": "admitted",
            "capability_ids": ["CAP-30"],
            "inputs": ["CAP-69"],
            "typed_inputs": {
                "CAP-69": {
                    "semantic_type": "PromptSize",
                    "consumed_fields": ["tokens"],
                    "role": "prompt",
                }
            },
            "algorithm": "deterministically select, tie break, and round",
            "output_type": "PromptSize",
            "unknown_behavior": "unknown",
            "failure_behavior": "fail",
            "freshness": "snapshot",
            "recomputation_behavior": "recompute",
            "implementation_evidence_ids": ["EVD-105"],
            "evidence_ids": ["EVD-105"],
            "limitations": ["bounded"],
            "prohibited_interpretations": ["complete"],
        },
    )
    result = run_validator(root, phase=0)
    assert {
        "DERIVATION_TYPED_INPUT_CONTRACT_MISMATCH",
        "DERIVATION_IMPLEMENTATION_EVIDENCE_CHAIN_INVALID",
    } <= set(issue_codes(result))


def test_partial_gap_rejects_duplicate_normalized_limitations_and_prohibitions(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    duplicate = "Carrier evidence is incomplete."
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    limitations=[duplicate, " carrier evidence is incomplete. "],
                    prohibited_interpretations=[duplicate, "CARRIER EVIDENCE IS INCOMPLETE."],
                    implementation_carrier_bindings=[],
                )
            ],
        },
    )
    result = run_validator(root)
    assert {
        "CAPABILITY_LIMITATIONS_DUPLICATE",
        "CAPABILITY_PROHIBITED_INTERPRETATIONS_DUPLICATE",
    } <= set(issue_codes(result))


def test_partial_gap_rejects_non_action_reversibility_binding(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "EVI-1",
                            "role": "reversibility-action",
                            "semantic_type": "ActionContract",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/evidence/inventory.yaml",
        {"schema_version": "1", "items": [semantic_item("EVI-1", evidence_ids=["EVD-01"])]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "audit-report"}],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_non_permission_authority_binding(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-42",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "EVI-1",
                            "role": "authority-policy",
                            "semantic_type": "PermissionContract",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/evidence/inventory.yaml",
        {"schema_version": "1", "items": [semantic_item("EVI-1", evidence_ids=["EVD-01"])]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "audit-report"}],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_non_usage_telemetry_cost_binding(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-6",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "EVI-1",
                            "role": "usage-telemetry",
                            "semantic_type": "UsageTelemetry",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/evidence/inventory.yaml",
        {"schema_version": "1", "items": [semantic_item("EVI-1", evidence_ids=["EVD-01"])]},
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "audit-report"}],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_binding_semantic_type_mismatch(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ACT-01",
                            "role": "reversibility-action",
                            "semantic_type": "UsageTelemetry",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/actions/ACT-01.yaml", {"id": "ACT-01", "audit_evidence_ids": ["EVD-01"]}
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-01", "source_kind": "audit-report"}],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_typed_carrier_with_unrelated_binding_evidence(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-02"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ENT-1",
                            "role": "entity-input",
                            "semantic_type": "EntityRecord",
                            "evidence_ids": ["EVD-02"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/domain-model.yaml",
        {"schema_version": "1", "items": [semantic_item("ENT-1", evidence_ids=["EVD-01"])]},
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_EVIDENCE_UNSUPPORTED" in issue_codes(result)


def test_partial_unknown_requires_typed_carrier_bindings(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-70",
                    capability_status="unknown",
                    implementation_status="partial",
                    implementation_carrier_bindings=[],
                )
            ],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_UNRESOLVED" in issue_codes(result)


def test_partial_unknown_rejects_absent_carrier(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-70",
                    capability_status="unknown",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ENT-1",
                            "role": "entity-input",
                            "semantic_type": "EntityRecord",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("ENT-1", implementation_status="absent", evidence_ids=["EVD-01"])
            ],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_NON_EXECUTABLE" in issue_codes(result)


def test_partial_gap_rejects_unknown_non_action_carrier(tmp_path: Path) -> None:
    del tmp_path
    validator = load_validator()

    assert (
        validator._carrier_is_executable({"id": "ENT-1", "implementation_status": "unknown"})
        is False
    )


def test_partial_gap_rejects_non_action_carrier_without_implementation_status(
    tmp_path: Path,
) -> None:
    del tmp_path
    validator = load_validator()

    assert validator._carrier_is_executable({"id": "ENT-1"}) is False


def test_partial_gap_rejects_legacy_cost_as_graph_usage_rollup(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("ENT-21", implementation_status="partial", evidence_ids=["EVD-01"])
            ],
        },
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-47",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ENT-21",
                            "role": "graph-usage-rollup",
                            "semantic_type": "UsageTelemetry",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )

    result = run_validator(root)

    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_attempt_entity_as_structured_tool_trace(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("ENT-5", implementation_status="partial", evidence_ids=["EVD-01"])
            ],
        },
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-50",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ENT-5",
                            "role": "structured-tool-trace",
                            "semantic_type": "EvidenceInventory",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )

    result = run_validator(root)

    assert "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID" in issue_codes(result)


def test_partial_gap_rejects_capability_evidence_copied_into_binding(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-99"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ENT-1",
                            "role": "entity-input",
                            "semantic_type": "EntityRecord",
                            "evidence_ids": ["EVD-99"],
                        }
                    ],
                )
            ],
        },
    )
    write_yaml(
        root / "reality/domain-model.yaml",
        {"schema_version": "1", "items": [semantic_item("ENT-1", evidence_ids=[])]},
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_CARRIER_EVIDENCE_UNSUPPORTED" in issue_codes(result)


def test_partial_gap_rejects_absence_contract_as_implementation_carrier(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    absent_action = semantic_item(
        "ACT-15",
        implementation_status="absent",
        executable=False,
        audit_evidence_ids=["EVD-01"],
    )
    write_yaml(root / "reality/actions/act-15.yaml", absent_action)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-21",
                    capability_status="gap",
                    implementation_status="partial",
                    evidence_ids=["EVD-01"],
                    absence_contract_ids=["ACT-15"],
                    implementation_carrier_bindings=[
                        {
                            "id": "ACT-15",
                            "role": "action-contract",
                            "semantic_type": "ActionContract",
                            "evidence_ids": ["EVD-01"],
                        }
                    ],
                )
            ],
        },
    )
    result = run_validator(root)
    assert {
        "GAP_PARTIAL_CARRIER_NON_EXECUTABLE",
        "GAP_PARTIAL_ABSENCE_CARRIER_OVERLAP",
    } <= set(issue_codes(result))


def test_absent_gap_rejects_executable_absence_contract(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/actions/act-1.yaml",
        semantic_item(
            "ACT-1",
            implementation_status="present",
            executable=True,
            audit_evidence_ids=["EVD-01"],
        ),
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "CAP-43",
                    capability_status="gap",
                    implementation_status="absent",
                    absence_basis="No implementation exists.",
                    absence_contract_ids=["ACT-1"],
                    implementation_carrier_ids=[],
                )
            ],
        },
    )
    result = run_validator(root)
    assert "GAP_PARTIAL_ABSENCE_CARRIER_INVALID" in issue_codes(result)


def test_current_and_derived_capabilities_require_output_contracts(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("CAP-1", capability_status="current"),
                semantic_item("CAP-2", capability_status="derived"),
            ],
        },
    )
    result = run_validator(root)
    assert issue_codes(result).count("CAPABILITY_OUTPUT_CONTRACT_INVALID") == 2


def _admitted_derivation_fixture(
    root: Path, *, output_contract: dict[str, object], bindings: list[dict[str, object]]
) -> None:
    current = semantic_item(
        "CAP-01",
        capability_status="current",
        implementation_status="present",
        test_status="exercised",
        documentation_status="documented",
        output_contract={"semantic_type": "Input", "fields": ["value"]},
        evidence_ids=["EVD-01", "EVD-02"],
    )
    derived = semantic_item(
        "CAP-02",
        capability_status="derived",
        derivation_id="DRV-01",
        output_contract=output_contract,
        evidence_ids=["EVD-03"],
    )
    write_yaml(
        root / "capabilities/registry.yaml", {"schema_version": "1", "items": [current, derived]}
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {"id": "EVD-01", "source_kind": "implementation", "reachable": True},
                {
                    "id": "EVD-02",
                    "source_kind": "test",
                    "reachable": True,
                    "test_status": "exercised",
                },
                {"id": "EVD-03", "source_kind": "implementation", "reachable": True},
            ],
        },
    )
    write_yaml(
        root / "capabilities/derivations/DRV-01.yaml",
        {
            "id": "DRV-01",
            "status": "admitted",
            "capability_ids": ["CAP-02"],
            "inputs": ["CAP-01"],
            "typed_inputs": {
                "CAP-01": {"semantic_type": "Input", "consumed_fields": ["value"], "role": "input"}
            },
            "algorithm": "deterministically select, tie break, and round",
            "output_type": "Output",
            "produced_fields": ["result"],
            "unknown_behavior": "unknown",
            "failure_behavior": "fail",
            "freshness": "snapshot",
            "recomputation_behavior": "recompute",
            "implementation_evidence_ids": ["EVD-03"],
            "evidence_bindings": bindings,
            "limitations": ["bounded"],
            "prohibited_interpretations": ["complete"],
        },
    )


def test_derivation_rejects_unrelated_implementation_locator(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    _admitted_derivation_fixture(
        root,
        output_contract={"semantic_type": "Output", "fields": ["result"]},
        bindings=[
            {
                "id": "EVD-03",
                "role": "pure-projection-implementation",
                "path": "other.py",
                "symbol": "other",
                "semantic_type": "Output",
            }
        ],
    )
    result = run_validator(root)
    assert "DERIVATION_EVIDENCE_BINDING_LOCATOR_INVALID" in issue_codes(result)


def test_derivation_rejects_incompatible_output_contract(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    _admitted_derivation_fixture(
        root,
        output_contract={"semantic_type": "Different", "fields": ["other"]},
        bindings=[
            {
                "id": "EVD-03",
                "role": "pure-projection-implementation",
                "path": "implementation.py",
                "symbol": "project",
                "semantic_type": "Output",
            }
        ],
    )
    result = run_validator(root)
    assert "DERIVATION_OUTPUT_CONTRACT_MISMATCH" in issue_codes(result)


def test_derivation_rejects_output_evidence_without_derivation_binding(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    _admitted_derivation_fixture(
        root, output_contract={"semantic_type": "Output", "fields": ["result"]}, bindings=[]
    )
    result = run_validator(root)
    assert "DERIVATION_EVIDENCE_BINDING_MISSING" in issue_codes(result)


def test_derivation_rejects_real_patch_validator_as_prompt_size_implementation(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    _admitted_derivation_fixture(
        root,
        output_contract={"semantic_type": "PromptSize", "fields": ["bytes"]},
        bindings=[
            {
                "id": "EVD-105",
                "role": "pure-projection-implementation",
                "path": "src/orchestrator/graph/patch_validator.py",
                "symbol": "validate_patch",
                "semantic_type": "PromptSize",
            }
        ],
    )
    evidence = yaml.safe_load((root / "catalog/evidence.yaml").read_text(encoding="utf-8"))
    evidence["items"][2].update(
        {
            "id": "EVD-105",
            "path": "src/orchestrator/graph/patch_validator.py",
            "symbol": "validate_patch",
            "supported_semantic_types": ["GraphPatchValidationResult"],
        }
    )
    write_yaml(root / "catalog/evidence.yaml", evidence)
    derivation = yaml.safe_load(
        (root / "capabilities/derivations/DRV-01.yaml").read_text(encoding="utf-8")
    )
    derivation["implementation_evidence_ids"] = ["EVD-105"]
    derivation["output_type"] = "PromptSize"
    derivation["produced_fields"] = ["bytes"]
    write_yaml(root / "capabilities/derivations/DRV-01.yaml", derivation)
    registry = yaml.safe_load((root / "capabilities/registry.yaml").read_text(encoding="utf-8"))
    registry["items"][1]["evidence_ids"] = ["EVD-105"]
    write_yaml(root / "capabilities/registry.yaml", registry)
    result = run_validator(root)
    assert "DERIVATION_IMPLEMENTATION_SEMANTIC_UNSUPPORTED" in issue_codes(result)


def test_derivation_rejects_evidence_copied_to_output_without_canonical_semantic_support(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    _admitted_derivation_fixture(
        root,
        output_contract={"semantic_type": "Output", "fields": ["result"]},
        bindings=[
            {
                "id": "EVD-03",
                "role": "pure-projection-implementation",
                "path": "implementation.py",
                "symbol": "project",
                "semantic_type": "Output",
            }
        ],
    )
    evidence = yaml.safe_load((root / "catalog/evidence.yaml").read_text(encoding="utf-8"))
    evidence["items"][2].update(
        {
            "path": "implementation.py",
            "symbol": "project",
            "supported_semantic_types": ["DifferentOutput"],
        }
    )
    write_yaml(root / "catalog/evidence.yaml", evidence)
    result = run_validator(root)
    assert "DERIVATION_IMPLEMENTATION_SEMANTIC_UNSUPPORTED" in issue_codes(result)


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


def test_validator_rejects_duplicate_id_allocation_ledger_entries(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/ids.yaml",
        {
            "schema_version": "1",
            "items": [{"canonical_id": "EVD-113"}, {"canonical_id": "EVD-113"}],
        },
    )
    result = run_validator(root, phase=0)
    assert "ID_ALLOCATION_DUPLICATE" in issue_codes(result)


def test_validator_rejects_direct_evidence_missing_each_required_locator(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [{"path": "direct.py", "sha256": "0" * 64, "audited_at": "now"}],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "provenance_role": "direct",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "direct.py",
                    "symbol": "subject",
                },
                {
                    "id": "EVD-02",
                    "source_kind": "implementation",
                    "path": "direct.py",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "direct.py",
                },
                {
                    "id": "EVD-03",
                    "source_kind": "implementation",
                    "path": "direct.py",
                    "symbol": "subject",
                    "snapshot_path": "direct.py",
                },
                {
                    "id": "EVD-04",
                    "source_kind": "implementation",
                    "path": "direct.py",
                    "symbol": "subject",
                    "snapshot_id": "snapshot-test",
                },
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert issue_codes(result).count("DIRECT_EVIDENCE_FIELD_MISSING") == 4
    assert "path" in result.stderr
    assert "symbol" in result.stderr
    assert "snapshot_id" in result.stderr
    assert "snapshot_path" in result.stderr


def test_validator_rejects_direct_evidence_path_mismatch_and_undeclared_snapshot_path(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [{"path": "declared.py", "sha256": "0" * 64, "audited_at": "now"}],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "test",
                    "path": "actual.py",
                    "symbol": "test_subject",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "undeclared.py",
                },
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "DIRECT_EVIDENCE_PATH_MISMATCH" in issue_codes(result)
    assert "EVIDENCE_SNAPSHOT_PATH_UNRESOLVED" in issue_codes(result)


def test_phase_one_snapshot_requires_coverage_counts_and_files(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    required_source = root.parents[1] / "src/orchestrator"
    required_source.mkdir(parents=True)
    (required_source / "required.py").write_text("x = 1\n", encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "phase1",
                "include_patterns": [
                    "src/orchestrator/**/*.py",
                    "tests/**/*.py",
                    "ui/src/**/*.ts",
                    "ui/src/**/*.tsx",
                    "docs/jtbd/jobs.md",
                    "docs/jtbd/journeys.md",
                    "docs/jtbd/decision-information.md",
                    "docs/jtbd/information-architecture.md",
                    "docs/jtbd/evaluation-rubric.md",
                    "docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md",
                    "research/ui-foundation/agent-reports/*.md",
                    "research/ui-foundation/tools/validate.py",
                    "tests/integration/test_ui_foundation_tools.py",
                ],
                "expected_count": 0,
                "covered_count": 0,
                "files": [],
            },
            "items": [],
        },
    )

    result = run_validator(root, phase=1)

    assert "SOURCE_SNAPSHOT_COUNT_MISMATCH" in issue_codes(result)
    assert "SOURCE_SNAPSHOT_COVERAGE_MISSING" in issue_codes(result)


def test_phase_one_snapshot_requires_every_coverage_pattern(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "phase1",
                "include_patterns": [],
                "expected_count": 0,
                "covered_count": 0,
                "files": [],
            },
            "items": [],
        },
    )

    result = run_validator(root, phase=1)

    assert "SOURCE_SNAPSHOT_PATTERN_MISSING" in issue_codes(result)


def test_phase_one_rejects_invalid_q7_coverage_attestation(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/questions.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "Q-7",
                    "status": "resolved",
                    "blocking": False,
                    "decisive_evidence_ids": ["EVD-113"],
                },
            ],
        },
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-113", "source_kind": "audit-report"}],
        },
    )

    result = run_validator(root, phase=1)

    assert "Q7_COVERAGE_ATTESTATION_INVALID" in issue_codes(result)


def test_validator_rejects_exercised_semantic_without_direct_test_evidence(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "ENT-01",
                    test_status="exercised",
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
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "test_status": "exercised",
                }
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "EXERCISED_DIRECT_TEST_EVIDENCE_MISSING" in issue_codes(result)


def test_validator_rejects_current_semantic_without_direct_reachable_implementation(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "reality/domain-model.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item(
                    "ENT-01",
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
            "items": [{"id": "EVD-01", "source_kind": "audit-report", "reachable": True}],
        },
    )

    result = run_validator(root, phase=0)

    assert "CURRENT_DIRECT_IMPLEMENTATION_EVIDENCE_MISSING" in issue_codes(result)


def test_phase_one_rejects_missing_or_malformed_snapshot_coverage_fields(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    for field in ("include_patterns", "files", "expected_count", "covered_count"):
        snapshot: dict[str, object] = {
            "id": "phase1",
            "include_patterns": [],
            "files": [],
            "expected_count": 0,
            "covered_count": 0,
        }
        snapshot.pop(field)
        write_yaml(
            root / "catalog/evidence.yaml",
            {"schema_version": "1", "snapshot": snapshot, "items": []},
        )

        result = run_validator(root, phase=1)

        assert "SOURCE_SNAPSHOT_COVERAGE_INVALID" in issue_codes(result), field


def test_validator_rejects_zero_padded_allocation_suffix_collision(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/ids.yaml",
        {
            "schema_version": "1",
            "items": [{"canonical_id": "EVD-01"}, {"canonical_id": "EVD-1"}],
        },
    )

    result = run_validator(root, phase=0)

    assert "ID_ALLOCATION_SUFFIX_DUPLICATE" in issue_codes(result)


def test_validator_rejects_synthesis_evidence_with_missing_markdown_anchor(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    report = root.parents[1] / "research/ui-foundation/agent-reports/03-workflow-state.md"
    report.parent.mkdir(parents=True)
    report.write_text("# Workflow state\n\n## Key findings\n", encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {
                        "path": "research/ui-foundation/agent-reports/03-workflow-state.md",
                        "sha256": "0" * 64,
                        "audited_at": "now",
                    }
                ],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "provenance_role": "synthesis",
                    "source_label": "03-workflow-state.md#Key findings",
                    "path": "research/ui-foundation/agent-reports/03-workflow-state.md#missing",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "research/ui-foundation/agent-reports/03-workflow-state.md",
                }
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "SYNTHESIS_REPORT_ANCHOR_UNRESOLVED" in issue_codes(result)


def test_validator_rejects_synthesis_evidence_in_wrong_source_label_report(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    repository = root.parents[1]
    for name in ("03-workflow-state.md", "04-api-actions-authority.md"):
        report = repository / "research/ui-foundation/agent-reports" / name
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# Report\n\n## Key findings\n", encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {
                        "path": "research/ui-foundation/agent-reports/03-workflow-state.md",
                        "sha256": "0" * 64,
                        "audited_at": "now",
                    },
                    {
                        "path": "research/ui-foundation/agent-reports/04-api-actions-authority.md",
                        "sha256": "0" * 64,
                        "audited_at": "now",
                    },
                ],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "provenance_role": "synthesis",
                    "source_label": "03-workflow-state.md#Key findings",
                    "path": "research/ui-foundation/agent-reports/04-api-actions-authority.md#key-findings",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "research/ui-foundation/agent-reports/04-api-actions-authority.md",
                }
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "SYNTHESIS_REPORT_SOURCE_LABEL_MISMATCH" in issue_codes(result)


def test_validator_accepts_synthesis_evidence_with_specific_report_anchor(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    report = root.parents[1] / "research/ui-foundation/agent-reports/03-workflow-state.md"
    report.parent.mkdir(parents=True)
    report.write_text(
        "# Workflow state\n\n## State carriers and legal transitions\n", encoding="utf-8"
    )
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [
                    {
                        "path": "research/ui-foundation/agent-reports/03-workflow-state.md",
                        "sha256": "0" * 64,
                        "audited_at": "now",
                    }
                ],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "provenance_role": "synthesis",
                    "source_label": "03-workflow-state.md#state-carriers-and-legal-transitions",
                    "path": "research/ui-foundation/agent-reports/03-workflow-state.md#state-carriers-and-legal-transitions",
                    "symbol": "WF-run-status",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "research/ui-foundation/agent-reports/03-workflow-state.md",
                }
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "SYNTHESIS_REPORT_ANCHOR_UNRESOLVED" not in issue_codes(result)
    assert "SYNTHESIS_REPORT_SOURCE_LABEL_MISMATCH" not in issue_codes(result)


def test_validator_rejects_synthesis_evidence_missing_each_required_field(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    report_path = "research/ui-foundation/agent-reports/03-workflow-state.md"
    report = root.parents[1] / report_path
    report.parent.mkdir(parents=True)
    report.write_text("# Workflow\n\n## Key findings\n", encoding="utf-8")
    items = []
    for index, field in enumerate(
        ("path", "symbol", "source_label", "snapshot_id", "snapshot_path")
    ):
        item: dict[str, object] = {
            "id": f"EVD-{index + 1:02}",
            "source_kind": "audit-report",
            "provenance_role": "synthesis",
            "path": f"{report_path}#key-findings",
            "symbol": "finding",
            "source_label": "03-workflow-state.md#key-findings",
            "snapshot_id": "snapshot-test",
            "snapshot_path": report_path,
        }
        item.pop(field)
        items.append(item)
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [{"path": report_path, "sha256": "0" * 64, "audited_at": "now"}],
            },
            "items": items,
        },
    )

    result = run_validator(root, phase=0)

    assert issue_codes(result).count("SYNTHESIS_EVIDENCE_FIELD_MISSING") == 5
    for field in ("path", "symbol", "source_label", "snapshot_id", "snapshot_path"):
        assert field in result.stderr


def test_validator_rejects_synthesis_evidence_path_snapshot_mismatch(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    report_path = "research/ui-foundation/agent-reports/03-workflow-state.md"
    report = root.parents[1] / report_path
    report.parent.mkdir(parents=True)
    report.write_text("# Workflow\n\n## Key findings\n", encoding="utf-8")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {
                "id": "snapshot-test",
                "files": [{"path": report_path, "sha256": "0" * 64, "audited_at": "now"}],
            },
            "items": [
                {
                    "id": "EVD-01",
                    "source_kind": "audit-report",
                    "provenance_role": "synthesis",
                    "path": f"{report_path}#key-findings",
                    "symbol": "finding",
                    "source_label": "03-workflow-state.md#key-findings",
                    "snapshot_id": "snapshot-test",
                    "snapshot_path": "research/ui-foundation/agent-reports/other.md",
                }
            ],
        },
    )

    result = run_validator(root, phase=0)

    assert "SYNTHESIS_EVIDENCE_SNAPSHOT_PATH_MISMATCH" in issue_codes(result)


def test_phase_two_requires_exactly_one_registry_status_per_scope_demand(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "key": "claim.one",
                    "source": "docs/jtbd/jobs.md",
                    "source_anchor": "J1",
                    "demand_type": "claim",
                    "label": "One",
                    "audit_owner": "workflow-state",
                    "downstream_jobs": ["J1"],
                    "blocking": True,
                },
                {
                    "key": "action.two",
                    "source": "docs/jtbd/decision-information.md",
                    "source_anchor": "Action",
                    "demand_type": "implemented-action-candidate",
                    "label": "Two",
                    "audit_owner": "api-actions-authority",
                    "downstream_jobs": ["J1"],
                    "blocking": True,
                },
            ],
        },
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                semantic_item("CAP-01", scope_demand_key="claim.one", capability_status="gap")
            ],
        },
    )

    result = run_validator(root, phase=2)

    assert "CAPABILITY_DEMAND_COVERAGE_MISSING" in issue_codes(result)


def test_phase_two_rejects_duplicate_scope_status_and_forbidden_current_manifest(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    demand = {
        "key": "decisions.steer-context",
        "source": "docs/jtbd/decision-information.md",
        "source_anchor": "Action",
        "demand_type": "absent-intervention",
        "label": "Steer with new context",
        "audit_owner": "api-actions-authority",
        "downstream_jobs": ["J6"],
        "blocking": True,
    }
    write_yaml(root / "catalog/scope.yaml", {"schema_version": "1", "items": [demand]})
    current = semantic_item(
        "CAP-01",
        scope_demand_key="decisions.steer-context",
        implementation_status="present",
        test_status="exercised",
        documentation_status="documented",
        capability_status="current",
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {"schema_version": "1", "items": [current, current | {"id": "CAP-02"}]},
    )

    result = run_validator(root, phase=2)

    assert "CAPABILITY_DEMAND_STATUS_DUPLICATE" in issue_codes(result)
    assert "FORBIDDEN_CURRENT_MANIFEST" in issue_codes(result)


def test_committed_phase_two_registry_preserves_adjudicated_capability_boundaries() -> None:
    result = run_validator(REPO_ROOT / "research/ui-foundation", phase=2)

    assert result.returncode == 0, result.stderr
    claims = yaml.safe_load(
        (REPO_ROOT / "research/ui-foundation/catalog/claims.yaml").read_text(encoding="utf-8")
    )
    assert claims["classification_counts"] == {
        "current": 1,
        "derived": 0,
        "proposed": 25,
        "gap": 49,
        "unknown": 57,
    }
    assert claims["derivation_count"] == 0


def test_current_variant_contract_rejects_missing_evidence_for_one_asserted_branch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    cap69["current_command_identities"] = ["graph.patch-validator"]
    cap69["evidence_ids"].remove("EVD-106")
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CURRENT_OUTPUT_VARIANT_EVIDENCE_MISSING" in issue_codes(result)


def test_current_variant_contract_rejects_broad_definition_with_narrow_output_contract(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap86 = next(item for item in registry["items"] if item["id"] == "CAP-86")
    cap86.update(
        {
            "implementation_status": "present",
            "test_status": "exercised",
            "capability_status": "current",
            "current_command_identities": ["graph.record-decision"],
            "output_contract": {
                "semantic_type": "RecordGraphDecisionResponse",
                "fields": ["run_id", "events", "decision_view"],
                "role": "graph-decision-result",
                "command_identity": "graph.record-decision",
            },
            "asserted_output_variant_types": [
                "RecordGraphDecisionResponse",
                "PatchValidationResult",
            ],
        }
    )
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_VARIANT_CONTRACT_INVALID" in issue_codes(result)


def test_current_validator_result_rejects_decision_and_attempt_variants(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    cap69["current_command_identities"] = ["graph.patch-validator"]
    cap69["evidence_ids"] += ["EVD-111", "EVD-112"]
    cap69["asserted_output_variant_types"] += [
        "RecordGraphDecisionResponse",
        "GraphPatchAttemptsResponse",
    ]
    cap69["output_contract"]["variants"] += [
        {
            "semantic_type": "RecordGraphDecisionResponse",
            "fields": ["run_id", "graph_position", "events", "decision_view"],
            "role": "graph-decision-response",
            "command_identity": "graph.record-decision",
        },
        {
            "semantic_type": "GraphPatchAttemptsResponse",
            "fields": ["run_id", "graph_position", "attempts"],
            "role": "graph-patch-attempt-readback",
            "command_identity": "graph.patch-attempt-readback",
        },
    ]
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CURRENT_OUTPUT_VARIANT_DEMAND_MISMATCH" in issue_codes(result)


def test_current_rejects_unrelated_command_evidence_for_a_variant(tmp_path: Path) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    cap69["current_command_identities"] = ["graph.record-decision"]
    cap69["output_contract"]["variants"][0]["command_identity"] = "graph.record-decision"
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CURRENT_OUTPUT_VARIANT_COMMAND_EVIDENCE_MISSING" in issue_codes(result)


def test_current_rejects_copied_output_contract_for_a_distinct_demand(tmp_path: Path) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    cap86 = next(item for item in registry["items"] if item["id"] == "CAP-86")
    cap86.update(
        {
            "implementation_status": "present",
            "test_status": "exercised",
            "capability_status": "current",
            "output_contract": cap69["output_contract"],
            "asserted_output_variant_types": cap69["asserted_output_variant_types"],
        }
    )
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CURRENT_OUTPUT_CONTRACT_COPIED_CROSS_DEMAND" in issue_codes(result)


def test_current_approve_gate_patch_requires_human_patch_approval_and_defer_commands(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap86 = next(item for item in registry["items"] if item["id"] == "CAP-86")
    cap86.update(
        {
            "implementation_status": "present",
            "test_status": "exercised",
            "capability_status": "current",
            "output_contract": {
                "semantic_type": "RecordGraphDecisionResponse",
                "fields": ["run_id", "graph_position", "events", "decision_view"],
                "role": "graph-decision-response",
                "command_identity": "graph.record-decision",
            },
            "asserted_output_variant_types": ["RecordGraphDecisionResponse"],
        }
    )
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CURRENT_REQUIRED_COMMAND_EVIDENCE_MISSING" in issue_codes(result)


def test_current_variant_contract_requires_asserted_variants_for_narrow_cap69(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    cap69.pop("asserted_output_variant_types")
    cap69["output_contract"]["variants"] = cap69["output_contract"]["variants"][:1]
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_VARIANT_CONTRACT_INVALID" in issue_codes(result)


def test_current_variant_contract_requires_asserted_variants_for_narrow_cap86(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap86 = next(item for item in registry["items"] if item["id"] == "CAP-86")
    cap86.update(
        {
            "implementation_status": "present",
            "test_status": "exercised",
            "capability_status": "current",
            "current_command_identities": ["graph.record-decision"],
            "output_contract": {
                "semantic_type": "RecordGraphDecisionResponse",
                "fields": ["run_id", "graph_position", "events", "decision_view"],
                "role": "graph-decision-response",
                "command_identity": "graph.record-decision",
            },
        }
    )
    cap86.pop("asserted_output_variant_types", None)
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_VARIANT_CONTRACT_INVALID" in issue_codes(result)


def test_current_variant_contract_rejects_duplicate_contract_variant_type(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    variants = cap69["output_contract"]["variants"]
    variants.append(dict(variants[0]))
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_VARIANT_CONTRACT_INVALID" in issue_codes(result)


def test_current_variant_contract_rejects_duplicate_asserted_variant_type(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    asserted = cap69["asserted_output_variant_types"]
    asserted.append(asserted[0])
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_VARIANT_CONTRACT_INVALID" in issue_codes(result)


def test_current_variant_contract_rejects_duplicate_variant_field(
    tmp_path: Path,
) -> None:
    root = tmp_path / "research/ui-foundation"
    shutil.copytree(REPO_ROOT / "research/ui-foundation", root)
    registry_path = root / "capabilities/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    cap69 = next(item for item in registry["items"] if item["id"] == "CAP-69")
    fields = cap69["output_contract"]["variants"][0]["fields"]
    fields.append(fields[0])
    write_yaml(registry_path, registry)

    result = run_validator(root, phase=2)

    assert "CAPABILITY_OUTPUT_CONTRACT_INVALID" in issue_codes(result)


def test_phase_two_validates_superseded_derivation_ledger_bindings(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    append_yaml_item(
        root / "catalog/ids.yaml",
        {
            "namespace": "DRV",
            "canonical_id": "DRV-1",
            "provisional_key": "historical-output",
            "title": "Historical output",
            "status": "superseded",
            "output_capability_ids": ["CAP-404"],
        },
    )
    result = run_validator(root)
    assert "DERIVATION_LEDGER_SUPERSEDED_INVALID" in issue_codes(result)


def phase_two_demand(key: str, label: str = "Demand-specific label") -> dict[str, object]:
    return {
        "key": key,
        "source": "docs/jtbd/jobs.md",
        "source_anchor": "J1",
        "demand_type": "claim",
        "label": label,
        "audit_owner": "workflow-state",
        "downstream_jobs": ["J1"],
        "blocking": True,
    }


def classified_capability(identifier: str, key: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "title": "Demand-specific capability",
        "definition": f"Demand-specific definition for {key}.",
        "implementation_status": "absent",
        "test_status": "unexercised",
        "documentation_status": "documented",
        "capability_status": "gap",
        "confidence_basis": f"Direct adjudication for {key}.",
        "limitations": [f"{key} remains unavailable."],
        "prohibited_interpretations": [f"Do not present {key} as available."],
        "scope_demand_key": key,
        "classification_basis": "No reachable implementation evidence establishes this demand.",
    }
    return semantic_item(identifier, **(values | overrides))


def write_cap_allocation(root: Path, identifier: str, key: str) -> None:
    append_yaml_item(
        root / "catalog/ids.yaml",
        {
            "namespace": "CAP",
            "provisional_key": key,
            "title": "Demand-specific capability",
            "status": "active",
            "canonical_id": identifier,
        },
    )


def test_phase_two_rejects_duplicate_scope_keys_before_coverage_set_conversion(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")] * 2},
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {"schema_version": "1", "items": [classified_capability("CAP-1", "claim.one")]},
    )
    write_cap_allocation(root, "CAP-1", "claim.one")

    result = run_validator(root)

    assert "SCOPE_DEMAND_KEY_DUPLICATE" in issue_codes(result)


def test_phase_two_rejects_extra_registry_records_and_unbound_or_placeholder_allocations(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    write_yaml(
        root / "capabilities/registry.yaml",
        {
            "schema_version": "1",
            "items": [
                classified_capability("CAP-1", "claim.one"),
                classified_capability("CAP-2", "claim.extra"),
            ],
        },
    )
    write_cap_allocation(root, "CAP-1", "scope-demand-001")
    write_cap_allocation(root, "CAP-2", "claim.extra")

    result = run_validator(root)

    assert {
        "CAPABILITY_DEMAND_EXTRA",
        "CAPABILITY_ALLOCATION_BINDING_INVALID",
        "CAPABILITY_ALLOCATION_PLACEHOLDER",
    } <= set(issue_codes(result))


def test_phase_two_rejects_generic_or_incomplete_capability_adjudication(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability("CAP-1", "claim.one")
    item.update(
        {
            "title": "CAP-1",
            "definition": "Definition",
            "limitations": [],
            "prohibited_interpretations": [],
        }
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_cap_allocation(root, "CAP-1", "claim.one")

    result = run_validator(root)

    assert "CAPABILITY_ADJUDICATION_GENERIC" in issue_codes(result)
    assert "CAPABILITY_ORTHOGONAL_STATUS_MISSING" in issue_codes(result)


def test_phase_two_rejects_known_generic_unknown_fallback_template(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability(
        "CAP-1",
        "claim.one",
        capability_status="unknown",
        implementation_status="partial",
        definition=("Demand cannot be established across the audited Phase 1 carrier boundaries."),
        implementation_carrier_bindings=[],
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_cap_allocation(root, "CAP-1", "claim.one")
    result = run_validator(root)
    assert "CAPABILITY_UNKNOWN_FALLBACK_GENERIC" in issue_codes(result)


def test_phase_two_rejects_generic_gap_template_and_duplicate_gap_definitions(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {
            "schema_version": "1",
            "items": [phase_two_demand("claim.one"), phase_two_demand("claim.two")],
        },
    )
    generic = "Demand is a source demand with audited partial or absent Phase 1 evidence; it is not an implemented aggregate or projection."
    first = classified_capability("CAP-1", "claim.one", definition=generic)
    second = classified_capability("CAP-2", "claim.two", definition=generic)
    write_yaml(
        root / "capabilities/registry.yaml", {"schema_version": "1", "items": [first, second]}
    )
    write_cap_allocation(root, "CAP-1", "claim.one")
    write_cap_allocation(root, "CAP-2", "claim.two")

    result = run_validator(root)

    assert {
        "CAPABILITY_GAP_FALLBACK_GENERIC",
        "CAPABILITY_GAP_DEFINITION_DUPLICATE",
    } <= set(issue_codes(result))


def test_committed_phase_two_gap_definitions_are_individualized_and_unique() -> None:
    registry = yaml.safe_load(
        (REPO_ROOT / "research/ui-foundation/capabilities/registry.yaml").read_text(
            encoding="utf-8"
        )
    )
    gap_definitions = [
        " ".join(item["definition"].split())
        for item in registry["items"]
        if item["capability_status"] == "gap"
    ]

    assert len(gap_definitions) == 49
    assert len(gap_definitions) == len(set(gap_definitions))
    assert all(
        "source demand with audited partial or absent" not in definition
        for definition in gap_definitions
    )


def test_phase_two_current_requires_direct_reachable_implementation_and_direct_exercised_test(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability(
        "CAP-1",
        "claim.one",
        implementation_status="partial",
        test_status="unknown",
        capability_status="current",
        evidence_ids=["EVD-1", "EVD-2"],
        question_ids=["Q-1"],
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_cap_allocation(root, "CAP-1", "claim.one")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [
                {"id": "EVD-1", "source_kind": "persisted-record", "reachable": True},
                {
                    "id": "EVD-2",
                    "source_kind": "audit-report",
                    "reachable": True,
                    "test_status": "exercised",
                },
            ],
        },
    )
    write_yaml(
        root / "catalog/questions.yaml",
        {
            "schema_version": "1",
            "items": [
                {
                    "id": "Q-1",
                    "blocking": True,
                    "status": "open",
                    "affected_ids": ["CAP-1"],
                }
            ],
        },
    )

    result = run_validator(root)

    assert {
        "CURRENT_DIRECT_IMPLEMENTATION_EVIDENCE_MISSING",
        "CURRENT_DIRECT_TEST_EVIDENCE_MISSING",
        "CURRENT_STATUS_INCONSISTENT",
        "CURRENT_QUESTION_UNRESOLVED",
    } <= set(issue_codes(result))


def test_phase_two_rejects_incomplete_or_non_bidirectional_derivation_contract(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability(
        "CAP-1", "claim.one", capability_status="derived", derivation_id="DRV-1"
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_cap_allocation(root, "CAP-1", "claim.one")
    write_yaml(
        root / "capabilities/derivations/DRV-1.yaml",
        {
            "id": "DRV-1",
            "status": "admitted",
            "capability_ids": ["CAP-2"],
            "inputs": ["CAP-9"],
            "algorithm": "Combine values.",
            "output_type": "Result",
            "unknown_behavior": "Unknown on missing input.",
            "failure_behavior": "Reject malformed input.",
            "freshness": "At source position.",
            "recomputation_behavior": "On source change.",
            "implementation_evidence_ids": ["EVD-1"],
            "limitations": ["Limited."],
            "prohibited_interpretations": ["Not causal."],
        },
    )

    result = run_validator(root)

    assert {
        "DERIVATION_TYPED_INPUTS_MISSING",
        "DERIVATION_CAPABILITY_BACKLINK_MISSING",
        "DERIVATION_CAPABILITY_LINK_UNRESOLVED",
        "DERIVATION_ALGORITHM_INCOMPLETE",
    } <= set(issue_codes(result))


def test_phase_two_rejects_false_absence_and_unlinked_claimed_uncertainty(tmp_path: Path) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability(
        "CAP-1",
        "claim.one",
        classification_basis="Partial reachable implementation exists, but a blocking conflict remains.",
        evidence_ids=["EVD-1"],
    )
    write_yaml(root / "capabilities/registry.yaml", {"schema_version": "1", "items": [item]})
    write_cap_allocation(root, "CAP-1", "claim.one")
    write_yaml(
        root / "catalog/evidence.yaml",
        {
            "schema_version": "1",
            "snapshot": {"id": "snapshot-test", "files": []},
            "items": [{"id": "EVD-1", "source_kind": "implementation", "reachable": True}],
        },
    )

    result = run_validator(root)

    assert "CAPABILITY_FALSE_ABSENCE" in issue_codes(result)
    assert "CAPABILITY_BASIS_LINK_MISSING" in issue_codes(result)


def test_phase_two_rejects_stale_completion_metadata_and_generated_projections(
    tmp_path: Path,
) -> None:
    root = write_valid_phase_zero(tmp_path)
    write_yaml(
        root / "catalog/scope.yaml",
        {"schema_version": "1", "items": [phase_two_demand("claim.one")]},
    )
    item = classified_capability("CAP-1", "claim.one")
    write_yaml(
        root / "capabilities/registry.yaml",
        {"schema_version": "1", "phase_status": "complete", "completion_phase": 2, "items": [item]},
    )
    write_cap_allocation(root, "CAP-1", "claim.one")
    write_yaml(
        root / "catalog/claims.yaml",
        {
            "schema_version": "1",
            "phase_status": "complete",
            "completion_phase": 2,
            "scope_demand_count": 99,
            "classification_counts": {"gap": 99},
            "items": [],
        },
    )
    (root / "capabilities/gaps.md").write_text("stale\n", encoding="utf-8")
    (root / "status.md").write_text("stale\n", encoding="utf-8")

    result = run_validator(root)

    assert {
        "PHASE_TWO_METADATA_MISMATCH",
        "PHASE_TWO_CLAIMS_PROJECTION_STALE",
        "PHASE_TWO_GAPS_PROJECTION_STALE",
        "PHASE_TWO_STATUS_PROJECTION_STALE",
    } <= set(issue_codes(result))
