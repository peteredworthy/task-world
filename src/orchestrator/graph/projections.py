"""Pure graph projections for scenario fixtures."""

from __future__ import annotations

from datetime import datetime

from typing import Any, Iterable, Literal, Sequence, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestrator.graph.catalog import GraphCatalog
from orchestrator.graph.events.file_state import file_entry_values
from orchestrator.graph.command_bindings import check_command_reference
from orchestrator.graph.contracts import (
    DEFAULT_NODE_CONTRACTS,
    PortContract,
    binding_policy_for_edge,
    input_port_contract,
    merge_bound_record_ids,
    node_contract_summary,
    output_port_contract,
    port_contract_summary,
)
from orchestrator.graph.models import (
    AnalysisSummaryRecord,
    ApprovalDecisionProjection,
    ArtifactReferenceRecord,
    AuthorityDecisionProjection,
    AuthorityDecisionRecord,
    AuthorityRequestRecord,
    CallbackIdempotencyEvent,
    CandidateProjection,
    CandidateRecord,
    CheckResultProjection,
    CheckResultRecord,
    CleanupRequestedProjection,
    CompactEventEnvelope,
    CommandDefinitionProjection,
    CompletionDecisionRecord,
    DecisionRecord,
    DecisionRequestRecord,
    EdgeProjection,
    EnvironmentFailureProjection,
    EventEnvelope,
    FileEntry,
    FileStateRecord,
    FailureRecord,
    GapClassificationRecord,
    GraphBaseModel,
    GraphPatchAcceptedPayload,
    GraphPatchProposalRecord,
    GraphPatchRejectedPayload,
    GraphPatchStatusPayload,
    InvalidTestBlockProjection,
    InputBindingProjection,
    LegacyOutputRecord,
    LegacyReplayOutputRecordPayload,
    LeaseProjection,
    JoinResultRecord,
    NodeCreationProjection,
    NodeKind,
    NodeState,
    OversightDecisionProjection,
    OutputRecord,
    PendingGateDecisionProjection,
    RecoveryPlanRecord,
    RequirementRecord,
    RequirementRevisionProjection,
    ResourceClaimProjection,
    RunContextRecord,
    RoutineSnapshotRecord,
    SupportEvidenceProjection,
    VerificationReportRecord,
    VerificationResultProjection,
    VerifierVerdictProjection,
)
from orchestrator.graph.events.decisions import (
    AppealOpenedPayload,
    ApprovalDecisionRecordedPayload,
    AuthorityDecisionRecordedPayload,
    OversightDecisionRecordedPayload,
)
from orchestrator.graph.events.requirements import RequirementRevisionPayload
from orchestrator.graph.events.leases import (
    LeaseExpiredPayload,
    LeaseGrantedPayload,
    LeaseReleasedPayload,
    LeaseRenewedPayload,
    LeaseRevokedPayload,
)
from orchestrator.graph.events.records import OutputRecordAcceptedPayload
from orchestrator.graph.events.topology import (
    EdgeCreatedPayload,
    InputBoundPayload,
    NodeAuthorityChangedPayload,
    NodeCreatedPayload,
    NodeDeferredPayload,
    NodeReadyPayload,
    NodeRetiredPayload,
    NodeStateChangedPayload,
    PlanRegionMarkedSuspectPayload,
    PlannerSessionStateChangedPayload,
)
from orchestrator.graph.models import normalize_record_selector
from orchestrator.graph.payloads import JsonValue, LegacyEventPayload
from orchestrator.graph.specifications import HydratedEvent, event_payload_json

GraphHistoryEvent = EventEnvelope | HydratedEvent


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


def copy_projection(state: GraphProjection) -> GraphProjection:
    """Return a fully isolated projection for catalog-owned reducers."""

    def copy_value(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_copy()
        if isinstance(value, dict):
            return {key: copy_value(item) for key, item in cast(dict[Any, Any], value).items()}
        if isinstance(value, list):
            return [copy_value(item) for item in cast(list[Any], value)]
        if isinstance(value, tuple):
            return tuple(copy_value(item) for item in cast(tuple[Any, ...], value))
        if isinstance(value, set):
            return {copy_value(item) for item in cast(set[Any], value)}
        return value

    return cast(GraphProjection, copy_value(state))


# Bump this whenever reduce_event semantics or GraphProjection shape changes.
PROJECTION_SCHEMA_VERSION = 10


class GraphRecordSummary(BaseModel):
    """Closed projection of the stable identity fields of an accepted record."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    record_id: str
    record_type: str | None = None
    record_kind: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    producer_node_id: str | None = None
    producer_port: str | None = None
    position: int | None = None


class PlannerGenerations(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    values: dict[str, int]


class PlannerSessions(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    values: dict[str, str]


class PlannerSessionStates(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    values: dict[str, str]


class PlannerSessionCurrentNodes(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    values: dict[str, str]


class PlannerSessionCarryovers(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    values: dict[str, str | None]


class PlannerRegionLabels(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    values: dict[str, str]


class GatekeeperPatternLibrarySizeRow(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    position: int
    file_state_record_id: str | None
    size: int


class GatekeeperCostRow(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    model_id: str
    consults: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    wall_time_ms: int
    executions: list[str]


class GatekeeperReport(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    run_id: str
    boundary_count: int
    deterministic_classifications: int
    gatekeeper_consults: int
    gatekeeper_resolved: int
    unresolved_residue: int
    total_classified: int
    hit_rate: float
    pattern_library_size: int
    pattern_library_size_over_time: list[GatekeeperPatternLibrarySizeRow]
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    wall_time_ms: int
    models: dict[str, GatekeeperCostRow]


class AcceptedOutputRecord(TypedDict):
    record_id: str
    payload: LegacyReplayOutputRecordPayload


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
    output_records_by_node_port: dict[str, dict[str, list[LegacyReplayOutputRecordPayload]]]
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
    planner_generations: PlannerGenerations
    planner_sessions: PlannerSessions
    planner_session_states: PlannerSessionStates
    planner_session_current_nodes: PlannerSessionCurrentNodes
    planner_session_carryovers: PlannerSessionCarryovers
    planner_region_labels: PlannerRegionLabels
    requirement_revisions: dict[str, RequirementRevisionProjection]
    active_requirement_versions: dict[str, str]
    support_evidence: dict[str, SupportEvidenceProjection]
    last_deferred_reasons: dict[str, str]
    retry_not_before_by_node: dict[str, str | None]
    node_creation_payloads: dict[str, NodeCreationProjection]
    output_record_payloads: dict[str, LegacyReplayOutputRecordPayload]
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


class GraphTopologyBinding(BaseModel):
    """Closed, serializable input-binding view for a topology edge."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    record_ids: list[str]
    edge_id: str | None = None
    to_node_id: str | None = None
    to_port: str | None = None
    bound_at_position: int | None = None
    record_bound_positions: dict[str, int] | None = None
    binding_policy: str | None = None
    trigger: str | None = None


class GraphTopologyNode(TypedDict, total=False):
    node_id: str
    kind: str | None
    role: str | None
    state: str | None
    contract: dict[str, Any]


class GraphTopologyEdge(BaseModel):
    """Closed topology response record; opaque contract values stay JSON values."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    edge_id: str
    from_node_id: str
    from_port: str
    to_node_id: str
    to_port: str
    required: bool
    dependency_type: str
    metadata: dict[str, JsonValue]
    record_types: list[str]
    bound_records: list[GraphRecordSummary]
    from_node_kind: str | None = None
    from_node_role: str | None = None
    accepted_record_selector: dict[str, JsonValue] | None = None
    source_port_contract: dict[str, JsonValue] | None = None
    target_port_contract: dict[str, JsonValue] | None = None
    binding: GraphTopologyBinding | None = None


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
    stderr: str
    exit_code: int
    support_ids: list[str]


class GraphPatchAttempt(BaseModel):
    """Closed result projection for a proposed graph patch."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    patch_id: str
    current_graph_position: int
    status: Literal["accepted", "rejected"]
    proposed_by_node_id: str | None = None
    base_graph_position: int | None = None
    rejection_reason: str | None = None
    diagnostics: dict[str, JsonValue] | None = None
    read_set_diff: dict[str, JsonValue] | None = None
    accepted_event_id: str | None = None
    accepted_position: int | None = None
    rejected_event_id: str | None = None
    rejected_position: int | None = None
    created_node_ids: list[str] = Field(default_factory=list)
    created_edge_ids: list[str] = Field(default_factory=list)


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
        "planner_generations": PlannerGenerations(values={}),
        "planner_sessions": PlannerSessions(values={}),
        "planner_session_states": PlannerSessionStates(values={}),
        "planner_session_current_nodes": PlannerSessionCurrentNodes(values={}),
        "planner_session_carryovers": PlannerSessionCarryovers(values={}),
        "planner_region_labels": PlannerRegionLabels(values={}),
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
    checkpoint["accepted_record_summaries_by_id"] = {
        record_id: summary.model_dump(mode="json", by_alias=True, exclude_none=True)
        for record_id, summary in projection.get("accepted_record_summaries_by_id", {}).items()
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
    checkpoint["planner_generations"] = projection["planner_generations"].model_dump(mode="json")[
        "values"
    ]
    checkpoint["planner_sessions"] = projection["planner_sessions"].model_dump(mode="json")[
        "values"
    ]
    checkpoint["planner_session_states"] = projection["planner_session_states"].model_dump(
        mode="json"
    )["values"]
    checkpoint["planner_session_current_nodes"] = projection[
        "planner_session_current_nodes"
    ].model_dump(mode="json")["values"]
    checkpoint["planner_session_carryovers"] = projection["planner_session_carryovers"].model_dump(
        mode="json"
    )["values"]
    checkpoint["planner_region_labels"] = projection["planner_region_labels"].model_dump(
        mode="json"
    )["values"]
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
    projection["planner_generations"] = PlannerGenerations(
        values=_int_map_from_checkpoint(raw_projection.get("planner_generations"))
    )
    projection["planner_sessions"] = PlannerSessions(
        values=_string_map_from_checkpoint(raw_projection.get("planner_sessions"))
    )
    projection["planner_session_states"] = PlannerSessionStates(
        values=_string_map_from_checkpoint(raw_projection.get("planner_session_states"))
    )
    projection["planner_session_current_nodes"] = PlannerSessionCurrentNodes(
        values=_string_map_from_checkpoint(raw_projection.get("planner_session_current_nodes"))
    )
    projection["planner_session_carryovers"] = PlannerSessionCarryovers(
        values=_nullable_string_map_from_checkpoint(
            raw_projection.get("planner_session_carryovers")
        )
    )
    projection["planner_region_labels"] = PlannerRegionLabels(
        values=_string_map_from_checkpoint(raw_projection.get("planner_region_labels"))
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
        try:
            summary = GraphRecordSummary.model_validate(raw_summary)
        except ValueError:
            continue
        if summary.record_id == record_id:
            typed[record_id] = summary
    return typed


def _copy_record_summary(value: Any) -> GraphRecordSummary | None:
    if isinstance(value, GraphRecordSummary):
        return value.model_copy(deep=True)
    if not isinstance(value, dict):
        return None
    try:
        return GraphRecordSummary.model_validate(value)
    except ValueError:
        return None


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
    "stderr",
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
) -> LeaseReleasedPayload | LeaseRevokedPayload | LeaseExpiredPayload | None:
    model: type[LeaseReleasedPayload] | type[LeaseRevokedPayload] | type[LeaseExpiredPayload] | None
    if event_type == "lease_released":
        model = LeaseReleasedPayload
    elif event_type == "lease_revoked":
        model = LeaseRevokedPayload
    elif event_type == "lease_expired":
        model = LeaseExpiredPayload
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


def _graph_patch_status_payload_from_event(event: EventEnvelope) -> GraphPatchStatusPayload | None:
    try:
        return GraphPatchStatusPayload.model_validate(event.payload)
    except ValueError:
        return None


def _graph_patch_payload_for_event(event: EventEnvelope) -> dict[str, Any] | None:
    if event.event_type == "graph_patch_accepted":
        payload = _graph_patch_accepted_payload_from_event(event)
    elif event.event_type == "graph_patch_rejected":
        payload = _graph_patch_rejected_payload_from_event(event)
    elif event.event_type in {
        "graph_patch_proposed",
        "planner_proposal_opened",
        "proposal_opened",
        "proposal_recorded",
        "proposal_accepted",
        "proposal_rejected",
        "proposal_resolved",
        "proposal_closed",
    }:
        payload = _graph_patch_status_payload_from_event(event)
    else:
        payload = None
    if payload is None:
        return None
    return payload.model_dump(mode="json")


def _node_creation_from_event(event: GraphHistoryEvent) -> NodeCreationProjection | None:
    event_payload = _node_created_payload_from_event(event)
    if event_payload is None:
        return None
    normalized = event_payload.model_dump(mode="json")
    raw_extra = normalized.pop("extra", {})
    extra = cast(dict[str, Any], raw_extra) if isinstance(raw_extra, dict) else {}
    projection_payload: dict[str, Any] = dict(extra)
    projection_payload.update(normalized)
    return _node_creation_from_payload(
        {
            **projection_payload,
            "position": _history_event_position(event),
        }
    )


def _node_created_payload_from_event(event: GraphHistoryEvent) -> NodeCreatedPayload | None:
    if isinstance(event, HydratedEvent):
        return event.payload if isinstance(event.payload, NodeCreatedPayload) else None
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
) -> dict[str, dict[str, list[LegacyReplayOutputRecordPayload]]]:
    if not isinstance(raw_ports_by_node, dict):
        return {}
    typed: dict[str, dict[str, list[LegacyReplayOutputRecordPayload]]] = {}
    for node_id, raw_ports in cast(dict[Any, Any], raw_ports_by_node).items():
        if not isinstance(node_id, str) or not isinstance(raw_ports, dict):
            continue
        ports: dict[str, list[LegacyReplayOutputRecordPayload]] = {}
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


def _output_payloads_from_checkpoint(
    raw_payloads: Any,
) -> dict[str, LegacyReplayOutputRecordPayload]:
    if not isinstance(raw_payloads, dict):
        return {}
    typed: dict[str, LegacyReplayOutputRecordPayload] = {}
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


def _checkpoint_output_record_payload(raw_payload: Any) -> LegacyReplayOutputRecordPayload | None:
    if not isinstance(raw_payload, dict):
        return None
    try:
        return OutputRecordAcceptedPayload.model_validate(
            {"record": cast(dict[str, Any], raw_payload)}
        ).record
    except ValueError:
        pass
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


def reduce_typed_output_record_accepted(
    state: GraphProjection,
    payload: Any,
    metadata: Any,
) -> GraphProjection:
    """Apply a catalog-hydrated accepted record without legacy payload parsing."""
    next_state = copy_projection(state)
    record = payload.record
    record_payload = record.model_dump(mode="json")
    event = EventEnvelope(
        event_id=metadata.event_id,
        run_id=metadata.run_id,
        position=metadata.position,
        event_type=metadata.event_type,
        schema_version=metadata.payload_schema_generation,
        actor=metadata.actor,
        causation_id=metadata.causation_id,
        correlation_id=metadata.correlation_id,
        timestamp=metadata.timestamp,
        payload=record_payload,
    )
    typed_record = cast(LegacyReplayOutputRecordPayload, record)
    _record_output_record(next_state, typed_record)
    _record_node_output_port(next_state, event)
    _record_accepted_output_record(next_state, typed_record)
    _record_accepted_record_summary(next_state, event)
    _record_output_payload(next_state, typed_record)
    _record_latest_routine_snapshot(next_state, event)
    _record_completion_decision(next_state, event)
    _record_decision_request_details(next_state, event)
    _record_candidate(next_state, event)
    _record_check_result(next_state, event)
    _record_environment_failure(next_state, event)
    _refresh_derived_topology_state(next_state)
    return next_state


def reduce_typed_verification_outcome(
    state: GraphProjection,
    payload: Any,
    metadata: Any,
) -> GraphProjection:
    """Project a catalog-hydrated verifier outcome without raw event parsing."""

    next_state = copy_projection(state)
    verdict = VerifierVerdictProjection(
        candidate_id=payload.candidate_id,
        verdict=payload.outcome,
        position=metadata.position,
    )
    next_state["verifier_verdicts"][payload.candidate_id] = verdict
    result = VerificationResultProjection(
        node_id=payload.verifier_node_id,
        record_id=payload.record_id,
        candidate_id=payload.candidate_id,
        task_region_id=payload.task_region_id,
    )
    if payload.outcome == "passed":
        if payload.candidate_id not in next_state["passed_verification_candidate_ids"]:
            next_state["passed_verification_candidate_ids"].append(payload.candidate_id)
        next_state["passed_verification_results_by_record_id"][payload.record_id] = result
    else:
        next_state["failed_verification_candidate_ids"][payload.candidate_id] = True
        next_state["failed_verification_results_by_record_id"][payload.record_id] = result
    _refresh_derived_topology_state(next_state)
    return next_state


def reduce_compact_output_record_accepted(
    state: GraphProjection,
    event: CompactEventEnvelope,
) -> GraphProjection:
    """Apply the projection fields selected by the transitional compact reader."""
    if event.schema_version != 1 or event.event_type != "output_record_accepted":
        raise ValueError("compact legacy replay requires generation 1 output_record_accepted")
    record = event.payload.get("record")
    if not isinstance(record, dict):
        msg = "compact output_record_accepted requires a record object"
        raise ValueError(msg)
    flat_event = event.model_copy(update={"payload": record})
    next_state = reduce_legacy_event(state, flat_event)
    output_record_payload = _parse_output_record_payload(flat_event.payload)
    _record_output_record(next_state, output_record_payload)
    _record_node_output_port(next_state, flat_event)
    _record_accepted_output_record(next_state, output_record_payload)
    _record_accepted_record_summary(next_state, flat_event)
    _record_output_payload(next_state, output_record_payload)
    _record_latest_routine_snapshot(next_state, flat_event)
    _record_completion_decision(next_state, flat_event)
    _record_decision_request_details(next_state, flat_event)
    _record_candidate(next_state, flat_event)
    _record_check_result(next_state, flat_event)
    _record_environment_failure(next_state, flat_event)
    _refresh_derived_topology_state(next_state)
    return next_state


_D3_LEGACY_RECORD_EVENT_TYPES = frozenset(
    {
        "output_record_accepted",
        "verification_passed",
        "verification_failed",
        "file_state_accepted",
    }
)


def _normalize_d3_file_state_membership(record: dict[str, Any]) -> dict[str, Any]:
    """Lift historical file-state membership only while replaying generation 1."""

    if record.get("record_type") != "file_state" and record.get("record_kind") != "file_state":
        return record
    membership = record.get("membership")
    if not isinstance(membership, dict):
        return record
    typed_membership = cast(dict[str, Any], membership)
    normalized = dict(record)
    for key in ("task_region_id", "candidate_id"):
        value = typed_membership.get(key)
        if normalized.get(key) is None and isinstance(value, str):
            normalized[key] = value
    return normalized


def reduce_d3_legacy_record_replay(
    state: GraphProjection,
    event: EventEnvelope,
) -> GraphProjection:
    """Replay the pre-strict record envelope generation until Task 13 cutover."""

    if event.schema_version != 1 or event.event_type not in _D3_LEGACY_RECORD_EVENT_TYPES:
        msg = "D3 legacy replay accepts only schema generation 1 record events"
        raise ValueError(msg)
    if event.event_type == "output_record_accepted":
        raw_record = event.payload.get("record")
        if isinstance(raw_record, dict):
            return reduce_legacy_event(
                state,
                event.model_copy(
                    update={
                        "payload": _normalize_d3_file_state_membership(
                            cast(dict[str, Any], raw_record)
                        )
                    }
                ),
            )
    if event.event_type == "file_state_accepted":
        next_state = copy_projection(state)
        normalized = event.model_copy(
            update={"payload": _normalize_d3_file_state_membership(event.payload)}
        )
        _record_node_output_port(next_state, normalized)
        _record_accepted_record_summary(next_state, normalized)
        _record_file_state(next_state, normalized)
        _refresh_derived_topology_state(next_state)
        return next_state
    return reduce_legacy_event(
        state,
        event.model_copy(update={"payload": _normalize_d3_file_state_membership(event.payload)}),
    )


def _is_d3_legacy_record_replay_event(event: EventEnvelope) -> bool:
    """Identify the only durable generation eligible for the D3 replay adapter."""

    return event.schema_version == 1 and event.event_type in _D3_LEGACY_RECORD_EVENT_TYPES


def reduce_event(
    catalog: GraphCatalog,
    state: GraphProjection,
    event: EventEnvelope | HydratedEvent,
) -> GraphProjection:
    if isinstance(event, HydratedEvent):
        if isinstance(event.payload, LegacyEventPayload):
            event = EventEnvelope(
                event_id=event.event_id,
                run_id=event.run_id,
                position=event.position,
                event_type=event.event_type,
                schema_version=1,
                actor=event.actor,
                causation_id=event.causation_id,
                correlation_id=event.correlation_id,
                timestamp=event.timestamp,
                payload=event.payload.to_json(),
            )
        else:
            specification = catalog.resolve_event(event.metadata.event_type)
            return specification.reduce(state, event)
    if isinstance(event, CompactEventEnvelope):
        return reduce_compact_output_record_accepted(state, event)
    # Mixed persistence boundary: catalog-owned events hydrate exactly once;
    # future-domain events continue through the legacy raw reducer below.
    try:
        handled, reduced = catalog.reduce_stored_event(state, event)
    except ValueError:
        if _is_d3_legacy_record_replay_event(event):
            return reduce_d3_legacy_record_replay(state, event)
        raise
    if handled:
        return cast(GraphProjection, reduced)
    if _is_d3_legacy_record_replay_event(event):
        return reduce_d3_legacy_record_replay(state, event)
    return reduce_legacy_event(state, event)


def reduce_legacy_event(
    state: GraphProjection,
    event: EventEnvelope,
) -> GraphProjection:
    """Fold one event that is not owned by the injected typed catalog."""
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
            record_id: summary_copy
            for record_id, summary in state.get("accepted_record_summaries_by_id", {}).items()
            if (summary_copy := _copy_record_summary(summary)) is not None
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
        "planner_generations": state["planner_generations"].model_copy(deep=True),
        "planner_sessions": state["planner_sessions"].model_copy(deep=True),
        "planner_session_states": state["planner_session_states"].model_copy(deep=True),
        "planner_session_current_nodes": state["planner_session_current_nodes"].model_copy(
            deep=True
        ),
        "planner_session_carryovers": state["planner_session_carryovers"].model_copy(deep=True),
        "planner_region_labels": state["planner_region_labels"].model_copy(deep=True),
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
    }

    if event.event_type == "lease_granted":
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
                    if key == "expires_at" and isinstance(value, datetime):
                        value = value.isoformat()
                    lease_payload[key] = value
            session_id = granted_payload.session_id
            if session_id is not None:
                lease_payload["session_id"] = session_id
                next_state["planner_sessions"] = PlannerSessions(
                    values={**next_state["planner_sessions"].values, node_id: session_id}
                )
            task_region_id = next_state["node_task_regions"].get(node_id)
            if task_region_id is not None:
                lease_payload["task_region_id"] = task_region_id
            if node_id in next_state["node_kinds"]:
                lease_payload["kind"] = next_state["node_kinds"][node_id]
            resource_claims = granted_payload.resource_claims
            if not resource_claims:
                resource_claims = next_state["node_resource_claims"].get(node_id, [])
            if resource_claims:
                lease_payload["resource_claims"] = resource_claims
            lease = _lease_from_payload(lease_payload)
            if lease is not None:
                next_state["leases"][lease_id] = lease
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
                    if key == "expires_at" and isinstance(value, datetime):
                        value = value.isoformat()
                    lease_payload[key] = value
            lease = _lease_from_payload(lease_payload)
            if lease is not None:
                next_state["leases"][lease_id] = lease
    elif event.event_type in {"verification_passed", "verification_failed"}:
        _record_verdict(next_state, event)
        _record_verification_result(next_state, event)
    elif event.event_type in {"environment_failure_accepted", "check_result_classified"}:
        _record_environment_failure(next_state, event)
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
    elif event.event_type == "requirement_revision_proposed":
        _record_authority_revision_blocker(next_state, event)
    elif event.event_type in {
        "graph_patch_proposed",
        "planner_proposal_opened",
        "proposal_opened",
        "proposal_recorded",
        "graph_patch_rejected",
        "proposal_accepted",
        "proposal_rejected",
        "proposal_resolved",
        "proposal_closed",
    }:
        _record_open_proposal_blocker(next_state, event)
    elif event.event_type == "authority_resolution_recorded":
        _record_authority_revision_blocker(next_state, event)
    # node_ready/node_deferred and agent_died/runtime_retry_scheduled are
    # audit/policy facts. Projection facts are updated only by lease_* and
    # node_state_changed events so replay has a single state authority.

    next_state["ready_nodes"] = _ready_nodes(next_state["node_states"])
    next_state["task_states"] = _derive_task_states(next_state)
    return next_state


def project_run_state(
    catalog: GraphCatalog,
    events: Sequence[GraphHistoryEvent],
    *,
    projection: GraphProjection | None = None,
) -> str | None:
    projection = projection if projection is not None else _project(catalog, events)
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
    catalog: GraphCatalog,
    events: Sequence[GraphHistoryEvent],
    *,
    projection: GraphProjection | None = None,
) -> list[FinalInvariantBlocker]:
    proj = projection if projection is not None else _project(catalog, events)
    return final_invariant_blockers_for_events(events, proj)


def final_invariant_blockers_for_events(
    events: Sequence[GraphHistoryEvent],
    projection: GraphProjection,
    *,
    include_completion_decision: bool = True,
) -> list[FinalInvariantBlocker]:
    stored_events = [_history_event_envelope(event) for event in events]
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
    blockers.extend(_open_proposal_blockers(stored_events, projection))
    blockers.extend(_suspect_node_blockers(stored_events, projection))
    blockers.extend(_requirement_evidence_blockers(stored_events, projection))
    blockers.extend(_authority_revision_blockers(stored_events, projection))
    blockers.extend(_blocked_requirement_node_blockers(stored_events, projection))
    blockers.extend(_dead_required_input_blockers(projection))
    blockers.extend(_impossible_input_blockers(projection))
    blockers.extend(_failed_check_result_blockers(stored_events, projection))
    if include_completion_decision:
        blockers.extend(_completion_decision_blockers(stored_events, projection))
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
        if edge.get("required") is False:
            continue
        if edge.get("dependency_type", "input_binding") != "input_binding":
            continue
        from_node_id = edge.get("from_node_id")
        to_node_id = edge.get("to_node_id")
        to_port = edge.get("to_port")
        if not all(isinstance(value, str) for value in (from_node_id, to_node_id, to_port)):
            continue
        if projection["node_states"].get(str(to_node_id)) in terminal_states:
            continue
        if str(from_node_id) in projection["node_states"]:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "impossible_input",
            "reason": "required input edge has no producer node",
            "node_id": str(to_node_id),
            "edge_id": str(edge_id),
            "to_port": str(to_port),
            "state": projection["node_states"].get(str(to_node_id), "unknown"),
        }
        task_region_id = projection["node_task_regions"].get(str(to_node_id))
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        blockers.append(blocker)
    return blockers


def _dead_required_input_blockers(projection: GraphProjection) -> list[FinalInvariantBlocker]:
    blockers: list[FinalInvariantBlocker] = []
    dead_source_states = {"failed", "cancelled", "retired"}
    target_terminal_states = {"completed", "failed", "cancelled", "retired"}
    for edge_id, edge in sorted(projection["edges"].items()):
        if edge.get("required") is False:
            continue
        if edge.get("dependency_type", "input_binding") != "input_binding":
            continue
        from_node_id = edge.get("from_node_id")
        to_node_id = edge.get("to_node_id")
        to_port = edge.get("to_port")
        if not all(isinstance(value, str) for value in (from_node_id, to_node_id, to_port)):
            continue
        source_state = projection["node_states"].get(str(from_node_id))
        if source_state not in dead_source_states:
            continue
        target_state = projection["node_states"].get(str(to_node_id), "unknown")
        if target_state in target_terminal_states:
            continue
        binding = projection["input_bindings"].get(str(to_node_id), {}).get(str(to_port), {})
        record_ids = binding.get("record_ids")
        if isinstance(record_ids, list) and record_ids:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "dead_required_input",
            "reason": "required input source is terminal before producing a bound record",
            "node_id": str(to_node_id),
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
        payload = event_payload_json(event).get("record")
        if not isinstance(payload, dict):
            continue
        typed_payload = cast(dict[str, Any], payload)
        if not _is_check_result_record(typed_payload):
            continue
        status = _check_result_status(typed_payload)
        if status is None:
            continue
        if status in {"passed", "pass", "ok"}:
            continue
        if _check_result_recovery_superseded(projection, typed_payload):
            continue
        record_id = typed_payload.get("record_id")
        key = record_id if isinstance(record_id, str) else f"position-{event.position}"
        blocker: FinalInvariantBlocker = {
            "kind": "failed_check_result",
            "reason": "check result did not pass",
        }
        value = typed_payload.get("value")
        if isinstance(value, dict):
            typed_value = cast(dict[str, Any], value)
            classification = typed_value.get("classification")
            command_text = typed_value.get("command_text")
            stderr = typed_value.get("stderr")
            exit_code = typed_value.get("exit_code")
            if isinstance(classification, str):
                blocker["classification"] = classification
            if isinstance(command_text, str):
                blocker["command_text"] = command_text
            if isinstance(stderr, str):
                blocker["stderr"] = stderr
            if isinstance(exit_code, int) and (
                isinstance(command_text, str)
                or isinstance(stderr, str)
                or isinstance(classification, str)
            ):
                blocker["exit_code"] = exit_code
            if classification in {"environment_error", "tool_error", "tool_unavailable"}:
                blocker["reason"] = _environment_failure_reason_from_check_value(typed_value)
        node_id = typed_payload.get("producer_node_id") or typed_payload.get("node_id")
        if isinstance(node_id, str):
            blocker["node_id"] = node_id
        task_region_id = typed_payload.get("task_region_id")
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
        if payload.stderr is not None:
            blocker["stderr"] = payload.stderr
        if payload.exit_code is not None and (
            payload.command_text is not None
            or payload.stderr is not None
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
            cast(dict[str, Any], event_payload_json(event)["record"])
            for event in events
            if event.event_type == "output_record_accepted"
            and isinstance(event_payload_json(event).get("record"), dict)
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
        if event.event_type in {
            "graph_patch_proposed",
            "planner_proposal_opened",
            "proposal_opened",
            "proposal_recorded",
        }:
            status = payload.get("status")
            if status in {"accepted", "rejected", "resolved", "closed"}:
                open_proposals.pop(proposal_id, None)
                continue
            open_proposals[proposal_id] = {
                "kind": "open_planner_proposal",
                "reason": "planner proposal has not been accepted or rejected",
                "proposal_id": proposal_id,
            }
        elif event.event_type in {
            "graph_patch_accepted",
            "graph_patch_rejected",
            "proposal_accepted",
            "proposal_rejected",
            "proposal_resolved",
            "proposal_closed",
        }:
            open_proposals.pop(proposal_id, None)
    return [open_proposals[key] for key in sorted(open_proposals)]


def _suspect_node_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> list[FinalInvariantBlocker]:
    del events
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

    if blockers:
        return blockers
    return _legacy_requirement_evidence_blockers(events)


def _legacy_requirement_evidence_blockers(
    events: list[EventEnvelope],
) -> list[FinalInvariantBlocker]:
    blockers_by_requirement: dict[tuple[str, str], FinalInvariantBlocker] = {}
    freshness_events = {
        "requirement_support_evaluated",
        "requirement_freshness_evaluated",
        "requirement_evidence_freshness_recorded",
    }
    for event in events:
        if event.event_type not in freshness_events:
            continue
        requirement_id = _requirement_id(event.payload)
        if requirement_id is None:
            continue
        support_ids = _payload_string_list(event.payload, "support_ids")
        if (
            event_payload_json(event).get("supported") is True
            or event_payload_json(event).get("freshness") == "fresh"
        ):
            blockers_by_requirement.pop(("unsupported_active_requirement", requirement_id), None)
            blockers_by_requirement.pop(("stale_support_evidence", requirement_id), None)
            continue
        if (
            _payload_truthy(event.payload, "unsupported")
            or event_payload_json(event).get("supported") is False
        ):
            blockers_by_requirement[("unsupported_active_requirement", requirement_id)] = {
                "kind": "unsupported_active_requirement",
                "reason": "active requirement has no current supporting evidence",
                "requirement_id": requirement_id,
                "support_ids": support_ids,
            }
        if _is_stale_only_evidence(event.payload):
            blockers_by_requirement[("stale_support_evidence", requirement_id)] = {
                "kind": "stale_support_evidence",
                "reason": "active requirement is supported only by stale evidence",
                "requirement_id": requirement_id,
                "support_ids": support_ids,
            }
    return [
        blockers_by_requirement[key]
        for key in sorted(blockers_by_requirement, key=lambda item: (item[0], item[1]))
    ]


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
        payload = _authority_revision_payload_for_event(event)
        if payload is None:
            continue
        revision_id = _revision_id(payload)
        if revision_id is None:
            continue
        if event.event_type in {
            "requirement_revision_recorded",
            "requirement_revision_proposed",
        }:
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
        elif event.event_type == "authority_resolution_recorded":
            unresolved.pop(revision_id, None)
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
    if event.event_type in {
        "graph_patch_proposed",
        "planner_proposal_opened",
        "proposal_opened",
        "proposal_recorded",
    }:
        status = payload.get("status")
        if status in {"accepted", "rejected", "resolved", "closed"}:
            state["open_proposal_blockers"].pop(proposal_id, None)
            return
        state["open_proposal_blockers"][proposal_id] = {
            "kind": "open_planner_proposal",
            "reason": "planner proposal has not been accepted or rejected",
            "proposal_id": proposal_id,
        }
    elif event.event_type in {
        "graph_patch_accepted",
        "graph_patch_rejected",
        "proposal_accepted",
        "proposal_rejected",
        "proposal_resolved",
        "proposal_closed",
    }:
        state["open_proposal_blockers"].pop(proposal_id, None)


def _record_authority_revision_blocker(state: GraphProjection, event: EventEnvelope) -> None:
    payload = _authority_revision_payload_for_event(event)
    if payload is None:
        return
    revision_id = _revision_id(payload)
    if revision_id is None:
        return
    if event.event_type in {
        "requirement_revision_recorded",
        "requirement_revision_proposed",
    }:
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
    elif event.event_type == "authority_resolution_recorded":
        state["authority_revision_blockers"].pop(revision_id, None)


def _authority_revision_payload_for_event(event: EventEnvelope) -> dict[str, Any] | None:
    if event.event_type == "requirement_revision_recorded":
        return RequirementRevisionPayload.model_validate(event.payload).model_dump(mode="json")
    if event.event_type in {"requirement_revision_proposed", "authority_resolution_recorded"}:
        return dict(event.payload)
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


def _payload_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in cast(list[Any], value) if isinstance(item, str)]


def _payload_truthy(payload: dict[str, Any], key: str) -> bool:
    return payload.get(key) is True


def _is_stale_only_evidence(payload: dict[str, Any]) -> bool:
    if payload.get("stale_only") is True:
        return True
    for key in ("freshness", "status", "evidence_freshness"):
        value = payload.get(key)
        if value in {"stale_only", "stale"}:
            return True
    return False


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


def project_planner_chain(
    catalog: GraphCatalog, events: Sequence[GraphHistoryEvent]
) -> list[dict[str, Any]]:
    projection = _project(catalog, events)
    planner_ids = [
        node_id
        for node_id, kind in projection["node_kinds"].items()
        if kind == "planner" and projection["node_roles"].get(node_id) == "planner"
    ]
    ordered = sorted(
        planner_ids,
        key=lambda node_id: (
            projection["planner_generations"].values.get(node_id, 0),
            _node_creation_position(events, node_id),
            node_id,
        ),
    )
    return [
        {
            "node_id": node_id,
            "generation_index": projection["planner_generations"].values.get(node_id, 0),
            "session_id": projection["planner_sessions"].values.get(node_id),
            "lease_generation": _latest_lease_generation(events, node_id),
            "region_label": _planner_region_label(events, projection, node_id),
            "state": projection["node_states"].get(node_id),
            "successor_node_id": projection["planner_successors"].get(node_id),
        }
        for node_id in ordered
    ]


def project_planner_session(catalog: GraphCatalog, events: list[EventEnvelope]) -> dict[str, Any]:
    projection = _project(catalog, events)
    session_ids = list(projection["planner_session_states"].values)
    if not session_ids:
        session_ids = list(projection["planner_sessions"].values.values())
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
            "node_id": event_payload_json(event)["node_id"],
            "lease_generation": event_payload_json(event)["generation"],
            "region_label": _planner_region_label(
                events,
                projection,
                str(event_payload_json(event)["node_id"]),
            ),
            "state": _planner_generation_state(events, str(event_payload_json(event)["lease_id"])),
        }
        for event in events
        if event.event_type == "lease_granted"
        and event_payload_json(event).get("session_id") == session_id
        and isinstance(event_payload_json(event).get("node_id"), str)
        and isinstance(event_payload_json(event).get("lease_id"), str)
        and isinstance(event_payload_json(event).get("generation"), int)
    ]
    generations.sort(key=lambda generation: int(generation["lease_generation"]))
    return {
        "session_id": session_id,
        "state": projection["planner_session_states"].values.get(session_id),
        "generations": generations,
        "current_node_id": projection["planner_session_current_nodes"].values.get(session_id),
        "carryover_record_id": projection["planner_session_carryovers"].values.get(session_id),
    }


def project_node_states(
    catalog: GraphCatalog,
    events: Sequence[GraphHistoryEvent],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, str]:
    proj = projection if projection is not None else _project(catalog, events)
    return proj["node_states"]


def project_node_metadata(
    catalog: GraphCatalog,
    events: Sequence[GraphHistoryEvent],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, dict[str, Any]]:
    projection = projection if projection is not None else _project(catalog, events)
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


def project_graph_topology(
    catalog: GraphCatalog, events: Sequence[GraphHistoryEvent]
) -> GraphTopologyView:
    projection = _project(catalog, events)
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
    events: Sequence[GraphHistoryEvent],
    *,
    run_id: str = "",
    current_graph_position: int | None = None,
) -> GraphPatchAttemptView:
    attempts: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    active_patch_id: str | None = None

    def ensure_attempt(patch_id: str) -> dict[str, Any]:
        if patch_id not in attempts:
            attempts[patch_id] = {
                "patch_id": patch_id,
                "created_node_ids": [],
                "created_edge_ids": [],
            }
            order.append(patch_id)
        return attempts[patch_id]

    for history_event in events:
        event = _history_event_envelope(history_event)
        payload = _graph_patch_payload_for_event(event) or event.payload
        patch_id = _patch_id(payload)
        if event.event_type == "graph_patch_proposed" and patch_id is not None:
            attempt = ensure_attempt(patch_id)
            _apply_patch_payload(attempt, payload)
            active_patch_id = patch_id
            continue
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
                cast(list[str], attempt["created_node_ids"]).append(node_id)
        elif event.event_type == "edge_created":
            edge_id = payload.get("edge_id")
            if isinstance(edge_id, str):
                cast(list[str], attempt["created_edge_ids"]).append(edge_id)
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
        ordered_attempts.append(GraphPatchAttempt.model_validate(attempt))
    return {
        "run_id": run_id,
        "current_graph_position": current_graph_position,
        "attempts": ordered_attempts,
    }


def _apply_patch_payload(attempt: dict[str, Any], payload: dict[str, Any]) -> None:
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
    diagnostics = dict(payload.get("diagnostics") or {})
    diagnostics.update(
        {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "patch_id",
                "proposed_by_node_id",
                "base_graph_position",
                "reason",
                "read_set_diff",
                "diagnostics",
            }
        }
    )
    if diagnostics:
        attempt["diagnostics"] = diagnostics


def _patch_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("patch_id")
    if isinstance(value, str) and value:
        return value
    return None


def project_task_states(
    catalog: GraphCatalog,
    events: Sequence[GraphHistoryEvent],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, str]:
    proj = projection if projection is not None else _project(catalog, events)
    return proj["task_states"]


def project_requirement_revisions(
    catalog: GraphCatalog, events: list[EventEnvelope]
) -> dict[str, dict[str, Any]]:
    return {
        version_id: revision.model_dump(mode="json")
        for version_id, revision in _project(catalog, events)["requirement_revisions"].items()
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
    catalog: GraphCatalog,
    events: list[EventEnvelope],
) -> dict[str, SupportEvidenceFreshness]:
    return support_evidence_freshness_from_projection(_project(catalog, events))


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
    catalog: GraphCatalog,
    events: list[EventEnvelope],
) -> list[RequirementFreshnessFact]:
    return requirement_freshness_facts_from_projection(_project(catalog, events))


def project_planner_freshness_packet(
    catalog: GraphCatalog, events: list[EventEnvelope]
) -> dict[str, Any]:
    """Expose compact requirement/evidence freshness facts for gap planners."""
    facts = project_requirement_freshness_facts(catalog, events)
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
    catalog: GraphCatalog,
    events: Sequence[GraphHistoryEvent],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, dict[str, Any]]:
    proj = projection if projection is not None else _project(catalog, events)
    return {lease_id: lease.model_dump(mode="json") for lease_id, lease in proj["leases"].items()}


def project_ready_nodes(
    catalog: GraphCatalog,
    events: Sequence[GraphHistoryEvent],
    *,
    projection: GraphProjection | None = None,
) -> list[str]:
    proj = projection if projection is not None else _project(catalog, events)
    return proj["ready_nodes"]


def project_scheduler_view(
    catalog: GraphCatalog,
    events: Sequence[GraphHistoryEvent],
    *,
    projection: GraphProjection | None = None,
) -> SchedulerView:
    """Project ready/deferred scheduler buckets from graph events.

    Readiness remains governed by node_state_changed facts. Deferred scheduler
    events are audit facts, so this view exposes the latest deferral reason
    even when a node is still ready but blocked by a transient scheduler
    precondition such as a resource conflict.
    """
    proj = projection if projection is not None else _project(catalog, events)
    node_states = project_node_states(catalog, events, projection=proj)
    ready = sorted(project_ready_nodes(catalog, events, projection=proj))
    latest_deferrals = _latest_node_deferrals(events)
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
    catalog: GraphCatalog,
    events: Sequence[GraphHistoryEvent],
    *,
    projection: GraphProjection | None = None,
) -> LeaseView:
    leases = project_leases(catalog, events, projection=projection)
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
    catalog: GraphCatalog,
    events: Sequence[GraphHistoryEvent],
    *,
    projection: GraphProjection | None = None,
) -> DecisionView:
    """Project human decisions, appeal outcomes, and review readiness."""
    projection = projection if projection is not None else _project(catalog, events)
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


def project_residue_report(
    catalog: GraphCatalog, events: Sequence[GraphHistoryEvent]
) -> dict[str, list[dict[str, Any]]]:
    """Project accepted file-state residue classifications by path."""
    report: dict[str, list[dict[str, Any]]] = {}
    for record in _project(catalog, events)["file_state_records"].values():
        entries = record.residue or record.classifications
        for raw_entry in entries:
            entry = file_entry_values(raw_entry)
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


def _bound_record_ids(binding: dict[str, Any]) -> list[str]:
    record_ids = binding.get("record_ids")
    if not isinstance(record_ids, list):
        return []
    return [record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)]


def _topology_edge(
    edge: dict[str, Any],
    projection: GraphProjection,
    record_summaries: dict[str, GraphRecordSummary],
) -> GraphTopologyEdge:
    source_contract, target_contract = _edge_port_contracts(edge, projection)
    metadata = {
        key: edge[key] for key in _EDGE_METADATA_KEYS if key in edge and edge[key] is not None
    }
    topology_edge: dict[str, Any] = {
        "edge_id": str(edge["edge_id"]),
        "from_node_id": str(edge["from_node_id"]),
        "from_port": str(edge["from_port"]),
        "to_node_id": str(edge["to_node_id"]),
        "to_port": str(edge["to_port"]),
        "required": _edge_required(edge.get("required")),
        "dependency_type": str(edge.get("dependency_type", "input_binding")),
        "metadata": dict(metadata),
        "record_types": _compatible_edge_record_types(source_contract, target_contract),
        "binding": None,
        "bound_records": [],
    }
    from_node_kind = edge.get("from_node_kind")
    if isinstance(from_node_kind, str):
        topology_edge["from_node_kind"] = from_node_kind
    from_node_role = edge.get("from_node_role")
    if isinstance(from_node_role, str):
        topology_edge["from_node_role"] = from_node_role
    selector = edge.get("accepted_record_selector")
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
        record_ids = binding_summary.record_ids
        bound_records: list[GraphRecordSummary] = [
            record_summaries[record_id] for record_id in record_ids if record_id in record_summaries
        ]
        topology_edge["bound_records"] = bound_records
    return GraphTopologyEdge.model_validate(topology_edge)


def _edge_port_contracts(
    edge: dict[str, Any],
    projection: GraphProjection,
) -> tuple[PortContract | None, PortContract | None]:
    from_node_id = edge.get("from_node_id")
    to_node_id = edge.get("to_node_id")
    from_port = edge.get("from_port")
    to_port = edge.get("to_port")
    if not all(isinstance(value, str) for value in (from_node_id, to_node_id, from_port, to_port)):
        return None, None

    source_kind = projection["node_kinds"].get(cast(str, from_node_id))
    if source_kind is None and from_node_id == "*":
        raw_source_kind = edge.get("from_node_kind")
        source_kind = raw_source_kind if isinstance(raw_source_kind, str) else None
    source_role = projection["node_roles"].get(cast(str, from_node_id))
    if source_role is None and from_node_id == "*":
        raw_source_role = edge.get("from_node_role")
        source_role = raw_source_role if isinstance(raw_source_role, str) else None
    target_kind = projection["node_kinds"].get(cast(str, to_node_id))
    target_role = projection["node_roles"].get(cast(str, to_node_id))
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
        output_port_contract(source_contract, cast(str, from_port))
        if source_contract is not None
        else None
    )
    target_port_contract = (
        input_port_contract(target_contract, cast(str, to_port))
        if target_contract is not None
        else None
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
    edge: dict[str, Any],
) -> dict[str, Any] | None:
    edge_id = edge.get("edge_id")
    to_node_id = edge.get("to_node_id")
    to_port = edge.get("to_port")
    if isinstance(to_node_id, str) and isinstance(to_port, str):
        binding = projection["input_bindings"].get(to_node_id, {}).get(to_port)
        if binding is not None and (
            not isinstance(edge_id, str) or binding.get("edge_id") in {None, edge_id}
        ):
            return binding
    if not isinstance(edge_id, str):
        return None
    for ports in projection["input_bindings"].values():
        for binding in ports.values():
            if binding.get("edge_id") == edge_id:
                return binding
    return None


def _topology_binding(binding: dict[str, Any]) -> GraphTopologyBinding:
    summary: dict[str, Any] = {
        "record_ids": _bound_record_ids(binding),
    }
    for key in ("edge_id", "to_node_id", "to_port", "binding_policy", "trigger"):
        value = binding.get(key)
        if isinstance(value, str):
            summary[key] = value
    bound_at_position = binding.get("bound_at_position")
    if isinstance(bound_at_position, int) and not isinstance(bound_at_position, bool):
        summary["bound_at_position"] = bound_at_position
    record_bound_positions = binding.get("record_bound_positions")
    if isinstance(record_bound_positions, dict):
        summary["record_bound_positions"] = {
            record_id: position
            for record_id, position in cast(dict[Any, Any], record_bound_positions).items()
            if isinstance(record_id, str)
            and isinstance(position, int)
            and not isinstance(position, bool)
        }
    return GraphTopologyBinding.model_validate(summary)


def _record_summaries_by_id(projection: GraphProjection) -> dict[str, GraphRecordSummary]:
    return {
        record_id: summary_copy
        for record_id, summary in projection["accepted_record_summaries_by_id"].items()
        if (summary_copy := _copy_record_summary(summary)) is not None
    }


def _add_record_summary_positions(
    summaries: dict[str, GraphRecordSummary],
    events: Sequence[GraphHistoryEvent],
) -> None:
    for event in events:
        if event.event_type not in {"output_record_accepted", "file_state_accepted"}:
            continue
        if event.event_type == "output_record_accepted":
            if isinstance(event, CompactEventEnvelope) and event.schema_version == 1:
                record_id = cast(str, event.payload["record"]["record_id"])
            else:
                record_id = OutputRecordAcceptedPayload.model_validate(
                    event.payload
                ).record.record_id
        elif isinstance(event, HydratedEvent):
            record_id = getattr(event.payload, "record_id", None)
        elif event.schema_version == 1 and event.event_type == "file_state_accepted":
            record_id = event.payload.get("record_id")
        else:
            continue
        if not isinstance(record_id, str):
            continue
        summary = summaries.get(record_id)
        if summary is not None:
            summaries[record_id] = summary.model_copy(update={"position": event.position})


def _record_type_for_summary(
    payload: dict[str, Any],
    projection: GraphProjection,
) -> str | None:
    record_type = payload.get("record_type")
    if isinstance(record_type, str):
        return record_type
    record_kind = payload.get("record_kind")
    if record_kind == "file_state":
        return "file_state"
    if record_kind == "verification":
        return "verification_report"
    producer_node_id = payload.get("producer_node_id")
    port = payload.get("port")
    if isinstance(producer_node_id, str) and isinstance(port, str):
        node_kind = projection["node_kinds"].get(producer_node_id)
        node_role = projection["node_roles"].get(producer_node_id)
        contract = (
            DEFAULT_NODE_CONTRACTS.contract_for(node_kind, node_role)
            if node_kind is not None
            else None
        )
        port_contract = output_port_contract(contract, port) if contract is not None else None
        if port_contract is not None and port_contract.record_types:
            return sorted(port_contract.record_types)[0]
    return record_kind if isinstance(record_kind, str) else None


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
            record_id = event_payload_json(event).get("record_id")
            if isinstance(record_id, str):
                file_state_records[record_id] = event.payload
            continue
        if event.event_type != "gatekeeper_verdict_recorded":
            continue
        record_id = event_payload_json(event).get("file_state_record_id")
        verdicts = event_payload_json(event).get("verdicts")
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


def project_gatekeeper_report(events: Sequence[GraphHistoryEvent]) -> dict[str, dict[str, Any]]:
    """Project gatekeeper cost, hit-rate, and pattern-library growth per run."""
    reports: dict[str, GatekeeperReport] = {}
    prefixes: dict[str, list[EventEnvelope]] = {}
    for history_event in events:
        event = _history_event_envelope(history_event)
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
            library = project_pattern_library(prefixes[event.run_id])
            record_id = (
                event.payload.get("record_id")
                if event.schema_version == 1
                else event_payload_json(event).get("record_id")
            )
            reports[event.run_id] = run.model_copy(
                update={
                    "deterministic_classifications": run.deterministic_classifications
                    + deterministic,
                    "unresolved_residue": run.unresolved_residue + unresolved,
                    "boundary_count": run.boundary_count + 1,
                    "pattern_library_size_over_time": [
                        *run.pattern_library_size_over_time,
                        GatekeeperPatternLibrarySizeRow(
                            position=event.position,
                            file_state_record_id=record_id if isinstance(record_id, str) else None,
                            size=len(library["patterns"]),
                        ),
                    ],
                }
            )
        elif event.event_type == "gatekeeper_verdict_recorded":
            verdicts = (
                event.payload.get("verdicts")
                if event.schema_version == 1
                else event_payload_json(event).get("verdicts")
            )
            resolved = len(cast(list[Any], verdicts)) if isinstance(verdicts, list) else 0
            library = project_pattern_library(prefixes[event.run_id])
            record_id = (
                event.payload.get("file_state_record_id")
                if event.schema_version == 1
                else event_payload_json(event).get("file_state_record_id")
            )
            reports[event.run_id] = run.model_copy(
                update={
                    "gatekeeper_resolved": run.gatekeeper_resolved + resolved,
                    "unresolved_residue": max(0, run.unresolved_residue - resolved),
                    "pattern_library_size_over_time": [
                        *run.pattern_library_size_over_time,
                        GatekeeperPatternLibrarySizeRow(
                            position=event.position,
                            file_state_record_id=record_id if isinstance(record_id, str) else None,
                            size=len(library["patterns"]),
                        ),
                    ],
                }
            )
        elif event.event_type == "gatekeeper_cost_recorded":
            reports[event.run_id] = _record_model_cost(run, event.payload)

    for run_id, run in reports.items():
        total_classified = run.deterministic_classifications + run.gatekeeper_resolved
        reports[run_id] = run.model_copy(
            update={
                "total_classified": total_classified,
                "hit_rate": (
                    run.deterministic_classifications / total_classified
                    if total_classified
                    else 0.0
                ),
                "pattern_library_size": (
                    run.pattern_library_size_over_time[-1].size
                    if run.pattern_library_size_over_time
                    else 0
                ),
            }
        )
    return {run_id: report.model_dump(mode="json") for run_id, report in reports.items()}


def _project(catalog: GraphCatalog, events: Sequence[GraphHistoryEvent]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(catalog, projection, event)
    return projection


def build_projection(catalog: GraphCatalog, events: Sequence[GraphHistoryEvent]) -> GraphProjection:
    """Fold *events* into a full :class:`GraphProjection`.

    Public entry point for callers (e.g. read-model presenters) that need to
    fold the event stream once and pass the result into the various
    ``project_*`` view functions via their ``projection=`` argument, avoiding
    a full re-fold per view.
    """
    return _project(catalog, events)


def _has_full_event_history(events: list[EventEnvelope]) -> bool:
    # Compact envelopes carry transitional flat output-record payloads, not the
    # durable nested shape the event-introspection helpers read; treat those
    # histories as partial so callers use the projection-based fallbacks.
    return (
        bool(events)
        and events[0].position <= 1
        and not any(isinstance(event, CompactEventEnvelope) for event in events)
    )


_PENDING_DECISION_STATES = {"planned", "blocked", "ready", "leased", "running", "suspended"}


def _latest_node_creation_payloads(
    events: Sequence[GraphHistoryEvent],
) -> dict[str, NodeCreationProjection]:
    payloads: dict[str, NodeCreationProjection] = {}
    for event in events:
        if _history_event_type(event) != "node_created":
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


def reduce_node_created(
    state: GraphProjection, payload: NodeCreatedPayload, metadata: Any
) -> GraphProjection:
    """Apply a hydrated node creation payload without revisiting storage JSON."""
    next_state = copy_projection(state)
    node_id = payload.node_id
    kind = payload.kind
    role = payload.role
    if payload.state is not None:
        next_state["node_states"][node_id] = payload.state
    next_state["node_creation_positions"].setdefault(node_id, metadata.position)
    node_creation = NodeCreationProjection.model_validate(
        {**payload.model_dump(mode="json"), "position": metadata.position}
    )
    next_state["node_creation_payloads"][node_id] = node_creation
    _record_recovery_node(next_state, payload)
    if kind == "root" and payload.planner_generation_budget is not None:
        next_state["planner_generation_budget"] = payload.planner_generation_budget
    next_state["node_kinds"][node_id] = kind
    if role is not None:
        next_state["node_roles"][node_id] = role
    if kind == "planner" and role == "planner":
        if payload.generation_index is not None:
            next_state["planner_generations"] = PlannerGenerations(
                values={
                    **next_state["planner_generations"].values,
                    node_id: payload.generation_index,
                }
            )
        if payload.region_label is not None:
            next_state["planner_region_labels"] = PlannerRegionLabels(
                values={
                    **next_state["planner_region_labels"].values,
                    node_id: payload.region_label,
                }
            )
        if payload.session_id is not None:
            next_state["planner_sessions"] = PlannerSessions(
                values={**next_state["planner_sessions"].values, node_id: payload.session_id}
            )
            next_state["planner_session_states"] = PlannerSessionStates(
                values={
                    **next_state["planner_session_states"].values,
                    payload.session_id: next_state["planner_session_states"].values.get(
                        payload.session_id, "detached"
                    ),
                }
            )
            next_state["planner_session_carryovers"] = PlannerSessionCarryovers(
                values={
                    **next_state["planner_session_carryovers"].values,
                    payload.session_id: next_state["planner_session_carryovers"].values.get(
                        payload.session_id
                    ),
                }
            )
    if payload.task_region_id is not None:
        next_state["node_task_regions"][node_id] = payload.task_region_id
    if payload.attempt_number is not None:
        next_state["node_attempts"][node_id] = payload.attempt_number
    if payload.candidate_id is not None:
        next_state["node_candidates"][node_id] = payload.candidate_id
    if payload.failed_candidate_id is not None:
        next_state["node_failed_candidates"][node_id] = payload.failed_candidate_id
    if payload.resource_claims:
        next_state["node_resource_claims"][node_id] = payload.resource_claims
    if payload.allowed_actions:
        next_state["node_allowed_actions"][node_id] = payload.allowed_actions
    preconditions = list(payload.preconditions)
    if kind == "check" and "has_command_definition" not in preconditions:
        preconditions.append("has_command_definition")
    if preconditions:
        next_state["node_preconditions"][node_id] = preconditions
    command_definition = _command_definition_for_node_creation(payload)
    if command_definition is not None:
        next_state["node_command_definitions"][node_id] = command_definition
    if kind == "gate" and payload.task_region_id is not None:
        next_state["configured_gates"].setdefault(payload.task_region_id, {})[node_id] = True
    _refresh_derived_topology_state(next_state)
    return next_state


def reduce_node_state_changed(
    state: GraphProjection, payload: NodeStateChangedPayload, metadata: Any
) -> GraphProjection:
    del metadata
    next_state = copy_projection(state)
    next_state["node_states"][payload.node_id] = payload.new_state
    if payload.attempt_number is not None:
        next_state["node_attempts"][payload.node_id] = payload.attempt_number
    _refresh_derived_topology_state(next_state)
    return next_state


def reduce_node_retired(
    state: GraphProjection, payload: NodeRetiredPayload, metadata: Any
) -> GraphProjection:
    del metadata
    next_state = copy_projection(state)
    next_state["node_states"][payload.node_id] = "retired"
    _refresh_derived_topology_state(next_state)
    return next_state


def reduce_node_ready(
    state: GraphProjection, payload: NodeReadyPayload, metadata: Any
) -> GraphProjection:
    del metadata
    next_state = copy_projection(state)
    next_state["last_deferred_reasons"].pop(payload.node_id, None)
    _refresh_derived_topology_state(next_state)
    return next_state


def reduce_node_deferred(
    state: GraphProjection, payload: NodeDeferredPayload, metadata: Any
) -> GraphProjection:
    del metadata
    next_state = copy_projection(state)
    next_state["last_deferred_reasons"][payload.node_id] = payload.reason
    _refresh_derived_topology_state(next_state)
    return next_state


def reduce_node_authority_changed(
    state: GraphProjection, payload: NodeAuthorityChangedPayload, metadata: Any
) -> GraphProjection:
    del metadata
    next_state = copy_projection(state)
    _record_authority_change(next_state, payload)
    _refresh_derived_topology_state(next_state)
    return next_state


def reduce_plan_region_marked_suspect(
    state: GraphProjection, payload: PlanRegionMarkedSuspectPayload, metadata: Any
) -> GraphProjection:
    del metadata
    next_state = copy_projection(state)
    for node_id in payload.region_node_ids:
        next_state["suspect_node_reasons"][node_id] = payload.reason
    _refresh_derived_topology_state(next_state)
    return next_state


def reduce_edge_created(
    state: GraphProjection, payload: EdgeCreatedPayload, metadata: Any
) -> GraphProjection:
    del metadata
    next_state = copy_projection(state)
    _record_edge(next_state, payload)
    _refresh_derived_topology_state(next_state)
    return next_state


def reduce_input_bound(
    state: GraphProjection, payload: InputBoundPayload, metadata: Any
) -> GraphProjection:
    del metadata
    next_state = copy_projection(state)
    _record_input_binding(next_state, payload)
    _refresh_derived_topology_state(next_state)
    return next_state


def reduce_session_state_changed(
    state: GraphProjection, payload: PlannerSessionStateChangedPayload, metadata: Any
) -> GraphProjection:
    del metadata
    next_state = copy_projection(state)
    next_state["planner_session_states"] = PlannerSessionStates(
        values={**next_state["planner_session_states"].values, payload.session_id: payload.state}
    )
    if payload.state == "attached":
        next_state["planner_session_current_nodes"] = PlannerSessionCurrentNodes(
            values={
                **next_state["planner_session_current_nodes"].values,
                payload.session_id: payload.node_id,
            }
        )
    elif payload.state in {"suspended", "detached", "dead"}:
        next_state["planner_session_current_nodes"] = PlannerSessionCurrentNodes(
            values={
                session_id: node_id
                for session_id, node_id in next_state[
                    "planner_session_current_nodes"
                ].values.items()
                if session_id != payload.session_id
            }
        )
    next_state["planner_session_carryovers"] = PlannerSessionCarryovers(
        values={
            **next_state["planner_session_carryovers"].values,
            payload.session_id: payload.carryover_record_id,
        }
    )
    _refresh_derived_topology_state(next_state)
    return next_state


def _refresh_derived_topology_state(state: GraphProjection) -> None:
    state["ready_nodes"] = _ready_nodes(state["node_states"])
    state["task_states"] = _derive_task_states(state)


def refresh_derived_topology_state(state: Any) -> None:
    """Synchronize derived topology views after a domain-owned reducer mutation."""
    _refresh_derived_topology_state(cast(GraphProjection, state))


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


def _callback_idempotency_event_from_payload(
    payload: dict[str, Any],
) -> CallbackIdempotencyEvent | None:
    try:
        return CallbackIdempotencyEvent.model_validate(payload)
    except ValueError:
        return None


def _record_decision_request_details(state: GraphProjection, event: EventEnvelope) -> None:
    node_id = event_payload_json(event).get("producer_node_id")
    if not isinstance(node_id, str):
        return
    record_type = event_payload_json(event).get("record_type")
    port = event_payload_json(event).get("port")
    if record_type not in {"decision_request", "authority_request_record"} and port not in {
        "decision_request",
        "authority_request_record",
    }:
        return
    value = event_payload_json(event).get("value")
    if not isinstance(value, dict):
        return
    projected = _request_details_from_value(cast(dict[str, Any], value))
    if projected is not None:
        state["decision_request_details"][node_id] = projected


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
    for value in (payload.outcome, payload.decision, payload.verdict):
        if isinstance(value, str) and value:
            return value
    if payload.approved is not None:
        return "approved" if payload.approved else "rejected"
    return None


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


def _latest_node_deferrals(events: Sequence[GraphHistoryEvent]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for event in events:
        if event.event_type != "node_deferred":
            continue
        payload = NodeDeferredPayload.model_validate(event.payload)
        node_id = payload.node_id
        reason = payload.reason
        reasons[node_id] = reason
    return reasons


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


def _node_creation_position(events: Sequence[GraphHistoryEvent], node_id: str) -> int:
    for event in events:
        if _history_event_type(event) != "node_created":
            continue
        payload = _node_created_payload_from_event(event)
        if payload is not None and payload.node_id == node_id:
            return _history_event_position(event)
    return 0


def _latest_lease_generation(events: Sequence[GraphHistoryEvent], node_id: str) -> int | None:
    generation: int | None = None
    for event in events:
        if _history_event_type(event) != "lease_granted":
            continue
        if isinstance(event, HydratedEvent):
            payload = event.payload
            event_node_id = getattr(payload, "node_id", None)
            value = getattr(payload, "generation", None)
        elif event.schema_version == 1 and event.event_type == "lease_granted":
            event_node_id = event.payload.get("node_id")
            value = event.payload.get("generation")
        else:
            continue
        if event_node_id != node_id:
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            generation = value
    return generation


def _planner_region_label(
    events: Sequence[GraphHistoryEvent],
    projection: GraphProjection,
    node_id: str,
) -> str | None:
    label = projection["planner_region_labels"].values.get(node_id)
    if label is not None:
        return label
    generation_index = projection["planner_generations"].values.get(node_id)
    if generation_index is None:
        return None
    labels = _seeded_planner_chain_labels(events)
    return labels.get(generation_index)


def _seeded_planner_chain_labels(events: Sequence[GraphHistoryEvent]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for event in events:
        if _history_event_type(event) != "node_created":
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


def _history_event_type(event: GraphHistoryEvent) -> str:
    if isinstance(event, HydratedEvent):
        return event.metadata.event_type
    return event.event_type


def _history_event_envelope(event: GraphHistoryEvent) -> EventEnvelope:
    if isinstance(event, EventEnvelope):
        return event
    return EventEnvelope(
        event_id=event.event_id,
        run_id=event.run_id,
        position=event.position,
        event_type=event.event_type,
        schema_version=event.schema_version,
        actor=event.actor,
        causation_id=event.causation_id,
        correlation_id=event.correlation_id,
        timestamp=event.timestamp,
        payload=event.payload.to_json(),
    )


def _history_event_position(event: GraphHistoryEvent) -> int:
    if isinstance(event, HydratedEvent):
        return event.metadata.position
    return event.position


def _planner_generation_state(events: list[EventEnvelope], lease_id: str) -> str:
    state = "active"
    for event in events:
        if event_payload_json(event).get("lease_id") != lease_id:
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


def _record_candidate(state: GraphProjection, event: EventEnvelope) -> None:
    record_kind = event_payload_json(event).get("record_kind")
    if record_kind is not None and record_kind != "output":
        return
    port = event_payload_json(event).get("port")
    record_type = event_payload_json(event).get("record_type")
    schema = event_payload_json(event).get("schema")
    candidate_ports = {"candidate", "reader_output", "fan_out_inputs"}
    candidate_schemas = {"ImplementationCandidate", "FanOutInputs", "FanOutJoinedInputs"}
    explicit_non_candidate = port is not None or record_type is not None or schema is not None
    if (
        explicit_non_candidate
        and port not in candidate_ports
        and record_type != "candidate"
        and schema not in candidate_schemas
    ):
        return

    producer_node_id = event_payload_json(event).get("producer_node_id")
    task_region_id = _task_region_id(event.payload)
    if task_region_id is None and isinstance(producer_node_id, str):
        task_region_id = state["node_task_regions"].get(producer_node_id)
    if task_region_id is None:
        return

    candidate_id = _candidate_id(event.payload)
    if candidate_id is None:
        record_id = event_payload_json(event).get("record_id")
        candidate_id = record_id if isinstance(record_id, str) else None
    if candidate_id is None:
        return

    attempt_number = _attempt_number(event.payload)
    if attempt_number is None and isinstance(producer_node_id, str):
        attempt_number = state["node_attempts"].get(producer_node_id)
    if attempt_number is None:
        attempt_number = 0

    try:
        candidate = CandidateProjection.model_validate(
            {
                "candidate_id": candidate_id,
                "attempt_number": attempt_number,
                "position": event.position,
                "file_state_record_ids": _record_ids_from_payload(
                    event.payload,
                    "file_state_record_ids",
                ),
                "supersedes_task_region_ids": _task_region_ids_from_payload(
                    event.payload,
                    "supersedes_task_region_ids",
                    "supersedes_task_region_id",
                ),
            }
        )
    except ValueError:
        return
    state["task_candidates"].setdefault(task_region_id, []).append(candidate)


def _record_verdict(state: GraphProjection, event: EventEnvelope) -> None:
    candidate_id = _candidate_id(event.payload)
    if candidate_id is None:
        return
    try:
        verdict = VerifierVerdictProjection.model_validate(
            {
                "candidate_id": candidate_id,
                "verdict": "passed" if event.event_type == "verification_passed" else "failed",
                "position": event.position,
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


def _record_completion_decision(state: GraphProjection, event: EventEnvelope) -> None:
    if state["completion_decision_passed"]:
        return
    if event_payload_json(event).get("record_type") != "completion_decision":
        return
    if event_payload_json(event).get("port") != "completion_decision":
        return
    value = event_payload_json(event).get("value")
    if isinstance(value, dict) and cast(dict[str, Any], value).get("status") == "passed":
        state["completion_decision_passed"] = True


def _record_verification_result(state: GraphProjection, event: EventEnvelope) -> None:
    candidate_id = event_payload_json(event).get("candidate_id")
    if isinstance(candidate_id, str) and event.event_type == "verification_passed":
        if candidate_id not in state["passed_verification_candidate_ids"]:
            state["passed_verification_candidate_ids"].append(candidate_id)
    if isinstance(candidate_id, str) and event.event_type == "verification_failed":
        state["failed_verification_candidate_ids"][candidate_id] = True
    if event.event_type not in {"verification_passed", "verification_failed"}:
        return

    node_id = event_payload_json(event).get("verifier_node_id") or event_payload_json(event).get(
        "node_id"
    )
    record_id = event_payload_json(event).get("record_id")
    if not isinstance(node_id, str) or not node_id:
        return
    if not isinstance(record_id, str) or not record_id:
        return

    result_payload: dict[str, str] = {
        "node_id": node_id,
        "record_id": record_id,
    }
    if isinstance(candidate_id, str) and candidate_id:
        result_payload["candidate_id"] = candidate_id
    task_region_id = event_payload_json(event).get("task_region_id")
    if isinstance(task_region_id, str) and task_region_id:
        result_payload["task_region_id"] = task_region_id
    try:
        result = VerificationResultProjection.model_validate(result_payload)
    except ValueError:
        return
    if event.event_type == "verification_passed":
        state["passed_verification_results_by_record_id"][record_id] = result
    else:
        state["failed_verification_results_by_record_id"][record_id] = result


def _record_check_result(state: GraphProjection, event: EventEnvelope) -> None:
    if not _is_check_result_record(event.payload):
        return
    node_id = event_payload_json(event).get("producer_node_id") or event_payload_json(event).get(
        "node_id"
    )
    if not isinstance(node_id, str):
        return
    status = _check_result_status(event.payload)
    if status is None:
        status = "unknown"
    task_region_id = _task_region_id(event.payload) or state["node_task_regions"].get(node_id)
    result_payload: dict[str, Any] = {
        "node_id": node_id,
        "status": status,
        "position": event.position,
    }
    value = event_payload_json(event).get("value")
    if isinstance(value, dict):
        typed_value = cast(dict[str, Any], value)
        for key in ("classification", "command_text", "stderr", "stdout", "exit_code"):
            if key in typed_value:
                result_payload[key] = typed_value[key]
    if task_region_id is not None:
        result_payload["task_region_id"] = task_region_id
    record_id = event_payload_json(event).get("record_id")
    if isinstance(record_id, str):
        result_payload["record_id"] = record_id
    for field in ("candidate_record_ids", "file_state_record_ids", "evaluated_record_ids"):
        record_ids = _record_ids_from_payload(event.payload, field)
        if record_ids:
            result_payload[field] = record_ids
    try:
        result = CheckResultProjection.model_validate(result_payload)
    except ValueError:
        return
    state["check_results"][node_id] = result


def _copy_output_record_payload(
    payload: LegacyReplayOutputRecordPayload,
) -> LegacyReplayOutputRecordPayload:
    return payload.model_copy(deep=False)


def _output_record_payload_dict(payload: LegacyReplayOutputRecordPayload) -> dict[str, Any]:
    return payload.model_dump(mode="json")


def _parse_output_record_payload(
    payload: dict[str, Any],
) -> LegacyReplayOutputRecordPayload | None:
    model = _output_record_model_for_payload(payload)
    if model is None:
        return None
    normalized = _normalized_output_record_payload(payload, model)
    try:
        return cast(LegacyReplayOutputRecordPayload, model.model_validate(normalized))
    except ValueError:
        if model is OutputRecord:
            fallback = _legacy_output_record_payload(payload)
        else:
            fallback = _generic_output_record_payload(payload)
            if fallback is None:
                fallback = _legacy_output_record_payload(payload)
        if fallback is None:
            return None
        try:
            return LegacyOutputRecord.model_validate(fallback)
        except ValueError:
            return None


def _output_record_model_for_payload(payload: dict[str, Any]) -> type[GraphBaseModel] | None:
    record_kind = payload.get("record_kind")
    record_type = payload.get("record_type")
    schema = payload.get("schema")
    port = payload.get("port")

    if record_kind == "file_state":
        return FileStateRecord
    if record_type == "run_context" or schema == "RunContext":
        return RunContextRecord
    if record_kind == "verification" or record_type in {"verification", "verification_report"}:
        return VerificationReportRecord
    if schema == "VerificationReport" or port in {"verification_report", "verification_result"}:
        return VerificationReportRecord
    if record_type == "completion_decision" or port == "completion_decision":
        return CompletionDecisionRecord
    if record_type == "join_result" or port == "join_result":
        return JoinResultRecord
    if record_type == "check_result" or port == "check_result" or schema == "CheckResult":
        return CheckResultRecord
    if record_type == "candidate" or port == "candidate" or schema == "ImplementationCandidate":
        return CandidateRecord
    if record_type in {"gap_plan", "gap_classification", "classified_gap"}:
        return GapClassificationRecord
    if port in {"gap_plan", "gap_classification", "classified_gap"}:
        return GapClassificationRecord
    if record_type == "decision_record" or port == "decision_record":
        return DecisionRecord
    if record_type == "authority_decision" or port == "authority_decision":
        return AuthorityDecisionRecord
    if record_type == "analysis_summary" or port in {
        "analysis_summary",
        "planning_summary",
        "region_summary",
    }:
        return AnalysisSummaryRecord
    if record_type == "graph_patch_proposal" or port in {"graph_patch_proposal", "graph_patch"}:
        return GraphPatchProposalRecord
    if record_type == "routine_snapshot" or schema == "RoutineSnapshot":
        return RoutineSnapshotRecord
    if record_type == "artifact_reference" or port in {"artifact_reference", "artifact"}:
        return ArtifactReferenceRecord
    if record_type == "requirement_record" or port == "requirement":
        return RequirementRecord
    if record_type == "decision_request" or port == "decision_request":
        return DecisionRequestRecord
    if record_type == "authority_request_record" or port == "authority_request_record":
        return AuthorityRequestRecord
    if record_type == "failure_record" or port == "failure_record":
        return FailureRecord
    if record_type == "recovery_plan" or port == "recovery_plan":
        return RecoveryPlanRecord
    if record_kind in {None, "output"}:
        return OutputRecord
    return None


def _normalized_output_record_payload(
    payload: dict[str, Any],
    model: type[GraphBaseModel],
) -> dict[str, Any]:
    if model is OutputRecord:
        generic = _generic_output_record_payload(payload)
        return generic if generic is not None else dict(payload)
    normalized = dict(payload)
    if model is VerificationReportRecord and normalized.get("record_type") == "verification":
        normalized["record_type"] = "verification_report"
    return normalized


def _generic_output_record_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    value = payload.get("value")
    if not isinstance(value, dict):
        return None
    normalized = dict(payload)
    normalized.setdefault("record_kind", "output")
    schema = normalized.get("schema")
    if not isinstance(schema, str) or not schema:
        record_type = normalized.get("record_type")
        port = normalized.get("port")
        if isinstance(record_type, str) and record_type:
            normalized["schema"] = record_type
        elif isinstance(port, str) and port:
            normalized["schema"] = port
        else:
            normalized["schema"] = "OutputRecord"
    return normalized


def _legacy_output_record_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    record_id = payload.get("record_id")
    node_id = payload.get("producer_node_id") or payload.get("node_id")
    port = payload.get("port")
    if not all(isinstance(value, str) and value for value in (record_id, node_id, port)):
        return None
    normalized = dict(payload)
    normalized["record_id"] = cast(str, record_id)
    normalized["producer_node_id"] = cast(str, node_id)
    normalized["port"] = cast(str, port)
    normalized.setdefault("record_kind", "output")
    return normalized


def _record_node_output_port(state: GraphProjection, event: EventEnvelope) -> None:
    node_id = event_payload_json(event).get("producer_node_id") or event_payload_json(event).get(
        "node_id"
    )
    if not isinstance(node_id, str):
        return
    port = event_payload_json(event).get("port")
    if not isinstance(port, str) or not port:
        if event.event_type == "file_state_accepted":
            port = "file_state"
        else:
            return
    record_id = event_payload_json(event).get("record_id")
    if not isinstance(record_id, str) or not record_id:
        record_id = f"{event.event_type}:{event.position}"
    ports = state["node_output_ports"].setdefault(node_id, {})
    records = ports.setdefault(port, [])
    if record_id not in records:
        records.append(record_id)


def _record_accepted_output_record(
    state: GraphProjection,
    record: LegacyReplayOutputRecordPayload | None,
) -> None:
    if record is None:
        return
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


def _record_accepted_record_summary(state: GraphProjection, event: EventEnvelope) -> None:
    record_id = event_payload_json(event).get("record_id")
    if not isinstance(record_id, str):
        return
    payload = _stable_accepted_record_payload(event.payload)
    summary_values: dict[str, Any] = {"record_id": record_id}
    record_kind = payload.get("record_kind")
    if isinstance(record_kind, str):
        summary_values["record_kind"] = record_kind
    schema = payload.get("schema")
    if isinstance(schema, str):
        summary_values["schema"] = schema
    producer_node_id = payload.get("producer_node_id")
    if isinstance(producer_node_id, str):
        summary_values["producer_node_id"] = producer_node_id
    producer_port = payload.get("port")
    if isinstance(producer_port, str):
        summary_values["producer_port"] = producer_port
    record_type = _record_type_for_summary(payload, state)
    if record_type is not None:
        summary_values["record_type"] = record_type
    state["accepted_record_summaries_by_id"][record_id] = GraphRecordSummary.model_validate(
        summary_values
    )


_DURABLE_RECORD_DECORATION_FIELDS = frozenset(
    {
        "created_at",
        "graph_position",
        "payload",
        "producer_port",
        "provenance",
        "run_id",
        "schema_version",
    }
)


def _stable_accepted_record_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in payload.items() if key not in _DURABLE_RECORD_DECORATION_FIELDS
    }


def _record_output_record(
    state: GraphProjection,
    record: LegacyReplayOutputRecordPayload | None,
) -> None:
    if record is None:
        return
    state["output_records_by_node_port"].setdefault(record.producer_node_id, {}).setdefault(
        record.port,
        [],
    ).append(record)


def _record_output_payload(
    state: GraphProjection,
    record: LegacyReplayOutputRecordPayload | None,
) -> None:
    if record is None:
        return
    if record.record_id:
        state["output_record_payloads"][record.record_id] = record


def _record_latest_routine_snapshot(state: GraphProjection, event: EventEnvelope) -> None:
    payload = event.payload
    record_id = payload.get("record_id")
    producer_node_id = payload.get("producer_node_id")
    port = payload.get("port")
    if not all(isinstance(value, str) and value for value in (record_id, producer_node_id, port)):
        return
    is_routine_snapshot = (
        payload.get("record_type") == "routine_snapshot"
        or payload.get("record_kind") == "routine_snapshot"
        or payload.get("schema") == "RoutineSnapshot"
        or (producer_node_id == "routine-snapshot" and port in {"snapshot", "routine_snapshot"})
    )
    if not is_routine_snapshot:
        return
    state["latest_routine_snapshot_record"] = LatestRoutineSnapshotRecord(
        record_id=cast(str, record_id),
        producer_node_id=cast(str, producer_node_id),
        port=cast(str, port),
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
    passed = decision in {"granted", "approved", "passed", "accepted"}
    state["node_gate_decisions"][node_id] = passed


def _record_edge(state: GraphProjection, payload: EdgeCreatedPayload) -> None:
    edge_id = payload.edge_id
    edge_payload: dict[str, Any] = {
        "edge_id": edge_id,
        "from_node_id": payload.from_node_id,
        "from_port": payload.from_port,
        "to_node_id": payload.to_node_id,
        "to_port": payload.to_port,
        "required": payload.required,
        "dependency_type": payload.dependency_type or "input_binding",
    }
    for key in ("from_node_kind", "from_node_role"):
        value = getattr(payload, key, None)
        if isinstance(value, str) and value:
            edge_payload[key] = value
    if payload.accepted_record_selector is not None:
        edge_payload["accepted_record_selector"] = normalize_record_selector(
            payload.accepted_record_selector
        )
    for key in _EDGE_METADATA_KEYS:
        value = getattr(payload, key, None)
        if value is None:
            continue
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


def _record_input_binding(state: GraphProjection, payload: InputBoundPayload) -> None:
    to_node_id = payload.to_node_id
    to_port = payload.to_port
    edge_id = payload.edge_id
    binding: dict[str, Any] = {
        "to_node_id": to_node_id,
        "to_port": to_port,
        "edge_id": edge_id,
        "record_ids": list(payload.record_ids),
        "bound_at_position": payload.bound_at_position,
    }
    if payload.supersedes_record_id is not None:
        binding["supersedes_record_id"] = payload.supersedes_record_id
    if payload.record_bound_positions is not None:
        binding["record_bound_positions"] = dict(payload.record_bound_positions)
    if payload.trigger is not None:
        binding["trigger"] = payload.trigger
    existing_binding = state["input_bindings"].get(to_node_id, {}).get(to_port)
    policy = _binding_policy_for_input_event(state, binding, to_node_id, to_port)
    binding["binding_policy"] = policy
    merged_ids = merge_bound_record_ids(
        policy,
        _bound_record_ids(existing_binding or {}),
        _bound_record_ids(binding),
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
        return binding_policy_for_edge(edge, target_port)
    return binding_policy_for_edge(binding, target_port)


def _edge_for_input_binding(
    state: GraphProjection,
    binding: dict[str, Any],
    to_node_id: str,
    to_port: str,
) -> dict[str, Any] | None:
    edge_id = binding.get("edge_id")
    if isinstance(edge_id, str):
        edge = state["edges"].get(edge_id)
        if edge is not None:
            return edge
    for edge in state["edges"].values():
        if edge.get("to_node_id") == to_node_id and edge.get("to_port") == to_port:
            return edge
    return None


def _target_port_for_binding(
    state: GraphProjection,
    edge: dict[str, Any] | None,
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
    existing_binding: dict[str, Any] | None,
    incoming_binding: dict[str, Any],
    merged_ids: list[str],
) -> dict[str, int]:
    positions: dict[str, int] = {}
    if existing_binding is not None:
        raw_existing_positions = existing_binding.get("record_bound_positions")
        if isinstance(raw_existing_positions, dict):
            for record_id, position in cast(dict[Any, Any], raw_existing_positions).items():
                if isinstance(record_id, str) and isinstance(position, int):
                    positions[record_id] = position
        else:
            bound_at_position = existing_binding.get("bound_at_position")
            if isinstance(bound_at_position, int) and not isinstance(bound_at_position, bool):
                for record_id in _bound_record_ids(existing_binding):
                    positions.setdefault(record_id, bound_at_position)

    incoming_position = incoming_binding.get("bound_at_position")
    if not isinstance(incoming_position, int) or isinstance(incoming_position, bool):
        incoming_position = 0
    for record_id in _bound_record_ids(incoming_binding):
        positions.setdefault(record_id, incoming_position)
    return {record_id: positions[record_id] for record_id in merged_ids if record_id in positions}


def _record_authority_change(state: GraphProjection, payload: NodeAuthorityChangedPayload) -> None:
    node_id = payload.node_id
    if "resource_claims" in payload.model_fields_set:
        state["node_resource_claims"][node_id] = payload.resource_claims

    if "allowed_actions" in payload.model_fields_set:
        state["node_allowed_actions"][node_id] = payload.allowed_actions

    if "preconditions" in payload.model_fields_set:
        state["node_preconditions"][node_id] = payload.preconditions


def _record_environment_failure(state: GraphProjection, event: EventEnvelope) -> None:
    task_region_id = _task_region_id(event.payload)
    node_id = event_payload_json(event).get("node_id")
    if task_region_id is None and isinstance(node_id, str):
        task_region_id = state["node_task_regions"].get(node_id)
    if task_region_id is None:
        return

    classification = event_payload_json(event).get("classification")
    value = event_payload_json(event).get("value")
    if isinstance(value, dict):
        typed_value = cast(dict[str, Any], value)
        classification = typed_value.get("classification", classification)
    is_environment = event.event_type == "environment_failure_accepted" or classification in {
        "environment_error",
        "tool_error",
        "tool_unavailable",
    }
    if not is_environment:
        return

    failure = _environment_failure_from_event_payload(task_region_id, event)
    if failure is not None:
        state["environment_failures"][task_region_id] = failure


def _environment_failure_from_event_payload(
    task_region_id: str,
    event: EventEnvelope,
) -> EnvironmentFailureProjection | None:
    payload = {
        **event.payload,
        "position": event.position,
        "task_region_id": task_region_id,
    }
    value = payload.get("value")
    if isinstance(value, dict):
        typed_value = cast(dict[str, Any], value)
        payload["classification"] = typed_value.get("classification", payload.get("classification"))
        payload["command_text"] = typed_value.get("command_text", payload.get("command_text"))
        payload["stderr"] = typed_value.get("stderr", payload.get("stderr"))
        payload["exit_code"] = typed_value.get("exit_code", payload.get("exit_code"))
        if payload.get("reason") is None:
            derived_reason_payload = dict(typed_value)
            derived_reason_payload["classification"] = payload.get("classification")
            payload["reason"] = _environment_failure_reason_from_check_value(
                derived_reason_payload,
            )
    return _environment_failure_from_payload(payload)


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
    stderr = value.get("stderr")
    if classification == "tool_unavailable":
        return f"check tool unavailable while running: {command_label}"
    if classification == "tool_error":
        return f"check tool error while running: {command_label}"
    if classification == "environment_error":
        return f"check environment setup failed while running: {command_label}"
    if isinstance(stderr, str) and stderr.strip():
        return stderr.strip().splitlines()[0]
    return "check failed because of the execution environment"


def _record_file_state(state: GraphProjection, event: EventEnvelope) -> None:
    record_id = event_payload_json(event).get("record_id")
    if not isinstance(record_id, str):
        return
    record = _file_state_record_from_payload(
        {
            **event.payload,
            "run_id": event.run_id,
            "position": event.position,
        }
    )
    if record is None:
        return
    state["file_state_records"][record_id] = record


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
                entry = file_entry_values(raw_entry)
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


def _empty_gatekeeper_report(run_id: str) -> GatekeeperReport:
    return GatekeeperReport(
        run_id=run_id,
        boundary_count=0,
        deterministic_classifications=0,
        gatekeeper_consults=0,
        gatekeeper_resolved=0,
        unresolved_residue=0,
        total_classified=0,
        hit_rate=0.0,
        pattern_library_size=0,
        pattern_library_size_over_time=[],
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=0.0,
        wall_time_ms=0,
        models={},
    )


def _record_model_cost(run: GatekeeperReport, payload: dict[str, Any]) -> GatekeeperReport:
    model_id = payload.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        model_id = "unknown"
    model = run.models.get(model_id) or GatekeeperCostRow(
        model_id=model_id,
        consults=0,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=0.0,
        wall_time_ms=0,
        executions=[],
    )
    execution_id = payload.get("execution_id")
    executions = model.executions
    if isinstance(execution_id, str) and execution_id not in executions:
        executions = [*executions, execution_id]
    return run.model_copy(
        update={
            "gatekeeper_consults": run.gatekeeper_consults + 1,
            "input_tokens": run.input_tokens + _payload_number(payload, "input_tokens"),
            "output_tokens": run.output_tokens + _payload_number(payload, "output_tokens"),
            "cache_read_tokens": run.cache_read_tokens
            + _payload_number(payload, "cache_read_tokens"),
            "cache_write_tokens": run.cache_write_tokens
            + _payload_number(payload, "cache_write_tokens"),
            "cost_usd": run.cost_usd + _payload_float(payload, "cost_usd"),
            "wall_time_ms": run.wall_time_ms + _payload_number(payload, "wall_time_ms"),
            "models": {
                **run.models,
                model_id: GatekeeperCostRow(
                    model_id=model_id,
                    consults=model.consults + 1,
                    input_tokens=model.input_tokens + _payload_number(payload, "input_tokens"),
                    output_tokens=model.output_tokens + _payload_number(payload, "output_tokens"),
                    cache_read_tokens=model.cache_read_tokens
                    + _payload_number(payload, "cache_read_tokens"),
                    cache_write_tokens=model.cache_write_tokens
                    + _payload_number(payload, "cache_write_tokens"),
                    cost_usd=model.cost_usd + _payload_float(payload, "cost_usd"),
                    wall_time_ms=model.wall_time_ms + _payload_number(payload, "wall_time_ms"),
                    executions=executions,
                ),
            },
        }
    )


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
        source = edge.get("from_node_id")
        target = edge.get("to_node_id")
        if isinstance(source, str) and isinstance(target, str):
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


def _task_region_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("task_region_id")
    if isinstance(value, str):
        return value
    membership = payload.get("membership")
    if isinstance(membership, dict):
        typed_membership = cast(dict[str, Any], membership)
        value = typed_membership.get("task_region_id")
        if isinstance(value, str):
            return value
    return None


def _attempt_number(payload: dict[str, Any]) -> int | None:
    value = payload.get("attempt_number")
    if isinstance(value, int):
        return value
    membership = payload.get("membership")
    if isinstance(membership, dict):
        typed_membership = cast(dict[str, Any], membership)
        value = typed_membership.get("attempt_number")
        if isinstance(value, int):
            return value
    return None


def _candidate_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("candidate_id")
    if isinstance(value, str):
        return value
    membership = payload.get("membership")
    if isinstance(membership, dict):
        typed_membership = cast(dict[str, Any], membership)
        value = typed_membership.get("candidate_id")
        if isinstance(value, str):
            return value
    return None


def _record_ids_from_payload(payload: dict[str, Any], field: str) -> list[str]:
    for source in (
        payload,
        payload.get("value"),
        payload.get("provenance"),
        payload.get("evidence"),
    ):
        if not isinstance(source, dict):
            continue
        raw_value = cast(dict[str, Any], source).get(field)
        if not isinstance(raw_value, list):
            continue
        record_ids = [
            record_id for record_id in cast(list[Any], raw_value) if isinstance(record_id, str)
        ]
        if record_ids:
            return record_ids
    return []


def _task_region_ids_from_payload(
    payload: dict[str, Any],
    list_field: str,
    scalar_field: str,
) -> list[str]:
    raw_list = payload.get(list_field)
    if isinstance(raw_list, list):
        return [value for value in cast(list[Any], raw_list) if isinstance(value, str)]
    raw_scalar = payload.get(scalar_field)
    if isinstance(raw_scalar, str):
        return [raw_scalar]
    return []


def _command_definition_for_node_creation(
    payload: NodeCreationProjection | NodeCreatedPayload,
) -> CommandDefinitionProjection | None:
    return check_command_reference(payload.model_dump(mode="json"))


derive_task_states = _derive_task_states
record_open_appeal = _record_open_appeal
record_latest_decision = _record_latest_decision
record_latest_approval_decision = _record_latest_approval_decision
record_latest_authority_decision = _record_latest_authority_decision
record_oversight_decision = _record_oversight_decision
record_gate_decision = _record_gate_decision
record_authority_decision = _record_authority_decision
authority_required_reason = _authority_required_reason
mark_superseded_support_stale = _mark_superseded_support_stale
requirement_revision_classification = _requirement_revision_classification
requirement_revision_from_payload = _requirement_revision_from_payload
requires_explicit_requirement_authority = _requires_explicit_requirement_authority
support_evidence_from_payload = _support_evidence_from_payload
