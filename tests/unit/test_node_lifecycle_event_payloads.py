from __future__ import annotations

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    NodeAuthorityChangedPayload,
    NodeDeferredPayload,
    NodeStateChangedPayload,
    NodeSuspectPayload,
    SequentialIdGenerator,
    apply_command,
    initial_projection,
    reduce_event,
)
from orchestrator.graph import build_graph_catalog


def test_node_state_changed_payload_normalizes_legacy_membership_and_extra() -> None:
    payload = NodeStateChangedPayload.model_validate(
        {
            "node_id": "worker-1",
            "new_state": "running",
            "attempt_number": "bad",
            "membership": {"attempt_number": 2},
            "legacy_note": "kept",
        }
    )

    assert payload.node_id == "worker-1"
    assert payload.attempt_number == 2
    assert payload.extra == {"attempt_number": "bad", "legacy_note": "kept"}


def test_node_state_changed_payload_moves_malformed_fixed_values_to_extra() -> None:
    retry_payload = NodeStateChangedPayload.model_validate({"retry_not_before": 3})
    prompt_payload = NodeStateChangedPayload.model_validate({"prompt_summary": ["bad"]})

    assert retry_payload.retry_not_before is None
    assert retry_payload.extra == {"retry_not_before": 3}
    assert prompt_payload.prompt_summary is None
    assert prompt_payload.extra == {"prompt_summary": ["bad"]}


def test_node_lifecycle_auxiliary_scans_preserve_legacy_suspect_and_deferral_facts() -> None:
    projection = reduce_event(
        build_graph_catalog(),
        initial_projection(),
        _event(
            "node_created", {"node_id": "worker-1", "kind": "worker", "state": "ready"}, position=1
        ),
    )
    projection = reduce_event(
        build_graph_catalog(),
        projection,
        _event(
            "plan_region_marked_suspect",
            {"region_node_ids": ["worker-1"], "reason": "stale"},
            position=2,
        ),
    )
    projection = reduce_event(
        build_graph_catalog(),
        projection,
        _event("node_deferred", {"node_id": "worker-1", "reason": "blocked"}, position=3),
    )

    assert projection["suspect_node_reasons"] == {"worker-1": "stale"}
    assert projection["last_deferred_reasons"] == {"worker-1": "blocked"}


def test_node_deferred_payload_moves_invalid_legacy_fields_to_extra() -> None:
    payload = NodeDeferredPayload.model_validate(
        {"node_id": "worker-1", "reason": 3, "legacy_note": "kept"}
    )

    assert payload.node_id == "worker-1"
    assert payload.reason is None
    assert payload.extra == {"reason": 3, "legacy_note": "kept"}


def test_node_authority_changed_payload_normalizes_nested_authority_fallbacks() -> None:
    payload = NodeAuthorityChangedPayload.model_validate(
        {
            "node_id": "worker-1",
            "authority": {
                "resource_claims": [{"mode": "write", "scope": "repo", "path": "src"}],
                "allowed_actions": ["submit_records", 2],
                "preconditions": ["has_input", 3],
            },
            "legacy_note": "kept",
        }
    )

    assert [claim.model_dump(mode="json") for claim in payload.resource_claims] == [
        {"mode": "write", "scope": "repo", "paths": ["src"]}
    ]
    assert payload.allowed_actions == ["submit_records"]
    assert payload.preconditions == ["has_input"]
    assert payload.extra == {
        "allowed_actions": [2],
        "preconditions": [3],
        "legacy_note": "kept",
    }


def test_node_suspect_payload_preserves_node_and_region_aliases() -> None:
    payload = NodeSuspectPayload.model_validate(
        {
            "node_id": "worker-1",
            "node_ids": ["worker-2", 3],
            "region_node_ids": ["worker-3"],
            "region_id": "region-1",
            "reason": "stale",
            "legacy_note": "kept",
        }
    )

    assert payload.node_ids == ["worker-2"]
    assert payload.region_node_ids == ["worker-3"]
    assert payload.extra == {"node_ids": [3], "legacy_note": "kept"}


def test_node_lifecycle_reducers_use_typed_legacy_payloads() -> None:
    projection = reduce_event(
        build_graph_catalog(),
        initial_projection(),
        _event(
            "node_state_changed",
            {
                "node_id": "worker-1",
                "new_state": "running",
                "membership": {"attempt_number": 2},
            },
            position=1,
        ),
    )
    projection = reduce_event(
        build_graph_catalog(),
        projection,
        _event(
            "node_authority_changed",
            {
                "node_id": "worker-1",
                "authority": {
                    "allowed_actions": ["submit_records"],
                    "preconditions": ["has_input"],
                },
            },
            position=2,
        ),
    )
    projection = reduce_event(
        build_graph_catalog(),
        projection,
        _event("node_deferred", {"node_id": "worker-1", "reason": "blocked"}, position=3),
    )
    projection = reduce_event(
        build_graph_catalog(),
        projection,
        _event("node_ready", {"node_id": "worker-1"}, position=4),
    )
    projection = reduce_event(
        build_graph_catalog(),
        projection,
        _event(
            "node_marked_suspect", {"region_node_ids": ["worker-1"], "reason": "stale"}, position=5
        ),
    )
    projection = reduce_event(
        build_graph_catalog(),
        projection,
        _event("node_suspect_cleared", {"node_id": "worker-1"}, position=6),
    )

    assert projection["node_states"] == {"worker-1": "running"}
    assert projection["node_attempts"] == {"worker-1": 2}
    assert projection["node_allowed_actions"] == {"worker-1": ["submit_records"]}
    assert projection["node_preconditions"] == {"worker-1": ["has_input"]}
    assert projection["last_deferred_reasons"] == {}
    assert projection["suspect_node_reasons"] == {}


def test_node_lifecycle_producers_emit_typed_payloads() -> None:
    events = [
        _event(
            "node_created", {"node_id": "worker-1", "kind": "worker", "state": "ready"}, position=1
        )
    ]
    output = apply_command(
        _project(events),
        events,
        "schedule",
        {"run_id": "run-1", "base_snapshot_id": "snapshot-1"},
        FakeClock(),
        SequentialIdGenerator(),
    )

    for event in output:
        if event.event_type == "node_state_changed":
            assert NodeStateChangedPayload.model_validate(event.payload).extra == {}
        elif event.event_type == "node_ready":
            assert event.payload == {"node_id": "worker-1"}


def _project(events: list[EventEnvelope]) -> Any:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(build_graph_catalog(), projection, event)
    return projection


def _event(event_type: str, payload: dict[str, Any], *, position: int) -> EventEnvelope:
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
