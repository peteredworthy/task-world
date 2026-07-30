"""Immutable destination models for the future graph-projection cutover.

This module is deliberately passive: production reducers do not construct these
models until the later cutover task.  Conversion copies transport records at the
boundary, preventing mutable event payloads from becoming projected state.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
)

from orchestrator.graph.models import AcceptedOutputRecordPayload, OUTPUT_RECORD_MODELS_BY_TYPE
from orchestrator.graph.projection_collections import FrozenJsonValue, FrozenMap, freeze_json


class ProjectionModel(BaseModel):
    """Strict, immutable base for every model reachable from the scaffold."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, populate_by_name=True)


class LifecycleProjection(ProjectionModel):
    run_state: StrictStr | None = None
    completion_decision_passed: StrictBool = False


class ResourceClaimValue(ProjectionModel):
    claim_type: StrictStr
    resource_id: StrictStr
    mode: StrictStr | None = None


class CommandDefinitionValue(ProjectionModel):
    command_id: StrictStr | None = None
    command_text: StrictStr | None = None
    working_directory: StrictStr | None = None
    environment: FrozenMap[StrictStr, FrozenJsonValue] = Field(default_factory=FrozenMap)


class DecisionRequestValue(ProjectionModel):
    gate_type: StrictStr | None = None
    prompt: StrictStr | None = None
    options: tuple[StrictStr, ...] = ()
    default_option: StrictStr | None = None


class AuthorityRequestValue(ProjectionModel):
    authority_type: StrictStr | None = None
    reason: StrictStr | None = None
    metadata: FrozenMap[StrictStr, FrozenJsonValue] = Field(default_factory=FrozenMap)


class NodeSpecProjection(ProjectionModel):
    node_id: StrictStr
    creation_position: StrictInt
    kind: StrictStr | None = None
    role: StrictStr | None = None
    task_region_id: StrictStr | None = None
    resource_claims: tuple[ResourceClaimValue, ...] = ()
    allowed_actions: tuple[StrictStr, ...] = ()
    preconditions: tuple[StrictStr, ...] = ()
    gate_type: StrictStr | None = None
    approval_type: StrictStr | None = None
    reason: StrictStr | None = None
    prompt: StrictStr | None = None
    approval_prompt: StrictStr | None = None
    human_prompt: StrictStr | None = None
    message: StrictStr | None = None
    blocker: StrictStr | None = None
    blocker_reason: StrictStr | None = None
    decision_request: DecisionRequestValue | None = None
    authority_request_record: AuthorityRequestValue | None = None
    authority_request: AuthorityRequestValue | None = None
    authority: AuthorityRequestValue | None = None
    command_definition: CommandDefinitionValue | None = None
    command_definition_id: StrictStr | None = None
    hidden_oracle_command: StrictStr | None = None
    command_binding: StrictStr | None = None
    max_attempts: StrictInt | None = None


class NodeRuntimeProjection(ProjectionModel):
    state: StrictStr | None = None
    attempt_number: StrictInt | None = None
    candidate_id: StrictStr | None = None
    failed_candidate_id: StrictStr | None = None
    suspect_reason: StrictStr | None = None


class NodeSchedulingProjection(ProjectionModel):
    last_deferred_reason: StrictStr | None = None
    retry_not_before: StrictStr | None = None


class NodeProjection(ProjectionModel):
    spec: NodeSpecProjection
    runtime: NodeRuntimeProjection = Field(default_factory=NodeRuntimeProjection)
    scheduling: NodeSchedulingProjection = Field(default_factory=NodeSchedulingProjection)


class CandidateValue(ProjectionModel):
    candidate_id: StrictStr
    record_id: StrictStr | None = None
    task_region_id: StrictStr | None = None
    attempt_number: StrictInt | None = None


class TaskProjection(ProjectionModel):
    state: StrictStr | None = None
    candidates: tuple[CandidateValue, ...] = ()


class EdgeValue(ProjectionModel):
    edge_id: StrictStr
    from_node_id: StrictStr
    from_port: StrictStr
    to_node_id: StrictStr
    to_port: StrictStr
    required: StrictBool = False
    metadata: FrozenMap[StrictStr, FrozenJsonValue] = Field(default_factory=FrozenMap)


class InputBindingValue(ProjectionModel):
    edge_id: StrictStr | None = None
    to_node_id: StrictStr
    to_port: StrictStr
    record_ids: tuple[StrictStr, ...] = ()


class TopologyProjection(ProjectionModel):
    edges: FrozenMap[StrictStr, EdgeValue] = Field(default_factory=FrozenMap)
    input_bindings: FrozenMap[StrictStr, FrozenMap[StrictStr, InputBindingValue]] = Field(
        default_factory=FrozenMap
    )
    inbound_edge_ids: FrozenMap[StrictStr, tuple[StrictStr, ...]] = Field(default_factory=FrozenMap)
    outbound_edge_ids: FrozenMap[StrictStr, tuple[StrictStr, ...]] = Field(
        default_factory=FrozenMap
    )


class GraphRecordSummaryProjection(ProjectionModel):
    record_id: StrictStr | None = None
    record_type: StrictStr | None = None
    record_kind: StrictStr | None = None
    schema_: StrictStr | None = Field(default=None, alias="schema")
    producer_node_id: StrictStr | None = None
    producer_port: StrictStr | None = None
    position: StrictInt | None = None


class FinalInvariantBlockerProjection(ProjectionModel):
    kind: StrictStr
    reason: StrictStr
    node_id: StrictStr | None = None
    edge_id: StrictStr | None = None
    from_node_id: StrictStr | None = None
    to_port: StrictStr | None = None
    proposal_id: StrictStr | None = None
    requirement_id: StrictStr | None = None
    revision_id: StrictStr | None = None
    task_region_id: StrictStr | None = None
    state: StrictStr | None = None
    classification: StrictStr | None = None
    command_text: StrictStr | None = None
    stderr_tail: StrictStr | None = None
    exit_code: StrictInt | None = None
    support_ids: tuple[StrictStr, ...] = ()


class RecordStore(ProjectionModel):
    """Canonical full-record ownership; indexes elsewhere retain identifiers only."""

    by_id: FrozenMap[StrictStr, "ProjectedRecord"] = Field(default_factory=FrozenMap)
    ids_by_node_port: FrozenMap[StrictStr, FrozenMap[StrictStr, tuple[StrictStr, ...]]] = Field(
        default_factory=FrozenMap
    )
    summaries_by_id: FrozenMap[StrictStr, GraphRecordSummaryProjection] = Field(
        default_factory=FrozenMap
    )


class SchedulingProjection(ProjectionModel):
    ready_node_ids: tuple[StrictStr, ...] = ()


class PlannerSessionProjection(ProjectionModel):
    state: StrictStr | None = None
    current_node_id: StrictStr | None = None
    carryover_record_id: StrictStr | None = None


class PlanningProjection(ProjectionModel):
    generation_budget: StrictInt = 8
    successor_by_node: FrozenMap[StrictStr, StrictStr] = Field(default_factory=FrozenMap)
    accepted_patch_ids_by_node: FrozenMap[StrictStr, tuple[StrictStr, ...]] = Field(
        default_factory=FrozenMap
    )
    no_successor_patch_ids_by_node: FrozenMap[StrictStr, tuple[StrictStr, ...]] = Field(
        default_factory=FrozenMap
    )
    latest_no_successor_patch_id_by_node: FrozenMap[StrictStr, StrictStr] = Field(
        default_factory=FrozenMap
    )
    latest_routine_snapshot: GraphRecordSummaryProjection | None = None
    generation_by_node: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    session_id_by_node: FrozenMap[StrictStr, StrictStr] = Field(default_factory=FrozenMap)
    sessions: FrozenMap[StrictStr, PlannerSessionProjection] = Field(default_factory=FrozenMap)
    region_label_by_node: FrozenMap[StrictStr, StrictStr] = Field(default_factory=FrozenMap)


class RecoveryNodeIndexValue(ProjectionModel):
    node_id: StrictStr
    recovery_reason: StrictStr


class VerificationResultValue(ProjectionModel):
    record_id: StrictStr
    candidate_id: StrictStr | None = None
    status: StrictStr | None = None


class CheckResultValue(ProjectionModel):
    node_id: StrictStr
    status: StrictStr
    position: StrictInt
    record_ids: tuple[StrictStr, ...] = ()


class InvalidTestBlockValue(ProjectionModel):
    task_region_id: StrictStr
    reason: StrictStr | None = None


class VerifierVerdictValue(ProjectionModel):
    node_id: StrictStr
    candidate_id: StrictStr | None = None
    verdict: StrictStr | None = None
    position: StrictInt | None = None


class DecisionValue(ProjectionModel):
    node_id: StrictStr
    decision: StrictStr | None = None
    position: StrictInt | None = None
    metadata: FrozenMap[StrictStr, FrozenJsonValue] = Field(default_factory=FrozenMap)


class RequirementRevisionValue(ProjectionModel):
    revision_id: StrictStr
    requirement_id: StrictStr | None = None
    position: StrictInt | None = None
    metadata: FrozenMap[StrictStr, FrozenJsonValue] = Field(default_factory=FrozenMap)


class SupportEvidenceValue(ProjectionModel):
    support_id: StrictStr
    requirement_id: StrictStr | None = None
    evidence_id: StrictStr | None = None
    metadata: FrozenMap[StrictStr, FrozenJsonValue] = Field(default_factory=FrozenMap)


class LeaseValue(ProjectionModel):
    lease_id: StrictStr
    node_id: StrictStr
    state: StrictStr
    generation: StrictInt | None = None
    execution_id: StrictStr | None = None
    expires_at: StrictStr | None = None


class EnvironmentFailureValue(ProjectionModel):
    position: StrictInt
    node_id: StrictStr | None = None
    classification: StrictStr | None = None
    reason: StrictStr | None = None
    task_region_id: StrictStr | None = None


class CallbackEventValue(ProjectionModel):
    callback_id: StrictStr
    event_type: StrictStr
    position: StrictInt | None = None


class CleanupRequestValue(ProjectionModel):
    cleanup_id: StrictStr
    node_id: StrictStr | None = None
    position: StrictInt | None = None


class VerificationProjection(ProjectionModel):
    verdicts_by_node: FrozenMap[StrictStr, VerifierVerdictValue] = Field(default_factory=FrozenMap)
    passed_results_by_record_id: FrozenMap[StrictStr, VerificationResultValue] = Field(
        default_factory=FrozenMap
    )
    failed_results_by_record_id: FrozenMap[StrictStr, VerificationResultValue] = Field(
        default_factory=FrozenMap
    )
    passed_candidate_ids: tuple[StrictStr, ...] = ()
    failed_candidate_ids: FrozenMap[StrictStr, StrictBool] = Field(default_factory=FrozenMap)
    recovery_nodes_by_record_id: FrozenMap[StrictStr, tuple[RecoveryNodeIndexValue, ...]] = Field(
        default_factory=FrozenMap
    )
    check_results_by_node: FrozenMap[StrictStr, CheckResultValue] = Field(default_factory=FrozenMap)
    invalid_test_blocks_by_task: FrozenMap[StrictStr, InvalidTestBlockValue] = Field(
        default_factory=FrozenMap
    )


class GovernanceProjection(ProjectionModel):
    pending_appeals_by_node: FrozenMap[StrictStr, StrictBool] = Field(default_factory=FrozenMap)
    node_gate_decisions: FrozenMap[StrictStr, StrictBool] = Field(default_factory=FrozenMap)
    configured_gates_by_task: FrozenMap[StrictStr, FrozenMap[StrictStr, StrictBool]] = Field(
        default_factory=FrozenMap
    )
    gate_decisions_by_task: FrozenMap[StrictStr, FrozenMap[StrictStr, StrictBool]] = Field(
        default_factory=FrozenMap
    )
    approval_decisions_by_node: FrozenMap[StrictStr, DecisionValue] = Field(
        default_factory=FrozenMap
    )
    authority_decisions_by_node: FrozenMap[StrictStr, DecisionValue] = Field(
        default_factory=FrozenMap
    )
    oversight_decisions_by_node: FrozenMap[StrictStr, DecisionValue] = Field(
        default_factory=FrozenMap
    )
    decision_requests_by_node: FrozenMap[StrictStr, DecisionRequestValue] = Field(
        default_factory=FrozenMap
    )
    authority_revision_blockers: FrozenMap[StrictStr, FinalInvariantBlockerProjection] = Field(
        default_factory=FrozenMap
    )


class RequirementsProjection(ProjectionModel):
    revisions_by_id: FrozenMap[StrictStr, RequirementRevisionValue] = Field(
        default_factory=FrozenMap
    )
    active_version_id_by_requirement: FrozenMap[StrictStr, StrictStr] = Field(
        default_factory=FrozenMap
    )
    support_by_id: FrozenMap[StrictStr, SupportEvidenceValue] = Field(default_factory=FrozenMap)


class ExecutionProjection(ProjectionModel):
    leases: FrozenMap[StrictStr, LeaseValue] = Field(default_factory=FrozenMap)
    environment_failures_by_task: FrozenMap[StrictStr, EnvironmentFailureValue] = Field(
        default_factory=FrozenMap
    )
    callback_events_by_key: FrozenMap[StrictStr, CallbackEventValue] = Field(
        default_factory=FrozenMap
    )
    cleanup_requests_by_id: FrozenMap[StrictStr, CleanupRequestValue] = Field(
        default_factory=FrozenMap
    )
    applied_cleanup_ids: FrozenMap[StrictStr, StrictBool] = Field(default_factory=FrozenMap)


class UsageProjection(ProjectionModel):
    tokens_by_node: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    tokens_by_node_kind: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    latency_ms_by_node_kind: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    execution_count_by_node_kind: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    action_count_by_node_kind: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    recorded_keys: FrozenMap[StrictStr, StrictBool] = Field(default_factory=FrozenMap)


class ImmutableGraphProjection(ProjectionModel):
    """Unused grouped projection scaffold; production ``GraphProjection`` remains canonical."""

    lifecycle: LifecycleProjection = Field(default_factory=LifecycleProjection)
    nodes: FrozenMap[StrictStr, NodeProjection] = Field(default_factory=FrozenMap)
    tasks: FrozenMap[StrictStr, TaskProjection] = Field(default_factory=FrozenMap)
    topology: TopologyProjection = Field(default_factory=TopologyProjection)
    records: RecordStore = Field(default_factory=RecordStore)
    scheduling: SchedulingProjection = Field(default_factory=SchedulingProjection)
    planning: PlanningProjection = Field(default_factory=PlanningProjection)
    verification: VerificationProjection = Field(default_factory=VerificationProjection)
    governance: GovernanceProjection = Field(default_factory=GovernanceProjection)
    requirements: RequirementsProjection = Field(default_factory=RequirementsProjection)
    execution: ExecutionProjection = Field(default_factory=ExecutionProjection)
    usage: UsageProjection = Field(default_factory=UsageProjection)


class ProjectedRecordBase(ProjectionModel):
    record_id: StrictStr
    record_kind: StrictStr
    producer_node_id: StrictStr | None = None
    port: StrictStr
    schema_: StrictStr = Field(alias="schema")
    data: FrozenMap[StrictStr, FrozenJsonValue]

    @field_validator("data", mode="before")
    @classmethod
    def freeze_data(cls, value: object) -> FrozenMap[str, FrozenJsonValue]:
        frozen = freeze_json(value)
        if not isinstance(frozen, FrozenMap):
            raise ValueError("projected record data must be an object")
        return frozen


class ProjectedAnalysisSummaryRecord(ProjectedRecordBase):
    record_type: Literal["analysis_summary"]


class ProjectedArtifactReferenceRecord(ProjectedRecordBase):
    record_type: Literal["artifact_reference"]


class ProjectedAuthorityDecisionRecord(ProjectedRecordBase):
    record_type: Literal["authority_decision"]


class ProjectedAuthorityRequestRecord(ProjectedRecordBase):
    record_type: Literal["authority_request_record"]


class ProjectedCandidateRecord(ProjectedRecordBase):
    record_type: Literal["candidate"]


class ProjectedCheckResultRecord(ProjectedRecordBase):
    record_type: Literal["check_result"]


class ProjectedClassifiedGapRecord(ProjectedRecordBase):
    record_type: Literal["classified_gap"]


class ProjectedCompletionDecisionRecord(ProjectedRecordBase):
    record_type: Literal["completion_decision"]


class ProjectedDecisionRecord(ProjectedRecordBase):
    record_type: Literal["decision_record"]


class ProjectedDecisionRequestRecord(ProjectedRecordBase):
    record_type: Literal["decision_request"]


class ProjectedFailureRecord(ProjectedRecordBase):
    record_type: Literal["failure_record"]


class ProjectedFanOutInputsRecord(ProjectedRecordBase):
    record_type: Literal["fan_out_inputs"]


class ProjectedFileStateRecord(ProjectedRecordBase):
    record_type: Literal["file_state"]


class ProjectedGapClassificationRecord(ProjectedRecordBase):
    record_type: Literal["gap_classification"]


class ProjectedGapPlanRecord(ProjectedRecordBase):
    record_type: Literal["gap_plan"]


class ProjectedGraphPatchProposalRecord(ProjectedRecordBase):
    record_type: Literal["graph_patch_proposal"]


class ProjectedJoinResultRecord(ProjectedRecordBase):
    record_type: Literal["join_result"]


class ProjectedRecoveryPlanRecord(ProjectedRecordBase):
    record_type: Literal["recovery_plan"]


class ProjectedRequirementRecord(ProjectedRecordBase):
    record_type: Literal["requirement_record"]


class ProjectedRoutineSnapshotRecord(ProjectedRecordBase):
    record_type: Literal["routine_snapshot"]


class ProjectedRunContextRecord(ProjectedRecordBase):
    record_type: Literal["run_context"]


class ProjectedVerificationReportRecord(ProjectedRecordBase):
    record_type: Literal["verification_report"]


ProjectedRecord: TypeAlias = Annotated[
    ProjectedAnalysisSummaryRecord
    | ProjectedArtifactReferenceRecord
    | ProjectedAuthorityDecisionRecord
    | ProjectedAuthorityRequestRecord
    | ProjectedCandidateRecord
    | ProjectedCheckResultRecord
    | ProjectedClassifiedGapRecord
    | ProjectedCompletionDecisionRecord
    | ProjectedDecisionRecord
    | ProjectedDecisionRequestRecord
    | ProjectedFailureRecord
    | ProjectedFanOutInputsRecord
    | ProjectedFileStateRecord
    | ProjectedGapClassificationRecord
    | ProjectedGapPlanRecord
    | ProjectedGraphPatchProposalRecord
    | ProjectedJoinResultRecord
    | ProjectedRecoveryPlanRecord
    | ProjectedRequirementRecord
    | ProjectedRoutineSnapshotRecord
    | ProjectedRunContextRecord
    | ProjectedVerificationReportRecord,
    Field(discriminator="record_type"),
]

_PROJECTED_RECORD_MODELS: FrozenMap[str, type[ProjectedRecordBase]] = FrozenMap(
    {
        "analysis_summary": ProjectedAnalysisSummaryRecord,
        "artifact_reference": ProjectedArtifactReferenceRecord,
        "authority_decision": ProjectedAuthorityDecisionRecord,
        "authority_request_record": ProjectedAuthorityRequestRecord,
        "candidate": ProjectedCandidateRecord,
        "check_result": ProjectedCheckResultRecord,
        "classified_gap": ProjectedClassifiedGapRecord,
        "completion_decision": ProjectedCompletionDecisionRecord,
        "decision_record": ProjectedDecisionRecord,
        "decision_request": ProjectedDecisionRequestRecord,
        "failure_record": ProjectedFailureRecord,
        "fan_out_inputs": ProjectedFanOutInputsRecord,
        "file_state": ProjectedFileStateRecord,
        "gap_classification": ProjectedGapClassificationRecord,
        "gap_plan": ProjectedGapPlanRecord,
        "graph_patch_proposal": ProjectedGraphPatchProposalRecord,
        "join_result": ProjectedJoinResultRecord,
        "recovery_plan": ProjectedRecoveryPlanRecord,
        "requirement_record": ProjectedRequirementRecord,
        "routine_snapshot": ProjectedRoutineSnapshotRecord,
        "run_context": ProjectedRunContextRecord,
        "verification_report": ProjectedVerificationReportRecord,
    }
)

if set(_PROJECTED_RECORD_MODELS) != set(OUTPUT_RECORD_MODELS_BY_TYPE):
    raise RuntimeError("projected record registry must cover every accepted output record type")


def project_record(record: AcceptedOutputRecordPayload) -> ProjectedRecord:
    """Copy a validated accepted record into its immutable projection counterpart."""
    if not hasattr(record, "model_dump"):
        raise ValueError("unknown projected record discriminator")
    payload = record.model_dump(mode="json", by_alias=True)
    record_type = payload.get("record_type")
    if not isinstance(record_type, str) or record_type not in _PROJECTED_RECORD_MODELS:
        raise ValueError("unknown projected record discriminator")
    model = _PROJECTED_RECORD_MODELS[record_type]
    adapter: TypeAdapter[ProjectedRecord] = TypeAdapter(ProjectedRecord)
    return adapter.validate_python(
        model.model_validate(
            {
                "record_id": payload["record_id"],
                "record_kind": payload["record_kind"],
                "producer_node_id": payload.get("producer_node_id"),
                "port": payload["port"],
                "schema": payload["schema"],
                "record_type": record_type,
                "data": payload,
            }
        )
    )
