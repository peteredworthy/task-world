"""Canonical graph-event behavior fixtures shared by projection tests."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeAlias

from orchestrator.graph import (
    Actor,
    ActorKind,
    EVENT_PAYLOAD_MODELS,
    EventEnvelope,
    GraphProjection,
    accepted_graph_patch_ids,
    accepted_graph_patches_by_node_view,
    active_requirement_version,
    approval_decision,
    approval_decisions_view,
    authority_decision,
    authority_decisions_view,
    bound_record_ids,
    callback_idempotency_events_view,
    callback_idempotency_event,
    cleanup_applied,
    cleanup_request,
    cleanup_requested_events_view,
    edge_by_id,
    edges_view,
    failed_verification_candidate_ids,
    failed_verification_result,
    file_state_record,
    file_state_records_view,
    input_bindings_view,
    initial_projection,
    lease_by_id,
    leases_view,
    node_allowed_actions,
    node_creation_payloads_view,
    node_creation_position,
    node_exists,
    node_gate_decision,
    node_last_deferred_reason,
    node_pending_appeals_view,
    node_preconditions,
    node_retry_not_before,
    node_resource_claims_view,
    node_state,
    node_states_view,
    node_usage_recorded,
    output_record_payload,
    output_records_by_node_port_view,
    oversight_decision,
    passed_verification_candidate_ids,
    passed_verification_result,
    planner_session_state,
    planner_sessions_view,
    projection_to_checkpoint,
    ready_nodes_view,
    reduce_event,
    requirement_revision,
    requirement_revisions_view,
    run_state,
    support_evidence,
    support_evidence_view,
    task_state,
    tokens_by_node_view,
    verifier_verdict,
    verifier_verdicts_view,
)
from tests.unit.graph_test_utils import canonical_event_payload

ProjectionPath: TypeAlias = tuple[str, ...]
OutcomeAssertion: TypeAlias = Callable[[GraphProjection, GraphProjection], None]
QueryProbe: TypeAlias = Callable[[GraphProjection], object]
MutationProbe: TypeAlias = Callable[[object], None]


@dataclass(frozen=True)
class ProjectionBehaviorCase:
    event_type: str
    prefix: tuple[EventEnvelope, ...]
    event: EventEnvelope
    changed_groups: frozenset[str]
    replaced_paths: tuple[ProjectionPath, ...]
    shared_paths: tuple[ProjectionPath, ...]
    assert_outcome: OutcomeAssertion
    query: QueryProbe
    mutate_query_result: MutationProbe | None = None

    @property
    def stream(self) -> tuple[EventEnvelope, ...]:
        return (*self.prefix, self.event)


def event(event_type: str, payload: dict[str, object], position: int) -> EventEnvelope:
    canonical = (
        EVENT_PAYLOAD_MODELS[event_type]
        .model_validate(payload)
        .model_dump(mode="json", by_alias=True)
    )
    return EventEnvelope(
        event_id=f"matrix-{event_type}-{position}",
        run_id="matrix-run",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical,
    )


def fold_events(
    events: tuple[EventEnvelope, ...], projection: GraphProjection | None = None
) -> GraphProjection:
    current = projection if projection is not None else initial_projection()
    for item in events:
        current = reduce_event(current, item)
    return current


def case_projection(case: ProjectionBehaviorCase) -> tuple[GraphProjection, GraphProjection]:
    before = fold_events(case.prefix)
    return before, reduce_event(before, case.event)


def _event(event_type: str, payload: dict[str, object], position: int) -> EventEnvelope:
    return event(event_type, canonical_event_payload(event_type, payload), position)


def _unchanged(before: GraphProjection, after: GraphProjection) -> None:
    assert projection_to_checkpoint(after) == projection_to_checkpoint(before)


def _assert_event_outcome(event_type: str, before: GraphProjection, after: GraphProjection) -> None:
    """Assert the externally observable domain fact owned by one event type."""
    if event_type == "run_lifecycle_changed":
        assert run_state(after) == "active"
    elif event_type == "node_created":
        assert node_exists(after, "worker-1")
        assert node_creation_position(after, "worker-1") == 1
    elif event_type == "node_state_changed":
        assert node_state(after, "worker-1") == "ready"
        assert "worker-1" in ready_nodes_view(after)
    elif event_type == "node_retired":
        assert node_state(before, "worker-1") == "running"
        assert node_state(after, "worker-1") == "retired"
    elif event_type == "node_deferred":
        assert node_last_deferred_reason(after, "worker-1") == "waiting"
    elif event_type == "node_ready":
        assert node_last_deferred_reason(after, "worker-1") is None
        assert node_state(after, "worker-1") == "planned"
    elif event_type == "runtime_retry_scheduled":
        assert node_retry_not_before(after, "worker-1") == "2026-01-01T00:01:00+00:00"
    elif event_type == "plan_region_marked_suspect":
        checkpoint = projection_to_checkpoint(after)
        assert checkpoint["nodes"]["worker-1"]["runtime"]["suspect_reason"] == "requirement_changed"
    elif event_type == "node_authority_changed":
        assert node_allowed_actions(after, "worker-1") == ("write",)
        assert node_resource_claims_view(after)["worker-1"] == []
        assert node_preconditions(after, "worker-1") == ("approved",)
    elif event_type == "edge_created":
        edge = edge_by_id(after, "edge-1")
        assert edge is not None
        assert (edge.from_node_id, edge.from_port, edge.to_node_id, edge.to_port) == (
            "source-1",
            "candidate",
            "target-1",
            "candidate",
        )
    elif event_type == "input_bound":
        assert bound_record_ids(after, "target-1", "candidate") == ("candidate-1",)
    elif event_type == "output_record_accepted":
        record = output_record_payload(after, "record-1")
        assert record is not None
        assert record.record_type == "fan_out_inputs"
        assert record.producer_node_id == "worker-1"
        assert record.port == "fan_out_inputs"
        indexed = output_records_by_node_port_view(after)
        assert set(indexed) == {"worker-1"}
        assert set(indexed["worker-1"]) == {"fan_out_inputs"}
        assert [item.record_id for item in indexed["worker-1"]["fan_out_inputs"]] == ["record-1"]
    elif event_type == "file_state_accepted":
        record = file_state_record(after, "file-state-1")
        assert record is not None
        assert record.snapshot_id == "snapshot-1"
    elif event_type == "gatekeeper_verdict_recorded":
        record = file_state_record(after, "file-state-1")
        assert record is not None
        assert record.untracked[0].classification == "source"
    elif event_type == "session_state_changed":
        assert planner_session_state(after, "session-1") == "detached"
    elif event_type == "graph_patch_accepted":
        assert accepted_graph_patch_ids(after, "planner-1") == ("patch-1",)
        assert (
            projection_to_checkpoint(after)["governance"]["resolved_patch_ids"]["patch-1"] is True
        )
    elif event_type == "verification_passed":
        assert verifier_verdict(after, "candidate-1").verdict == "passed"
        assert passed_verification_result(after, "verification-1") is not None
        assert passed_verification_candidate_ids(after) == ("candidate-1",)
        assert task_state(after, "task-1") == "accepted"
    elif event_type == "verification_failed":
        assert verifier_verdict(after, "candidate-1").verdict == "failed"
        assert failed_verification_result(after, "verification-1") is not None
        assert failed_verification_candidate_ids(after) == ("candidate-1",)
        assert task_state(after, "task-1") == "needs_revision"
    elif event_type == "appeal_opened":
        assert node_pending_appeals_view(after)["worker-1"] is True
    elif event_type == "approval_decision_recorded":
        assert approval_decision(after, "gate-1").decision == "approved"
        assert node_gate_decision(after, "gate-1") is True
    elif event_type == "authority_decision_recorded":
        assert authority_decision(after, "authority-1").decision == "granted"
    elif event_type == "oversight_decision_recorded":
        decision = oversight_decision(after, "oversight-1")
        assert decision is not None
        assert (decision.decision, decision.position) == ("accepted", 2)
    elif event_type == "requirement_revision_recorded":
        assert requirement_revision(after, "version-1") is not None
        assert active_requirement_version(after, "requirement-1") == "version-1"
    elif event_type == "support_evidence_recorded":
        support = support_evidence(after, "support-1")
        assert support is not None
        assert (support.evidence_id, support.requirement_id, support.requirement_version_id) == (
            "evidence-1",
            "requirement-1",
            "version-1",
        )
    elif event_type == "node_usage_recorded":
        assert node_usage_recorded(after, "execution-1:0") is True
        assert tokens_by_node_view(after)["worker-1"] == 5
    elif event_type == "lease_granted":
        lease = lease_by_id(after, "lease-1")
        assert lease is not None
        assert lease.state == "active"
        assert tuple(leases_view(after)) == ("lease-1",)
    elif event_type == "lease_renewed":
        lease = lease_by_id(after, "lease-1")
        assert lease is not None
        assert (lease.expires_at, lease.state) == ("2026-01-01T00:10:00+00:00", "active")
    elif event_type in {"lease_suspended", "lease_revoked", "lease_expired", "lease_released"}:
        lease = lease_by_id(after, "lease-1")
        assert lease is not None
        assert lease.state == event_type.removeprefix("lease_")
    elif event_type == "cleanup_requested":
        cleanup = cleanup_request(after, "cleanup-1")
        assert cleanup is not None
        assert (tuple(cleanup.paths), cleanup.file_state_record_id) == (
            ("src/app.py",),
            "file-state-1",
        )
    elif event_type == "cleanup_applied":
        assert cleanup_applied(after, "cleanup-1") is True
    elif event_type == "callback_accepted":
        callback = callback_idempotency_event(after, "callback-1")
        assert callback is not None
        assert (callback.outcome, callback.payload) == ("callback_accepted", {"result": "ok"})
    else:
        raise AssertionError(f"missing direct outcome assertion for {event_type}")


def _assert_outcome(event_type: str) -> OutcomeAssertion:
    return lambda before, after: _assert_event_outcome(event_type, before, after)


def _mutate_nested_mapping(result: object) -> None:
    """Exercise a nested fresh public container without reaching projection storage."""
    assert isinstance(result, dict)
    result["__matrix_probe__"] = {"items": []}
    result["__matrix_probe__"]["items"].append("mutated")


_NEUTRAL_QUERIES: dict[str, QueryProbe] = {
    "agent_died": lambda state: lease_by_id(state, "lease-1"),
    "agent_dispatch_requested": lambda state: lease_by_id(state, "lease-1"),
    "callback_duplicate_returned": lambda state: callback_idempotency_event(state, "callback-1"),
    "callback_rejected_conflict": lambda state: callback_idempotency_event(state, "callback-1"),
    "callback_rejected_stale": lambda state: callback_idempotency_event(state, "callback-1"),
    "command_recorded": lambda state: run_state(state),
    "command_rejected": lambda state: run_state(state),
    "dead_input_detected": lambda state: bound_record_ids(state, "worker-1", "input"),
    "file_state_rejected": lambda state: file_state_record(state, "rejected-file-state"),
    "gatekeeper_cost_recorded": lambda state: file_state_record(state, "file-state-1"),
    "graph_patch_rejected": lambda state: accepted_graph_patch_ids(state, "planner-1"),
    "heartbeat_recorded": lambda state: lease_by_id(state, "lease-1"),
    "outbox_requeued": lambda state: run_state(state),
    "revision_created": lambda state: node_creation_payloads_view(state),
}


_CHANGING_QUERIES: dict[str, QueryProbe] = {
    "run_lifecycle_changed": lambda state: run_state(state),
    "node_created": lambda state: node_creation_payloads_view(state),
    "node_state_changed": lambda state: node_creation_payloads_view(state),
    "node_retired": lambda state: node_states_view(state),
    "node_deferred": lambda state: node_last_deferred_reason(state, "worker-1"),
    "node_ready": lambda state: node_last_deferred_reason(state, "worker-1"),
    "runtime_retry_scheduled": lambda state: node_retry_not_before(state, "worker-1"),
    "plan_region_marked_suspect": lambda state: node_creation_payloads_view(state),
    "node_authority_changed": lambda state: node_creation_payloads_view(state),
    "edge_created": lambda state: edges_view(state),
    "input_bound": lambda state: input_bindings_view(state),
    "output_record_accepted": lambda state: output_records_by_node_port_view(state),
    "file_state_accepted": lambda state: file_state_records_view(state),
    "gatekeeper_verdict_recorded": lambda state: file_state_records_view(state),
    "session_state_changed": lambda state: planner_sessions_view(state),
    "graph_patch_accepted": lambda state: accepted_graph_patches_by_node_view(state),
    "verification_passed": lambda state: verifier_verdicts_view(state),
    "verification_failed": lambda state: verifier_verdicts_view(state),
    "appeal_opened": lambda state: node_pending_appeals_view(state),
    "approval_decision_recorded": lambda state: approval_decisions_view(state),
    "authority_decision_recorded": lambda state: authority_decisions_view(state),
    "oversight_decision_recorded": lambda state: oversight_decision(state, "oversight-1"),
    "requirement_revision_recorded": lambda state: requirement_revisions_view(state),
    "support_evidence_recorded": lambda state: support_evidence_view(state),
    "node_usage_recorded": lambda state: tokens_by_node_view(state),
    "lease_granted": lambda state: leases_view(state),
    "lease_renewed": lambda state: leases_view(state),
    "lease_suspended": lambda state: leases_view(state),
    "lease_revoked": lambda state: leases_view(state),
    "lease_expired": lambda state: leases_view(state),
    "lease_released": lambda state: leases_view(state),
    "cleanup_requested": lambda state: cleanup_requested_events_view(state),
    "cleanup_applied": lambda state: cleanup_applied(state, "cleanup-1"),
    "callback_accepted": lambda state: callback_idempotency_events_view(state),
}


_MUTABLE_QUERY_EVENTS = frozenset(
    {
        "node_created",
        "node_state_changed",
        "node_retired",
        "plan_region_marked_suspect",
        "node_authority_changed",
        "edge_created",
        "input_bound",
        "output_record_accepted",
        "file_state_accepted",
        "gatekeeper_verdict_recorded",
        "session_state_changed",
        "graph_patch_accepted",
        "verification_passed",
        "verification_failed",
        "appeal_opened",
        "approval_decision_recorded",
        "authority_decision_recorded",
        "requirement_revision_recorded",
        "support_evidence_recorded",
        "node_usage_recorded",
        "lease_granted",
        "lease_renewed",
        "lease_suspended",
        "lease_revoked",
        "lease_expired",
        "lease_released",
        "cleanup_requested",
        "callback_accepted",
    }
)


_REPLACED_PATHS: dict[str, tuple[ProjectionPath, ...]] = {
    "run_lifecycle_changed": (("lifecycle",),),
    "node_state_changed": (("nodes", "worker-1"),),
    "node_retired": (("nodes", "worker-1"),),
    "node_deferred": (("nodes", "worker-1"),),
    "node_ready": (("nodes", "worker-1"),),
    "runtime_retry_scheduled": (("nodes", "worker-1"),),
    "plan_region_marked_suspect": (("nodes", "worker-1"),),
    "node_authority_changed": (("nodes", "worker-1"),),
    "gatekeeper_verdict_recorded": (("records", "by_id", "file-state-1"),),
    "verification_passed": (("tasks", "task-1"),),
    "verification_failed": (("tasks", "task-1"),),
    "lease_renewed": (("execution", "leases", "lease-1"),),
    "lease_suspended": (("execution", "leases", "lease-1"),),
    "lease_revoked": (("execution", "leases", "lease-1"),),
    "lease_expired": (("execution", "leases", "lease-1"),),
    "lease_released": (("execution", "leases", "lease-1"),),
}


_SHARED_PATHS: dict[str, tuple[ProjectionPath, ...]] = {
    "node_state_changed": (("nodes", "sibling-1"),),
    "node_retired": (("nodes", "sibling-1"),),
    "node_deferred": (("nodes", "sibling-1"),),
    "node_ready": (("nodes", "sibling-1"),),
    "runtime_retry_scheduled": (("nodes", "sibling-1"),),
    "plan_region_marked_suspect": (("nodes", "sibling-1"),),
    "node_authority_changed": (("nodes", "sibling-1"),),
    "edge_created": (("nodes", "source-1"),),
    "input_bound": (("nodes", "source-1"),),
    "output_record_accepted": (("nodes", "worker-1"),),
    "file_state_accepted": (("nodes", "worker-1"),),
    "gatekeeper_verdict_recorded": (("nodes", "worker-1"),),
    "graph_patch_accepted": (("nodes", "planner-1"),),
    "verification_passed": (("nodes", "worker-1"),),
    "verification_failed": (("nodes", "worker-1"),),
    "appeal_opened": (("nodes", "worker-1"),),
    "approval_decision_recorded": (("nodes", "gate-1"),),
    "authority_decision_recorded": (("nodes", "authority-1"),),
    "oversight_decision_recorded": (("nodes", "oversight-1"),),
    "support_evidence_recorded": (("nodes", "worker-1"),),
    "node_usage_recorded": (("nodes", "worker-1"),),
    "lease_granted": (("nodes", "worker-1"),),
    "lease_renewed": (("nodes", "worker-1"),),
    "lease_suspended": (("nodes", "worker-1"),),
    "lease_revoked": (("nodes", "worker-1"),),
    "lease_expired": (("nodes", "worker-1"),),
    "lease_released": (("nodes", "worker-1"),),
    "cleanup_requested": (("nodes", "worker-1"),),
    "cleanup_applied": (("nodes", "worker-1"),),
    "callback_accepted": (("nodes", "worker-1"),),
}


NEUTRAL_PAYLOADS: dict[str, dict[str, object]] = {
    "agent_died": {"lease_id": "lease-1", "node_id": "worker-1", "reason": "agent_exit"},
    "agent_dispatch_requested": {
        "lease_granted_event_id": "lease-granted-1",
        "lease_id": "lease-1",
        "node_id": "worker-1",
        "generation": 1,
        "execution_id": "execution-1",
        "base_snapshot_id": "snapshot-1",
        "resource_claims": [],
    },
    "callback_duplicate_returned": {
        "node_id": "worker-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "execution_id": "execution-1",
        "idempotency_key": "callback-1",
        "payload": None,
        "reason": "duplicate",
        "prior_result": None,
    },
    "callback_rejected_conflict": {
        "node_id": "worker-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "execution_id": "execution-1",
        "idempotency_key": "callback-1",
        "payload": None,
        "reason": "conflict",
    },
    "callback_rejected_stale": {
        "node_id": "worker-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "execution_id": "execution-1",
        "idempotency_key": "callback-1",
        "payload": None,
        "reason": "stale",
    },
    "command_recorded": {"command_type": "start", "command_payload": {}},
    "command_rejected": {"command_type": "start", "reason": "invalid"},
    "dead_input_detected": {
        "node_id": "worker-1",
        "from_node_id": "source-1",
        "to_port": "input",
        "reason": "upstream_failed",
    },
    "file_state_rejected": {
        "record_id": "rejected-file-state",
        "record_type": "file_state",
        "record_kind": "file_state",
        "producer_node_id": "worker-1",
        "port": "file_state",
        "schema": "FileStateRecord",
        "reason": "residue",
    },
    "gatekeeper_cost_recorded": {
        "execution_id": "execution-1",
        "file_state_record_id": "file-state-1",
        "consult_id": "consult-1",
    },
    "graph_patch_rejected": {"patch_id": "patch-1", "reason": "invalid"},
    "heartbeat_recorded": {
        "lease_id": "lease-1",
        "node_id": "worker-1",
        "observed_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-01T00:05:00+00:00",
    },
    "outbox_requeued": {
        "run_id": "matrix-run",
        "outbox_id": 1,
        "event_id": "event-1",
        "kind": "callback",
        "previous_status": "failed",
        "previous_attempts": 1,
        "previous_last_error": "transient",
        "operator": "operator-1",
        "graph_position": 1,
    },
    "revision_created": {
        "node": {"node_id": "revision-1", "kind": "worker"},
        "worker_node": {"node_id": "worker-1", "kind": "worker"},
        "verifier_node": {"node_id": "verifier-1", "kind": "verifier"},
    },
}


def behavior_cases() -> tuple[ProjectionBehaviorCase, ...]:
    """Return one independently executable row for every canonical event type."""
    neutral = tuple(
        ProjectionBehaviorCase(
            name,
            (),
            event(name, payload, 1),
            frozenset(),
            (),
            (),
            _unchanged,
            _NEUTRAL_QUERIES[name],
            _mutate_nested_mapping if name == "revision_created" else None,
        )
        for name, payload in NEUTRAL_PAYLOADS.items()
    )
    # The state-changing rows deliberately use the canonical fixture boundary too:
    # a malformed payload can never be hidden by the matrix construction itself.
    worker = _event(
        "node_created",
        {"node_id": "worker-1", "kind": "worker", "state": "planned", "task_region_id": "task-1"},
        0,
    )
    running_worker = _event(
        "node_created",
        {"node_id": "worker-1", "kind": "worker", "state": "running", "task_region_id": "task-1"},
        0,
    )
    sibling = _event(
        "node_created", {"node_id": "sibling-1", "kind": "worker", "state": "planned"}, 1
    )
    planner = _event(
        "node_created",
        {"node_id": "planner-1", "kind": "planner", "role": "planner", "state": "planned"},
        0,
    )
    patch_proposal = _event(
        "output_record_accepted",
        {
            "record_id": "patch-proposal-1",
            "record_kind": "output",
            "record_type": "graph_patch_proposal",
            "producer_node_id": "planner-1",
            "port": "graph_patch_proposal",
            "schema": "GraphPatch",
            "value": {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-1",
                "base_graph_position": 0,
                "ops": [{"op": "add", "path": "/nodes/worker-2", "value": {}}],
            },
        },
        1,
    )
    gate = _event("node_created", {"node_id": "gate-1", "kind": "gate", "state": "planned"}, 0)
    authority = _event(
        "node_created", {"node_id": "authority-1", "kind": "gate", "state": "planned"}, 0
    )
    oversight = _event(
        "node_created", {"node_id": "oversight-1", "kind": "gate", "state": "planned"}, 0
    )
    source = _event(
        "node_created", {"node_id": "source-1", "kind": "worker", "state": "completed"}, 0
    )
    target = _event(
        "node_created", {"node_id": "target-1", "kind": "worker", "state": "planned"}, 1
    )
    edge = _event(
        "edge_created",
        {
            "edge_id": "edge-1",
            "from_node_id": "source-1",
            "from_port": "candidate",
            "to_node_id": "target-1",
            "to_port": "candidate",
        },
        2,
    )
    candidate = _event(
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
            "file_state_record_ids": ["file-state-1"],
            "value": {"summary": "candidate"},
        },
        1,
    )
    file_state = _event(
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
            "untracked": [{"path": "src/app.py", "status": "modified"}],
            "verdict": "captured",
        },
        1,
    )
    evidence = _event(
        "output_record_accepted",
        {
            "record_id": "evidence-1",
            "record_kind": "output",
            "record_type": "fan_out_inputs",
            "producer_node_id": "worker-1",
            "port": "fan_out_inputs",
            "schema": "FanOutInputs",
            "value": {},
        },
        1,
    )
    granted = _event(
        "lease_granted",
        {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 1,
            "execution_id": "execution-1",
            "expires_at": "2026-01-01T00:05:00+00:00",
        },
        1,
    )
    verifier = _event(
        "node_created",
        {
            "node_id": "verifier-1",
            "kind": "verifier",
            "state": "planned",
            "task_region_id": "task-1",
        },
        2,
    )
    passed_verification = _event(
        "output_record_accepted",
        {
            "record_id": "verification-1",
            "record_kind": "verification",
            "candidate_id": "candidate-1",
            "producer_node_id": "verifier-1",
            "outcome": "passed",
            "value": {"outcome": "passed", "grades": []},
        },
        3,
    )
    failed_verification = _event(
        "output_record_accepted",
        {
            "record_id": "verification-1",
            "record_kind": "verification",
            "candidate_id": "candidate-1",
            "producer_node_id": "verifier-1",
            "outcome": "failed",
            "value": {"outcome": "failed", "grades": []},
        },
        3,
    )
    requirement_revision = _event(
        "requirement_revision_recorded",
        {"requirement_id": "requirement-1", "version_id": "version-1"},
        2,
    )
    cleanup_requested = _event(
        "cleanup_requested",
        {
            "cleanup_id": "cleanup-1",
            "file_state_record_id": "file-state-1",
            "paths": ["src/app.py"],
            "reason": "residue",
        },
        2,
    )
    changing_payloads: tuple[
        tuple[str, tuple[EventEnvelope, ...], dict[str, object], frozenset[str]], ...
    ] = (
        ("run_lifecycle_changed", (), {"to_state": "active"}, frozenset({"lifecycle"})),
        (
            "node_created",
            (),
            {"node_id": "worker-1", "kind": "worker", "state": "planned"},
            frozenset({"nodes"}),
        ),
        (
            "node_state_changed",
            (worker, sibling),
            {"node_id": "worker-1", "new_state": "ready"},
            frozenset({"nodes", "scheduling"}),
        ),
        (
            "node_retired",
            (running_worker, sibling),
            {"node_id": "worker-1"},
            frozenset({"nodes", "tasks"}),
        ),
        (
            "node_deferred",
            (worker, sibling),
            {"node_id": "worker-1", "reason": "waiting"},
            frozenset({"nodes"}),
        ),
        (
            "node_ready",
            (
                worker,
                sibling,
                _event("node_deferred", {"node_id": "worker-1", "reason": "waiting"}, 2),
            ),
            {"node_id": "worker-1"},
            frozenset({"nodes"}),
        ),
        (
            "runtime_retry_scheduled",
            (worker, sibling),
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "generation": 1,
                "policy": "v1_requeue_same_node_after_agent_death",
                "reason": "agent_exit",
                "retry_not_before": "2026-01-01T00:01:00+00:00",
            },
            frozenset({"nodes"}),
        ),
        (
            "plan_region_marked_suspect",
            (worker, sibling),
            {"node_id": "worker-1", "reason": "requirement_changed"},
            frozenset({"nodes"}),
        ),
        (
            "node_authority_changed",
            (worker, sibling),
            {
                "node_id": "worker-1",
                "allowed_actions": ["write"],
                "resource_claims": [],
                "preconditions": ["approved"],
            },
            frozenset({"nodes"}),
        ),
        (
            "edge_created",
            (source, target),
            {
                "edge_id": "edge-1",
                "from_node_id": "source-1",
                "from_port": "candidate",
                "to_node_id": "target-1",
                "to_port": "candidate",
            },
            frozenset({"topology"}),
        ),
        (
            "input_bound",
            (worker, source, target, file_state, candidate, edge),
            {
                "edge_id": "edge-1",
                "to_node_id": "target-1",
                "to_port": "candidate",
                "record_ids": ["candidate-1"],
                "bound_at_position": 4,
            },
            frozenset({"topology"}),
        ),
        (
            "output_record_accepted",
            (worker,),
            {
                "record_id": "record-1",
                "record_kind": "output",
                "record_type": "fan_out_inputs",
                "producer_node_id": "worker-1",
                "port": "fan_out_inputs",
                "schema": "FanOutInputs",
                "value": {},
            },
            frozenset({"records", "tasks"}),
        ),
        (
            "file_state_accepted",
            (worker,),
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "record_type": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "snapshot_id": "snapshot-1",
                "base_snapshot_id": "snapshot-0",
                "untracked": [{"path": "src/app.py", "status": "modified"}],
                "verdict": "captured",
            },
            frozenset({"records"}),
        ),
        (
            "gatekeeper_verdict_recorded",
            (worker, file_state),
            {
                "file_state_record_id": "file-state-1",
                "execution_id": "execution-1",
                "producer_node_id": "worker-1",
                "verdicts": [
                    {
                        "path": "src/app.py",
                        "classification": "source",
                        "confidence": 1.0,
                        "rationale": "canonical",
                    }
                ],
                "resolved_count": 1,
            },
            frozenset({"records"}),
        ),
        (
            "session_state_changed",
            (),
            {"session_id": "session-1", "state": "detached"},
            frozenset({"planning"}),
        ),
        (
            "graph_patch_accepted",
            (planner, patch_proposal),
            {"patch_id": "patch-1", "proposed_by_node_id": "planner-1"},
            frozenset({"planning", "governance"}),
        ),
        (
            "verification_passed",
            (worker, file_state, candidate, verifier, passed_verification),
            {
                "node_id": "verifier-1",
                "verifier_node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "record_id": "verification-1",
                "outcome": "passed",
                "value": {"outcome": "passed", "grades": []},
                "task_region_id": "task-1",
            },
            frozenset({"verification", "tasks"}),
        ),
        (
            "verification_failed",
            (worker, file_state, candidate, verifier, failed_verification),
            {
                "node_id": "verifier-1",
                "verifier_node_id": "verifier-1",
                "candidate_id": "candidate-1",
                "record_id": "verification-1",
                "outcome": "failed",
                "value": {"outcome": "failed", "grades": []},
                "task_region_id": "task-1",
            },
            frozenset({"verification", "tasks"}),
        ),
        (
            "appeal_opened",
            (worker,),
            {"node_id": "appeal-1", "appealed_node_id": "worker-1", "appeal_type": "other"},
            frozenset({"governance"}),
        ),
        (
            "approval_decision_recorded",
            (gate,),
            {
                "decision_type": "approval",
                "node_id": "gate-1",
                "decider": "controller",
                "decision": "approved",
            },
            frozenset({"governance"}),
        ),
        (
            "authority_decision_recorded",
            (authority,),
            {
                "decision_type": "authority",
                "node_id": "authority-1",
                "decider": "controller",
                "decision": "granted",
            },
            frozenset({"governance"}),
        ),
        (
            "oversight_decision_recorded",
            (oversight,),
            {
                "decision_type": "oversight",
                "node_id": "oversight-1",
                "decider": "controller",
                "decision": "accepted",
            },
            frozenset({"governance"}),
        ),
        (
            "requirement_revision_recorded",
            (),
            {"requirement_id": "requirement-1", "version_id": "version-1"},
            frozenset({"requirements"}),
        ),
        (
            "support_evidence_recorded",
            (worker, evidence, requirement_revision),
            {
                "support_id": "support-1",
                "evidence_id": "evidence-1",
                "requirement_id": "requirement-1",
                "version_id": "version-1",
            },
            frozenset({"requirements"}),
        ),
        (
            "node_usage_recorded",
            (worker,),
            {
                "node_id": "worker-1",
                "node_kind": "worker",
                "execution_id": "execution-1",
                "usage_index": 0,
                "usage_count": 1,
                "usage_key": "execution-1:0",
                "model": "test",
                "gen_ai_usage_input_tokens": 2,
                "gen_ai_usage_output_tokens": 3,
            },
            frozenset({"usage"}),
        ),
        (
            "lease_granted",
            (worker,),
            {
                "lease_id": "lease-1",
                "node_id": "worker-1",
                "generation": 1,
                "execution_id": "execution-1",
                "expires_at": "2026-01-01T00:05:00+00:00",
            },
            frozenset({"execution", "tasks"}),
        ),
        (
            "lease_renewed",
            (worker, granted),
            {"lease_id": "lease-1", "expires_at": "2026-01-01T00:10:00+00:00"},
            frozenset({"execution"}),
        ),
        *(
            (name, (worker, granted), {"lease_id": "lease-1"}, frozenset({"execution", "tasks"}))
            for name in ("lease_suspended", "lease_revoked", "lease_expired", "lease_released")
        ),
        (
            "cleanup_requested",
            (worker, file_state),
            {
                "cleanup_id": "cleanup-1",
                "file_state_record_id": "file-state-1",
                "paths": ["src/app.py"],
                "reason": "residue",
            },
            frozenset({"execution", "records"}),
        ),
        (
            "cleanup_applied",
            (worker, file_state, cleanup_requested),
            {"cleanup_id": "cleanup-1", "file_state_record_id": "file-state-1"},
            frozenset({"execution", "records"}),
        ),
        (
            "callback_accepted",
            (worker,),
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "execution_id": "execution-1",
                "idempotency_key": "callback-1",
                "payload": {"result": "ok"},
                "reason": "accepted",
            },
            frozenset({"execution"}),
        ),
    )
    changing = tuple(
        ProjectionBehaviorCase(
            name,
            prefix,
            _event(name, payload, len(prefix) + 1),
            groups,
            _REPLACED_PATHS.get(name, ()),
            _SHARED_PATHS.get(name, ()),
            _assert_outcome(name),
            _CHANGING_QUERIES[name],
            _mutate_nested_mapping if name in _MUTABLE_QUERY_EVENTS else None,
        )
        for name, prefix, payload, groups in changing_payloads
    )
    return (*neutral, *changing)


def replay_streams() -> tuple[tuple[str, tuple[EventEnvelope, ...]], ...]:
    """Return the canonical replay streams derived solely from matrix cases."""
    return tuple((case.event_type, case.stream) for case in behavior_cases())
