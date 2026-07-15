import pytest
from pydantic import ValidationError

from orchestrator.graph import LeaseGrantedPayload, LeaseRenewedPayload, build_projection
from tests.unit.graph_test_utils import event


def test_lease_payload_serializes_canonical_shape() -> None:
    raw = {
        "lease_id": "lease-1",
        "node_id": "worker-1",
        "task_region_id": "task-1",
        "kind": "worker",
        "generation": 2,
        "execution_id": "exec-1",
    }
    assert (
        LeaseGrantedPayload.model_validate(raw).model_dump(mode="json", exclude_unset=True) == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"lease_id": "lease-1", "node_id": "worker-1", "future_field": True},
        {"lease_id": "lease-1", "node_id": "worker-1", "generation": "2"},
    ],
)
def test_lease_payload_rejects_unknown_and_wrong_typed_fields(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LeaseGrantedPayload.model_validate(raw)


def test_lease_reducer_projects_canonical_fields() -> None:
    projection = build_projection(
        [
            event("node_created", {"node_id": "worker-1", "kind": "worker"}),
            event(
                "lease_granted",
                {
                    "lease_id": "lease-1",
                    "node_id": "worker-1",
                    "task_region_id": "task-1",
                    "kind": "worker",
                },
                position=1,
            ),
        ]
    )
    assert projection["leases"]["lease-1"].task_region_id == "task-1"
    assert projection["leases"]["lease-1"].kind == "worker"
    assert LeaseRenewedPayload.model_validate({"lease_id": "lease-1"}).lease_id == "lease-1"
