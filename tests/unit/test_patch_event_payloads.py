import pytest
from pydantic import ValidationError

from orchestrator.graph.events.patches import EVENT_SPECIFICATIONS, GraphPatchAcceptedPayload


def test_patch_payload_rejects_misspelled_or_unknown_fields() -> None:
    payload = {
        "patch_id": "patch-1",
        "base_graph_position": 1,
        "actor_role": "planner",
        "proposed_by_node_id": "node-1",
        "successor_planner_node_ids": [],
    }
    assert GraphPatchAcceptedPayload.model_validate(payload).patch_id == "patch-1"
    with pytest.raises(ValidationError):
        GraphPatchAcceptedPayload.model_validate({**payload, "base_graph_postion": 1})
    with pytest.raises(ValidationError):
        GraphPatchAcceptedPayload.model_validate({**payload, "unknown_field": {}})


def test_only_accepted_and_rejected_patch_events_are_registered() -> None:
    assert {spec.name for spec in EVENT_SPECIFICATIONS} == {
        "graph_patch_accepted",
        "graph_patch_rejected",
    }
