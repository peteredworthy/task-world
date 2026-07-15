import pytest
from pydantic import BaseModel, ValidationError

from orchestrator.graph import (
    CommandRejectedPayload,
    FakeClock,
    GraphPatchAcceptedPayload,
    GraphPatchRejectedPayload,
    SequentialIdGenerator,
    apply_command,
    build_projection,
)
from tests.unit.graph_test_utils import event


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


@pytest.mark.parametrize("model", [GraphPatchRejectedPayload, CommandRejectedPayload])
def test_all_current_patch_positions_are_strict_integers(model: type[BaseModel]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"patch_id": "patch-1", "base_graph_position": "4"})


def test_patch_command_producer_matches_canonical_payload_json() -> None:
    events = [event("run_lifecycle_changed", {"to_state": "active"}, position=1)]
    emitted = apply_command(
        build_projection(events),
        events,
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-1",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": 1,
            "ops": [],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )
    payload = next(item.payload for item in emitted if item.event_type == "graph_patch_accepted")

    assert payload == GraphPatchAcceptedPayload.model_validate(payload).model_dump(mode="json")
