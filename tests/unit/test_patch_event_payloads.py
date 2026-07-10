from __future__ import annotations

from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    GraphPatchAcceptedPayload,
    GraphPatchRejectedPayload,
    GraphPatchStatusPayload,
    SequentialIdGenerator,
    apply_command,
    initial_projection,
    project_graph_patch_attempts,
    reduce_event,
)
from orchestrator.graph import build_graph_catalog


def test_graph_patch_accepted_payload_normalizes_legacy_free_form_keys_to_extra() -> None:
    payload = GraphPatchAcceptedPayload.model_validate(
        {
            "patch_id": "patch-1",
            "base_graph_position": 4,
            "actor_role": "planner",
            "proposed_by_node_id": "planner-1",
            "successor_planner_node_ids": ["planner-2", 3],
            "session_id": "session-1",
            "carryover_record_id": "summary-1",
            "legacy_note": "kept",
        }
    )

    assert payload.successor_planner_node_ids == ["planner-2"]
    assert payload.extra == {"legacy_note": "kept"}


def test_graph_patch_rejected_payload_preserves_rejection_metadata_and_extra() -> None:
    payload = GraphPatchRejectedPayload.model_validate(
        {
            "patch_id": "patch-1",
            "base_graph_position": -1,
            "actor_role": "planner",
            "proposed_by_node_id": "planner-1",
            "reason": "invalid_patch",
            "rejection_reason": "invalid_patch",
            "read_set_diff": {"changed": ["node-1"]},
            "budget": 4,
            "count": 5,
            "legacy_note": "kept",
        }
    )

    assert payload.reason == "invalid_patch"
    assert payload.read_set_diff == {"changed": ["node-1"]}
    assert payload.extra == {"legacy_note": "kept"}


def test_graph_patch_status_payload_handles_replay_aliases() -> None:
    payload = GraphPatchStatusPayload.model_validate(
        {
            "proposal_id": "proposal-1",
            "patch_id": 123,
            "node_id": "planner-1",
            "proposed_by_node_id": ["planner-legacy"],
            "reason": "waiting",
            "legacy_note": "kept",
        }
    )

    assert payload.proposal_id == "proposal-1"
    assert payload.patch_id is None
    assert payload.proposed_by_node_id is None
    assert payload.extra == {
        "patch_id": 123,
        "proposed_by_node_id": ["planner-legacy"],
        "legacy_note": "kept",
    }


def test_patch_reducers_tolerate_legacy_payloads_through_typed_models() -> None:
    projection = reduce_event(
        build_graph_catalog(),
        initial_projection(),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-1",
                "successor_planner_node_ids": ["planner-2", {"bad": "legacy"}],
                "legacy_note": "kept",
            },
            position=1,
        ),
    )

    assert projection["accepted_graph_patches_by_node"] == {"planner-1": ["patch-1"]}
    assert projection["planner_successors"] == {"planner-1": "planner-2"}

    projection = reduce_event(
        build_graph_catalog(),
        projection,
        _event("graph_patch_proposed", {"patch_id": "patch-2", "node_id": "planner-2"}, position=2),
    )
    assert "patch-2" in projection["open_proposal_blockers"]

    projection = reduce_event(
        build_graph_catalog(),
        projection,
        _event("graph_patch_rejected", {"patch_id": "patch-2", "reason": "invalid"}, position=3),
    )
    assert "patch-2" not in projection["open_proposal_blockers"]


def test_patch_producers_emit_payloads_validated_by_typed_models() -> None:
    events = [_event("run_lifecycle_changed", {"to_state": "active"}, position=1)]
    output = apply_command(
        _project(events),
        events,
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-1",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )

    accepted = next(event for event in output if event.event_type == "graph_patch_accepted")
    accepted_payload = GraphPatchAcceptedPayload.model_validate(accepted.payload)
    assert accepted_payload.patch_id == "patch-1"
    assert accepted_payload.extra == {}

    rejected = apply_command(
        _project(events),
        events,
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-bad",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [{"op": "bad"}],
        },
        FakeClock(),
        SequentialIdGenerator(),
    )
    rejected_payload = GraphPatchRejectedPayload.model_validate(rejected[0].payload)
    assert rejected_payload.patch_id == "patch-bad"
    assert rejected_payload.extra == {}


def test_project_graph_patch_attempts_reads_patch_payloads_through_typed_models() -> None:
    events = [
        _event(
            "graph_patch_proposed",
            {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-1",
                "base_graph_position": 2,
            },
            position=1,
        ),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-1",
                "base_graph_position": 2,
                "successor_planner_node_ids": ["planner-2"],
            },
            position=2,
        ),
    ]

    attempts = project_graph_patch_attempts(events)["attempts"]

    assert attempts[0]["patch_id"] == "patch-1"
    assert attempts[0]["status"] == "accepted"
    assert attempts[0]["diagnostics"] == {"successor_planner_node_ids": ["planner-2"]}


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
