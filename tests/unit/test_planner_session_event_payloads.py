import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    FakeClock,
    PlannerSessionStateChangedPayload,
    SequentialIdGenerator,
    build_projection,
)
from tests.unit.graph_test_utils import apply_command, command_context
from tests.unit.graph_test_utils import event


def test_planner_session_payload_serializes_canonical_shape() -> None:
    raw = {
        "session_id": "session-1",
        "state": "attached",
        "node_id": "planner-1",
        "lease_generation": 2,
        "carryover_record_id": "record-1",
    }
    assert (
        PlannerSessionStateChangedPayload.model_validate(raw).model_dump(
            mode="json", exclude_unset=True
        )
        == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"session_id": "session-1", "state": "attached", "future_field": True},
        {"session_id": "session-1", "state": "attached", "lease_generation": "2"},
    ],
)
def test_planner_session_payload_rejects_unknown_and_wrong_typed_fields(
    raw: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        PlannerSessionStateChangedPayload.model_validate(raw)


def test_planner_session_reducer_preserves_explicit_null_carryover() -> None:
    projection = build_projection(
        [
            event(
                "session_state_changed",
                {"session_id": "session-1", "state": "attached", "carryover_record_id": None},
            )
        ]
    )
    assert projection["planner_session_carryovers"]["session-1"] is None


def test_planner_callback_producer_matches_typed_session_payload_json() -> None:
    events = [
        event("run_lifecycle_changed", {"to_state": "active"}, position=1),
        event(
            "node_created",
            {
                "node_id": "planner-1",
                "kind": "planner",
                "role": "planner",
                "state": "running",
                "generation_index": 0,
                "session_id": "session-1",
            },
            position=2,
        ),
        event(
            "lease_granted",
            {
                "node_id": "planner-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
                "base_snapshot_id": "snapshot-1",
                "session_id": "session-1",
            },
            position=3,
        ),
        event(
            "session_state_changed",
            {
                "session_id": "session-1",
                "state": "attached",
                "node_id": "planner-1",
                "lease_generation": 1,
                "carryover_record_id": None,
            },
            position=4,
        ),
    ]
    emitted = apply_command(
        build_projection(events),
        events,
        "submit_callback",
        {
            "node_id": "planner-1",
            "execution_id": "exec-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "base_snapshot_id": "snapshot-1",
            "observed_graph_position": 4,
            "idempotency_key": "callback-1",
            "payload": {"payload_hash": "hash-1"},
        },
        command_context(events),
        FakeClock(),
        SequentialIdGenerator(),
    )
    payload = next(
        item.payload
        for item in emitted
        if item.event_type == "session_state_changed" and item.payload["state"] == "suspended"
    )

    assert payload == PlannerSessionStateChangedPayload.model_validate(payload).model_dump(
        mode="json"
    )
