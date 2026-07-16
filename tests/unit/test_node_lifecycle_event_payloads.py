import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    FakeClock,
    NodeAuthorityChangedPayload,
    NodeStateChangedPayload,
    SequentialIdGenerator,
    build_projection,
)
from tests.unit.graph_test_utils import apply_command, command_context
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


def test_schedule_producer_matches_typed_node_state_payload_json() -> None:
    events = [
        event("run_lifecycle_changed", {"to_state": "active"}, position=1),
        event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "state": "ready"},
            position=2,
        ),
        event(
            "input_bound",
            {
                "to_node_id": "worker-1",
                "to_port": "routine_snapshot",
                "record_ids": ["routine-snapshot-record"],
                "bound_at_position": 2,
            },
            position=3,
        ),
    ]
    emitted = apply_command(
        build_projection(events),
        events,
        "schedule_tick",
        {"max_grants": 1},
        command_context(events),
        FakeClock(),
        SequentialIdGenerator(),
    )
    payload = next(item.payload for item in emitted if item.event_type == "node_state_changed")

    assert payload == NodeStateChangedPayload.model_validate(payload).model_dump(
        mode="json", exclude_unset=True
    )
