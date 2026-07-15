import pytest
from pydantic import ValidationError

from orchestrator.graph import NodeCreatedPayload, build_projection
from tests.unit.graph_test_utils import event


def test_node_created_payload_serializes_canonical_shape() -> None:
    raw = {
        "node_id": "worker-1",
        "kind": "worker",
        "state": "planned",
        "task_region_id": "task-1",
        "attempt_number": 1,
        "authority": {"resource_claims": []},
        "resource_claims": [],
        "allowed_actions": ["submit_output"],
        "preconditions": ["inputs_bound"],
    }
    assert NodeCreatedPayload.model_validate(raw).model_dump(mode="json") == raw


@pytest.mark.parametrize(
    "raw",
    [
        {"node_id": "worker-1", "kind": "worker", "future_field": True},
        {"node_id": "worker-1", "kind": "worker", "attempt_number": "1"},
    ],
)
def test_node_created_payload_rejects_unknown_and_wrong_typed_fields(
    raw: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        NodeCreatedPayload.model_validate(raw)


def test_node_created_reducer_reads_direct_membership_fields() -> None:
    projection = build_projection(
        [
            event(
                "node_created",
                {
                    "node_id": "worker-1",
                    "kind": "worker",
                    "task_region_id": "task-1",
                    "attempt_number": 2,
                },
            )
        ]
    )
    assert projection["node_task_regions"]["worker-1"] == "task-1"
    assert projection["node_attempts"]["worker-1"] == 2
