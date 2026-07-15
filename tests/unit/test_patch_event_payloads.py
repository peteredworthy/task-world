import pytest
from pydantic import ValidationError

from orchestrator.graph import GraphPatchAcceptedPayload, GraphPatchRejectedPayload


def test_patch_payload_serializes_canonical_shape() -> None:
    raw = {
        "patch_id": "patch-1",
        "base_graph_position": 4,
        "actor_role": "planner",
        "proposed_by_node_id": "planner-1",
        "successor_planner_node_ids": ["planner-2"],
    }
    assert (
        GraphPatchAcceptedPayload.model_validate(raw).model_dump(mode="json", exclude_unset=True)
        == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"patch_id": "patch-1", "future_field": True},
        {"patch_id": "patch-1", "base_graph_position": "4"},
    ],
)
def test_patch_payload_rejects_unknown_and_wrong_typed_fields(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GraphPatchAcceptedPayload.model_validate(raw)


def test_rejected_patch_payload_uses_current_port_names() -> None:
    payload = GraphPatchRejectedPayload.model_validate(
        {"patch_id": "patch-1", "reason": "invalid topology"}
    )
    assert payload.reason == "invalid topology"
