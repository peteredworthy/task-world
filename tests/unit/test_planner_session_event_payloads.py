from __future__ import annotations

from typing import Any

import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    PlannerSessionStateChangedPayload,
    build_graph_catalog,
    initial_projection,
    reduce_event,
)
from tests.graph_command_support import dispatch_graph_command


@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "session-1", "state": "attached", "operator_note": "legacy"},
        {"session_id": 123, "state": ["attached"]},
    ],
)
def test_session_state_changed_payload_rejects_legacy_and_malformed_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        PlannerSessionStateChangedPayload.model_validate(payload)


@pytest.mark.parametrize("missing", ["node_id", "lease_generation", "carryover_record_id"])
def test_session_state_changed_requires_current_producer_fields(missing: str) -> None:
    payload = {
        "session_id": "session-1",
        "state": "attached",
        "node_id": "planner-1",
        "lease_generation": 2,
        "carryover_record_id": None,
    }
    payload.pop(missing)

    with pytest.raises(ValueError):
        PlannerSessionStateChangedPayload.model_validate(payload)


def test_session_state_changed_reducer_uses_strict_payload() -> None:
    projection = reduce_event(
        build_graph_catalog(),
        initial_projection(),
        _event(
            "session_state_changed",
            {
                "session_id": "session-1",
                "state": "attached",
                "node_id": "planner-1",
                "lease_generation": 2,
                "carryover_record_id": "summary-1",
            },
        ),
    )
    assert projection["planner_session_states"] == {"session-1": "attached"}
    assert projection["planner_session_current_nodes"] == {"session-1": "planner-1"}
    assert projection["planner_session_carryovers"] == {"session-1": "summary-1"}


def test_session_state_changed_producers_emit_strict_payloads() -> None:
    events = _events_with_active_planner()
    callback = dispatch_graph_command(
        events,
        "submit_callback",
        _callback_payload("planner-0", "lease-planner-0", "exec-planner-0", 1),
    )
    suspended_event = next(
        event
        for event in callback
        if event.event_type == "session_state_changed" and event.payload.get("state") == "suspended"
    )
    payload = PlannerSessionStateChangedPayload.model_validate(suspended_event.payload)
    assert (
        payload.session_id,
        payload.state,
        payload.node_id,
        payload.lease_generation,
        payload.carryover_record_id,
    ) == ("session-1", "suspended", "planner-0", 1, None)


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
    callback = dispatch_graph_command(
        events,
        "submit_callback",
        _callback_payload("planner-0", "lease-planner-0", "exec-planner-0", 1),
    )
    suspended_event = next(
        event
        for event in callback
        if event.event_type == "session_state_changed" and event.payload.get("state") == "suspended"
    )
    assert suspended_event.payload["carryover_record_id"] is None
    assert reduce_event(build_graph_catalog(), projection, suspended_event)[
        "planner_session_carryovers"
    ] == {"session-1": None}


def _project(events: list[EventEnvelope]) -> Any:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(build_graph_catalog(), projection, event)
    return projection


def _events_with_active_planner() -> list[EventEnvelope]:
    return [
        _event("run_lifecycle_changed", {"to_state": "active"}, 1),
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
            2,
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
                "expires_at": "2026-01-01T00:05:00+00:00",
                "resource_claims": [],
            },
            3,
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
            4,
        ),
    ]


def _callback_payload(
    node_id: str, lease_id: str, execution_id: str, lease_generation: int
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


def _event(event_type: str, payload: dict[str, Any], position: int = 1) -> EventEnvelope:
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
