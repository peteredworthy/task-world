"""Immutable destination models for the future graph-projection cutover.

This module is deliberately passive: production reducers do not construct these
models until the later cutover task.  Conversion copies transport records at the
boundary, preventing mutable event payloads from becoming projected state.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from orchestrator.graph.models import AcceptedOutputRecordPayload, OUTPUT_RECORD_MODELS_BY_TYPE
from orchestrator.graph.projection_collections import FrozenJsonValue, FrozenMap, freeze_json


class ProjectionModel(BaseModel):
    """Strict, immutable base for every model reachable from the scaffold."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, populate_by_name=True)


def _freeze_sequence(value: object, message: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(message)
    return tuple(cast(list[object] | tuple[object, ...], value))


class LifecycleProjection(ProjectionModel):
    run_state: StrictStr | None = None
    completion_decision_passed: StrictBool = False


class ResourceClaimValue(ProjectionModel):
    mode: StrictStr
    scope: StrictStr
    paths: tuple[StrictStr, ...] | None = None
    external_resource_key: StrictStr | None = None

    @field_validator("paths", mode="before")
    @classmethod
    def freeze_paths(cls, value: object) -> tuple[object, ...] | None:
        if value is None:
            return None
        return _freeze_sequence(value, "paths must be a sequence")


class CommandDefinitionValue(ProjectionModel):
    """Frozen wrapper for the deliberately open command-definition JSON object."""

    value: FrozenMap[StrictStr, FrozenJsonValue]

    @field_validator("value", mode="before")
    @classmethod
    def freeze_command(cls, value: object) -> FrozenMap[str, FrozenJsonValue]:
        frozen = freeze_json(value)
        if not isinstance(frozen, FrozenMap):
            raise ValueError("command definition must be a JSON object")
        return frozen


class DecisionRequestValue(ProjectionModel):
    decision_type: StrictStr
    options: tuple[StrictStr, ...]
    default_option: StrictStr | None = None
    consequence_summary: StrictStr
    expires_at: StrictStr | None = None
    target_node_id: StrictStr | None = None
    target_region_id: StrictStr | None = None

    @field_validator("options", mode="before")
    @classmethod
    def freeze_request_ids(cls, value: object) -> tuple[object, ...] | None:
        return _freeze_sequence(value, "request values must be a sequence")

    @model_validator(mode="after")
    def options_are_consistent(self) -> "DecisionRequestValue":
        if not self.options:
            raise ValueError("decision request requires at least one option")
        if self.default_option is not None and self.default_option not in self.options:
            raise ValueError("decision request default_option must be one of options")
        return self


class AuthorityRequestValue(ProjectionModel):
    requested_authority: tuple[StrictStr, ...]
    target_node_id: StrictStr | None = None
    target_region_id: StrictStr | None = None
    reason: StrictStr
    expires_at: StrictStr | None = None

    @field_validator("requested_authority", mode="before")
    @classmethod
    def freeze_requested_authority(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "requested_authority must be a sequence")

    @model_validator(mode="after")
    def target_is_present(self) -> "AuthorityRequestValue":
        if self.target_node_id is None and self.target_region_id is None:
            raise ValueError("authority request requires target_node_id or target_region_id")
        return self


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

    @field_validator("resource_claims", "allowed_actions", "preconditions", mode="before")
    @classmethod
    def freeze_node_sequences(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "node sequences must be sequences")

    @field_validator("command_definition", mode="before")
    @classmethod
    def wrap_command_definition(cls, value: object) -> object:
        if value is None or isinstance(value, CommandDefinitionValue):
            return value
        if isinstance(value, FrozenMap) or isinstance(value, dict):
            return {"value": cast(object, value)}
        raise ValueError("command_definition must be a JSON object")


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
    attempt_number: StrictInt
    position: StrictInt
    file_state_record_ids: tuple[StrictStr, ...] = ()
    supersedes_task_region_ids: tuple[StrictStr, ...] = ()

    @field_validator("file_state_record_ids", "supersedes_task_region_ids", mode="before")
    @classmethod
    def freeze_candidate_ids(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "candidate IDs must be a sequence")


class TaskProjection(ProjectionModel):
    state: StrictStr | None = None
    candidates: tuple[CandidateValue, ...] = ()


class EdgeValue(ProjectionModel):
    edge_id: StrictStr
    from_node_id: StrictStr
    from_port: StrictStr
    to_node_id: StrictStr
    to_port: StrictStr
    required: StrictBool = True
    dependency_type: Literal["input_binding", "state_dependency"] = "input_binding"
    from_node_kind: StrictStr | None = None
    from_node_role: StrictStr | None = None
    accepted_record_selector: FrozenJsonValue | None = None
    purpose: FrozenJsonValue | None = None
    description: FrozenJsonValue | None = None
    selection: FrozenJsonValue | None = None
    binding_policy: FrozenJsonValue | None = None
    freshness_policy: FrozenJsonValue | None = None
    prompt_hydration_policy: FrozenJsonValue | None = None
    metadata: FrozenMap[StrictStr, FrozenJsonValue] = Field(default_factory=FrozenMap)

    @field_validator(
        "accepted_record_selector",
        "purpose",
        "description",
        "selection",
        "binding_policy",
        "freshness_policy",
        "prompt_hydration_policy",
        "metadata",
        mode="before",
    )
    @classmethod
    def freeze_edge_json(cls, value: object) -> FrozenJsonValue | None:
        return None if value is None else freeze_json(value)


class InputBindingValue(ProjectionModel):
    edge_id: StrictStr | None = None
    to_node_id: StrictStr
    to_port: StrictStr
    record_ids: tuple[StrictStr, ...] = ()
    bound_at_position: StrictInt
    record_bound_positions: FrozenMap[StrictStr, StrictInt] | None = None
    binding_policy: StrictStr | None = None
    trigger: StrictStr | None = None
    supersedes_record_id: StrictStr | None = None

    @field_validator("record_ids", mode="before")
    @classmethod
    def freeze_record_ids(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "record IDs must be a sequence")


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


class LatestRoutineSnapshotProjection(ProjectionModel):
    record_id: StrictStr
    producer_node_id: StrictStr
    port: StrictStr


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
    latest_routine_snapshot: LatestRoutineSnapshotProjection | None = None
    generation_by_node: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    session_id_by_node: FrozenMap[StrictStr, StrictStr] = Field(default_factory=FrozenMap)
    sessions: FrozenMap[StrictStr, PlannerSessionProjection] = Field(default_factory=FrozenMap)
    region_label_by_node: FrozenMap[StrictStr, StrictStr] = Field(default_factory=FrozenMap)


class RecoveryNodeIndexValue(ProjectionModel):
    node_id: StrictStr
    recovery_reason: StrictStr


class VerificationResultValue(ProjectionModel):
    node_id: StrictStr
    record_id: StrictStr
    candidate_id: StrictStr | None = None
    task_region_id: StrictStr | None = None


class CheckResultValue(ProjectionModel):
    node_id: StrictStr
    status: StrictStr
    position: StrictInt
    task_region_id: StrictStr | None = None
    record_id: StrictStr | None = None
    classification: StrictStr | None = None
    command_text: StrictStr | None = None
    stderr_tail: StrictStr | None = None
    stdout_tail: StrictStr | None = None
    exit_code: StrictInt | None = None
    candidate_record_ids: tuple[StrictStr, ...] = ()
    file_state_record_ids: tuple[StrictStr, ...] = ()
    evaluated_record_ids: tuple[StrictStr, ...] = ()

    @field_validator(
        "candidate_record_ids", "file_state_record_ids", "evaluated_record_ids", mode="before"
    )
    @classmethod
    def freeze_check_ids(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "check record IDs must be a sequence")


class InvalidTestBlockValue(ProjectionModel):
    position: StrictInt
    accepted: StrictBool | None = None
    appeal_open: StrictBool | None = None
    candidate_id: StrictStr | None = None


class VerifierVerdictValue(ProjectionModel):
    candidate_id: StrictStr
    verdict: Literal["passed", "failed"]
    position: StrictInt


class DecisionActorValue(ProjectionModel):
    kind: StrictStr
    id: StrictStr | None = None


class ApprovalDecisionValue(ProjectionModel):
    node_id: StrictStr
    decision: Literal["approved", "rejected", "deferred"]
    task_region_id: StrictStr | None = None
    gate_id: StrictStr | None = None
    appeal_node_id: StrictStr | None = None
    decider: DecisionActorValue | StrictStr | None = None
    scope: FrozenJsonValue | None = None
    expires_at: StrictStr | None = None
    reason: StrictStr | None = None


class AuthorityDecisionValue(ProjectionModel):
    node_id: StrictStr
    decision: Literal["granted", "denied", "deferred"]
    task_region_id: StrictStr | None = None
    appeal_node_id: StrictStr | None = None
    decider: DecisionActorValue | StrictStr | None = None
    scope: FrozenJsonValue | None = None
    expires_at: StrictStr | None = None
    reason: StrictStr | None = None


class OversightDecisionValue(ProjectionModel):
    node_id: StrictStr
    decision: Literal["accepted", "rejected", "invalid_test_accepted"]
    position: StrictInt
    task_region_id: StrictStr | None = None
    candidate_id: StrictStr | None = None
    gate_id: StrictStr | None = None
    appeal_node_id: StrictStr | None = None
    appealed_node_id: StrictStr | None = None
    appeal_type: StrictStr | None = None
    decider: FrozenJsonValue | StrictStr | None = None
    scope: FrozenJsonValue | None = None
    expires_at: StrictStr | None = None
    reason: StrictStr | None = None


class RequirementRevisionValue(ProjectionModel):
    requirement_id: StrictStr
    version_id: StrictStr
    change_classification: StrictStr
    requires_authority: StrictBool
    position: StrictInt
    previous_version_id: StrictStr | None = None
    revision_index: StrictInt | None = None
    authority_required_reason: StrictStr | None = None
    validation_strengthening: StrictBool


class SupportEvidenceValue(ProjectionModel):
    support_id: StrictStr
    evidence_id: StrictStr
    requirement_id: StrictStr
    requirement_version_id: StrictStr
    status: StrictStr
    position: StrictInt
    stale_reason: StrictStr | None = None
    confidence: StrictStr | None = None


class LeaseValue(ProjectionModel):
    lease_id: StrictStr
    state: Literal["active", "suspended", "revoked", "expired", "released"]
    node_id: StrictStr | None = None
    generation: StrictInt | None = None
    execution_id: StrictStr | None = None
    expires_at: StrictStr | None = None
    session_id: StrictStr | None = None
    base_snapshot_id: StrictStr | None = None
    task_region_id: StrictStr | None = None
    kind: StrictStr | None = None
    resource_claims: tuple[ResourceClaimValue, ...] = ()

    @field_validator("resource_claims", mode="before")
    @classmethod
    def freeze_lease_claims(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "resource_claims must be a sequence")


class EnvironmentFailureValue(ProjectionModel):
    position: StrictInt
    node_id: StrictStr | None = None
    classification: StrictStr | None = None
    reason: StrictStr | None = None
    task_region_id: StrictStr | None = None
    record_id: StrictStr | None = None
    command_text: StrictStr | None = None
    stderr_tail: StrictStr | None = None
    exit_code: StrictInt | None = None


class CallbackEventValue(ProjectionModel):
    event_type: Literal[
        "callback_accepted",
        "callback_rejected_stale",
        "callback_rejected_conflict",
        "callback_duplicate_returned",
    ]
    node_id: StrictStr
    idempotency_key: StrictStr
    outcome: StrictStr
    payload: FrozenJsonValue | None = None


class CleanupRequestValue(ProjectionModel):
    cleanup_id: StrictStr
    position: StrictInt
    file_state_record_id: StrictStr | None = None
    snapshot_id: StrictStr | None = None
    paths: tuple[StrictStr, ...] = ()
    authority: StrictStr | None = None
    reason: StrictStr | None = None
    execution_id: StrictStr | None = None
    producer_node_id: StrictStr | None = None

    @field_validator("paths", mode="before")
    @classmethod
    def freeze_cleanup_paths(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "paths must be a sequence")


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
    approval_decisions_by_node: FrozenMap[StrictStr, ApprovalDecisionValue] = Field(
        default_factory=FrozenMap
    )
    authority_decisions_by_node: FrozenMap[StrictStr, AuthorityDecisionValue] = Field(
        default_factory=FrozenMap
    )
    oversight_decisions_by_node: FrozenMap[StrictStr, OversightDecisionValue] = Field(
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
