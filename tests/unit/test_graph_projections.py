"""Public graph-projection reducer, view, and checkpoint contracts."""

from typing import Any

import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    Actor,
    ActorKind,
    AuthorityRequestRecord,
    EventEnvelope,
    FakeClock,
    build_projection,
    file_state_records_view,
    initial_projection,
    latest_routine_snapshot_record,
    node_command_definitions_view,
    node_states_view,
    output_record_payloads_view,
    output_records_by_node_port_view,
    project_decision_view,
    project_graph_topology,
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
    task_candidates_view,
)


def _event(event_type: str, payload: dict[str, Any], position: int) -> EventEnvelope:
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


def _worker(node_id: str, position: int, *, state: str = "planned") -> EventEnvelope:
    return _event(
        "node_created",
        {"node_id": node_id, "kind": "worker", "state": state, "task_region_id": "task-1"},
        position,
    )


def _candidate(position: int) -> EventEnvelope:
    return _event(
        "output_record_accepted",
        {
            "record_id": "candidate-1",
            "record_kind": "output",
            "record_type": "candidate",
            "producer_node_id": "worker-1",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "candidate_id": "candidate-1",
            "task_region_id": "task-1",
            "attempt_number": 1,
            "value": {"summary": "implemented"},
        },
        position,
    )


def test_empty_projection_has_empty_public_views() -> None:
    projection = initial_projection()

    assert node_states_view(projection) == {}
    assert output_records_by_node_port_view(projection) == {}
    assert file_state_records_view(projection) == {}
    assert task_candidates_view(projection) == {}


def test_authority_request_record_is_owned_only_by_canonical_record_store() -> None:
    record_id = "authority-request-gate-1"
    authority_request = {
        "record_id": record_id,
        "record_kind": "graph_record",
        "record_type": "authority_request_record",
        "producer_node_id": "gate-1",
        "port": "authority_request_record",
        "schema": "AuthorityRequest",
        "value": {
            "requested_authority": ["graph_write"],
            "target_node_id": "gate-1",
            "reason": "approve write",
        },
    }
    projection = build_projection(
        [
            _event(
                "node_created",
                {
                    "node_id": "gate-1",
                    "kind": "authority_request",
                    "state": "planned",
                    "authority_request_record": authority_request,
                },
                1,
            ),
            _event("output_record_accepted", authority_request, 2),
        ]
    )

    checkpoint = projection_to_checkpoint(projection)

    assert "authority_request_record" not in checkpoint["state"]["nodes"]["gate-1"]["spec"]
    assert "authority_request" not in checkpoint["state"]["nodes"]["gate-1"]["spec"]
    assert (
        checkpoint["state"]["nodes"]["gate-1"]["spec"].get("authority_request_record_id")
        == record_id
    )
    public_record = output_record_payloads_view(projection)[record_id]
    assert isinstance(public_record, AuthorityRequestRecord)
    assert public_record.record_id == record_id
    assert public_record.value.requested_authority == ["graph_write"]
    public_record.value.requested_authority.append("admin")
    fresh_public_record = output_record_payloads_view(projection)[record_id]
    assert isinstance(fresh_public_record, AuthorityRequestRecord)
    assert fresh_public_record.value.requested_authority == ["graph_write"]
    assert project_decision_view([], projection=projection)["pending_gates"] == [
        {
            "node_id": "gate-1",
            "gate_type": "authority_request",
            "prompt": None,
            "requested_authority": ["graph_write"],
            "target_node_id": "gate-1",
        }
    ]


def test_authority_request_record_is_not_fabricated_before_acceptance() -> None:
    projection = build_projection(
        [
            _event(
                "node_created",
                {
                    "node_id": "gate-1",
                    "kind": "authority_request",
                    "state": "planned",
                    "authority_request_record": {
                        "record_id": "authority-request-gate-1",
                        "record_kind": "graph_record",
                        "record_type": "authority_request_record",
                        "producer_node_id": "gate-1",
                        "port": "authority_request_record",
                        "schema": "AuthorityRequest",
                        "value": {
                            "requested_authority": ["graph_write"],
                            "target_node_id": "gate-1",
                            "reason": "approve write",
                        },
                    },
                },
                1,
            )
        ]
    )

    assert output_record_payloads_view(projection).get("authority-request-gate-1") is None


def test_node_created_rejects_mismatched_authority_request_record_identity() -> None:
    with pytest.raises(ValueError, match="authority_request_record_id"):
        build_projection(
            [
                _event(
                    "node_created",
                    {
                        "node_id": "gate-1",
                        "kind": "authority_request",
                        "state": "planned",
                        "authority_request_record_id": "custom-id",
                        "authority_request_record": {
                            "record_id": "envelope-id",
                            "record_kind": "graph_record",
                            "record_type": "authority_request_record",
                            "producer_node_id": "gate-1",
                            "port": "authority_request_record",
                            "schema": "AuthorityRequest",
                            "value": {
                                "requested_authority": ["graph_write"],
                                "target_node_id": "gate-1",
                                "reason": "approve write",
                            },
                        },
                    },
                    1,
                )
            ]
        )


def test_node_created_authority_request_record_identity_semantics() -> None:
    value_only = build_projection(
        [
            _event(
                "node_created",
                {
                    "node_id": "value-only",
                    "kind": "authority_request",
                    "state": "planned",
                    "authority_request_record_id": "custom-id",
                    "authority_request_record": {
                        "requested_authority": ["graph_write"],
                        "target_node_id": "value-only",
                        "reason": "approve write",
                    },
                },
                1,
            )
        ]
    )
    envelope_only = build_projection(
        [
            _event(
                "node_created",
                {
                    "node_id": "envelope-only",
                    "kind": "authority_request",
                    "state": "planned",
                    "authority_request_record": {
                        "record_id": "envelope-id",
                        "record_kind": "graph_record",
                        "record_type": "authority_request_record",
                        "producer_node_id": "envelope-only",
                        "port": "authority_request_record",
                        "schema": "AuthorityRequest",
                        "value": {
                            "requested_authority": ["graph_write"],
                            "target_node_id": "envelope-only",
                            "reason": "approve write",
                        },
                    },
                },
                1,
            )
        ]
    )
    id_only = build_projection(
        [
            _event(
                "node_created",
                {
                    "node_id": "id-only",
                    "kind": "authority_request",
                    "state": "planned",
                    "authority_request_record_id": "reference-id",
                },
                1,
            )
        ]
    )

    assert (
        projection_to_checkpoint(value_only)["state"]["nodes"]["value-only"]["spec"][
            "authority_request_record_id"
        ]
        == "custom-id"
    )
    assert (
        projection_to_checkpoint(envelope_only)["state"]["nodes"]["envelope-only"]["spec"][
            "authority_request_record_id"
        ]
        == "envelope-id"
    )
    assert (
        projection_to_checkpoint(id_only)["state"]["nodes"]["id-only"]["spec"][
            "authority_request_record_id"
        ]
        == "reference-id"
    )


def test_accepted_authority_request_record_fills_only_missing_node_reference() -> None:
    accepted = {
        "record_id": "accepted-reference",
        "record_kind": "graph_record",
        "record_type": "authority_request_record",
        "producer_node_id": "missing-reference",
        "port": "authority_request_record",
        "schema": "AuthorityRequest",
        "value": {
            "requested_authority": ["graph_write"],
            "target_node_id": "missing-reference",
            "reason": "approve write",
        },
    }
    preserved = {**accepted, "record_id": "second-reference", "producer_node_id": "first-reference"}
    projection = build_projection(
        [
            _event(
                "node_created",
                {"node_id": "missing-reference", "kind": "authority_request", "state": "planned"},
                1,
            ),
            _event("output_record_accepted", accepted, 2),
            _event(
                "node_created",
                {
                    "node_id": "first-reference",
                    "kind": "authority_request",
                    "state": "planned",
                    "authority_request_record_id": "first-reference-id",
                },
                3,
            ),
            _event("output_record_accepted", preserved, 4),
        ]
    )

    checkpoint = projection_to_checkpoint(projection)
    assert checkpoint["state"]["nodes"]["missing-reference"]["spec"][
        "authority_request_record_id"
    ] == ("accepted-reference")
    assert "authority_request" not in checkpoint["state"]["nodes"]["missing-reference"]["spec"]
    assert checkpoint["state"]["nodes"]["first-reference"]["spec"][
        "authority_request_record_id"
    ] == ("first-reference-id")
    pending_gate = next(
        gate
        for gate in project_decision_view([], projection=projection)["pending_gates"]
        if gate["node_id"] == "missing-reference"
    )
    assert pending_gate["requested_authority"] == ["graph_write"]


def test_check_command_binding_projects_command_definition() -> None:
    projection = build_projection(
        [
            _event(
                "node_created",
                {
                    "node_id": "check-1",
                    "kind": "check",
                    "state": "planned",
                    "command_binding": "dynamic_feature_hidden_oracle",
                },
                0,
            )
        ]
    )

    command_definition = node_command_definitions_view(projection).get("check-1")
    assert command_definition is not None
    assert dict(command_definition) == {
        "id": "check-1",
        "command_binding": "dynamic_feature_hidden_oracle",
        "source": "dynamic_feature_hidden_oracle_binding",
        "deferred": True,
    }


def test_canonical_candidate_event_projects_public_record_and_task_views() -> None:
    projection = build_projection([_worker("worker-1", 0), _candidate(1)])

    assert node_states_view(projection) == {"worker-1": "planned"}
    record = output_records_by_node_port_view(projection)["worker-1"]["candidate"][0]
    assert record.record_id == "candidate-1"
    assert record.record_type == "candidate"
    assert record.model_dump(mode="json")["value"]["summary"] == "implemented"
    assert [candidate.candidate_id for candidate in task_candidates_view(projection)["task-1"]] == [
        "candidate-1"
    ]


def test_canonical_file_state_event_projects_public_file_state_view() -> None:
    projection = build_projection(
        [
            _worker("worker-1", 0),
            _event(
                "file_state_accepted",
                {
                    "record_id": "file-state-1",
                    "record_kind": "file_state",
                    "record_type": "file_state",
                    "producer_node_id": "worker-1",
                    "port": "file_state",
                    "schema": "FileStateRecord",
                    "snapshot_id": "snapshot-1",
                    "base_snapshot_id": "snapshot-0",
                    "tracked": [{"path": "src/app.py", "status": "modified"}],
                    "verdict": "captured",
                },
                1,
            ),
        ]
    )

    file_state = file_state_records_view(projection)["file-state-1"]
    assert file_state.snapshot_id == "snapshot-1"
    assert file_state.tracked[0].path == "src/app.py"


def test_canonical_topology_events_produce_public_topology() -> None:
    events = [
        _worker("source-1", 0, state="completed"),
        _worker("target-1", 1),
        _event(
            "edge_created",
            {
                "edge_id": "candidate-edge",
                "from_node_id": "source-1",
                "from_port": "candidate",
                "to_node_id": "target-1",
                "to_port": "candidate",
                "required": True,
            },
            2,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "candidate-edge",
                "to_node_id": "target-1",
                "to_port": "candidate",
                "record_ids": ["candidate-1"],
                "bound_at_position": 3,
            },
            3,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "candidate-edge",
                "to_node_id": "target-1",
                "to_port": "candidate",
                "record_ids": ["candidate-2"],
                "bound_at_position": 4,
            },
            4,
        ),
    ]

    topology = project_graph_topology(events)

    edge = topology["edges"][0]
    assert edge["edge_id"] == "candidate-edge"
    assert edge["from_node_id"] == "source-1"
    assert edge["to_node_id"] == "target-1"
    assert edge["binding"]["record_ids"] == ["candidate-1"]
    assert edge["binding"]["binding_policy"] == "bind_first"
    assert "metadata" not in edge["metadata"]


def test_canonical_decision_request_is_visible_through_decision_view() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "gate-1",
                "kind": "human_gate",
                "state": "blocked",
                "reason": "approve release",
            },
            0,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "decision-request-1",
                "record_kind": "graph_record",
                "record_type": "decision_request",
                "producer_node_id": "gate-1",
                "port": "decision_request",
                "schema": "DecisionRequest",
                "value": {
                    "decision_type": "approval",
                    "options": ["approve", "reject"],
                    "default_option": "reject",
                    "consequence_summary": "Release the change.",
                },
            },
            1,
        ),
    ]

    assert project_decision_view(events)["pending_gates"] == [
        {
            "node_id": "gate-1",
            "gate_type": "approve release",
            "prompt": "approve release",
            "options": ["approve", "reject"],
            "default_option": "reject",
            "consequence_summary": "Release the change.",
        }
    ]


def test_checkpoint_round_trip_preserves_public_reducer_outcomes() -> None:
    projection = build_projection([_worker("worker-1", 0), _candidate(1)])

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))

    assert node_states_view(restored) == node_states_view(projection)
    assert output_records_by_node_port_view(restored) == output_records_by_node_port_view(
        projection
    )
    assert task_candidates_view(restored) == task_candidates_view(projection)


def test_checkpoint_rejects_a_malformed_current_version_body_as_a_whole() -> None:
    checkpoint = projection_to_checkpoint(initial_projection())
    checkpoint["state"]["nodes"] = {"unexpected": "legacy-flat-body"}

    with pytest.raises(ValueError):
        projection_from_checkpoint(checkpoint)


def test_reducer_rejects_malformed_canonical_event_payload() -> None:
    malformed = _event(
        "node_created",
        {"node_id": ["not", "an", "id"], "kind": "worker", "state": "planned"},
        0,
    )

    with pytest.raises(ValidationError):
        reduce_event(initial_projection(), malformed)


def test_outbox_requeue_audit_event_is_exactly_projection_neutral() -> None:
    projection = build_projection([_worker("worker-1", 0)])
    audit_event = _event(
        "outbox_requeued",
        {
            "run_id": "run-1",
            "outbox_id": 7,
            "event_id": "outbox-event-1",
            "kind": "agent_dispatch",
            "previous_status": "failed",
            "previous_attempts": 3,
            "previous_last_error": "agent dispatch exploded",
            "operator": "human-operator",
            "graph_position": 2,
        },
        1,
    )

    assert reduce_event(projection, audit_event) is projection


def test_reducer_replays_historical_routine_snapshot_without_value() -> None:
    historical = _event(
        "output_record_accepted",
        {
            "record_id": "routine-snapshot-1",
            "record_kind": "graph_record",
            "record_type": "routine_snapshot",
            "producer_node_id": "routine-snapshot",
            "port": "snapshot",
            "schema": "RoutineSnapshot",
        },
        1,
    )

    projection = reduce_event(initial_projection(), historical)

    assert output_records_by_node_port_view(projection) == {}
    assert latest_routine_snapshot_record(projection) is None


def test_reducer_rejects_malformed_routine_snapshot_with_value() -> None:
    malformed = _event(
        "output_record_accepted",
        {
            "record_id": "routine-snapshot-1",
            "record_kind": "graph_record",
            "record_type": "routine_snapshot",
            "producer_node_id": "routine-snapshot",
            "port": "snapshot",
            "schema": "RoutineSnapshot",
            "value": {"routine_id": "routine-1"},
        },
        1,
    )

    with pytest.raises(ValidationError):
        reduce_event(initial_projection(), malformed)
