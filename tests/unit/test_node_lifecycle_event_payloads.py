import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    NodeAuthorityChangedPayload,
    NodeStateChangedPayload,
    build_projection,
)
from tests.unit.graph_test_utils import event


def test_node_state_payload_serializes_canonical_shape() -> None:
    raw = {
        "node_id": "worker-1",
        "new_state": "ready",
        "trigger": "readiness_evaluator",
        "attempt_number": 2,
    }
    assert (
        NodeStateChangedPayload.model_validate(raw).model_dump(mode="json", exclude_unset=True)
        == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"node_id": "worker-1", "new_state": "ready", "future_field": True},
        {"node_id": "worker-1", "new_state": "ready", "attempt_number": "2"},
    ],
)
def test_node_lifecycle_payload_rejects_unknown_and_wrong_typed_fields(
    raw: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        NodeStateChangedPayload.model_validate(raw)


def test_authority_reducer_reads_direct_fields() -> None:
    projection = build_projection(
        [
            event(
                "node_authority_changed",
                {
                    "node_id": "worker-1",
                    "allowed_actions": ["submit_output"],
                    "preconditions": ["inputs_bound"],
                },
            )
        ]
    )
    assert projection["node_allowed_actions"]["worker-1"] == ["submit_output"]
    assert projection["node_preconditions"]["worker-1"] == ["inputs_bound"]
    assert NodeAuthorityChangedPayload.model_validate({"node_id": "worker-1"}).node_id == "worker-1"
