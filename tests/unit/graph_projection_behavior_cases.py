"""Canonical graph-event behavior fixtures shared by projection tests."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeAlias

from pydantic import BaseModel

from orchestrator.graph import (
    Actor,
    ActorKind,
    EVENT_PAYLOAD_MODELS,
    EventEnvelope,
    GraphProjection,
    active_requirement_versions_view,
    callback_idempotency_events_view,
    cleanup_applied_ids_view,
    cleanup_requested_events_view,
    edges_view,
    failed_verification_candidate_ids_view,
    failed_verification_results_by_record_id_view,
    file_state_records_view,
    input_bindings_view,
    initial_projection,
    lease_by_id,
    leases_view,
    node_pending_appeals_view,
    node_creation_positions_view,
    node_resource_claims_view,
    node_states_view,
    output_records_by_node_port_view,
    output_record_payloads_view,
    planner_patch_facts_view,
    projection_to_checkpoint,
    ready_nodes_view,
    retry_not_before_by_node_view,
    reduce_event,
    run_state,
    passed_verification_results_by_record_id_view,
    task_states_view,
    verifier_verdicts_view,
)
from orchestrator.graph import recovery_proof_hash
from orchestrator.graph import boundary_manifest_hash
from orchestrator.graph import derive_recovery_paths
from tests.unit.graph_test_utils import canonical_event_payload

ProjectionPath: TypeAlias = tuple[str, ...]
OutcomeAssertion: TypeAlias = Callable[[GraphProjection, GraphProjection], None]
QueryProbe: TypeAlias = Callable[[GraphProjection], object]
MutationProbe: TypeAlias = Callable[[object], None]
FrozenQueryResultTarget: TypeAlias = Callable[[object], tuple[BaseModel, str]]


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
    has_mutable_query_target: bool = False
    frozen_query_result_target: FrozenQueryResultTarget | None = None

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


_RUNNER_TREE_SHA = "a" * 40
_RUNNER_CLEAN_ENTRY = {
    "path": "src/app.py",
    "kind": "tracked",
    "status": "clean",
    "fingerprint": "sha256:" + "a" * 64,
    "file_type": "file",
}
_RUNNER_FINAL_ENTRY = {
    **_RUNNER_CLEAN_ENTRY,
    "status": "modified",
    "fingerprint": "sha256:" + "c" * 64,
}
_RUNNER_BASELINE_ENTRIES = [_RUNNER_CLEAN_ENTRY]
_RUNNER_STAGED_ENTRIES = [_RUNNER_CLEAN_ENTRY]
_RUNNER_FINAL_ENTRIES = [_RUNNER_FINAL_ENTRY]
_RUNNER_STAGED_HASH = boundary_manifest_hash(_RUNNER_TREE_SHA, _RUNNER_STAGED_ENTRIES)
_RUNNER_FINAL_HASH = boundary_manifest_hash(_RUNNER_TREE_SHA, _RUNNER_FINAL_ENTRIES)


_RUNNER_MISMATCH_PREFIX = (
    event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "running"}, 0),
    event(
        "lease_granted",
        {
            "lease_id": "lease-1",
            "node_id": "worker-1",
            "generation": 1,
            "execution_id": "execution-1",
            "base_snapshot_id": "snapshot-1",
        },
        1,
    ),
    event(
        "runner_baseline_recorded",
        {
            "execution_id": "execution-1",
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "baseline_snapshot_id": "snapshot-1",
            "baseline_tree_sha": _RUNNER_TREE_SHA,
            "entries": _RUNNER_BASELINE_ENTRIES,
            "boundary_hash": boundary_manifest_hash(_RUNNER_TREE_SHA, _RUNNER_BASELINE_ENTRIES),
            "cache_roots": [],
        },
        2,
    ),
    event(
        "runner_submission_staged",
        {
            "execution_id": "execution-1",
            "node_id": "worker-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "idempotency_key": "callback-1",
            "payload": {"result": "ok"},
            "payload_hash": "sha256:1",
            "staged_snapshot_id": "snapshot-2",
            "staged_tree_sha": _RUNNER_TREE_SHA,
            "boundary_hash": _RUNNER_STAGED_HASH,
            "boundary_entries": _RUNNER_STAGED_ENTRIES,
            "base_snapshot_id": "snapshot-1",
            "observed_graph_position": 1,
            "is_mutating": True,
            "complete_node": True,
            "new_state": "completed",
        },
        3,
    ),
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
        assert "worker-1" in after.nodes
        assert node_creation_positions_view(after)["worker-1"] == 1
    elif event_type == "node_state_changed":
        assert node_states_view(after)["worker-1"] == "ready"
        assert "worker-1" in ready_nodes_view(after)
    elif event_type == "node_retired":
        assert node_states_view(before)["worker-1"] == "running"
        assert node_states_view(after)["worker-1"] == "retired"
    elif event_type == "node_deferred":
        assert after.nodes["worker-1"].scheduling.last_deferred_reason == "waiting"
    elif event_type == "node_ready":
        assert after.nodes["worker-1"].scheduling.last_deferred_reason is None
        assert node_states_view(after)["worker-1"] == "planned"
    elif event_type == "runtime_retry_scheduled":
        assert retry_not_before_by_node_view(after)["worker-1"] == "2026-01-01T00:01:00+00:00"
    elif event_type == "plan_region_marked_suspect":
        checkpoint = projection_to_checkpoint(after)
        assert (
            checkpoint["state"]["nodes"]["worker-1"]["runtime"]["suspect_reason"]
            == "requirement_changed"
        )
    elif event_type == "node_authority_changed":
        assert after.nodes["worker-1"].spec.allowed_actions == ("write",)
        assert node_resource_claims_view(after)["worker-1"] == []
        assert after.nodes["worker-1"].spec.preconditions == ("approved",)
    elif event_type == "edge_created":
        edge = edges_view(after).get("edge-1")
        assert edge is not None
        assert (edge.from_node_id, edge.from_port, edge.to_node_id, edge.to_port) == (
            "source-1",
            "candidate",
            "target-1",
            "candidate",
        )
    elif event_type == "input_bound":
        binding = input_bindings_view(after)["target-1"]["candidate"]
        assert tuple(binding.record_ids) == ("candidate-1",)
    elif event_type == "output_record_accepted":
        record = output_record_payloads_view(after)["record-1"]
        assert record is not None
        assert record.record_type == "fan_out_inputs"
        assert record.producer_node_id == "worker-1"
        assert record.port == "fan_out_inputs"
        indexed = output_records_by_node_port_view(after)
        assert set(indexed) == {"worker-1"}
        assert set(indexed["worker-1"]) == {"fan_out_inputs"}
        assert [item.record_id for item in indexed["worker-1"]["fan_out_inputs"]] == ["record-1"]
    elif event_type == "file_state_accepted":
        record = file_state_records_view(after)["file-state-1"]
        assert record is not None
        assert record.snapshot_id == "snapshot-1"
    elif event_type == "gatekeeper_verdict_recorded":
        record = file_state_records_view(after)["file-state-1"]
        assert record is not None
        assert record.untracked[0].classification == "source"
    elif event_type == "session_state_changed":
        assert after.planning.sessions["session-1"].state == "detached"
    elif event_type == "graph_patch_accepted":
        assert after.planning.accepted_patch_ids_by_node["planner-1"] == ("patch-1",)
        assert (
            projection_to_checkpoint(after)["state"]["governance"]["resolved_patch_ids"]["patch-1"]
            is True
        )
    elif event_type == "graph_patch_rejected":
        facts = planner_patch_facts_view(after, "planner-1")
        assert facts["patch_rejections"] == [
            {"patch_id": "patch-1", "position": 3, "reason": "invalid"}
        ]
        assert (
            projection_to_checkpoint(after)["state"]["governance"]["resolved_patch_ids"]["patch-1"]
            is True
        )
    elif event_type == "verification_passed":
        assert verifier_verdicts_view(after)["candidate-1"].verdict == "passed"
        assert passed_verification_results_by_record_id_view(after)["verification-1"] is not None
        assert after.verification.passed_candidate_ids == ("candidate-1",)
        assert task_states_view(after)["task-1"] == "accepted"
    elif event_type == "verification_failed":
        assert verifier_verdicts_view(after)["candidate-1"].verdict == "failed"
        assert failed_verification_results_by_record_id_view(after)["verification-1"] is not None
        assert failed_verification_candidate_ids_view(after)["candidate-1"] is True
        assert task_states_view(after)["task-1"] == "needs_revision"
    elif event_type == "appeal_opened":
        assert node_pending_appeals_view(after)["worker-1"] is True
    elif event_type == "approval_decision_recorded":
        governance = projection_to_checkpoint(after)["state"]["governance"]
        decision_id = governance["approval_decision_id_by_node"]["gate-1"]
        assert governance["approval_decisions_by_id"][decision_id]["decision"] == "approved"
        assert governance["node_gate_decisions"]["gate-1"] is True
    elif event_type == "authority_decision_recorded":
        governance = projection_to_checkpoint(after)["state"]["governance"]
        decision_id = governance["authority_decision_id_by_node"]["authority-1"]
        assert governance["authority_decisions_by_id"][decision_id]["decision"] == "granted"
    elif event_type == "oversight_decision_recorded":
        governance = projection_to_checkpoint(after)["state"]["governance"]
        decision_id = governance["oversight_decision_id_by_node"]["oversight-1"]
        decision = governance["oversight_decisions_by_id"][decision_id]
        assert decision is not None
        assert (decision["decision"], decision["position"]) == ("accepted", 2)
    elif event_type == "requirement_revision_recorded":
        requirements = projection_to_checkpoint(after)["state"]["requirements"]
        assert requirements["revisions_by_id"]["version-1"] is not None
        assert active_requirement_versions_view(after)["requirement-1"] == "version-1"
    elif event_type == "support_evidence_recorded":
        support = projection_to_checkpoint(after)["state"]["requirements"]["support_by_id"][
            "support-1"
        ]
        assert support is not None
        assert (
            support["evidence_id"],
            support["requirement_id"],
            support["requirement_version_id"],
        ) == (
            "evidence-1",
            "requirement-1",
            "version-1",
        )
    elif event_type == "node_usage_recorded":
        assert "execution-1:0" in after.usage.recorded_keys
        assert after.usage.tokens_by_node["worker-1"] == 5
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
        cleanup = cleanup_requested_events_view(after)["cleanup-1"]
        assert cleanup is not None
        assert (tuple(cleanup.paths), cleanup.file_state_record_id) == (
            ("src/app.py",),
            "file-state-1",
        )
    elif event_type == "cleanup_applied":
        assert cleanup_applied_ids_view(after)["cleanup-1"] is True
    elif event_type == "callback_accepted":
        callback = next(
            value
            for value in callback_idempotency_events_view(after).values()
            if value.idempotency_key == "callback-1"
        )
        assert callback is not None
        assert (callback.outcome, callback.payload) == ("callback_accepted", {"result": "ok"})
    elif event_type.startswith("runner_"):
        attempts = projection_to_checkpoint(after)["state"]["execution"]["attempts_by_execution_id"]
        assert (
            attempts["execution-1"]["state"]
            == {
                "runner_baseline_recorded": "baseline_captured",
                "runner_submission_staged": "submission_staged",
                "runner_boundary_mismatch": "submission_staged",
                "runner_recovery_requested": "recovery_requested",
                "runner_recovery_completed": "recovered",
                "runner_execution_finalized": "finalized",
            }[event_type]
        )
    else:
        raise AssertionError(f"missing direct outcome assertion for {event_type}")


def _assert_outcome(event_type: str) -> OutcomeAssertion:
    return lambda before, after: _assert_event_outcome(event_type, before, after)


def _mutate_existing_nested_value(result: object) -> None:
    """Mutate an existing nested public container without reaching projection storage."""

    def mutate(value: object, depth: int = 0) -> bool:
        if isinstance(value, list):
            value.append("__matrix_probe__")
            return True
        if isinstance(value, dict):
            for child in value.values():
                if mutate(child, depth + 1):
                    return True
            if depth and value:
                key = next(iter(value))
                value[key] = "__matrix_probe__"
                return True
            return False
        if isinstance(value, BaseModel):
            return any(
                mutate(getattr(value, field), depth + 1) for field in type(value).model_fields
            )
        return False

    assert mutate(result), "matrix query has no truthful nested mutable target"


def _frozen_model_field(result: object) -> tuple[BaseModel, str]:
    """Return an existing public frozen model and field for an assignment probe."""

    if isinstance(result, BaseModel):
        return result, next(iter(type(result).model_fields))
    if isinstance(result, dict):
        for value in result.values():
            try:
                return _frozen_model_field(value)
            except LookupError:
                continue
    if isinstance(result, (list, tuple)):
        for value in result:
            try:
                return _frozen_model_field(value)
            except LookupError:
                continue
    raise LookupError("matrix query has no frozen model assignment target")


_NEUTRAL_QUERIES: dict[str, QueryProbe] = {
    "agent_died": lambda state: lease_by_id(state, "lease-1"),
    "agent_dispatch_requested": lambda state: lease_by_id(state, "lease-1"),
    "callback_duplicate_returned": lambda state: callback_idempotency_events_view(state),
    "callback_rejected_conflict": lambda state: callback_idempotency_events_view(state),
    "callback_rejected_stale": lambda state: callback_idempotency_events_view(state),
    "command_recorded": lambda state: run_state(state),
    "command_rejected": lambda state: run_state(state),
    "dead_input_detected": lambda state: input_bindings_view(state),
    "file_state_rejected": lambda state: file_state_records_view(state),
    "gatekeeper_cost_recorded": lambda state: file_state_records_view(state),
    "heartbeat_recorded": lambda state: lease_by_id(state, "lease-1"),
    "runner_boundary_mismatch": lambda state: projection_to_checkpoint(state)["state"]["execution"],
    "outbox_requeued": lambda state: run_state(state),
    "revision_created": lambda state: state.nodes,
}


_CHANGING_QUERIES: dict[str, QueryProbe] = {
    "run_lifecycle_changed": lambda state: run_state(state),
    "node_created": lambda state: node_states_view(state),
    "node_state_changed": lambda state: node_states_view(state),
    "node_retired": lambda state: node_states_view(state),
    "node_deferred": lambda state: projection_to_checkpoint(state)["state"]["nodes"],
    "node_ready": lambda state: projection_to_checkpoint(state)["state"]["nodes"],
    "runtime_retry_scheduled": lambda state: retry_not_before_by_node_view(state),
    "plan_region_marked_suspect": lambda state: projection_to_checkpoint(state)["state"]["nodes"][
        "worker-1"
    ]["runtime"].get("suspect_reason"),
    "node_authority_changed": lambda state: projection_to_checkpoint(state)["state"]["nodes"],
    "edge_created": lambda state: edges_view(state),
    "input_bound": lambda state: input_bindings_view(state),
    "output_record_accepted": lambda state: output_records_by_node_port_view(state),
    "file_state_accepted": lambda state: file_state_records_view(state),
    "gatekeeper_verdict_recorded": lambda state: file_state_records_view(state),
    "session_state_changed": lambda state: state.planning.sessions,
    "graph_patch_accepted": lambda state: projection_to_checkpoint(state)["state"]["planning"],
    "graph_patch_rejected": lambda state: projection_to_checkpoint(state)["state"]["planning"],
    "verification_passed": lambda state: verifier_verdicts_view(state),
    "verification_failed": lambda state: verifier_verdicts_view(state),
    "appeal_opened": lambda state: node_pending_appeals_view(state),
    "approval_decision_recorded": lambda state: state.governance.approval_decisions_by_id,
    "authority_decision_recorded": lambda state: state.governance.authority_decisions_by_id,
    "oversight_decision_recorded": lambda state: state.governance.oversight_decisions_by_id,
    "requirement_revision_recorded": lambda state: state.requirements.revisions_by_id,
    "support_evidence_recorded": lambda state: state.requirements.support_by_id,
    "node_usage_recorded": lambda state: state.usage.tokens_by_node,
    "lease_granted": lambda state: leases_view(state),
    "lease_renewed": lambda state: leases_view(state),
    "lease_suspended": lambda state: leases_view(state),
    "lease_revoked": lambda state: leases_view(state),
    "lease_expired": lambda state: leases_view(state),
    "lease_released": lambda state: leases_view(state),
    "cleanup_requested": lambda state: cleanup_requested_events_view(state),
    "cleanup_applied": lambda state: cleanup_applied_ids_view(state),
    "callback_accepted": lambda state: callback_idempotency_events_view(state),
}


_MUTABLE_QUERY_EVENTS = frozenset(
    {
        "graph_patch_accepted",
    }
)


_FROZEN_QUERY_EVENTS = frozenset(
    {
        "edge_created",
        "input_bound",
        "output_record_accepted",
        "file_state_accepted",
        "gatekeeper_verdict_recorded",
        "verification_passed",
        "verification_failed",
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
    "graph_patch_rejected": (("nodes", "planner-1"),),
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
    "heartbeat_recorded": {
        "lease_id": "lease-1",
        "node_id": "worker-1",
        "observed_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-01T00:05:00+00:00",
    },
    "runner_boundary_mismatch": {
        "execution_id": "execution-1",
        "node_id": "worker-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "staged_boundary_hash": _RUNNER_STAGED_HASH,
        "final_boundary_hash": _RUNNER_FINAL_HASH,
        "final_tree_sha": _RUNNER_TREE_SHA,
        "final_boundary_entries": _RUNNER_FINAL_ENTRIES,
        "reason": "boundary_mismatch",
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
            _RUNNER_MISMATCH_PREFIX if name == "runner_boundary_mismatch" else (),
            event(name, payload, 1),
            frozenset(),
            (),
            (),
            _unchanged,
            _NEUTRAL_QUERIES[name],
            None,
            False,
            None,
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
            "external": [
                {
                    "path": "vendor/tool",
                    "source": "external",
                    "manifest": {
                        "path": "vendor/tool",
                        "hash": "sha256:tool",
                        "origin": "registry",
                        "retention": "keep",
                    },
                }
            ],
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
    runner_context = (
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "running"}, 0),
        _event(
            "lease_granted",
            {
                "lease_id": "lease-1",
                "node_id": "worker-1",
                "generation": 1,
                "execution_id": "execution-1",
                "base_snapshot_id": "snapshot-1",
            },
            1,
        ),
    )
    runner_baseline_payload: dict[str, object] = {
        "execution_id": "execution-1",
        "node_id": "worker-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "baseline_snapshot_id": "snapshot-1",
        "baseline_tree_sha": _RUNNER_TREE_SHA,
        "entries": _RUNNER_BASELINE_ENTRIES,
        "boundary_hash": boundary_manifest_hash(_RUNNER_TREE_SHA, _RUNNER_BASELINE_ENTRIES),
        "cache_roots": [".cache"],
    }
    runner_baseline = _event("runner_baseline_recorded", runner_baseline_payload, 2)
    runner_staged_payload: dict[str, object] = {
        "execution_id": "execution-1",
        "node_id": "worker-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "idempotency_key": "callback-1",
        "payload": {"result": "ok"},
        "payload_hash": "sha256:1",
        "staged_snapshot_id": "snapshot-2",
        "staged_tree_sha": _RUNNER_TREE_SHA,
        "boundary_hash": _RUNNER_STAGED_HASH,
        "boundary_entries": _RUNNER_STAGED_ENTRIES,
        "base_snapshot_id": "snapshot-1",
        "observed_graph_position": 1,
        "is_mutating": True,
        "complete_node": True,
        "new_state": "completed",
    }
    runner_staged = _event("runner_submission_staged", runner_staged_payload, 3)
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
                    },
                    {
                        "path": "vendor/tool",
                        "classification": "dependency",
                        "confidence": 1.0,
                        "rationale": "canonical external",
                    },
                ],
                "resolved_count": 2,
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
            "graph_patch_rejected",
            (planner, patch_proposal),
            {
                "patch_id": "patch-1",
                "proposed_by_node_id": "planner-1",
                "reason": "invalid",
            },
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
    runner_recovery_requested_payload: dict[str, object] = {
        "execution_id": "execution-1",
        "recovery_id": "recovery-1",
        "node_id": "worker-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "reason": "boundary_mismatch",
        "baseline_snapshot_id": "snapshot-1",
        "baseline_tree_sha": _RUNNER_TREE_SHA,
        "final_tree_sha": _RUNNER_TREE_SHA,
        "final_boundary_hash": _RUNNER_FINAL_HASH,
        "final_boundary_entries": _RUNNER_FINAL_ENTRIES,
        "paths": list(
            derive_recovery_paths(
                _RUNNER_BASELINE_ENTRIES,
                _RUNNER_STAGED_ENTRIES,
                _RUNNER_FINAL_ENTRIES,
                [],
                [".cache"],
            )
        ),
    }
    runner_recovery_requested = _event(
        "runner_recovery_requested", runner_recovery_requested_payload, 2
    )
    runner_names = (
        "runner_baseline_recorded",
        "runner_submission_staged",
        "runner_boundary_mismatch",
        "runner_recovery_requested",
        "runner_recovery_completed",
        "runner_execution_finalized",
    )
    _CHANGING_QUERIES.update(
        {
            name: lambda projection: projection_to_checkpoint(projection)["state"]["execution"].get(
                "attempts_by_execution_id", {}
            )
            for name in runner_names
        }
    )
    _SHARED_PATHS.update({name: (("lifecycle",),) for name in runner_names})
    changing_payloads = (
        *changing_payloads,
        (
            "runner_baseline_recorded",
            runner_context,
            runner_baseline_payload,
            frozenset({"execution"}),
        ),
        (
            "runner_submission_staged",
            (*runner_context, runner_baseline),
            runner_staged_payload,
            frozenset({"execution"}),
        ),
        (
            "runner_recovery_requested",
            (*runner_context, runner_baseline, runner_staged),
            runner_recovery_requested_payload,
            frozenset({"execution"}),
        ),
        (
            "runner_recovery_completed",
            (*runner_context, runner_baseline, runner_staged, runner_recovery_requested),
            {
                "execution_id": "execution-1",
                "recovery_id": "recovery-1",
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "baseline_snapshot_id": "snapshot-1",
                "baseline_tree_sha": _RUNNER_TREE_SHA,
                "requested_paths": list(
                    derive_recovery_paths(
                        _RUNNER_BASELINE_ENTRIES,
                        _RUNNER_STAGED_ENTRIES,
                        _RUNNER_FINAL_ENTRIES,
                        [],
                        [".cache"],
                    )
                ),
                "proof_hash": recovery_proof_hash(
                    execution_id="execution-1",
                    recovery_id="recovery-1",
                    node_id="worker-1",
                    lease_id="lease-1",
                    lease_generation=1,
                    baseline_snapshot_id="snapshot-1",
                    baseline_tree_sha=_RUNNER_TREE_SHA,
                    requested_paths=(".cache", "src/app.py"),
                    restored_paths=(".cache", "src/app.py"),
                    removed_paths=(),
                ),
                "restored_paths": [".cache", "src/app.py"],
                "removed_paths": [],
            },
            frozenset({"execution"}),
        ),
        (
            "runner_execution_finalized",
            (*runner_context, runner_baseline, runner_staged),
            {
                "execution_id": "execution-1",
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "final_snapshot_id": "snapshot-3",
                "final_tree_sha": _RUNNER_TREE_SHA,
                "boundary_hash": _RUNNER_STAGED_HASH,
                "boundary_entries": _RUNNER_STAGED_ENTRIES,
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
            _mutate_existing_nested_value if name in _MUTABLE_QUERY_EVENTS else None,
            name in _MUTABLE_QUERY_EVENTS,
            _frozen_model_field if name in _FROZEN_QUERY_EVENTS else None,
        )
        for name, prefix, payload, groups in changing_payloads
    )
    return (*neutral, *changing)


def replay_streams() -> tuple[tuple[str, tuple[EventEnvelope, ...]], ...]:
    """Return the canonical replay streams derived solely from matrix cases."""
    return tuple((case.event_type, case.stream) for case in behavior_cases())
