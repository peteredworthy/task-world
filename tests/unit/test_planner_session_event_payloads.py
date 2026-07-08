from __future__ import annotations

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    PlannerSessionStateChangedPayload,
    SequentialIdGenerator,
    apply_command,
    initial_projection,
    reduce_event,
)


def test_session_state_changed_payload_normalizes_legacy_free_form_keys_to_extra() -> None:
    payload = PlannerSessionStateChangedPayload.model_validate(
        {
            "session_id": "session-1",
            "state": "attached",
            "node_id": "planner-1",
            "lease_generation": 2,
            "carryover_record_id": "summary-1",
            "operator_note": "legacy note",
        }
    )

    assert payload.session_id == "session-1"
    assert payload.state == "attached"
    assert payload.node_id == "planner-1"
    assert payload.lease_generation == 2
    assert payload.carryover_record_id == "summary-1"
    assert payload.extra == {"operator_note": "legacy note"}


def test_session_state_changed_payload_moves_invalid_legacy_scalars_to_extra() -> None:
    payload = PlannerSessionStateChangedPayload.model_validate(
        {
            "session_id": 123,
            "state": ["attached"],
            "node_id": {"node": "planner-1"},
            "lease_generation": "2",
            "carryover_record_id": 456,
        }
    )

    assert payload.session_id is None
    assert payload.state is None
    assert payload.node_id is None
    assert payload.lease_generation is None
    assert payload.carryover_record_id is None
    assert payload.extra == {
        "session_id": 123,
        "state": ["attached"],
        "node_id": {"node": "planner-1"},
        "lease_generation": "2",
        "carryover_record_id": 456,
    }


def test_session_state_changed_reducer_tolerates_legacy_payloads_through_typed_model() -> None:
    projection = reduce_event(
        initial_projection(),
        _event(
            "session_state_changed",
            {
                "session_id": "session-1",
                "state": "attached",
                "node_id": 123,
                "carryover_record_id": ["summary-1"],
                "lease_generation": "2",
                "legacy_note": "kept under extra",
            },
        ),
    )

    assert projection["planner_session_states"] == {"session-1": "attached"}
    assert projection["planner_session_current_nodes"] == {}
    assert projection["planner_session_carryovers"] == {}


def test_session_state_changed_producers_emit_payloads_validated_by_typed_model() -> None:
    events = _events_with_active_planner()
    callback = apply_command(
        _project(events),
        events,
        "submit_callback",
        _callback_payload("planner-0", "lease-planner-0", "exec-planner-0", 1),
        FakeClock(),
        SequentialIdGenerator(),
    )

    suspended_event = next(
        event
        for event in callback
        if event.event_type == "session_state_changed" and event.payload.get("state") == "suspended"
    )

    payload = PlannerSessionStateChangedPayload.model_validate(suspended_event.payload)
    assert payload.session_id == "session-1"
    assert payload.state == "suspended"
    assert payload.node_id == "planner-0"
    assert payload.lease_generation == 1
    assert payload.carryover_record_id is None
    assert payload.extra == {}
    assert suspended_event.payload["carryover_record_id"] is None


def test_session_state_changed_producer_emits_explicit_null_to_clear_stale_carryover() -> None:
    events = [
        *_events_with_active_planner(),
        _event(
            "session_state_changed",
            {
                "session_id": "session-1",
                "state": "attached",
                "node_id": "planner-0",
                "lease_generation": 1,
                "carryover_record_id": "summary-carryover-1",
            },
            position=5,
        ),
    ]
    projection = _project(events)
    assert projection["planner_session_carryovers"] == {"session-1": "summary-carryover-1"}

    callback = apply_command(
        projection,
        events,
        "submit_callback",
        _callback_payload("planner-0", "lease-planner-0", "exec-planner-0", 1),
        FakeClock(),
        SequentialIdGenerator(),
    )

    suspended_event = next(
        event
        for event in callback
        if event.event_type == "session_state_changed" and event.payload.get("state") == "suspended"
    )
    assert "carryover_record_id" in suspended_event.payload
    assert suspended_event.payload["carryover_record_id"] is None

    cleared_projection = reduce_event(projection, suspended_event)
    assert cleared_projection["planner_session_carryovers"] == {"session-1": None}


def _project(events: list[EventEnvelope]) -> Any:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _events_with_active_planner() -> list[EventEnvelope]:
    return [
        _event("run_lifecycle_changed", {"to_state": "active"}, position=1),
        _event(
            "node_created",
            {
                "node_id": "planner-0",
                "kind": "planner",
                "role": "planner",
                "state": "running",
                "generation_index": 0,
                "session_id": "session-1",
            },
            position=2,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "planner-0",
                "lease_id": "lease-planner-0",
                "generation": 1,
                "execution_id": "exec-planner-0",
                "base_snapshot_id": "snapshot-0",
                "session_id": "session-1",
            },
            position=3,
        ),
        _event(
            "session_state_changed",
            {
                "session_id": "session-1",
                "state": "attached",
                "node_id": "planner-0",
                "lease_generation": 1,
                "carryover_record_id": None,
            },
            position=4,
        ),
    ]


def _callback_payload(
    node_id: str,
    lease_id: str,
    execution_id: str,
    lease_generation: int,
) -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "node_id": node_id,
        "execution_id": execution_id,
        "lease_id": lease_id,
        "lease_generation": lease_generation,
        "base_snapshot_id": "snapshot-0",
        "observed_graph_position": 4,
        "idempotency_key": f"callback-{node_id}-{lease_generation}",
        "payload": {"payload_hash": f"hash-{node_id}-{lease_generation}"},
    }


def _event(
    event_type: str,
    payload: dict[str, Any],
    *,
    position: int = 1,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )
