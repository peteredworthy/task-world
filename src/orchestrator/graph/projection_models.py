"""Immutable destination models for the future graph-projection cutover.

This module is deliberately passive: production reducers do not construct these
models until the later cutover task.  Conversion copies transport records at the
boundary, preventing mutable event payloads from becoming projected state.
"""

from __future__ import annotations

from math import isfinite
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from orchestrator.graph.models import (
    AcceptedOutputRecordPayload,
    OUTPUT_RECORD_MODELS_BY_TYPE,
    OutputRecord,
)
from orchestrator.graph.projection_collections import FrozenJsonValue, FrozenMap, freeze_json


class ProjectionModel(BaseModel):
    """Strict, immutable base for every model reachable from the scaffold."""

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

    by_id: FrozenMap[StrictStr, "ProjectedRecord"] = Field(default_factory=FrozenMap)
    ids_by_node_port: FrozenMap[StrictStr, FrozenMap[StrictStr, tuple[StrictStr, ...]]] = Field(
        default_factory=FrozenMap
    )
    summaries_by_id: FrozenMap[StrictStr, GraphRecordSummaryProjection] = Field(
        default_factory=FrozenMap
    )

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

    @field_validator("payload", mode="before")
    @classmethod
    def freeze_callback_payload(cls, value: object) -> FrozenJsonValue | None:
        if value is None:
            return None
        return _freeze_json_input(value)


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


class ProjectedCandidateRecordValue(ProjectionModel):
    summary: StrictStr
    changed_paths: tuple[StrictStr, ...] = ()
    requirements_addressed: tuple[StrictStr, ...] = ()
    file_state_record_id: StrictStr | None = None
    file_state_record_ids: tuple[StrictStr, ...] = ()


class ProjectedRunContextValue(ProjectionModel):
    routine_id: StrictStr
    routine_name: StrictStr
    planner_generation_budget: StrictInt | None = None


class ProjectedRoutineSnapshotValue(ProjectionModel):
    routine_id: StrictStr
    name: StrictStr
    description: StrictStr | None = None
    content_hash: StrictStr
    source_path: StrictStr | None = None
    source_ref: StrictStr | None = None
    step_count: StrictInt = Field(ge=0)
    task_count: StrictInt = Field(ge=0)
    builder_agent: StrictStr | None = None
    verifier_agent: StrictStr | None = None
    dynamic_feature: FrozenMap[StrictStr, FrozenJsonValue] | None = None


class ProjectedArtifactReferenceValue(ProjectionModel):
    artifact_id: StrictStr
    artifact_type: StrictStr
    uri: StrictStr
    summary: StrictStr | None = None
    source_record_ids: tuple[StrictStr, ...] = ()
    required: StrictBool | None = None
    section: StrictStr | None = None
    max_tokens: StrictInt | None = None
    summarize: StrictBool | None = None
    summarize_model: StrictStr | None = None


class ProjectedStoredArtifactRef(ProjectionModel):
    artifact_id: StrictStr
    content_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: StrictInt = Field(ge=0)
    media_type: StrictStr
    encoding: StrictStr | None = None
    storage_uri: StrictStr = Field(pattern=r"^artifact://sha256/[0-9a-f]{64}$")

    @model_validator(mode="after")
    def storage_uri_matches_content_hash(self) -> "ProjectedStoredArtifactRef":
        if self.storage_uri.removeprefix("artifact://sha256/") != self.content_hash.removeprefix(
            "sha256:"
        ):
            raise ValueError("storage_uri digest must match content_hash digest")
        return self


class ProjectedGradeRow(ProjectionModel):
    requirement_id: StrictStr
    grade: StrictStr
    reason: StrictStr | None = None


class ProjectedVerificationReportValue(ProjectionModel):
    outcome: Literal["passed", "failed"]
    grades: tuple[ProjectedGradeRow, ...] = ()
    reason: StrictStr | None = None


class ProjectedCompletionDecisionValue(ProjectionModel):
    status: Literal["passed", "blocked"]
    blockers: tuple[FrozenMap[StrictStr, FrozenJsonValue], ...] = ()


class ProjectedJoinResultValue(ProjectionModel):
    status: Literal["ready", "blocked"]
    source_record_ids: tuple[StrictStr, ...] = ()
    missing_optional_inputs: tuple[StrictStr, ...] = ()


class ProjectedCheckResultRecordValue(ProjectionModel):
    status: Literal["passed", "failed", "timeout"]
    classification: Literal[
        "passed", "failed", "timeout", "environment_error", "tool_error", "tool_unavailable"
    ]
    command_id: StrictStr
    command_binding: FrozenJsonValue | None = None
    command_text: StrictStr
    command: FrozenMap[StrictStr, FrozenJsonValue]
    worktree_path: StrictStr
    source_worktree_path: StrictStr | None = None
    execution_worktree_path: StrictStr | None = None
    base_snapshot_id: StrictStr
    execution_snapshot_id: StrictStr | None = None
    execution_snapshot_ref: StrictStr | None = None
    execution_id: StrictStr
    exit_code: StrictInt | None = None
    duration_ms: StrictInt = Field(ge=0)
    stdout_tail: StrictStr
    stdout_ref: ProjectedStoredArtifactRef | None = None
    stderr_tail: StrictStr
    stderr_ref: ProjectedStoredArtifactRef | None = None
    stdout_truncated: StrictBool
    stderr_truncated: StrictBool
    timeout_seconds: StrictFloat = Field(gt=0)
    environment_policy: FrozenMap[StrictStr, FrozenJsonValue]
    source: StrictStr | None = None
    cited_record_id: StrictStr | None = None
    citation_mode: StrictStr | None = None
    reused_verification_record_id: StrictStr | None = None
    candidate_record_ids: tuple[StrictStr, ...] = ()
    file_state_record_ids: tuple[StrictStr, ...] = ()
    verification_report_record_ids: tuple[StrictStr, ...] = ()
    evaluated_record_ids: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def truncation_matches_artifact_references(self) -> "ProjectedCheckResultRecordValue":
        if self.stdout_truncated != (self.stdout_ref is not None):
            raise ValueError("stdout_truncated must match stdout_ref presence")
        if self.stderr_truncated != (self.stderr_ref is not None):
            raise ValueError("stderr_truncated must match stderr_ref presence")
        return self


class ProjectedGapClassificationValue(ProjectionModel):
    milestone_kind: StrictStr
    classification: Literal[
        "corrective_work_required", "no_gap", "human_decision_required", "graph_mutation_required"
    ]
    source: StrictStr
    task_region_id: StrictStr
    attempt_number: StrictInt = Field(ge=0)


class ProjectedDecisionActor(ProjectionModel):
    kind: StrictStr
    id: StrictStr | None = None


class ProjectedDecisionRecordValue(ProjectionModel):
    decision: Literal["approved", "rejected", "deferred"]
    decision_type: Literal["approval"]
    decider: ProjectedDecisionActor | StrictStr
    scope: FrozenMap[StrictStr, FrozenJsonValue] | None = None
    expires_at: StrictStr | None = None
    reason: StrictStr | None = None

    @model_validator(mode="after")
    def decider_is_nonempty(self) -> "ProjectedDecisionRecordValue":
        if isinstance(self.decider, str) and not self.decider:
            raise ValueError("decider must not be empty")
        return self


class ProjectedAuthorityDecisionRecordValue(ProjectionModel):
    decision: Literal["granted", "denied", "deferred"]
    decision_type: Literal["authority"]
    decider: ProjectedDecisionActor | StrictStr
    scope: FrozenMap[StrictStr, FrozenJsonValue] | None = None
    expires_at: StrictStr | None = None
    reason: StrictStr | None = None

    @model_validator(mode="after")
    def decider_is_nonempty(self) -> "ProjectedAuthorityDecisionRecordValue":
        if isinstance(self.decider, str) and not self.decider:
            raise ValueError("decider must not be empty")
        return self


class ProjectedAnalysisSummaryValue(ProjectionModel):
    summary: StrictStr
    source_record_ids: tuple[StrictStr, ...]
    lossy: StrictBool
    omitted_details: tuple[StrictStr, ...]


class ProjectedGraphPatchProposalValue(ProjectionModel):
    patch_id: StrictStr
    proposed_by_node_id: StrictStr
    base_graph_position: StrictInt = Field(ge=0)
    ops: tuple[FrozenMap[StrictStr, FrozenJsonValue], ...] = ()
    macro_invocations: tuple[FrozenMap[StrictStr, FrozenJsonValue], ...] = ()
    rationale: StrictStr | None = None
    rationale_record_id: StrictStr | None = None
    expected_downstream_effects: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def proposal_has_mutation_plan(self) -> "ProjectedGraphPatchProposalValue":
        if not self.ops and not self.macro_invocations:
            raise ValueError("graph patch proposal must include ops or macro_invocations")
        return self


class ProjectedRequirementRecordValue(ProjectionModel):
    id: StrictStr
    text: StrictStr
    desc: StrictStr | None = None
    priority: Literal["critical", "expected", "nice"] = "critical"
    acceptance_criteria: tuple[StrictStr, ...] = ()
    source: StrictStr | None = None
    version: StrictStr | None = None
    supersedes: StrictStr | None = None
    must: StrictBool = True


class ProjectedDecisionRequestRecordValue(DecisionRequestValue):
    pass


class ProjectedAuthorityRequestRecordValue(AuthorityRequestValue):
    pass


class ProjectedFailureRecordValue(ProjectionModel):
    failed_node_id: StrictStr
    phase: StrictStr
    error_class: StrictStr
    retryable: StrictBool
    lease_id: StrictStr | None = None
    lease_generation: StrictInt | None = None
    execution_id: StrictStr | None = None
    reason: StrictStr | None = None
    expires_at: StrictStr | None = None
    attempt_number: StrictInt | None = None
    max_attempts: StrictInt | None = None


class ProjectedRecoveryPlanValue(ProjectionModel):
    action: Literal["retry", "supersede", "cancel", "cleanup"]
    responsible_actor: StrictStr
    graph_changes: tuple[FrozenMap[StrictStr, FrozenJsonValue], ...]
    reason: StrictStr | None = None
    retry_after_seconds: StrictInt | None = None
    retry_not_before: StrictStr | None = None


class ProjectedGitRef(ProjectionModel):
    commit_sha: StrictStr | None = None
    tree_sha: StrictStr | None = None
    no_commit_reason: StrictStr | None = None
    ref: StrictStr | None = None
    diff_summary: FrozenMap[StrictStr, FrozenJsonValue] | None = None


class ProjectedExternalArtifactManifest(ProjectionModel):
    path: StrictStr
    hash: StrictStr
    origin: StrictStr
    retention: StrictStr


class ProjectedFileEntry(ProjectionModel):
    path: StrictStr
    source: StrictStr | None = None
    status: StrictStr | None = None
    classification: StrictStr | None = None
    policy: StrictStr | None = None
    matched_rule: StrictStr | None = None
    needs_gatekeeper: StrictBool | None = None
    rejected: StrictBool | None = None
    reason: StrictStr | None = None
    size_bytes: StrictInt | None = None
    entropy: StrictFloat | None = None
    gatekeeper_confidence: StrictFloat | None = None
    gatekeeper_rationale: StrictStr | None = None
    manifest: ProjectedExternalArtifactManifest | None = None


class ProjectedExternalFileEntry(ProjectedFileEntry):
    @model_validator(mode="after")
    def external_entry_requires_manifest(self) -> "ProjectedExternalFileEntry":
        if self.manifest is None:
            raise ValueError("external file entries require manifest")
        return self


ProjectedFanOutInputsValue: TypeAlias = FrozenMap[StrictStr, FrozenJsonValue]


class ProjectedRecordBase(ProjectionModel):
    """The immutable common record envelope; concrete records own their payload fields."""

    schema_version: StrictInt | None = None
    producer_port: StrictStr | None = None
    created_at: StrictStr | None = None
    graph_position: StrictInt | None = None
    run_id: StrictStr | None = None
    payload: FrozenMap[StrictStr, FrozenJsonValue] | None = None
    provenance: FrozenMap[StrictStr, FrozenJsonValue] | None = None

    @model_validator(mode="before")
    @classmethod
    def freeze_record_sequences(cls, value: object) -> object:
        """Make every declared tuple independent before strict nested validation."""

        def freeze_sequences(item: object) -> object:
            if isinstance(item, list):
                return tuple(freeze_sequences(child) for child in cast(list[object], item))
            if isinstance(item, dict):
                return {
                    key: freeze_sequences(child)
                    for key, child in cast(dict[object, object], item).items()
                }
            return item

        return freeze_sequences(value)

    @field_validator("payload", "provenance", mode="before")
    @classmethod
    def freeze_record_json(cls, value: object) -> FrozenMap[str, FrozenJsonValue] | None:
        if value is None:
            return None
        frozen = _freeze_json_input(value)
        if type(frozen) is not FrozenMap:
            raise ValueError("record envelope JSON must be an object")
        return cast(FrozenMap[str, FrozenJsonValue], frozen)

    @model_validator(mode="after")
    def record_envelope_is_consistent(self) -> "ProjectedRecordBase":
        if self.schema_version is not None and self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        port = getattr(self, "port", None)
        if self.producer_port is not None and self.producer_port != port:
            raise ValueError("producer_port must match port")
        return self


class ProjectedAnalysisSummaryRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["analysis_summary"]
    record_kind: Literal["output"]
    producer_node_id: StrictStr
    port: Literal["analysis_summary", "planning_summary", "region_summary"]
    schema_: Literal["AnalysisSummary", "RegionSummary"] = Field(alias="schema")
    value: ProjectedAnalysisSummaryValue

    @model_validator(mode="after")
    def port_schema_are_paired(self) -> "ProjectedAnalysisSummaryRecord":
        valid_pairs = {
            ("analysis_summary", "AnalysisSummary"),
            ("analysis_summary", "RegionSummary"),
            ("planning_summary", "AnalysisSummary"),
            ("planning_summary", "RegionSummary"),
            ("region_summary", "AnalysisSummary"),
            ("region_summary", "RegionSummary"),
        }
        if (self.port, self.schema_) not in valid_pairs:
            raise ValueError("analysis summary port and schema must be paired")
        return self


class ProjectedArtifactReferenceRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["artifact_reference"]
    record_kind: Literal["graph_record"]
    producer_node_id: StrictStr
    port: Literal["artifact_reference", "artifact"]
    schema_: Literal["ContextArtifact", "ArtifactReference"] = Field(alias="schema")
    value: ProjectedArtifactReferenceValue

    @model_validator(mode="after")
    def port_schema_are_paired(self) -> "ProjectedArtifactReferenceRecord":
        if (self.port, self.schema_) not in {
            ("artifact", "ContextArtifact"),
            ("artifact_reference", "ArtifactReference"),
        }:
            raise ValueError("artifact reference port and schema must be paired")
        return self


class ProjectedAuthorityDecisionRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["authority_decision"]
    record_kind: Literal["output"]
    producer_node_id: StrictStr
    port: Literal["authority_decision"]
    schema_: Literal["AuthorityDecision"] = Field(alias="schema")
    value: ProjectedAuthorityDecisionRecordValue


class ProjectedAuthorityRequestRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["authority_request_record"]
    record_kind: Literal["graph_record"]
    producer_node_id: StrictStr
    port: Literal["authority_request_record"]
    schema_: Literal["AuthorityRequest"] = Field(alias="schema")
    value: ProjectedAuthorityRequestRecordValue


class ProjectedCandidateRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["candidate"]
    record_kind: Literal["output"]
    producer_node_id: StrictStr
    port: Literal["candidate"]
    schema_: Literal["ImplementationCandidate"] = Field(alias="schema")
    candidate_id: StrictStr
    task_region_id: StrictStr | None = None
    attempt_number: StrictInt | None = Field(default=None, ge=0)
    value: ProjectedCandidateRecordValue
    file_state_record_id: StrictStr | None = None
    file_state_record_ids: tuple[StrictStr, ...] = ()
    supersedes_task_region_id: StrictStr | None = None
    supersedes_task_region_ids: tuple[StrictStr, ...] = ()


class ProjectedCheckResultRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["check_result"]
    record_kind: Literal["output"]
    producer_node_id: StrictStr
    port: Literal["check_result"]
    schema_: Literal["CheckResult"] = Field(alias="schema")
    candidate_id: StrictStr
    task_region_id: StrictStr
    attempt_number: StrictInt = Field(ge=0)
    value: ProjectedCheckResultRecordValue
    candidate_record_id: StrictStr | None = None
    candidate_record_ids: tuple[StrictStr, ...] = ()
    file_state_record_ids: tuple[StrictStr, ...] = ()
    verification_report_record_ids: tuple[StrictStr, ...] = ()
    evaluated_record_ids: tuple[StrictStr, ...] = ()


class ProjectedCompletionDecisionRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["completion_decision"]
    record_kind: Literal["output"]
    producer_node_id: StrictStr
    port: Literal["completion_decision"]
    schema_: Literal["CompletionDecision"] = Field(alias="schema")
    value: ProjectedCompletionDecisionValue


class ProjectedDecisionRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["decision_record"]
    record_kind: Literal["output"]
    producer_node_id: StrictStr
    port: Literal["decision_record"]
    schema_: Literal["DecisionRecord"] = Field(alias="schema")
    value: ProjectedDecisionRecordValue


class ProjectedDecisionRequestRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["decision_request"]
    record_kind: Literal["graph_record"]
    producer_node_id: StrictStr
    port: Literal["decision_request"]
    schema_: Literal["DecisionRequest"] = Field(alias="schema")
    value: ProjectedDecisionRequestRecordValue


class ProjectedFailureRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["failure_record"]
    record_kind: Literal["graph_record"]
    producer_node_id: StrictStr
    port: Literal["failure_record"]
    schema_: Literal["FailureRecord"] = Field(alias="schema")
    task_region_id: StrictStr | None = None
    value: ProjectedFailureRecordValue


class ProjectedFanOutInputsRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["fan_out_inputs"]
    record_kind: Literal["output"]
    producer_node_id: StrictStr
    port: StrictStr
    schema_: StrictStr = Field(alias="schema")
    value: FrozenMap[StrictStr, FrozenJsonValue]
    candidate_id: StrictStr | None = None
    task_region_id: StrictStr | None = None
    attempt_number: StrictInt | None = Field(default=None, ge=0)
    file_state_record_id: StrictStr | None = None
    file_state_record_ids: tuple[StrictStr, ...] = ()


class ProjectedFileStateRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["file_state"]
    record_kind: Literal["file_state"] = "file_state"
    producer_node_id: StrictStr | None = None
    snapshot_id: StrictStr | None = None
    base_snapshot_id: StrictStr | None = None
    port: Literal["file_state", "accepted_file_state"] = "file_state"
    schema_: Literal["FileStateRecord"] = Field(default="FileStateRecord", alias="schema")
    git: ProjectedGitRef | None = None
    tracked: tuple[ProjectedFileEntry, ...] = ()
    untracked: tuple[ProjectedFileEntry, ...] = ()
    ignored: tuple[ProjectedFileEntry, ...] = ()
    external: tuple[ProjectedExternalFileEntry, ...] = ()
    classifications: tuple[ProjectedFileEntry, ...] = ()
    residue: tuple[ProjectedFileEntry, ...] = ()
    rejected_paths: tuple[ProjectedFileEntry, ...] = ()
    verdict: Literal["captured", "rejected"] = "captured"
    patch_bundle_id: StrictStr | None = None
    tree_snapshot_id: StrictStr | None = None
    position: StrictInt | None = None
    task_region_id: StrictStr | None = None
    candidate_id: StrictStr | None = None
    compromised: StrictBool | None = None
    superseded_pending: StrictBool | None = None
    supersedes_record_id: StrictStr | None = None
    superseded_by_record_id: StrictStr | None = None
    cleanup_id: StrictStr | None = None
    cleanup_excluded_paths: tuple[StrictStr, ...] = ()
    cleanup_reason: StrictStr | None = None
    cleanup_applied_event_id: StrictStr | None = None
    compromised_snapshot_deleted: StrictBool | None = None
    compromised_paths: tuple[StrictStr, ...] | None = None
    acceptance_identity: StrictStr | None = None


class ProjectedGapClassificationRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["classified_gap", "gap_classification", "gap_plan"]
    record_kind: Literal["output"]
    producer_node_id: StrictStr
    port: Literal["classified_gap", "gap_classification", "gap_plan"]
    schema_: Literal["GapClassification"] = Field(alias="schema")
    value: ProjectedGapClassificationValue

    @model_validator(mode="after")
    def gap_port_matches_record_type(self) -> "ProjectedGapClassificationRecord":
        if self.record_type != self.port and not (
            self.record_type == "classified_gap" and self.port == "gap_classification"
        ):
            raise ValueError("record_type must match port")
        return self


class ProjectedGraphPatchProposalRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["graph_patch_proposal"]
    record_kind: Literal["output"]
    producer_node_id: StrictStr
    port: Literal["graph_patch_proposal", "graph_patch"]
    schema_: Literal["GraphPatch"] = Field(alias="schema")
    value: ProjectedGraphPatchProposalValue


class ProjectedJoinResultRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["join_result"]
    record_kind: Literal["output"]
    producer_node_id: StrictStr
    port: Literal["join_result"]
    schema_: Literal["JoinResult"] = Field(alias="schema")
    value: ProjectedJoinResultValue


class ProjectedRecoveryPlanRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["recovery_plan"]
    record_kind: Literal["output"]
    producer_node_id: StrictStr
    port: Literal["recovery_plan"]
    schema_: Literal["RecoveryPlan"] = Field(alias="schema")
    value: ProjectedRecoveryPlanValue


class ProjectedRequirementRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["requirement_record"]
    record_kind: Literal["graph_record"]
    producer_node_id: StrictStr
    port: Literal["requirement"]
    schema_: Literal["RequirementRecord"] = Field(alias="schema")
    value: ProjectedRequirementRecordValue


class ProjectedRoutineSnapshotRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["routine_snapshot"]
    record_kind: Literal["graph_record"]
    producer_node_id: StrictStr
    port: Literal["routine_snapshot", "snapshot"]
    schema_: Literal["RoutineSnapshot"] = Field(alias="schema")
    value: ProjectedRoutineSnapshotValue


class ProjectedRunContextRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["run_context"]
    record_kind: Literal["graph_record"]
    producer_node_id: StrictStr
    port: Literal["run_context"]
    schema_: Literal["RunContext"] = Field(alias="schema")
    value: ProjectedRunContextValue


class ProjectedVerificationReportRecord(ProjectedRecordBase):
    record_id: StrictStr
    record_type: Literal["verification_report"]
    record_kind: Literal["verification"]
    producer_node_id: StrictStr
    port: Literal["verification_report"] = "verification_report"
    schema_: Literal["VerificationReport"] = Field(default="VerificationReport", alias="schema")
    candidate_id: StrictStr
    task_region_id: StrictStr | None = None
    outcome: Literal["passed", "failed"]
    value: ProjectedVerificationReportValue
    evidence: FrozenJsonValue | None = None
    candidate_record_id: StrictStr | None = None
    candidate_record_ids: tuple[StrictStr, ...] = ()
    file_state_record_ids: tuple[StrictStr, ...] = ()
    evaluated_record_ids: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def outcome_matches_value(self) -> "ProjectedVerificationReportRecord":
        if self.value.outcome != self.outcome:
            raise ValueError("outcome must match value.outcome")
        return self


ProjectedRecord: TypeAlias = Annotated[
    ProjectedAnalysisSummaryRecord
    | ProjectedArtifactReferenceRecord
    | ProjectedAuthorityDecisionRecord
    | ProjectedAuthorityRequestRecord
    | ProjectedCandidateRecord
    | ProjectedCheckResultRecord
    | ProjectedCompletionDecisionRecord
    | ProjectedDecisionRecord
    | ProjectedDecisionRequestRecord
    | ProjectedFailureRecord
    | ProjectedFanOutInputsRecord
    | ProjectedFileStateRecord
    | ProjectedGapClassificationRecord
    | ProjectedGraphPatchProposalRecord
    | ProjectedJoinResultRecord
    | ProjectedRecoveryPlanRecord
    | ProjectedRequirementRecord
    | ProjectedRoutineSnapshotRecord
    | ProjectedRunContextRecord
    | ProjectedVerificationReportRecord,
    Field(discriminator="record_type"),
]

# This deliberately finite list is the relation-audit contract.  Keep it in
# lockstep with the public discriminated union above; codec visitors and tests
# use it to make a newly-added record impossible to silently skip.
PROJECTED_RECORD_TYPES = (
    ProjectedAnalysisSummaryRecord,
    ProjectedArtifactReferenceRecord,
    ProjectedAuthorityDecisionRecord,
    ProjectedAuthorityRequestRecord,
    ProjectedCandidateRecord,
    ProjectedCheckResultRecord,
    ProjectedCompletionDecisionRecord,
    ProjectedDecisionRecord,
    ProjectedDecisionRequestRecord,
    ProjectedFailureRecord,
    ProjectedFanOutInputsRecord,
    ProjectedFileStateRecord,
    ProjectedGapClassificationRecord,
    ProjectedGraphPatchProposalRecord,
    ProjectedJoinResultRecord,
    ProjectedRecoveryPlanRecord,
    ProjectedRequirementRecord,
    ProjectedRoutineSnapshotRecord,
    ProjectedRunContextRecord,
    ProjectedVerificationReportRecord,
)

_PROJECTED_RECORD_MODELS: FrozenMap[str, type[ProjectedRecordBase]] = FrozenMap(
    {
        "analysis_summary": ProjectedAnalysisSummaryRecord,
        "artifact_reference": ProjectedArtifactReferenceRecord,
        "authority_decision": ProjectedAuthorityDecisionRecord,
        "authority_request_record": ProjectedAuthorityRequestRecord,
        "candidate": ProjectedCandidateRecord,
        "check_result": ProjectedCheckResultRecord,
        "classified_gap": ProjectedGapClassificationRecord,
        "completion_decision": ProjectedCompletionDecisionRecord,
        "decision_record": ProjectedDecisionRecord,
        "decision_request": ProjectedDecisionRequestRecord,
        "failure_record": ProjectedFailureRecord,
        "fan_out_inputs": ProjectedFanOutInputsRecord,
        "file_state": ProjectedFileStateRecord,
        "gap_classification": ProjectedGapClassificationRecord,
        "gap_plan": ProjectedGapClassificationRecord,
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
    payload = record.model_dump(
        mode="json",
        by_alias=True,
        exclude_unset=True,
        exclude_none=True,
    )
    record_type = payload.get("record_type")
    if not isinstance(record_type, str) or record_type not in _PROJECTED_RECORD_MODELS:
        raise ValueError("unknown projected record discriminator")
    return cast(ProjectedRecord, _PROJECTED_RECORD_MODELS[record_type].model_validate(payload))


def _is_native_json(value: object, *, active_ids: set[int] | None = None, depth: int = 0) -> bool:
    if depth > 100:
        return False
    value_type = type(value)
    if value is None or value_type is bool or value_type is int or value_type is str:
        return True
    if value_type is float:
        return isfinite(cast(float, value))
    if value_type is list or value_type is tuple:
        sequence = cast(list[object] | tuple[object, ...], value)
        current_active_ids = active_ids if active_ids is not None else set[int]()
        if id(sequence) in current_active_ids:
            return False
        current_active_ids.add(id(sequence))
        try:
            return all(
                _is_native_json(item, active_ids=current_active_ids, depth=depth + 1)
                for item in sequence
            )
        finally:
            current_active_ids.remove(id(sequence))
    if value_type is dict:
        dictionary = cast(dict[object, object], value)
        current_active_ids = active_ids if active_ids is not None else set[int]()
        if id(dictionary) in current_active_ids:
            return False
        current_active_ids.add(id(dictionary))
        try:
            return all(
                type(key) is str
                and _is_native_json(item, active_ids=current_active_ids, depth=depth + 1)
                for key, item in dictionary.items()
            )
        finally:
            current_active_ids.remove(id(dictionary))
    return False


def _can_construct_validated_fan_out_record(record: AcceptedOutputRecordPayload) -> bool:
    if type(record) is not OutputRecord:
        return False
    if any(field_name not in record.__dict__ for field_name in OutputRecord.model_fields):
        return False
    if (
        record.record_type != "fan_out_inputs"
        or record.record_kind != "output"
        or type(record.record_id) is not str
        or type(record.producer_node_id) is not str
        or type(record.port) is not str
        or type(record.schema_) is not str
        or (
            record.schema_version is not None
            and (type(record.schema_version) is not int or record.schema_version <= 0)
        )
        or (
            record.producer_port is not None
            and (type(record.producer_port) is not str or record.producer_port != record.port)
        )
        or (record.created_at is not None and type(record.created_at) is not str)
        or (record.graph_position is not None and type(record.graph_position) is not int)
        or (record.run_id is not None and type(record.run_id) is not str)
        or (record.candidate_id is not None and type(record.candidate_id) is not str)
        or (record.task_region_id is not None and type(record.task_region_id) is not str)
        or (
            record.attempt_number is not None
            and (type(record.attempt_number) is not int or record.attempt_number < 0)
        )
        or (
            record.file_state_record_id is not None and type(record.file_state_record_id) is not str
        )
        or type(record.file_state_record_ids) is not list
        or any(type(record_id) is not str for record_id in record.file_state_record_ids)
    ):
        return False
    return (
        type(record.value) is dict
        and _is_native_json(record.value)
        and all(
            value is None or (type(value) is dict and _is_native_json(value))
            for value in (record.payload, record.provenance)
        )
    )


def project_validated_record_for_reducer(record: AcceptedOutputRecordPayload) -> ProjectedRecord:
    """Construct an exact, already-validated reducer record or retain public validation."""
    if not _can_construct_validated_fan_out_record(record):
        return project_record(record)
    fan_out = cast(OutputRecord, record)
    payload = None if fan_out.payload is None else _freeze_json_input(fan_out.payload)
    provenance = None if fan_out.provenance is None else _freeze_json_input(fan_out.provenance)
    fields_set = {
        field_name
        for field_name in fan_out.model_fields_set
        if field_name in ProjectedFanOutInputsRecord.model_fields
        and getattr(fan_out, field_name) is not None
    }
    return ProjectedFanOutInputsRecord.model_construct(
        _fields_set=fields_set,
        record_id=fan_out.record_id,
        record_type="fan_out_inputs",
        record_kind="output",
        producer_node_id=fan_out.producer_node_id,
        port=fan_out.port,
        schema_=fan_out.schema_,
        value=cast(FrozenMap[str, FrozenJsonValue], _freeze_json_input(fan_out.value)),
        schema_version=fan_out.schema_version,
        producer_port=fan_out.producer_port,
        created_at=fan_out.created_at,
        graph_position=fan_out.graph_position,
        run_id=fan_out.run_id,
        payload=payload,
        provenance=provenance,
        candidate_id=fan_out.candidate_id,
        task_region_id=fan_out.task_region_id,
        attempt_number=fan_out.attempt_number,
        file_state_record_id=fan_out.file_state_record_id,
        file_state_record_ids=tuple(fan_out.file_state_record_ids),
    )
