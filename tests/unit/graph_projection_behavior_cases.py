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
    initial_projection,
    projection_to_checkpoint,
    reduce_event,
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


def _changed_groups(groups: frozenset[str]) -> OutcomeAssertion:
    def assert_changed(before: GraphProjection, after: GraphProjection) -> None:
        for group in groups:
            assert getattr(after, group) is not getattr(before, group)

    return assert_changed


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
            lambda state: projection_to_checkpoint(state),
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
    verification = _event(
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
            (worker,),
            {"node_id": "worker-1", "new_state": "ready"},
            frozenset({"nodes", "scheduling"}),
        ),
        ("node_retired", (worker,), {"node_id": "worker-1"}, frozenset({"nodes"})),
        (
            "node_deferred",
            (worker,),
            {"node_id": "worker-1", "reason": "waiting"},
            frozenset({"nodes"}),
        ),
        (
            "node_ready",
            (worker, _event("node_deferred", {"node_id": "worker-1", "reason": "waiting"}, 1)),
            {"node_id": "worker-1"},
            frozenset({"nodes"}),
        ),
        (
            "runtime_retry_scheduled",
            (worker,),
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
            (worker,),
            {"node_id": "worker-1", "reason": "requirement_changed"},
            frozenset({"nodes"}),
        ),
        (
            "node_authority_changed",
            (worker,),
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
            (source, target, edge, candidate),
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
            frozenset({"records"}),
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
            (),
            {"patch_id": "patch-1", "proposed_by_node_id": "planner-1"},
            frozenset({"planning", "governance"}),
        ),
        (
            "verification_passed",
            (worker, file_state, candidate, verifier, verification),
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
            (worker, file_state, candidate, verifier, verification),
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
            (),
            {"node_id": "appeal-1", "appealed_node_id": "worker-1", "appeal_type": "other"},
            frozenset({"governance"}),
        ),
        (
            "approval_decision_recorded",
            (),
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
            (),
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
            (),
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
            (),
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
            frozenset({"execution"}),
        ),
        (
            "lease_renewed",
            (worker, granted),
            {"lease_id": "lease-1", "expires_at": "2026-01-01T00:10:00+00:00"},
            frozenset({"execution"}),
        ),
        *(
            (name, (worker, granted), {"lease_id": "lease-1"}, frozenset({"execution"}))
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
            frozenset({"execution"}),
        ),
        ("cleanup_applied", (), {"cleanup_id": "cleanup-1"}, frozenset({"execution"})),
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
            tuple((group,) for group in sorted(groups)),
            (),
            _changed_groups(groups),
            lambda state: projection_to_checkpoint(state),
        )
        for name, prefix, payload, groups in changing_payloads
    )
    return (*neutral, *changing)
