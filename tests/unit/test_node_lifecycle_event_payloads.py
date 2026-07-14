from __future__ import annotations

from typing import Any

import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    CommandExecutionContext,
    FakeClock,
    HydratedEvent,
    InputBoundPayload,
    NodeAuthorityChangedPayload,
    NodeDeferredPayload,
    NodeStateChangedPayload,
    PlanRegionMarkedSuspectPayload,
    SequentialIdGenerator,
    apply_command,
    build_graph_catalog,
    build_graph_command_dependencies,
    initial_projection,
    reduce_event,
)
from orchestrator.graph import StoredEventEnvelope


@pytest.mark.parametrize(
    ("payload_type", "payload"),
    [
        (
            NodeStateChangedPayload,
            {"node_id": "worker-1", "new_state": "running", "membership": {}},
        ),
        (
            NodeStateChangedPayload,
            {"node_id": "worker-1", "new_state": "running", "attempt_number": "2"},
        ),
        (NodeDeferredPayload, {"node_id": "worker-1", "reason": 3}),
        (NodeAuthorityChangedPayload, {"node_id": "worker-1", "authority": {}}),
        (PlanRegionMarkedSuspectPayload, {"node_ids": ["worker-1"], "reason": "stale"}),
    ],
)
def test_node_lifecycle_payloads_reject_legacy_aliases_and_malformed_values(
    payload_type: type[
        NodeStateChangedPayload
        | NodeDeferredPayload
        | NodeAuthorityChangedPayload
        | PlanRegionMarkedSuspectPayload
    ],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        payload_type.model_validate(payload)


def test_node_lifecycle_reducers_use_only_named_strict_payloads() -> None:
    catalog = build_graph_catalog()
    projection = reduce_event(
        catalog,
        initial_projection(),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "ready"}, 1),
    )
    projection = reduce_event(
        catalog,
        projection,
        _event(
            "node_state_changed",
            {"node_id": "worker-1", "new_state": "running", "attempt_number": 2},
            2,
        ),
    )
    projection = reduce_event(
        catalog,
        projection,
        _event(
            "node_authority_changed",
            {
                "node_id": "worker-1",
                "allowed_actions": ["submit_records"],
                "preconditions": ["has_input"],
            },
            3,
        ),
    )
    projection = reduce_event(
        catalog,
        projection,
        _event("node_deferred", {"node_id": "worker-1", "reason": "blocked"}, 4),
    )
    projection = reduce_event(catalog, projection, _event("node_ready", {"node_id": "worker-1"}, 5))
    projection = reduce_event(
        catalog,
        projection,
        _event(
            "plan_region_marked_suspect", {"region_node_ids": ["worker-1"], "reason": "stale"}, 6
        ),
    )

    assert projection["node_states"] == {"worker-1": "running"}
    assert projection["node_attempts"] == {"worker-1": 2}
    assert projection["node_allowed_actions"] == {"worker-1": ["submit_records"]}
    assert projection["node_preconditions"] == {"worker-1": ["has_input"]}
    assert projection["last_deferred_reasons"] == {}
    assert projection["suspect_node_reasons"] == {"worker-1": "stale"}


def test_node_authority_changed_applies_explicit_empty_lists() -> None:
    catalog = build_graph_catalog()
    projection = reduce_event(
        catalog,
        initial_projection(),
        _event(
            "node_authority_changed",
            {
                "node_id": "worker-1",
                "allowed_actions": ["submit_records"],
                "preconditions": ["has_input"],
            },
            1,
        ),
    )
    projection = reduce_event(
        catalog,
        projection,
        _event(
            "node_authority_changed",
            {"node_id": "worker-1", "allowed_actions": [], "preconditions": []},
            2,
        ),
    )

    assert projection["node_allowed_actions"] == {"worker-1": []}
    assert projection["node_preconditions"] == {"worker-1": []}


@pytest.mark.parametrize("missing", ["edge_id", "record_ids", "bound_at_position"])
def test_input_bound_requires_current_producer_fields(missing: str) -> None:
    payload = {
        "edge_id": "edge-1",
        "to_node_id": "worker-1",
        "to_port": "input",
        "record_ids": [],
        "bound_at_position": 3,
    }
    payload.pop(missing)

    with pytest.raises(ValueError):
        InputBoundPayload.model_validate(payload)


def test_node_lifecycle_producers_emit_strict_payloads() -> None:
    events = [
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "ready"}, 1)
    ]
    catalog = build_graph_catalog()
    clock = FakeClock()
    id_generator = SequentialIdGenerator()
    output = apply_command(
        catalog,
        _project(events),
        events,
        "schedule_tick",
        {"base_snapshot_id": "snapshot-1", "lease_seconds": 30, "max_grants": 1},
        CommandExecutionContext(
            run_id="run-1",
            current_position=max(event.metadata.position for event in events),
            clock=clock,
            id_generator=id_generator,
            actor=Actor(kind=ActorKind.CONTROLLER),
            events=tuple(events),
            future_effects=build_graph_command_dependencies(catalog=catalog).future_effects,
            catalog=catalog,
        ),
    )

    for event in output:
        if event.event_type == "node_state_changed":
            assert NodeStateChangedPayload.model_validate(event.payload).node_id == "worker-1"
        elif event.event_type == "node_ready":
            assert event.payload == {"node_id": "worker-1"}


def _project(events: list[HydratedEvent]) -> Any:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(build_graph_catalog(), projection, event)
    return projection


def _event(event_type: str, payload: dict[str, Any], position: int) -> HydratedEvent:
    return (
        build_graph_catalog()
        .resolve_event(event_type)
        .hydrate(
            StoredEventEnvelope(
                event_id=f"{event_type}-{position}",
                run_id="run-1",
                position=position,
                event_type=event_type,
                payload_schema_generation=2,
                actor=Actor(kind=ActorKind.CONTROLLER),
                timestamp=FakeClock().now(),
                payload=payload,
            )
        )
    )
