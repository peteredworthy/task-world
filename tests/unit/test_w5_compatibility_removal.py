from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.graph import GraphPatchAcceptedPayload, NodeStateChangedPayload, build_projection
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
