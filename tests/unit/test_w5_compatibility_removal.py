from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.graph import GraphPatchAcceptedPayload, NodeStateChangedPayload, build_projection
from orchestrator.graph import (
    EdgeProjection,
    InputBindingProjection,
    LeaseProjection,
    NodeCreatedPayload,
)
from tests.unit.graph_test_utils import event


SOURCE = Path("src/orchestrator/graph")


def test_event_payloads_forbid_unknown_fields_and_scalar_coercion() -> None:
    with pytest.raises(ValidationError):
        GraphPatchAcceptedPayload.model_validate(
            {
                "patch_id": "patch-1",
                "base_graph_position": 0,
                "future_field": True,
            }
        )
    with pytest.raises(ValidationError):
        NodeStateChangedPayload.model_validate(
            {"node_id": "node-1", "new_state": "ready", "attempt_number": "1"}
        )


def test_historical_compatibility_symbols_are_absent() -> None:
    source = "\n".join(path.read_text() for path in SOURCE.glob("*.py"))
    for symbol in (
        "LegacyOutputRecord",
        "GraphPatchStatusPayload",
        "RequirementAuthorityResolutionPayload",
        "_legacy_output_record_payload",
        "_generic_output_record_payload",
        "_legacy_requirement_evidence_blockers",
        "_DictCompatibleProjection",
    ):
        assert symbol not in source


def test_output_replay_requires_exact_record_type_discriminator() -> None:
    projection = build_projection(
        [
            event(
                "output_record_accepted",
                {
                    "record_id": "summary-1",
                    "record_kind": "output",
                    "producer_node_id": "summarizer-1",
                    "port": "opaque_summary",
                    "schema": "OpaqueSummary",
                    "value": {"summary": "missing discriminator"},
                },
            )
        ]
    )

    assert projection["accepted_output_records_by_node_port"] == {}


def test_output_replay_rejects_unknown_nonempty_discriminator() -> None:
    projection = build_projection(
        [
            event(
                "output_record_accepted",
                {
                    "record_id": "future-1",
                    "record_kind": "output",
                    "record_type": "future_record",
                    "producer_node_id": "worker-1",
                    "port": "future_output",
                    "schema": "FutureRecord",
                    "value": {"body": "unsupported"},
                },
            )
        ]
    )

    assert projection["accepted_output_records_by_node_port"] == {}


@pytest.mark.parametrize("record_type", ["fan_out_inputs"])
def test_output_replay_accepts_each_explicit_generic_discriminator(record_type: str) -> None:
    projection = build_projection(
        [
            event(
                "output_record_accepted",
                {
                    "record_id": "fan-out-1",
                    "record_kind": "output",
                    "record_type": record_type,
                    "producer_node_id": "fanout-reader-1",
                    "port": "reader_output",
                    "schema": "FanOutInputs",
                    "value": {"summary": "one input"},
                },
            )
        ]
    )

    records = projection["accepted_output_records_by_node_port"]
    assert records["fanout-reader-1"]["reader_output"][0]["record_id"] == "fan-out-1"


@pytest.mark.parametrize("model", [EdgeProjection, InputBindingProjection, LeaseProjection])
def test_typed_projections_have_no_mapping_methods(model: type[object]) -> None:
    assert "get" not in model.__dict__
    assert "__getitem__" not in model.__dict__


@pytest.mark.parametrize(
    "payload",
    [
        {
            "node_id": "planner-1",
            "kind": "planner",
            "resource_claims": [{"mode": "read", "scope": "repo", "future": True}],
        },
        {
            "node_id": "planner-1",
            "kind": "planner",
            "inputs": [{"port": "source", "future": True}],
        },
        {
            "node_id": "planner-1",
            "kind": "planner",
            "planner_chain": {"regions": [{"region_label": "one", "future": True}]},
        },
    ],
)
def test_w5_nested_models_reject_unknown_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        NodeCreatedPayload.model_validate(payload)


def test_named_dynamic_node_created_fields_remain_open() -> None:
    payload = NodeCreatedPayload.model_validate(
        {
            "node_id": "check-1",
            "kind": "check",
            "command_definition": {"argv": ["uv", "run", "pytest"], "future": {"ok": True}},
            "dynamic_feature": {"provider_extension": [1, 2, 3]},
        }
    )

    assert payload.command_definition == {
        "argv": ["uv", "run", "pytest"],
        "future": {"ok": True},
    }
    assert payload.dynamic_feature == {"provider_extension": [1, 2, 3]}


@pytest.mark.parametrize("nested_key", ["value", "grade"])
def test_verification_record_rejects_unknown_nested_fields(nested_key: str) -> None:
    grade: dict[str, object] = {"requirement_id": "R-1", "grade": "A"}
    value: dict[str, object] = {
        "outcome": "passed",
        "grades": [grade],
    }
    if nested_key == "value":
        value["future"] = True
    else:
        grade["future"] = True
    projection = build_projection(
        [
            event(
                "output_record_accepted",
                {
                    "record_id": "verification-1",
                    "record_kind": "verification",
                    "record_type": "verification_report",
                    "producer_node_id": "verifier-1",
                    "port": "verification_report",
                    "schema": "VerificationReport",
                    "candidate_id": "candidate-1",
                    "outcome": "passed",
                    "value": value,
                },
            )
        ]
    )

    assert projection["accepted_output_records_by_node_port"] == {}
