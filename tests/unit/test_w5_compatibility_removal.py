from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from orchestrator.graph import (
    accepted_output_records_by_node_port_view,
    GraphPatchAcceptedPayload,
    NodeStateChangedPayload,
    build_projection,
)
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
        "normalize_legacy_membership",
    ):
        assert symbol not in source


def test_output_replay_rejects_missing_record_type_discriminator() -> None:
    with pytest.raises(ValidationError):
        build_projection(
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


def test_output_replay_rejects_unknown_nonempty_discriminator() -> None:
    with pytest.raises(ValidationError):
        build_projection(
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

    records = accepted_output_records_by_node_port_view(projection)
    assert records["fanout-reader-1"]["reader_output"][0]["record_id"] == "fan-out-1"


@pytest.mark.parametrize("model", [EdgeProjection, InputBindingProjection, LeaseProjection])
def test_typed_projections_reject_mapping_access(model: type[BaseModel]) -> None:
    projection = model.model_construct()
    with pytest.raises(AttributeError):
        getattr(projection, "get")
    with pytest.raises(TypeError):
        projection["node_id"]


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
            "state": "planned",
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
def test_verification_replay_rejects_unknown_nested_fields(nested_key: str) -> None:
    grade: dict[str, object] = {"requirement_id": "R-1", "grade": "A"}
    value: dict[str, object] = {
        "outcome": "passed",
        "grades": [grade],
    }
    if nested_key == "value":
        value["future"] = True
    else:
        grade["future"] = True
    with pytest.raises(ValidationError):
        build_projection(
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
