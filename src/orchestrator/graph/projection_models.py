"""Schema-14 immutable models owned by the permanent graph projection.

Production reducers construct these frozen grouped models directly. Conversion
at event and checkpoint boundaries prevents mutable transport payloads from
becoming reachable projected state.
"""

from __future__ import annotations

from typing import Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from orchestrator.graph.models import (
    AcceptedOutputRecordPayload,
    RunnerBoundaryEntry,
    StoredArtifactRef,
    freeze_canonical_record,
)
from orchestrator.graph.cache_authority import CacheStatusEvidence, RunnerCacheRoot
from orchestrator.graph.projection_collections import FrozenJsonValue, FrozenMap, freeze_json


class ProjectionModel(BaseModel):
    """Strict, immutable base for every model reachable from the projection."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        populate_by_name=True,
        revalidate_instances="always",
    )


def _freeze_json_input(value: object) -> FrozenJsonValue:
    if type(value) is FrozenMap:
        return cast(FrozenMap[str, FrozenJsonValue], value)
    return freeze_json(value)


def _freeze_sequence(value: object, message: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(message)
    return tuple(cast(list[object] | tuple[object, ...], value))


def _freeze_sequence_map(value: object, message: str) -> object:
    if type(value) is not dict:
        return value
    dictionary = cast(dict[object, object], value)
    return {key: _freeze_sequence(item, message) for key, item in dictionary.items()}


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
        frozen = _freeze_json_input(value)
        if type(frozen) is not FrozenMap:
            raise ValueError("command definition must be a JSON object")
        return cast(FrozenMap[str, FrozenJsonValue], frozen)


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


class ExecutionAuthorityValue(ProjectionModel):
    """Complete immutable counterpart of the canonical execution authority."""

    allowed_actions: tuple[StrictStr, ...] = ()
    resource_claims: tuple[ResourceClaimValue, ...] = ()
    preconditions: tuple[StrictStr, ...] = ()

    @field_validator("allowed_actions", "resource_claims", "preconditions", mode="before")
    @classmethod
    def freeze_authority_sequences(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "authority values must be sequences")

    @model_validator(mode="after")
    def external_claims_have_keys(self) -> "ExecutionAuthorityValue":
        if any(
            claim.mode == "external" and claim.external_resource_key is None
            for claim in self.resource_claims
        ):
            raise ValueError("external claims require external_resource_key")
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
    authority_request_record_id: StrictStr | None = None
    authority_request: AuthorityRequestValue | None = None
    authority: ExecutionAuthorityValue | None = None
    command_definition: CommandDefinitionValue | None = None
    command_definition_id: StrictStr | None = None
    hidden_oracle_command: StrictStr | None = None
    command_binding: StrictStr | None = None
    max_attempts: StrictInt | None = None
    cache_authority_hash: StrictStr | None = None
    dispatch_payload: FrozenMap[StrictStr, FrozenJsonValue] = Field(default_factory=FrozenMap)

    @field_validator("resource_claims", "allowed_actions", "preconditions", mode="before")
    @classmethod
    def freeze_node_sequences(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "node sequences must be sequences")

    @field_validator("command_definition", mode="before")
    @classmethod
    def wrap_command_definition(cls, value: object, info: ValidationInfo) -> object:
        if value is None or isinstance(value, CommandDefinitionValue):
            return value
        if info.context and info.context.get("canonical_checkpoint") is True:
            return value
        if isinstance(value, FrozenMap) or isinstance(value, dict):
            return {"value": cast(object, value)}
        raise ValueError("command_definition must be a JSON object")

    @field_validator("dispatch_payload", mode="before")
    @classmethod
    def freeze_dispatch_payload(cls, value: object) -> FrozenMap[str, FrozenJsonValue]:
        frozen = _freeze_json_input(value)
        if not isinstance(frozen, FrozenMap):
            raise ValueError("dispatch_payload must be a JSON object")
        return frozen


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

    @field_validator("candidates", mode="before")
    @classmethod
    def freeze_candidates(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "candidates must be a sequence")


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
    metadata: FrozenMap[StrictStr, FrozenJsonValue] | None = None

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
        return None if value is None else _freeze_json_input(value)


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
    input_binding_port_order: FrozenMap[StrictStr, tuple[StrictStr, ...]] = Field(
        default_factory=FrozenMap
    )
    inbound_edge_ids: FrozenMap[StrictStr, tuple[StrictStr, ...]] = Field(default_factory=FrozenMap)
    outbound_edge_ids: FrozenMap[StrictStr, tuple[StrictStr, ...]] = Field(
        default_factory=FrozenMap
    )

    @field_validator(
        "input_binding_port_order", "inbound_edge_ids", "outbound_edge_ids", mode="before"
    )
    @classmethod
    def freeze_adjacency_ids(cls, value: object) -> object:
        return _freeze_sequence_map(value, "edge IDs must be sequences")


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

    @field_validator("support_ids", mode="before")
    @classmethod
    def freeze_support_ids(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "support IDs must be a sequence")


class RecordStore(ProjectionModel):
    """Canonical full-record ownership; indexes elsewhere retain identifiers only."""

    by_id: FrozenMap[StrictStr, AcceptedOutputRecordPayload] = Field(default_factory=FrozenMap)
    ids_by_node_port: FrozenMap[StrictStr, FrozenMap[StrictStr, tuple[StrictStr, ...]]] = Field(
        default_factory=FrozenMap
    )
    summaries_by_id: FrozenMap[StrictStr, GraphRecordSummaryProjection] = Field(
        default_factory=FrozenMap
    )

    @model_validator(mode="after")
    def freeze_canonical_records(self) -> "RecordStore":
        for record in self.by_id.values():
            freeze_canonical_record(record)
        return self

    @field_validator("ids_by_node_port", mode="before")
    @classmethod
    def freeze_record_indexes(cls, value: object) -> object:
        if type(value) is not dict:
            return value
        indexes = cast(dict[object, object], value)
        return {
            node_id: _freeze_sequence_map(ports, "record IDs must be sequences")
            for node_id, ports in indexes.items()
        }


class SchedulingProjection(ProjectionModel):
    ready_node_ids: tuple[StrictStr, ...] = ()

    @field_validator("ready_node_ids", mode="before")
    @classmethod
    def freeze_ready_node_ids(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "ready node IDs must be a sequence")


class PlannerSessionProjection(ProjectionModel):
    state: StrictStr | None = None
    current_node_id: StrictStr | None = None
    carryover_record_id: StrictStr | None = None


class PlannerPatchDecisionValue(ProjectionModel):
    patch_id: StrictStr
    status: Literal["accepted", "rejected"]
    position: StrictInt
    proposed_by_node_id: StrictStr | None = None
    base_graph_position: StrictInt | None = None
    reason: StrictStr | None = None


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
    patch_decisions_by_id: FrozenMap[StrictStr, PlannerPatchDecisionValue] = Field(
        default_factory=FrozenMap
    )

    @field_validator("accepted_patch_ids_by_node", "no_successor_patch_ids_by_node", mode="before")
    @classmethod
    def freeze_patch_indexes(cls, value: object) -> object:
        return _freeze_sequence_map(value, "patch IDs must be sequences")


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

    @field_validator("scope", mode="before")
    @classmethod
    def freeze_scope(cls, value: object) -> FrozenJsonValue | None:
        if value is None:
            return None
        return _freeze_json_input(value)


class AuthorityDecisionValue(ProjectionModel):
    node_id: StrictStr
    decision: Literal["granted", "denied", "deferred"]
    task_region_id: StrictStr | None = None
    appeal_node_id: StrictStr | None = None
    decider: DecisionActorValue | StrictStr | None = None
    scope: FrozenJsonValue | None = None
    expires_at: StrictStr | None = None
    reason: StrictStr | None = None

    @field_validator("scope", mode="before")
    @classmethod
    def freeze_scope(cls, value: object) -> FrozenJsonValue | None:
        if value is None:
            return None
        return _freeze_json_input(value)


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

    @field_validator("decider", "scope", mode="before")
    @classmethod
    def freeze_open_json(cls, value: object) -> FrozenJsonValue | None:
        if value is None:
            return None
        return _freeze_json_input(value)


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
    cache_authority_hash: StrictStr | None = None

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
    payload_hash: StrictStr | None = None
    payload_size_bytes: StrictInt | None = None
    record_ids: tuple[StrictStr, ...] = ()

    @field_validator("payload", mode="before")
    @classmethod
    def freeze_callback_payload(cls, value: object) -> FrozenJsonValue | None:
        if value is None:
            return None
        return _freeze_json_input(value)

    @field_validator("record_ids", mode="before")
    @classmethod
    def freeze_callback_record_ids(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "callback record_ids must be a sequence")


class ExecutionAttemptValue(ProjectionModel):
    execution_id: StrictStr
    state: Literal[
        "baseline_captured", "submission_staged", "recovery_requested", "recovered", "finalized"
    ]
    node_id: StrictStr
    lease_id: StrictStr
    lease_generation: StrictInt
    lease_base_snapshot_id: StrictStr | None = None
    baseline_snapshot_id: StrictStr | None = None
    baseline_snapshot_ref: StrictStr | None = None
    baseline_commit_sha: StrictStr | None = None
    baseline_tree_sha: StrictStr | None = None
    baseline_boundary_hash: StrictStr | None = None
    baseline_entries: tuple[RunnerBoundaryEntry, ...] = ()
    cache_authority_hash: StrictStr | None = None
    # Kept only to replay pre-cache-authority durable histories. New attempts
    # store independently attributable typed root evidence per phase.
    cache_roots: tuple[RunnerCacheRoot | StrictStr, ...] = ()
    legacy_cache_root_paths: tuple[StrictStr, ...] = ()
    baseline_cache_roots: tuple[RunnerCacheRoot | StrictStr, ...] = ()
    baseline_cache_status_evidence: tuple[CacheStatusEvidence, ...] = ()
    idempotency_key: StrictStr | None = None
    # ``payload`` is legacy replay state only. New staged attempts retain the
    # content-addressed reference and resolve it at the runtime boundary.
    payload: FrozenJsonValue | None = None
    payload_ref: StoredArtifactRef | None = None
    payload_hash: StrictStr | None = None
    payload_size_bytes: StrictInt | None = None
    staged_snapshot_id: StrictStr | None = None
    staged_snapshot_ref: StrictStr | None = None
    staged_commit_sha: StrictStr | None = None
    staged_tree_sha: StrictStr | None = None
    staged_boundary_hash: StrictStr | None = None
    staged_boundary_entries: tuple[RunnerBoundaryEntry, ...] = ()
    staged_cache_roots: tuple[RunnerCacheRoot | StrictStr, ...] = ()
    staged_cache_status_evidence: tuple[CacheStatusEvidence, ...] = ()
    observed_graph_position: StrictInt | None = None
    callback_base_snapshot_id: StrictStr | None = None
    is_mutating: StrictBool | None = None
    complete_node: StrictBool | None = None
    new_state: StrictStr | None = None
    recovery_id: StrictStr | None = None
    recovery_reason: StrictStr | None = None
    recovery_max_attempts: StrictInt | None = None
    recovery_snapshot_id: StrictStr | None = None
    recovery_snapshot_ref: StrictStr | None = None
    recovery_commit_sha: StrictStr | None = None
    recovery_scope: Literal["selective", "full_baseline"] = "selective"
    recovery_paths: tuple[StrictStr, ...] = ()
    recovery_proof_hash: StrictStr | None = None
    restored_paths: tuple[StrictStr, ...] = ()
    removed_paths: tuple[StrictStr, ...] = ()
    final_snapshot_id: StrictStr | None = None
    final_snapshot_ref: StrictStr | None = None
    final_commit_sha: StrictStr | None = None
    final_tree_sha: StrictStr | None = None
    final_boundary_hash: StrictStr | None = None
    final_boundary_entries: tuple[RunnerBoundaryEntry, ...] = ()
    final_cache_roots: tuple[RunnerCacheRoot | StrictStr, ...] = ()
    final_cache_status_evidence: tuple[CacheStatusEvidence, ...] = ()
    recovery_observed_cache_roots: tuple[RunnerCacheRoot | StrictStr, ...] = ()
    recovery_authorized_cache_roots: tuple[RunnerCacheRoot, ...] = ()
    recovery_cache_status_evidence: tuple[CacheStatusEvidence, ...] = ()

    @field_validator(
        "baseline_entries",
        "staged_boundary_entries",
        "final_boundary_entries",
        "cache_roots",
        "legacy_cache_root_paths",
        "baseline_cache_roots",
        "baseline_cache_status_evidence",
        "staged_cache_roots",
        "staged_cache_status_evidence",
        "final_cache_roots",
        "final_cache_status_evidence",
        "recovery_observed_cache_roots",
        "recovery_authorized_cache_roots",
        "recovery_cache_status_evidence",
        "recovery_paths",
        "restored_paths",
        "removed_paths",
        mode="before",
    )
    @classmethod
    def freeze_attempt_sequences(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "execution attempt values must be sequences")

    @field_validator("payload", mode="before")
    @classmethod
    def freeze_attempt_payload(cls, value: object) -> FrozenJsonValue | None:
        return None if value is None else _freeze_json_input(value)


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
    snapshot_ref: StrictStr | None = None
    tree_sha: StrictStr | None = None
    commit_sha: StrictStr | None = None
    node_id: StrictStr | None = None
    lease_id: StrictStr | None = None
    lease_generation: StrictInt | None = None
    snapshot_role: Literal["baseline", "staged", "final", "recovery"] | None = None

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

    @field_validator("passed_candidate_ids", mode="before")
    @classmethod
    def freeze_passed_candidate_ids(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "passed candidate IDs must be a sequence")

    @field_validator("recovery_nodes_by_record_id", mode="before")
    @classmethod
    def freeze_recovery_nodes(cls, value: object) -> object:
        return _freeze_sequence_map(value, "recovery nodes must be sequences")


class GovernanceProjection(ProjectionModel):
    pending_appeals_by_node: FrozenMap[StrictStr, StrictBool] = Field(default_factory=FrozenMap)
    # Resolution-only replacement for the removed open-proposal payload cache.
    resolved_patch_ids: FrozenMap[StrictStr, StrictBool] = Field(default_factory=FrozenMap)
    node_gate_decisions: FrozenMap[StrictStr, StrictBool] = Field(default_factory=FrozenMap)
    configured_gates_by_task: FrozenMap[StrictStr, FrozenMap[StrictStr, StrictBool]] = Field(
        default_factory=FrozenMap
    )
    gate_decisions_by_task: FrozenMap[StrictStr, FrozenMap[StrictStr, StrictBool]] = Field(
        default_factory=FrozenMap
    )
    # Decisions have one canonical value keyed by durable record/event identity.
    # Node and appeal lookups are aliases to that identity, never duplicate
    # serialized decision payloads.
    approval_decisions_by_id: FrozenMap[StrictStr, ApprovalDecisionValue] = Field(
        default_factory=FrozenMap
    )
    approval_decision_id_by_node: FrozenMap[StrictStr, StrictStr] = Field(default_factory=FrozenMap)
    authority_decisions_by_id: FrozenMap[StrictStr, AuthorityDecisionValue] = Field(
        default_factory=FrozenMap
    )
    authority_decision_id_by_node: FrozenMap[StrictStr, StrictStr] = Field(
        default_factory=FrozenMap
    )
    oversight_decisions_by_id: FrozenMap[StrictStr, OversightDecisionValue] = Field(
        default_factory=FrozenMap
    )
    oversight_decision_id_by_node: FrozenMap[StrictStr, StrictStr] = Field(
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
    lease_ids_in_grant_order: tuple[StrictStr, ...] = ()
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
    attempts_by_execution_id: FrozenMap[StrictStr, ExecutionAttemptValue] = Field(
        default_factory=FrozenMap
    )

    @field_validator("lease_ids_in_grant_order", mode="before")
    @classmethod
    def freeze_lease_order(cls, value: object) -> tuple[object, ...]:
        return _freeze_sequence(value, "lease grant order must be a sequence")


class UsageProjection(ProjectionModel):
    tokens_by_node: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    tokens_by_node_kind: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    latency_ms_by_node_kind: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    execution_count_by_node_kind: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    action_count_by_node_kind: FrozenMap[StrictStr, StrictInt] = Field(default_factory=FrozenMap)
    recorded_keys: FrozenMap[StrictStr, StrictBool] = Field(default_factory=FrozenMap)


class GraphProjection(ProjectionModel):
    """The canonical immutable grouped graph projection."""

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
