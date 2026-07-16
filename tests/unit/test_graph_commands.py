"""Unit tests for the pure graph command applier."""

from datetime import timedelta
from pathlib import Path
from typing import Any

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    GraphCommandContext,
    PatchCommandContext,
    SequentialIdGenerator,
    apply_command as apply_graph_command,
    initial_projection,
    project_requirement_freshness_facts,
    project_task_states,
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
)
from tests.unit.graph_test_utils import canonical_event_payload


def _event(
    event_type: str,
    payload: dict[str, Any],
    position: int = -1,
    *,
    canonicalize: bool = True,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=canonical_event_payload(event_type, payload) if canonicalize else payload,
    )


def _project(events: list[EventEnvelope]):
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _legacy_has_passed_completion_decision(events: list[EventEnvelope]) -> bool:
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        if event.payload.get("record_type") != "completion_decision":
            continue
        if event.payload.get("port") != "completion_decision":
            continue
        value = event.payload.get("value")
        if isinstance(value, dict) and value.get("status") == "passed":
            return True
    return False


def _legacy_retry_not_before(events: list[EventEnvelope], node_id: str) -> str | None:
    retry_not_before: str | None = None
    for event in events:
        if event.event_type != "runtime_retry_scheduled":
            continue
        if event.payload.get("node_id") != node_id:
            continue
        value = event.payload.get("retry_not_before")
        retry_not_before = value if isinstance(value, str) and value else None
    return retry_not_before


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
        payload or {},
        clock,
        SequentialIdGenerator(),
    )


def _apply_from_checkpoint(
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any] | None = None,
) -> list[EventEnvelope]:
    projection = projection_from_checkpoint(projection_to_checkpoint(_project(events)))
    return apply_command(
        projection,
        events,
        command_type,
        payload or {},
        FakeClock(),
        SequentialIdGenerator(),
    )


def apply_command(
    projection: Any,
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any],
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> list[EventEnvelope]:
    command_payload, context = _command_input(events, command_type, payload)
    return apply_graph_command(
        projection,
        events,
        command_type,
        command_payload,
        context,
        clock,
        id_gen,
    )


def _command_input(
    events: list[EventEnvelope],
    command_type: str,
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], GraphCommandContext]:
    command_payload = dict(payload or {})
    run_id = command_payload.pop("run_id", events[-1].run_id if events else "run-1")
    current_position = command_payload.pop(
        "_current_graph_position",
        max((event.position for event in events), default=-1),
    )
    actor_role = command_payload.pop("actor_role", None)
    proposed_by_node_id = command_payload.pop("proposed_by_node_id", None)
    if command_type == "submit_patch":
        return command_payload, PatchCommandContext(
            run_id=run_id,
            current_graph_position=current_position,
            proposed_by_node_id=proposed_by_node_id or "controller",
            actor_role=actor_role or "planner",
        )
    actor = Actor(kind=ActorKind.HUMAN, role=actor_role) if isinstance(actor_role, str) else None
    return command_payload, GraphCommandContext(
        run_id=run_id,
        current_graph_position=current_position,
        actor=actor,
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
        "payload": {
            "payload_hash": "hash-a",
            "output_records": [
                {
                    "record_id": "candidate-1",
                    "record_kind": "output",
                    "record_type": "candidate",
                    "producer_node_id": "worker-1",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "candidate_id": "candidate-1",
                    "value": {"summary": "done"},
                },
                {
                    "record_id": "file-state-1",
                    "record_kind": "file_state",
                    "producer_node_id": "worker-1",
                    "port": "file_state",
                    "schema": "FileStateRecord",
                    "snapshot_id": "snapshot-1",
                    "base_snapshot_id": "S0",
                    "verdict": "captured",
                },
            ],
        },
    }
    payload.update(overrides)
    return payload


def test_command_raw_event_scan_count_is_bounded() -> None:
    commands_source = (
        Path(__file__).resolve().parents[2] / "src" / "orchestrator" / "graph" / "_commands.py"
    ).read_text()

    assert commands_source.count("for event in events") <= 2


def test_projection_fields_match_legacy_scans_for_completion_and_retry() -> None:
    completion_events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created", {"node_id": "gate-final", "kind": "final_gate", "state": "ready"}, 1
        ),
    ]
    decision_events = _apply(
        completion_events,
        "evaluate_final_gate",
        {"run_id": "run-1", "node_id": "gate-final", "record_id": "decision-1"},
    )
    completion_stream = [*completion_events, *decision_events]
    completion_projection = _project(completion_stream)

    assert completion_projection["completion_decision_passed"] is True
    assert completion_projection[
        "completion_decision_passed"
    ] == _legacy_has_passed_completion_decision(completion_stream)

    retry_events = [
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
    clock = FakeClock()
    retry_output = apply_command(
        _project(retry_events),
        retry_events,
        "agent_died",
        {
            "run_id": "run-1",
            "lease_id": "lease-1",
            "execution_id": "exec-1",
            "reason": "process_exit",
            "retry_backoff_seconds": 60,
        },
        clock,
        SequentialIdGenerator(),
    )
    retry_stream = [*retry_events, *retry_output]
    retry_projection = _project(retry_stream)

    assert retry_projection["retry_not_before_by_node"]["worker-1"] == _legacy_retry_not_before(
        retry_stream, "worker-1"
    )


def _active_lease_events() -> list[EventEnvelope]:
    return [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "running"}, 1),
        _event("lease_granted", {"node_id": "worker-1", "lease_id": "lease-1", "generation": 1}, 2),
    ]


def _active_lease_events_with_resource_claims(
    resource_claims: list[dict[str, Any]],
) -> list[EventEnvelope]:
    return [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "running"}, 1),
        _event(
            "lease_granted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "generation": 1,
                "resource_claims": resource_claims,
            },
            2,
        ),
    ]


def _planner_active_lease_events() -> list[EventEnvelope]:
    return [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {"node_id": "planner-1", "kind": "planner", "role": "planner", "state": "running"},
            1,
        ),
        _event(
            "lease_granted",
            {"node_id": "planner-1", "lease_id": "lease-1", "generation": 1},
            2,
        ),
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

        lifecycle_event = next(
            event for event in output if event.event_type == "run_lifecycle_changed"
        )
        assert lifecycle_event.payload["to_state"] == expected_state


def test_cancel_revokes_active_lease_and_cancels_running_node() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "running"}, 1),
        _event(
            "lease_granted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "generation": 2,
                "execution_id": "exec-1",
            },
            2,
        ),
    ]

    output = _apply(events, "cancel")

    assert [event.event_type for event in output] == [
        "run_lifecycle_changed",
        "lease_revoked",
        "node_state_changed",
    ]
    assert output[1].payload == {
        "node_id": "worker-1",
        "lease_id": "lease-1",
        "trigger": "cancel_command_accepted",
        "reason": "run_cancelled",
        "generation": 2,
        "execution_id": "exec-1",
    }
    assert output[2].payload == {
        "node_id": "worker-1",
        "new_state": "cancelled",
        "trigger": "run_cancelled",
        "reason": "run_cancelled",
    }

    projected = _project([*events, *output])
    assert projected["leases"]["lease-1"].state == "revoked"
    assert projected["node_states"]["worker-1"] == "cancelled"


def test_cancel_revokes_suspended_lease_without_reopening_terminal_node() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "paused"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "failed"}, 1),
        _event("lease_granted", {"node_id": "worker-1", "lease_id": "lease-1"}, 2),
        _event("lease_suspended", {"node_id": "worker-1", "lease_id": "lease-1"}, 3),
    ]

    output = _apply(events, "cancel")

    assert [event.event_type for event in output] == ["run_lifecycle_changed", "lease_revoked"]
    projected = _project([*events, *output])
    assert projected["leases"]["lease-1"].state == "revoked"
    assert projected["node_states"]["worker-1"] == "failed"


def test_record_heartbeat_renews_active_lease() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "running"}, 1),
        _event(
            "lease_granted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "generation": 2,
                "execution_id": "exec-1",
                "expires_at": "2026-01-01T00:01:00+00:00",
            },
            2,
        ),
    ]

    output = _apply(
        events,
        "record_heartbeat",
        {"run_id": "run-1", "lease_id": "lease-1", "node_id": "worker-1", "ttl_seconds": 120},
    )

    assert [event.event_type for event in output] == ["heartbeat_recorded", "lease_renewed"]
    assert output[0].payload == {
        "lease_id": "lease-1",
        "node_id": "worker-1",
        "observed_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-01T00:02:00+00:00",
        "generation": 2,
        "execution_id": "exec-1",
    }
    assert output[1].payload == output[0].payload

    projected = _project([*events, *output])
    assert projected["leases"]["lease-1"].state == "active"
    assert projected["leases"]["lease-1"].expires_at == "2026-01-01T00:02:00+00:00"


def test_record_heartbeat_rejects_non_active_lease() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "running"}, 1),
        _event("lease_granted", {"node_id": "worker-1", "lease_id": "lease-1"}, 2),
        _event("lease_suspended", {"node_id": "worker-1", "lease_id": "lease-1"}, 3),
    ]

    output = _apply(
        events,
        "record_heartbeat",
        {"run_id": "run-1", "lease_id": "lease-1", "node_id": "worker-1"},
    )

    assert [event.event_type for event in output] == ["command_rejected"]
    assert output[0].payload == {
        "command_type": "record_heartbeat",
        "reason": "lease_not_active:suspended",
    }


def test_lifecycle_illegal_transition_rejected() -> None:
    output = _apply([_event("run_lifecycle_changed", {"to_state": "queued"}, 0)], "complete")

    assert output[0].event_type == "command_rejected"
    assert output[0].payload["command_type"] == "complete"


def test_lifecycle_complete_rejected_with_final_blocker_evidence() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
            1,
        ),
    ]

    output = _apply(events, "complete")

    assert [event.event_type for event in output] == ["command_rejected"]
    assert output[0].payload == {
        "command_type": "complete",
        "reason": "final invariant blockers remain",
        "blockers": [
            {
                "kind": "task_not_accepted",
                "reason": "task region has not reached accepted",
                "task_region_id": "task-1",
                "state": "pending",
            }
        ],
    }


def test_lifecycle_complete_accepts_clean_graph_without_blockers() -> None:
    output = _apply([_event("run_lifecycle_changed", {"to_state": "active"}, 0)], "complete")

    assert [event.event_type for event in output] == [
        "output_record_accepted",
        "run_lifecycle_changed",
    ]
    assert output[0].payload["record_type"] == "completion_decision"
    assert output[0].payload["producer_node_id"] == "run_lifecycle"
    assert output[0].payload["port"] == "completion_decision"
    assert output[0].payload["schema"] == "CompletionDecision"
    assert output[0].payload["value"] == {"status": "passed", "blockers": []}
    assert output[0].payload["provenance"] == {"source": "lifecycle_complete"}
    assert output[1].payload["to_state"] == "completed"


def test_evaluate_final_gate_emits_blocked_completion_decision() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created", {"node_id": "gate-final", "kind": "final_gate", "state": "ready"}, 1
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
            2,
        ),
    ]

    output = _apply(events, "evaluate_final_gate", {"run_id": "run-1", "node_id": "gate-final"})

    assert [event.event_type for event in output] == [
        "output_record_accepted",
        "node_state_changed",
    ]
    decision = output[0].payload
    assert decision["record_type"] == "completion_decision"
    assert decision["producer_node_id"] == "gate-final"
    assert decision["port"] == "completion_decision"
    assert decision["schema"] == "CompletionDecision"
    assert decision["value"] == {
        "status": "blocked",
        "blockers": [
            {
                "kind": "task_not_accepted",
                "reason": "task region has not reached accepted",
                "task_region_id": "task-1",
                "state": "pending",
            }
        ],
    }
    assert output[1].payload == {
        "node_id": "gate-final",
        "new_state": "completed",
        "trigger": "final_gate_evaluated",
        "completion_status": "blocked",
        "completion_decision_record_id": decision["record_id"],
    }


def test_evaluate_final_gate_releases_runtime_lease_when_present() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created", {"node_id": "gate-final", "kind": "final_gate", "state": "ready"}, 1
        ),
    ]

    output = _apply(
        events,
        "evaluate_final_gate",
        {
            "run_id": "run-1",
            "node_id": "gate-final",
            "lease_id": "lease-final",
            "lease_generation": 2,
        },
    )

    assert [event.event_type for event in output] == [
        "output_record_accepted",
        "node_state_changed",
        "lease_released",
    ]
    assert output[2].payload == {
        "node_id": "gate-final",
        "lease_id": "lease-final",
        "generation": 2,
    }


def test_evaluate_join_emits_join_result_and_releases_lease() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "completed"}, 1),
        _event("node_created", {"node_id": "check-1", "kind": "check", "state": "completed"}, 2),
        _event(
            "node_created",
            {"node_id": "join-1", "kind": "join", "role": "join", "state": "ready"},
            3,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-worker-join",
                "to_node_id": "join-1",
                "to_port": "source_record_1",
                "record_ids": ["candidate-1"],
            },
            4,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-check-join",
                "to_node_id": "join-1",
                "to_port": "source_record_2",
                "record_ids": ["check-result-1"],
            },
            5,
        ),
    ]

    output = _apply(
        events,
        "evaluate_join",
        {
            "run_id": "run-1",
            "node_id": "join-1",
            "lease_id": "lease-join",
            "lease_generation": 1,
        },
    )

    assert [event.event_type for event in output] == [
        "output_record_accepted",
        "node_state_changed",
        "lease_released",
    ]
    join_result = output[0].payload
    assert join_result["record_type"] == "join_result"
    assert join_result["producer_node_id"] == "join-1"
    assert join_result["port"] == "join_result"
    assert join_result["schema"] == "JoinResult"
    assert join_result["value"] == {
        "status": "ready",
        "source_record_ids": ["candidate-1", "check-result-1"],
    }
    assert output[1].payload["new_state"] == "completed"
    assert output[1].payload["trigger"] == "join_evaluated"
    assert output[2].payload == {
        "node_id": "join-1",
        "lease_id": "lease-join",
        "generation": 1,
    }


def test_evaluate_final_gate_passed_decision_allows_lifecycle_completion() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created", {"node_id": "gate-final", "kind": "final_gate", "state": "ready"}, 1
        ),
    ]

    decision_events = _apply(
        events,
        "evaluate_final_gate",
        {"run_id": "run-1", "node_id": "gate-final", "record_id": "decision-1"},
    )
    completion = _apply([*events, *decision_events], "complete")

    assert decision_events[0].payload["value"] == {"status": "passed", "blockers": []}
    assert [event.event_type for event in completion] == ["run_lifecycle_changed"]
    assert completion[0].payload["to_state"] == "completed"


def test_lifecycle_complete_rejected_when_final_gate_has_no_completion_decision() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {"node_id": "gate-final", "kind": "final_gate", "state": "completed"},
            1,
        ),
    ]

    output = _apply(events, "complete")

    assert [event.event_type for event in output] == ["command_rejected"]
    assert output[0].payload["blockers"] == [
        {
            "kind": "missing_completion_decision",
            "reason": "final gate has not produced a completion_decision",
            "node_id": "gate-final",
            "state": "completed",
        }
    ]


def test_record_requirement_revision_command_emits_replayable_policy_event() -> None:
    output = _apply(
        [],
        "record_requirement_revision",
        {
            "run_id": "run-1",
            "requirement_id": "R-1",
            "version_id": "R-1.v1",
            "classification": "semantic",
        },
    )

    assert [event.event_type for event in output] == ["requirement_revision_recorded"]
    assert project_requirement_freshness_facts(output) == [
        {
            "requirement_id": "R-1",
            "active_version_id": "R-1.v1",
            "revision_classification": "semantic",
            "requires_authority": True,
            "authority_required_reason": "semantic",
            "fresh_support_ids": [],
            "stale_support_ids": [],
            "unsupported": True,
        }
    ]


def test_record_support_evidence_command_uses_active_requirement_version() -> None:
    events = _apply(
        [],
        "record_requirement_revision",
        {
            "run_id": "run-1",
            "requirement_id": "R-1",
            "version_id": "R-1.v1",
            "classification": "initial",
        },
    )

    output = _apply(
        events,
        "record_support_evidence",
        {
            "run_id": "run-1",
            "support_id": "S-1",
            "evidence_id": "E-1",
            "requirement_id": "R-1",
        },
    )

    assert [event.event_type for event in output] == ["support_evidence_recorded"]
    assert output[0].payload["requirement_version_id"] == "R-1.v1"
    assert project_requirement_freshness_facts([*events, *output])[0]["unsupported"] is False


def test_record_support_evidence_rejects_unknown_active_requirement_version() -> None:
    output = _apply(
        [],
        "record_support_evidence",
        {
            "run_id": "run-1",
            "support_id": "S-1",
            "evidence_id": "E-1",
            "requirement_id": "R-1",
        },
    )

    assert [event.event_type for event in output] == ["command_rejected"]
    assert output[0].payload["command_type"] == "record_support_evidence"
    assert output[0].payload["reason"] == "unknown active requirement version: R-1"


def test_callback_accept_emits_boundary_events() -> None:
    output = _apply(_active_lease_events(), "submit_callback", _callback_payload())

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "output_record_accepted",
        "file_state_accepted",
        "node_state_changed",
        "lease_released",
    ]
    candidate_record = output[1].payload
    assert candidate_record["file_state_record_id"] == "file-state-1"
    assert candidate_record["file_state_record_ids"] == ["file-state-1"]
    assert candidate_record["value"]["file_state_record_ids"] == ["file-state-1"]
    assert candidate_record["provenance"]["file_state_record_ids"] == ["file-state-1"]


def test_callback_rejects_candidate_file_state_citation_mismatch() -> None:
    output = _apply(
        _active_lease_events(),
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
                        "file_state_record_ids": ["file-state-other"],
                        "value": {"summary": "done"},
                    },
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                    },
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "file_state_record_ids does not match bound records" in output[0].payload["reason"]


def test_callback_rejects_malformed_candidate_record() -> None:
    output = _apply(
        _active_lease_events(),
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
                        "value": {},
                    }
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "candidate record at index 0 is invalid" in output[0].payload["reason"]
    assert "Field required" in output[0].payload["reason"]


def test_callback_accepts_analysis_summary_record() -> None:
    output = _apply(
        _active_lease_events(),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-a",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "record_type": "candidate",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "candidate_id": "candidate-1",
                        "value": {"summary": "done"},
                    },
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                    },
                    {
                        "record_id": "summary-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "record_type": "analysis_summary",
                        "port": "analysis_summary",
                        "schema": "AnalysisSummary",
                        "value": {
                            "summary": "Build output summarized.",
                            "source_record_ids": ["candidate-1"],
                            "lossy": True,
                            "omitted_details": ["full diff omitted"],
                        },
                    },
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "output_record_accepted",
        "file_state_accepted",
        "output_record_accepted",
        "node_state_changed",
        "lease_released",
    ]
    assert output[4].payload["record_type"] == "analysis_summary"
    assert output[4].payload["value"]["source_record_ids"] == ["candidate-1"]


def test_callback_rejects_malformed_analysis_summary_record_atomically() -> None:
    output = _apply(
        _active_lease_events(),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-a",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "record_type": "candidate",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "candidate_id": "candidate-1",
                        "value": {"summary": "done"},
                    },
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                    },
                    {
                        "record_id": "summary-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "analysis_summary",
                        "schema": "AnalysisSummary",
                        "value": {
                            "source_record_ids": ["candidate-1"],
                            "lossy": True,
                            "omitted_details": [],
                        },
                    },
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "analysis_summary record at index 2 is invalid" in output[0].payload["reason"]


def test_callback_accepts_graph_patch_proposal_record() -> None:
    output = _apply(
        _planner_active_lease_events(),
        "submit_callback",
        _callback_payload(
            node_id="planner-1",
            payload={
                "payload_hash": "hash-a",
                "output_records": [
                    {
                        "record_id": "proposal-1",
                        "record_kind": "output",
                        "record_type": "graph_patch_proposal",
                        "producer_node_id": "planner-1",
                        "port": "graph_patch_proposal",
                        "schema": "GraphPatch",
                        "value": {
                            "patch_id": "patch-1",
                            "proposed_by_node_id": "planner-1",
                            "base_graph_position": 3,
                            "ops": [
                                {
                                    "op": "create_node",
                                    "node": {
                                        "node_id": "worker-1",
                                        "kind": "worker",
                                        "role": "builder",
                                    },
                                }
                            ],
                            "expected_downstream_effects": ["creates worker-1"],
                        },
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "node_state_changed",
        "lease_released",
    ]
    assert output[1].payload["record_type"] == "graph_patch_proposal"
    assert output[1].payload["value"]["patch_id"] == "patch-1"


def test_callback_rejects_malformed_graph_patch_proposal_record_atomically() -> None:
    output = _apply(
        _planner_active_lease_events(),
        "submit_callback",
        _callback_payload(
            node_id="planner-1",
            payload={
                "payload_hash": "hash-a",
                "output_records": [
                    {
                        "record_id": "proposal-1",
                        "record_kind": "output",
                        "producer_node_id": "planner-1",
                        "port": "graph_patch_proposal",
                        "schema": "GraphPatch",
                        "value": {
                            "patch_id": "patch-1",
                            "proposed_by_node_id": "planner-1",
                            "base_graph_position": 3,
                            "ops": [],
                            "macro_invocations": [],
                        },
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "graph_patch_proposal record at index 0 is invalid" in output[0].payload["reason"]


def test_callback_before_acknowledge_start_rejected_and_leaves_lease_intact() -> None:
    events = _leased_lease_events()

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(payload={"payload_hash": "hash-a"}),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == "node not running: leased"

    projected = _project([*events, *output])
    assert projected["node_states"]["worker-1"] == "leased"
    assert projected["leases"]["lease-1"].state == "active"


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
    assert projected["leases"]["lease-1"].state == "active"


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


def test_schedule_tick_fails_node_when_active_lease_expires_without_callback() -> None:
    clock = FakeClock()
    expired_at = clock.now() - timedelta(seconds=1)
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created", {"node_id": "verifier-1", "kind": "verifier", "state": "running"}, 1
        ),
        _event(
            "lease_granted",
            {
                "node_id": "verifier-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
                "base_snapshot_id": "S0",
                "expires_at": expired_at.isoformat(),
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["docs/out.md"]}],
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-2",
                "kind": "worker",
                "state": "ready",
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["docs/out.md"]}],
            },
            3,
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

    assert [event.event_type for event in output[:3]] == [
        "lease_expired",
        "output_record_accepted",
        "node_state_changed",
    ]
    assert [event.event_type for event in output[:4]] == [
        "lease_expired",
        "output_record_accepted",
        "node_state_changed",
        "node_ready",
    ]
    assert output[0].payload == {
        "lease_id": "lease-1",
        "node_id": "verifier-1",
        "generation": 1,
        "execution_id": "exec-1",
        "expires_at": expired_at.isoformat(),
        "reason": "lease_expired_without_callback",
    }
    assert output[1].payload["record_type"] == "failure_record"
    assert output[1].payload["value"] == {
        "failed_node_id": "verifier-1",
        "phase": "runtime",
        "error_class": "lease_expired_without_callback",
        "retryable": False,
        "lease_id": "lease-1",
        "execution_id": "exec-1",
        "lease_generation": 1,
        "reason": "lease_expired_without_callback",
        "expires_at": expired_at.isoformat(),
    }
    assert output[2].payload == {
        "node_id": "verifier-1",
        "new_state": "failed",
        "trigger": "lease_expired_without_callback",
        "reason": "lease_expired_without_callback",
    }
    assert any(
        event.event_type == "lease_granted" and event.payload["node_id"] == "worker-2"
        for event in output
    )

    projected = _project([*events, *output])
    assert projected["leases"]["lease-1"].state == "expired"
    assert projected["node_states"]["verifier-1"] == "failed"


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
        "output_record_accepted",
        "output_record_accepted",
        "file_state_accepted",
        "node_state_changed",
        "lease_released",
    ]


def test_late_callback_after_uncontested_lease_expiry_is_accepted() -> None:
    events = [
        *_active_lease_events(),
        _event(
            "lease_expired",
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
                "reason": "lease_expired_without_callback",
            },
            3,
        ),
        _event(
            "node_state_changed",
            {
                "node_id": "worker-1",
                "new_state": "failed",
                "trigger": "lease_expired_without_callback",
                "reason": "lease_expired_without_callback",
            },
            4,
        ),
    ]

    output = _apply(events, "submit_callback", _callback_payload())

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "output_record_accepted",
        "file_state_accepted",
        "node_state_changed",
        "lease_released",
    ]
    assert output[0].payload["reason"] == "accepted_late_expired_lease"


def test_callback_rejects_completion_without_required_output_record() -> None:
    output = _apply(
        _active_lease_events(),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-empty",
                "output_records": [],
            }
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == (
        "node completion missing required output record ports: candidate, file_state"
    )


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
                    },
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                    },
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "input_bound",
        "output_record_accepted",
        "file_state_accepted",
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


def test_callback_accepts_artifact_reference_output_record() -> None:
    output = _apply(
        _active_lease_events(),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-artifact",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "done"},
                    },
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                    },
                    {
                        "record_id": "artifact-reference-1",
                        "record_kind": "graph_record",
                        "record_type": "artifact_reference",
                        "producer_node_id": "worker-1",
                        "port": "artifact_reference",
                        "schema": "ArtifactReference",
                        "value": {
                            "artifact_id": "docs/out.txt",
                            "artifact_type": "run_output",
                            "uri": "docs/out.txt",
                            "summary": "submitted artifact",
                            "source_record_ids": ["candidate-1"],
                        },
                    },
                ],
            },
            payload_hash="hash-artifact",
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "output_record_accepted",
        "file_state_accepted",
        "output_record_accepted",
        "node_state_changed",
        "lease_released",
    ]
    assert output[4].payload["record_type"] == "artifact_reference"
    assert output[4].payload["port"] == "artifact_reference"
    assert output[4].payload["value"]["uri"] == "docs/out.txt"


def test_callback_binds_first_record_only_for_one_cardinality_input() -> None:
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

    first_output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            payload_hash="hash-first",
            idempotency_key="key-first",
            payload={
                "payload_hash": "hash-first",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "first"},
                    }
                ],
            },
            complete_node=False,
        ),
    )
    second_output = _apply(
        [*events, *first_output],
        "submit_callback",
        _callback_payload(
            payload_hash="hash-second",
            idempotency_key="key-second",
            payload={
                "payload_hash": "hash-second",
                "output_records": [
                    {
                        "record_id": "candidate-2",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "second"},
                    }
                ],
            },
            complete_node=False,
        ),
    )

    assert "input_bound" not in [event.event_type for event in second_output]
    projected = _project([*events, *first_output, *second_output])
    binding = projected["input_bindings"]["verifier-1"]["candidate_under_test"]
    assert binding.binding_policy == "bind_first"
    assert binding.record_ids == ["candidate-1"]


def test_callback_accumulates_records_for_many_cardinality_input() -> None:
    events = [
        *_active_lease_events(),
        _event(
            "node_created",
            {"node_id": "summarizer-1", "kind": "summarizer", "state": "planned"},
            3,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-source-records",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "required": True,
            },
            4,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            payload_hash="hash-many",
            idempotency_key="key-many",
            payload={
                "payload_hash": "hash-many",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "first"},
                    },
                    {
                        "record_id": "candidate-2",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "second"},
                    },
                ],
            },
            complete_node=False,
        ),
    )

    assert [event.event_type for event in output].count("input_bound") == 2
    projected = _project([*events, *output])
    binding = projected["input_bindings"]["summarizer-1"]["source_records"]
    assert binding.binding_policy == "bind_all"
    assert binding.record_ids == ["candidate-1", "candidate-2"]


def test_callback_rebinds_superseding_record_when_policy_allows() -> None:
    events = [
        *_active_lease_events(),
        _event(
            "node_created",
            {"node_id": "planner-1", "kind": "planner", "role": "planner", "state": "planned"},
            3,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-file-state",
                "from_node_id": "worker-1",
                "from_port": "file_state",
                "to_node_id": "planner-1",
                "to_port": "accepted_file_state",
                "required": True,
                "binding_policy": "rebind_on_superseding",
            },
            4,
        ),
    ]

    first_output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            payload_hash="hash-file-state-1",
            idempotency_key="key-file-state-1",
            payload={
                "payload_hash": "hash-file-state-1",
                "output_records": [
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                    }
                ],
            },
            complete_node=False,
        ),
    )
    second_output = _apply(
        [*events, *first_output],
        "submit_callback",
        _callback_payload(
            payload_hash="hash-file-state-2",
            idempotency_key="key-file-state-2",
            payload={
                "payload_hash": "hash-file-state-2",
                "output_records": [
                    {
                        "record_id": "file-state-2",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-2",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                        "supersedes_record_id": "file-state-1",
                    }
                ],
            },
            complete_node=False,
        ),
    )

    projected = _project([*events, *first_output, *second_output])
    binding = projected["input_bindings"]["planner-1"]["accepted_file_state"]
    assert binding.binding_policy == "rebind_on_superseding"
    assert binding.record_ids == ["file-state-2"]


def test_callback_accepts_gap_analysis_output_and_binds_classified_gap() -> None:
    events = [
        *_active_lease_events(),
        _event(
            "node_created",
            {"node_id": "worker-2", "kind": "worker", "role": "fixer", "state": "planned"},
            3,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-gap-classification",
                "from_node_id": "worker-1",
                "from_port": "gap_classification",
                "to_node_id": "worker-2",
                "to_port": "classified_gap",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "gap_classification",
                    "schema": "GapClassification",
                },
            },
            4,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-gap",
                "output_records": [
                    {
                        "record_id": "gap-classification-1",
                        "record_kind": "output",
                        "record_type": "classified_gap",
                        "producer_node_id": "worker-1",
                        "port": "gap_classification",
                        "schema": "GapClassification",
                        "value": {
                            "milestone_kind": "gap_analysis",
                            "classification": "corrective_work_required",
                            "source": "test",
                            "task_region_id": "task-1",
                            "attempt_number": 0,
                        },
                    }
                ],
            },
            complete_node=False,
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "input_bound",
    ]
    assert output[2].payload == {
        "edge_id": "edge-gap-classification",
        "to_node_id": "worker-2",
        "to_port": "classified_gap",
        "record_ids": ["gap-classification-1"],
        "bound_at_position": 0,
    }


def test_callback_accepts_classified_gap_port_and_binds_classified_gap() -> None:
    events = [
        *_active_lease_events(),
        _event(
            "node_created",
            {"node_id": "worker-2", "kind": "worker", "role": "fixer", "state": "planned"},
            3,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-classified-gap",
                "from_node_id": "worker-1",
                "from_port": "classified_gap",
                "to_node_id": "worker-2",
                "to_port": "classified_gap",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "gap_classification",
                    "schema": "GapClassification",
                },
            },
            4,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-gap",
                "output_records": [
                    {
                        "record_id": "classified-gap-1",
                        "record_kind": "output",
                        "record_type": "classified_gap",
                        "producer_node_id": "worker-1",
                        "port": "classified_gap",
                        "schema": "GapClassification",
                        "value": {
                            "milestone_kind": "gap_analysis",
                            "classification": "corrective_work_required",
                            "source": "test",
                            "task_region_id": "task-1",
                            "attempt_number": 0,
                        },
                    }
                ],
            },
            complete_node=False,
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "input_bound",
    ]
    assert output[2].payload == {
        "edge_id": "edge-classified-gap",
        "to_node_id": "worker-2",
        "to_port": "classified_gap",
        "record_ids": ["classified-gap-1"],
        "bound_at_position": 0,
    }


def test_callback_value_selector_blocks_no_gap_from_corrective_worker() -> None:
    events = [
        *_active_lease_events(),
        _event(
            "node_created",
            {"node_id": "worker-2", "kind": "worker", "role": "fixer", "state": "planned"},
            3,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-classified-gap",
                "from_node_id": "worker-1",
                "from_port": "classified_gap",
                "to_node_id": "worker-2",
                "to_port": "classified_gap",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "gap_classification",
                    "schema": "GapClassification",
                    "classification": "corrective_work_required",
                },
            },
            4,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-gap",
                "output_records": [
                    {
                        "record_id": "classified-gap-1",
                        "record_kind": "output",
                        "record_type": "classified_gap",
                        "producer_node_id": "worker-1",
                        "port": "classified_gap",
                        "schema": "GapClassification",
                        "value": {
                            "milestone_kind": "gap_analysis",
                            "classification": "no_gap",
                            "source": "accepted_gap_planner_no_op_patch",
                            "task_region_id": "region-1",
                            "attempt_number": 0,
                        },
                    }
                ],
            },
            complete_node=False,
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
    ]


def test_patch_create_edge_backfills_existing_verification_record() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "planner-gap",
                "kind": "planner",
                "role": "gap_planner",
                "state": "running",
            },
            1,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final",
                "kind": "check",
                "role": "invariant_gate",
                "state": "planned",
                "command_definition": {"id": "hidden-oracle", "cmd": "true", "must": True},
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-1",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-1",
                "outcome": "passed",
                "value": {"outcome": "passed", "grades": []},
            },
            4,
        ),
    ]

    output = _apply(
        events,
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-late-edge",
            "proposed_by_node_id": "planner-gap",
            "actor_role": "gap_planner",
            "base_graph_position": 2,
            "ops": [
                {
                    "op": "create_edge",
                    "edge_id": "edge-verifier-final",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "check-final",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == [
        "graph_patch_accepted",
        "edge_created",
        "input_bound",
    ]
    assert output[2].payload == {
        "edge_id": "edge-verifier-final",
        "to_node_id": "check-final",
        "to_port": "verification_evidence",
        "record_ids": ["verification-1"],
        "bound_at_position": 0,
        "trigger": "edge_backfill",
    }


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
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
                "snapshot_id": "snapshot-1",
                "base_snapshot_id": "S0",
                "verdict": "captured",
            },
            3,
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
            4,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-gap",
                "kind": "planner",
                "role": "gap_planner",
                "state": "planned",
                "task_region_id": "task-1",
            },
            5,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            6,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "file_state",
                "record_ids": ["file-state-1"],
            },
            7,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-verifier-gap",
                "from_node_id": "verifier-1",
                "from_port": "verification_report",
                "to_node_id": "planner-gap",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                },
            },
            8,
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
            9,
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
                        "outcome": "passed",
                        "value": {
                            "outcome": "passed",
                            "grades": [
                                {
                                    "requirement_id": "R-1",
                                    "grade": "A",
                                    "reason": "candidate satisfies requirement",
                                }
                            ],
                        },
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "verification_passed",
        "input_bound",
        "node_state_changed",
        "lease_released",
    ]
    accepted_record = output[1].payload
    assert accepted_record["outcome"] == "passed"
    assert accepted_record["value"]["outcome"] == "passed"
    assert accepted_record["candidate_record_id"] == "candidate-1"
    assert accepted_record["candidate_record_ids"] == ["candidate-1"]
    assert accepted_record["file_state_record_ids"] == ["file-state-1"]
    assert accepted_record["evaluated_record_ids"] == ["candidate-1", "file-state-1"]
    assert accepted_record["provenance"]["evaluated_record_ids"] == [
        "candidate-1",
        "file-state-1",
    ]
    assert accepted_record["evidence"]["file_state_record_ids"] == ["file-state-1"]
    assert output[2].payload["candidate_id"] == "candidate-1"
    assert output[2].payload["outcome"] == "passed"
    assert output[2].payload["evidence"][0]["evaluated_record_ids"] == [
        "candidate-1",
        "file-state-1",
    ]
    assert output[3].payload == {
        "edge_id": "edge-verifier-gap",
        "to_node_id": "planner-gap",
        "to_port": "verification_evidence",
        "record_ids": ["verification-1"],
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
        event.event_type == "lease_granted" and event.payload["node_id"] == "planner-gap"
        for event in schedule_output
    )


def test_verifier_callback_rejects_verification_record_with_status_key() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "completed"}, 1),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "value": {},
            },
            2,
        ),
        _event(
            "node_created", {"node_id": "verifier-1", "kind": "verifier", "state": "running"}, 3
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
                        "status": "passed",
                        "value": {
                            "outcome": "passed",
                            "grades": [{"requirement_id": "R-1", "grade": "A"}],
                        },
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "verification record at index 0 is invalid" in output[0].payload["reason"]
    assert "Extra inputs are not permitted" in output[0].payload["reason"]


def test_verifier_callback_failed_output_has_explicit_failed_outcome() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "completed"}, 1),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "value": {"summary": "candidate"},
            },
            2,
        ),
        _event(
            "node_created",
            {"node_id": "verifier-1", "kind": "verifier", "role": "verifier", "state": "running"},
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
            idempotency_key="verify-failed",
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
                        "outcome": "failed",
                        "value": {
                            "outcome": "failed",
                            "grades": [
                                {
                                    "requirement_id": "R-1",
                                    "grade": "C",
                                    "reason": "missing regression evidence",
                                }
                            ],
                        },
                    }
                ],
            },
        ),
    )

    accepted_record = next(
        event.payload for event in output if event.event_type == "output_record_accepted"
    )
    failed_event = next(
        event.payload for event in output if event.event_type == "verification_failed"
    )
    assert accepted_record["outcome"] == "failed"
    assert accepted_record["value"]["outcome"] == "failed"
    assert accepted_record["value"]["grades"][0]["reason"] == "missing regression evidence"
    assert failed_event["outcome"] == "failed"


def test_verifier_callback_rejects_completion_without_grades() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "completed"}, 1),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "done"},
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "running",
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
            idempotency_key="verify-empty-grades",
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
                        "outcome": "passed",
                        "value": {"outcome": "passed", "grades": []},
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == "verification record at index 0 missing grades"


def test_verifier_callback_rejects_stale_status_with_outcome() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "done"},
            },
            1,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "running",
                "candidate_id": "candidate-1",
            },
            2,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            3,
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
            4,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            node_id="verifier-1",
            lease_id="lease-v",
            execution_id="exec-v",
            idempotency_key="verify-status",
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
                        "outcome": "passed",
                        "status": "passed",
                        "value": {
                            "outcome": "passed",
                            "grades": [{"requirement_id": "R-1", "grade": "A"}],
                        },
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "Extra inputs are not permitted" in output[0].payload["reason"]


def test_verifier_callback_rejects_report_shaped_output_with_value_status() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "done"},
            },
            1,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "running",
                "candidate_id": "candidate-1",
            },
            2,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            3,
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
            4,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            node_id="verifier-1",
            lease_id="lease-v",
            execution_id="exec-v",
            idempotency_key="verify-output-status",
            payload={
                "payload_hash": "hash-v",
                "output_records": [
                    {
                        "record_id": "verification-1",
                        "record_kind": "output",
                        "record_type": "verification_report",
                        "producer_node_id": "verifier-1",
                        "port": "verification_report",
                        "schema": "VerificationReport",
                        "candidate_id": "candidate-1",
                        "outcome": "passed",
                        "value": {
                            "outcome": "passed",
                            "status": "passed",
                            "grades": [{"requirement_id": "R-1", "grade": "A"}],
                        },
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "Extra inputs are not permitted" in output[0].payload["reason"]


def test_verifier_callback_canonicalizes_result_port_for_final_invariant_binding() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "worker-corrective",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "corrective_work_region",
                "attempt_number": 2,
                "candidate_id": "candidate-fix",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-fix",
                "record_kind": "output",
                "producer_node_id": "worker-corrective",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-fix",
                "task_region_id": "corrective_work_region",
                "attempt_number": 2,
                "value": {},
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-corrective",
                "kind": "verifier",
                "state": "running",
                "task_region_id": "corrective_work_region",
                "candidate_id": "candidate-fix",
            },
            3,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final",
                "kind": "check",
                "role": "invariant_gate",
                "state": "planned",
                "task_region_id": "corrective_work_region",
                "command_definition": {"id": "hidden-oracle", "cmd": "true", "must": True},
            },
            4,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-corrective",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-fix"],
            },
            5,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-corrective-verifier-final",
                "from_node_id": "verifier-corrective",
                "from_port": "verification_report",
                "to_node_id": "check-final",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "any_of",
                    "selectors": [
                        {
                            "record_type": "verification_report",
                            "schema": "VerificationReport",
                        },
                        {"record_type": "check_result", "schema": "CheckResult"},
                    ],
                },
            },
            6,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "verifier-corrective",
                "lease_id": "lease-v",
                "generation": 1,
                "execution_id": "exec-v",
                "base_snapshot_id": "S0",
            },
            7,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            node_id="verifier-corrective",
            lease_id="lease-v",
            execution_id="exec-v",
            idempotency_key="verify-key",
            payload={
                "payload_hash": "hash-v",
                "output_records": [
                    {
                        "record_id": "verification-fix",
                        "record_kind": "verification",
                        "producer_node_id": "verifier-corrective",
                        "port": "verification_result",
                        "schema": "VerificationReport",
                        "candidate_id": "candidate-fix",
                        "verdict": "pass",
                        "value": {
                            "grades": [
                                {
                                    "requirement_id": "R-1",
                                    "grade": "A",
                                    "reason": "candidate satisfies requirement",
                                }
                            ]
                        },
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "verification_passed",
        "input_bound",
        "node_state_changed",
        "lease_released",
    ]
    assert output[1].payload["port"] == "verification_report"
    assert output[1].payload["outcome"] == "passed"
    assert output[1].payload["value"]["outcome"] == "passed"
    assert "verdict" not in output[1].payload
    assert output[3].payload == {
        "edge_id": "edge-corrective-verifier-final",
        "to_node_id": "check-final",
        "to_port": "verification_evidence",
        "record_ids": ["verification-fix"],
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
        event.event_type == "lease_granted" and event.payload["node_id"] == "check-final"
        for event in schedule_output
    )


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
                        "outcome": "passed",
                        "value": {
                            "outcome": "passed",
                            "grades": [{"requirement_id": "R-1", "grade": "A"}],
                        },
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "not bound" in output[0].payload["reason"]


def test_verifier_callback_rejects_mismatched_candidate_record_citation() -> None:
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
                        "candidate_id": "candidate-1",
                        "candidate_record_ids": ["candidate-other"],
                        "outcome": "passed",
                        "value": {
                            "outcome": "passed",
                            "grades": [
                                {
                                    "requirement_id": "R-1",
                                    "grade": "A",
                                    "reason": "candidate satisfies requirement",
                                }
                            ],
                        },
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "candidate_record_ids does not match bound records" in output[0].payload["reason"]


def test_check_result_rejects_mismatched_evaluated_record_citation() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "running",
                "task_region_id": "task-1",
            },
            1,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "check-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            2,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "check-1",
                "to_port": "file_state",
                "record_ids": ["file-state-1"],
            },
            3,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "check-1",
                "lease_id": "lease-c",
                "generation": 1,
                "execution_id": "exec-c",
                "base_snapshot_id": "S0",
            },
            4,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            node_id="check-1",
            lease_id="lease-c",
            execution_id="exec-c",
            idempotency_key="check-key",
            payload={
                "payload_hash": "hash-c",
                "output_records": [
                    {
                        "record_id": "check-1-result",
                        "record_kind": "output",
                        "record_type": "check_result",
                        "producer_node_id": "check-1",
                        "port": "check_result",
                        "schema": "CheckResult",
                        "candidate_id": "candidate-1",
                        "task_region_id": "task-1",
                        "value": {
                            "status": "passed",
                            "classification": "passed",
                            "command_id": "unit-check",
                            "exit_code": 0,
                            "duration_ms": 1,
                            "evaluated_record_ids": ["candidate-other"],
                        },
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "value.evaluated_record_ids does not match bound records" in output[0].payload["reason"]


def test_callback_rejects_malformed_check_result_record() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "running",
                "task_region_id": "task-1",
            },
            1,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "check-1",
                "lease_id": "lease-c",
                "generation": 1,
                "execution_id": "exec-c",
                "base_snapshot_id": "S0",
            },
            2,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            node_id="check-1",
            lease_id="lease-c",
            execution_id="exec-c",
            idempotency_key="check-key",
            payload={
                "payload_hash": "hash-c",
                "output_records": [
                    {
                        "record_id": "check-1-result",
                        "record_kind": "output",
                        "record_type": "check_result",
                        "producer_node_id": "check-1",
                        "port": "check_result",
                        "schema": "CheckResult",
                        "candidate_id": "candidate-1",
                        "task_region_id": "task-1",
                        "attempt_number": 1,
                        "value": {
                            "status": "unknown",
                            "classification": "failed",
                            "command_id": "unit-check",
                            "command_binding": None,
                            "command_text": "unit check",
                            "command": {"id": "unit-check", "argv": ["false"]},
                            "worktree_path": "/tmp/worktree",
                            "base_snapshot_id": "S0",
                            "execution_id": "exec-c",
                            "exit_code": 1,
                            "duration_ms": 1,
                            "stdout": "",
                            "stderr": "failed",
                            "stdout_truncated": False,
                            "stderr_truncated": False,
                            "timeout_seconds": 60,
                            "environment_policy": {
                                "cwd": "/tmp/worktree",
                                "env": "inherited",
                                "shell": False,
                            },
                        },
                    }
                ],
            },
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert "check_result record at index 0 is invalid" in output[0].payload["reason"]
    assert "Input should be 'passed', 'failed' or 'timeout'" in output[0].payload["reason"]


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
                        "outcome": "passed",
                        "value": {
                            "outcome": "passed",
                            "grades": [{"requirement_id": "R-1", "grade": "A"}],
                        },
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
    assert projected["leases"]["lease-1"].state == "active"
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


def test_callback_accepts_file_state_paths_within_lease_write_scope() -> None:
    output = _apply(
        _active_lease_events_with_resource_claims(
            [{"mode": "write", "scope": "repo", "paths": ["docs/**"]}]
        ),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-file-state-authorized",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "docs updated"},
                    },
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                        "tracked": [{"path": "docs/out.md", "status": "modified"}],
                    },
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "output_record_accepted",
        "file_state_accepted",
        "node_state_changed",
        "lease_released",
    ]


def test_callback_allows_tool_cache_file_state_outside_write_scope() -> None:
    output = _apply(
        _active_lease_events_with_resource_claims(
            [{"mode": "write", "scope": "repo", "paths": ["docs/out.md"]}]
        ),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-file-state-tool-cache",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "docs updated"},
                    },
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                        "tracked": [{"path": "docs/out.md", "status": "modified"}],
                        "untracked": [
                            {
                                "path": ".claude/settings.local.json",
                                "classification": "tool_cache",
                            }
                        ],
                        "classifications": [
                            {"path": "docs/out.md", "classification": "source_code"},
                            {
                                "path": ".claude/settings.local.json",
                                "classification": "tool_cache",
                            },
                        ],
                    },
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "output_record_accepted",
        "file_state_accepted",
        "node_state_changed",
        "lease_released",
    ]


def test_callback_rejects_file_state_path_outside_lease_write_scope() -> None:
    output = _apply(
        _active_lease_events_with_resource_claims(
            [{"mode": "write", "scope": "repo", "paths": ["docs/**"]}]
        ),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-file-state-outside-scope",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "src updated"},
                    },
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                        "tracked": [{"path": "src/app.py", "status": "modified"}],
                    },
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == (
        "file_state path outside lease write authority at index 1: src/app.py"
    )


def test_callback_rejects_file_state_path_with_only_read_authority() -> None:
    output = _apply(
        _active_lease_events_with_resource_claims(
            [{"mode": "read", "scope": "repo", "paths": ["docs/**"]}]
        ),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-file-state-read-only",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "docs updated"},
                    },
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                        "tracked": [{"path": "docs/out.md", "status": "modified"}],
                    },
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == (
        "file_state path outside lease write authority at index 1: docs/out.md"
    )


def test_callback_accepts_file_state_path_under_path_in_scope_write_claim() -> None:
    """Regression test for run 8feabee5.

    A planner-issued claim shaped like ``{"mode": "write", "scope": "src/orchestrator/graph"}``
    (path prefix stuffed into ``scope`` with no ``paths`` list) must still grant write
    authority over files beneath that path, via normalization in ``_claim_from_dict``.
    Before the fix this was rejected with "file_state path outside lease write authority".
    """
    output = _apply(
        _active_lease_events_with_resource_claims(
            [{"mode": "write", "scope": "src/orchestrator/graph"}]
        ),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-file-state-path-in-scope",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "graph module updated"},
                    },
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                        "tracked": [
                            {"path": "src/orchestrator/graph/commands.py", "status": "modified"}
                        ],
                    },
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == [
        "callback_accepted",
        "output_record_accepted",
        "output_record_accepted",
        "file_state_accepted",
        "node_state_changed",
        "lease_released",
    ]


def test_callback_rejects_file_state_path_outside_path_in_scope_write_claim() -> None:
    """A path-in-scope write claim only authorizes paths beneath that prefix."""
    output = _apply(
        _active_lease_events_with_resource_claims(
            [{"mode": "write", "scope": "src/orchestrator/graph"}]
        ),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-file-state-path-in-scope-outside",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "unrelated module touched"},
                    },
                    {
                        "record_id": "file-state-1",
                        "record_kind": "file_state",
                        "producer_node_id": "worker-1",
                        "port": "file_state",
                        "schema": "FileStateRecord",
                        "snapshot_id": "snapshot-1",
                        "base_snapshot_id": "S0",
                        "verdict": "captured",
                        "tracked": [
                            {"path": "src/orchestrator/api/routers/graph.py", "status": "modified"}
                        ],
                    },
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == (
        "file_state path outside lease write authority at index 1: "
        "src/orchestrator/api/routers/graph.py"
    )


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


def test_callback_rejects_unregistered_output_port() -> None:
    events = [
        *_active_lease_events(),
        _event(
            "node_created",
            {"node_id": "verifier-1", "kind": "verifier", "role": "verifier", "state": "blocked"},
            3,
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

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == (
        "output record at index 0 uses unknown output port: diagnostic"
    )


def test_callback_rejects_incompatible_explicit_record_type() -> None:
    output = _apply(
        _active_lease_events(),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-a",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "record_type": "check_result",
                        "producer_node_id": "worker-1",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "done"},
                    }
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == (
        "output record at index 0 has incompatible record_type for candidate: check_result"
    )
    assert "output_record_accepted" not in [event.event_type for event in output]


def test_callback_rejects_explicit_producer_port_mismatch() -> None:
    output = _apply(
        _active_lease_events(),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-a",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "producer_port": "check_result",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "done"},
                    }
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == (
        "output record at index 0 producer_port does not match port: check_result"
    )
    assert "output_record_accepted" not in [event.event_type for event in output]


def test_callback_rejects_explicit_record_run_id_mismatch() -> None:
    output = _apply(
        _active_lease_events(),
        "submit_callback",
        _callback_payload(
            payload={
                "payload_hash": "hash-a",
                "output_records": [
                    {
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "producer_node_id": "worker-1",
                        "run_id": "other-run",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "done"},
                    }
                ],
            }
        ),
    )

    assert [event.event_type for event in output] == ["callback_rejected_conflict"]
    assert output[0].payload["reason"] == (
        "output record at index 0 run_id does not match callback run: other-run"
    )
    assert "output_record_accepted" not in [event.event_type for event in output]


def test_callback_rejected_stale() -> None:
    events = [
        *_active_lease_events(),
        _event("lease_revoked", {"node_id": "worker-1", "lease_id": "lease-1"}, 3),
    ]

    output = _apply(
        events, "submit_callback", _callback_payload(payload={"payload_hash": "hash-a"})
    )

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

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(payload={"payload_hash": "hash-a"}),
    )

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

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(payload={"payload_hash": "hash-a"}),
    )

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
    assert output[0].payload["patch_id"] == "patch-1"
    assert output[0].payload["proposed_by_node_id"] == "planner-1"
    assert output[0].payload["actor_role"] == "planner"
    assert output[0].payload["base_graph_position"] == -1


def test_patch_create_edge_preserves_producer_class_constraints() -> None:
    output = _apply(
        [
            _event("run_lifecycle_changed", {"to_state": "active"}, 0),
            _event("node_created", {"node_id": "check-final", "kind": "check"}, 1),
        ],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-class-edge",
            "proposed_by_node_id": "planner-1",
            "actor_role": "oversight",
            "base_graph_position": 1,
            "ops": [
                {
                    "op": "create_edge",
                    "edge_id": "edge-verifier-class-final",
                    "from_node_id": "*",
                    "from_node_kind": "verifier",
                    "from_node_role": "verifier",
                    "from_port": "verification_report",
                    "to_node_id": "check-final",
                    "to_port": "verification_evidence",
                    "required": True,
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == ["graph_patch_accepted", "edge_created"]
    assert output[1].payload["from_node_kind"] == "verifier"
    assert output[1].payload["from_node_role"] == "verifier"


def test_submit_patch_rejects_verification_selector_with_status_before_acceptance() -> None:
    output = _apply(
        [
            _event("run_lifecycle_changed", {"to_state": "active"}, 0),
            _event(
                "node_created",
                {
                    "node_id": "verifier-1",
                    "kind": "verifier",
                    "role": "verifier",
                    "state": "completed",
                },
                1,
            ),
            _event(
                "node_created",
                {
                    "node_id": "planner-gap",
                    "kind": "planner",
                    "role": "gap_planner",
                    "state": "planned",
                },
                2,
            ),
        ],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-invalid-selector",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": 2,
            "ops": [
                {
                    "op": "create_edge",
                    "edge_id": "edge-invalid-selector",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "planner-gap",
                    "to_port": "verification_evidence",
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "status": "failed",
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == ["command_rejected"]
    assert output[0].payload["command_type"] == "submit_patch"
    assert "accepted_record_selector" in output[0].payload["reason"]
    assert "status" in output[0].payload["reason"]


def test_submit_patch_rejects_legacy_verification_selector_value_status() -> None:
    output = _apply(
        [
            _event("run_lifecycle_changed", {"to_state": "active"}, 0),
            _event(
                "node_created",
                {
                    "node_id": "verifier-1",
                    "kind": "verifier",
                    "role": "verifier",
                    "state": "completed",
                },
                1,
            ),
            _event(
                "node_created",
                {
                    "node_id": "planner-gap",
                    "kind": "planner",
                    "role": "gap_planner",
                    "state": "planned",
                },
                2,
            ),
        ],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-invalid-legacy-selector",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": 2,
            "ops": [
                {
                    "op": "create_edge",
                    "edge_id": "edge-invalid-legacy-selector",
                    "from_node_id": "verifier-1",
                    "from_port": "verification_report",
                    "to_node_id": "planner-gap",
                    "to_port": "verification_evidence",
                    "accepted_record_selector": {
                        "record_kinds": ["verification_report"],
                        "value_matches": {"status": "failed"},
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == ["command_rejected"]
    assert "record_type" in output[0].payload["reason"]


def test_seed_compiled_events_rejects_invalid_edge_selector() -> None:
    output = _apply(
        [],
        "seed_compiled_events",
        {
            "run_id": "run-1",
            "events": [
                _event(
                    "edge_created",
                    {
                        "edge_id": "edge-invalid-selector",
                        "from_node_id": "verifier-1",
                        "from_port": "verification_report",
                        "to_node_id": "planner-gap",
                        "to_port": "verification_evidence",
                        "accepted_record_selector": {
                            "record_type": "verification_report",
                            "schema": "VerificationReport",
                            "status": "failed",
                        },
                    },
                    1,
                    canonicalize=False,
                )
            ],
        },
    )

    assert [event.event_type for event in output] == ["command_rejected"]
    assert output[0].payload["command_type"] == "seed_compiled_events"
    assert "status" in output[0].payload["reason"]


def test_seed_compiled_events_rejects_invalid_verification_report_record() -> None:
    output = _apply(
        [],
        "seed_compiled_events",
        {
            "run_id": "run-1",
            "events": [
                _event(
                    "output_record_accepted",
                    {
                        "record_id": "verification-1",
                        "record_kind": "verification",
                        "producer_node_id": "verifier-1",
                        "port": "verification_report",
                        "schema": "VerificationReport",
                        "candidate_id": "candidate-1",
                        "outcome": "failed",
                        "value": {
                            "outcome": "failed",
                            "grades": [{"requirement_id": "R-1", "grade": "F"}],
                        },
                    },
                    1,
                    canonicalize=False,
                )
            ],
        },
    )

    assert [event.event_type for event in output] == ["command_rejected"]
    assert output[0].payload["command_type"] == "seed_compiled_events"
    assert "require record_type=verification_report" in output[0].payload["reason"]


def test_seed_compiled_events_rejects_legacy_selector_key() -> None:
    output = _apply(
        [],
        "seed_compiled_events",
        {
            "run_id": "run-1",
            "events": [
                _event(
                    "edge_created",
                    {
                        "edge_id": "edge-invalid-selector",
                        "from_node_id": "verifier-1",
                        "from_port": "verification_report",
                        "to_node_id": "planner-gap",
                        "to_port": "verification_evidence",
                        "accepted_record_selector": {
                            "record_kinds": ["verification_report"],
                        },
                    },
                    1,
                )
            ],
        },
    )

    assert [event.event_type for event in output] == ["command_rejected"]
    assert output[0].payload["command_type"] == "seed_compiled_events"
    assert "record_type" in output[0].payload["reason"]


def test_patch_rejects_planner_authored_verifier_candidate_id() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-verifier-candidate",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "verifier-1",
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "planned",
                        "candidate_id": "candidate-llm-authored",
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == ["graph_patch_rejected"]
    assert (
        output[0].payload["reason"]
        == "node verifier-1 must not declare candidate_id; verifiers derive the "
        "candidate from the required candidate_under_test input edge"
    )


def test_patch_rejects_planner_authored_check_candidate_id() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-check-candidate",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "check-1",
                        "kind": "check",
                        "role": "invariant_gate",
                        "state": "planned",
                        "candidate_id": "candidate-llm-authored",
                        "command_definition": {"id": "unit-check", "argv": ["true"]},
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == ["graph_patch_rejected"]
    assert (
        output[0].payload["reason"]
        == "node check-1 must not declare candidate_id; checks derive evaluated "
        "candidates from bound candidate or verification evidence inputs"
    )


def test_patch_rejected_after_run_cancellation() -> None:
    events = [
        _event(
            "run_lifecycle_changed",
            {"from_state": "active", "to_state": "cancelled", "trigger": "cancel_command_accepted"},
            1,
        )
    ]

    output = _apply(
        events,
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-after-cancel",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": 1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {"node_id": "artifact-1", "kind": "artifact", "state": "planned"},
                }
            ],
        },
    )

    assert [event.event_type for event in output] == ["command_rejected"]
    assert output[0].payload == {
        "command_type": "submit_patch",
        "reason": "run_not_active:cancelled",
    }


def test_patch_accept_adds_default_worker_write_authority() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-worker",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "task_region_id": "region-1",
                        "candidate_id": "candidate-1",
                        "attempt_number": 1,
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == ["graph_patch_accepted", "node_created"]
    assert output[1].payload["authority"]["resource_claims"] == [
        {"mode": "write", "scope": "repo", "paths": ["."]}
    ]


def test_patch_accept_emits_human_gate_request_record_and_binding() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-human-gate",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "gate-review",
                        "kind": "human_gate",
                        "state": "planned",
                        "reason": "Review graph expansion.",
                        "decision_request": {
                            "decision_type": "approval",
                            "options": ["approve", "reject"],
                            "default_option": "reject",
                            "consequence_summary": "Review graph expansion.",
                        },
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == [
        "graph_patch_accepted",
        "node_created",
        "output_record_accepted",
        "input_bound",
    ]
    request_record = output[2].payload
    assert request_record == {
        "record_id": "decision-request-gate-review",
        "record_kind": "graph_record",
        "record_type": "decision_request",
        "producer_node_id": "gate-review",
        "port": "decision_request",
        "schema": "DecisionRequest",
        "value": {
            "decision_type": "approval",
            "options": ["approve", "reject"],
            "default_option": "reject",
            "consequence_summary": "Review graph expansion.",
        },
    }
    assert output[3].payload == {
        "edge_id": "edge-decision-request-gate-review-to-gate-review-decision_request",
        "to_node_id": "gate-review",
        "to_port": "decision_request",
        "record_ids": ["decision-request-gate-review"],
        "bound_at_position": 0,
        "binding_policy": "bind_latest",
    }
    projected = _project(output)
    assert projected["input_bindings"]["gate-review"]["decision_request"].record_ids == [
        "decision-request-gate-review"
    ]


def test_patch_accept_emits_authority_request_record_and_binding() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-authority-request",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "gate-authority",
                        "kind": "authority_request",
                        "state": "planned",
                        "authority_request_record": {
                            "requested_authority": ["repo:docs/**:write"],
                            "target_node_id": "worker-docs",
                            "reason": "Worker needs docs write access.",
                        },
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == [
        "graph_patch_accepted",
        "node_created",
        "output_record_accepted",
        "input_bound",
    ]
    assert output[2].payload == {
        "record_id": "authority-request-gate-authority",
        "record_kind": "graph_record",
        "record_type": "authority_request_record",
        "producer_node_id": "gate-authority",
        "port": "authority_request_record",
        "schema": "AuthorityRequest",
        "value": {
            "requested_authority": ["repo:docs/**:write"],
            "target_node_id": "worker-docs",
            "reason": "Worker needs docs write access.",
        },
    }
    assert output[3].payload["to_port"] == "authority_request_record"
    assert output[3].payload["record_ids"] == ["authority-request-gate-authority"]


def test_patch_accepts_authority_request_typed_record_envelope() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-authority-request-envelope",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "gate-authority",
                        "kind": "authority_request",
                        "state": "planned",
                        "authority_request_record": {
                            "record_type": "authority_request_record",
                            "schema": "AuthorityRequest",
                            "value": {
                                "requested_authority": ["repo:docs/**:write"],
                                "target_node_id": "worker-docs",
                                "reason": "Worker needs docs write access.",
                            },
                        },
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == [
        "graph_patch_accepted",
        "node_created",
        "output_record_accepted",
        "input_bound",
    ]
    assert output[2].payload["value"] == {
        "requested_authority": ["repo:docs/**:write"],
        "target_node_id": "worker-docs",
        "reason": "Worker needs docs write access.",
    }


def test_patch_accepts_authority_request_edge_to_worker_authority_input() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-authority-gated-worker",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "authority-docs-write",
                        "kind": "authority_request",
                        "state": "planned",
                        "authority_request_record": {
                            "requested_authority": ["repo:docs/**:write"],
                            "target_node_id": "worker-docs-authorized",
                            "reason": "Worker needs docs write access.",
                        },
                    },
                },
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "worker-docs-authorized",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "task_region_id": "authority-product-proof",
                        "candidate_id": "candidate-docs-authorized",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-authority-docs-write-to-worker-docs-authorized",
                    "from_node_id": "authority-docs-write",
                    "from_port": "authority_decision",
                    "to_node_id": "worker-docs-authorized",
                    "to_port": "authority",
                    "required": True,
                    "accepted_record_selector": {
                        "record_type": "authority_decision",
                        "schema": "AuthorityDecision",
                    },
                },
            ],
        },
    )

    assert [event.event_type for event in output] == [
        "graph_patch_accepted",
        "node_created",
        "output_record_accepted",
        "input_bound",
        "node_created",
        "edge_created",
    ]
    assert output[-1].payload["to_port"] == "authority"


def test_patch_rejects_malformed_request_gate_record() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-bad-request",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "gate-review",
                        "kind": "human_gate",
                        "state": "planned",
                        "decision_request": {
                            "decision_type": "approval",
                            "options": ["approve"],
                            "default_option": "reject",
                            "consequence_summary": "Review graph expansion.",
                        },
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == ["graph_patch_rejected"]
    assert output[0].payload["patch_id"] == "patch-bad-request"
    assert "invalid request record for node gate-review" in output[0].payload["reason"]
    assert "default_option must be one of options" in output[0].payload["reason"]


def test_gap_planner_no_op_patch_accepts_through_submit_patch() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "gap-no-op",
            "proposed_by_node_id": "gap-planner-1",
            "actor_role": "gap_planner",
            "base_graph_position": -1,
            "ops": [],
        },
    )

    assert [event.event_type for event in output] == ["graph_patch_accepted"]
    assert output[0].payload["actor_role"] == "gap_planner"


def test_gap_planner_corrective_work_patch_accepts_through_submit_patch() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "gap-corrective",
            "proposed_by_node_id": "gap-planner-1",
            "actor_role": "gap_planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "corrective-worker-1",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "task_region_id": "corrective_work_region",
                    },
                }
            ],
        },
    )

    assert [event.event_type for event in output] == ["graph_patch_accepted", "node_created"]
    assert output[1].payload["task_region_id"] == "corrective_work_region"


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
    assert output[0].payload["patch_id"] == "patch-1"
    assert output[0].payload["proposed_by_node_id"] == "planner-1"
    assert output[0].payload["actor_role"] == "planner"
    assert output[0].payload["base_graph_position"] == -1


def test_malformed_patch_is_rejected_at_schema_boundary() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-bad",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": "not-an-int",
            "ops": [],
        },
    )

    assert output[0].event_type == "command_rejected"
    assert output[0].payload["command_type"] == "submit_patch"
    assert "invalid command payload" in output[0].payload["reason"]
    assert "base_graph_position" in output[0].payload["reason"]


def test_seed_compiled_events_accepts_topology_and_controller_records_for_empty_run() -> None:
    seed_events = [
        _event("node_created", {"node_id": "root", "kind": "root", "state": "completed"}, 0),
        _event(
            "output_record_accepted",
            {
                "record_id": "run-context",
                "record_kind": "graph_record",
                "record_type": "run_context",
                "producer_node_id": "root",
                "port": "run_context",
                "schema": "RunContext",
                "value": {"routine_id": "routine-1", "routine_name": "Routine"},
            },
            1,
        ),
        _event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "state": "planned"},
            2,
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
            3,
        ),
        _event(
            "input_bound",
            {"edge_id": "edge-1", "to_node_id": "worker-1", "to_port": "routine_snapshot"},
            4,
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


def test_schedule_tick_path_in_scope_write_claim_blocks_overlapping_path() -> None:
    """A normalized path-in-scope write claim still conflicts with overlapping requests.

    Regression coverage for the Part A normalization changing scheduling-conflict
    semantics: before the fix, a claim shaped ``{"mode": "write", "scope": "<path>"}``
    with no ``paths`` was treated by ``_paths_overlap`` as conflicting with *everything*
    (empty paths list = overlaps all). After normalization it has a real paths entry, so
    it must still conflict with genuinely overlapping paths...
    """
    events = [
        *_active_lease_events_with_resource_claims(
            [{"mode": "write", "scope": "src/orchestrator/graph"}]
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-2",
                "kind": "worker",
                "state": "ready",
                "resource_claims": [
                    {
                        "mode": "write",
                        "scope": "repo",
                        "paths": ["src/orchestrator/graph/scheduler.py"],
                    }
                ],
            },
            3,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})

    assert "lease_granted" not in [event.event_type for event in output]


def test_schedule_tick_path_in_scope_write_claim_allows_disjoint_path() -> None:
    """...but must no longer conflict with genuinely disjoint paths."""
    events = [
        *_active_lease_events_with_resource_claims(
            [{"mode": "write", "scope": "src/orchestrator/graph"}]
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-2",
                "kind": "worker",
                "state": "ready",
                "resource_claims": [
                    {"mode": "write", "scope": "repo", "paths": ["docs/readme.md"]}
                ],
            },
            3,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    granted_node_ids = [
        event.payload["node_id"] for event in output if event.event_type == "lease_granted"
    ]
    assert granted_node_ids == ["worker-2"]


def test_reconcile_recovers_quiescent_graph_after_failed_required_check() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "graph_record",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
                "value": {
                    "routine_id": "routine-1",
                    "name": "Routine 1",
                    "content_hash": "hash-routine-1",
                    "step_count": 1,
                    "task_count": 1,
                },
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final-invariant-r1",
                "kind": "check",
                "role": "invariant_gate",
                "state": "completed",
                "task_region_id": "region-r1-final",
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-r1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-invariant-r1",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "region-r1-final",
                "candidate_id": "candidate-r1",
                "attempt_number": 1,
                "value": {
                    "status": "failed",
                    "classification": "tool_unavailable",
                    "command_id": "final-invariant",
                    "command_text": "check",
                    "command": {"cmd": "check"},
                    "worktree_path": ".",
                    "base_snapshot_id": "S0",
                    "execution_id": "exec-check-r1",
                    "exit_code": 127,
                    "duration_ms": 1,
                    "stdout": "",
                    "stderr": "not found",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "timeout_seconds": 60,
                    "environment_policy": {},
                },
            },
            4,
        ),
    ]

    assert project_task_states(events) == {"region-r1-final": "pending"}

    output = _apply_from_checkpoint(events, "reconcile", {"run_id": "run-1"})

    assert [event.event_type for event in output] == [
        "node_created",
        "edge_created",
        "input_bound",
        "edge_created",
        "input_bound",
    ]
    recovery_node = output[0].payload
    assert recovery_node["node_id"] == "planner-recover-check-result-r1"
    assert recovery_node["kind"] == "planner"
    assert recovery_node["role"] == "gap_planner"
    assert recovery_node["recovery_reason"] == "failed_required_check"
    assert output[2].payload["to_port"] == "verification_evidence"
    assert output[2].payload["record_ids"] == ["check-result-r1"]
    assert output[4].payload["to_port"] == "routine_snapshot"
    assert output[4].payload["record_ids"] == ["routine-snapshot-record"]

    next_output = _apply(events + output, "schedule_tick", {"run_id": "run-1"})

    assert any(
        event.event_type == "lease_granted"
        and event.payload["node_id"] == "planner-recover-check-result-r1"
        and event.payload["base_snapshot_id"] == "routine-snapshot-record"
        for event in next_output
    )


def test_reconcile_recovers_runtime_failed_check_without_check_result() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "graph_record",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
                "value": {
                    "routine_id": "routine-1",
                    "name": "Routine 1",
                    "content_hash": "hash-routine-1",
                    "step_count": 1,
                    "task_count": 1,
                },
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-runtime-failed",
                "kind": "check",
                "role": "invariant_gate",
                "state": "failed",
                "task_region_id": "region-r1-final",
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "failure-check-runtime-failed",
                "record_type": "failure_record",
                "record_kind": "graph_record",
                "schema": "FailureRecord",
                "producer_node_id": "check-runtime-failed",
                "port": "failure_record",
                "task_region_id": "region-r1-final",
                "value": {
                    "failed_node_id": "check-runtime-failed",
                    "phase": "runtime",
                    "error_class": "runtime_configuration_error",
                    "retryable": False,
                    "reason": "check node missing command_definition",
                },
            },
            4,
        ),
    ]

    assert project_task_states(events) == {"region-r1-final": "pending"}

    output = _apply_from_checkpoint(events, "reconcile", {"run_id": "run-1"})

    assert [event.event_type for event in output] == [
        "node_created",
        "edge_created",
        "input_bound",
        "edge_created",
        "input_bound",
    ]
    recovery_node = output[0].payload
    assert recovery_node["node_id"] == "planner-recover-failure-check-runtime-failed"
    assert recovery_node["recovery_reason"] == "failed_required_check"
    evidence_edge = output[1].payload
    assert evidence_edge["from_node_id"] == "check-runtime-failed"
    assert evidence_edge["from_port"] == "failure_record"
    assert evidence_edge["accepted_record_selector"] == {
        "record_type": "failure_record",
        "schema": "FailureRecord",
    }
    assert output[2].payload["to_port"] == "verification_evidence"
    assert output[2].payload["record_ids"] == ["failure-check-runtime-failed"]

    recovered_events = [
        *events,
        *output,
        _event(
            "node_retired",
            {"node_id": "check-runtime-failed", "reason": "recovered_runtime_failure"},
            5,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-runtime-failed-retry",
                "kind": "check",
                "role": "invariant_gate",
                "state": "completed",
                "task_region_id": "region-r1-final",
                "command_definition": {"id": "hidden-oracle", "cmd": "true", "must": True},
            },
            6,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-runtime-failed-retry",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-runtime-failed-retry",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "region-r1-final",
                "status": "passed",
                "value": {"status": "passed"},
            },
            7,
        ),
    ]

    recovered_task_states = project_task_states(recovered_events)
    assert recovered_task_states["region-r1-final"] == "accepted"


def test_schedule_tick_does_not_repair_failed_required_check() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "graph_record",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
                "value": {
                    "routine_id": "routine-1",
                    "name": "Routine 1",
                    "content_hash": "hash-routine-1",
                    "step_count": 1,
                    "task_count": 1,
                },
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final-invariant-r1",
                "kind": "check",
                "role": "invariant_gate",
                "state": "completed",
                "task_region_id": "region-r1-final",
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-r1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-invariant-r1",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "region-r1-final",
                "status": "failed",
            },
            4,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1"})

    assert output == []


def test_reconcile_is_idempotent_and_rejects_terminal_runs() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "graph_record",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
                "value": {
                    "routine_id": "routine-1",
                    "name": "Routine 1",
                    "content_hash": "hash-routine-1",
                    "step_count": 1,
                    "task_count": 1,
                },
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final-invariant-r1",
                "kind": "check",
                "role": "invariant_gate",
                "state": "completed",
                "task_region_id": "region-r1-final",
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-r1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-invariant-r1",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "region-r1-final",
                "status": "failed",
            },
            4,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})
    second_output = _apply([*events, *output], "reconcile", {"run_id": "run-1"})
    terminal_output = _apply(
        [_event("run_lifecycle_changed", {"to_state": "completed"}, 0)],
        "reconcile",
        {"run_id": "run-1"},
    )

    assert any(event.event_type == "node_created" for event in output)
    assert second_output == []
    assert [event.event_type for event in terminal_output] == ["command_rejected"]
    assert terminal_output[0].payload["command_type"] == "reconcile"
    assert terminal_output[0].payload["reason"] == "terminal run: completed"


def test_callback_check_result_emits_scoped_failed_check_recovery() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "routine_snapshot",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final-invariant-r1",
                "kind": "check",
                "role": "invariant_gate",
                "state": "running",
                "task_region_id": "region-r1-final",
            },
            3,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "check-final-invariant-r1",
                "lease_id": "lease-check",
                "generation": 1,
                "execution_id": "exec-check",
                "base_snapshot_id": "routine-snapshot-record",
            },
            4,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            node_id="check-final-invariant-r1",
            execution_id="exec-check",
            lease_id="lease-check",
            base_snapshot_id="routine-snapshot-record",
            observed_graph_position=4,
            payload={
                "payload_hash": "hash-check",
                "output_records": [
                    {
                        "record_id": "check-result-r1",
                        "record_kind": "output",
                        "record_type": "check_result",
                        "producer_node_id": "check-final-invariant-r1",
                        "port": "check_result",
                        "schema": "CheckResult",
                        "candidate_id": "candidate-1",
                        "task_region_id": "region-r1-final",
                        "attempt_number": 1,
                        "value": {
                            "status": "failed",
                            "classification": "failed",
                            "command_id": "unit-check",
                            "command_binding": None,
                            "command_text": "unit check",
                            "command": {"id": "unit-check", "argv": ["false"]},
                            "worktree_path": "/tmp/worktree",
                            "base_snapshot_id": "routine-snapshot-record",
                            "execution_id": "exec-check",
                            "exit_code": 1,
                            "duration_ms": 1,
                            "stdout": "",
                            "stderr": "failed",
                            "stdout_truncated": False,
                            "stderr_truncated": False,
                            "timeout_seconds": 60,
                            "environment_policy": {
                                "cwd": "/tmp/worktree",
                                "env": "inherited",
                                "shell": False,
                            },
                        },
                    }
                ],
            },
        ),
    )

    assert any(
        event.event_type == "node_created"
        and event.payload["node_id"] == "planner-recover-check-result-r1"
        for event in output
    )
    assert any(
        event.event_type == "input_bound"
        and event.payload["to_port"] == "verification_evidence"
        and event.payload["record_ids"] == ["check-result-r1"]
        for event in output
    )


def test_schedule_tick_does_not_duplicate_existing_failed_check_recovery() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "routine_snapshot",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final-invariant-r1",
                "kind": "check",
                "role": "invariant_gate",
                "state": "completed",
                "task_region_id": "region-r1-final",
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-r1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-invariant-r1",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "region-r1-final",
                "status": "failed",
            },
            4,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-gap-existing",
                "kind": "planner",
                "role": "gap_planner",
                "state": "completed",
                "task_region_id": "region-r1-gap",
            },
            5,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-existing-gap",
                "from_node_id": "check-final-invariant-r1",
                "from_port": "check_result",
                "to_node_id": "planner-gap-existing",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "check_result",
                    "schema": "CheckResult",
                },
            },
            6,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1"})

    assert output == []


def test_reconcile_fails_after_no_successor_failed_check_recovery() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "check-final-invariant-r1",
                "kind": "check",
                "role": "invariant_gate",
                "state": "completed",
                "task_region_id": "region-r1-final",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-r1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-invariant-r1",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "region-r1-final",
                "status": "failed",
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-recover-check-result-r1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "completed",
                "task_region_id": "recovery-region-r1-final",
                "recovery_reason": "failed_required_check",
                "recovery_of_node_id": "check-final-invariant-r1",
                "recovery_of_record_id": "check-result-r1",
            },
            3,
        ),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-no-safe-mutation",
                "proposed_by_node_id": "planner-recover-check-result-r1",
                "successor_planner_node_ids": [],
            },
            4,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})

    assert [event.event_type for event in output] == ["run_lifecycle_changed"]
    assert output[0].payload["to_state"] == "failed"
    assert output[0].payload["trigger"] == "recovery_planner_no_successor"
    assert output[0].payload["node_id"] == "planner-recover-check-result-r1"
    assert output[0].payload["patch_id"] == "patch-no-safe-mutation"
    assert output[0].payload["recovery_of_record_id"] == "check-result-r1"


def test_reconcile_does_not_fail_after_environment_no_successor_recovery() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "check-final-invariant-r1",
                "kind": "check",
                "role": "invariant_gate",
                "state": "completed",
                "task_region_id": "region-r1-final",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-r1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-invariant-r1",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "region-r1-final",
                "value": {
                    "status": "failed",
                    "classification": "tool_unavailable",
                    "command_text": "npm --prefix ui test -- RunEvidenceDigest",
                    "stderr": "sh: vitest: command not found",
                    "exit_code": 127,
                },
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-recover-check-result-r1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "completed",
                "task_region_id": "recovery-region-r1-final",
                "recovery_reason": "failed_required_check",
                "recovery_of_node_id": "check-final-invariant-r1",
                "recovery_of_record_id": "check-result-r1",
            },
            3,
        ),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-no-safe-mutation",
                "proposed_by_node_id": "planner-recover-check-result-r1",
                "successor_planner_node_ids": [],
            },
            4,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})

    assert not any(
        event.event_type == "run_lifecycle_changed" and event.payload.get("to_state") == "failed"
        for event in output
    )


def test_lifecycle_resume_reopens_failed_run_for_operator_only() -> None:
    failed_events = [_event("run_lifecycle_changed", {"to_state": "failed"}, 0)]

    # No actor_role: rejected.
    rejected = _apply(failed_events, "resume")
    assert rejected[0].event_type == "command_rejected"
    assert "operator" in rejected[0].payload["reason"]

    # Non-operator actor: rejected.
    rejected_planner = _apply(
        failed_events,
        "resume",
        {"run_id": "run-1", "actor_role": "planner"},
    )
    assert rejected_planner[0].event_type == "command_rejected"

    # Human/operator actor: failed -> resuming.
    for actor_role in ("human", "operator"):
        reopened = _apply(
            failed_events,
            "resume",
            {"run_id": "run-1", "actor_role": actor_role},
        )
        assert reopened[0].event_type == "run_lifecycle_changed"
        assert reopened[0].payload["from_state"] == "failed"
        assert reopened[0].payload["to_state"] == "resuming"

    # Second resume completes the reopen: resuming -> active (ungated).
    resuming_events = [_event("run_lifecycle_changed", {"to_state": "resuming"}, 0)]
    activated = _apply(resuming_events, "resume")
    assert activated[0].event_type == "run_lifecycle_changed"
    assert activated[0].payload["to_state"] == "active"


def test_reconcile_no_successor_skips_recovery_with_executable_successors() -> None:
    # Same shape as test_reconcile_fails_after_no_successor_failed_check_recovery,
    # but the recovery planner's accepted patch wired a corrective worker
    # (executable successor). That is real recovery work, not a dead end, so
    # the sweep must not fail the run (W4 0694df2d regression, 2026-07-04).
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "check-final-invariant-r1",
                "kind": "check",
                "role": "invariant_gate",
                "state": "completed",
                "task_region_id": "region-r1-final",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-r1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-invariant-r1",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "region-r1-final",
                "status": "failed",
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-recover-check-result-r1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "completed",
                "task_region_id": "recovery-region-r1-final",
                "recovery_reason": "failed_required_check",
                "recovery_of_node_id": "check-final-invariant-r1",
                "recovery_of_record_id": "check-result-r1",
            },
            3,
        ),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-corrective-work",
                "proposed_by_node_id": "planner-recover-check-result-r1",
                "successor_planner_node_ids": [],
            },
            4,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-corrective-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "corrective_work_region",
            },
            5,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-gap-to-corrective-worker",
                "from_node_id": "planner-recover-check-result-r1",
                "from_port": "classified_gap",
                "to_node_id": "worker-corrective-1",
                "to_port": "classified_gap",
                "required": True,
            },
            6,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})

    assert not any(
        event.event_type == "run_lifecycle_changed" and event.payload.get("to_state") == "failed"
        for event in output
    )

    # Validity control: without the executable successor the same graph is a
    # genuine dead end and the sweep still fails the run.
    dead_end_output = _apply(events[:5], "reconcile", {"run_id": "run-1"})
    assert any(
        event.event_type == "run_lifecycle_changed"
        and event.payload.get("to_state") == "failed"
        and event.payload.get("trigger") == "recovery_planner_no_successor"
        for event in dead_end_output
    )


def test_reconcile_no_successor_skips_superseded_failed_verification() -> None:
    # A failed verification whose task region later produced a PASSING
    # candidate is superseded: it must neither trigger the no-successor
    # terminal failure nor count as a current failure needing recovery.
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "worker-a",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "region-a",
            },
            1,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-a",
                "kind": "verifier",
                "state": "completed",
                "task_region_id": "region-a",
            },
            2,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "cand-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-a",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "task_region_id": "region-a",
                "candidate_id": "cand-1",
            },
            3,
        ),
        _event(
            "verification_failed",
            {
                "node_id": "verifier-a",
                "record_id": "vf-1",
                "candidate_id": "cand-1",
                "task_region_id": "region-a",
            },
            4,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-recover-vf-1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "completed",
                "task_region_id": "recovery-region-a",
                "recovery_reason": "failed_verification",
                "recovery_of_node_id": "verifier-a",
                "recovery_of_record_id": "vf-1",
            },
            5,
        ),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-no-planner-successor",
                "proposed_by_node_id": "planner-recover-vf-1",
                "successor_planner_node_ids": [],
            },
            6,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-a-retry",
                "kind": "verifier",
                "state": "completed",
                "task_region_id": "region-a",
            },
            7,
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-a-retry",
                "record_id": "vp-1",
                "candidate_id": "cand-2",
                "task_region_id": "region-a",
            },
            8,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})

    assert not any(
        event.event_type == "run_lifecycle_changed" and event.payload.get("to_state") == "failed"
        for event in output
    )

    # Validity control: without the later regional pass, the failed
    # verification is current and its dead-end recovery fails the run.
    dead_end_output = _apply(events[:7], "reconcile", {"run_id": "run-1"})
    assert any(
        event.event_type == "run_lifecycle_changed"
        and event.payload.get("to_state") == "failed"
        and event.payload.get("trigger") == "recovery_planner_no_successor"
        for event in dead_end_output
    )


def test_reconcile_does_not_fail_recovered_run_w2_shape() -> None:
    # Regression for run 69ce4f7c (W2, 2026-07-04): failed verification ->
    # kernel recovery planner -> accepted patch with NO successor planner but
    # a corrective worker+verifier -> repair candidate passes -> final
    # invariant check passes -> quiescent tick. The kernel used to emit
    # run_lifecycle_changed active->failed (recovery_planner_no_successor)
    # at event v557 despite the recovery having fully succeeded.
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "worker-impl",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "region-impl",
            },
            1,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-impl",
                "kind": "verifier",
                "state": "completed",
                "task_region_id": "region-impl",
            },
            2,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "cand-impl-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-impl",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "task_region_id": "region-impl",
                "candidate_id": "cand-impl-1",
            },
            3,
        ),
        # The primary verification fails (W2: verification-exec-857f...).
        _event(
            "verification_failed",
            {
                "node_id": "verifier-impl",
                "record_id": "vf-impl-1",
                "candidate_id": "cand-impl-1",
                "task_region_id": "region-impl",
            },
            4,
        ),
        # Kernel-created recovery planner for the failed verification.
        _event(
            "node_created",
            {
                "node_id": "planner-recover-vf-impl-1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "completed",
                "task_region_id": "recovery-region-impl",
                "recovery_reason": "failed_verification",
                "recovery_of_node_id": "verifier-impl",
                "recovery_of_record_id": "vf-impl-1",
            },
            5,
        ),
        # Its accepted patch: no successor planner, but corrective work nodes.
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-source-scope-corrective-v2",
                "proposed_by_node_id": "planner-recover-vf-impl-1",
                "successor_planner_node_ids": [],
            },
            6,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-repair",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "corrective_work_region",
            },
            7,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-repair",
                "kind": "verifier",
                "state": "completed",
                "task_region_id": "corrective_work_region",
            },
            8,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-recovery-gap-to-repair-worker",
                "from_node_id": "planner-recover-vf-impl-1",
                "from_port": "classified_gap",
                "to_node_id": "worker-repair",
                "to_port": "classified_gap",
                "required": True,
            },
            9,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-repair-worker-to-verifier",
                "from_node_id": "worker-repair",
                "from_port": "candidate",
                "to_node_id": "verifier-repair",
                "to_port": "candidate_under_test",
                "required": True,
            },
            10,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "cand-repair-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-repair",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "task_region_id": "corrective_work_region",
                "candidate_id": "cand-repair-1",
            },
            11,
        ),
        # The repair candidate passes verification.
        _event(
            "verification_passed",
            {
                "node_id": "verifier-repair",
                "record_id": "vp-repair-1",
                "candidate_id": "cand-repair-1",
                "task_region_id": "corrective_work_region",
            },
            12,
        ),
        # Final invariant check completed with a passing result.
        _event(
            "node_created",
            {
                "node_id": "check-final-invariant",
                "kind": "check",
                "role": "invariant_gate",
                "state": "completed",
                "task_region_id": "region-final-invariant",
            },
            13,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-final-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-invariant",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "region-final-invariant",
                "status": "passed",
                "value": {"status": "passed"},
            },
            14,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})

    assert not any(
        event.event_type == "run_lifecycle_changed" and event.payload.get("to_state") == "failed"
        for event in output
    )


def test_reconcile_ignores_retired_failed_check_recovery_target() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "routine_snapshot",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final-invariant-r1",
                "kind": "check",
                "role": "invariant_gate",
                "state": "completed",
                "task_region_id": "region-r1-final",
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-r1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final-invariant-r1",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "region-r1-final",
                "status": "failed",
            },
            4,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-gap-retired",
                "kind": "planner",
                "role": "gap_planner",
                "state": "retired",
                "task_region_id": "region-r1-gap",
            },
            5,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-retired-gap",
                "from_node_id": "check-final-invariant-r1",
                "from_port": "check_result",
                "to_node_id": "planner-gap-retired",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "check_result",
                    "schema": "CheckResult",
                },
            },
            6,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})

    recovery_node = next(event.payload for event in output if event.event_type == "node_created")
    assert recovery_node["node_id"] == "planner-recover-check-result-r1"
    assert recovery_node["recovery_reason"] == "failed_required_check"


def test_reconcile_creates_gap_planner_for_failed_corrective_verifier() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "graph_record",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
                "value": {
                    "routine_id": "routine-1",
                    "name": "Routine 1",
                    "content_hash": "hash-routine-1",
                    "step_count": 1,
                    "task_count": 1,
                },
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-corrective",
                "kind": "worker",
                "role": "fixer",
                "state": "completed",
                "task_region_id": "corrective_work_region",
                "candidate_id": "candidate-fix",
                "attempt_number": 2,
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-fix",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-corrective",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-fix",
                "task_region_id": "corrective_work_region",
                "attempt_number": 2,
                "value": {"summary": "corrective candidate"},
            },
            4,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-corrective",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "task_region_id": "corrective_work_region",
                "candidate_id": "candidate-fix",
            },
            5,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-passed-old",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-corrective",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-old",
                "outcome": "passed",
                "value": {
                    "outcome": "passed",
                    "grades": [{"requirement_id": "R-1", "grade": "A"}],
                },
            },
            6,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-fix-failed",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-corrective",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-fix",
                "outcome": "failed",
                "value": {
                    "outcome": "failed",
                    "grades": [{"requirement_id": "R-1", "grade": "C"}],
                },
            },
            7,
        ),
        _event(
            "verification_failed",
            {
                "node_id": "verifier-corrective",
                "verifier_node_id": "verifier-corrective",
                "candidate_id": "candidate-fix",
                "outcome": "failed",
                "record_id": "verification-fix-failed",
                "task_region_id": "corrective_work_region",
            },
            8,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final",
                "kind": "check",
                "role": "invariant_gate",
                "state": "blocked",
                "task_region_id": "final-region",
                "command_definition": {"id": "hidden-oracle", "cmd": "true", "must": True},
            },
            9,
        ),
    ]

    assert project_task_states(events)["corrective_work_region"] == "needs_revision"

    output = _apply_from_checkpoint(events, "reconcile", {"run_id": "run-1"})

    assert [event.event_type for event in output[:5]] == [
        "node_created",
        "edge_created",
        "input_bound",
        "edge_created",
        "input_bound",
    ]
    recovery_node = output[0].payload
    assert recovery_node["node_id"] == "planner-recover-verification-fix-failed"
    assert recovery_node["role"] == "gap_planner"
    assert recovery_node["recovery_reason"] == "failed_verification"
    assert output[1].payload["accepted_record_selector"] == {
        "record_type": "verification_report",
        "schema": "VerificationReport",
        "outcome": "failed",
    }
    assert output[2].payload["to_port"] == "verification_evidence"
    assert output[2].payload["record_ids"] == ["verification-fix-failed"]
    assert output[4].payload["to_port"] == "routine_snapshot"
    assert output[4].payload["record_ids"] == ["routine-snapshot-record"]

    next_output = _apply(events + output, "schedule_tick", {"run_id": "run-1"})

    assert any(
        event.event_type == "lease_granted"
        and event.payload["node_id"] == "planner-recover-verification-fix-failed"
        and event.payload["base_snapshot_id"] == "routine-snapshot-record"
        for event in next_output
    )


def test_schedule_tick_does_not_duplicate_existing_failed_verification_recovery() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "routine_snapshot",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-implementation",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "implementation-region",
                "candidate_id": "candidate-1",
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-implementation",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "task_region_id": "implementation-region",
                "value": {},
            },
            4,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-implementation",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "task_region_id": "implementation-region",
                "candidate_id": "candidate-1",
            },
            5,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-implementation-failed",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-implementation",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-1",
                "outcome": "failed",
                "value": {
                    "outcome": "failed",
                    "grades": [{"requirement_id": "R-1", "grade": "C"}],
                },
            },
            6,
        ),
        _event(
            "verification_failed",
            {
                "node_id": "verifier-implementation",
                "verifier_node_id": "verifier-implementation",
                "candidate_id": "candidate-1",
                "outcome": "failed",
                "record_id": "verification-implementation-failed",
                "task_region_id": "implementation-region",
            },
            7,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-gap-existing",
                "kind": "planner",
                "role": "gap_planner",
                "state": "completed",
                "task_region_id": "implementation-region",
            },
            8,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-existing-verification-gap",
                "from_node_id": "verifier-implementation",
                "from_port": "verification_report",
                "to_node_id": "planner-gap-existing",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                },
            },
            9,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1"})

    assert output == []


def test_passed_corrective_verifier_releases_final_check_without_recovery() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "routine_snapshot",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-corrective",
                "kind": "worker",
                "role": "fixer",
                "state": "completed",
                "task_region_id": "corrective_work_region",
                "candidate_id": "candidate-fix",
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-fix",
                "record_kind": "output",
                "producer_node_id": "worker-corrective",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-fix",
                "task_region_id": "corrective_work_region",
                "value": {},
            },
            4,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-corrective",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "task_region_id": "corrective_work_region",
                "candidate_id": "candidate-fix",
            },
            5,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final",
                "kind": "check",
                "role": "invariant_gate",
                "state": "planned",
                "task_region_id": "final-region",
                "command_definition": {"id": "hidden-oracle", "cmd": "true", "must": True},
            },
            6,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-corrective-final",
                "from_node_id": "verifier-corrective",
                "from_port": "verification_report",
                "to_node_id": "check-final",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                },
            },
            7,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-fix-passed",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-corrective",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-fix",
                "outcome": "passed",
                "value": {
                    "outcome": "passed",
                    "grades": [{"requirement_id": "R-1", "grade": "A"}],
                },
            },
            8,
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-corrective",
                "verifier_node_id": "verifier-corrective",
                "candidate_id": "candidate-fix",
                "outcome": "passed",
                "record_id": "verification-fix-passed",
                "task_region_id": "corrective_work_region",
            },
            9,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-corrective-final",
                "to_node_id": "check-final",
                "to_port": "verification_evidence",
                "record_ids": ["verification-fix-passed"],
            },
            10,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert not any(
        event.event_type == "node_created"
        and event.payload.get("recovery_reason") == "failed_verification"
        for event in output
    )
    assert any(
        event.event_type == "lease_granted" and event.payload["node_id"] == "check-final"
        for event in output
    )


def test_passed_verification_recovers_final_check_and_retires_failure_branch() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "worker-implementation",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
                "task_region_id": "implementation-region",
                "candidate_id": "candidate-1",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-implementation",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "task_region_id": "implementation-region",
                "value": {},
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-implementation",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "task_region_id": "implementation-region",
                "candidate_id": "candidate-1",
            },
            3,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-implementation-passed",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-implementation",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-1",
                "task_region_id": "implementation-region",
                "outcome": "passed",
                "value": {
                    "outcome": "passed",
                    "grades": [{"requirement_id": "R-1", "grade": "A"}],
                },
            },
            4,
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-implementation",
                "verifier_node_id": "verifier-implementation",
                "candidate_id": "candidate-1",
                "outcome": "passed",
                "record_id": "verification-implementation-passed",
                "task_region_id": "implementation-region",
            },
            5,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-gap",
                "kind": "planner",
                "role": "gap_planner",
                "state": "planned",
                "task_region_id": "gap-region",
            },
            6,
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-corrective",
                "kind": "worker",
                "role": "fixer",
                "state": "planned",
                "task_region_id": "corrective-region",
                "candidate_id": "candidate-fix",
            },
            7,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-corrective",
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "task_region_id": "corrective-region",
                "candidate_id": "candidate-fix",
            },
            8,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final",
                "kind": "check",
                "role": "invariant_gate",
                "state": "planned",
                "task_region_id": "final-region",
                "command_definition": {"id": "hidden-oracle", "cmd": "true", "must": True},
            },
            9,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-verifier-gap",
                "from_node_id": "verifier-implementation",
                "from_port": "verification_report",
                "to_node_id": "planner-gap",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "failed",
                },
            },
            10,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-gap-corrective",
                "from_node_id": "planner-gap",
                "from_port": "classified_gap",
                "to_node_id": "worker-corrective",
                "to_port": "classified_gap",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "gap_classification",
                    "schema": "GapClassification",
                    "classification": "corrective_work_required",
                },
            },
            11,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-corrective-verifier",
                "from_node_id": "worker-corrective",
                "from_port": "candidate",
                "to_node_id": "verifier-corrective",
                "to_port": "candidate_under_test",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "candidate",
                    "schema": "ImplementationCandidate",
                },
            },
            12,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-corrective-final",
                "from_node_id": "verifier-corrective",
                "from_port": "verification_report",
                "to_node_id": "check-final",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                },
            },
            13,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})

    recovery_edge = next(
        event
        for event in output
        if event.event_type == "edge_created"
        and event.payload.get("metadata", {}).get("purpose")
        == "passed_verification_final_invariant_recovery"
    )
    assert recovery_edge.payload["from_node_id"] == "verifier-implementation"
    assert recovery_edge.payload["to_node_id"] == "check-final"
    assert recovery_edge.payload["accepted_record_selector"] == {
        "record_type": "verification_report",
        "schema": "VerificationReport",
        "outcome": "passed",
    }
    assert any(
        event.event_type == "input_bound"
        and event.payload["to_node_id"] == "check-final"
        and event.payload["record_ids"] == ["verification-implementation-passed"]
        for event in output
    )
    retired_node_ids = {
        event.payload["node_id"] for event in output if event.event_type == "node_retired"
    }
    assert retired_node_ids == {"planner-gap", "worker-corrective", "verifier-corrective"}

    next_output = _apply(
        events + output,
        "schedule_tick",
        {"run_id": "run-1", "base_snapshot_id": "S0"},
    )

    assert any(
        event.event_type == "lease_granted" and event.payload["node_id"] == "check-final"
        for event in next_output
    )
    task_states = project_task_states([*events, *output])
    assert task_states["gap-region"] == "accepted"
    assert task_states["corrective-region"] == "accepted"


def test_passed_verification_final_check_sweep_skips_cycle_forming_edge() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "verifier-implementation",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "task_region_id": "implementation-region",
                "candidate_id": "candidate-1",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-implementation-passed",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-implementation",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-1",
                "task_region_id": "implementation-region",
                "outcome": "passed",
                "value": {
                    "outcome": "passed",
                    "grades": [{"requirement_id": "R-1", "grade": "A"}],
                },
            },
            2,
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-implementation",
                "verifier_node_id": "verifier-implementation",
                "candidate_id": "candidate-1",
                "outcome": "passed",
                "record_id": "verification-implementation-passed",
                "task_region_id": "implementation-region",
            },
            3,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-gap",
                "kind": "planner",
                "role": "gap_planner",
                "state": "planned",
                "task_region_id": "gap-region",
            },
            4,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-verifier-gap",
                "from_node_id": "verifier-implementation",
                "from_port": "verification_report",
                "to_node_id": "planner-gap",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "failed",
                },
            },
            5,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final",
                "kind": "check",
                "role": "invariant_gate",
                "state": "planned",
                "task_region_id": "final-region",
                "command_definition": {"id": "hidden-oracle", "cmd": "true", "must": True},
            },
            6,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-check-back-to-verifier",
                "from_node_id": "check-final",
                "from_port": "check_result",
                "to_node_id": "verifier-implementation",
                "to_port": "verification_evidence",
                "required": False,
                "accepted_record_selector": {
                    "record_type": "check_result",
                    "schema": "CheckResult",
                },
            },
            7,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})

    assert not any(
        event.event_type == "edge_created"
        and event.payload.get("from_node_id") == "verifier-implementation"
        and event.payload.get("to_node_id") == "check-final"
        for event in output
    )
    assert any(
        event.event_type == "node_retired" and event.payload["node_id"] == "planner-gap"
        for event in output
    )

    valid_output = _apply(
        events[:-1],
        "reconcile",
        {"run_id": "run-1"},
    )
    assert any(
        event.event_type == "edge_created"
        and event.payload.get("metadata", {}).get("purpose")
        == "passed_verification_final_invariant_recovery"
        for event in valid_output
    )
    valid_projection = _project([*events[:-1], *valid_output])
    assert any(
        edge.from_node_id == "verifier-implementation" and edge.to_node_id == "check-final"
        for edge in valid_projection["edges"].values()
    )


def test_corrective_passed_verification_repoints_stranded_final_check() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "verifier-primary",
                "kind": "verifier",
                "role": "verifier",
                "state": "failed",
                "task_region_id": "primary-region",
                "candidate_id": "candidate-primary",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-primary-failed",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-primary",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-primary",
                "task_region_id": "primary-region",
                "outcome": "failed",
                "value": {"outcome": "failed"},
            },
            2,
        ),
        _event(
            "verification_failed",
            {
                "node_id": "verifier-primary",
                "verifier_node_id": "verifier-primary",
                "candidate_id": "candidate-primary",
                "outcome": "failed",
                "record_id": "verification-primary-failed",
                "task_region_id": "primary-region",
            },
            3,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final",
                "kind": "check",
                "role": "invariant_gate",
                "state": "planned",
                "task_region_id": "final-region",
                "command_definition": {"id": "hidden-oracle", "cmd": "true", "must": True},
            },
            4,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-primary-pass-final",
                "from_node_id": "verifier-primary",
                "from_port": "verification_report",
                "to_node_id": "check-final",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "passed",
                },
            },
            5,
        ),
        _event(
            "node_deferred",
            {"node_id": "check-final", "reason": "missing_required_input:verification_evidence"},
            6,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-corrective",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "task_region_id": "corrective-region",
                "candidate_id": "candidate-corrective",
            },
            7,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-corrective-passed",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-corrective",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-corrective",
                "task_region_id": "corrective-region",
                "outcome": "passed",
                "value": {"outcome": "passed"},
            },
            8,
        ),
        _event(
            "verification_passed",
            {
                "node_id": "verifier-corrective",
                "verifier_node_id": "verifier-corrective",
                "candidate_id": "candidate-corrective",
                "outcome": "passed",
                "record_id": "verification-corrective-passed",
                "task_region_id": "corrective-region",
            },
            9,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})

    recovery_edges = [
        event
        for event in output
        if event.event_type == "edge_created"
        and event.payload.get("metadata", {}).get("purpose")
        == "passed_verification_final_invariant_recovery"
    ]
    assert len(recovery_edges) == 1
    assert recovery_edges[0].payload["from_node_id"] == "verifier-corrective"
    assert recovery_edges[0].payload["to_node_id"] == "check-final"
    assert any(
        event.event_type == "input_bound"
        and event.payload["to_node_id"] == "check-final"
        and event.payload["record_ids"] == ["verification-corrective-passed"]
        for event in output
    )


def test_passed_final_check_retires_failure_continuation() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "check-final",
                "kind": "check",
                "role": "invariant_gate",
                "state": "completed",
                "task_region_id": "final-region",
                "command_definition": {"id": "hidden-oracle", "cmd": "true", "must": True},
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "check-result-passed",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-final",
                "port": "check_result",
                "schema": "CheckResult",
                "task_region_id": "final-region",
                "value": {"status": "passed"},
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "planner-gap-final",
                "kind": "planner",
                "role": "gap_planner",
                "state": "planned",
                "task_region_id": "final-gap-region",
            },
            3,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-final-check-gap",
                "from_node_id": "check-final",
                "from_port": "check_result",
                "to_node_id": "planner-gap-final",
                "to_port": "verification_evidence",
                "required": False,
                "accepted_record_selector": {
                    "record_type": "check_result",
                    "schema": "CheckResult",
                },
            },
            4,
        ),
    ]

    output = _apply(events, "reconcile", {"run_id": "run-1"})

    assert [event.payload["node_id"] for event in output if event.event_type == "node_retired"] == [
        "planner-gap-final"
    ]
    task_states = project_task_states([*events, *output])
    assert task_states["final-gap-region"] == "accepted"


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


def test_output_record_binds_to_producer_class_edge() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {"node_id": "verifier-1", "kind": "verifier", "role": "verifier", "state": "running"},
            1,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "verifier-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
            },
            2,
        ),
        _event("node_created", {"node_id": "check-final", "kind": "check", "state": "planned"}, 3),
        _event(
            "input_bound",
            {
                "edge_id": "edge-candidate-verifier",
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            4,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-verifier-class-final",
                "from_node_id": "*",
                "from_node_kind": "verifier",
                "from_node_role": "verifier",
                "from_port": "verification_report",
                "to_node_id": "check-final",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "passed",
                },
            },
            5,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            node_id="verifier-1",
            execution_id="exec-1",
            lease_id="lease-1",
            payload={
                "payload_hash": "hash-verification",
                "output_records": [
                    {
                        "record_id": "verification-1",
                        "record_kind": "verification",
                        "record_type": "verification_report",
                        "producer_node_id": "verifier-1",
                        "port": "verification_report",
                        "schema": "VerificationReport",
                        "candidate_id": "candidate-1",
                        "outcome": "passed",
                        "value": {
                            "outcome": "passed",
                            "grades": [{"requirement_id": "R1", "grade": "pass"}],
                        },
                    }
                ],
            },
        ),
    )

    assert any(
        event.event_type == "input_bound"
        and event.payload["edge_id"] == "edge-verifier-class-final"
        and event.payload["to_node_id"] == "check-final"
        and event.payload["to_port"] == "verification_evidence"
        and event.payload["record_ids"] == ["verification-1"]
        for event in output
    )


def test_output_record_does_not_bind_to_non_matching_producer_class_edge() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "role": "builder", "state": "running"},
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
        _event("node_created", {"node_id": "check-final", "kind": "check", "state": "planned"}, 3),
        _event(
            "edge_created",
            {
                "edge_id": "edge-verifier-class-final",
                "from_node_id": "*",
                "from_node_kind": "verifier",
                "from_node_role": "verifier",
                "from_port": "candidate",
                "to_node_id": "check-final",
                "to_port": "candidate_under_test",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "candidate",
                    "schema": "ImplementationCandidate",
                },
            },
            4,
        ),
    ]

    output = _apply(events, "submit_callback", _callback_payload())

    assert not any(
        event.event_type == "input_bound"
        and event.payload["edge_id"] == "edge-verifier-class-final"
        for event in output
    )


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
        _event(
            "lease_granted",
            {
                "lease_id": "lease-authority-1",
                "node_id": "authority-1",
                "generation": 1,
            },
            4,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert [(event.event_type, event.payload) for event in output] == [
        ("node_deferred", {"node_id": "worker-1", "reason": "missing_required_input:candidate"})
    ]


def test_schedule_tick_emits_dead_input_for_terminal_failed_source() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "producer-1", "kind": "worker", "state": "failed"}, 1),
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
        _event(
            "input_bound",
            {"edge_id": "edge-1", "to_node_id": "worker-1", "to_port": "candidate"},
            4,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert [(event.event_type, event.payload) for event in output] == [
        (
            "dead_input_detected",
            {
                "node_id": "worker-1",
                "from_node_id": "producer-1",
                "to_port": "candidate",
                "reason": "upstream_failed:producer-1",
            },
        ),
        ("node_deferred", {"node_id": "worker-1", "reason": "upstream_failed:producer-1"}),
    ]


def test_schedule_tick_dedupes_unchanged_missing_required_input() -> None:
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

    first = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})
    second = _apply(
        [*events, *first],
        "schedule_tick",
        {"run_id": "run-1", "base_snapshot_id": "S0"},
    )

    assert [(event.event_type, event.payload) for event in first] == [
        ("node_deferred", {"node_id": "worker-1", "reason": "missing_required_input:candidate"})
    ]
    assert second == []


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


def test_schedule_tick_defers_ungranted_authority_request_input() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {"node_id": "authority-1", "kind": "authority_request", "state": "completed"},
            1,
        ),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "blocked"}, 2),
        _event(
            "edge_created",
            {
                "edge_id": "edge-authority",
                "from_node_id": "authority-1",
                "from_port": "authority_decision",
                "to_node_id": "worker-1",
                "to_port": "authority",
                "required": True,
            },
            3,
        ),
        _event(
            "input_bound",
            {"edge_id": "edge-authority", "to_node_id": "worker-1", "to_port": "authority"},
            4,
        ),
    ]

    output = _apply(events, "schedule_tick", {"run_id": "run-1", "base_snapshot_id": "S0"})

    assert [(event.event_type, event.payload) for event in output] == [
        (
            "node_deferred",
            {"node_id": "worker-1", "reason": "authority_not_granted:authority-1"},
        )
    ]


def test_schedule_tick_allows_granted_authority_request_input() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {"node_id": "authority-1", "kind": "authority_request", "state": "completed"},
            1,
        ),
        _event("authority_decision_recorded", {"node_id": "authority-1", "decision": "granted"}, 2),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "blocked"}, 3),
        _event(
            "edge_created",
            {
                "edge_id": "edge-authority",
                "from_node_id": "authority-1",
                "from_port": "authority_decision",
                "to_node_id": "worker-1",
                "to_port": "authority",
                "required": True,
            },
            4,
        ),
        _event(
            "input_bound",
            {"edge_id": "edge-authority", "to_node_id": "worker-1", "to_port": "authority"},
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


def test_schedule_tick_rechecks_ready_check_precondition_requires_command_definition() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "check-1", "kind": "check", "state": "ready"}, 1),
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


def test_schedule_tick_check_precondition_passes_with_known_command_binding() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "planned",
                "command_binding": "dynamic_feature_hidden_oracle",
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
        "output_record_accepted",
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
        "record_id": "recovery-plan-worker-1-lease-1",
        "record_kind": "output",
        "record_type": "recovery_plan",
        "producer_node_id": "worker-1",
        "port": "recovery_plan",
        "schema": "RecoveryPlan",
        "value": {
            "action": "retry",
            "responsible_actor": "controller",
            "graph_changes": [{"op": "set_node_state", "node_id": "worker-1", "state": "ready"}],
            "reason": "process_exit",
        },
    }
    assert output[4].payload == {
        "node_id": "worker-1",
        "new_state": "ready",
        "trigger": "agent_died_retry_scheduled",
        "attempt_number": 1,
    }
    assert projection["leases"]["lease-1"].state == "revoked"
    assert projection["node_states"]["worker-1"] == "ready"


def test_agent_died_check_missing_command_fails_without_retry() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "check-1", "kind": "check", "state": "running"}, 1),
        _event(
            "lease_granted",
            {
                "node_id": "check-1",
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
            "reason": "check node missing command_definition",
        },
    )
    projection = _project([*events, *output])

    assert [event.event_type for event in output] == [
        "agent_died",
        "lease_revoked",
        "output_record_accepted",
        "node_state_changed",
    ]
    assert output[2].payload["record_type"] == "failure_record"
    assert output[2].payload["value"] == {
        "failed_node_id": "check-1",
        "phase": "runtime",
        "error_class": "runtime_configuration_error",
        "retryable": False,
        "lease_id": "lease-1",
        "execution_id": "exec-1",
        "lease_generation": 1,
        "reason": "check node missing command_definition",
    }
    assert output[3].payload == {
        "node_id": "check-1",
        "new_state": "failed",
        "trigger": "non_retryable_runtime_error",
        "reason": "check node missing command_definition",
    }
    assert projection["leases"]["lease-1"].state == "revoked"
    assert projection["node_states"]["check-1"] == "failed"


def test_agent_died_retry_backoff_blocks_until_not_before() -> None:
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
    clock = FakeClock()
    id_gen = SequentialIdGenerator()

    output = apply_command(
        _project(events),
        events,
        "agent_died",
        {
            "run_id": "run-1",
            "lease_id": "lease-1",
            "execution_id": "exec-1",
            "reason": "process_exit",
            "retry_backoff_seconds": 60,
        },
        clock,
        id_gen,
    )
    retry_not_before = (clock.now() + timedelta(seconds=60)).isoformat()
    projection = _project([*events, *output])

    assert output[2].event_type == "runtime_retry_scheduled"
    assert output[2].payload["retry_after_seconds"] == 60
    assert output[2].payload["retry_not_before"] == retry_not_before
    assert output[3].event_type == "output_record_accepted"
    assert output[3].payload["record_type"] == "recovery_plan"
    assert output[3].payload["value"] == {
        "action": "retry",
        "responsible_actor": "controller",
        "graph_changes": [{"op": "set_node_state", "node_id": "worker-1", "state": "blocked"}],
        "reason": "process_exit",
        "retry_after_seconds": 60,
        "retry_not_before": retry_not_before,
    }
    assert output[4].payload == {
        "node_id": "worker-1",
        "new_state": "blocked",
        "trigger": "agent_died_retry_backoff_scheduled",
        "retry_not_before": retry_not_before,
        "attempt_number": 1,
    }
    assert projection["node_states"]["worker-1"] == "blocked"

    immediate = apply_command(
        projection,
        [*events, *output],
        "schedule_tick",
        {"run_id": "run-1", "base_snapshot_id": "S0"},
        clock,
        id_gen,
    )
    assert [(event.event_type, event.payload) for event in immediate] == [
        (
            "node_deferred",
            {
                "node_id": "worker-1",
                "reason": f"retry_backoff_until:{retry_not_before}",
            },
        )
    ]

    clock.advance(61)
    later = apply_command(
        _project([*events, *output, *immediate]),
        [*events, *output, *immediate],
        "schedule_tick",
        {"run_id": "run-1", "base_snapshot_id": "S0"},
        clock,
        id_gen,
    )
    assert [event.event_type for event in later] == [
        "node_ready",
        "node_state_changed",
        "lease_granted",
        "node_state_changed",
    ]
    assert later[2].payload["node_id"] == "worker-1"
    assert later[3].payload == {
        "node_id": "worker-1",
        "new_state": "leased",
        "trigger": "scheduler_grants_lease",
    }


def test_agent_died_fails_node_when_max_attempts_exhausted() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "running",
                "attempt_number": 2,
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
            "max_attempts": 2,
        },
    )
    projection = _project([*events, *output])

    assert [event.event_type for event in output] == [
        "agent_died",
        "lease_revoked",
        "output_record_accepted",
        "node_state_changed",
    ]
    assert output[2].payload["record_type"] == "failure_record"
    assert output[2].payload["value"] == {
        "failed_node_id": "worker-1",
        "phase": "runtime",
        "error_class": "max_attempts_exhausted",
        "retryable": False,
        "lease_id": "lease-1",
        "execution_id": "exec-1",
        "lease_generation": 1,
        "reason": "process_exit",
        "attempt_number": 2,
        "max_attempts": 2,
    }
    assert output[3].payload == {
        "node_id": "worker-1",
        "new_state": "failed",
        "trigger": "max_attempts_exhausted",
        "reason": "max_attempts_exhausted",
        "attempt_number": 2,
        "max_attempts": 2,
    }
    assert projection["leases"]["lease-1"].state == "revoked"
    assert projection["node_states"]["worker-1"] == "failed"


def test_agent_died_rate_limit_revokes_lease_and_fails_without_retry() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "planner-1", "kind": "planner", "state": "running"}, 1),
        _event(
            "lease_granted",
            {
                "node_id": "planner-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
            },
            2,
        ),
    ]
    reason = "Agent runner 'cli_subprocess' hit rate limit (resets at 14:30)"

    output = _apply(
        events,
        "agent_died",
        {
            "run_id": "run-1",
            "lease_id": "lease-1",
            "execution_id": "exec-1",
            "reason": reason,
        },
    )
    projection = _project([*events, *output])

    assert [event.event_type for event in output] == [
        "agent_died",
        "lease_revoked",
        "output_record_accepted",
        "node_state_changed",
    ]
    assert output[2].payload["record_type"] == "failure_record"
    assert output[2].payload["value"] == {
        "failed_node_id": "planner-1",
        "phase": "runtime",
        "error_class": "agent_rate_limited",
        "retryable": False,
        "lease_id": "lease-1",
        "execution_id": "exec-1",
        "lease_generation": 1,
        "reason": reason,
    }
    assert output[3].payload == {
        "node_id": "planner-1",
        "new_state": "failed",
        "trigger": "agent_rate_limited",
        "reason": reason,
    }
    assert projection["leases"]["lease-1"].state == "revoked"
    assert projection["node_states"]["planner-1"] == "failed"


def test_agent_died_usage_limit_revokes_lease_and_fails_without_retry() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created", {"node_id": "verifier-1", "kind": "verifier", "state": "running"}, 1
        ),
        _event(
            "lease_granted",
            {
                "node_id": "verifier-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
            },
            2,
        ),
    ]
    reason = (
        "Agent runner 'codex_server' execution failed: Codex session ended with status: "
        "failed - You've hit your usage limit for GPT-5.3-Codex-Spark. "
        "Switch to another model now, or try again at 5:25 PM."
    )

    output = _apply(
        events,
        "agent_died",
        {
            "run_id": "run-1",
            "lease_id": "lease-1",
            "execution_id": "exec-1",
            "reason": reason,
        },
    )
    projection = _project([*events, *output])

    assert [event.event_type for event in output] == [
        "agent_died",
        "lease_revoked",
        "output_record_accepted",
        "node_state_changed",
    ]
    assert output[2].payload["value"]["error_class"] == "agent_rate_limited"
    assert output[2].payload["value"]["retryable"] is False
    assert output[3].payload["trigger"] == "agent_rate_limited"
    assert projection["leases"]["lease-1"].state == "revoked"
    assert projection["node_states"]["verifier-1"] == "failed"


def test_agent_died_completes_non_gap_planner_after_accepted_patch() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {"node_id": "planner-1", "kind": "planner", "role": "planner", "state": "running"},
            1,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "planner-1",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
            },
            2,
        ),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-1",
                "successor_planner_node_ids": ["planner-gap"],
            },
            3,
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
        "node_state_changed",
    ]
    assert output[2].payload == {
        "node_id": "planner-1",
        "new_state": "completed",
        "trigger": "accepted_graph_patch_before_agent_death",
    }
    assert projection["node_states"]["planner-1"] == "completed"


def test_agent_died_requeues_gap_planner_after_accepted_patch() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "planner-gap",
                "kind": "planner",
                "role": "gap_planner",
                "state": "running",
            },
            1,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "planner-gap",
                "lease_id": "lease-1",
                "generation": 1,
                "execution_id": "exec-1",
            },
            2,
        ),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-gap",
                "successor_planner_node_ids": [],
            },
            3,
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

    assert [event.event_type for event in output] == [
        "agent_died",
        "lease_revoked",
        "runtime_retry_scheduled",
        "output_record_accepted",
        "node_state_changed",
    ]
    assert output[3].payload["record_type"] == "recovery_plan"
    assert output[4].payload["new_state"] == "ready"


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
        "output_record_accepted",
        "node_state_changed",
    ]
    assert output[0].payload["task_region_id"] == "task-1"
    assert output[1].payload == {
        "record_id": "decision_record-gate-1",
        "record_kind": "output",
        "record_type": "decision_record",
        "producer_node_id": "gate-1",
        "port": "decision_record",
        "schema": "DecisionRecord",
        "value": {
            "decision": "approved",
            "decision_type": "approval",
            "decider": {"kind": "human", "id": "alice"},
        },
    }
    assert output[2].payload["new_state"] == "completed"


def test_record_decision_accepts_authority_request_with_typed_record() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "blocked",
            },
            1,
        ),
    ]

    output = _apply(
        events,
        "record_decision",
        {
            "run_id": "run-1",
            "decision_type": "authority",
            "node_id": "authority-1",
            "decision": "granted",
            "scope": {"tools": ["graph_write"]},
            "expires_at": "2026-01-02T00:00:00+00:00",
            "decider": {"kind": "human", "id": "alice"},
        },
    )

    assert [event.event_type for event in output] == [
        "authority_decision_recorded",
        "output_record_accepted",
        "node_state_changed",
    ]
    assert output[0].payload["decision"] == "granted"
    assert output[1].payload == {
        "record_id": "authority_decision-authority-1",
        "record_kind": "output",
        "record_type": "authority_decision",
        "producer_node_id": "authority-1",
        "port": "authority_decision",
        "schema": "AuthorityDecision",
        "value": {
            "decision": "granted",
            "decision_type": "authority",
            "decider": {"kind": "human", "id": "alice"},
            "scope": {"tools": ["graph_write"]},
            "expires_at": "2026-01-02T00:00:00+00:00",
        },
    }
    assert output[2].payload["new_state"] == "completed"


def test_record_decision_binds_authority_decision_to_worker_input() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "running",
            },
            1,
        ),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"}, 2),
        _event(
            "lease_granted",
            {
                "lease_id": "lease-authority-1",
                "node_id": "authority-1",
                "generation": 1,
            },
            3,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-authority",
                "from_node_id": "authority-1",
                "from_port": "authority_decision",
                "to_node_id": "worker-1",
                "to_port": "authority",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "authority_decision",
                    "schema": "AuthorityDecision",
                },
            },
            4,
        ),
    ]

    output = _apply(
        events,
        "record_decision",
        {
            "run_id": "run-1",
            "decision_type": "authority",
            "node_id": "authority-1",
            "decision": "granted",
            "decider": {"kind": "human", "id": "alice"},
        },
    )

    assert [event.event_type for event in output] == [
        "authority_decision_recorded",
        "output_record_accepted",
        "input_bound",
        "node_state_changed",
        "lease_released",
    ]
    assert output[2].payload == {
        "edge_id": "edge-authority",
        "to_node_id": "worker-1",
        "to_port": "authority",
        "record_ids": ["authority_decision-authority-1"],
        "bound_at_position": 0,
    }
    assert output[4].payload == {
        "node_id": "authority-1",
        "lease_id": "lease-authority-1",
        "generation": 1,
    }


def test_record_decision_rejects_authority_for_non_authority_target() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {
                "node_id": "gate-1",
                "kind": "gate",
                "state": "blocked",
            },
            1,
        ),
    ]

    output = _apply(
        events,
        "record_decision",
        {
            "run_id": "run-1",
            "decision_type": "authority",
            "node_id": "gate-1",
            "decision": "granted",
            "decider": {"kind": "human", "id": "alice"},
        },
    )

    assert [event.event_type for event in output] == ["command_rejected"]
    assert output[0].payload == {
        "command_type": "record_decision",
        "reason": "authority decisions require authority_request target",
    }


def test_record_decision_rejects_missing_target() -> None:
    output = _apply([], "record_decision", {"run_id": "run-1", "decision_type": "approval"})

    assert output[0].event_type == "command_rejected"
    assert "invalid command payload" in output[0].payload["reason"]
    assert "node_id" in output[0].payload["reason"]


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
    assert "decision for approval must be one of" in output[0].payload["reason"]


def test_record_decision_rejects_malformed_typed_authority_record_atomically() -> None:
    output = _apply(
        [
            _event(
                "run_lifecycle_changed",
                {"to_state": "active"},
                0,
            ),
            _event(
                "node_created",
                {"node_id": "authority-1", "kind": "authority_request", "state": "blocked"},
                1,
            ),
        ],
        "record_decision",
        {
            "run_id": "run-1",
            "decision_type": "authority",
            "node_id": "authority-1",
            "decision": "granted",
            "scope": "graph_write",
            "decider": {"kind": "human", "id": "alice"},
        },
    )

    assert [event.event_type for event in output] == ["command_rejected"]
    assert "invalid command payload" in output[0].payload["reason"]
    assert "scope" in output[0].payload["reason"]


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
    assert "invalid command payload" in output[0].payload["reason"]
    assert "decider" in output[0].payload["reason"]


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


def test_submit_patch_accepts_edge_between_revision_attempt_embedded_nodes() -> None:
    output = _apply(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "revision-edge",
            "proposed_by_node_id": "gap-planner-1",
            "actor_role": "gap_planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_revision_attempt",
                    "task_region_id": "task-1",
                    "failed_candidate_id": "cand-1",
                    "worker_node": {
                        "node_id": "worker-revision-2",
                        "state": "planned",
                    },
                    "verifier_node": {
                        "node_id": "verifier-revision-2",
                        "state": "planned",
                    },
                },
                {
                    "op": "create_edge",
                    "edge_id": "edge-revision-candidate",
                    "from_node_id": "worker-revision-2",
                    "from_port": "candidate",
                    "to_node_id": "verifier-revision-2",
                    "to_port": "candidate_under_test",
                    "required": True,
                },
            ],
        },
    )

    assert [event.event_type for event in output] == [
        "graph_patch_accepted",
        "revision_created",
        "node_created",
        "node_created",
        "edge_created",
    ]
    assert output[2].payload["kind"] == "worker"
    assert output[3].payload["kind"] == "verifier"
    assert output[4].payload["from_node_id"] == "worker-revision-2"
    assert output[4].payload["to_node_id"] == "verifier-revision-2"


def test_callback_binds_required_input_by_wildcard_producer_class_edge() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event(
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "state": "completed"},
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "task_region_id": "task-1",
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-replacement",
                "kind": "verifier",
                "role": "verifier",
                "state": "running",
            },
            3,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-candidate-replacement",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "verifier-replacement",
                "to_port": "candidate_under_test",
                "required": True,
            },
            4,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-candidate-replacement",
                "to_node_id": "verifier-replacement",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            5,
        ),
        _event("node_created", {"node_id": "check-final", "kind": "check", "state": "blocked"}, 6),
        _event(
            "edge_created",
            {
                "edge_id": "edge-verification-evidence",
                "from_node_id": "*",
                "from_node_kind": "verifier",
                "from_node_role": "verifier",
                "from_port": "verification_report",
                "to_node_id": "check-final",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                },
            },
            7,
        ),
        _event(
            "lease_granted",
            {
                "node_id": "verifier-replacement",
                "lease_id": "lease-replacement",
                "generation": 1,
                "execution_id": "exec-replacement",
                "base_snapshot_id": "S0",
            },
            8,
        ),
    ]

    output = _apply(
        events,
        "submit_callback",
        _callback_payload(
            node_id="verifier-replacement",
            execution_id="exec-replacement",
            lease_id="lease-replacement",
            base_snapshot_id="S0",
            payload_hash="hash-replacement",
            idempotency_key="key-replacement",
            payload={
                "payload_hash": "hash-replacement",
                "output_records": [
                    {
                        "record_id": "verification-replacement",
                        "record_kind": "verification",
                        "record_type": "verification_report",
                        "producer_node_id": "verifier-replacement",
                        "port": "verification_report",
                        "schema": "VerificationReport",
                        "candidate_id": "candidate-1",
                        "outcome": "passed",
                        "value": {
                            "outcome": "passed",
                            "grades": [{"requirement_id": "R-01", "grade": "pass"}],
                        },
                    }
                ],
            },
        ),
    )

    assert any(
        event.event_type == "input_bound"
        and event.payload["edge_id"] == "edge-verification-evidence"
        and event.payload["to_node_id"] == "check-final"
        and event.payload["record_ids"] == ["verification-replacement"]
        for event in output
    ), [(event.event_type, event.payload.get("reason")) for event in output]


def test_schedule_tick_marks_dead_required_input_when_required_source_failed_unbound() -> None:
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "producer-1", "kind": "worker", "state": "failed"}, 1),
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
        (
            "node_deferred",
            {"node_id": "worker-1", "reason": "dead_required_input:candidate:producer-1"},
        )
    ]
