from __future__ import annotations

from typing import Any

import pytest

from orchestrator.graph import PLANNER_OPS, PatchEnvelope, initial_projection, validate_patch
from orchestrator.graph_runtime import (
    HORIZON_REGION_PURPOSES,
    horizon_region_templates,
    instantiate_horizon_template,
)


def test_horizon_templates_include_required_purposes_with_allowed_ops() -> None:
    templates = horizon_region_templates()

    assert [template["purpose"] for template in templates] == list(HORIZON_REGION_PURPOSES)
    assert set(HORIZON_REGION_PURPOSES) == {
        "discovery_region",
        "implementation_region",
        "validation_region",
        "gap_analysis_region",
        "corrective_work_region",
        "final_invariant_region",
    }
    for template in templates:
        assert template["description"]
        assert template["expected_successor_readiness"]
        assert template["ops"]
        assert all(op["op"] in PLANNER_OPS for op in template["ops"])


@pytest.mark.parametrize(
    "purpose",
    [
        "implementation_region",
        "validation_region",
        "gap_analysis_region",
        "corrective_work_region",
        "final_invariant_region",
    ],
)
def test_instantiated_horizon_templates_validate_as_planner_patches(purpose: str) -> None:
    template = instantiate_horizon_template(
        purpose,
        region_id=f"region-{purpose}",
        candidate_id=f"candidate-{purpose}",
    )
    if purpose == "final_invariant_region":
        _bind_test_check_command(template["ops"])
    envelope = _planner_envelope(purpose, template["ops"])

    result = validate_patch(
        envelope,
        current_position=0,
        events_since_base=[],
        projection=initial_projection(),
        actor_role="planner",
    )

    assert result.accepted is True


def test_unknown_horizon_template_purpose_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown horizon region template purpose"):
        instantiate_horizon_template("unknown_region")


def test_gap_template_names_canonical_verifier_evidence_port() -> None:
    template = instantiate_horizon_template("gap_analysis_region")

    evidence_input = template["canonical_inputs"]["verification_evidence"]
    assert evidence_input["from_port"] == "verification_report"
    assert evidence_input["accepted_record_selector"] == {
        "record_kinds": ["verification", "check_result"]
    }


def test_final_invariant_template_declares_runtime_command_binding() -> None:
    template = instantiate_horizon_template("final_invariant_region")

    assert template["runtime_binding_required"] == {
        "check_command": (
            "Use command_binding='dynamic_feature_hidden_oracle' when the runtime "
            "dynamic feature oracle should be bound; otherwise provide a concrete "
            "command_definition for the invariant being checked."
        )
    }
    check_node = next(op["node"] for op in template["ops"] if op.get("op") == "create_node")
    assert check_node["command_binding"] == "dynamic_feature_hidden_oracle"


def _planner_envelope(purpose: str, ops: list[dict[str, Any]]) -> PatchEnvelope:
    return PatchEnvelope(
        patch_id=f"patch-{purpose}",
        proposed_by_node_id="planner-1",
        base_graph_position=0,
        ops=ops,
    )


def _bind_test_check_command(ops: list[dict[str, Any]]) -> None:
    for op in ops:
        if op.get("op") != "create_node":
            continue
        node = op.get("node")
        if isinstance(node, dict) and node.get("kind") == "check":
            node["command_binding"] = "dynamic_feature_hidden_oracle"
