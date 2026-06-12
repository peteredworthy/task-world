"""Unit tests for the pure graph command applier."""

from datetime import timedelta
from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    SequentialIdGenerator,
    apply_command,
    initial_projection,
    project_task_states,
    reduce_event,
)


def _event(event_type: str, payload: dict[str, Any], position: int = -1) -> EventEnvelope:
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


def _project(events: list[EventEnvelope]):
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _apply(
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any] | None = None,
) -> list[EventEnvelope]:
    clock = FakeClock()
    return apply_command(
        _project(events),
        events,
        command_type,
        payload or {"run_id": "run-1"},
        clock,
        SequentialIdGenerator(),
    )


def _callback_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": "run-1",
        "node_id": "worker-1",
        "execution_id": "exec-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "base_snapshot_id": "S0",
        "observed_graph_position": 1,
        "idempotency_key": "key-1",
        "payload_hash": "hash-a",
    }
    payload.update(overrides)
    return payload


def _active_lease_events() -> list[EventEnvelope]:
    return [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "running"}, 1),
        _event("lease_granted", {"node_id": "worker-1", "lease_id": "lease-1", "generation": 1}, 2),
    ]


def _leased_lease_events() -> list[EventEnvelope]:
    return [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "leased"}, 1),
        _event(
            "lease_granted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
                "base_snapshot_id": "S0",
            },
            2,
        ),
    ]


def test_lifecycle_legal_transitions() -> None:
    cases = [
        ([], "accept_run", "queued"),
        ([_event("run_lifecycle_changed", {"to_state": "queued"}, 0)], "start", "active"),
        ([_event("run_lifecycle_changed", {"to_state": "active"}, 0)], "pause", "pausing"),
        ([_event("run_lifecycle_changed", {"to_state": "pausing"}, 0)], "pause", "paused"),
        ([_event("run_lifecycle_changed", {"to_state": "paused"}, 0)], "resume", "resuming"),
        ([_event("run_lifecycle_changed", {"to_state": "resuming"}, 0)], "resume", "active"),
        ([_event("run_lifecycle_changed", {"to_state": "active"}, 0)], "cancel", "cancelling"),
        ([_event("run_lifecycle_changed", {"to_state": "paused"}, 0)], "cancel", "cancelling"),
        ([_event("run_lifecycle_changed", {"to_state": "cancelling"}, 0)], "cancel", "cancelled"),
        ([_event("run_lifecycle_changed", {"to_state": "active"}, 0)], "complete", "completed"),
        ([_event("run_lifecycle_changed", {"to_state": "queued"}, 0)], "fail", "failed"),
    ]

    for events, command_type, expected_state in cases:
        output = _apply(events, command_type)

        assert output[0].event_type == "run_lifecycle_changed"
        assert output[0].payload["to_state"] == expected_state


def test_lifecycle_illegal_transition_rejected() -> None:
    output = _apply([_event("run_lifecycle_changed", {"to_state": "queued"}, 0)], "complete")

    assert output[0].event_type == "command_rejected"
    assert output[0].payload["command_type"] == "complete"


def test_callback_accept_emits_boundary_events() -> None:
    output = _apply(_active_lease_events(), "submit_callback", _callback_payload())

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "node_state_changed",
        "lease_released",
    ]


def test_callback_before_acknowledge_start_rejected_and_leaves_lease_intact() -> None:
    events = _leased_lease_events()

    output = _apply(events, "submit_callback", _callback_payload())

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == "node not running: leased"

    projected = _project([*events, *output])
    assert projected["node_states"]["worker-1"] == "leased"
    assert projected["leases"]["lease-1"]["state"] == "active"


def test_callback_claiming_non_mutating_cannot_complete_leased_node() -> None:
    """is_mutating=False is not trusted: completion is derived as a mutation."""
    events = _leased_lease_events()

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(is_mutating=False),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == "node not running: leased"

    projected = _project([*events, *output])
    assert projected["node_states"]["worker-1"] == "leased"
    assert projected["leases"]["lease-1"]["state"] == "active"


def test_schedule_tick_defers_node_without_base_snapshot() -> None:
    """The kernel never fabricates a base snapshot identity (no 'S0' fallback)."""
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "ready"}, 1),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1"})

    assert not any(event.event_type == "lease_granted" for event in output)
    assert any(
        event.event_type == "node_deferred"
        and event.payload == {"node_id": "worker-1", "reason": "missing_base_snapshot"}
        for event in output
    )


def test_callback_after_acknowledge_start_accepts_boundary() -> None:
    events = _leased_lease_events()
    start_output = _apply(
        events,
        "acknowledge_start",
        {
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "execution_id": "exec-1",
        },
    )

    output = _apply([*events, *start_output], "submit_callback", _callback_payload())

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "node_state_changed",
        "lease_released",
    ]


def test_callback_accepts_output_records_and_binds_downstream_inputs() -> None:
    events = [
        *_active_lease_events(),
        _event(
            "node_created", {"node_id": "verifier-1", "kind": "verifier", "state": "planned"}, 3
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-candidate",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "required": True,
            },
            4,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-a",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "done"},
                    }
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "input_bound",
        "node_state_changed",
        "lease_released",
    ]
    assert output[2].payload == {
        "edge_id": "edge-candidate",
        "to_node_id": "verifier-1",
        "to_port": "candidate_under_test",
        "record_ids": ["candidate-1"],
        "bound_at_position": 0,
    }

    projected = _project([*events, *output])
    schedule_output = apply_command(
        projected,
        [*events, *output],
        "schedule_tick",
        {"run_id": "run-1", "base_snapshot_id": "S0"},
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert any(
        event.event_type == "lease_granted" and event.payload["node_id"] == "verifier-1"
        for event in schedule_output
    )


def test_verifier_callback_accepts_verification_record_for_bound_candidate() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
                "attempt_number": 1,
                "candidate_id": "candidate-1",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
                "attempt_number": 1,
                "value": {},
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "state": "running",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
            },
            3,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            4,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "verifier-1",
                "lease_id": "lease-v",
                "generation": 1,
                "execution_id": "exec-v",
                "base_snapshot_id": "S0",
            },
            5,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            node_id="verifier-1",
            lease_id="lease-v",
            execution_id="exec-v",
            idempotency_key="verify-key",
            payload={
                "payload_hash": "hash-v",
                "output_records": [
                    {
                        "record_id": "verification-1",
                        "record_kind": "verification",
                        "producer_node_id": "verifier-1",
                        "port": "verification_report",
                        "schema": "VerificationReport",
                        "candidate_id": "candidate-1",
                        "verdict": "passed",
                        "value": {"grades": []},
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "verification_passed",
        "node_state_changed",
        "lease_released",
    ]
    assert output[2].payload["candidate_id"] == "candidate-1"


def test_verifier_callback_rejects_unbound_verification_candidate() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "state": "running",
                "task_region_id": "task-1",
            },
            1,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            2,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "verifier-1",
                "lease_id": "lease-v",
                "generation": 1,
                "execution_id": "exec-v",
                "base_snapshot_id": "S0",
            },
            3,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            node_id="verifier-1",
            lease_id="lease-v",
            execution_id="exec-v",
            idempotency_key="verify-key",
            payload={
                "payload_hash": "hash-v",
                "output_records": [
                    {
                        "record_id": "verification-1",
                        "record_kind": "verification",
                        "producer_node_id": "verifier-1",
                        "port": "verification_report",
                        "schema": "VerificationReport",
                        "candidate_id": "other-candidate",
                        "verdict": "passed",
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "not bound" in output[0].payload["reason"]


def test_worker_smuggled_verification_record_rejected_atomically() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "running",
                "task_region_id": "task-1",
                "candidate_id": "candidate-1",
            },
            1,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
                "base_snapshot_id": "S0",
            },
            2,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-v",
                "output_records": [
                    {
                        "record_id": "verification-forged",
                        "record_kind": "verification",
                        "producer_node_id": "worker-1",
                        "port": "verification_report",
                        "schema": "VerificationReport",
                        "candidate_id": "candidate-1",
                        "verdict": "passed",
                    }
                ],
            },
        ),
    )

    event_types = [event.event_type for event in output]
    assert event_types == ["callback_rejected_conflict"]
    assert "not produced by a verifier" in output[0].payload["reason"]
    assert "callback_accepted" not in event_types
    assert "output_record_accepted" not in event_types
    assert "verification_passed" not in event_types

    projected = _project([*events, *output])
    assert projected["node_states"]["worker-1"] == "running"
    assert projected["leases"]["lease-1"]["state"] == "active"
    assert project_task_states([*events, *output]).get("task-1") != "accepted"


def test_callback_rejects_output_record_producer_forgery_without_partial_events() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"}, 1),
        _event(
            "node_created",
            {"node_id": "consumer-1", "kind": "verifier", "state": "blocked"},
            2,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-candidate",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "consumer-1",
                "to_port": "candidate_under_test",
                "required": True,
            },
            3,
        ),
        _event(
            "node_created",
            {"node_id": "verifier-evil", "kind": "verifier", "state": "running"},
            4,
        ),
        _event(
            "lease_granted",
            {"node_id": "verifier-evil", "lease_id": "lease-evil", "generation": 1},
            5,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            node_id="verifier-evil",
            lease_id="lease-evil",
            execution_id="exec-evil",
            idempotency_key="evil-key",
            payload_hash="hash-evil",
            payload={
                "payload_hash": "hash-evil",
                "output_records": [
                    {
                        "record_id": "forged-candidate",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "worker never ran"},
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "producer_node_id does not match lease node" in output[0].payload["reason"]
    assert "output_record_accepted" not in [event.event_type for event in output]
    assert "input_bound" not in [event.event_type for event in output]

    projected = _project([*events, *output])
    assert "consumer-1" not in projected["input_bindings"]

    schedule_output = apply_command(
        projected,
        [*events, *output],
        "schedule_tick",
        {"run_id": "run-1", "max_grants": 10},
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert not any(
        event.event_type in {"node_ready", "lease_granted"}
        and event.payload.get("node_id") == "consumer-1"
        for event in schedule_output
    )
    assert any(
        event.event_type == "node_deferred"
        and event.payload
        == {
            "node_id": "consumer-1",
            "reason": "missing_required_input:candidate_under_test",
        }
        for event in schedule_output
    )


def test_callback_with_mixed_honest_and_forged_records_rejected_atomically() -> None:
    events = [
        *_active_lease_events(),
        _event("node_created", {"node_id": "other-1", "kind": "worker", "state": "planned"}, 3),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-mixed",
                "output_records": [
                    {
                        "record_id": "honest-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "real"},
                    },
                    {
                        "record_id": "forged-1",
                        "record_kind": "output",
                        "producer_node_id": "other-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "forged"},
                    },
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "producer_node_id does not match lease node" in output[0].payload["reason"]


def test_callback_rejects_forged_file_state_record_atomically() -> None:
    events = [
        *_active_lease_events(),
        _event("node_created", {"node_id": "other-1", "kind": "worker", "state": "planned"}, 3),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-file-state",
                "output_records": [
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "other-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                    }
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "producer_node_id does not match lease node" in output[0].payload["reason"]
    assert "file_state_accepted" not in [event.event_type for event in output]


def test_callback_rejects_forged_file_state_rejected_node_id() -> None:
    output = _apply(
        _active_lease_events(),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-file-state-rejected",
                "output_records": [],
                "file_state_rejected": {
                    "record_kind": "file_state_rejected",
                    "run_id": "run-1",
                    "node_id": "other-1",
                    "reason": "file_state_rejected",
                    "classifications": [],
                    "rejected_paths": [],
                    "residue": [],
                },
            },
            complete_node=False,
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "file_state_rejected node_id does not match lease node" in output[0].payload["reason"]
    assert "file_state_rejected" not in [event.event_type for event in output]


def test_callback_accepts_unmatched_output_port_without_binding_input() -> None:
    events = [
        *_active_lease_events(),
        _event(
            "node_created", {"node_id": "verifier-1", "kind": "verifier", "state": "blocked"}, 3
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-candidate",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "required": True,
            },
            4,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-a",
                "output_records": [
                    {
                        "record_id": "diagnostic-1",
                        "record_kind": "output",
                        "port": "diagnostic",
                        "schema": "DiagnosticRecord",
                        "value": {"summary": "not a candidate"},
                    }
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "node_state_changed",
        "lease_released",
    ]
    assert output[1].payload["producer_node_id"] == "worker-1"
    assert output[1].payload["port"] == "diagnostic"


def test_callback_rejected_stale() -> None:
    events = [
        *_active_lease_events(),
        _event("lease_revoked", {"node_id": "worker-1", "lease_id": "lease-1"}, 3),
    ]

    output = _apply(events, "submit_callback", _callback_payload())

    assert output[0].event_type == "callback_rejected_stale"


def test_callback_rejected_conflict() -> None:
    events = [
        *_active_lease_events(),
        _event(
            "callback_accepted",
            {
                "node_id": "worker-1",
                "idempotency_key": "key-1",
                "payload": {"payload_hash": "hash-b"},
            },
            3,
        ),
    ]

    output = _apply(events, "submit_callback", _callback_payload())

    assert output[0].event_type == "callback_rejected_conflict"


def test_callback_duplicate_returned() -> None:
    events = [
        *_active_lease_events(),
        _event(
            "callback_accepted",
            {
                "node_id": "worker-1",
                "idempotency_key": "key-1",
                "payload": {"payload_hash": "hash-a"},
            },
            3,
        ),
    ]

    output = _apply(events, "submit_callback", _callback_payload())

    assert output[0].event_type == "callback_duplicate_returned"


def test_patch_accept_emits_graph_events() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-1",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {"node_id": "artifact-1", "kind": "artifact", "state": "planned"},
                }
            ],
        },
    )

    assert [event.event_type for event in output] == ["graph_patch_accepted", "node_created"]


def test_patch_accept_emits_events_for_all_v1_ops() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "worker-claim",
                "kind": "worker",
                "state": "planned",
                "resource_claims": [{"mode": "graph_write", "scope": "repo"}],
            },
            0,
        ),
        _event(
            "node_created", {"node_id": "worker-actions", "kind": "worker", "state": "planned"}, 1
        ),
    ]
    output = _apply(
        events,
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-v1",
            "proposed_by_node_id": "oversight-1",
            "actor_role": "oversight",
            "base_graph_position": 1,
            "ops": [
                {
                    "op": "create_gate",
                    "node_id": "gate-1",
                    "task_region_id": "task-1",
                    "predecessor_node_ids": ["worker-claim"],
                },
                {
                    "op": "create_revision_attempt",
                    "task_region_id": "task-1",
                    "failed_candidate_id": "cand-1",
                    "worker_node": {
                        "node_id": "worker-revision-2",
                        "kind": "worker",
                        "state": "planned",
                    },
                },
                {
                    "op": "create_appeal",
                    "node_id": "appeal-1",
                    "appealed_node_id": "verify-1",
                    "appeal_type": "invalid_test",
                },
                {
                    "op": "set_resource_claims",
                    "node_id": "worker-claim",
                    "resource_claims": [{"mode": "read", "scope": "repo"}],
                },
                {
                    "op": "set_allowed_actions",
                    "node_id": "worker-actions",
                    "allowed_actions": ["submit_records"],
                },
                {
                    "op": "mark_plan_region_suspect",
                    "region_node_ids": ["region-1"],
                    "reason": "requirement_changed",
                },
            ],
        },
    )

    assert [event.event_type for event in output] == [
        "graph_patch_accepted",
        "node_created",
        "revision_created",
        "node_created",
        "node_created",
        "appeal_opened",
        "node_authority_changed",
        "node_authority_changed",
        "plan_region_marked_suspect",
    ]
    assert output[1].payload["kind"] == "gate"
    assert output[3].payload["kind"] == "worker"
    assert output[4].payload["kind"] == "appeal"
    assert output[6].payload["resource_claims"] == [{"mode": "read", "scope": "repo"}]
    assert output[7].payload["allowed_actions"] == ["submit_records"]


def test_patch_reject_emits_rejection() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-1",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [{"op": "create_gate", "predecessor_node_ids": ["worker-1"]}],
        },
    )

    assert output[0].event_type == "graph_patch_rejected"
    assert "cannot perform create_gate" in output[0].payload["reason"]


def test_seed_compiled_events_accepts_topology_only_for_empty_run() -> None:
    seed_events = [
        _event("node_created", {"node_id": "root", "kind": "root", "state": "completed"}, 0),
        _event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "state": "planned"},
            1,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-1",
                "from_node_id": "root",
                "from_port": "snapshot",
                "to_node_id": "worker-1",
                "to_port": "routine_snapshot",
                "required": True,
            },
            2,
        ),
        _event(
            "input_bound",
            {"edge_id": "edge-1", "to_node_id": "worker-1", "to_port": "routine_snapshot"},
            3,
        ),
    ]

    output = _apply([], "seed_compiled_events", {"run_id": "run-1", "events": seed_events})

    assert output == seed_events


def test_seed_compiled_events_rejects_already_seeded_run() -> None:
    events = [_event("node_created", {"node_id": "root", "kind": "root", "state": "completed"}, 0)]

    output = _apply(events, "seed_compiled_events", {"run_id": "run-1", "events": events})

    assert output[0].event_type == "command_rejected"
    assert output[0].payload["reason"] == "run topology already seeded"


def test_schedule_tick_grants_leases() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "ready",
                "resource_claims": [{"mode": "read", "scope": "repo", "paths": ["src/a.py"]}],
            },
            1,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert [event.event_type for event in output] == [
        "node_ready",
        "lease_granted",
        "node_state_changed",
    ]
    assert output[1].payload["node_id"] == "worker-1"


def test_schedule_tick_marks_planned_node_ready_when_required_input_bound() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created", {"node_id": "producer-1", "kind": "worker", "state": "completed"}, 1
        ),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"}, 2),
        _event(
            "edge_created",
            {
                "edge_id": "edge-1",
                "from_node_id": "producer-1",
                "from_port": "candidate",
                "to_node_id": "worker-1",
                "to_port": "candidate",
                "required": True,
            },
            3,
        ),
        _event(
            "input_bound",
            {"edge_id": "edge-1", "to_node_id": "worker-1", "to_port": "candidate"},
            4,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert [event.event_type for event in output] == [
        "node_ready",
        "node_state_changed",
        "lease_granted",
        "node_state_changed",
    ]
    assert output[0].payload["node_id"] == "worker-1"
    assert output[1].payload == {
        "node_id": "worker-1",
        "new_state": "ready",
        "trigger": "readiness_evaluator",
    }


def test_schedule_tick_defers_missing_required_input() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created", {"node_id": "producer-1", "kind": "worker", "state": "completed"}, 1
        ),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "blocked"}, 2),
        _event(
            "edge_created",
            {
                "edge_id": "edge-1",
                "from_node_id": "producer-1",
                "from_port": "candidate",
                "to_node_id": "worker-1",
                "to_port": "candidate",
                "required": True,
            },
            3,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert [(event.event_type, event.payload) for event in output] == [
        ("node_deferred", {"node_id": "worker-1", "reason": "missing_required_input:candidate"})
    ]


def test_schedule_tick_defers_unapproved_gate_input() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "gate-1", "kind": "gate", "state": "completed"}, 1),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "blocked"}, 2),
        _event(
            "edge_created",
            {
                "edge_id": "edge-gate",
                "from_node_id": "gate-1",
                "from_port": "decision",
                "to_node_id": "worker-1",
                "to_port": "approval",
                "required": True,
            },
            3,
        ),
        _event(
            "input_bound",
            {"edge_id": "edge-gate", "to_node_id": "worker-1", "to_port": "approval"},
            4,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert [(event.event_type, event.payload) for event in output] == [
        ("node_deferred", {"node_id": "worker-1", "reason": "gate_not_approved:gate-1"})
    ]


def test_schedule_tick_allows_approved_gate_input() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "gate-1", "kind": "gate", "state": "completed"}, 1),
        _event("approval_decision_recorded", {"node_id": "gate-1", "decision": "approved"}, 2),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "blocked"}, 3),
        _event(
            "edge_created",
            {
                "edge_id": "edge-gate",
                "from_node_id": "gate-1",
                "from_port": "decision",
                "to_node_id": "worker-1",
                "to_port": "approval",
                "required": True,
            },
            4,
        ),
        _event(
            "input_bound",
            {"edge_id": "edge-gate", "to_node_id": "worker-1", "to_port": "approval"},
            5,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert [event.event_type for event in output] == [
        "node_ready",
        "node_state_changed",
        "lease_granted",
        "node_state_changed",
    ]


def test_schedule_tick_projection_ready_state_comes_from_node_state_changed() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"}, 1),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "max_grants": 0})
    projection = _project([*events, *output])

    assert [event.event_type for event in output] == [
        "node_ready",
        "node_state_changed",
        "node_deferred",
    ]
    assert output[1].payload["new_state"] == "ready"
    assert output[2].payload["reason"] == "max_grants_reached"
    assert projection["node_states"]["worker-1"] == "ready"
    assert projection["ready_nodes"] == ["worker-1"]


def test_schedule_tick_check_precondition_requires_command_definition() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "check-1", "kind": "check", "state": "planned"}, 1),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert [(event.event_type, event.payload) for event in output] == [
        (
            "node_deferred",
            {"node_id": "check-1", "reason": "precondition_failed:has_command_definition"},
        )
    ]


def test_schedule_tick_check_precondition_passes_with_command_definition() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "planned",
                "command_definition": {"argv": ["uv", "run", "pytest"]},
            },
            1,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert [event.event_type for event in output] == [
        "node_ready",
        "node_state_changed",
        "lease_granted",
        "node_state_changed",
    ]


def test_schedule_tick_external_claim_missing_key_is_invalid() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "external-1",
                "kind": "worker",
                "state": "planned",
                "resource_claims": [{"mode": "external", "scope": "external"}],
            },
            1,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert [(event.event_type, event.payload) for event in output] == [
        ("node_deferred", {"node_id": "external-1", "reason": "invalid_claim:external_missing_key"})
    ]


def test_acknowledge_start_validates_lease_identity_and_marks_running() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "planner-1", "kind": "planner", "state": "leased"}, 1),
        _event(
            "lease_granted",
            {
                "node_id": "planner-1",
                "lease_id": "lease-planner-1",
                "generation": 1,
                "execution_id": "exec-planner-1",
            },
            2,
        ),
    ]

    output = _apply(
        events,
        "acknowledge_start",
        {
            "run_id": "run-1",
            "node_id": "planner-1",
            "lease_id": "lease-planner-1",
            "lease_generation": 1,
            "execution_id": "exec-planner-1",
        },
    )

    assert [(event.event_type, event.payload) for event in output] == [
        (
            "node_state_changed",
            {
                "node_id": "planner-1",
                "new_state": "running",
                "trigger": "runtime_start_acknowledged",
            },
        )
    ]


def test_acknowledge_start_rejects_wrong_execution_id() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "planner-1", "kind": "planner", "state": "leased"}, 1),
        _event(
            "lease_granted",
            {
                "node_id": "planner-1",
                "lease_id": "lease-planner-1",
                "generation": 1,
                "execution_id": "exec-planner-1",
            },
            2,
        ),
    ]

    output = _apply(
        events,
        "acknowledge_start",
        {
            "run_id": "run-1",
            "node_id": "planner-1",
            "lease_id": "lease-planner-1",
            "lease_generation": 1,
            "execution_id": "exec-other",
        },
    )

    assert output[0].event_type == "command_rejected"
    assert output[0].payload["reason"] == "execution_incompatible"


def test_agent_died_revokes_active_lease_and_requeues_node() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "running"}, 1),
        _event(
            "lease_granted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
            },
            2,
        ),
    ]

    output = _apply(
        events,
        "agent_died",
        {
            "run_id": "run-1",
            "lease_id": "lease-1",
            "execution_id": "exec-1",
            "reason": "process_exit",
        },
    )
    projection = _project([*events, *output])

    assert [event.event_type for event in output] == [
        "agent_died",
        "lease_revoked",
        "runtime_retry_scheduled",
        "node_state_changed",
    ]
    assert output[0].payload == {
        "lease_id": "lease-1",
        "node_id": "worker-1",
        "generation": 1,
        "execution_id": "exec-1",
        "reason": "process_exit",
    }
    assert output[2].payload["policy"] == "v1_requeue_same_node_after_agent_death"
    assert output[3].payload == {
        "node_id": "worker-1",
        "new_state": "ready",
        "trigger": "agent_died_retry_scheduled",
    }
    assert projection["leases"]["lease-1"]["state"] == "revoked"
    assert projection["node_states"]["worker-1"] == "ready"


def test_agent_died_rejects_unknown_or_inactive_lease() -> None:
    inactive_events = [
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "running"}, 0),
        _event(
            "lease_granted",
            {"node_id": "worker-1", "lease_id": "lease-1", "generation": 1},
            1,
        ),
        _event("lease_revoked", {"node_id": "worker-1", "lease_id": "lease-1"}, 2),
    ]

    unknown_output = _apply([], "agent_died", {"run_id": "run-1", "lease_id": "missing-lease"})
    inactive_output = _apply(
        inactive_events,
        "agent_died",
        {"run_id": "run-1", "lease_id": "lease-1"},
    )

    assert unknown_output[0].event_type == "command_rejected"
    assert unknown_output[0].payload["reason"] == "unknown lease"
    assert inactive_output[0].event_type == "command_rejected"
    assert inactive_output[0].payload["reason"] == "lease not active"


def test_agent_died_requires_execution_id_when_lease_records_one() -> None:
    """A lease bound to an execution cannot be revoked without presenting it."""
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "running"}, 1),
        _event(
            "lease_granted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
            },
            2,
        ),
    ]

    omitted = _apply(events, "agent_died", {"run_id": "run-1", "lease_id": "lease-1"})
    mismatched = _apply(
        events,
        "agent_died",
        {"run_id": "run-1", "lease_id": "lease-1", "execution_id": "exec-other"},
    )
    matching = _apply(
        events,
        "agent_died",
        {"run_id": "run-1", "lease_id": "lease-1", "execution_id": "exec-1"},
    )

    assert omitted[0].event_type == "command_rejected"
    assert omitted[0].payload["reason"] == "missing execution_id"
    assert mismatched[0].event_type == "command_rejected"
    assert mismatched[0].payload["reason"] == "execution_incompatible"
    assert matching[0].event_type == "agent_died"


def test_schedule_tick_expires_past_leases_only() -> None:
    clock = FakeClock()
    past = (clock.now() - timedelta(seconds=1)).isoformat()
    future = (clock.now() + timedelta(seconds=60)).isoformat()
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "lease_granted",
            {"node_id": "worker-1", "lease_id": "past-lease", "expires_at": past},
            1,
        ),
        _event(
            "lease_granted",
            {"node_id": "worker-2", "lease_id": "future-lease", "expires_at": future},
            2,
        ),
    ]

    output = apply_command(
        _project(events),
        events,
        "schedule_tick",
        {"run_id": "run-1", "base_snapshot_id": "S0"},
        clock,
        SequentialIdGenerator(),
    )

    assert [
        event.payload["lease_id"] for event in output if event.event_type == "lease_expired"
    ] == ["past-lease"]


def test_raise_appeal_accepts_well_formed() -> None:
    output = _apply(
        [],
        "raise_appeal",
        {"run_id": "run-1", "node_id": "verify-1", "appeal_type": "invalid_test"},
    )

    assert [event.event_type for event in output] == ["appeal_opened", "node_created"]
    assert output[1].payload["kind"] == "oversight"


def test_raise_appeal_rejects_malformed() -> None:
    output = _apply([], "raise_appeal", {"run_id": "run-1", "node_id": "verify-1"})

    assert output[0].event_type == "command_rejected"


def test_record_decision_accepts_approval() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "gate-1",
                "kind": "gate",
                "state": "blocked",
                "task_region_id": "task-1",
            },
            1,
        ),
    ]

    output = _apply(
        events,
        "record_decision",
        {
            "run_id": "run-1",
            "decision_type": "approval",
            "node_id": "gate-1",
            "decision": "approved",
            "decider": {"kind": "human", "id": "alice"},
        },
    )

    assert [event.event_type for event in output] == [
        "approval_decision_recorded",
        "node_state_changed",
    ]
    assert output[0].payload["task_region_id"] == "task-1"
    assert output[1].payload["new_state"] == "completed"


def test_record_decision_rejects_missing_target() -> None:
    output = _apply([], "record_decision", {"run_id": "run-1", "decision_type": "approval"})

    assert output[0].event_type == "command_rejected"
    assert "missing target node_id" in output[0].payload["reason"]


def test_record_decision_rejects_invalid_decision() -> None:
    output = _apply(
        [_event("node_created", {"node_id": "gate-1", "kind": "gate", "state": "blocked"}, 0)],
        "record_decision",
        {
            "run_id": "run-1",
            "decision_type": "approval",
            "node_id": "gate-1",
            "decision": "maybe",
            "decider": {"kind": "human", "id": "alice"},
        },
    )

    assert output[0].event_type == "command_rejected"
    assert "invalid decision value" in output[0].payload["reason"]


def test_record_decision_rejects_missing_decider() -> None:
    output = _apply(
        [_event("node_created", {"node_id": "gate-1", "kind": "gate", "state": "blocked"}, 0)],
        "record_decision",
        {
            "run_id": "run-1",
            "decision_type": "approval",
            "node_id": "gate-1",
            "decision": "approved",
        },
    )

    assert output[0].event_type == "command_rejected"
    assert "missing decider actor" in output[0].payload["reason"]


def test_record_decision_rejects_unknown_target() -> None:
    output = _apply(
        [],
        "record_decision",
        {
            "run_id": "run-1",
            "decision_type": "approval",
            "node_id": "missing-gate",
            "decision": "approved",
            "decider": {"kind": "human", "id": "alice"},
        },
    )

    assert output[0].event_type == "command_rejected"
    assert "unknown target node" in output[0].payload["reason"]


def test_record_decision_rejects_terminal_target() -> None:
    output = _apply(
        [_event("node_created", {"node_id": "gate-1", "kind": "gate", "state": "completed"}, 0)],
        "record_decision",
        {
            "run_id": "run-1",
            "decision_type": "approval",
            "node_id": "gate-1",
            "decision": "approved",
            "decider": {"kind": "human", "id": "alice"},
        },
    )

    assert output[0].event_type == "command_rejected"
    assert "terminal target node" in output[0].payload["reason"]


def test_record_decision_rejects_terminal_run() -> None:
    output = _apply(
        [
            _event("run_lifecycle_changed", {"to_state": "cancelled"}, 0),
            _event("node_created", {"node_id": "gate-1", "kind": "gate", "state": "blocked"}, 1),
        ],
        "record_decision",
        {
            "run_id": "run-1",
            "decision_type": "approval",
            "node_id": "gate-1",
            "decision": "approved",
            "decider": {"kind": "human", "id": "alice"},
        },
    )

    assert output[0].event_type == "command_rejected"
    assert "terminal run" in output[0].payload["reason"]
