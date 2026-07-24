"""Pure graph projections for scenario fixtures."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import UTC, datetime
from typing import Any, Iterable, Literal, TypedDict, cast

from pydantic import ConfigDict, field_validator

from orchestrator.graph.command_bindings import check_command_reference
from orchestrator.graph.contracts import (
    DEFAULT_NODE_CONTRACTS,
    PortContract,
    binding_policy,
    binding_policy_for_edge,
    input_port_contract,
    merge_bound_record_ids,
    node_contract_summary,
    output_port_contract,
    port_contract_summary,
)
from orchestrator.graph.models import (
    AcceptedOutputRecordPayload,
    AppealOpenedPayload,
    ApprovalDecisionRecordedPayload,
    ApprovalDecisionProjection,
    AuthorityDecisionProjection,
    AuthorityDecisionRecordedPayload,
    AuthorityRequestRecord,
    CallbackAcceptedPayload,
    CallbackIdempotencyEvent,
    CandidateProjection,
    CandidateRecord,
    CheckResultProjection,
    CheckResultRecord,
    CleanupAppliedPayload,
    CleanupRequestedPayload,
    CleanupRequestedProjection,
    CommandDefinitionProjection,
    CompletionDecisionRecord,
    DecisionRequestRecord,
    EdgeProjection,
    EnvironmentFailureProjection,
    EventEnvelope,
    ExternalFileEntry,
    FileEntry,
    FileStateAcceptedPayload,
    FileStateRecord,
    GatekeeperCostRecordedPayload,
    GatekeeperVerdictRecordedPayload,
    GraphBaseModel,
    GraphPatchAcceptedPayload,
    GraphPatchRejectedPayload,
    GraphPatchResultRecord,
    InvalidTestBlockProjection,
    InputBindingProjection,
    InputBoundPayload,
    LeaseExpiredPayload,
    LeaseGrantedPayload,
    LeaseProjection,
    LeaseReleasedPayload,
    LeaseRenewedPayload,
    LeaseRevokedPayload,
    LeaseSuspendedPayload,
    NodeCreationProjection,
    NodeAuthorityChangedPayload,
    NodeCreatedPayload,
    NodeDeferredPayload,
    NodeReadyPayload,
    NodeRetiredPayload,
    NodeStateChangedPayload,
    NodeUsageRecordedPayload,
    NodeSuspectPayload,
    NodeKind,
    NodeState,
    OversightDecisionProjection,
    OversightDecisionRecordedPayload,
    OutputRecord,
    OutputRecordAcceptedPayload,
    PendingGateDecisionProjection,
    PlannerSessionStateChangedPayload,
    RequirementRevisionPayload,
    RequirementRevisionProjection,
    RunLifecycleChangedPayload,
    RuntimeRetryScheduledPayload,
    ResourceClaimProjection,
    RoutineSnapshotRecord,
    SupportEvidenceProjection,
    SupportEvidencePayload,
    VerificationFailedPayload,
    VerificationOutcomePayload,
    VerificationPassedPayload,
    VerificationResultProjection,
    VerifierVerdictProjection,
)
from orchestrator.graph.models import normalize_record_selector
from orchestrator.graph.payload_registry import (
    GRAPH_PROJECTION_PAYLOAD_FIELDS as _GENERATED_GRAPH_PROJECTION_PAYLOAD_FIELDS,
)


_EDGE_METADATA_KEYS = (
    "purpose",
    "description",
    "selection",
    "binding_policy",
    "freshness_policy",
    "prompt_hydration_policy",
    "metadata",
)

_TASK_STATE_VALUES = {
    "accepted",
    "blocked_environment",
    "blocked_invalid_test",
    "in_progress",
    "needs_revision",
    "pending",
}
_NODE_STATE_VALUES = {state.value for state in NodeState}
_NODE_KIND_VALUES = {kind.value for kind in NodeKind}

# Bump this whenever reduce_event semantics or GraphProjection shape changes.
PROJECTION_SCHEMA_VERSION = 12
GRAPH_PROJECTION_PAYLOAD_FIELDS = _GENERATED_GRAPH_PROJECTION_PAYLOAD_FIELDS


class GraphRecordSummary(TypedDict, total=False):
    record_id: str
    record_type: str
    record_kind: str
    schema: str
    producer_node_id: str
    producer_port: str
    position: int


class AcceptedOutputRecord(TypedDict):
    record_id: str
    payload: AcceptedOutputRecordPayload


class RecoveryNodeIndexEntry(GraphBaseModel):
    model_config = ConfigDict(extra="ignore")

    node_id: str
    recovery_reason: str

    @field_validator("node_id", "recovery_reason")
    @classmethod
    def fields_must_be_non_empty(cls, value: str) -> str:
        if not value:
            msg = "field must be non-empty"
            raise ValueError(msg)
        return value


class LatestRoutineSnapshotRecord(GraphBaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: str
    producer_node_id: str
    port: str

    @field_validator("record_id", "producer_node_id", "port")
    @classmethod
    def fields_must_be_non_empty(cls, value: str) -> str:
        if not value:
            msg = "field must be non-empty"
            raise ValueError(msg)
        return value


class GraphProjection(TypedDict):
    run_state: str | None
    node_states: dict[str, str]
    task_states: dict[str, str]
    leases: dict[str, LeaseProjection]
    ready_nodes: list[str]
    node_kinds: dict[str, str]
    node_roles: dict[str, str]
    node_creation_positions: dict[str, int]
    node_task_regions: dict[str, str]
    node_attempts: dict[str, int]
    node_candidates: dict[str, str]
    node_failed_candidates: dict[str, str]
    node_resource_claims: dict[str, list[ResourceClaimProjection]]
    node_allowed_actions: dict[str, list[str]]
    node_preconditions: dict[str, list[str]]
    node_command_definitions: dict[str, CommandDefinitionProjection]
    node_output_ports: dict[str, dict[str, list[str]]]
    accepted_output_records_by_node_port: dict[str, dict[str, list[AcceptedOutputRecord]]]
    accepted_record_summaries_by_id: dict[str, GraphRecordSummary]
    output_records_by_node_port: dict[str, dict[str, list[AcceptedOutputRecordPayload]]]
    edges: dict[str, EdgeProjection]
    input_bindings: dict[str, dict[str, InputBindingProjection]]
    node_pending_appeals: dict[str, bool]
    node_gate_decisions: dict[str, bool]
    task_candidates: dict[str, list[CandidateProjection]]
    verifier_verdicts: dict[str, VerifierVerdictProjection]
    completion_decision_passed: bool
    passed_verification_results_by_record_id: dict[str, VerificationResultProjection]
    failed_verification_results_by_record_id: dict[str, VerificationResultProjection]
    passed_verification_candidate_ids: list[str]
    failed_verification_candidate_ids: dict[str, bool]
    recovery_nodes_by_record_id: dict[str, list[RecoveryNodeIndexEntry]]
    check_results: dict[str, CheckResultProjection]
    invalid_test_blocks: dict[str, InvalidTestBlockProjection]
    configured_gates: dict[str, dict[str, bool]]
    gate_decisions: dict[str, dict[str, bool]]
    environment_failures: dict[str, EnvironmentFailureProjection]
    file_state_records: dict[str, FileStateRecord]
    planner_generation_budget: int
    planner_successors: dict[str, str]
    accepted_graph_patches_by_node: dict[str, list[str]]
    accepted_no_successor_patches_by_node: dict[str, list[str]]
    accepted_no_successor_patch_ids_by_node: dict[str, str]
    latest_routine_snapshot_record: LatestRoutineSnapshotRecord | None
    planner_generations: dict[str, int]
    planner_sessions: dict[str, str]
    planner_session_states: dict[str, str]
    planner_session_current_nodes: dict[str, str]
    planner_session_carryovers: dict[str, str | None]
    planner_region_labels: dict[str, str]
    requirement_revisions: dict[str, RequirementRevisionProjection]
    active_requirement_versions: dict[str, str]
    support_evidence: dict[str, SupportEvidenceProjection]
    last_deferred_reasons: dict[str, str]
    retry_not_before_by_node: dict[str, str | None]
    node_creation_payloads: dict[str, NodeCreationProjection]
    output_record_payloads: dict[str, AcceptedOutputRecordPayload]
    approval_decisions: dict[str, ApprovalDecisionProjection]
    authority_decisions: dict[str, AuthorityDecisionProjection]
    oversight_decisions: dict[str, OversightDecisionProjection]
    decision_request_details: dict[str, PendingGateDecisionProjection]
    callback_idempotency_events: dict[str, CallbackIdempotencyEvent]
    open_proposal_blockers: dict[str, FinalInvariantBlocker]
    suspect_node_reasons: dict[str, str]
    authority_revision_blockers: dict[str, FinalInvariantBlocker]
    cleanup_requested_events: dict[str, CleanupRequestedProjection]
    cleanup_applied_ids: dict[str, bool]
    tokens_by_node: dict[str, int]
    tokens_by_node_kind: dict[str, int]
    latency_ms_by_node_kind: dict[str, int]
    execution_count_by_node_kind: dict[str, int]
    num_actions_by_node_kind: dict[str, int]
    recorded_node_usage_keys: dict[str, bool]


class GraphTopologyBinding(TypedDict, total=False):
    edge_id: str
    to_node_id: str
    to_port: str
    record_ids: list[str]
    bound_at_position: int
    record_bound_positions: dict[str, int]
    binding_policy: str
    trigger: str


class GraphTopologyNode(TypedDict, total=False):
    node_id: str
    kind: str | None
    role: str | None
    state: str | None
    contract: dict[str, Any]


class GraphTopologyEdge(TypedDict, total=False):
    edge_id: str
    from_node_id: str
    from_node_kind: str
    from_node_role: str
    from_port: str
    to_node_id: str
    to_port: str
    required: bool
    dependency_type: str
    accepted_record_selector: dict[str, Any]
    metadata: dict[str, Any]
    source_port_contract: dict[str, Any]
    target_port_contract: dict[str, Any]
    record_types: list[str]
    binding: GraphTopologyBinding | None
    bound_records: list[GraphRecordSummary]


class GraphTopologyView(TypedDict):
    nodes: list[GraphTopologyNode]
    edges: list[GraphTopologyEdge]


class SchedulerBlockedNode(TypedDict):
    node_id: str
    reason: str


class SchedulerView(TypedDict):
    ready: list[str]
    blocked: list[SchedulerBlockedNode]
    waiting_resources: list[SchedulerBlockedNode]
    waiting_gates: list[SchedulerBlockedNode]


class LeaseViewEntry(TypedDict):
    lease_id: str
    node_id: str
    generation: int | None
    state: str
    execution_id: str | None
    expires_at: str | None


class LeaseView(TypedDict):
    active: list[LeaseViewEntry]
    suspended: list[LeaseViewEntry]


class PendingGateDecision(TypedDict, total=False):
    node_id: str
    gate_type: str
    prompt: str | None
    options: list[str]
    default_option: str
    consequence_summary: str
    expires_at: str
    requested_authority: list[str]
    target_node_id: str
    target_region_id: str


class AppealDecision(TypedDict):
    node_id: str
    state: str
    outcome: str | None


class ReviewReadiness(TypedDict):
    ready: bool
    blockers: list[str]


class DecisionView(TypedDict):
    pending_gates: list[PendingGateDecision]
    appeals: list[AppealDecision]
    review: ReviewReadiness


class SupportEvidenceFreshness(TypedDict):
    support_id: str
    evidence_id: str
    requirement_id: str
    requirement_version_id: str
    status: str
    freshness: Literal["fresh", "stale"]
    stale_reason: str | None


class RequirementFreshnessFact(TypedDict):
    requirement_id: str
    active_version_id: str
    revision_classification: str
    requires_authority: bool
    authority_required_reason: str | None
    fresh_support_ids: list[str]
    stale_support_ids: list[str]
    unsupported: bool


class FinalInvariantBlocker(TypedDict, total=False):
    kind: str
    reason: str
    node_id: str
    edge_id: str
    from_node_id: str
    to_port: str
    proposal_id: str
    requirement_id: str
    revision_id: str
    task_region_id: str
    state: str
    classification: str
    command_text: str
    stderr_tail: str
    exit_code: int
    support_ids: list[str]


TERMINAL_GRAPH_NODE_STATES = frozenset({"completed", "failed", "cancelled", "retired"})


@dataclass(frozen=True)
class GraphRunOutcome:
    """Pure driver-facing classification of a graph projection."""

    run_id: str
    run_state: str | None
    completed: bool
    blocked_reason: str | None = None


def _empty_str_dict() -> dict[str, str]:
    return {}


def _empty_environment_failures() -> dict[str, EnvironmentFailureProjection]:
    return {}


def _empty_int_dict() -> dict[str, int]:
    return {}


def _empty_str_list_dict() -> dict[str, list[str]]:
    return {}


@dataclass(frozen=True)
class GraphProjectionSnapshot:
    """Driver policy view derived solely from a graph event projection."""

    run_state: str | None
    ready_nodes: list[str]
    active_leases: dict[str, dict[str, Any]]
    schedulable_nodes: list[str]
    task_states: dict[str, str]
    node_states: dict[str, str] = dataclass_field(default_factory=_empty_str_dict)
    failed_node_reasons: dict[str, str] = dataclass_field(default_factory=_empty_str_dict)
    node_deferral_reasons: dict[str, str] = dataclass_field(default_factory=_empty_str_dict)
    missing_input_sources: dict[str, list[str]] = dataclass_field(
        default_factory=_empty_str_list_dict
    )
    environment_failures: dict[str, EnvironmentFailureProjection] = dataclass_field(
        default_factory=_empty_environment_failures
    )
    node_max_attempts: dict[str, int] = dataclass_field(default_factory=_empty_int_dict)


@dataclass(frozen=True)
class ActiveLeaseWaitPlan:
    execution_ids: set[str]
    timeout_seconds: float | None


class GraphPatchAttempt(TypedDict, total=False):
    patch_id: str
    proposed_by_node_id: str
    base_graph_position: int
    current_graph_position: int
    status: Literal["accepted", "rejected"]
    rejection_reason: str
    diagnostics: dict[str, Any]
    read_set_diff: dict[str, Any]
    accepted_event_id: str
    accepted_position: int
    rejected_event_id: str
    rejected_position: int
    created_node_ids: list[str]
    created_edge_ids: list[str]


class GraphPatchAttemptView(TypedDict):
    run_id: str
    current_graph_position: int
    attempts: list[GraphPatchAttempt]


def initial_projection() -> GraphProjection:
    return {
        "run_state": None,
        "node_states": {},
        "task_states": {},
        "leases": {},
        "ready_nodes": [],
        "node_kinds": {},
        "node_roles": {},
        "node_creation_positions": {},
        "node_task_regions": {},
        "node_attempts": {},
        "node_candidates": {},
        "node_failed_candidates": {},
        "node_resource_claims": {},
        "node_allowed_actions": {},
        "node_preconditions": {},
        "node_command_definitions": {},
        "node_output_ports": {},
        "accepted_output_records_by_node_port": {},
        "accepted_record_summaries_by_id": {},
        "output_records_by_node_port": {},
        "edges": {},
        "input_bindings": {},
        "node_pending_appeals": {},
        "node_gate_decisions": {},
        "task_candidates": {},
        "verifier_verdicts": {},
        "completion_decision_passed": False,
        "passed_verification_results_by_record_id": {},
        "failed_verification_results_by_record_id": {},
        "passed_verification_candidate_ids": [],
        "failed_verification_candidate_ids": {},
        "recovery_nodes_by_record_id": {},
        "check_results": {},
        "invalid_test_blocks": {},
        "configured_gates": {},
        "gate_decisions": {},
        "environment_failures": {},
        "file_state_records": {},
        "planner_generation_budget": 8,
        "planner_successors": {},
        "accepted_graph_patches_by_node": {},
        "accepted_no_successor_patches_by_node": {},
        "accepted_no_successor_patch_ids_by_node": {},
        "latest_routine_snapshot_record": None,
        "planner_generations": {},
        "planner_sessions": {},
        "planner_session_states": {},
        "planner_session_current_nodes": {},
        "planner_session_carryovers": {},
        "planner_region_labels": {},
        "requirement_revisions": {},
        "active_requirement_versions": {},
        "support_evidence": {},
        "last_deferred_reasons": {},
        "retry_not_before_by_node": {},
        "node_creation_payloads": {},
        "output_record_payloads": {},
        "approval_decisions": {},
        "authority_decisions": {},
        "oversight_decisions": {},
        "decision_request_details": {},
        "callback_idempotency_events": {},
        "open_proposal_blockers": {},
        "suspect_node_reasons": {},
        "authority_revision_blockers": {},
        "cleanup_requested_events": {},
        "cleanup_applied_ids": {},
        "tokens_by_node": {},
        "tokens_by_node_kind": {},
        "latency_ms_by_node_kind": {},
        "execution_count_by_node_kind": {},
        "num_actions_by_node_kind": {},
        "recorded_node_usage_keys": {},
    }


def projection_to_checkpoint(projection: GraphProjection) -> dict[str, Any]:
    checkpoint = dict(cast(dict[str, Any], projection))
    checkpoint["node_states"] = _string_map_from_checkpoint(
        projection.get("node_states"),
        _NODE_STATE_VALUES,
    )
    checkpoint["task_states"] = _string_map_from_checkpoint(
        projection.get("task_states"),
        _TASK_STATE_VALUES,
    )
    checkpoint["node_kinds"] = _string_map_from_checkpoint(
        projection.get("node_kinds"),
        _NODE_KIND_VALUES,
    )
    checkpoint["node_resource_claims"] = _node_resource_claims_from_checkpoint(
        projection.get("node_resource_claims"),
    )
    checkpoint["node_resource_claims"] = {
        node_id: [claim.model_dump(mode="json") for claim in claims]
        for node_id, claims in checkpoint["node_resource_claims"].items()
    }
    checkpoint["leases"] = {
        lease_id: lease.model_dump(mode="json")
        for lease_id, lease in projection.get("leases", {}).items()
    }
    checkpoint["edges"] = {
        edge_id: edge_copy.model_dump(mode="json")
        for edge_id, edge in projection.get("edges", {}).items()
        if (edge_copy := _copy_edge_projection(edge)) is not None
    }
    checkpoint["input_bindings"] = {
        node_id: {
            port: binding_copy.model_dump(mode="json")
            for port, binding in ports.items()
            if (binding_copy := _copy_input_binding_projection(binding)) is not None
        }
        for node_id, ports in projection.get("input_bindings", {}).items()
    }
    checkpoint["passed_verification_results_by_record_id"] = {
        record_id: result.model_dump(mode="json")
        for record_id, result in projection.get(
            "passed_verification_results_by_record_id", {}
        ).items()
    }
    checkpoint["failed_verification_results_by_record_id"] = {
        record_id: result.model_dump(mode="json")
        for record_id, result in projection.get(
            "failed_verification_results_by_record_id", {}
        ).items()
    }
    checkpoint["check_results"] = {
        node_id: result.model_dump(mode="json")
        for node_id, result in projection.get("check_results", {}).items()
    }
    checkpoint["invalid_test_blocks"] = {
        task_region_id: block.model_dump(mode="json")
        for task_region_id, block in projection.get("invalid_test_blocks", {}).items()
    }
    checkpoint["decision_request_details"] = {
        node_id: details.model_dump(mode="json")
        for node_id, details in projection.get("decision_request_details", {}).items()
    }
    checkpoint["cleanup_requested_events"] = {
        cleanup_id: event.model_dump(mode="json")
        for cleanup_id, event in projection.get("cleanup_requested_events", {}).items()
    }
    checkpoint["task_candidates"] = {
        task_region_id: [candidate.model_dump(mode="json") for candidate in candidates]
        for task_region_id, candidates in projection.get("task_candidates", {}).items()
    }
    checkpoint["verifier_verdicts"] = {
        candidate_id: verdict.model_dump(mode="json")
        for candidate_id, verdict in projection.get("verifier_verdicts", {}).items()
    }
    checkpoint["accepted_output_records_by_node_port"] = {
        node_id: {
            port: [
                {
                    "record_id": record["record_id"],
                    "payload": _output_record_payload_dict(record["payload"]),
                }
                for record in records
            ]
            for port, records in ports.items()
        }
        for node_id, ports in projection.get("accepted_output_records_by_node_port", {}).items()
    }
    checkpoint["output_records_by_node_port"] = {
        node_id: {
            port: [_output_record_payload_dict(record) for record in records]
            for port, records in ports.items()
        }
        for node_id, ports in projection.get("output_records_by_node_port", {}).items()
    }
    checkpoint["output_record_payloads"] = {
        record_id: _output_record_payload_dict(payload)
        for record_id, payload in projection.get("output_record_payloads", {}).items()
    }
    checkpoint["callback_idempotency_events"] = {
        key: event.model_dump(mode="json")
        for key, event in projection.get("callback_idempotency_events", {}).items()
    }
    checkpoint["environment_failures"] = {
        task_region_id: failure.model_dump(mode="json")
        for task_region_id, failure in projection.get("environment_failures", {}).items()
    }
    checkpoint["file_state_records"] = {
        record_id: record.model_dump(mode="json")
        for record_id, record in projection.get("file_state_records", {}).items()
    }
    checkpoint["recovery_nodes_by_record_id"] = _recovery_nodes_from_checkpoint(
        projection.get("recovery_nodes_by_record_id"),
    )
    checkpoint["recovery_nodes_by_record_id"] = {
        record_id: [recovery.model_dump(mode="json") for recovery in recoveries]
        for record_id, recoveries in checkpoint["recovery_nodes_by_record_id"].items()
    }
    checkpoint["latest_routine_snapshot_record"] = _latest_routine_snapshot_from_checkpoint(
        projection.get("latest_routine_snapshot_record"),
    )
    if checkpoint["latest_routine_snapshot_record"] is not None:
        checkpoint["latest_routine_snapshot_record"] = checkpoint[
            "latest_routine_snapshot_record"
        ].model_dump(mode="json")
    checkpoint["node_creation_payloads"] = {
        node_id: payload.model_dump(mode="json")
        for node_id, payload in projection.get("node_creation_payloads", {}).items()
    }
    checkpoint["approval_decisions"] = {
        node_id: payload.model_dump(mode="json")
        for node_id, payload in projection.get("approval_decisions", {}).items()
    }
    checkpoint["authority_decisions"] = {
        node_id: payload.model_dump(mode="json")
        for node_id, payload in projection.get("authority_decisions", {}).items()
    }
    checkpoint["requirement_revisions"] = {
        version_id: revision.model_dump(mode="json")
        for version_id, revision in projection.get("requirement_revisions", {}).items()
    }
    checkpoint["support_evidence"] = {
        support_id: support.model_dump(mode="json")
        for support_id, support in projection.get("support_evidence", {}).items()
    }
    checkpoint["oversight_decisions"] = {
        node_id: payload.model_dump(mode="json")
        for node_id, payload in projection.get("oversight_decisions", {}).items()
    }
    return checkpoint


def projection_from_checkpoint(raw_projection: dict[str, Any]) -> GraphProjection:
    projection = cast(GraphProjection, {**initial_projection(), **raw_projection})
    projection["run_state"] = _nullable_string_from_checkpoint(raw_projection.get("run_state"))
    projection["ready_nodes"] = _string_list_from_checkpoint(raw_projection.get("ready_nodes"))
    projection["node_states"] = _string_map_from_checkpoint(
        raw_projection.get("node_states"),
        _NODE_STATE_VALUES,
    )
    projection["task_states"] = _string_map_from_checkpoint(
        raw_projection.get("task_states"),
        _TASK_STATE_VALUES,
    )
    projection["node_kinds"] = _string_map_from_checkpoint(
        raw_projection.get("node_kinds"),
        _NODE_KIND_VALUES,
    )
    projection["node_roles"] = _string_map_from_checkpoint(raw_projection.get("node_roles"))
    projection["node_creation_positions"] = _int_map_from_checkpoint(
        raw_projection.get("node_creation_positions"),
    )
    projection["node_task_regions"] = _string_map_from_checkpoint(
        raw_projection.get("node_task_regions"),
    )
    projection["node_attempts"] = _int_map_from_checkpoint(raw_projection.get("node_attempts"))
    projection["node_candidates"] = _string_map_from_checkpoint(
        raw_projection.get("node_candidates"),
    )
    projection["node_failed_candidates"] = _string_map_from_checkpoint(
        raw_projection.get("node_failed_candidates"),
    )
    projection["node_resource_claims"] = _node_resource_claims_from_checkpoint(
        raw_projection.get("node_resource_claims"),
    )
    projection["node_allowed_actions"] = _string_list_map_from_checkpoint(
        raw_projection.get("node_allowed_actions"),
    )
    projection["node_preconditions"] = _string_list_map_from_checkpoint(
        raw_projection.get("node_preconditions"),
    )
    projection["node_command_definitions"] = _dict_map_from_checkpoint(
        raw_projection.get("node_command_definitions"),
    )
    projection["node_output_ports"] = _node_output_ports_from_checkpoint(
        raw_projection.get("node_output_ports"),
    )
    projection["accepted_record_summaries_by_id"] = _record_summaries_from_checkpoint(
        raw_projection.get("accepted_record_summaries_by_id"),
    )
    projection["leases"] = _leases_from_checkpoint(
        raw_projection.get("leases"),
    )
    projection["edges"] = _edges_from_checkpoint(
        raw_projection.get("edges"),
    )
    projection["input_bindings"] = _input_bindings_from_checkpoint(
        raw_projection.get("input_bindings"),
    )
    projection["node_pending_appeals"] = _bool_map_from_checkpoint(
        raw_projection.get("node_pending_appeals"),
    )
    projection["node_gate_decisions"] = _bool_map_from_checkpoint(
        raw_projection.get("node_gate_decisions"),
    )
    projection["completion_decision_passed"] = _bool_from_checkpoint(
        raw_projection.get("completion_decision_passed"),
    )
    projection["passed_verification_results_by_record_id"] = _verification_results_from_checkpoint(
        raw_projection.get("passed_verification_results_by_record_id"),
    )
    projection["failed_verification_results_by_record_id"] = _verification_results_from_checkpoint(
        raw_projection.get("failed_verification_results_by_record_id"),
    )
    projection["passed_verification_candidate_ids"] = _string_list_from_checkpoint(
        raw_projection.get("passed_verification_candidate_ids"),
    )
    projection["failed_verification_candidate_ids"] = _bool_map_from_checkpoint(
        raw_projection.get("failed_verification_candidate_ids"),
    )
    projection["check_results"] = _check_results_from_checkpoint(
        raw_projection.get("check_results"),
    )
    projection["invalid_test_blocks"] = _invalid_test_blocks_from_checkpoint(
        raw_projection.get("invalid_test_blocks"),
    )
    projection["configured_gates"] = _bool_matrix_from_checkpoint(
        raw_projection.get("configured_gates"),
    )
    projection["gate_decisions"] = _bool_matrix_from_checkpoint(
        raw_projection.get("gate_decisions"),
    )
    projection["decision_request_details"] = _decision_request_details_from_checkpoint(
        raw_projection.get("decision_request_details"),
    )
    projection["cleanup_requested_events"] = _cleanup_requested_events_from_checkpoint(
        raw_projection.get("cleanup_requested_events"),
    )
    projection["task_candidates"] = _task_candidates_from_checkpoint(
        raw_projection.get("task_candidates"),
    )
    projection["verifier_verdicts"] = _verifier_verdicts_from_checkpoint(
        raw_projection.get("verifier_verdicts"),
    )
    projection["accepted_output_records_by_node_port"] = _accepted_output_records_from_checkpoint(
        raw_projection.get("accepted_output_records_by_node_port"),
    )
    projection["output_records_by_node_port"] = _output_records_from_checkpoint(
        raw_projection.get("output_records_by_node_port"),
    )
    projection["output_record_payloads"] = _output_payloads_from_checkpoint(
        raw_projection.get("output_record_payloads"),
    )
    projection["callback_idempotency_events"] = _callback_idempotency_events_from_checkpoint(
        raw_projection.get("callback_idempotency_events"),
    )
    projection["environment_failures"] = _environment_failures_from_checkpoint(
        raw_projection.get("environment_failures"),
    )
    projection["file_state_records"] = _file_state_records_from_checkpoint(
        raw_projection.get("file_state_records"),
    )
    projection["recovery_nodes_by_record_id"] = _recovery_nodes_from_checkpoint(
        raw_projection.get("recovery_nodes_by_record_id"),
    )
    projection["latest_routine_snapshot_record"] = _latest_routine_snapshot_from_checkpoint(
        raw_projection.get("latest_routine_snapshot_record"),
    )
    projection["planner_generation_budget"] = _int_from_checkpoint(
        raw_projection.get("planner_generation_budget"),
        default=initial_projection()["planner_generation_budget"],
    )
    projection["planner_successors"] = _string_map_from_checkpoint(
        raw_projection.get("planner_successors"),
    )
    projection["accepted_graph_patches_by_node"] = _string_list_map_from_checkpoint(
        raw_projection.get("accepted_graph_patches_by_node"),
    )
    projection["accepted_no_successor_patches_by_node"] = _string_list_map_from_checkpoint(
        raw_projection.get("accepted_no_successor_patches_by_node"),
    )
    projection["accepted_no_successor_patch_ids_by_node"] = _string_map_from_checkpoint(
        raw_projection.get("accepted_no_successor_patch_ids_by_node"),
    )
    projection["planner_generations"] = _int_map_from_checkpoint(
        raw_projection.get("planner_generations"),
    )
    projection["planner_sessions"] = _string_map_from_checkpoint(
        raw_projection.get("planner_sessions"),
    )
    projection["planner_session_states"] = _string_map_from_checkpoint(
        raw_projection.get("planner_session_states"),
    )
    projection["planner_session_current_nodes"] = _string_map_from_checkpoint(
        raw_projection.get("planner_session_current_nodes"),
    )
    projection["planner_session_carryovers"] = _nullable_string_map_from_checkpoint(
        raw_projection.get("planner_session_carryovers"),
    )
    projection["planner_region_labels"] = _string_map_from_checkpoint(
        raw_projection.get("planner_region_labels"),
    )
    projection["node_creation_payloads"] = _node_creation_payloads_from_checkpoint(
        raw_projection.get("node_creation_payloads"),
    )
    projection["approval_decisions"] = _approval_decisions_from_checkpoint(
        raw_projection.get("approval_decisions"),
    )
    projection["authority_decisions"] = _authority_decisions_from_checkpoint(
        raw_projection.get("authority_decisions"),
    )
    projection["requirement_revisions"] = _requirement_revisions_from_checkpoint(
        raw_projection.get("requirement_revisions"),
    )
    projection["support_evidence"] = _support_evidence_from_checkpoint(
        raw_projection.get("support_evidence"),
    )
    projection["active_requirement_versions"] = _string_map_from_checkpoint(
        raw_projection.get("active_requirement_versions"),
    )
    projection["last_deferred_reasons"] = _string_map_from_checkpoint(
        raw_projection.get("last_deferred_reasons"),
    )
    projection["retry_not_before_by_node"] = _nullable_string_map_from_checkpoint(
        raw_projection.get("retry_not_before_by_node"),
    )
    projection["oversight_decisions"] = _oversight_decisions_from_checkpoint(
        raw_projection.get("oversight_decisions"),
    )
    projection["open_proposal_blockers"] = _final_invariant_blockers_from_checkpoint(
        raw_projection.get("open_proposal_blockers"),
    )
    projection["suspect_node_reasons"] = _string_map_from_checkpoint(
        raw_projection.get("suspect_node_reasons"),
    )
    projection["authority_revision_blockers"] = _final_invariant_blockers_from_checkpoint(
        raw_projection.get("authority_revision_blockers"),
    )
    projection["cleanup_applied_ids"] = _bool_map_from_checkpoint(
        raw_projection.get("cleanup_applied_ids"),
    )
    projection["tokens_by_node"] = _int_map_from_checkpoint(raw_projection.get("tokens_by_node"))
    projection["tokens_by_node_kind"] = _int_map_from_checkpoint(
        raw_projection.get("tokens_by_node_kind")
    )
    projection["latency_ms_by_node_kind"] = _int_map_from_checkpoint(
        raw_projection.get("latency_ms_by_node_kind")
    )
    projection["execution_count_by_node_kind"] = _int_map_from_checkpoint(
        raw_projection.get("execution_count_by_node_kind")
    )
    projection["num_actions_by_node_kind"] = _int_map_from_checkpoint(
        raw_projection.get("num_actions_by_node_kind")
    )
    projection["recorded_node_usage_keys"] = _bool_map_from_checkpoint(
        raw_projection.get("recorded_node_usage_keys")
    )
    return projection


def _nullable_string_from_checkpoint(raw_value: Any) -> str | None:
    return raw_value if isinstance(raw_value, str) else None


def _int_from_checkpoint(raw_value: Any, *, default: int = 0) -> int:
    return raw_value if isinstance(raw_value, int) and not isinstance(raw_value, bool) else default


def _bool_from_checkpoint(raw_value: Any) -> bool:
    return raw_value if isinstance(raw_value, bool) else False


def _string_list_from_checkpoint(raw_values: Any) -> list[str]:
    if not isinstance(raw_values, list):
        return []
    return [value for value in cast(list[Any], raw_values) if isinstance(value, str)]


def _string_map_from_checkpoint(
    raw_map: Any,
    allowed_values: set[str] | None = None,
) -> dict[str, str]:
    if not isinstance(raw_map, dict):
        return {}
    typed: dict[str, str] = {}
    for key, value in cast(dict[Any, Any], raw_map).items():
        if (
            isinstance(key, str)
            and isinstance(value, str)
            and (allowed_values is None or value in allowed_values)
        ):
            typed[key] = value
    return typed


def _nullable_string_map_from_checkpoint(raw_map: Any) -> dict[str, str | None]:
    if not isinstance(raw_map, dict):
        return {}
    typed: dict[str, str | None] = {}
    for key, value in cast(dict[Any, Any], raw_map).items():
        if isinstance(key, str) and (isinstance(value, str) or value is None):
            typed[key] = value
    return typed


def _int_map_from_checkpoint(raw_map: Any) -> dict[str, int]:
    if not isinstance(raw_map, dict):
        return {}
    typed: dict[str, int] = {}
    for key, value in cast(dict[Any, Any], raw_map).items():
        if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool):
            typed[key] = value
    return typed


def _bool_map_from_checkpoint(raw_map: Any) -> dict[str, bool]:
    if not isinstance(raw_map, dict):
        return {}
    typed: dict[str, bool] = {}
    for key, value in cast(dict[Any, Any], raw_map).items():
        if isinstance(key, str) and isinstance(value, bool):
            typed[key] = value
    return typed


def _string_list_map_from_checkpoint(raw_map: Any) -> dict[str, list[str]]:
    if not isinstance(raw_map, dict):
        return {}
    typed: dict[str, list[str]] = {}
    for key, raw_values in cast(dict[Any, Any], raw_map).items():
        if not isinstance(key, str) or not isinstance(raw_values, list):
            continue
        typed[key] = _string_list_from_checkpoint(raw_values)
    return typed


def _dict_map_from_checkpoint(raw_map: Any) -> dict[str, CommandDefinitionProjection]:
    if not isinstance(raw_map, dict):
        return {}
    typed: dict[str, CommandDefinitionProjection] = {}
    for key, value in cast(dict[Any, Any], raw_map).items():
        if isinstance(key, str) and isinstance(value, dict):
            typed[key] = dict(cast(dict[str, Any], value))
    return typed


def _bool_matrix_from_checkpoint(raw_map: Any) -> dict[str, dict[str, bool]]:
    if not isinstance(raw_map, dict):
        return {}
    typed: dict[str, dict[str, bool]] = {}
    for key, raw_values in cast(dict[Any, Any], raw_map).items():
        if not isinstance(key, str) or not isinstance(raw_values, dict):
            continue
        values = _bool_map_from_checkpoint(raw_values)
        if values:
            typed[key] = values
    return typed


def _node_output_ports_from_checkpoint(raw_map: Any) -> dict[str, dict[str, list[str]]]:
    if not isinstance(raw_map, dict):
        return {}
    typed: dict[str, dict[str, list[str]]] = {}
    for node_id, raw_ports in cast(dict[Any, Any], raw_map).items():
        if not isinstance(node_id, str) or not isinstance(raw_ports, dict):
            continue
        ports = _string_list_map_from_checkpoint(raw_ports)
        if ports:
            typed[node_id] = ports
    return typed


_GRAPH_RECORD_SUMMARY_STRING_FIELDS = {
    "record_id",
    "record_type",
    "record_kind",
    "schema",
    "producer_node_id",
    "producer_port",
}


def _record_summaries_from_checkpoint(raw_map: Any) -> dict[str, GraphRecordSummary]:
    if not isinstance(raw_map, dict):
        return {}
    typed: dict[str, GraphRecordSummary] = {}
    for record_id, raw_summary in cast(dict[Any, Any], raw_map).items():
        if not isinstance(record_id, str) or not isinstance(raw_summary, dict):
            continue
        summary: GraphRecordSummary = {}
        for field in _GRAPH_RECORD_SUMMARY_STRING_FIELDS:
            value = cast(dict[str, Any], raw_summary).get(field)
            if isinstance(value, str):
                summary[field] = value
        position = cast(dict[str, Any], raw_summary).get("position")
        if isinstance(position, int) and not isinstance(position, bool):
            summary["position"] = position
        if summary:
            typed[record_id] = summary
    return typed


_FINAL_INVARIANT_BLOCKER_STRING_FIELDS = {
    "kind",
    "reason",
    "node_id",
    "edge_id",
    "from_node_id",
    "to_port",
    "proposal_id",
    "requirement_id",
    "revision_id",
    "task_region_id",
    "state",
    "classification",
    "command_text",
    "stderr_tail",
}


def _final_invariant_blockers_from_checkpoint(raw_map: Any) -> dict[str, FinalInvariantBlocker]:
    if not isinstance(raw_map, dict):
        return {}
    typed: dict[str, FinalInvariantBlocker] = {}
    for blocker_id, raw_blocker in cast(dict[Any, Any], raw_map).items():
        if not isinstance(blocker_id, str) or not isinstance(raw_blocker, dict):
            continue
        blocker: FinalInvariantBlocker = {}
        for field in _FINAL_INVARIANT_BLOCKER_STRING_FIELDS:
            value = cast(dict[str, Any], raw_blocker).get(field)
            if isinstance(value, str):
                blocker[field] = value
        exit_code = cast(dict[str, Any], raw_blocker).get("exit_code")
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            blocker["exit_code"] = exit_code
        support_ids = _string_list_from_checkpoint(
            cast(dict[str, Any], raw_blocker).get("support_ids"),
        )
        if support_ids:
            blocker["support_ids"] = support_ids
        if "kind" in blocker and "reason" in blocker:
            typed[blocker_id] = blocker
    return typed


def _node_resource_claims_from_checkpoint(
    raw_claims_by_node: Any,
) -> dict[str, list[ResourceClaimProjection]]:
    if not isinstance(raw_claims_by_node, dict):
        return {}
    typed: dict[str, list[ResourceClaimProjection]] = {}
    for node_id, raw_claims in cast(dict[Any, Any], raw_claims_by_node).items():
        if not isinstance(node_id, str) or not isinstance(raw_claims, list):
            continue
        claims: list[ResourceClaimProjection] = []
        for raw_claim in cast(list[Any], raw_claims):
            if isinstance(raw_claim, ResourceClaimProjection):
                claim = raw_claim.model_copy(deep=True)
            elif isinstance(raw_claim, dict):
                try:
                    claim = ResourceClaimProjection.model_validate(raw_claim)
                except ValueError:
                    continue
            else:
                continue
            claims.append(claim)
        if claims:
            typed[node_id] = claims
    return typed


def _recovery_nodes_from_checkpoint(
    raw_recoveries_by_record: Any,
) -> dict[
    str,
    list[RecoveryNodeIndexEntry],
]:
    if not isinstance(raw_recoveries_by_record, dict):
        return {}
    typed: dict[str, list[RecoveryNodeIndexEntry]] = {}
    for record_id, raw_recoveries in cast(dict[Any, Any], raw_recoveries_by_record).items():
        if not isinstance(record_id, str) or not isinstance(raw_recoveries, list):
            continue
        recoveries: list[RecoveryNodeIndexEntry] = []
        for raw_recovery in cast(list[Any], raw_recoveries):
            if isinstance(raw_recovery, RecoveryNodeIndexEntry):
                recoveries.append(raw_recovery.model_copy(deep=True))
                continue
            if not isinstance(raw_recovery, dict):
                continue
            try:
                recoveries.append(RecoveryNodeIndexEntry.model_validate(raw_recovery))
            except ValueError:
                continue
        if recoveries:
            typed[record_id] = recoveries
    return typed


def _latest_routine_snapshot_from_checkpoint(raw_record: Any) -> LatestRoutineSnapshotRecord | None:
    if isinstance(raw_record, LatestRoutineSnapshotRecord):
        return raw_record.model_copy(deep=True)
    if not isinstance(raw_record, dict):
        return None
    try:
        record = LatestRoutineSnapshotRecord.model_validate(raw_record)
    except ValueError:
        return None
    if not all(value for value in (record.record_id, record.producer_node_id, record.port)):
        return None
    return record


def _leases_from_checkpoint(raw_leases: Any) -> dict[str, LeaseProjection]:
    if not isinstance(raw_leases, dict):
        return {}
    typed: dict[str, LeaseProjection] = {}
    for lease_id, raw_lease in cast(dict[Any, Any], raw_leases).items():
        if not isinstance(lease_id, str) or not isinstance(raw_lease, dict):
            continue
        lease = _lease_from_payload(cast(dict[str, Any], raw_lease))
        if lease is not None:
            typed[lease_id] = lease
    return typed


def _edges_from_checkpoint(raw_edges: Any) -> dict[str, EdgeProjection]:
    if not isinstance(raw_edges, dict):
        return {}
    typed: dict[str, EdgeProjection] = {}
    for edge_id, raw_edge in cast(dict[Any, Any], raw_edges).items():
        if not isinstance(edge_id, str) or not isinstance(raw_edge, dict):
            continue
        edge = _edge_from_payload(cast(dict[str, Any], raw_edge))
        if edge is not None:
            if edge.edge_id != edge_id:
                continue
            typed[edge_id] = edge
    return typed


def _input_bindings_from_checkpoint(
    raw_bindings: Any,
) -> dict[str, dict[str, InputBindingProjection]]:
    if not isinstance(raw_bindings, dict):
        return {}
    typed: dict[str, dict[str, InputBindingProjection]] = {}
    for node_id, raw_ports in cast(dict[Any, Any], raw_bindings).items():
        if not isinstance(node_id, str) or not isinstance(raw_ports, dict):
            continue
        ports: dict[str, InputBindingProjection] = {}
        for port, raw_binding in cast(dict[Any, Any], raw_ports).items():
            if not isinstance(port, str) or not isinstance(raw_binding, dict):
                continue
            binding = _input_binding_from_payload(cast(dict[str, Any], raw_binding))
            if binding is not None:
                if binding.to_node_id != node_id or binding.to_port != port:
                    continue
                ports[port] = binding
        if ports:
            typed[node_id] = ports
    return typed


def _invalid_test_blocks_from_checkpoint(
    raw_blocks: Any,
) -> dict[str, InvalidTestBlockProjection]:
    if not isinstance(raw_blocks, dict):
        return {}
    typed: dict[str, InvalidTestBlockProjection] = {}
    for task_region_id, raw_block in cast(dict[Any, Any], raw_blocks).items():
        if not isinstance(task_region_id, str) or not isinstance(raw_block, dict):
            continue
        block = _invalid_test_block_from_payload(cast(dict[str, Any], raw_block))
        if block is not None:
            typed[task_region_id] = block
    return typed


def _decision_request_details_from_checkpoint(
    raw_details: Any,
) -> dict[str, PendingGateDecisionProjection]:
    if not isinstance(raw_details, dict):
        return {}
    typed: dict[str, PendingGateDecisionProjection] = {}
    for node_id, raw_detail in cast(dict[Any, Any], raw_details).items():
        if not isinstance(node_id, str) or not isinstance(raw_detail, dict):
            continue
        detail = _pending_gate_decision_from_payload(cast(dict[str, Any], raw_detail))
        if detail is not None:
            typed[node_id] = detail
    return typed


def _cleanup_requested_events_from_checkpoint(
    raw_events: Any,
) -> dict[str, CleanupRequestedProjection]:
    if not isinstance(raw_events, dict):
        return {}
    typed: dict[str, CleanupRequestedProjection] = {}
    for cleanup_id, raw_cleanup in cast(dict[Any, Any], raw_events).items():
        if not isinstance(cleanup_id, str) or not isinstance(raw_cleanup, dict):
            continue
        cleanup = _cleanup_requested_from_payload(cast(dict[str, Any], raw_cleanup))
        if cleanup is not None:
            typed[cleanup_id] = cleanup
    return typed


def _callback_idempotency_events_from_checkpoint(
    raw_events: Any,
) -> dict[str, CallbackIdempotencyEvent]:
    if not isinstance(raw_events, dict):
        return {}
    typed: dict[str, CallbackIdempotencyEvent] = {}
    for key, raw_event in cast(dict[Any, Any], raw_events).items():
        if not isinstance(key, str) or not isinstance(raw_event, dict):
            continue
        event = _callback_idempotency_event_from_payload(cast(dict[str, Any], raw_event))
        if event is not None:
            typed[key] = event
    return typed


def _environment_failures_from_checkpoint(
    raw_failures: Any,
) -> dict[str, EnvironmentFailureProjection]:
    if not isinstance(raw_failures, dict):
        return {}
    typed: dict[str, EnvironmentFailureProjection] = {}
    for task_region_id, raw_failure in cast(dict[Any, Any], raw_failures).items():
        if not isinstance(task_region_id, str) or not isinstance(raw_failure, dict):
            continue
        failure = _environment_failure_from_payload(cast(dict[str, Any], raw_failure))
        if failure is not None:
            typed[task_region_id] = failure
    return typed


def _node_creation_payloads_from_checkpoint(
    raw_payloads: Any,
) -> dict[str, NodeCreationProjection]:
    if not isinstance(raw_payloads, dict):
        return {}
    typed: dict[str, NodeCreationProjection] = {}
    for node_id, raw_payload in cast(dict[Any, Any], raw_payloads).items():
        if not isinstance(node_id, str) or not isinstance(raw_payload, dict):
            continue
        payload = _node_creation_from_payload(cast(dict[str, Any], raw_payload))
        if payload is not None:
            typed[node_id] = payload
    return typed


def _approval_decisions_from_checkpoint(
    raw_payloads: Any,
) -> dict[str, ApprovalDecisionProjection]:
    if not isinstance(raw_payloads, dict):
        return {}
    typed: dict[str, ApprovalDecisionProjection] = {}
    for node_id, raw_payload in cast(dict[Any, Any], raw_payloads).items():
        if not isinstance(node_id, str) or not isinstance(raw_payload, dict):
            continue
        payload = _approval_decision_from_payload(cast(dict[str, Any], raw_payload))
        if payload is not None:
            typed[node_id] = payload
    return typed


def _authority_decisions_from_checkpoint(
    raw_payloads: Any,
) -> dict[str, AuthorityDecisionProjection]:
    if not isinstance(raw_payloads, dict):
        return {}
    typed: dict[str, AuthorityDecisionProjection] = {}
    for node_id, raw_payload in cast(dict[Any, Any], raw_payloads).items():
        if not isinstance(node_id, str) or not isinstance(raw_payload, dict):
            continue
        payload = _authority_decision_from_payload(cast(dict[str, Any], raw_payload))
        if payload is not None:
            typed[node_id] = payload
    return typed


def _requirement_revisions_from_checkpoint(
    raw_payloads: Any,
) -> dict[str, RequirementRevisionProjection]:
    if not isinstance(raw_payloads, dict):
        return {}
    typed: dict[str, RequirementRevisionProjection] = {}
    for version_id, raw_payload in cast(dict[Any, Any], raw_payloads).items():
        if not isinstance(version_id, str) or not isinstance(raw_payload, dict):
            continue
        payload = _requirement_revision_from_payload(cast(dict[str, Any], raw_payload))
        if payload is not None:
            typed[version_id] = payload
    return typed


def _support_evidence_from_checkpoint(
    raw_payloads: Any,
) -> dict[str, SupportEvidenceProjection]:
    if not isinstance(raw_payloads, dict):
        return {}
    typed: dict[str, SupportEvidenceProjection] = {}
    for support_id, raw_payload in cast(dict[Any, Any], raw_payloads).items():
        if not isinstance(support_id, str) or not isinstance(raw_payload, dict):
            continue
        payload = _support_evidence_from_payload(cast(dict[str, Any], raw_payload))
        if payload is not None:
            typed[support_id] = payload
    return typed


def _oversight_decisions_from_checkpoint(
    raw_payloads: Any,
) -> dict[str, OversightDecisionProjection]:
    if not isinstance(raw_payloads, dict):
        return {}
    typed: dict[str, OversightDecisionProjection] = {}
    for node_id, raw_payload in cast(dict[Any, Any], raw_payloads).items():
        if not isinstance(node_id, str) or not isinstance(raw_payload, dict):
            continue
        payload = _oversight_decision_from_payload(cast(dict[str, Any], raw_payload))
        if payload is not None:
            canonical = typed.get(payload.node_id, payload)
            typed[node_id] = canonical
            if payload.appeal_node_id is not None:
                typed[payload.appeal_node_id] = canonical
    return typed


def _file_state_records_from_checkpoint(raw_records: Any) -> dict[str, FileStateRecord]:
    if not isinstance(raw_records, dict):
        return {}
    typed: dict[str, FileStateRecord] = {}
    for record_id, raw_record in cast(dict[Any, Any], raw_records).items():
        if not isinstance(record_id, str) or not isinstance(raw_record, dict):
            continue
        record = _file_state_record_from_payload(cast(dict[str, Any], raw_record))
        if record is not None:
            typed[record_id] = record
    return typed


def _lease_from_payload(payload: dict[str, Any]) -> LeaseProjection | None:
    try:
        return LeaseProjection.model_validate(payload)
    except ValueError:
        return None


def _lease_granted_from_payload(payload: dict[str, Any]) -> LeaseGrantedPayload | None:
    try:
        return LeaseGrantedPayload.model_validate(payload)
    except ValueError:
        return None


def _lease_renewed_from_payload(payload: dict[str, Any]) -> LeaseRenewedPayload | None:
    try:
        return LeaseRenewedPayload.model_validate(payload)
    except ValueError:
        return None


def _lease_terminal_from_event(
    event_type: str,
    payload: dict[str, Any],
) -> (
    LeaseReleasedPayload | LeaseRevokedPayload | LeaseExpiredPayload | LeaseSuspendedPayload | None
):
    model: (
        type[LeaseReleasedPayload]
        | type[LeaseRevokedPayload]
        | type[LeaseExpiredPayload]
        | type[LeaseSuspendedPayload]
        | None
    )
    if event_type == "lease_released":
        model = LeaseReleasedPayload
    elif event_type == "lease_revoked":
        model = LeaseRevokedPayload
    elif event_type == "lease_expired":
        model = LeaseExpiredPayload
    elif event_type == "lease_suspended":
        model = LeaseSuspendedPayload
    else:
        model = None
    if model is None:
        return None
    try:
        return model.model_validate(payload)
    except ValueError:
        return None


def _edge_from_payload(payload: dict[str, Any]) -> EdgeProjection | None:
    try:
        return EdgeProjection.model_validate(payload)
    except ValueError:
        return None


def _input_binding_from_payload(payload: dict[str, Any]) -> InputBindingProjection | None:
    try:
        return InputBindingProjection.model_validate(payload)
    except ValueError:
        return None


def _invalid_test_block_from_payload(
    payload: dict[str, Any],
) -> InvalidTestBlockProjection | None:
    try:
        return InvalidTestBlockProjection.model_validate(payload)
    except ValueError:
        return None


def _pending_gate_decision_from_payload(
    payload: dict[str, Any],
) -> PendingGateDecisionProjection | None:
    try:
        return PendingGateDecisionProjection.model_validate(payload)
    except ValueError:
        return None


def _cleanup_requested_from_payload(payload: dict[str, Any]) -> CleanupRequestedProjection | None:
    try:
        return CleanupRequestedProjection.model_validate(payload)
    except ValueError:
        return None


def _cleanup_requested_payload_from_event(event: EventEnvelope) -> CleanupRequestedPayload | None:
    try:
        return CleanupRequestedPayload.model_validate(event.payload)
    except ValueError:
        return None


def _cleanup_applied_payload_from_event(event: EventEnvelope) -> CleanupAppliedPayload | None:
    try:
        return CleanupAppliedPayload.model_validate(event.payload)
    except ValueError:
        return None


def _planner_session_state_changed_payload_from_event(
    event: EventEnvelope,
) -> PlannerSessionStateChangedPayload | None:
    try:
        return PlannerSessionStateChangedPayload.model_validate(event.payload)
    except ValueError:
        return None


def _graph_patch_accepted_payload_from_event(
    event: EventEnvelope,
) -> GraphPatchAcceptedPayload | None:
    try:
        return GraphPatchAcceptedPayload.model_validate(event.payload)
    except ValueError:
        return None


def _graph_patch_rejected_payload_from_event(
    event: EventEnvelope,
) -> GraphPatchRejectedPayload | None:
    try:
        return GraphPatchRejectedPayload.model_validate(event.payload)
    except ValueError:
        return None


def _graph_patch_payload_for_event(event: EventEnvelope) -> dict[str, Any] | None:
    if event.event_type == "graph_patch_accepted":
        payload = _graph_patch_accepted_payload_from_event(event)
    elif event.event_type == "graph_patch_rejected":
        payload = _graph_patch_rejected_payload_from_event(event)
    else:
        payload = None
    if payload is None:
        return None
    return payload.model_dump(mode="json")


def _cleanup_requested_from_event(event: EventEnvelope) -> CleanupRequestedProjection | None:
    payload = _cleanup_requested_payload_from_event(event)
    if payload is None:
        return None
    return _cleanup_requested_from_payload(
        {
            **payload.model_dump(mode="json"),
            "position": event.position,
        }
    )


def _node_creation_from_event(event: EventEnvelope) -> NodeCreationProjection | None:
    event_payload = _node_created_payload_from_event(event)
    if event_payload is None:
        return None
    projection_payload = event_payload.model_dump(mode="json")
    authority = event_payload.authority
    if authority is not None:
        if "resource_claims" not in event_payload.model_fields_set:
            projection_payload["resource_claims"] = [
                claim.model_dump(mode="json") for claim in authority.resource_claims
            ]
        if "allowed_actions" not in event_payload.model_fields_set:
            projection_payload["allowed_actions"] = authority.allowed_actions
        if "preconditions" not in event_payload.model_fields_set:
            projection_payload["preconditions"] = authority.preconditions
    return _node_creation_from_payload(
        {
            **projection_payload,
            "position": event.position,
        }
    )


def _node_created_payload_from_event(event: EventEnvelope) -> NodeCreatedPayload | None:
    try:
        return NodeCreatedPayload.model_validate(event.payload)
    except ValueError:
        return None


def _node_creation_from_payload(payload: dict[str, Any]) -> NodeCreationProjection | None:
    try:
        return NodeCreationProjection.model_validate(payload)
    except ValueError:
        return None


def _verification_results_from_checkpoint(
    raw_results: Any,
) -> dict[str, VerificationResultProjection]:
    if not isinstance(raw_results, dict):
        return {}
    typed: dict[str, VerificationResultProjection] = {}
    for record_id, raw_result in cast(dict[Any, Any], raw_results).items():
        if not isinstance(record_id, str) or not isinstance(raw_result, dict):
            continue
        try:
            result = VerificationResultProjection.model_validate(raw_result)
        except ValueError:
            continue
        typed[record_id] = result
    return typed


def _check_results_from_checkpoint(raw_results: Any) -> dict[str, CheckResultProjection]:
    if not isinstance(raw_results, dict):
        return {}
    typed: dict[str, CheckResultProjection] = {}
    for node_id, raw_result in cast(dict[Any, Any], raw_results).items():
        if not isinstance(node_id, str) or not isinstance(raw_result, dict):
            continue
        try:
            result = CheckResultProjection.model_validate(raw_result)
        except ValueError:
            continue
        typed[node_id] = result
    return typed


def _task_candidates_from_checkpoint(raw_candidates: Any) -> dict[str, list[CandidateProjection]]:
    if not isinstance(raw_candidates, dict):
        return {}
    typed: dict[str, list[CandidateProjection]] = {}
    for task_region_id, raw_task_candidates in cast(dict[Any, Any], raw_candidates).items():
        if not isinstance(task_region_id, str) or not isinstance(raw_task_candidates, list):
            continue
        candidates: list[CandidateProjection] = []
        for raw_candidate in cast(list[Any], raw_task_candidates):
            if not isinstance(raw_candidate, dict):
                continue
            try:
                candidate = CandidateProjection.model_validate(raw_candidate)
            except ValueError:
                continue
            candidates.append(candidate)
        typed[task_region_id] = candidates
    return typed


def _verifier_verdicts_from_checkpoint(
    raw_verdicts: Any,
) -> dict[str, VerifierVerdictProjection]:
    if not isinstance(raw_verdicts, dict):
        return {}
    typed: dict[str, VerifierVerdictProjection] = {}
    for candidate_id, raw_verdict in cast(dict[Any, Any], raw_verdicts).items():
        if not isinstance(candidate_id, str) or not isinstance(raw_verdict, dict):
            continue
        try:
            verdict = VerifierVerdictProjection.model_validate(raw_verdict)
        except ValueError:
            continue
        typed[candidate_id] = verdict
    return typed


def _accepted_output_records_from_checkpoint(
    raw_ports_by_node: Any,
) -> dict[str, dict[str, list[AcceptedOutputRecord]]]:
    if not isinstance(raw_ports_by_node, dict):
        return {}
    typed: dict[str, dict[str, list[AcceptedOutputRecord]]] = {}
    for node_id, raw_ports in cast(dict[Any, Any], raw_ports_by_node).items():
        if not isinstance(node_id, str) or not isinstance(raw_ports, dict):
            continue
        ports: dict[str, list[AcceptedOutputRecord]] = {}
        for port, raw_records in cast(dict[Any, Any], raw_ports).items():
            if not isinstance(port, str) or not isinstance(raw_records, list):
                continue
            records: list[AcceptedOutputRecord] = []
            for raw_record in cast(list[Any], raw_records):
                if not isinstance(raw_record, dict):
                    continue
                record = cast(dict[str, Any], raw_record)
                record_id = _checkpoint_record_id(record)
                payload = _checkpoint_output_record_payload(record.get("payload"))
                if record_id is not None and payload is not None:
                    records.append({"record_id": record_id, "payload": payload})
            ports[port] = records
        typed[node_id] = ports
    return typed


def _output_records_from_checkpoint(
    raw_ports_by_node: Any,
) -> dict[str, dict[str, list[AcceptedOutputRecordPayload]]]:
    if not isinstance(raw_ports_by_node, dict):
        return {}
    typed: dict[str, dict[str, list[AcceptedOutputRecordPayload]]] = {}
    for node_id, raw_ports in cast(dict[Any, Any], raw_ports_by_node).items():
        if not isinstance(node_id, str) or not isinstance(raw_ports, dict):
            continue
        ports: dict[str, list[AcceptedOutputRecordPayload]] = {}
        for port, raw_records in cast(dict[Any, Any], raw_ports).items():
            if not isinstance(port, str) or not isinstance(raw_records, list):
                continue
            records = [
                payload
                for raw_payload in cast(list[Any], raw_records)
                if (payload := _checkpoint_output_record_payload(raw_payload)) is not None
            ]
            ports[port] = records
        typed[node_id] = ports
    return typed


def _output_payloads_from_checkpoint(raw_payloads: Any) -> dict[str, AcceptedOutputRecordPayload]:
    if not isinstance(raw_payloads, dict):
        return {}
    typed: dict[str, AcceptedOutputRecordPayload] = {}
    for record_id, raw_payload in cast(dict[Any, Any], raw_payloads).items():
        if not isinstance(record_id, str):
            continue
        payload = _checkpoint_output_record_payload(raw_payload)
        if payload is not None:
            typed[record_id] = payload
    return typed


def _checkpoint_record_id(raw_record: dict[str, Any]) -> str | None:
    record_id = raw_record.get("record_id")
    return record_id if isinstance(record_id, str) else None


def _checkpoint_output_record_payload(raw_payload: Any) -> AcceptedOutputRecordPayload | None:
    if not isinstance(raw_payload, dict):
        return None
    return _parse_output_record_payload(cast(dict[str, Any], raw_payload))


def _copy_lease_projection(value: Any) -> LeaseProjection | None:
    if isinstance(value, LeaseProjection):
        return value.model_copy(deep=True)
    if isinstance(value, dict):
        return _lease_from_payload(cast(dict[str, Any], value))
    return None


def _copy_edge_projection(value: Any) -> EdgeProjection | None:
    if isinstance(value, EdgeProjection):
        return value.model_copy(deep=True)
    if isinstance(value, dict):
        return _edge_from_payload(cast(dict[str, Any], value))
    return None


def _copy_input_binding_projection(value: Any) -> InputBindingProjection | None:
    if isinstance(value, InputBindingProjection):
        return value.model_copy(deep=True)
    if isinstance(value, dict):
        return _input_binding_from_payload(cast(dict[str, Any], value))
    return None


def _copy_invalid_test_block_projection(value: Any) -> InvalidTestBlockProjection | None:
    if isinstance(value, InvalidTestBlockProjection):
        return value.model_copy(deep=True)
    if isinstance(value, dict):
        return _invalid_test_block_from_payload(cast(dict[str, Any], value))
    return None


def _copy_pending_gate_decision_projection(value: Any) -> PendingGateDecisionProjection | None:
    if isinstance(value, PendingGateDecisionProjection):
        return value.model_copy(deep=True)
    if isinstance(value, dict):
        return _pending_gate_decision_from_payload(cast(dict[str, Any], value))
    return None


def _copy_cleanup_requested_projection(value: Any) -> CleanupRequestedProjection | None:
    if isinstance(value, CleanupRequestedProjection):
        return value.model_copy(deep=True)
    if isinstance(value, dict):
        return _cleanup_requested_from_payload(cast(dict[str, Any], value))
    return None


def _lease_payload(lease: LeaseProjection | None, lease_id: str) -> dict[str, Any]:
    if lease is None:
        return {"lease_id": lease_id}
    return lease.model_dump(mode="json")


def _invalid_test_block_payload(block: InvalidTestBlockProjection | None) -> dict[str, Any]:
    if block is None:
        return {}
    return block.model_dump(mode="json")


def _pending_gate_decision_payload(
    details: PendingGateDecisionProjection | None,
) -> PendingGateDecision:
    if details is None:
        return {}
    return cast(PendingGateDecision, details.model_dump(mode="json"))


def _clone_projection(state: GraphProjection) -> GraphProjection:
    next_state: GraphProjection = {
        "run_state": state["run_state"],
        "node_states": dict(state["node_states"]),
        "task_states": dict(state["task_states"]),
        "leases": {
            lease_id: lease_copy
            for lease_id, lease in state["leases"].items()
            if (lease_copy := _copy_lease_projection(lease)) is not None
        },
        "ready_nodes": list(state["ready_nodes"]),
        "node_kinds": dict(state["node_kinds"]),
        "node_roles": dict(state.get("node_roles", {})),
        "node_creation_positions": dict(state.get("node_creation_positions", {})),
        "node_task_regions": dict(state["node_task_regions"]),
        "node_attempts": dict(state["node_attempts"]),
        "node_candidates": dict(state["node_candidates"]),
        "node_failed_candidates": dict(state["node_failed_candidates"]),
        "node_resource_claims": {
            node_id: [claim.model_copy(deep=True) for claim in claims]
            for node_id, claims in state["node_resource_claims"].items()
        },
        "node_allowed_actions": {
            node_id: list(actions) for node_id, actions in state["node_allowed_actions"].items()
        },
        "node_preconditions": {
            node_id: list(preconditions)
            for node_id, preconditions in state["node_preconditions"].items()
        },
        "node_command_definitions": dict(state["node_command_definitions"]),
        "node_output_ports": {
            node_id: {port: list(record_ids) for port, record_ids in ports.items()}
            for node_id, ports in state.get("node_output_ports", {}).items()
        },
        "accepted_output_records_by_node_port": {
            node_id: {
                port: [
                    {
                        "record_id": record["record_id"],
                        "payload": _copy_output_record_payload(record["payload"]),
                    }
                    for record in records
                ]
                for port, records in ports.items()
            }
            for node_id, ports in state.get("accepted_output_records_by_node_port", {}).items()
        },
        "accepted_record_summaries_by_id": {
            record_id: cast(GraphRecordSummary, dict(summary))
            for record_id, summary in state.get("accepted_record_summaries_by_id", {}).items()
        },
        "output_records_by_node_port": {
            node_id: {
                port: [_copy_output_record_payload(record) for record in records]
                for port, records in ports.items()
            }
            for node_id, ports in state.get("output_records_by_node_port", {}).items()
        },
        "edges": {
            edge_id: edge_copy
            for edge_id, edge in state["edges"].items()
            if (edge_copy := _copy_edge_projection(edge)) is not None
        },
        "input_bindings": {
            node_id: {
                port: binding_copy
                for port, binding in ports.items()
                if (binding_copy := _copy_input_binding_projection(binding)) is not None
            }
            for node_id, ports in state["input_bindings"].items()
        },
        "node_pending_appeals": dict(state["node_pending_appeals"]),
        "node_gate_decisions": dict(state["node_gate_decisions"]),
        "task_candidates": {
            task_region_id: [candidate.model_copy(deep=True) for candidate in candidates]
            for task_region_id, candidates in state["task_candidates"].items()
        },
        "verifier_verdicts": {
            candidate_id: verdict.model_copy(deep=True)
            for candidate_id, verdict in state["verifier_verdicts"].items()
        },
        "completion_decision_passed": state.get("completion_decision_passed", False),
        "passed_verification_results_by_record_id": {
            record_id: result.model_copy(deep=True)
            for record_id, result in state.get(
                "passed_verification_results_by_record_id",
                {},
            ).items()
        },
        "failed_verification_results_by_record_id": {
            record_id: result.model_copy(deep=True)
            for record_id, result in state.get(
                "failed_verification_results_by_record_id", {}
            ).items()
        },
        "failed_verification_candidate_ids": dict(
            state.get("failed_verification_candidate_ids", {})
        ),
        "passed_verification_candidate_ids": list(
            state.get("passed_verification_candidate_ids", [])
        ),
        "recovery_nodes_by_record_id": {
            record_id: [recovery.model_copy(deep=True) for recovery in recoveries]
            for record_id, recoveries in state.get("recovery_nodes_by_record_id", {}).items()
        },
        "check_results": {
            node_id: result.model_copy(deep=True)
            for node_id, result in state.get("check_results", {}).items()
        },
        "invalid_test_blocks": {
            task_region_id: block_copy
            for task_region_id, block in state["invalid_test_blocks"].items()
            if (block_copy := _copy_invalid_test_block_projection(block)) is not None
        },
        "configured_gates": {
            task_region_id: dict(gates)
            for task_region_id, gates in state["configured_gates"].items()
        },
        "gate_decisions": {
            task_region_id: dict(decisions)
            for task_region_id, decisions in state["gate_decisions"].items()
        },
        "environment_failures": {
            task_region_id: failure.model_copy(deep=True)
            for task_region_id, failure in state["environment_failures"].items()
        },
        "file_state_records": {
            record_id: record.model_copy(deep=True)
            for record_id, record in state.get("file_state_records", {}).items()
        },
        "planner_generation_budget": state.get("planner_generation_budget", 8),
        "planner_successors": dict(state.get("planner_successors", {})),
        "accepted_graph_patches_by_node": {
            node_id: list(patch_ids)
            for node_id, patch_ids in state.get("accepted_graph_patches_by_node", {}).items()
        },
        "accepted_no_successor_patches_by_node": {
            node_id: list(patch_ids)
            for node_id, patch_ids in state.get("accepted_no_successor_patches_by_node", {}).items()
        },
        "accepted_no_successor_patch_ids_by_node": dict(
            state.get("accepted_no_successor_patch_ids_by_node", {})
        ),
        "latest_routine_snapshot_record": _copy_latest_routine_snapshot_record(state),
        "planner_generations": dict(state.get("planner_generations", {})),
        "planner_sessions": dict(state.get("planner_sessions", {})),
        "planner_session_states": dict(state.get("planner_session_states", {})),
        "planner_session_current_nodes": dict(state.get("planner_session_current_nodes", {})),
        "planner_session_carryovers": dict(state.get("planner_session_carryovers", {})),
        "planner_region_labels": dict(state.get("planner_region_labels", {})),
        "requirement_revisions": {
            version_id: revision.model_copy(deep=True)
            for version_id, revision in state.get("requirement_revisions", {}).items()
        },
        "active_requirement_versions": dict(state.get("active_requirement_versions", {})),
        "support_evidence": {
            support_id: support.model_copy(deep=True)
            for support_id, support in state.get("support_evidence", {}).items()
        },
        "last_deferred_reasons": dict(state.get("last_deferred_reasons", {})),
        "retry_not_before_by_node": dict(state.get("retry_not_before_by_node", {})),
        "node_creation_payloads": {
            node_id: payload.model_copy(deep=True)
            for node_id, payload in state.get("node_creation_payloads", {}).items()
        },
        "output_record_payloads": {
            record_id: _copy_output_record_payload(payload)
            for record_id, payload in state.get("output_record_payloads", {}).items()
        },
        "approval_decisions": {
            node_id: payload.model_copy(deep=True)
            for node_id, payload in state.get("approval_decisions", {}).items()
        },
        "authority_decisions": {
            node_id: payload.model_copy(deep=True)
            for node_id, payload in state.get("authority_decisions", {}).items()
        },
        "oversight_decisions": {
            node_id: payload.model_copy(deep=True)
            for node_id, payload in state.get("oversight_decisions", {}).items()
        },
        "decision_request_details": {
            node_id: details_copy
            for node_id, details in state.get("decision_request_details", {}).items()
            if (details_copy := _copy_pending_gate_decision_projection(details)) is not None
        },
        "callback_idempotency_events": {
            key: event.model_copy(deep=True)
            for key, event in state.get("callback_idempotency_events", {}).items()
        },
        "open_proposal_blockers": {
            proposal_id: cast(FinalInvariantBlocker, dict(blocker))
            for proposal_id, blocker in state.get("open_proposal_blockers", {}).items()
        },
        "suspect_node_reasons": dict(state.get("suspect_node_reasons", {})),
        "authority_revision_blockers": {
            revision_id: cast(FinalInvariantBlocker, dict(blocker))
            for revision_id, blocker in state.get("authority_revision_blockers", {}).items()
        },
        "cleanup_requested_events": {
            cleanup_id: cleanup_event_copy
            for cleanup_id, cleanup_event in state.get("cleanup_requested_events", {}).items()
            if (cleanup_event_copy := _copy_cleanup_requested_projection(cleanup_event)) is not None
        },
        "cleanup_applied_ids": dict(state.get("cleanup_applied_ids", {})),
        "tokens_by_node": dict(state.get("tokens_by_node", {})),
        "tokens_by_node_kind": dict(state.get("tokens_by_node_kind", {})),
        "latency_ms_by_node_kind": dict(state.get("latency_ms_by_node_kind", {})),
        "execution_count_by_node_kind": dict(state.get("execution_count_by_node_kind", {})),
        "num_actions_by_node_kind": dict(state.get("num_actions_by_node_kind", {})),
        "recorded_node_usage_keys": dict(state.get("recorded_node_usage_keys", {})),
    }
    return next_state


def reduce_event(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    next_state = _clone_projection(state)

    if event.event_type == "run_lifecycle_changed":
        lifecycle_payload = RunLifecycleChangedPayload.model_validate(event.payload)
        next_state["run_state"] = lifecycle_payload.to_state
    elif event.event_type == "node_created":
        typed_node_payload = _node_created_payload_from_event(event)
        node_payload = _node_creation_from_event(event)
        if node_payload is not None and typed_node_payload is not None:
            prior_payload = next_state["node_creation_payloads"].get(node_payload.node_id)
            if prior_payload is not None and prior_payload.max_attempts is not None:
                node_payload = node_payload.model_copy(
                    update={"max_attempts": prior_payload.max_attempts}
                )
            node_id = node_payload.node_id
            kind = node_payload.kind
            role = node_payload.role
            node_state = node_payload.state
            task_region_id = node_payload.task_region_id
            attempt_number = node_payload.attempt_number
            candidate_id = node_payload.candidate_id
            if node_state is not None:
                next_state["node_states"][node_id] = node_state
            next_state["node_creation_positions"].setdefault(node_id, event.position)
            next_state["node_creation_payloads"][node_id] = node_payload
            _record_recovery_node(next_state, typed_node_payload)
            if kind == "root":
                budget = node_payload.planner_generation_budget
                if isinstance(budget, int) and not isinstance(budget, bool) and budget >= 0:
                    next_state["planner_generation_budget"] = budget
            if kind is not None:
                next_state["node_kinds"][node_id] = kind
            if role is not None:
                next_state["node_roles"][node_id] = role
            if kind == "planner" and role == "planner":
                generation_index = node_payload.generation_index
                if isinstance(generation_index, int) and not isinstance(generation_index, bool):
                    next_state["planner_generations"][node_id] = generation_index
                region_label = node_payload.region_label
                if region_label is not None:
                    next_state["planner_region_labels"][node_id] = region_label
                session_id = node_payload.session_id
                if session_id is not None:
                    next_state["planner_sessions"][node_id] = session_id
                    next_state["planner_session_states"].setdefault(session_id, "detached")
                    next_state["planner_session_carryovers"].setdefault(session_id, None)
            if task_region_id is not None:
                next_state["node_task_regions"][node_id] = task_region_id
            if attempt_number is not None:
                next_state["node_attempts"][node_id] = attempt_number
            if candidate_id is not None:
                next_state["node_candidates"][node_id] = candidate_id
            failed_candidate_id = node_payload.failed_candidate_id
            if failed_candidate_id is not None:
                next_state["node_failed_candidates"][node_id] = failed_candidate_id
            resource_claims = node_payload.resource_claims
            if resource_claims:
                next_state["node_resource_claims"][node_id] = resource_claims
            allowed_actions = node_payload.allowed_actions
            if allowed_actions:
                next_state["node_allowed_actions"][node_id] = allowed_actions
            preconditions = list(node_payload.preconditions)
            if kind == "check" and "has_command_definition" not in preconditions:
                preconditions.append("has_command_definition")
            if preconditions:
                next_state["node_preconditions"][node_id] = preconditions
            command_definition = _command_definition_for_node_creation(node_payload)
            if command_definition is not None:
                next_state["node_command_definitions"][node_id] = command_definition
            if kind == "gate" and task_region_id is not None:
                next_state["configured_gates"].setdefault(task_region_id, {})[node_id] = True
    elif event.event_type == "node_state_changed":
        payload = NodeStateChangedPayload.model_validate(event.payload)
        node_id = payload.node_id
        new_state = payload.new_state
        next_state["node_states"][node_id] = new_state
        attempt_number = payload.attempt_number
        if attempt_number is not None:
            next_state["node_attempts"][node_id] = attempt_number
    elif event.event_type == "node_usage_recorded":
        usage = NodeUsageRecordedPayload.model_validate(event.payload)
        if usage.usage_key not in next_state["recorded_node_usage_keys"]:
            next_state["recorded_node_usage_keys"][usage.usage_key] = True
            tokens = usage.gen_ai_usage_input_tokens + usage.gen_ai_usage_output_tokens
            next_state["tokens_by_node"][usage.node_id] = (
                next_state["tokens_by_node"].get(usage.node_id, 0) + tokens
            )
            next_state["tokens_by_node_kind"][usage.node_kind] = (
                next_state["tokens_by_node_kind"].get(usage.node_kind, 0) + tokens
            )
            if usage.usage_index == 0:
                next_state["latency_ms_by_node_kind"][usage.node_kind] = (
                    next_state["latency_ms_by_node_kind"].get(usage.node_kind, 0) + usage.latency_ms
                )
                next_state["execution_count_by_node_kind"][usage.node_kind] = (
                    next_state["execution_count_by_node_kind"].get(usage.node_kind, 0) + 1
                )
                next_state["num_actions_by_node_kind"][usage.node_kind] = (
                    next_state["num_actions_by_node_kind"].get(usage.node_kind, 0)
                    + usage.num_actions
                )
    elif event.event_type == "node_retired":
        node_id = NodeRetiredPayload.model_validate(event.payload).node_id
        next_state["node_states"][node_id] = "retired"
    elif event.event_type == "edge_created":
        _record_edge(next_state, event)
    elif event.event_type == "input_bound":
        try:
            input_bound_payload = InputBoundPayload.model_validate(event.payload)
        except ValueError:
            return next_state
        _record_input_binding(next_state, input_bound_payload)
    elif event.event_type == "lease_granted":
        granted_payload = _lease_granted_from_payload(event.payload)
        if granted_payload is not None:
            lease_id = granted_payload.lease_id
            node_id = granted_payload.node_id
            lease_payload: dict[str, Any] = {
                "lease_id": lease_id,
                "node_id": node_id,
                "state": "active",
            }
            for key in ("generation", "expires_at", "execution_id", "base_snapshot_id"):
                value = getattr(granted_payload, key)
                if value is not None:
                    lease_payload[key] = value
            session_id = granted_payload.session_id
            if session_id is not None:
                lease_payload["session_id"] = session_id
                next_state["planner_sessions"][node_id] = session_id
            task_region_id = granted_payload.task_region_id or next_state["node_task_regions"].get(
                node_id
            )
            if task_region_id is not None:
                lease_payload["task_region_id"] = task_region_id
            kind = granted_payload.kind
            if kind is not None:
                lease_payload["kind"] = kind
            elif node_id in next_state["node_kinds"]:
                lease_payload["kind"] = next_state["node_kinds"][node_id]
            resource_claims = granted_payload.resource_claims
            if not resource_claims:
                resource_claims = next_state["node_resource_claims"].get(node_id, [])
            if resource_claims:
                lease_payload["resource_claims"] = resource_claims
            lease = _lease_from_payload(lease_payload)
            if lease is not None:
                next_state["leases"][lease_id] = lease
    elif event.event_type == "session_state_changed":
        payload = _planner_session_state_changed_payload_from_event(event)
        if payload is not None and payload.session_id is not None and payload.state is not None:
            session_id = payload.session_id
            session_state = payload.state
            next_state["planner_session_states"][session_id] = session_state
            if session_state == "attached" and payload.node_id is not None:
                next_state["planner_session_current_nodes"][session_id] = payload.node_id
            elif session_state in {"suspended", "detached", "dead"}:
                next_state["planner_session_current_nodes"].pop(session_id, None)
            if payload.carryover_record_id is not None:
                next_state["planner_session_carryovers"][session_id] = payload.carryover_record_id
            elif (
                "carryover_record_id" in event.payload
                and "carryover_record_id" in payload.model_fields_set
            ):
                next_state["planner_session_carryovers"][session_id] = None
    elif event.event_type in {
        "lease_suspended",
        "lease_revoked",
        "lease_expired",
        "lease_released",
    }:
        terminal_payload = _lease_terminal_from_event(event.event_type, event.payload)
        if terminal_payload is not None:
            lease_payload = _lease_payload(
                next_state["leases"].get(terminal_payload.lease_id),
                terminal_payload.lease_id,
            )
            lease_payload["state"] = event.event_type.removeprefix("lease_")
            lease = _lease_from_payload(lease_payload)
            if lease is not None:
                next_state["leases"][terminal_payload.lease_id] = lease
    elif event.event_type == "lease_renewed":
        renewed_payload = _lease_renewed_from_payload(event.payload)
        if renewed_payload is not None:
            lease_id = renewed_payload.lease_id
            lease_payload = _lease_payload(next_state["leases"].get(lease_id), lease_id)
            lease_payload["state"] = "active"
            for key in ("node_id", "generation", "execution_id", "expires_at"):
                value = getattr(renewed_payload, key)
                if value is not None:
                    lease_payload[key] = value
            lease = _lease_from_payload(lease_payload)
            if lease is not None:
                next_state["leases"][lease_id] = lease
    elif event.event_type == "output_record_accepted":
        try:
            output_record_payload = OutputRecordAcceptedPayload.model_validate(event.payload).root
        except ValueError:
            return next_state
        _record_output_record(next_state, output_record_payload)
        _record_node_output_port(next_state, output_record_payload, event.position)
        _record_accepted_output_record(next_state, output_record_payload)
        _record_accepted_record_summary(next_state, output_record_payload)
        _record_output_payload(next_state, output_record_payload)
        _record_latest_routine_snapshot(next_state, output_record_payload)
        _record_completion_decision(next_state, output_record_payload)
        _record_decision_request_details(next_state, output_record_payload)
        _record_candidate(next_state, output_record_payload, event.position)
        _record_check_result(next_state, output_record_payload, event.position)
        _record_environment_failure(next_state, output_record_payload, event.position)
    elif event.event_type in {"verification_passed", "verification_failed"}:
        try:
            verification_model = (
                VerificationPassedPayload
                if event.event_type == "verification_passed"
                else VerificationFailedPayload
            )
            verification_payload = verification_model.model_validate(event.payload)
        except ValueError:
            return next_state
        _record_verdict(next_state, verification_payload, event.position)
        _record_verification_result(next_state, verification_payload, event.event_type)
    elif event.event_type == "appeal_opened":
        _record_open_appeal(
            next_state,
            AppealOpenedPayload.model_validate(event.payload),
            event.position,
        )
    elif event.event_type == "oversight_decision_recorded":
        oversight_payload = OversightDecisionRecordedPayload.model_validate(event.payload)
        _record_latest_decision(
            next_state["oversight_decisions"], oversight_payload, event.position
        )
        _record_oversight_decision(next_state, oversight_payload, event.position)
    elif event.event_type == "approval_decision_recorded":
        approval_payload = ApprovalDecisionRecordedPayload.model_validate(event.payload)
        _record_latest_approval_decision(next_state["approval_decisions"], approval_payload)
        _record_gate_decision(next_state, approval_payload)
    elif event.event_type == "authority_decision_recorded":
        authority_payload = AuthorityDecisionRecordedPayload.model_validate(event.payload)
        _record_latest_authority_decision(next_state["authority_decisions"], authority_payload)
        _record_authority_decision(next_state, authority_payload)
        _clear_authority_revision_blocker(next_state, authority_payload)
    elif event.event_type == "node_authority_changed":
        _record_authority_change(
            next_state, NodeAuthorityChangedPayload.model_validate(event.payload)
        )
    elif event.event_type == "file_state_accepted":
        try:
            file_state_payload = FileStateAcceptedPayload.model_validate(event.payload)
        except ValueError:
            return next_state
        _record_node_output_port(next_state, file_state_payload.root, event.position)
        _record_accepted_record_summary(next_state, file_state_payload.root)
        _record_file_state(
            next_state,
            file_state_payload.root,
            run_id=event.run_id,
            position=event.position,
        )
    elif event.event_type == "graph_patch_accepted":
        _record_open_proposal_blocker(next_state, event)
        accepted_payload = _graph_patch_accepted_payload_from_event(event)
        if accepted_payload is not None and accepted_payload.proposed_by_node_id is not None:
            planner_node_id = accepted_payload.proposed_by_node_id
            patch_id = accepted_payload.patch_id
            accepted = list(next_state["accepted_graph_patches_by_node"].get(planner_node_id, []))
            accepted.append(patch_id)
            next_state["accepted_graph_patches_by_node"][planner_node_id] = accepted
            successor_node_ids = accepted_payload.successor_planner_node_ids
            has_successor = bool(successor_node_ids)
            if not has_successor:
                no_successor_patches = list(
                    next_state["accepted_no_successor_patches_by_node"].get(planner_node_id, [])
                )
                no_successor_patches.append(patch_id)
                next_state["accepted_no_successor_patches_by_node"][planner_node_id] = (
                    no_successor_patches
                )
            else:
                next_state["accepted_no_successor_patches_by_node"][planner_node_id] = []
            if successor_node_ids:
                next_state["accepted_no_successor_patch_ids_by_node"].pop(
                    planner_node_id,
                    None,
                )
            else:
                next_state["accepted_no_successor_patch_ids_by_node"][planner_node_id] = patch_id
            if successor_node_ids:
                next_state["planner_successors"][planner_node_id] = successor_node_ids[0]
    elif event.event_type == "gatekeeper_verdict_recorded":
        try:
            gatekeeper_payload = GatekeeperVerdictRecordedPayload.model_validate(event.payload)
        except ValueError:
            return next_state
        _record_gatekeeper_verdicts(next_state, gatekeeper_payload)
    elif event.event_type == "cleanup_requested":
        _record_cleanup_requested(next_state, event)
    elif event.event_type == "cleanup_applied":
        _record_cleanup_applied(next_state, event)
    elif event.event_type == "runtime_retry_scheduled":
        _record_runtime_retry_scheduled(next_state, event)
    elif event.event_type == "requirement_revision_recorded":
        _record_requirement_revision(next_state, event)
        _record_authority_revision_blocker(next_state, event)
    elif event.event_type == "support_evidence_recorded":
        _record_support_evidence(next_state, event)
    elif event.event_type == "graph_patch_rejected":
        _record_open_proposal_blocker(next_state, event)
    elif event.event_type == "plan_region_marked_suspect":
        _record_suspect_node_reason(
            next_state, event.event_type, NodeSuspectPayload.model_validate(event.payload)
        )
    elif event.event_type == "node_deferred":
        payload = NodeDeferredPayload.model_validate(event.payload)
        node_id = payload.node_id
        reason = payload.reason
        next_state["last_deferred_reasons"][node_id] = reason
    elif event.event_type == "callback_accepted":
        _record_callback_idempotency_event(next_state, event)
    elif event.event_type == "node_ready":
        node_id = NodeReadyPayload.model_validate(event.payload).node_id
        next_state["last_deferred_reasons"].pop(node_id, None)
    # node_ready/node_deferred and agent_died/runtime_retry_scheduled are
    # audit/policy facts. Projection facts are updated only by lease_* and
    # node_state_changed events so replay has a single state authority.

    next_state["ready_nodes"] = _ready_nodes(next_state["node_states"])
    next_state["task_states"] = _derive_task_states(next_state)
    return next_state


def project_run_state(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> str | None:
    projection = projection if projection is not None else _project(events)
    run_state = projection["run_state"]
    blockers = final_invariant_blockers_for_events(events, projection)
    if run_state == "completed":
        if blockers:
            return "active"
        return run_state
    if run_state != "active":
        return run_state
    if blockers:
        return run_state
    task_states = projection["task_states"]
    if task_states and all(state == "accepted" for state in task_states.values()):
        return "completed"
    return run_state


def project_final_invariant_blockers(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> list[FinalInvariantBlocker]:
    proj = projection if projection is not None else _project(events)
    return final_invariant_blockers_for_events(events, proj)


def final_invariant_blockers_for_events(
    events: list[EventEnvelope],
    projection: GraphProjection,
    *,
    include_completion_decision: bool = True,
) -> list[FinalInvariantBlocker]:
    blockers: list[FinalInvariantBlocker] = []
    pending_states = {"planned", "ready", "leased", "running", "blocked", "suspended"}
    for node_id, node_state in sorted(projection["node_states"].items()):
        kind = projection["node_kinds"].get(node_id)
        role = projection["node_roles"].get(node_id)
        is_planner = kind == "planner" and role == "planner"
        is_gap_planner = kind == "gap_planner" or role == "gap_planner"
        if (is_planner or is_gap_planner) and node_state in pending_states:
            blockers.append(
                {
                    "kind": "pending_gap_planner" if is_gap_planner else "pending_planner",
                    "reason": "planner node has not completed",
                    "node_id": node_id,
                    "state": node_state,
                }
            )
            continue
        if (
            kind == "gate"
            and role == "planner_generation_budget_gate"
            and node_state in pending_states
        ):
            blockers.append(
                {
                    "kind": "pending_planner_generation_budget_gate",
                    "reason": "planner generation budget gate is unresolved",
                    "node_id": node_id,
                    "state": node_state,
                }
            )
            continue
        if kind == "check" and node_state in pending_states:
            blockers.append(
                {
                    "kind": "pending_check",
                    "reason": "check node has not completed",
                    "node_id": node_id,
                    "state": node_state,
                }
            )
    blockers.extend(_open_proposal_blockers(events, projection))
    blockers.extend(_suspect_node_blockers(events, projection))
    blockers.extend(_requirement_evidence_blockers(events, projection))
    blockers.extend(_authority_revision_blockers(events, projection))
    blockers.extend(_blocked_requirement_node_blockers(events, projection))
    blockers.extend(_dead_required_input_blockers(projection))
    blockers.extend(_impossible_input_blockers(projection))
    blockers.extend(_failed_check_result_blockers(events, projection))
    if include_completion_decision:
        blockers.extend(_completion_decision_blockers(events, projection))
    blockers.extend(_node_fulfillment_blockers(projection))
    blockers.extend(_non_terminal_node_blockers(projection, blockers, pending_states))
    for task_region_id, task_state in sorted(projection["task_states"].items()):
        if task_state == "accepted":
            continue
        blockers.append(
            {
                "kind": "task_not_accepted",
                "reason": "task region has not reached accepted",
                "task_region_id": task_region_id,
                "state": task_state,
            }
        )
    return blockers


def _node_fulfillment_blockers(projection: GraphProjection) -> list[FinalInvariantBlocker]:
    blockers: list[FinalInvariantBlocker] = []
    for node_id, node_state in sorted(projection["node_states"].items()):
        if node_state in {"cancelled", "retired"}:
            continue
        if node_state not in {"completed", "failed"}:
            continue
        contract = _contract_for_node(projection, node_id)
        if contract is None or contract.fulfillment_contribution == "none":
            continue
        if contract.fulfillment_contribution == "task_acceptance":
            continue
        if contract.node_type == "final_gate":
            continue
        missing_ports = _missing_fulfillment_ports(projection, node_id)
        if not missing_ports:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "node_unfulfilled",
            "reason": "node contract fulfillment outputs are missing",
            "node_id": node_id,
            "state": node_state,
            "support_ids": missing_ports,
        }
        task_region_id = projection["node_task_regions"].get(node_id)
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        blockers.append(blocker)
    return blockers


def _impossible_input_blockers(projection: GraphProjection) -> list[FinalInvariantBlocker]:
    blockers: list[FinalInvariantBlocker] = []
    terminal_states = {"completed", "failed", "cancelled", "retired"}
    for edge_id, edge in sorted(projection["edges"].items()):
        if not edge.required:
            continue
        if edge.dependency_type != "input_binding":
            continue
        from_node_id = edge.from_node_id
        to_node_id = edge.to_node_id
        to_port = edge.to_port
        if projection["node_states"].get(to_node_id) in terminal_states:
            continue
        if from_node_id in projection["node_states"]:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "impossible_input",
            "reason": "required input edge has no producer node",
            "node_id": to_node_id,
            "edge_id": str(edge_id),
            "to_port": to_port,
            "state": projection["node_states"].get(to_node_id, "unknown"),
        }
        task_region_id = projection["node_task_regions"].get(to_node_id)
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        blockers.append(blocker)
    return blockers


def _dead_required_input_blockers(projection: GraphProjection) -> list[FinalInvariantBlocker]:
    blockers: list[FinalInvariantBlocker] = []
    dead_source_states = {"failed", "cancelled", "retired"}
    target_terminal_states = {"completed", "failed", "cancelled", "retired"}
    for edge_id, edge in sorted(projection["edges"].items()):
        if not edge.required:
            continue
        if edge.dependency_type != "input_binding":
            continue
        from_node_id = edge.from_node_id
        to_node_id = edge.to_node_id
        to_port = edge.to_port
        source_state = projection["node_states"].get(from_node_id)
        if source_state not in dead_source_states:
            continue
        target_state = projection["node_states"].get(to_node_id, "unknown")
        if target_state in target_terminal_states:
            continue
        binding = projection["input_bindings"].get(to_node_id, {}).get(to_port)
        record_ids = binding.record_ids if binding is not None else None
        if isinstance(record_ids, list) and record_ids:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "dead_required_input",
            "reason": "required input source is terminal before producing a bound record",
            "node_id": to_node_id,
            "edge_id": str(edge_id),
            "from_node_id": str(from_node_id),
            "to_port": str(to_port),
            "state": target_state,
        }
        task_region_id = projection["node_task_regions"].get(str(to_node_id))
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        blockers.append(blocker)
    return blockers


def _non_terminal_node_blockers(
    projection: GraphProjection,
    existing_blockers: list[FinalInvariantBlocker],
    pending_states: set[str],
) -> list[FinalInvariantBlocker]:
    blocked_node_ids = {
        node_id
        for blocker in existing_blockers
        if isinstance((node_id := blocker.get("node_id")), str)
    }
    blockers: list[FinalInvariantBlocker] = []
    for node_id, node_state in sorted(projection["node_states"].items()):
        if (
            node_id in blocked_node_ids
            or node_state not in pending_states
            or projection["node_kinds"].get(node_id) == "final_gate"
        ):
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "pending_node",
            "reason": "node has not reached a terminal state",
            "node_id": node_id,
            "state": node_state,
        }
        task_region_id = projection["node_task_regions"].get(node_id)
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        blockers.append(blocker)
    return blockers


def _failed_check_result_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    if not _has_full_event_history(events):
        return _failed_check_result_blockers_from_projection(projection)
    blockers_by_record: dict[str, FinalInvariantBlocker] = {}
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        if not _is_check_result_record(event.payload):
            continue
        status = _check_result_status(event.payload)
        if status is None:
            continue
        if status in {"passed", "pass", "ok"}:
            continue
        if _check_result_recovery_superseded(projection, event.payload):
            continue
        record_id = event.payload.get("record_id")
        key = record_id if isinstance(record_id, str) else f"position-{event.position}"
        blocker: FinalInvariantBlocker = {
            "kind": "failed_check_result",
            "reason": "check result did not pass",
        }
        value = event.payload.get("value")
        if isinstance(value, dict):
            typed_value = cast(dict[str, Any], value)
            classification = typed_value.get("classification")
            command_text = typed_value.get("command_text")
            stderr = typed_value.get("stderr_tail")
            exit_code = typed_value.get("exit_code")
            if isinstance(classification, str):
                blocker["classification"] = classification
            if isinstance(command_text, str):
                blocker["command_text"] = command_text
            if isinstance(stderr, str):
                blocker["stderr_tail"] = stderr
            if isinstance(exit_code, int) and (
                isinstance(command_text, str)
                or isinstance(stderr, str)
                or isinstance(classification, str)
            ):
                blocker["exit_code"] = exit_code
            if classification in {"environment_error", "tool_error", "tool_unavailable"}:
                blocker["reason"] = _environment_failure_reason_from_check_value(typed_value)
        node_id = event.payload.get("producer_node_id") or event.payload.get("node_id")
        if isinstance(node_id, str):
            blocker["node_id"] = node_id
        task_region_id = event.payload.get("task_region_id")
        if isinstance(task_region_id, str):
            blocker["task_region_id"] = task_region_id
        blocker["state"] = status
        blockers_by_record[key] = blocker
    return [blockers_by_record[key] for key in sorted(blockers_by_record)]


def _failed_check_result_blockers_from_projection(
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    blockers_by_record: dict[str, FinalInvariantBlocker] = {}
    for node_id, payload in projection.get("check_results", {}).items():
        status = payload.status
        if status in {"passed", "pass", "ok"}:
            continue
        key = payload.record_id or node_id
        blocker: FinalInvariantBlocker = {
            "kind": "failed_check_result",
            "reason": "check result did not pass",
            "node_id": node_id,
            "state": status,
        }
        if payload.classification is not None:
            blocker["classification"] = payload.classification
        if payload.command_text is not None:
            blocker["command_text"] = payload.command_text
        if payload.stderr_tail is not None:
            blocker["stderr_tail"] = payload.stderr_tail
        if payload.exit_code is not None and (
            payload.command_text is not None
            or payload.stderr_tail is not None
            or payload.classification is not None
        ):
            blocker["exit_code"] = payload.exit_code
        if payload.classification in {"environment_error", "tool_error", "tool_unavailable"}:
            blocker["reason"] = _environment_failure_reason_from_check_value(
                payload.model_dump(mode="json"),
            )
        if payload.task_region_id is not None:
            blocker["task_region_id"] = payload.task_region_id
        blockers_by_record[key] = blocker
    return [blockers_by_record[key] for key in sorted(blockers_by_record)]


def _is_check_result_record(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "check_result"
        or payload.get("port") == "check_result"
        or payload.get("record_kind") == "check_result"
    )


def _check_result_status(payload: dict[str, Any]) -> str | None:
    status = payload.get("status")
    if isinstance(status, str):
        return status.lower()
    value = payload.get("value")
    if isinstance(value, dict):
        value_status = cast(dict[str, Any], value).get("status")
        if isinstance(value_status, str):
            return value_status.lower()
    return None


def _completion_decision_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    final_gate_node_ids = {
        node_id
        for node_id, kind in projection["node_kinds"].items()
        if kind == "final_gate" and projection["node_states"].get(node_id) != "retired"
    }
    if not final_gate_node_ids:
        return []

    latest: dict[str, tuple[str, list[FinalInvariantBlocker]]] = {}
    payloads: Iterable[dict[str, Any]]
    if _has_full_event_history(events):
        payloads = [
            event.payload for event in events if event.event_type == "output_record_accepted"
        ]
    else:
        payloads = [
            _output_record_payload_dict(payload)
            for payload in projection.get("output_record_payloads", {}).values()
        ]
    for payload in payloads:
        node_id = payload.get("producer_node_id")
        if not isinstance(node_id, str) or node_id not in final_gate_node_ids:
            continue
        if payload.get("port") != "completion_decision":
            continue
        status = _completion_decision_status(payload)
        if status is None:
            continue
        latest[node_id] = (status, _completion_decision_payload_blockers(payload))

    blockers: list[FinalInvariantBlocker] = []
    for node_id in sorted(final_gate_node_ids):
        decision = latest.get(node_id)
        if decision is None:
            blockers.append(
                {
                    "kind": "missing_completion_decision",
                    "reason": "final gate has not produced a completion_decision",
                    "node_id": node_id,
                    "state": projection["node_states"].get(node_id, "unknown"),
                }
            )
            continue
        status, decision_blockers = decision
        if status == "passed":
            continue
        if decision_blockers:
            blockers.extend(decision_blockers)
            continue
        blockers.append(
            {
                "kind": "blocked_completion_decision",
                "reason": "final gate completion_decision is blocked",
                "node_id": node_id,
                "state": projection["node_states"].get(node_id, "unknown"),
            }
        )
    return blockers


def _completion_decision_status(payload: dict[str, Any]) -> str | None:
    status = payload.get("status")
    if isinstance(status, str):
        return status
    value = payload.get("value")
    if isinstance(value, dict):
        value_status = cast(dict[str, Any], value).get("status")
        if isinstance(value_status, str):
            return value_status
    return None


def _completion_decision_payload_blockers(payload: dict[str, Any]) -> list[FinalInvariantBlocker]:
    value = payload.get("value")
    raw_blockers: Any = payload.get("blockers")
    if raw_blockers is None and isinstance(value, dict):
        raw_blockers = cast(dict[str, Any], value).get("blockers")
    if not isinstance(raw_blockers, list):
        return []
    blockers: list[FinalInvariantBlocker] = []
    for raw_blocker in cast(list[Any], raw_blockers):
        if not isinstance(raw_blocker, dict):
            continue
        blocker = cast(dict[str, Any], raw_blocker)
        kind = blocker.get("kind")
        reason = blocker.get("reason")
        if not isinstance(kind, str) or not isinstance(reason, str):
            continue
        blockers.append(cast(FinalInvariantBlocker, dict(blocker)))
    return blockers


def _open_proposal_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    if not _has_full_event_history(events):
        return [
            projection["open_proposal_blockers"][key]
            for key in sorted(projection["open_proposal_blockers"])
        ]
    open_proposals: dict[str, FinalInvariantBlocker] = {}
    for event in events:
        payload = _graph_patch_payload_for_event(event)
        if payload is None:
            continue
        proposal_id = _proposal_id(payload)
        if proposal_id is None:
            continue
        if event.event_type in {"graph_patch_accepted", "graph_patch_rejected"}:
            open_proposals.pop(proposal_id, None)
    return [open_proposals[key] for key in sorted(open_proposals)]


def _suspect_node_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    if _has_full_event_history(events):
        suspect_nodes: dict[str, str] = {}
        for event in events:
            if event.event_type == "plan_region_marked_suspect":
                payload = NodeSuspectPayload.model_validate(event.payload)
                reason = payload.reason or "suspect graph fact remains unresolved"
                for node_id in _node_ids_from_suspect_payload(payload):
                    suspect_nodes[node_id] = reason
    else:
        suspect_nodes = projection.get("suspect_node_reasons", {})

    blockers: list[FinalInvariantBlocker] = []
    inactive_states = {"completed", "failed", "cancelled", "retired"}
    for node_id in sorted(suspect_nodes):
        node_state = projection["node_states"].get(node_id)
        if node_state in inactive_states:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "suspect_active_node",
            "reason": suspect_nodes[node_id],
            "node_id": node_id,
        }
        if node_state is not None:
            blocker["state"] = node_state
        blockers.append(blocker)
    return blockers


def _requirement_evidence_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    blockers: list[FinalInvariantBlocker] = []
    for fact in requirement_freshness_facts_from_projection(projection):
        if fact["unsupported"]:
            stale_support_ids = list(fact["stale_support_ids"])
            if stale_support_ids:
                blockers.append(
                    {
                        "kind": "stale_support_evidence",
                        "reason": "active requirement is supported only by stale evidence",
                        "requirement_id": fact["requirement_id"],
                        "support_ids": stale_support_ids,
                    }
                )
            blockers.append(
                {
                    "kind": "unsupported_active_requirement",
                    "reason": "active requirement has no current supporting evidence",
                    "requirement_id": fact["requirement_id"],
                    "support_ids": stale_support_ids,
                }
            )

    return blockers


def _authority_revision_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    if not _has_full_event_history(events):
        return [
            projection["authority_revision_blockers"][key]
            for key in sorted(projection["authority_revision_blockers"])
        ]
    unresolved: dict[str, FinalInvariantBlocker] = {}
    for event in events:
        if event.event_type == "authority_decision_recorded":
            authority_payload = AuthorityDecisionRecordedPayload.model_validate(event.payload)
            if authority_payload.decision in {"granted", "approved", "passed", "accepted"}:
                authority_revision_id = _authority_decision_revision_id(authority_payload)
                if authority_revision_id is not None:
                    unresolved.pop(authority_revision_id, None)
            continue
        payload = _authority_revision_payload_for_event(event)
        if payload is None:
            continue
        revision_id = _revision_id(payload)
        if revision_id is None:
            continue
        if event.event_type == "requirement_revision_recorded":
            if not _requires_authority_resolution(payload):
                continue
            blocker: FinalInvariantBlocker = {
                "kind": "unresolved_authority_required_revision",
                "reason": "semantic or new-behavior requirement revision lacks authority resolution",
                "revision_id": revision_id,
            }
            requirement_id = _requirement_id(payload)
            if requirement_id is not None:
                blocker["requirement_id"] = requirement_id
            unresolved[revision_id] = blocker
    return [unresolved[key] for key in sorted(unresolved)]


def _blocked_requirement_node_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    payloads = (
        _latest_node_creation_payloads(events)
        if _has_full_event_history(events)
        else projection.get("node_creation_payloads", {})
    )
    blockers: list[FinalInvariantBlocker] = []
    for node_id, node_state in sorted(projection["node_states"].items()):
        if projection["node_kinds"].get(node_id) != "requirement" or node_state != "blocked":
            continue
        raw_payload = payloads.get(node_id)
        payload = raw_payload.model_dump(mode="json") if raw_payload is not None else {}
        priority = _requirement_priority(payload)
        if priority not in {"must", "expected", "critical"}:
            continue
        requirement_id = _requirement_id(payload) or node_id
        blockers.append(
            {
                "kind": "blocked_requirement",
                "reason": "must or expected requirement is blocked without accepted blocker",
                "node_id": node_id,
                "requirement_id": requirement_id,
                "state": node_state,
            }
        )
    return blockers


def _proposal_id(payload: dict[str, Any]) -> str | None:
    for key in ("proposal_id", "patch_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _record_open_proposal_blocker(state: GraphProjection, event: EventEnvelope) -> None:
    payload = _graph_patch_payload_for_event(event)
    if payload is None:
        return
    proposal_id = _proposal_id(payload)
    if proposal_id is None:
        return
    if event.event_type in {"graph_patch_accepted", "graph_patch_rejected"}:
        state["open_proposal_blockers"].pop(proposal_id, None)


def _record_suspect_node_reason(
    state: GraphProjection, event_type: str, payload: NodeSuspectPayload
) -> None:
    node_ids = _node_ids_from_suspect_payload(payload)
    if event_type == "plan_region_marked_suspect":
        reason = payload.reason or "suspect graph fact remains unresolved"
        for node_id in node_ids:
            state["suspect_node_reasons"][node_id] = reason
        return


def _node_ids_from_suspect_payload(payload: NodeSuspectPayload) -> list[str]:
    return sorted(
        set(
            [node_id for node_id in [payload.node_id, payload.region_id] if node_id is not None]
            + payload.node_ids
            + payload.region_node_ids
        )
    )


def _record_authority_revision_blocker(state: GraphProjection, event: EventEnvelope) -> None:
    payload = _authority_revision_payload_for_event(event)
    if payload is None:
        return
    revision_id = _revision_id(payload)
    if revision_id is None:
        return
    if event.event_type == "requirement_revision_recorded":
        if not _requires_authority_resolution(payload):
            state["authority_revision_blockers"].pop(revision_id, None)
            return
        blocker: FinalInvariantBlocker = {
            "kind": "unresolved_authority_required_revision",
            "reason": "semantic or new-behavior requirement revision lacks authority resolution",
            "revision_id": revision_id,
        }
        requirement_id = _requirement_id(payload)
        if requirement_id is not None:
            blocker["requirement_id"] = requirement_id
        state["authority_revision_blockers"][revision_id] = blocker


def _authority_revision_payload_for_event(event: EventEnvelope) -> dict[str, Any] | None:
    if event.event_type == "requirement_revision_recorded":
        return RequirementRevisionPayload.model_validate(event.payload).model_dump(mode="json")
    return None


def _revision_id(payload: dict[str, Any]) -> str | None:
    for key in ("revision_id", "version_id", "requirement_version_id", "proposal_id", "patch_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return _requirement_id(payload)


def _requirement_id(payload: dict[str, Any]) -> str | None:
    for key in ("requirement_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    requirement = payload.get("requirement")
    if isinstance(requirement, dict):
        value = cast(dict[str, Any], requirement).get("id")
        if isinstance(value, str) and value:
            return value
    node_id = payload.get("node_id")
    if isinstance(node_id, str) and node_id:
        return node_id
    return None


def _requires_authority_resolution(payload: dict[str, Any]) -> bool:
    if payload.get("requires_authority") is True:
        return True
    if payload.get("semantic_change") is True:
        return True
    revision_type = payload.get("revision_type")
    if not isinstance(revision_type, str):
        revision_type = payload.get("classification")
    return revision_type in {
        "semantic",
        "new_behavior",
        "new-behavior",
        "scope_expansion",
        "scope_reduction",
        "priority_change",
    }


def _requirement_priority(payload: dict[str, Any]) -> str | None:
    priority = payload.get("priority")
    if isinstance(priority, str):
        return priority.lower()
    requirement = payload.get("requirement")
    if isinstance(requirement, dict):
        value = cast(dict[str, Any], requirement).get("priority")
        if isinstance(value, str):
            return value.lower()
    return None


def project_planner_chain(events: list[EventEnvelope]) -> list[dict[str, Any]]:
    projection = _project(events)
    planner_ids = [
        node_id
        for node_id, kind in projection["node_kinds"].items()
        if kind == "planner" and projection["node_roles"].get(node_id) == "planner"
    ]
    ordered = sorted(
        planner_ids,
        key=lambda node_id: (
            projection["planner_generations"].get(node_id, 0),
            _node_creation_position(events, node_id),
            node_id,
        ),
    )
    return [
        {
            "node_id": node_id,
            "generation_index": projection["planner_generations"].get(node_id, 0),
            "session_id": projection["planner_sessions"].get(node_id),
            "lease_generation": _latest_lease_generation(events, node_id),
            "region_label": _planner_region_label(events, projection, node_id),
            "state": projection["node_states"].get(node_id),
            "successor_node_id": projection["planner_successors"].get(node_id),
        }
        for node_id in ordered
    ]


def project_planner_session(events: list[EventEnvelope]) -> dict[str, Any]:
    projection = _project(events)
    session_ids = list(projection["planner_session_states"])
    if not session_ids:
        session_ids = list(projection["planner_sessions"].values())
    session_id = sorted(set(session_ids))[0] if session_ids else None
    if session_id is None:
        return {
            "session_id": None,
            "state": None,
            "generations": [],
            "current_node_id": None,
            "carryover_record_id": None,
        }

    generations: list[dict[str, Any]] = [
        {
            "node_id": event.payload["node_id"],
            "lease_generation": event.payload["generation"],
            "region_label": _planner_region_label(
                events,
                projection,
                str(event.payload["node_id"]),
            ),
            "state": _planner_generation_state(events, str(event.payload["lease_id"])),
        }
        for event in events
        if event.event_type == "lease_granted"
        and event.payload.get("session_id") == session_id
        and isinstance(event.payload.get("node_id"), str)
        and isinstance(event.payload.get("lease_id"), str)
        and isinstance(event.payload.get("generation"), int)
    ]
    generations.sort(key=lambda generation: int(generation["lease_generation"]))
    return {
        "session_id": session_id,
        "state": projection["planner_session_states"].get(session_id),
        "generations": generations,
        "current_node_id": projection["planner_session_current_nodes"].get(session_id),
        "carryover_record_id": projection["planner_session_carryovers"].get(session_id),
    }


def project_node_states(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, str]:
    proj = projection if projection is not None else _project(events)
    return proj["node_states"]


def project_node_metadata(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, dict[str, Any]]:
    projection = projection if projection is not None else _project(events)
    metadata: dict[str, dict[str, Any]] = {}
    for node_id in projection["node_states"]:
        kind = projection["node_kinds"].get(node_id)
        role = projection["node_roles"].get(node_id)
        detail: dict[str, Any] = {
            "kind": projection["node_kinds"].get(node_id),
            "role": projection["node_roles"].get(node_id),
            "task_region_id": projection["node_task_regions"].get(node_id),
            "input_ports": {
                port: _bound_record_ids(binding)
                for port, binding in projection["input_bindings"].get(node_id, {}).items()
            },
            "resource_claims": [
                claim.model_dump(mode="json")
                for claim in projection["node_resource_claims"].get(node_id, [])
            ],
            "allowed_actions": list(projection["node_allowed_actions"].get(node_id, [])),
            "preconditions": list(projection["node_preconditions"].get(node_id, [])),
        }
        command_definition = projection["node_command_definitions"].get(node_id)
        if command_definition is not None:
            detail["command_definition"] = command_definition
        contract = node_contract_summary(kind, role)
        if contract is not None:
            detail["contract"] = contract
        metadata[node_id] = detail
    return metadata


def project_graph_topology(events: list[EventEnvelope]) -> GraphTopologyView:
    projection = _project(events)
    record_summaries = _record_summaries_by_id(projection)
    _add_record_summary_positions(record_summaries, events)
    nodes: list[GraphTopologyNode] = []
    for node_id in sorted(projection["node_states"]):
        kind = projection["node_kinds"].get(node_id)
        role = projection["node_roles"].get(node_id)
        node: GraphTopologyNode = {
            "node_id": node_id,
            "kind": kind,
            "role": role,
            "state": projection["node_states"].get(node_id),
        }
        contract = node_contract_summary(kind, role)
        if contract is not None:
            node["contract"] = contract
        nodes.append(node)

    edges = [
        _topology_edge(edge, projection, record_summaries)
        for _, edge in sorted(projection["edges"].items())
    ]
    return {"nodes": nodes, "edges": edges}


def project_graph_patch_attempts(
    events: list[EventEnvelope],
    *,
    run_id: str = "",
    current_graph_position: int | None = None,
) -> GraphPatchAttemptView:
    attempts: dict[str, GraphPatchAttempt] = {}
    order: list[str] = []
    active_patch_id: str | None = None

    def ensure_attempt(patch_id: str) -> GraphPatchAttempt:
        attempt = attempts.get(patch_id)
        if attempt is None:
            attempt = GraphPatchAttempt(
                patch_id=patch_id,
                created_node_ids=[],
                created_edge_ids=[],
            )
            attempts[patch_id] = attempt
            order.append(patch_id)
        return attempt

    for event in events:
        payload = _graph_patch_payload_for_event(event) or event.payload
        patch_id = _patch_id(payload)
        if event.event_type == "graph_patch_accepted" and patch_id is not None:
            attempt = ensure_attempt(patch_id)
            attempt["status"] = "accepted"
            attempt["accepted_event_id"] = event.event_id
            attempt["accepted_position"] = event.position
            _apply_patch_payload(attempt, payload)
            if current_graph_position is not None:
                attempt["current_graph_position"] = current_graph_position
            active_patch_id = patch_id
            continue
        if event.event_type == "graph_patch_rejected" and patch_id is not None:
            attempt = ensure_attempt(patch_id)
            attempt["status"] = "rejected"
            attempt["rejected_event_id"] = event.event_id
            attempt["rejected_position"] = event.position
            _apply_patch_payload(attempt, payload)
            if current_graph_position is not None:
                attempt["current_graph_position"] = current_graph_position
            active_patch_id = None
            continue
        if active_patch_id is None:
            continue
        attempt = attempts.get(active_patch_id)
        if attempt is None:
            continue
        if event.event_type == "node_created":
            node_payload = _node_created_payload_from_event(event)
            node_id = node_payload.node_id if node_payload is not None else None
            if node_id is not None:
                created = attempt.setdefault("created_node_ids", [])
                created.append(node_id)
        elif event.event_type == "edge_created":
            edge_id = payload.get("edge_id")
            if isinstance(edge_id, str):
                created = attempt.setdefault("created_edge_ids", [])
                created.append(edge_id)
        else:
            active_patch_id = None

    if current_graph_position is None:
        current_graph_position = max((event.position for event in events), default=0)
    ordered_attempts: list[GraphPatchAttempt] = []
    for patch_id in order:
        attempt = attempts[patch_id]
        if "status" not in attempt:
            continue
        attempt.setdefault("current_graph_position", current_graph_position)
        ordered_attempts.append(
            cast(
                GraphPatchAttempt,
                GraphPatchResultRecord.model_validate(attempt).model_dump(mode="json"),
            )
        )
    return {
        "run_id": run_id,
        "current_graph_position": current_graph_position,
        "attempts": ordered_attempts,
    }


def _apply_patch_payload(attempt: GraphPatchAttempt, payload: dict[str, Any]) -> None:
    proposed_by_node_id = payload.get("proposed_by_node_id")
    if isinstance(proposed_by_node_id, str):
        attempt["proposed_by_node_id"] = proposed_by_node_id
    base_graph_position = payload.get("base_graph_position")
    if (
        isinstance(base_graph_position, int)
        and not isinstance(base_graph_position, bool)
        and base_graph_position >= 0
    ):
        attempt["base_graph_position"] = base_graph_position
    reason = payload.get("reason")
    if isinstance(reason, str) and reason:
        attempt["rejection_reason"] = reason
    read_set_diff = payload.get("read_set_diff")
    if isinstance(read_set_diff, dict):
        attempt["read_set_diff"] = cast(dict[str, Any], read_set_diff)
    diagnostics = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "patch_id",
            "proposed_by_node_id",
            "base_graph_position",
            "reason",
            "read_set_diff",
        }
    }
    if diagnostics:
        attempt["diagnostics"] = diagnostics


def _patch_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("patch_id")
    if isinstance(value, str) and value:
        return value
    return None


def project_task_states(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, str]:
    proj = projection if projection is not None else _project(events)
    return proj["task_states"]


def project_requirement_revisions(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    return {
        version_id: revision.model_dump(mode="json")
        for version_id, revision in _project(events)["requirement_revisions"].items()
    }


def support_evidence_freshness_from_projection(
    projection: GraphProjection,
) -> dict[str, SupportEvidenceFreshness]:
    freshness: dict[str, SupportEvidenceFreshness] = {}
    for support_id, support in sorted(projection.get("support_evidence", {}).items()):
        stale_reason = _support_stale_reason(projection, support)
        is_fresh = stale_reason is None and support.status == "active"
        freshness[support_id] = {
            "support_id": support_id,
            "evidence_id": support.evidence_id,
            "requirement_id": support.requirement_id,
            "requirement_version_id": support.requirement_version_id,
            "status": support.status,
            "freshness": "fresh" if is_fresh else "stale",
            "stale_reason": stale_reason,
        }
    return freshness


def project_support_evidence_freshness(
    events: list[EventEnvelope],
) -> dict[str, SupportEvidenceFreshness]:
    return support_evidence_freshness_from_projection(_project(events))


def requirement_freshness_facts_from_projection(
    projection: GraphProjection,
) -> list[RequirementFreshnessFact]:
    support_freshness = support_evidence_freshness_from_projection(projection)
    facts: list[RequirementFreshnessFact] = []
    for requirement_id, active_version_id in sorted(
        projection.get("active_requirement_versions", {}).items()
    ):
        revision = projection.get("requirement_revisions", {}).get(active_version_id, {})
        fresh_support_ids: list[str] = []
        stale_support_ids: list[str] = []
        for support_id, support in sorted(projection.get("support_evidence", {}).items()):
            if support.requirement_id != requirement_id:
                continue
            support_fact = support_freshness.get(support_id)
            if support_fact is None:
                continue
            if support_fact["freshness"] == "fresh":
                fresh_support_ids.append(support_id)
            else:
                stale_support_ids.append(support_id)
        facts.append(
            {
                "requirement_id": requirement_id,
                "active_version_id": active_version_id,
                "revision_classification": (
                    revision.change_classification
                    if isinstance(revision, RequirementRevisionProjection)
                    else "initial"
                ),
                "requires_authority": (
                    revision.requires_authority
                    if isinstance(revision, RequirementRevisionProjection)
                    else False
                ),
                "authority_required_reason": (
                    revision.authority_required_reason
                    if isinstance(revision, RequirementRevisionProjection)
                    else None
                ),
                "fresh_support_ids": fresh_support_ids,
                "stale_support_ids": stale_support_ids,
                "unsupported": not fresh_support_ids,
            }
        )
    return facts


def project_requirement_freshness_facts(
    events: list[EventEnvelope],
) -> list[RequirementFreshnessFact]:
    return requirement_freshness_facts_from_projection(_project(events))


def project_planner_freshness_packet(events: list[EventEnvelope]) -> dict[str, Any]:
    """Expose compact requirement/evidence freshness facts for gap planners."""
    facts = project_requirement_freshness_facts(events)
    return {
        "requirement_freshness": facts,
        "unsupported_requirement_ids": [
            fact["requirement_id"] for fact in facts if fact["unsupported"]
        ],
        "stale_support_ids": [
            support_id for fact in facts for support_id in fact["stale_support_ids"]
        ],
        "authority_required_requirement_ids": [
            fact["requirement_id"] for fact in facts if fact["requires_authority"]
        ],
    }


def project_leases(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, dict[str, Any]]:
    proj = projection if projection is not None else _project(events)
    return {lease_id: lease.model_dump(mode="json") for lease_id, lease in proj["leases"].items()}


def project_ready_nodes(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> list[str]:
    proj = projection if projection is not None else _project(events)
    return proj["ready_nodes"]


def project_scheduler_view(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> SchedulerView:
    """Project ready/deferred scheduler buckets from graph events.

    Readiness remains governed by node_state_changed facts. Deferred scheduler
    events are audit facts, so this view exposes the latest deferral reason
    even when a node is still ready but blocked by a transient scheduler
    precondition such as a resource conflict.
    """
    proj = projection if projection is not None else _project(events)
    node_states = project_node_states([], projection=proj)
    ready = sorted(project_ready_nodes([], projection=proj))
    latest_deferrals = proj["last_deferred_reasons"]
    view: SchedulerView = {
        "ready": ready,
        "blocked": [],
        "waiting_resources": [],
        "waiting_gates": [],
    }
    for node_id, node_state in sorted(node_states.items()):
        reason = latest_deferrals.get(node_id)
        if node_state not in {"planned", "blocked", "ready"}:
            continue
        if node_state == "ready" and reason == "max_grants_reached":
            continue
        if reason is None and node_state not in {"blocked"}:
            continue
        if reason is None:
            reason = "blocked"
        entry: SchedulerBlockedNode = {"node_id": node_id, "reason": reason}
        bucket = _scheduler_bucket_for_reason(reason)
        view[bucket].append(entry)
    return view


def project_lease_view(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> LeaseView:
    leases = project_leases(events, projection=projection)
    view: LeaseView = {"active": [], "suspended": []}
    for lease_id in sorted(leases):
        lease = leases[lease_id]
        state = lease.get("state")
        if state not in {"active", "suspended"}:
            continue
        node_id = lease.get("node_id")
        if not isinstance(node_id, str):
            continue
        entry: LeaseViewEntry = {
            "lease_id": lease_id,
            "node_id": node_id,
            "generation": _optional_int(lease.get("generation")),
            "state": state,
            "execution_id": _optional_str(lease.get("execution_id")),
            "expires_at": _optional_str(lease.get("expires_at")),
        }
        if state == "active":
            view["active"].append(entry)
        else:
            view["suspended"].append(entry)
    return view


def project_decision_view(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> DecisionView:
    """Project human decisions, appeal outcomes, and review readiness."""
    projection = projection if projection is not None else _project(events)
    return project_decision_view_from_projection(projection)


def project_decision_view_from_projection(projection: GraphProjection) -> DecisionView:
    """Project decision readback from an already-folded graph projection."""
    latest_node_payloads = projection.get("node_creation_payloads", {})
    approval_decisions = projection.get("approval_decisions", {})
    authority_decisions = projection.get("authority_decisions", {})
    oversight_decisions = projection.get("oversight_decisions", {})
    latest_deferrals = projection.get("last_deferred_reasons", {})
    request_details = projection.get("decision_request_details", {})

    pending_gates: list[PendingGateDecision] = []
    appeals: list[AppealDecision] = []
    review_blockers: list[str] = []
    review_node_count = 0
    review_complete_count = 0

    for node_id, state in sorted(projection["node_states"].items()):
        kind = projection["node_kinds"].get(node_id)
        payload = latest_node_payloads.get(node_id)
        if (
            kind in {"gate", "human_gate"}
            and state in _PENDING_DECISION_STATES
            and (node_id not in approval_decisions)
        ):
            pending_gate: PendingGateDecision = {
                "node_id": node_id,
                "gate_type": _gate_type(node_id, payload, projection),
                "prompt": _gate_prompt(payload),
            }
            pending_gate.update(
                _request_details_for_pending_gate(node_id, payload, request_details)
            )
            pending_gates.append(pending_gate)
        elif (
            kind == "authority_request"
            and state in _PENDING_DECISION_STATES
            and node_id not in authority_decisions
        ):
            pending_gate = {
                "node_id": node_id,
                "gate_type": "authority_request",
                "prompt": _gate_prompt(payload),
            }
            pending_gate.update(
                _request_details_for_pending_gate(node_id, payload, request_details)
            )
            pending_gates.append(pending_gate)
        elif kind == "appeal":
            appeals.append(
                {
                    "node_id": node_id,
                    "state": state,
                    "outcome": _decision_outcome(oversight_decisions.get(node_id)),
                }
            )
        elif kind == "review":
            review_node_count += 1
            if state == "completed":
                review_complete_count += 1
            else:
                review_blockers.append(_review_blocker(node_id, state, payload, latest_deferrals))

    return {
        "pending_gates": pending_gates,
        "appeals": appeals,
        "review": {
            "ready": review_node_count > 0 and review_complete_count == review_node_count,
            "blockers": review_blockers,
        },
    }


def project_residue_report(events: list[EventEnvelope]) -> dict[str, list[dict[str, Any]]]:
    """Project accepted file-state residue classifications by path."""
    report: dict[str, list[dict[str, Any]]] = {}
    for record in _project(events)["file_state_records"].values():
        entries = record.residue or record.classifications
        for raw_entry in entries:
            entry = _file_entry_dict(raw_entry)
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            report.setdefault(path, []).append(
                {
                    "path": path,
                    "classification": entry.get("classification"),
                    "matched_rule": entry.get("matched_rule") or entry.get("policy"),
                    "needs_gatekeeper": entry.get("needs_gatekeeper") is True,
                    "run_id": record.run_id,
                    "node_id": record.producer_node_id,
                    "record_id": record.record_id,
                    "source": entry.get("source"),
                }
            )
    return {path: report[path] for path in sorted(report)}


def _bound_record_ids(binding: InputBindingProjection) -> list[str]:
    return list(binding.record_ids)


def _topology_edge(
    edge: EdgeProjection,
    projection: GraphProjection,
    record_summaries: dict[str, GraphRecordSummary],
) -> GraphTopologyEdge:
    source_contract, target_contract = _edge_port_contracts(edge, projection)
    metadata = {
        key: value for key in _EDGE_METADATA_KEYS if (value := getattr(edge, key)) is not None
    }
    topology_edge: GraphTopologyEdge = {
        "edge_id": edge.edge_id,
        "from_node_id": edge.from_node_id,
        "from_port": edge.from_port,
        "to_node_id": edge.to_node_id,
        "to_port": edge.to_port,
        "required": edge.required,
        "dependency_type": edge.dependency_type,
        "metadata": dict(metadata),
        "record_types": _compatible_edge_record_types(source_contract, target_contract),
        "binding": None,
        "bound_records": [],
    }
    from_node_kind = edge.from_node_kind
    if isinstance(from_node_kind, str):
        topology_edge["from_node_kind"] = from_node_kind
    from_node_role = edge.from_node_role
    if isinstance(from_node_role, str):
        topology_edge["from_node_role"] = from_node_role
    selector = edge.accepted_record_selector
    if isinstance(selector, dict):
        topology_edge["accepted_record_selector"] = normalize_record_selector(selector)
    if source_contract is not None:
        topology_edge["source_port_contract"] = port_contract_summary(source_contract)
    if target_contract is not None:
        topology_edge["target_port_contract"] = port_contract_summary(target_contract)

    binding = _binding_for_edge(projection, edge)
    if binding is not None:
        binding_summary = _topology_binding(binding)
        topology_edge["binding"] = binding_summary
        record_ids = binding_summary.get("record_ids", [])
        bound_records: list[GraphRecordSummary] = [
            record_summaries[record_id] for record_id in record_ids if record_id in record_summaries
        ]
        topology_edge["bound_records"] = bound_records
    return topology_edge


def _edge_port_contracts(
    edge: EdgeProjection,
    projection: GraphProjection,
) -> tuple[PortContract | None, PortContract | None]:
    from_node_id = edge.from_node_id
    to_node_id = edge.to_node_id
    from_port = edge.from_port
    to_port = edge.to_port
    source_kind = projection["node_kinds"].get(from_node_id)
    if source_kind is None and from_node_id == "*":
        raw_source_kind = edge.from_node_kind
        source_kind = raw_source_kind if isinstance(raw_source_kind, str) else None
    source_role = projection["node_roles"].get(from_node_id)
    if source_role is None and from_node_id == "*":
        raw_source_role = edge.from_node_role
        source_role = raw_source_role if isinstance(raw_source_role, str) else None
    target_kind = projection["node_kinds"].get(to_node_id)
    target_role = projection["node_roles"].get(to_node_id)
    source_contract = (
        DEFAULT_NODE_CONTRACTS.contract_for(source_kind, source_role)
        if source_kind is not None
        else None
    )
    target_contract = (
        DEFAULT_NODE_CONTRACTS.contract_for(target_kind, target_role)
        if target_kind is not None
        else None
    )
    source_port_contract = (
        output_port_contract(source_contract, from_port) if source_contract is not None else None
    )
    target_port_contract = (
        input_port_contract(target_contract, to_port) if target_contract is not None else None
    )
    return source_port_contract, target_port_contract


def _compatible_edge_record_types(
    source: PortContract | None,
    target: PortContract | None,
) -> list[str]:
    if source is None or target is None:
        return []
    return sorted(source.record_types & target.record_types)


def _binding_for_edge(
    projection: GraphProjection,
    edge: EdgeProjection,
) -> InputBindingProjection | None:
    edge_id = edge.edge_id
    to_node_id = edge.to_node_id
    to_port = edge.to_port
    binding = projection["input_bindings"].get(to_node_id, {}).get(to_port)
    if binding is not None and binding.edge_id in {None, edge_id}:
        return binding
    for ports in projection["input_bindings"].values():
        for binding in ports.values():
            if binding.edge_id == edge_id:
                return binding
    return None


def _topology_binding(binding: InputBindingProjection) -> GraphTopologyBinding:
    summary: GraphTopologyBinding = {
        "record_ids": _bound_record_ids(binding),
    }
    for key in ("edge_id", "to_node_id", "to_port", "binding_policy", "trigger"):
        value = getattr(binding, key)
        if isinstance(value, str):
            summary[key] = value
    bound_at_position = binding.bound_at_position
    summary["bound_at_position"] = bound_at_position
    record_bound_positions = binding.record_bound_positions
    if isinstance(record_bound_positions, dict):
        summary["record_bound_positions"] = {
            record_id: position
            for record_id, position in cast(dict[Any, Any], record_bound_positions).items()
            if isinstance(record_id, str)
            and isinstance(position, int)
            and not isinstance(position, bool)
        }
    return summary


def _record_summaries_by_id(projection: GraphProjection) -> dict[str, GraphRecordSummary]:
    return {
        record_id: cast(GraphRecordSummary, dict(summary))
        for record_id, summary in projection["accepted_record_summaries_by_id"].items()
    }


def _add_record_summary_positions(
    summaries: dict[str, GraphRecordSummary],
    events: list[EventEnvelope],
) -> None:
    for event in events:
        if event.event_type not in {"output_record_accepted", "file_state_accepted"}:
            continue
        record_id = event.payload.get("record_id")
        if not isinstance(record_id, str):
            continue
        summary = summaries.get(record_id)
        if summary is not None:
            summary["position"] = event.position


def project_pattern_library(events: list[EventEnvelope]) -> dict[str, Any]:
    """Project accepted gatekeeper verdicts into exact paths and derived globs.

    Learned patterns are scoped to untracked/ignored residue. The derived
    pattern rule is deterministic: ``dirname/*.ext`` when a non-root path has
    an extension, otherwise the exact path. Root-level files derive exact-path
    patterns only, never bare ``*.ext`` globs. Identical derived patterns merge
    and accumulate occurrence counts; exact paths are kept separately so the
    next boundary can classify both the same path and sibling files with the
    same directory-scoped shape.
    """
    patterns: dict[str, dict[str, Any]] = {}
    paths: dict[str, dict[str, Any]] = {}
    file_state_records: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type == "file_state_accepted":
            record_id = event.payload.get("record_id")
            if isinstance(record_id, str):
                file_state_records[record_id] = event.payload
            continue
        if event.event_type != "gatekeeper_verdict_recorded":
            continue
        record_id = event.payload.get("file_state_record_id")
        verdicts = event.payload.get("verdicts")
        if not isinstance(verdicts, list):
            continue
        source_by_path = _file_state_source_by_path(file_state_records.get(str(record_id)))
        for raw_verdict in cast(list[Any], verdicts):
            if not isinstance(raw_verdict, dict):
                continue
            verdict = cast(dict[str, Any], raw_verdict)
            path = verdict.get("path")
            classification = verdict.get("classification")
            if not isinstance(path, str) or not isinstance(classification, str):
                continue
            source = source_by_path.get(path)
            if source not in {"untracked", "ignored"} or classification == "secret":
                continue
            pattern = _derive_gatekeeper_pattern(path)
            _merge_pattern_entry(
                patterns,
                pattern,
                classification,
                path,
                event.position,
                record_id,
            )
            paths[path] = {
                "path": path,
                "classification": classification,
                "matched_rule": f"pattern_library:{path}",
                "source_record_ids": [record_id] if isinstance(record_id, str) else [],
                "last_position": event.position,
                "source_kinds": ["untracked", "ignored"],
            }
    return {
        "patterns": {pattern: patterns[pattern] for pattern in sorted(patterns)},
        "paths": {path: paths[path] for path in sorted(paths)},
    }


def project_gatekeeper_report(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    """Project gatekeeper cost, hit-rate, and pattern-library growth per run."""
    reports: dict[str, dict[str, Any]] = {}
    prefixes: dict[str, list[EventEnvelope]] = {}
    for event in events:
        run = reports.setdefault(event.run_id, _empty_gatekeeper_report(event.run_id))
        prefixes.setdefault(event.run_id, []).append(event)
        if event.event_type == "file_state_accepted":
            classifications = _payload_entries(event.payload, "classifications")
            deterministic = sum(
                1 for entry in classifications if entry.get("needs_gatekeeper") is not True
            )
            unresolved = sum(
                1 for entry in classifications if entry.get("needs_gatekeeper") is True
            )
            run["deterministic_classifications"] += deterministic
            run["unresolved_residue"] += unresolved
            run["boundary_count"] += 1
            library = project_pattern_library(prefixes[event.run_id])
            run["pattern_library_size_over_time"].append(
                {
                    "position": event.position,
                    "file_state_record_id": event.payload.get("record_id"),
                    "size": len(library["patterns"]),
                }
            )
        elif event.event_type == "gatekeeper_verdict_recorded":
            verdicts = event.payload.get("verdicts")
            resolved = len(cast(list[Any], verdicts)) if isinstance(verdicts, list) else 0
            run["gatekeeper_resolved"] += resolved
            run["unresolved_residue"] = max(0, int(run["unresolved_residue"]) - resolved)
            library = project_pattern_library(prefixes[event.run_id])
            run["pattern_library_size_over_time"].append(
                {
                    "position": event.position,
                    "file_state_record_id": event.payload.get("file_state_record_id"),
                    "size": len(library["patterns"]),
                }
            )
        elif event.event_type == "gatekeeper_cost_recorded":
            try:
                cost = GatekeeperCostRecordedPayload.model_validate(event.payload)
            except ValueError:
                continue
            cost_payload = cost.model_dump(mode="json")
            run["gatekeeper_consults"] += 1
            run["gen_ai_usage_input_tokens"] += cost.gen_ai_usage_input_tokens
            run["gen_ai_usage_output_tokens"] += cost.gen_ai_usage_output_tokens
            run["gen_ai_usage_cache_read_input_tokens"] += cost.gen_ai_usage_cache_read_input_tokens
            run["gen_ai_usage_cache_creation_input_tokens"] += (
                cost.gen_ai_usage_cache_creation_input_tokens
            )
            run["cost_usd"] += cost.cost_usd
            run["wall_time_ms"] += cost.wall_time_ms
            _record_model_cost(run, cost_payload)

    for run in reports.values():
        total_classified = int(run["deterministic_classifications"]) + int(
            run["gatekeeper_resolved"]
        )
        run["total_classified"] = total_classified
        run["hit_rate"] = (
            float(run["deterministic_classifications"]) / total_classified
            if total_classified
            else 0.0
        )
        run["pattern_library_size"] = (
            int(run["pattern_library_size_over_time"][-1]["size"])
            if run["pattern_library_size_over_time"]
            else 0
        )
    return reports


def _project(events: list[EventEnvelope]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def build_projection(events: list[EventEnvelope]) -> GraphProjection:
    """Fold *events* into a full :class:`GraphProjection`.

    Public entry point for callers (e.g. read-model presenters) that need to
    fold the event stream once and pass the result into the various
    ``project_*`` view functions via their ``projection=`` argument, avoiding
    a full re-fold per view.
    """
    return _project(events)


def project_graph_projection_snapshot(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> GraphProjectionSnapshot:
    """Build the pure policy view consumed by graph-run drivers.

    ``projection`` may be a transactional materialization of an event prefix.
    Callers still provide the complete event sequence when event-only reason
    fields are needed, but avoid folding that sequence again.
    """
    projection = projection if projection is not None else build_projection(events)
    leases = project_leases(events, projection=projection)
    node_states = project_node_states(events, projection=projection)
    active_leases = {
        lease_id: lease for lease_id, lease in leases.items() if lease.get("state") == "active"
    }
    return GraphProjectionSnapshot(
        run_state=project_run_state(events, projection=projection),
        ready_nodes=project_ready_nodes(events, projection=projection),
        active_leases=active_leases,
        schedulable_nodes=[
            node_id
            for node_id, state in node_states.items()
            if state in {"planned", "blocked", "ready"}
        ],
        task_states=project_task_states(events, projection=projection),
        node_states=node_states,
        failed_node_reasons=_project_failed_node_reasons(events),
        node_deferral_reasons=_project_node_deferral_reasons(events),
        missing_input_sources=_project_missing_input_sources(projection, events),
        environment_failures={
            task_region_id: failure.model_copy(deep=True)
            for task_region_id, failure in projection["environment_failures"].items()
        },
        node_max_attempts=project_node_max_attempts(events),
    )


def project_node_max_attempts(events: list[EventEnvelope]) -> dict[str, int]:
    """Return first-declared executable retry budgets keyed by node id."""
    max_attempts: dict[str, int] = {}
    for event in events:
        if event.event_type != "node_created":
            continue
        node_id = event.payload.get("node_id")
        if not isinstance(node_id, str) or node_id in max_attempts:
            continue
        value = event.payload.get("max_attempts")
        if isinstance(value, int) and not isinstance(value, bool):
            max_attempts[node_id] = value
    return max_attempts


def project_graph_completion_eligible(projection: GraphProjectionSnapshot) -> bool:
    return (
        projection.run_state == "active"
        and bool(projection.task_states)
        and all(state == "accepted" for state in projection.task_states.values())
    )


def project_graph_outcome(run_id: str, projection: GraphProjectionSnapshot) -> GraphRunOutcome:
    if projection.run_state == "completed":
        return GraphRunOutcome(run_id=run_id, run_state=projection.run_state, completed=True)
    return GraphRunOutcome(
        run_id=run_id,
        run_state=projection.run_state,
        completed=False,
        blocked_reason=project_graph_blocked_reason(projection),
    )


def project_graph_blocked_reason(projection: GraphProjectionSnapshot) -> str:
    if projection.run_state in {"paused", "pausing"}:
        return "graph paused"
    if projection.run_state in {"failed", "cancelled"}:
        return f"graph {projection.run_state}"
    if projection.run_state is None:
        return "graph has not started"
    if projection.ready_nodes:
        return f"graph has ready node(s) not dispatched: {', '.join(sorted(projection.ready_nodes)[:3])}"
    if projection.active_leases:
        leased_nodes = sorted(
            str(lease.get("node_id"))
            for lease in projection.active_leases.values()
            if lease.get("node_id") is not None
        )
        if leased_nodes:
            return f"graph has active lease(s) without callback: {', '.join(leased_nodes[:3])}"
    missing_input_nodes = _project_nonterminal_node_details(projection, require_missing_input=True)
    if missing_input_nodes:
        suffix = "" if len(missing_input_nodes) <= 3 else f" (+{len(missing_input_nodes) - 3} more)"
        return (
            "graph quiescent with non-terminal node(s): "
            + ", ".join(missing_input_nodes[:3])
            + suffix
        )
    failed_nodes = sorted(
        node_id for node_id, state in projection.node_states.items() if state == "failed"
    )
    if failed_nodes:
        details = [
            f"{node_id}: {reason}"
            if (reason := projection.failed_node_reasons.get(node_id))
            else node_id
            for node_id in failed_nodes[:3]
        ]
        suffix = "" if len(failed_nodes) <= 3 else f" (+{len(failed_nodes) - 3} more)"
        return f"graph has failed node(s): {', '.join(details)}{suffix}"
    nonterminal_nodes = _project_nonterminal_node_details(projection)
    if nonterminal_nodes:
        suffix = "" if len(nonterminal_nodes) <= 3 else f" (+{len(nonterminal_nodes) - 3} more)"
        return (
            f"graph quiescent with non-terminal node(s): {', '.join(nonterminal_nodes[:3])}{suffix}"
        )
    if projection.environment_failures:
        details: list[str] = []
        for task_region_id, failure in sorted(projection.environment_failures.items())[:3]:
            label = failure.classification or "environment"
            details.append(
                f"{task_region_id}: {label}: {failure.reason}"
                if failure.reason
                else f"{task_region_id}: {label}"
            )
        suffix = (
            ""
            if len(projection.environment_failures) <= 3
            else f" (+{len(projection.environment_failures) - 3} more)"
        )
        return f"graph needs human/operator help for check environment issue(s): {', '.join(details)}{suffix}"
    blocked_tasks = sorted(
        f"{task_id}={state}"
        for task_id, state in projection.task_states.items()
        if state != "accepted"
    )
    if blocked_tasks:
        suffix = "" if len(blocked_tasks) <= 3 else f" (+{len(blocked_tasks) - 3} more)"
        return f"graph quiescent with non-accepted task(s): {', '.join(blocked_tasks[:3])}{suffix}"
    return "graph quiescent without completion"


def project_active_lease_wait_plan(
    projection: GraphProjectionSnapshot, now: datetime
) -> ActiveLeaseWaitPlan:
    execution_ids: set[str] = set()
    timeouts: list[float] = []
    for lease in projection.active_leases.values():
        execution_id = lease.get("execution_id")
        if isinstance(execution_id, str) and execution_id:
            execution_ids.add(execution_id)
        expires_at = lease.get("expires_at")
        if not isinstance(expires_at, str):
            continue
        try:
            expires_at_dt = datetime.fromisoformat(expires_at)
        except ValueError:
            continue
        if expires_at_dt.tzinfo is None:
            expires_at_dt = expires_at_dt.replace(tzinfo=UTC)
        timeouts.append(max(0.0, (expires_at_dt - now).total_seconds()))
    if not execution_ids:
        return ActiveLeaseWaitPlan(execution_ids=set(), timeout_seconds=0.0)
    if not timeouts:
        return ActiveLeaseWaitPlan(execution_ids=execution_ids, timeout_seconds=None)
    return ActiveLeaseWaitPlan(execution_ids=execution_ids, timeout_seconds=min(timeouts))


def _project_failed_node_reasons(events: list[EventEnvelope]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for event in events:
        node_id = event.payload.get("node_id")
        if not isinstance(node_id, str):
            continue
        if event.event_type == "agent_died":
            reason = event.payload.get("reason")
        elif (
            event.event_type == "node_state_changed" and event.payload.get("new_state") == "failed"
        ):
            reason = event.payload.get("reason")
        else:
            continue
        if isinstance(reason, str):
            reasons[node_id] = reason
    return reasons


def _project_node_deferral_reasons(events: list[EventEnvelope]) -> dict[str, str]:
    return {
        node_id: reason
        for event in events
        if event.event_type == "node_deferred"
        and isinstance((node_id := event.payload.get("node_id")), str)
        and isinstance((reason := event.payload.get("reason")), str)
    }


def _project_missing_input_sources(
    projection: GraphProjection, events: list[EventEnvelope]
) -> dict[str, list[str]]:
    details: dict[str, list[str]] = {}
    for node_id, reason in _project_node_deferral_reasons(events).items():
        if not reason.startswith("missing_required_input:"):
            continue
        missing_port = reason.removeprefix("missing_required_input:")
        sources = sorted(
            f"{missing_port} from {edge.from_node_id}={projection['node_states'].get(edge.from_node_id, 'unknown')}"
            for edge in projection["edges"].values()
            if edge.to_node_id == node_id and edge.to_port == missing_port
        )
        if sources:
            details[node_id] = sources
    return details


def _project_nonterminal_node_details(
    projection: GraphProjectionSnapshot, *, require_missing_input: bool = False
) -> list[str]:
    details: list[str] = []
    for node_id, state in projection.node_states.items():
        if state in TERMINAL_GRAPH_NODE_STATES:
            continue
        reason = projection.node_deferral_reasons.get(node_id)
        if require_missing_input and not (
            isinstance(reason, str) and reason.startswith("missing_required_input:")
        ):
            continue
        detail = f"{node_id}={state}"
        if reason is not None:
            detail = f"{detail}: {reason}"
        if sources := projection.missing_input_sources.get(node_id):
            detail = f"{detail} ({'; '.join(sources[:3])})"
        details.append(detail)
    return sorted(details)


def _has_full_event_history(events: list[EventEnvelope]) -> bool:
    return bool(events) and events[0].position <= 1


_PENDING_DECISION_STATES = {"planned", "blocked", "ready", "leased", "running", "suspended"}


def _latest_node_creation_payloads(
    events: list[EventEnvelope],
) -> dict[str, NodeCreationProjection]:
    payloads: dict[str, NodeCreationProjection] = {}
    for event in events:
        if event.event_type != "node_created":
            continue
        payload = _node_creation_from_event(event)
        if payload is not None:
            payloads[payload.node_id] = payload
    return payloads


def _record_latest_decision(
    decisions: dict[str, OversightDecisionProjection],
    payload: OversightDecisionRecordedPayload,
    position: int,
) -> None:
    projection_payload = payload.model_dump(mode="json")
    projection_payload["position"] = position
    if projection_payload.get("node_id") is None and payload.appeal_node_id is not None:
        projection_payload["node_id"] = payload.appeal_node_id
    decision = _oversight_decision_from_payload(projection_payload)
    if decision is None:
        return
    decisions[decision.node_id] = decision
    if decision.appeal_node_id is not None:
        decisions[decision.appeal_node_id] = decision


def _record_latest_approval_decision(
    decisions: dict[str, ApprovalDecisionProjection],
    payload: ApprovalDecisionRecordedPayload,
) -> None:
    decision = _approval_decision_from_payload(payload.model_dump(mode="json"))
    if decision is None:
        return
    decisions[decision.node_id] = decision
    if decision.appeal_node_id is not None:
        decisions[decision.appeal_node_id] = decision


def _record_latest_authority_decision(
    decisions: dict[str, AuthorityDecisionProjection],
    payload: AuthorityDecisionRecordedPayload,
) -> None:
    decision = _authority_decision_from_payload(payload.model_dump(mode="json"))
    if decision is None:
        return
    decisions[decision.node_id] = decision
    if decision.appeal_node_id is not None:
        decisions[decision.appeal_node_id] = decision


def _approval_decision_from_payload(
    payload: dict[str, Any],
) -> ApprovalDecisionProjection | None:
    try:
        return ApprovalDecisionProjection.model_validate(payload)
    except ValueError:
        return None


def _authority_decision_from_payload(
    payload: dict[str, Any],
) -> AuthorityDecisionProjection | None:
    try:
        return AuthorityDecisionProjection.model_validate(payload)
    except ValueError:
        return None


def _oversight_decision_from_payload(
    payload: dict[str, Any],
) -> OversightDecisionProjection | None:
    try:
        return OversightDecisionProjection.model_validate(payload)
    except ValueError:
        return None


def _record_callback_idempotency_event(state: GraphProjection, event: EventEnvelope) -> None:
    callback_event = _callback_idempotency_event_from_envelope(event)
    if callback_event is None:
        return
    key = _callback_idempotency_projection_key(
        callback_event.node_id,
        callback_event.idempotency_key,
    )
    state["callback_idempotency_events"].setdefault(key, callback_event)


def _callback_idempotency_event_from_envelope(
    event: EventEnvelope,
) -> CallbackIdempotencyEvent | None:
    # Projection/light/node-detail rows intentionally omit callback bodies and
    # idempotency keys; only full and summary-rebuild rows carry this state.
    if not {"idempotency_key", "payload"} <= event.payload.keys():
        return None
    payload = CallbackAcceptedPayload.model_validate(event.payload)
    callback_payload = payload.model_dump(mode="json")
    callback_payload["event_type"] = event.event_type
    callback_payload["outcome"] = event.event_type
    return _callback_idempotency_event_from_payload(callback_payload)


def _callback_idempotency_event_from_payload(
    payload: dict[str, Any],
) -> CallbackIdempotencyEvent | None:
    try:
        return CallbackIdempotencyEvent.model_validate(payload)
    except ValueError:
        return None


def _callback_idempotency_projection_key(node_id: str, idempotency_key: str) -> str:
    return f"{node_id}\0{idempotency_key}"


def _record_decision_request_details(
    state: GraphProjection,
    record: AcceptedOutputRecordPayload,
) -> None:
    if not isinstance(record, DecisionRequestRecord | AuthorityRequestRecord):
        return
    projected = _request_details_from_value(record.value.model_dump(mode="json"))
    if projected is not None:
        state["decision_request_details"][record.producer_node_id] = projected


def _request_details_for_pending_gate(
    node_id: str,
    payload: NodeCreationProjection | None,
    request_details: dict[str, PendingGateDecisionProjection],
) -> PendingGateDecision:
    details = request_details.get(node_id)
    if details is not None:
        return _pending_gate_decision_payload(details)
    if payload is None:
        return {}
    for key in ("decision_request", "authority_request_record", "authority_request"):
        raw_request = getattr(payload, key)
        if isinstance(raw_request, dict):
            return _pending_gate_decision_payload(
                _request_details_from_value(cast(dict[str, Any], raw_request))
            )
    return {}


def _request_details_from_value(value: dict[str, Any]) -> PendingGateDecisionProjection | None:
    details: PendingGateDecision = {}
    options = value.get("options")
    if isinstance(options, list):
        string_options = [option for option in cast(list[Any], options) if isinstance(option, str)]
        if string_options:
            details["options"] = string_options
    requested_authority = value.get("requested_authority")
    if isinstance(requested_authority, list):
        authorities = [
            authority
            for authority in cast(list[Any], requested_authority)
            if isinstance(authority, str)
        ]
        if authorities:
            details["requested_authority"] = authorities
    for source_key, target_key in (
        ("default_option", "default_option"),
        ("consequence_summary", "consequence_summary"),
        ("expires_at", "expires_at"),
        ("target_node_id", "target_node_id"),
        ("target_region_id", "target_region_id"),
    ):
        value_field = value.get(source_key)
        if isinstance(value_field, str) and value_field:
            details[target_key] = value_field
    return _pending_gate_decision_from_payload(cast(dict[str, Any], details))


def _gate_type(
    node_id: str,
    payload: NodeCreationProjection | None,
    projection: GraphProjection,
) -> str:
    if payload is None:
        return projection["node_roles"].get(node_id) or "approval"
    for key in ("gate_type", "approval_type", "reason", "role"):
        value = getattr(payload, key)
        if isinstance(value, str) and value:
            return value
    role = projection["node_roles"].get(node_id)
    if role is not None:
        return role
    return "approval"


def _gate_prompt(payload: NodeCreationProjection | None) -> str | None:
    if payload is None:
        return None
    for key in ("prompt", "approval_prompt", "human_prompt", "message", "reason"):
        value = getattr(payload, key)
        if isinstance(value, str) and value:
            return value
    return None


def _decision_outcome(payload: OversightDecisionProjection | None) -> str | None:
    if payload is None:
        return None
    return payload.decision


def _review_blocker(
    node_id: str,
    state: str,
    payload: NodeCreationProjection | None,
    latest_deferrals: dict[str, str],
) -> str:
    if payload is not None:
        for key in ("blocker", "blocker_reason", "reason"):
            value = getattr(payload, key)
            if isinstance(value, str) and value:
                return f"{node_id}: {value}"
    reason = latest_deferrals.get(node_id)
    if reason is not None:
        return f"{node_id}: {reason}"
    return f"{node_id}: {state}"


def _scheduler_bucket_for_reason(
    reason: str,
) -> Literal["blocked", "waiting_resources", "waiting_gates"]:
    if reason.startswith("resource_") or reason.startswith("invalid_claim:"):
        return "waiting_resources"
    if (
        reason.startswith("gate_")
        or reason.startswith("waiting_gate")
        or reason.startswith("authority_")
    ):
        return "waiting_gates"
    return "blocked"


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _node_creation_position(events: list[EventEnvelope], node_id: str) -> int:
    for event in events:
        if event.event_type != "node_created":
            continue
        payload = _node_created_payload_from_event(event)
        if payload is not None and payload.node_id == node_id:
            return event.position
    return 0


def _latest_lease_generation(events: list[EventEnvelope], node_id: str) -> int | None:
    generation: int | None = None
    for event in events:
        if event.event_type != "lease_granted" or event.payload.get("node_id") != node_id:
            continue
        value = event.payload.get("generation")
        if isinstance(value, int) and not isinstance(value, bool):
            generation = value
    return generation


def _planner_region_label(
    events: list[EventEnvelope],
    projection: GraphProjection,
    node_id: str,
) -> str | None:
    label = projection["planner_region_labels"].get(node_id)
    if label is not None:
        return label
    generation_index = projection["planner_generations"].get(node_id)
    if generation_index is None:
        return None
    labels = _seeded_planner_chain_labels(events)
    return labels.get(generation_index)


def _seeded_planner_chain_labels(events: list[EventEnvelope]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for event in events:
        if event.event_type != "node_created":
            continue
        payload = _node_created_payload_from_event(event)
        if payload is None or payload.planner_chain is None:
            continue
        for region in payload.planner_chain.regions:
            generation_index = region.generation_index
            region_label = region.region_label
            if (
                isinstance(generation_index, int)
                and not isinstance(generation_index, bool)
                and isinstance(region_label, str)
            ):
                labels.setdefault(generation_index, region_label)
    return labels


def _planner_generation_state(events: list[EventEnvelope], lease_id: str) -> str:
    state = "active"
    for event in events:
        if event.payload.get("lease_id") != lease_id:
            continue
        if event.event_type == "lease_suspended":
            state = "suspended"
        elif event.event_type == "lease_released":
            state = "released"
        elif event.event_type == "lease_revoked":
            state = "revoked"
        elif event.event_type == "lease_expired":
            state = "expired"
    return state


def _ready_nodes(node_states: dict[str, str]) -> list[str]:
    return [node_id for node_id, node_state in node_states.items() if node_state == "ready"]


def _copy_latest_routine_snapshot_record(
    state: GraphProjection,
) -> LatestRoutineSnapshotRecord | None:
    record = state.get("latest_routine_snapshot_record")
    return _latest_routine_snapshot_from_checkpoint(record)


def _record_candidate(
    state: GraphProjection,
    record: AcceptedOutputRecordPayload,
    position: int,
) -> None:
    if not isinstance(record, CandidateRecord | OutputRecord):
        return
    task_region_id = record.task_region_id or state["node_task_regions"].get(
        record.producer_node_id
    )
    if task_region_id is None:
        return
    candidate_id = record.candidate_id or record.record_id
    attempt_number = record.attempt_number
    if attempt_number is None:
        attempt_number = state["node_attempts"].get(record.producer_node_id)
    if attempt_number is None:
        attempt_number = 0
    supersedes_task_region_ids: list[str] = []
    file_state_record_ids = list(record.file_state_record_ids)
    if isinstance(record, CandidateRecord):
        supersedes_task_region_ids.extend(record.supersedes_task_region_ids)
        if record.supersedes_task_region_id is not None:
            supersedes_task_region_ids.append(record.supersedes_task_region_id)
        if not file_state_record_ids:
            file_state_record_ids = list(record.value.file_state_record_ids)
    try:
        candidate = CandidateProjection.model_validate(
            {
                "candidate_id": candidate_id,
                "attempt_number": attempt_number,
                "position": position,
                "file_state_record_ids": file_state_record_ids,
                "supersedes_task_region_ids": supersedes_task_region_ids,
            }
        )
    except ValueError:
        return
    state["task_candidates"].setdefault(task_region_id, []).append(candidate)


def _record_verdict(
    state: GraphProjection,
    payload: VerificationOutcomePayload | VerificationPassedPayload | VerificationFailedPayload,
    position: int,
) -> None:
    candidate_id = payload.candidate_id
    try:
        verdict = VerifierVerdictProjection.model_validate(
            {
                "candidate_id": candidate_id,
                "verdict": payload.outcome,
                "position": position,
            }
        )
    except ValueError:
        return
    state["verifier_verdicts"][candidate_id] = verdict


def _record_recovery_node(state: GraphProjection, payload: NodeCreatedPayload) -> None:
    node_id = payload.node_id
    recovery_reason = payload.recovery_reason
    record_id = payload.recovery_of_record_id
    if not node_id:
        return
    if not isinstance(recovery_reason, str) or not recovery_reason:
        return
    if not isinstance(record_id, str) or not record_id:
        return
    if recovery_reason not in {"failed_required_check", "failed_verification"}:
        return
    state["recovery_nodes_by_record_id"].setdefault(record_id, []).append(
        RecoveryNodeIndexEntry(
            node_id=node_id,
            recovery_reason=recovery_reason,
        )
    )


def _record_completion_decision(
    state: GraphProjection,
    record: AcceptedOutputRecordPayload,
) -> None:
    if state["completion_decision_passed"]:
        return
    if not isinstance(record, CompletionDecisionRecord):
        return
    if record.value.status == "passed":
        state["completion_decision_passed"] = True


def _record_verification_result(
    state: GraphProjection,
    payload: VerificationOutcomePayload | VerificationPassedPayload | VerificationFailedPayload,
    event_type: str,
) -> None:
    candidate_id = payload.candidate_id
    if event_type == "verification_passed":
        if candidate_id not in state["passed_verification_candidate_ids"]:
            state["passed_verification_candidate_ids"].append(candidate_id)
    if event_type == "verification_failed":
        state["failed_verification_candidate_ids"][candidate_id] = True
    node_id = payload.verifier_node_id
    record_id = payload.record_id

    result_payload: dict[str, str] = {
        "node_id": node_id,
        "record_id": record_id,
    }
    if candidate_id:
        result_payload["candidate_id"] = candidate_id
    task_region_id = payload.task_region_id
    if task_region_id:
        result_payload["task_region_id"] = task_region_id
    try:
        result = VerificationResultProjection.model_validate(result_payload)
    except ValueError:
        return
    if event_type == "verification_passed":
        state["passed_verification_results_by_record_id"][record_id] = result
    else:
        state["failed_verification_results_by_record_id"][record_id] = result


def _record_check_result(
    state: GraphProjection,
    record: AcceptedOutputRecordPayload,
    position: int,
) -> None:
    if not isinstance(record, CheckResultRecord):
        return
    node_id = record.producer_node_id
    status = record.value.status
    task_region_id = record.task_region_id or state["node_task_regions"].get(node_id)
    result_payload: dict[str, Any] = {
        "node_id": node_id,
        "status": status,
        "position": position,
    }
    for key in ("classification", "command_text", "stderr_tail", "stdout_tail", "exit_code"):
        value = getattr(record.value, key)
        if value is not None:
            result_payload[key] = value
    if task_region_id is not None:
        result_payload["task_region_id"] = task_region_id
    result_payload["record_id"] = record.record_id
    for field in ("candidate_record_ids", "file_state_record_ids", "evaluated_record_ids"):
        record_ids = getattr(record, field) or getattr(record.value, field)
        if record_ids:
            result_payload[field] = record_ids
    try:
        result = CheckResultProjection.model_validate(result_payload)
    except ValueError:
        return
    state["check_results"][node_id] = result


def _copy_output_record_payload(
    payload: AcceptedOutputRecordPayload,
) -> AcceptedOutputRecordPayload:
    return payload.model_copy(deep=True)


def _output_record_payload_dict(payload: AcceptedOutputRecordPayload) -> dict[str, Any]:
    return payload.model_dump(mode="json")


def _parse_output_record_payload(
    payload: dict[str, Any],
) -> AcceptedOutputRecordPayload | None:
    try:
        return OutputRecordAcceptedPayload.model_validate(payload).root
    except ValueError:
        return None


def _record_node_output_port(
    state: GraphProjection,
    record: AcceptedOutputRecordPayload,
    position: int,
) -> None:
    node_id = record.producer_node_id
    if not node_id:
        return
    port = record.port
    record_id = record.record_id or f"accepted-record:{position}"
    ports = state["node_output_ports"].setdefault(node_id, {})
    records = ports.setdefault(port, [])
    if record_id not in records:
        records.append(record_id)


def _record_accepted_output_record(
    state: GraphProjection,
    record: AcceptedOutputRecordPayload,
) -> None:
    node_id = record.producer_node_id
    port = record.port
    record_id = record.record_id
    if not node_id or not port or not record_id:
        return
    ports = state["accepted_output_records_by_node_port"].setdefault(node_id, {})
    records = ports.setdefault(port, [])
    records.append(
        {
            "record_id": record_id,
            "payload": record,
        }
    )


def _record_accepted_record_summary(
    state: GraphProjection,
    record: AcceptedOutputRecordPayload,
) -> None:
    record_type = record.record_type
    if record_type is None:
        return
    summary: GraphRecordSummary = {
        "record_id": record.record_id,
        "record_kind": record.record_kind,
        "schema": record.schema_,
        "producer_port": record.port,
        "record_type": record_type,
    }
    if record.producer_node_id is not None:
        summary["producer_node_id"] = record.producer_node_id
    state["accepted_record_summaries_by_id"][record.record_id] = summary


def _record_output_record(state: GraphProjection, record: AcceptedOutputRecordPayload) -> None:
    if record.producer_node_id is None:
        return
    state["output_records_by_node_port"].setdefault(record.producer_node_id, {}).setdefault(
        record.port,
        [],
    ).append(record)


def _record_output_payload(state: GraphProjection, record: AcceptedOutputRecordPayload) -> None:
    if record.record_id:
        state["output_record_payloads"][record.record_id] = record


def _record_latest_routine_snapshot(
    state: GraphProjection,
    record: AcceptedOutputRecordPayload,
) -> None:
    if not isinstance(record, RoutineSnapshotRecord):
        return
    state["latest_routine_snapshot_record"] = LatestRoutineSnapshotRecord(
        record_id=record.record_id,
        producer_node_id=record.producer_node_id,
        port=record.port,
    )


def _record_open_appeal(
    state: GraphProjection, payload: AppealOpenedPayload, position: int
) -> None:
    appealed_node_id = payload.appealed_node_id
    state["node_pending_appeals"][appealed_node_id] = True

    task_region_id = payload.task_region_id
    candidate_id = payload.candidate_id
    if task_region_id is None and candidate_id is not None:
        task_region_id = _task_region_for_candidate(state, candidate_id)
    if task_region_id is None:
        return
    if payload.appeal_type == "invalid_test":
        block_payload = _invalid_test_block_payload(
            state["invalid_test_blocks"].get(task_region_id)
        )
        block_payload.update(
            {
                "appeal_open": True,
                "candidate_id": candidate_id,
                "position": position,
            }
        )
        block = _invalid_test_block_from_payload(block_payload)
        if block is not None:
            state["invalid_test_blocks"][task_region_id] = block


def _record_oversight_decision(
    state: GraphProjection,
    payload: OversightDecisionRecordedPayload,
    position: int,
) -> None:
    appealed_node_id = payload.appealed_node_id
    if isinstance(appealed_node_id, str):
        state["node_pending_appeals"][appealed_node_id] = False

    task_region_id = payload.task_region_id
    candidate_id = payload.candidate_id
    if task_region_id is None and candidate_id is not None:
        task_region_id = _task_region_for_candidate(state, candidate_id)
    if task_region_id is None:
        return

    decision = payload.decision
    appeal_type = payload.appeal_type
    accepted_invalid_test = decision in {"accepted", "invalid_test_accepted"} and (
        appeal_type in {None, "invalid_test"} or decision == "invalid_test_accepted"
    )
    if accepted_invalid_test:
        block = _invalid_test_block_from_payload(
            {
                "accepted": True,
                "candidate_id": candidate_id,
                "position": position,
            }
        )
        if block is not None:
            state["invalid_test_blocks"][task_region_id] = block


def _record_gate_decision(state: GraphProjection, payload: ApprovalDecisionRecordedPayload) -> None:
    task_region_id = payload.task_region_id
    node_id = payload.node_id
    decision = payload.decision
    passed = decision == "approved"
    state["node_gate_decisions"][node_id] = passed
    if task_region_id is None:
        task_region_id = state["node_task_regions"].get(node_id)
    if task_region_id is None:
        return
    gate_id = payload.gate_id
    if gate_id is None:
        gate_id = node_id
    state["gate_decisions"].setdefault(task_region_id, {})[gate_id] = passed


def _record_authority_decision(
    state: GraphProjection, payload: AuthorityDecisionRecordedPayload
) -> None:
    node_id = payload.node_id
    decision = payload.decision
    passed = decision == "granted"
    state["node_gate_decisions"][node_id] = passed


def _clear_authority_revision_blocker(
    state: GraphProjection, payload: AuthorityDecisionRecordedPayload
) -> None:
    if payload.decision != "granted":
        return
    revision_id = _authority_decision_revision_id(payload)
    if revision_id is not None:
        state["authority_revision_blockers"].pop(revision_id, None)


def _authority_decision_revision_id(payload: AuthorityDecisionRecordedPayload) -> str | None:
    scope_value: object = payload.scope
    if isinstance(scope_value, dict):
        scope = cast(dict[str, Any], scope_value)
        for key in ("revision_id", "requirement_version_id", "version_id"):
            value = scope.get(key)
            if isinstance(value, str) and value:
                return value
    return payload.record_id


def _record_edge(state: GraphProjection, event: EventEnvelope) -> None:
    from_node_id = event.payload.get("from_node_id")
    from_port = event.payload.get("from_port")
    to_node_id = event.payload.get("to_node_id")
    to_port = event.payload.get("to_port")
    if not all(isinstance(value, str) for value in (from_node_id, from_port, to_node_id, to_port)):
        return

    edge_id = event.payload.get("edge_id")
    if not isinstance(edge_id, str):
        edge_id = f"{from_node_id}:{from_port}->{to_node_id}:{to_port}"
    required = event.payload.get("required")
    dependency_type = event.payload.get("dependency_type", "input_binding")
    if not isinstance(dependency_type, str):
        dependency_type = "input_binding"
    edge_payload: dict[str, Any] = {
        "edge_id": edge_id,
        "from_node_id": from_node_id,
        "from_port": from_port,
        "to_node_id": to_node_id,
        "to_port": to_port,
        "required": _edge_required(required),
        "dependency_type": dependency_type,
    }
    for key in ("from_node_kind", "from_node_role"):
        value = event.payload.get(key)
        if isinstance(value, str) and value:
            edge_payload[key] = value
    selector = event.payload.get("accepted_record_selector")
    if isinstance(selector, dict):
        edge_payload["accepted_record_selector"] = normalize_record_selector(selector)
    for key in _EDGE_METADATA_KEYS:
        if key not in event.payload:
            continue
        value = event.payload[key]
        if isinstance(value, dict):
            edge_payload[key] = dict(cast(dict[str, Any], value))
        elif isinstance(value, list):
            edge_payload[key] = list(cast(list[Any], value))
        elif isinstance(value, str | int | float | bool):
            edge_payload[key] = value
    edge = _edge_from_payload(edge_payload)
    if edge is not None:
        state["edges"][edge_id] = edge


def _edge_required(value: Any) -> bool:
    if value is False:
        return False
    if isinstance(value, int) and not isinstance(value, bool) and value == 0:
        return False
    return True


def _record_requirement_revision(state: GraphProjection, event: EventEnvelope) -> None:
    payload = RequirementRevisionPayload.model_validate(event.payload).model_dump(mode="json")
    requirement_id = payload.get("requirement_id")
    if not isinstance(requirement_id, str):
        return

    version_id = payload.get("version_id")
    if not isinstance(version_id, str):
        version_id = payload.get("requirement_version_id")
    if not isinstance(version_id, str):
        version_id = f"{requirement_id}.v{event.position}"

    classification = _requirement_revision_classification(payload)
    requires_authority = _requires_explicit_requirement_authority(payload, classification)
    revision_payload: dict[str, Any] = {
        "requirement_id": requirement_id,
        "version_id": version_id,
        "change_classification": classification,
        "requires_authority": requires_authority,
        "position": event.position,
    }
    previous_version_id = payload.get("previous_version_id")
    if isinstance(previous_version_id, str):
        revision_payload["previous_version_id"] = previous_version_id
    revision_index = payload.get("revision_index")
    if isinstance(revision_index, int) and not isinstance(revision_index, bool):
        revision_payload["revision_index"] = revision_index
    authority_reason = _authority_required_reason(payload, classification)
    if authority_reason is not None:
        revision_payload["authority_required_reason"] = authority_reason
    validation_strengthening = (
        payload.get("validation_strengthening") is True
        or classification == "validation_strengthening"
    )
    revision_payload["validation_strengthening"] = validation_strengthening

    revision = _requirement_revision_from_payload(revision_payload)
    if revision is None:
        return
    state["requirement_revisions"][version_id] = revision
    if payload.get("active") is not False:
        state["active_requirement_versions"][requirement_id] = version_id
    if validation_strengthening:
        _mark_superseded_support_stale(state, requirement_id, version_id)


def _record_support_evidence(state: GraphProjection, event: EventEnvelope) -> None:
    payload = SupportEvidencePayload.model_validate(event.payload).model_dump(mode="json")
    support_id = payload.get("support_id")
    if not isinstance(support_id, str):
        support_id = payload.get("edge_id")
    if not isinstance(support_id, str):
        return

    evidence_id = payload.get("evidence_id")
    requirement_id = payload.get("requirement_id")
    if not isinstance(evidence_id, str) or not isinstance(requirement_id, str):
        return

    requirement_version_id = payload.get("requirement_version_id")
    if not isinstance(requirement_version_id, str):
        requirement_version_id = payload.get("version_id")
    if not isinstance(requirement_version_id, str):
        requirement_version_id = state["active_requirement_versions"].get(requirement_id)
    if not isinstance(requirement_version_id, str):
        return

    status = payload.get("status", "active")
    if not isinstance(status, str):
        status = "active"
    support_payload: dict[str, Any] = {
        "support_id": support_id,
        "evidence_id": evidence_id,
        "requirement_id": requirement_id,
        "requirement_version_id": requirement_version_id,
        "status": status,
        "position": event.position,
    }
    stale_reason = payload.get("stale_reason")
    if isinstance(stale_reason, str):
        support_payload["stale_reason"] = stale_reason
    confidence = payload.get("confidence")
    if isinstance(confidence, str):
        support_payload["confidence"] = confidence
    support = _support_evidence_from_payload(support_payload)
    if support is None:
        return
    state["support_evidence"][support_id] = support


def _mark_superseded_support_stale(
    state: GraphProjection,
    requirement_id: str,
    active_version_id: str,
) -> None:
    for support_id, support in list(state["support_evidence"].items()):
        if support.requirement_id != requirement_id:
            continue
        if support.requirement_version_id == active_version_id:
            continue
        state["support_evidence"][support_id] = support.model_copy(
            update={
                "status": "stale",
                "stale_reason": support.stale_reason
                or (
                    "Evidence was produced for an older requirement version and does not "
                    "prove the strengthened validation definition."
                ),
            },
            deep=True,
        )


def _support_stale_reason(
    projection: GraphProjection,
    support: SupportEvidenceProjection,
) -> str | None:
    status = support.status
    if status != "active":
        return support.stale_reason or f"support edge status is {status}"

    active_version_id = projection.get("active_requirement_versions", {}).get(
        support.requirement_id
    )
    if active_version_id is None:
        return "requirement has no active version"
    if support.requirement_version_id != active_version_id:
        return "support edge targets a superseded requirement version"
    return None


def _requirement_revision_from_payload(
    payload: dict[str, Any],
) -> RequirementRevisionProjection | None:
    try:
        return RequirementRevisionProjection.model_validate(payload)
    except ValueError:
        return None


def _support_evidence_from_payload(payload: dict[str, Any]) -> SupportEvidenceProjection | None:
    try:
        return SupportEvidenceProjection.model_validate(payload)
    except ValueError:
        return None


def _requirement_revision_classification(payload: dict[str, Any]) -> str:
    for key in ("change_classification", "classification", "revision_type"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    if payload.get("validation_strengthening") is True:
        return "validation_strengthening"
    if payload.get("new_behavior") is True:
        return "new_behavior"
    if payload.get("semantic_change") is True:
        return "semantic"
    return "initial"


def _requires_explicit_requirement_authority(
    payload: dict[str, Any],
    classification: str,
) -> bool:
    if payload.get("requires_authority") is True:
        return True
    if payload.get("explicit_authority_required") is True:
        return True
    if payload.get("new_behavior") is True or payload.get("behavior_change") is True:
        return True
    return classification in {
        "semantic",
        "semantic_change",
        "new_behavior",
        "scope_expansion",
        "scope_reduction",
        "priority_change",
    }


def _authority_required_reason(payload: dict[str, Any], classification: str) -> str | None:
    reason = payload.get("authority_required_reason")
    if isinstance(reason, str) and reason:
        return reason
    if not _requires_explicit_requirement_authority(payload, classification):
        return None
    if payload.get("new_behavior") is True or classification in {"new_behavior", "scope_expansion"}:
        return "new_behavior"
    if payload.get("behavior_change") is True:
        return "behavior_change"
    return classification


def _record_input_binding(
    state: GraphProjection,
    payload: InputBoundPayload,
) -> None:
    to_node_id = payload.to_node_id
    to_port = payload.to_port
    edge_id = payload.edge_id

    binding: dict[str, Any] = {
        "to_node_id": to_node_id,
        "to_port": to_port,
    }
    binding["edge_id"] = edge_id
    binding["record_ids"] = list(payload.record_ids)
    binding["bound_at_position"] = payload.bound_at_position
    if payload.trigger is not None:
        binding["trigger"] = payload.trigger
    if payload.supersedes_record_id is not None:
        binding["supersedes_record_id"] = payload.supersedes_record_id
    if payload.record_bound_positions:
        binding["record_bound_positions"] = dict(payload.record_bound_positions)
    existing_binding = state["input_bindings"].get(to_node_id, {}).get(to_port)
    policy = _binding_policy_for_input_event(state, binding, to_node_id, to_port)
    binding["binding_policy"] = policy
    if "edge_id" not in binding:
        edge = _edge_for_input_binding(state, binding, to_node_id, to_port)
        edge_id_from_projection = edge.edge_id if edge is not None else None
        if isinstance(edge_id_from_projection, str):
            binding["edge_id"] = edge_id_from_projection
    merged_ids = merge_bound_record_ids(
        policy,
        _bound_record_ids(existing_binding) if existing_binding is not None else [],
        _bound_record_ids_from_payload(binding),
        supersedes_record_id=binding.get("supersedes_record_id"),
    )
    if existing_binding is not None and merged_ids == _bound_record_ids(existing_binding):
        return
    binding["record_ids"] = merged_ids
    record_positions = _merged_record_bound_positions(existing_binding, binding, merged_ids)
    if record_positions:
        binding["record_bound_positions"] = record_positions
    typed_binding = _input_binding_from_payload(binding)
    if typed_binding is not None:
        state["input_bindings"].setdefault(to_node_id, {})[to_port] = typed_binding


def _binding_policy_for_input_event(
    state: GraphProjection,
    binding: dict[str, Any],
    to_node_id: str,
    to_port: str,
) -> str:
    edge = _edge_for_input_binding(state, binding, to_node_id, to_port)
    target_port = _target_port_for_binding(state, edge, to_node_id, to_port)
    if edge is not None:
        return binding_policy(edge.binding_policy, target_port)
    return binding_policy_for_edge(binding, target_port)


def _edge_for_input_binding(
    state: GraphProjection,
    binding: dict[str, Any],
    to_node_id: str,
    to_port: str,
) -> EdgeProjection | None:
    edge_id = binding.get("edge_id")
    if isinstance(edge_id, str):
        edge = state["edges"].get(edge_id)
        if edge is not None:
            return edge
    for edge in state["edges"].values():
        if edge.to_node_id == to_node_id and edge.to_port == to_port:
            return edge
    return None


def _target_port_for_binding(
    state: GraphProjection,
    edge: EdgeProjection | None,
    to_node_id: str,
    to_port: str,
) -> PortContract | None:
    if edge is not None:
        _, target_port = _edge_port_contracts(edge, state)
        if target_port is not None:
            return target_port
    target_kind = state["node_kinds"].get(to_node_id)
    if target_kind is None:
        return None
    target_role = state["node_roles"].get(to_node_id)
    contract = DEFAULT_NODE_CONTRACTS.contract_for(target_kind, target_role)
    if contract is None:
        return None
    return input_port_contract(contract, to_port)


def _merged_record_bound_positions(
    existing_binding: InputBindingProjection | None,
    incoming_binding: dict[str, Any],
    merged_ids: list[str],
) -> dict[str, int]:
    positions: dict[str, int] = {}
    if existing_binding is not None:
        raw_existing_positions = existing_binding.record_bound_positions
        if isinstance(raw_existing_positions, dict):
            for record_id, position in cast(dict[Any, Any], raw_existing_positions).items():
                if isinstance(record_id, str) and isinstance(position, int):
                    positions[record_id] = position
        else:
            bound_at_position = existing_binding.bound_at_position
            for record_id in _bound_record_ids(existing_binding):
                positions.setdefault(record_id, bound_at_position)

    incoming_position = incoming_binding.get("bound_at_position")
    if not isinstance(incoming_position, int) or isinstance(incoming_position, bool):
        incoming_position = 0
    for record_id in _bound_record_ids_from_payload(incoming_binding):
        positions.setdefault(record_id, incoming_position)
    return {record_id: positions[record_id] for record_id in merged_ids if record_id in positions}


def _bound_record_ids_from_payload(binding: dict[str, Any]) -> list[str]:
    record_ids = binding.get("record_ids")
    if not isinstance(record_ids, list):
        return []
    return [record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)]


def _record_authority_change(state: GraphProjection, payload: NodeAuthorityChangedPayload) -> None:
    node_id = payload.node_id

    authority = payload.authority
    resource_claims = payload.resource_claims
    if "resource_claims" not in payload.model_fields_set and authority is not None:
        resource_claims = [
            ResourceClaimProjection.model_validate(claim.model_dump(mode="json"))
            for claim in authority.resource_claims
        ]
    if "resource_claims" in payload.model_fields_set or authority is not None:
        state["node_resource_claims"][node_id] = resource_claims

    allowed_actions = payload.allowed_actions
    if "allowed_actions" not in payload.model_fields_set and authority is not None:
        allowed_actions = authority.allowed_actions
    if "allowed_actions" in payload.model_fields_set or authority is not None:
        state["node_allowed_actions"][node_id] = allowed_actions

    preconditions = payload.preconditions
    if "preconditions" not in payload.model_fields_set and authority is not None:
        preconditions = authority.preconditions
    if "preconditions" in payload.model_fields_set or authority is not None:
        state["node_preconditions"][node_id] = preconditions


def _record_environment_failure(
    state: GraphProjection,
    record: AcceptedOutputRecordPayload,
    position: int,
) -> None:
    if not isinstance(record, CheckResultRecord):
        return
    task_region_id = record.task_region_id or state["node_task_regions"].get(
        record.producer_node_id
    )
    if task_region_id is None:
        return
    classification = record.value.classification
    is_environment = classification in {
        "environment_error",
        "tool_error",
        "tool_unavailable",
    }
    if not is_environment:
        return

    value = record.value.model_dump(mode="json")
    reason = _environment_failure_reason_from_check_value(value)
    failure = _environment_failure_from_payload(
        {
            **value,
            "node_id": record.producer_node_id,
            "record_id": record.record_id,
            "record_kind": record.record_kind,
            "record_type": record.record_type,
            "task_region_id": task_region_id,
            "position": position,
            "reason": reason,
        }
    )
    if failure is not None:
        state["environment_failures"][task_region_id] = failure


def _environment_failure_from_payload(
    payload: dict[str, Any],
) -> EnvironmentFailureProjection | None:
    try:
        return EnvironmentFailureProjection.model_validate(payload)
    except ValueError:
        return None


def _environment_failure_reason_from_check_value(value: dict[str, Any]) -> str:
    classification = value.get("classification")
    command_text = value.get("command_text")
    command_label = (
        command_text if isinstance(command_text, str) and command_text else "check command"
    )
    stderr = value.get("stderr_tail")
    if classification == "tool_unavailable":
        return f"check tool unavailable while running: {command_label}"
    if classification == "tool_error":
        return f"check tool error while running: {command_label}"
    if classification == "environment_error":
        return f"check environment setup failed while running: {command_label}"
    if isinstance(stderr, str) and stderr.strip():
        return stderr.strip().splitlines()[0]
    return "check failed because of the execution environment"


def _record_file_state(
    state: GraphProjection,
    payload: FileStateRecord,
    *,
    run_id: str,
    position: int,
) -> None:
    record = payload.model_copy(
        update={"run_id": run_id, "position": position},
    )
    state["file_state_records"][record.record_id] = record


def _record_gatekeeper_verdicts(
    state: GraphProjection,
    payload: GatekeeperVerdictRecordedPayload,
) -> None:
    record_id = payload.file_state_record_id
    record = state["file_state_records"].get(record_id)
    if record is None:
        return
    by_path = {verdict.path: verdict.model_dump(mode="json") for verdict in payload.verdicts}
    for key in ("classifications", "residue", "untracked", "ignored", "external"):
        entries = getattr(record, key)
        if not entries:
            continue
        setattr(record, key, [_resolved_file_entry(entry, by_path) for entry in entries])


def _record_cleanup_requested(state: GraphProjection, event: EventEnvelope) -> None:
    payload = _cleanup_requested_payload_from_event(event)
    if payload is None:
        return

    cleanup_id = payload.cleanup_id
    cleanup = _cleanup_requested_from_event(event)
    if cleanup is not None:
        state["cleanup_requested_events"].setdefault(cleanup_id, cleanup)

    record_id = payload.file_state_record_id
    if record_id is None:
        return
    record = state["file_state_records"].get(record_id)
    if record is None:
        return
    record.compromised = True
    record.superseded_pending = True
    record.cleanup_id = cleanup_id
    record.cleanup_reason = payload.reason
    record.compromised_paths = list(payload.paths)


def _record_cleanup_applied(state: GraphProjection, event: EventEnvelope) -> None:
    payload = _cleanup_applied_payload_from_event(event)
    if payload is None:
        return

    cleanup_id = payload.cleanup_id
    state["cleanup_applied_ids"][cleanup_id] = True

    record_id = payload.file_state_record_id
    if record_id is None:
        return
    record = state["file_state_records"].get(record_id)
    if record is None:
        return
    record.compromised = True
    record.superseded_pending = False
    record.superseded_by_record_id = payload.superseding_record_id
    record.cleanup_applied_event_id = event.event_id
    record.compromised_snapshot_deleted = payload.deleted_snapshot_ref is True


def _record_runtime_retry_scheduled(state: GraphProjection, event: EventEnvelope) -> None:
    payload = RuntimeRetryScheduledPayload.model_validate(event.payload)
    node_id = payload.node_id
    if not node_id:
        return
    value = payload.retry_not_before
    state["retry_not_before_by_node"][node_id] = value if value else None


def _resolved_file_entry(
    raw_entry: FileEntry | ExternalFileEntry,
    verdicts_by_path: dict[str, dict[str, Any]],
) -> FileEntry | ExternalFileEntry:
    entry = _file_entry_dict(raw_entry)
    path = entry.get("path")
    if not isinstance(path, str) or path not in verdicts_by_path:
        return raw_entry
    verdict = verdicts_by_path[path]
    entry["classification"] = verdict.get("classification")
    entry["matched_rule"] = f"gatekeeper:{verdict.get('model_id', 'unknown')}"
    entry["needs_gatekeeper"] = False
    entry["gatekeeper_confidence"] = verdict.get("confidence")
    entry["gatekeeper_rationale"] = verdict.get("rationale")
    if isinstance(raw_entry, ExternalFileEntry):
        return ExternalFileEntry.model_validate(entry)
    return FileEntry.model_validate(entry)


def _file_entry_dict(entry: FileEntry | ExternalFileEntry) -> dict[str, Any]:
    return entry.model_dump(mode="json")


def _file_state_record_from_payload(payload: dict[str, Any]) -> FileStateRecord | None:
    try:
        return FileStateRecord.model_validate(payload)
    except ValueError:
        return None


def _derive_gatekeeper_pattern(path: str) -> str:
    normalized = path.replace("\\", "/").strip("/")
    dirname, _, filename = normalized.rpartition("/")
    if not dirname:
        return filename
    stem, dot, extension = filename.rpartition(".")
    if dot and stem:
        glob = f"*.{extension}"
    else:
        glob = filename
    return f"{dirname}/{glob}"


def _merge_pattern_entry(
    patterns: dict[str, dict[str, Any]],
    pattern: str,
    classification: str,
    path: str,
    position: int,
    record_id: Any,
) -> None:
    entry = patterns.get(pattern)
    if entry is None:
        patterns[pattern] = {
            "pattern": pattern,
            "classification": classification,
            "occurrences": 1,
            "paths": [path],
            "source_record_ids": [record_id] if isinstance(record_id, str) else [],
            "source_kinds": ["untracked", "ignored"],
            "first_position": position,
            "last_position": position,
        }
        return
    entry["occurrences"] = int(entry["occurrences"]) + 1
    entry["last_position"] = position
    if path not in entry["paths"]:
        entry["paths"].append(path)
        entry["paths"].sort()
    if isinstance(record_id, str) and record_id not in entry["source_record_ids"]:
        entry["source_record_ids"].append(record_id)


def _file_state_source_by_path(record: dict[str, Any] | FileStateRecord | None) -> dict[str, str]:
    if record is None:
        return {}
    sources: dict[str, str] = {}
    if isinstance(record, FileStateRecord):
        entry_groups: tuple[list[FileEntry], list[FileEntry]] = (
            record.residue,
            record.classifications,
        )
        for entries in entry_groups:
            for raw_entry in entries:
                entry = _file_entry_dict(raw_entry)
                path = entry.get("path")
                source = entry.get("source")
                if isinstance(path, str) and isinstance(source, str):
                    sources[path] = source
        return sources

    for key in ("residue", "classifications"):
        raw_entries = record.get(key)
        if not isinstance(raw_entries, list):
            continue
        for raw_entry in cast(list[Any], raw_entries):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            path = entry.get("path")
            source = entry.get("source")
            if isinstance(path, str) and isinstance(source, str):
                sources[path] = source
    return sources


def _payload_entries(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [
        dict(cast(dict[str, Any], entry))
        for entry in cast(list[Any], value)
        if isinstance(entry, dict)
    ]


def _payload_number(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return int(value)
    return 0


def _payload_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _empty_gatekeeper_report(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "boundary_count": 0,
        "deterministic_classifications": 0,
        "gatekeeper_consults": 0,
        "gatekeeper_resolved": 0,
        "unresolved_residue": 0,
        "total_classified": 0,
        "hit_rate": 0.0,
        "pattern_library_size": 0,
        "pattern_library_size_over_time": [],
        "gen_ai_usage_input_tokens": 0,
        "gen_ai_usage_output_tokens": 0,
        "gen_ai_usage_cache_read_input_tokens": 0,
        "gen_ai_usage_cache_creation_input_tokens": 0,
        "cost_usd": 0.0,
        "wall_time_ms": 0,
        "models": {},
    }


def _record_model_cost(run: dict[str, Any], payload: dict[str, Any]) -> None:
    model_id = payload.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        model_id = "unknown"
    models = cast(dict[str, dict[str, Any]], run["models"])
    model = models.setdefault(
        model_id,
        {
            "model_id": model_id,
            "consults": 0,
            "gen_ai_usage_input_tokens": 0,
            "gen_ai_usage_output_tokens": 0,
            "gen_ai_usage_cache_read_input_tokens": 0,
            "gen_ai_usage_cache_creation_input_tokens": 0,
            "cost_usd": 0.0,
            "wall_time_ms": 0,
            "executions": [],
        },
    )
    model["consults"] += 1
    model["gen_ai_usage_input_tokens"] += _payload_number(payload, "gen_ai_usage_input_tokens")
    model["gen_ai_usage_output_tokens"] += _payload_number(payload, "gen_ai_usage_output_tokens")
    model["gen_ai_usage_cache_read_input_tokens"] += _payload_number(
        payload, "gen_ai_usage_cache_read_input_tokens"
    )
    model["gen_ai_usage_cache_creation_input_tokens"] += _payload_number(
        payload, "gen_ai_usage_cache_creation_input_tokens"
    )
    model["cost_usd"] += _payload_float(payload, "cost_usd")
    model["wall_time_ms"] += _payload_number(payload, "wall_time_ms")
    execution_id = payload.get("execution_id")
    if isinstance(execution_id, str) and execution_id not in model["executions"]:
        model["executions"].append(execution_id)


def _derive_task_states(state: GraphProjection) -> dict[str, str]:
    task_region_ids = set(state["task_candidates"])
    task_region_ids.update(state["invalid_test_blocks"])
    task_region_ids.update(state["configured_gates"])
    task_region_ids.update(state["gate_decisions"])
    task_region_ids.update(state["environment_failures"])
    task_region_ids.update(
        lease.task_region_id
        for lease in state["leases"].values()
        if lease.task_region_id is not None
    )
    task_region_ids.update(state["node_task_regions"].values())

    task_states: dict[str, str] = {}
    for task_region_id in sorted(task_region_ids):
        latest_candidate = _latest_candidate(state["task_candidates"].get(task_region_id, []))
        if latest_candidate is None:
            task_states[task_region_id] = _derive_candidate_free_region_state(
                state,
                task_region_id,
            )
            continue

        candidate_id = latest_candidate.candidate_id
        configured_gates = state["configured_gates"].get(task_region_id, {})
        gate_decisions = state["gate_decisions"].get(task_region_id, {})
        gates_passed = _all_configured_gates_passed(configured_gates, gate_decisions)
        invalid_block = state["invalid_test_blocks"].get(task_region_id)

        verifier_passed = _verifier_requirement_passed(state, task_region_id, candidate_id)
        verdict = state["verifier_verdicts"].get(candidate_id)
        file_state_accepted = _task_file_state_accepted(state, task_region_id, candidate_id)
        checks_passed = _required_checks_passed(state, task_region_id)
        verifier_failure_superseded = _failed_verification_recovery_superseded(
            state,
            task_region_id,
            candidate_id,
        )

        if verifier_passed and gates_passed and file_state_accepted and checks_passed:
            task_states[task_region_id] = "accepted"
        elif (
            invalid_block is not None
            and invalid_block.accepted is True
            and not _replacement_verification_passed(state, task_region_id, invalid_block)
        ):
            task_states[task_region_id] = "blocked_invalid_test"
        elif (
            verdict is not None
            and verdict.verdict == "failed"
            and not verifier_failure_superseded
            and not _active_invalid_test_override(invalid_block, candidate_id)
        ):
            task_states[task_region_id] = "needs_revision"
        elif task_region_id in state["environment_failures"]:
            task_states[task_region_id] = "blocked_environment"
        elif _has_active_task_lease(state, task_region_id):
            task_states[task_region_id] = "in_progress"
        else:
            task_states[task_region_id] = "pending"

    _apply_accepted_region_supersessions(state, task_states)
    return task_states


def _apply_accepted_region_supersessions(
    state: GraphProjection,
    task_states: dict[str, str],
) -> None:
    for task_region_id, candidates in state["task_candidates"].items():
        if task_states.get(task_region_id) != "accepted":
            continue
        latest_candidate = _latest_candidate(candidates)
        if latest_candidate is None:
            continue
        for superseded_region_id in latest_candidate.supersedes_task_region_ids:
            if task_states.get(superseded_region_id) == "needs_revision":
                task_states[superseded_region_id] = "accepted"


def _derive_candidate_free_region_state(
    state: GraphProjection,
    task_region_id: str,
) -> str:
    if _has_active_task_lease(state, task_region_id):
        return "in_progress"
    node_ids = _task_region_node_ids(state, task_region_id)
    active_node_ids = [
        node_id
        for node_id in node_ids
        if state["node_states"].get(node_id) not in {"retired", "cancelled"}
    ]
    if node_ids and not active_node_ids:
        return "accepted"
    contributing_node_ids = [
        node_id
        for node_id in active_node_ids
        if _contract_fulfillment_contribution(state, node_id) != "none"
    ]
    if not contributing_node_ids:
        return "pending"
    if all(_node_contract_fulfilled(state, node_id) for node_id in contributing_node_ids):
        return "accepted"
    return "pending"


def _task_region_node_ids(state: GraphProjection, task_region_id: str) -> list[str]:
    return [
        node_id
        for node_id, node_task_region_id in sorted(state["node_task_regions"].items())
        if node_task_region_id == task_region_id
    ]


def _contract_for_node(state: GraphProjection, node_id: str) -> Any | None:
    kind = state["node_kinds"].get(node_id)
    if kind is None:
        return None
    return DEFAULT_NODE_CONTRACTS.contract_for(kind, state["node_roles"].get(node_id))


def _contract_fulfillment_contribution(state: GraphProjection, node_id: str) -> str:
    contract = _contract_for_node(state, node_id)
    if contract is None:
        return "none"
    return contract.fulfillment_contribution


def _node_contract_fulfilled(state: GraphProjection, node_id: str) -> bool:
    node_state = state["node_states"].get(node_id)
    if node_state != "completed":
        return False
    missing_ports = _missing_fulfillment_ports(state, node_id)
    if missing_ports:
        return False
    contract = _contract_for_node(state, node_id)
    if contract is None:
        return False
    if contract.fulfillment_contribution == "final_invariant":
        return _final_invariant_node_passed(state, node_id)
    return True


def _missing_fulfillment_ports(state: GraphProjection, node_id: str) -> list[str]:
    contract = _contract_for_node(state, node_id)
    if contract is None:
        return []
    ports = state["node_output_ports"].get(node_id, {})
    return [port for port in sorted(contract.fulfillment_required_outputs) if not ports.get(port)]


def _final_invariant_node_passed(state: GraphProjection, node_id: str) -> bool:
    contract = _contract_for_node(state, node_id)
    if contract is None:
        return False
    if "check_result" in contract.fulfillment_required_outputs:
        result = state.get("check_results", {}).get(node_id)
        return result is not None and result.status in {"passed", "pass", "ok"}
    if "completion_decision" in contract.fulfillment_required_outputs:
        return bool(state["node_output_ports"].get(node_id, {}).get("completion_decision"))
    return True


def _verifier_requirement_passed(
    state: GraphProjection,
    task_region_id: str,
    candidate_id: str,
) -> bool:
    verdict = state["verifier_verdicts"].get(candidate_id)
    if verdict is not None:
        if verdict.verdict == "failed" and _failed_verification_recovery_superseded(
            state,
            task_region_id,
            candidate_id,
        ):
            return True
        return verdict.verdict == "passed"

    return not any(
        kind == "verifier"
        and state["node_task_regions"].get(node_id) == task_region_id
        and state["node_states"].get(node_id) not in {"retired", "cancelled"}
        for node_id, kind in state["node_kinds"].items()
    )


def _task_file_state_accepted(
    state: GraphProjection,
    task_region_id: str,
    candidate_id: str,
) -> bool:
    for record in state.get("file_state_records", {}).values():
        record_region_id = record.task_region_id
        if not isinstance(record_region_id, str):
            producer_node_id = record.producer_node_id
            if isinstance(producer_node_id, str):
                record_region_id = state["node_task_regions"].get(producer_node_id)
        if record_region_id != task_region_id:
            continue
        record_candidate_id = record.candidate_id
        if isinstance(record_candidate_id, str) and record_candidate_id != candidate_id:
            continue
        verdict = record.verdict
        if verdict in {"rejected", "failed"}:
            continue
        return True
    return False


def _required_checks_passed(state: GraphProjection, task_region_id: str) -> bool:
    latest_candidate = _latest_candidate(state["task_candidates"].get(task_region_id, []))
    check_node_ids = [
        node_id
        for node_id, kind in state["node_kinds"].items()
        if kind == "check"
        and state["node_task_regions"].get(node_id) == task_region_id
        and state["node_states"].get(node_id) not in {"retired", "cancelled"}
    ]
    if not check_node_ids:
        return True
    for node_id in check_node_ids:
        result = state.get("check_results", {}).get(node_id)
        if result is None:
            return False
        status = result.status
        if status not in {"passed", "pass", "ok"} and _check_result_recovery_superseded(
            state,
            result,
        ):
            continue
        if status not in {"passed", "pass", "ok"}:
            return False
        if latest_candidate is not None and not _check_result_cites_latest_candidate(
            result,
            latest_candidate,
        ):
            return False
    return True


def _check_result_cites_latest_candidate(
    result: CheckResultProjection,
    latest_candidate: CandidateProjection,
) -> bool:
    candidate_id = latest_candidate.candidate_id
    candidate_record_ids = result.candidate_record_ids
    if candidate_id not in candidate_record_ids:
        return False

    expected_file_state_ids = latest_candidate.file_state_record_ids
    if not expected_file_state_ids:
        return True
    cited_file_state_ids = set(result.file_state_record_ids)
    return all(record_id in cited_file_state_ids for record_id in expected_file_state_ids)


def _check_result_recovery_superseded(
    state: GraphProjection,
    check_result: CheckResultProjection | dict[str, Any],
) -> bool:
    record_id = (
        check_result.record_id
        if isinstance(check_result, CheckResultProjection)
        else check_result.get("record_id")
    )
    if not isinstance(record_id, str) or not record_id:
        return False
    for recovery in state["recovery_nodes_by_record_id"].get(record_id, []):
        if _recovery_lineage_passed(state, recovery.node_id):
            return True
    return False


def _failed_verification_recovery_superseded(
    state: GraphProjection,
    task_region_id: str,
    candidate_id: str,
) -> bool:
    for verification in state["failed_verification_results_by_record_id"].values():
        if verification.candidate_id != candidate_id:
            continue
        if verification.task_region_id != task_region_id:
            continue
        record_id = verification.record_id
        if not record_id:
            continue
        for recovery in state["recovery_nodes_by_record_id"].get(record_id, []):
            if _recovery_lineage_has_complete_verification(state, recovery.node_id):
                return True
    return False


def _recovery_lineage_has_complete_verification(
    state: GraphProjection,
    recovery_node_id: str,
) -> bool:
    reachable = _downstream_node_ids(state, recovery_node_id)
    if not reachable:
        return False
    for verification in state["passed_verification_results_by_record_id"].values():
        verifier_node_id = verification.node_id
        if verifier_node_id not in reachable:
            continue
        candidate_id = verification.candidate_id
        if not isinstance(candidate_id, str) or not candidate_id:
            continue
        verdict = state["verifier_verdicts"].get(candidate_id)
        if verdict is not None and verdict.verdict != "passed":
            continue
        task_region_id = verification.task_region_id
        if not isinstance(task_region_id, str):
            task_region_id = state["node_task_regions"].get(verifier_node_id)
        if not isinstance(task_region_id, str) or not task_region_id:
            continue
        configured_gates = state["configured_gates"].get(task_region_id, {})
        gate_decisions = state["gate_decisions"].get(task_region_id, {})
        if not _all_configured_gates_passed(configured_gates, gate_decisions):
            continue
        if not _task_file_state_accepted(state, task_region_id, candidate_id):
            continue
        if not _required_checks_passed(state, task_region_id):
            continue
        return True
    return False


def _recovery_lineage_passed(state: GraphProjection, recovery_node_id: str) -> bool:
    reachable = _downstream_node_ids(state, recovery_node_id)
    if not reachable:
        return False
    for verification in state["passed_verification_results_by_record_id"].values():
        if verification.node_id not in reachable:
            continue
        candidate_id = verification.candidate_id
        verdict = state["verifier_verdicts"].get(candidate_id or "")
        if verdict is None or verdict.verdict == "passed":
            return True
    for check_node_id, result in state["check_results"].items():
        if check_node_id not in reachable:
            continue
        if result.status in {"passed", "pass", "ok"}:
            return True
    return False


def _downstream_node_ids(state: GraphProjection, start_node_id: str) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for edge in state["edges"].values():
        source = edge.from_node_id
        target = edge.to_node_id
        adjacency.setdefault(source, set()).add(target)
    seen: set[str] = set()
    frontier = [start_node_id]
    while frontier:
        node_id = frontier.pop()
        for neighbor in adjacency.get(node_id, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append(neighbor)
    return seen


def _latest_candidate(candidates: list[CandidateProjection]) -> CandidateProjection | None:
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate.attempt_number, candidate.position))


def _active_invalid_test_override(
    block: InvalidTestBlockProjection | None,
    candidate_id: str,
) -> bool:
    if block is None:
        return False
    return block.appeal_open is True and block.candidate_id == candidate_id


def _all_configured_gates_passed(
    configured_gates: dict[str, bool],
    gate_decisions: dict[str, bool],
) -> bool:
    return all(gate_decisions.get(gate_id) is True for gate_id in configured_gates) and all(
        gate_decisions.values()
    )


def _replacement_verification_passed(
    state: GraphProjection,
    task_region_id: str,
    invalid_block: InvalidTestBlockProjection,
) -> bool:
    block_position = invalid_block.position
    for candidate in state["task_candidates"].get(task_region_id, []):
        verdict = state["verifier_verdicts"].get(candidate.candidate_id)
        if (
            verdict is not None
            and verdict.verdict == "passed"
            and candidate.position > block_position
        ):
            return True
    return False


def _has_active_task_lease(state: GraphProjection, task_region_id: str) -> bool:
    for lease in state["leases"].values():
        if lease.state != "active":
            continue
        if lease.task_region_id != task_region_id:
            continue
        if lease.kind in {"worker", "verifier", "check"}:
            return True
    return False


def _task_region_for_candidate(state: GraphProjection, candidate_id: str) -> str | None:
    for task_region_id, candidates in state["task_candidates"].items():
        if any(candidate.candidate_id == candidate_id for candidate in candidates):
            return task_region_id
    return None


def _command_definition_for_node_creation(
    payload: NodeCreationProjection,
) -> CommandDefinitionProjection | None:
    return check_command_reference(payload.model_dump(mode="json"))
