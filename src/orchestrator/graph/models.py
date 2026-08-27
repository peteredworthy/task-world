"""Pydantic models for the execution graph PRD data contracts."""

from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
    field_validator,
)
from orchestrator.graph.boundary_types import (
    BoundaryValidationError,
    boundary_manifest_hash,
    validate_cache_roots,
    validate_git_oid,
    validate_repo_relative_path,
    validate_snapshot_ref,
    validate_sha256,
)
from orchestrator.graph.cache_authority import (
    CacheStatusEvidence,
    RunnerCacheRoot,
    canonicalize_cache_roots,
)
from orchestrator.graph.projection_collections import FrozenMap


def _freeze_canonical_record_value(value: object) -> object:
    """Freeze a validated record without introducing a projection schema."""
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            if hasattr(value, field_name):
                object.__setattr__(
                    value,
                    field_name,
                    _freeze_canonical_record_value(getattr(value, field_name)),
                )
        if isinstance(value, StrictNestedModel):
            object.__setattr__(value, "__canonical_record_frozen__", True)
        return value
    if type(value) is FrozenMap:
        return FrozenMap(
            {key: _freeze_canonical_record_value(item) for key, item in value.object_items()}
        )
    if type(value) is dict:
        return FrozenMap(
            {
                key: _freeze_canonical_record_value(item)
                for key, item in cast(dict[object, object], value).items()
            }
        )
    if type(value) in {list, tuple}:
        return tuple(_freeze_canonical_record_value(item) for item in cast(list[object], value))
    return value


def _thaw_canonical_model(
    model: BaseModel,
) -> tuple[list[tuple[BaseModel, str, object]], object]:
    changes: list[tuple[BaseModel, str, object]] = []

    def thaw(value: object) -> object:
        if isinstance(value, BaseModel):
            for field_name in type(value).model_fields:
                if hasattr(value, field_name):
                    current = getattr(value, field_name)
                    changes.append((value, field_name, current))
                    object.__setattr__(value, field_name, thaw(current))
            return value
        if isinstance(value, FrozenMap):
            return {key: thaw(item) for key, item in value.object_items()}
        if isinstance(value, dict):
            return {key: thaw(item) for key, item in cast(dict[object, object], value).items()}
        if isinstance(value, tuple):
            return [thaw(item) for item in cast(tuple[object, ...], value)]
        return value

    return changes, thaw(model)


def _restore_canonical_model(changes: list[tuple[BaseModel, str, object]]) -> None:
    for model, field_name, value in reversed(changes):
        object.__setattr__(model, field_name, value)


class GraphBaseModel(BaseModel):
    """Base model that preserves forward-compatible PRD fields."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Dump the supplied PRD shape unless callers choose a different policy."""
        kwargs.setdefault("by_alias", True)
        kwargs.setdefault("exclude_unset", True)
        return super().model_dump(*args, **kwargs)


class StrictNestedModel(GraphBaseModel):
    """Nested W5 values reject unknown fields without global graph strictness."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def __setattr__(self, name: str, value: object) -> None:
        if self.__dict__.get("__canonical_record_frozen__", False):
            raise TypeError("canonical record values are immutable")
        super().__setattr__(name, value)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if not self.__dict__.get("__canonical_record_frozen__", False):
            return super().model_dump(*args, **kwargs)
        changes, _ = _thaw_canonical_model(self)
        try:
            return super().model_dump(*args, **kwargs)
        finally:
            _restore_canonical_model(changes)


CommandDefinitionProjection: TypeAlias = dict[str, Any]


class TypedRecordBase(GraphBaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    record_type: str | None = None
    schema_version: int | None = None
    producer_port: str | None = None
    created_at: str | None = None
    graph_position: int | None = None
    run_id: str | None = None
    payload: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None

    @model_validator(mode="after")
    def base_fields_are_consistent(self) -> "TypedRecordBase":
        port = getattr(self, "port", None)
        if self.producer_port is not None and port is not None and self.producer_port != port:
            msg = "producer_port must match port"
            raise ValueError(msg)
        if self.schema_version is not None and self.schema_version <= 0:
            msg = "schema_version must be positive"
            raise ValueError(msg)
        return self

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Serialize owned immutable values through the canonical JSON shape."""
        changes, _ = _thaw_canonical_model(self)
        try:
            return super().model_dump(*args, **kwargs)
        finally:
            _restore_canonical_model(changes)


def freeze_canonical_record(record: TypedRecordBase) -> TypedRecordBase:
    """Freeze one accepted record when it enters projection-owned storage."""
    for field_name in type(record).model_fields:
        if hasattr(record, field_name):
            object.__setattr__(
                record,
                field_name,
                _freeze_canonical_record_value(getattr(record, field_name)),
            )
    return record


class RunLifecycleState(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    ACTIVE = "active"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class RunModel(GraphBaseModel):
    run_id: str
    routine_snapshot_id: str
    repo_id: str
    worktree_path: str
    run_branch: str
    lifecycle_state: RunLifecycleState
    root_snapshot_id: str
    event_position: int


class NodeKind(str, Enum):
    ROOT = "root"
    RUN_ROOT = "run_root"
    ROUTINE_SNAPSHOT = "routine_snapshot"
    TASK_PROJECTION = "task_projection"
    WORKER = "worker"
    VERIFIER = "verifier"
    CHECK = "check"
    PLANNER = "planner"
    GAP_PLANNER = "gap_planner"
    SUMMARIZER = "summarizer"
    JOIN = "join"
    FINAL_GATE = "final_gate"
    HUMAN_GATE = "human_gate"
    AUTHORITY_REQUEST = "authority_request"
    OVERSIGHT = "oversight"
    APPEAL = "appeal"
    GATE = "gate"
    RECOVERY = "recovery"
    REVIEW = "review"
    ARTIFACT = "artifact"
    ARTIFACT_INDEX = "artifact_index"
    REQUIREMENT = "requirement"
    FILE_STATE = "file_state"
    SESSION = "session"


class NodeState(str, Enum):
    PLANNED = "planned"
    BLOCKED = "blocked"
    READY = "ready"
    LEASED = "leased"
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    RETIRED = "retired"
    CANCELLED = "cancelled"


class ResourceClaimProjection(StrictNestedModel):
    model_config = ConfigDict(frozen=True)
    mode: str
    scope: str
    paths: list[str] | None = None
    external_resource_key: str | None = None


class AgentDispatchResourceClaim(StrictNestedModel):
    mode: StrictStr
    scope: StrictStr
    paths: Annotated[list[StrictStr], Field(strict=True)] | None = None
    external_resource_key: StrictStr | None = None


class ResourceClaim(ResourceClaimProjection):
    @model_validator(mode="after")
    def external_claims_require_keys(self) -> "ResourceClaim":
        if self.mode == "external" and self.external_resource_key is None:
            msg = "external claims require external_resource_key"
            raise ValueError(msg)
        return self


def _empty_resource_claims() -> list[ResourceClaim]:
    return []


class Authority(StrictNestedModel):
    allowed_actions: list[str] = Field(default_factory=list)
    resource_claims: list[ResourceClaim] = Field(default_factory=_empty_resource_claims)
    preconditions: list[str] = Field(default_factory=list)


class PortModel(StrictNestedModel):
    node_id: str | None = None
    port: str
    direction: Literal["input", "output"] | None = None
    schema_: str | None = Field(default=None, alias="schema")
    record_layers: list[str] | None = None
    required: StrictBool | None = None


def _empty_ports() -> list[PortModel]:
    return []


class NodeMembership(StrictNestedModel):
    task_region_id: str
    attempt_number: StrictInt
    candidate_id: str
    execution_id: str


class NodeModel(GraphBaseModel):
    node_id: str
    run_id: str | None = None
    kind: NodeKind
    role: str | None = None
    state: NodeState | None = None
    created_by_event: str | None = None
    authority: Authority | None = None
    inputs: list[PortModel] = Field(default_factory=_empty_ports)
    outputs: list[PortModel] = Field(default_factory=_empty_ports)
    membership: NodeMembership | None = None


class SelectorBaseModel(BaseModel):
    """Strict base for schema-aware edge selectors."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        kwargs.setdefault("exclude_none", True)
        return super().model_dump(*args, **kwargs)


class CandidateRecordSelector(SelectorBaseModel):
    record_type: Literal["candidate"]
    schema_: Literal["ImplementationCandidate"] = Field(
        default="ImplementationCandidate",
        alias="schema",
    )


class CheckResultSelector(SelectorBaseModel):
    record_type: Literal["check_result"]
    schema_: Literal["CheckResult"] = Field(default="CheckResult", alias="schema")
    status: Literal["passed", "failed", "timeout"] | None = None


class VerificationReportSelector(SelectorBaseModel):
    record_type: Literal["verification_report"]
    schema_: Literal["VerificationReport"] = Field(default="VerificationReport", alias="schema")
    outcome: Literal["passed", "failed"] | None = None


class GapClassificationSelector(SelectorBaseModel):
    record_type: Literal["gap_classification"]
    schema_: Literal["GapClassification"] = Field(default="GapClassification", alias="schema")
    classification: (
        Literal[
            "corrective_work_required",
            "no_gap",
            "human_decision_required",
            "graph_mutation_required",
        ]
        | None
    ) = None


class SimpleRecordSelector(SelectorBaseModel):
    record_type: Literal[
        "analysis_summary",
        "artifact_reference",
        "authority_decision",
        "authority_request_record",
        "completion_decision",
        "decision_record",
        "decision_request",
        "failure_record",
        "file_state",
        "graph_patch_proposal",
        "requirement_record",
        "routine_snapshot",
        "run_context",
    ]
    schema_: str | None = Field(default=None, alias="schema")


class AnyOfRecordSelector(SelectorBaseModel):
    record_type: Literal["any_of"]
    selectors: list[
        Annotated[
            CandidateRecordSelector
            | CheckResultSelector
            | VerificationReportSelector
            | GapClassificationSelector
            | SimpleRecordSelector,
            Field(discriminator="record_type"),
        ]
    ] = Field(min_length=1)


AcceptedRecordSelector = Annotated[
    CandidateRecordSelector
    | CheckResultSelector
    | VerificationReportSelector
    | GapClassificationSelector
    | SimpleRecordSelector
    | AnyOfRecordSelector,
    Field(discriminator="record_type"),
]


class RecordSelector(RootModel[AcceptedRecordSelector]):
    """Schema-aware selector wrapper for accepted graph edge records."""

    def model_dump(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("by_alias", True)
        kwargs.setdefault("exclude_none", True)
        return self.root.model_dump(*args, **kwargs)

    @property
    def record_type(self) -> str:
        return self.root.record_type

    def matches(self, record_payload: dict[str, Any], aliases: set[str] | None = None) -> bool:
        return _selector_matches_payload(self.root, record_payload, aliases or set())


def normalize_record_selector(value: Any) -> dict[str, Any]:
    """Normalize persisted or incoming selector shapes to the typed JSON form."""
    selector = RecordSelector.model_validate(value)
    return cast(dict[str, Any], selector.model_dump(mode="json"))


def record_selector_matches(
    selector: Any,
    record_payload: dict[str, Any],
    aliases: set[str] | None = None,
) -> bool:
    if selector is None:
        return True
    return RecordSelector.model_validate(selector).matches(record_payload, aliases)


def _selector_matches_payload(
    selector: AcceptedRecordSelector,
    record_payload: dict[str, Any],
    aliases: set[str],
) -> bool:
    if isinstance(selector, AnyOfRecordSelector):
        return any(
            _selector_matches_payload(part, record_payload, aliases) for part in selector.selectors
        )

    record_types = _payload_record_types(record_payload, aliases)
    if selector.record_type not in record_types:
        return False
    schema = getattr(selector, "schema_", None)
    payload_schema = record_payload.get("schema")
    if isinstance(schema, str) and isinstance(payload_schema, str) and schema != payload_schema:
        return False
    if isinstance(selector, VerificationReportSelector):
        return (
            selector.outcome is None
            or _verification_payload_outcome(record_payload) == selector.outcome
        )
    if isinstance(selector, CheckResultSelector):
        return (
            selector.status is None
            or _check_result_payload_status(record_payload) == selector.status
        )
    if isinstance(selector, GapClassificationSelector):
        return (
            selector.classification is None
            or _gap_classification_payload_classification(record_payload) == selector.classification
        )
    return True


def _payload_record_types(record_payload: dict[str, Any], aliases: set[str]) -> set[str]:
    candidates = {
        value
        for value in (
            record_payload.get("record_type"),
            record_payload.get("port"),
            record_payload.get("schema"),
            record_payload.get("record_kind"),
        )
        if isinstance(value, str)
    }
    candidates.update(aliases)
    value = record_payload.get("value")
    if isinstance(value, dict):
        milestone_kind = cast(dict[str, Any], value).get("milestone_kind")
        if isinstance(milestone_kind, str):
            candidates.add(milestone_kind)
    if record_payload.get("schema") == "GapClassification":
        candidates.add("gap_classification")
    return candidates


def _verification_payload_outcome(record_payload: dict[str, Any]) -> str | None:
    outcome = record_payload.get("outcome")
    if isinstance(outcome, str):
        if outcome in {"passed", "failed"}:
            return outcome
    value = record_payload.get("value")
    if isinstance(value, dict):
        value_outcome = cast(dict[str, Any], value).get("outcome")
        if value_outcome in {"passed", "failed"}:
            return cast(str, value_outcome)
    return None


def _check_result_payload_status(record_payload: dict[str, Any]) -> str | None:
    status = record_payload.get("status")
    if isinstance(status, str):
        return status
    value = record_payload.get("value")
    if isinstance(value, dict):
        value_status = cast(dict[str, Any], value).get("status")
        if isinstance(value_status, str):
            return value_status
    return None


def _gap_classification_payload_classification(record_payload: dict[str, Any]) -> str | None:
    classification = record_payload.get("classification")
    if isinstance(classification, str):
        return classification
    value = record_payload.get("value")
    if isinstance(value, dict):
        value_classification = cast(dict[str, Any], value).get("classification")
        if isinstance(value_classification, str):
            return value_classification
    return None


class EdgeModel(GraphBaseModel):
    edge_id: str
    from_node_id: str
    from_port: str
    to_node_id: str
    to_port: str
    required: bool = True
    dependency_type: Literal["input_binding", "state_dependency"] = "input_binding"
    accepted_record_selector: RecordSelector | None = None


class InputBinding(GraphBaseModel):
    edge_id: str
    to_node_id: str
    to_port: str
    record_ids: list[str]
    bound_at_position: int


class _AttributeProjection(GraphBaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EdgeProjection(_AttributeProjection):
    model_config = ConfigDict(frozen=True)
    edge_id: str
    from_node_id: str
    from_port: str
    to_node_id: str
    to_port: str
    required: StrictBool = True
    dependency_type: Literal["input_binding", "state_dependency"] = "input_binding"
    from_node_kind: str | None = None
    from_node_role: str | None = None
    accepted_record_selector: dict[str, Any] | None = None
    purpose: Any | None = None
    description: Any | None = None
    selection: Any | None = None
    binding_policy: Any | None = None
    freshness_policy: Any | None = None
    prompt_hydration_policy: Any | None = None
    metadata: Any | None = None
    patch_id: str | None = None


class InputBindingProjection(_AttributeProjection):
    model_config = ConfigDict(frozen=True)
    edge_id: str | None = None
    to_node_id: str
    to_port: str
    record_ids: list[str]
    bound_at_position: int
    record_bound_positions: dict[str, int] | None = None
    binding_policy: str | None = None
    trigger: str | None = None
    supersedes_record_id: str | None = None


class OutputRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: str
    schema_: str = Field(alias="schema")
    value: dict[str, Any]
    candidate_id: str | None = None
    task_region_id: str | None = None
    attempt_number: int | None = Field(default=None, ge=0)
    file_state_record_id: str | None = None
    file_state_record_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def generic_output_record_type_is_explicit(self) -> "OutputRecord":
        if self.record_type != "fan_out_inputs":
            msg = "record_type must be fan_out_inputs"
            raise ValueError(msg)
        return self


class RunContextValue(StrictNestedModel):
    routine_id: str
    routine_name: str
    planner_generation_budget: StrictInt | None = None


class RunContextRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["graph_record"]
    producer_node_id: str
    port: Literal["run_context"]
    schema_: Literal["RunContext"] = Field(alias="schema")
    value: RunContextValue

    @model_validator(mode="after")
    def run_context_fields_are_consistent(self) -> "RunContextRecord":
        if self.record_type != "run_context":
            msg = "record_type must be run_context"
            raise ValueError(msg)
        return self


class RoutineSnapshotValue(StrictNestedModel):
    routine_id: str
    name: str
    description: str | None = None
    content_hash: str
    source_path: str | None = None
    source_ref: str | None = None
    step_count: StrictInt = Field(ge=0)
    task_count: StrictInt = Field(ge=0)
    builder_agent: str | None = None
    verifier_agent: str | None = None
    dynamic_feature: dict[str, Any] | None = None
    cache_authority_preimage: str | None = None
    cache_authority_hash: str | None = None
    cache_authority_version: str | None = None


class RoutineSnapshotRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["graph_record"]
    producer_node_id: str
    port: Literal["routine_snapshot", "snapshot"]
    schema_: Literal["RoutineSnapshot"] = Field(alias="schema")
    value: RoutineSnapshotValue

    @model_validator(mode="after")
    def routine_snapshot_fields_are_consistent(self) -> "RoutineSnapshotRecord":
        if self.record_type != "routine_snapshot":
            msg = "record_type must be routine_snapshot"
            raise ValueError(msg)
        return self


class ArtifactReferenceValue(StrictNestedModel):
    artifact_id: str
    artifact_type: str
    uri: str
    summary: str | None = None
    source_record_ids: list[str] = Field(default_factory=list)
    required: StrictBool | None = None
    section: str | None = None
    max_tokens: StrictInt | None = None
    summarize: StrictBool | None = None
    summarize_model: str | None = None


class StoredArtifactRef(StrictNestedModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    artifact_id: str
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: StrictInt = Field(ge=0)
    media_type: str
    encoding: str | None = None
    storage_uri: str = Field(pattern=r"^artifact://sha256/[0-9a-f]{64}$")

    @model_validator(mode="after")
    def storage_uri_matches_content_hash(self) -> "StoredArtifactRef":
        if self.storage_uri.removeprefix("artifact://sha256/") != self.content_hash.removeprefix(
            "sha256:"
        ):
            raise ValueError("storage_uri digest must match content_hash digest")
        return self


class ArtifactReferenceRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["graph_record"]
    producer_node_id: str
    port: Literal["artifact_reference", "artifact"]
    schema_: Literal["ContextArtifact", "ArtifactReference"] = Field(alias="schema")
    value: ArtifactReferenceValue

    @model_validator(mode="after")
    def artifact_reference_fields_are_consistent(self) -> "ArtifactReferenceRecord":
        if self.record_type != "artifact_reference":
            msg = "record_type must be artifact_reference"
            raise ValueError(msg)
        return self


class GradeRow(StrictNestedModel):
    requirement_id: str
    grade: str
    reason: str | None = None


def _empty_verification_grades() -> list[GradeRow]:
    return []


def _empty_verification_record_ids() -> list[str]:
    return []


class VerificationReportValue(StrictNestedModel):
    outcome: Literal["passed", "failed"]
    grades: list[GradeRow] = Field(default_factory=_empty_verification_grades)
    reason: str | None = None


class VerificationReportRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["verification"]
    producer_node_id: str
    port: Literal["verification_report"] = "verification_report"
    schema_: Literal["VerificationReport"] = Field(default="VerificationReport", alias="schema")
    candidate_id: str
    task_region_id: str | None = None
    outcome: Literal["passed", "failed"]
    value: VerificationReportValue
    evidence: Any | None = None
    candidate_record_id: str | None = None
    candidate_record_ids: list[str] = Field(default_factory=_empty_verification_record_ids)
    file_state_record_ids: list[str] = Field(default_factory=_empty_verification_record_ids)
    evaluated_record_ids: list[str] = Field(default_factory=_empty_verification_record_ids)

    @model_validator(mode="after")
    def verification_report_fields_are_consistent(self) -> "VerificationReportRecord":
        if self.record_type != "verification_report":
            msg = "record_type must be verification_report"
            raise ValueError(msg)
        if self.outcome != self.value.outcome:
            msg = "outcome must match value.outcome"
            raise ValueError(msg)
        return self


class VerificationResultProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    node_id: str
    record_id: str
    candidate_id: str | None = None
    task_region_id: str | None = None


class CandidateProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    candidate_id: str
    attempt_number: int = Field(ge=0)
    position: int
    file_state_record_ids: list[str] = Field(default_factory=list)
    supersedes_task_region_ids: list[str] = Field(default_factory=list)


class VerifierVerdictProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    candidate_id: str
    verdict: Literal["passed", "failed"]
    position: int


def _empty_lease_resource_claims() -> list[ResourceClaimProjection]:
    return []


LeaseProjectionState: TypeAlias = Literal["active", "suspended", "revoked", "expired", "released"]


class StrictEventPayload(BaseModel):
    """Canonical event payloads reject unknown envelope fields."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AgentDispatchRequestedPayload(StrictEventPayload):
    lease_granted_event_id: StrictStr
    lease_id: StrictStr
    node_id: StrictStr
    generation: StrictInt
    execution_id: StrictStr
    base_snapshot_id: StrictStr
    resource_claims: Annotated[list[AgentDispatchResourceClaim], Field(strict=True)]
    cache_authority_hash: StrictStr | None = None


class CommandRecordedPayload(StrictEventPayload):
    command_type: StrictStr
    command_payload: dict[str, Any]


class LeaseGrantedPayload(StrictEventPayload):
    lease_id: str
    node_id: str
    task_region_id: str | None = None
    kind: str | None = None
    generation: StrictInt | None = None
    execution_id: str | None = None
    base_snapshot_id: str | None = None
    expires_at: str | None = None
    resource_claims: list[ResourceClaimProjection] = Field(
        default_factory=_empty_lease_resource_claims,
    )
    session_id: str | None = None
    cache_authority_hash: StrictStr | None = None


class LeaseRenewedPayload(StrictEventPayload):
    lease_id: str
    node_id: str | None = None
    observed_at: str | None = None
    expires_at: str | None = None
    generation: StrictInt | None = None
    execution_id: str | None = None


class LeaseReleasedPayload(StrictEventPayload):
    node_id: str | None = None
    lease_id: str
    generation: StrictInt | None = None


class LeaseRevokedPayload(StrictEventPayload):
    lease_id: str
    node_id: str | None = None
    generation: StrictInt | None = None
    execution_id: str | None = None
    trigger: str | None = None
    reason: str | None = None


class LeaseExpiredPayload(StrictEventPayload):
    lease_id: str
    node_id: str | None = None
    generation: StrictInt | None = None
    execution_id: str | None = None
    expires_at: str | None = None
    reason: str | None = None


class LeaseSuspendedPayload(StrictEventPayload):
    lease_id: str
    node_id: str | None = None
    generation: StrictInt | None = None
    execution_id: str | None = None
    reason: str | None = None


class RunLifecycleChangedPayload(StrictEventPayload):
    command_type: str
    from_state: str
    to_state: str
    trigger: str
    node_id: str | None = None
    patch_id: str | None = None
    recovery_of_node_id: str | None = None
    recovery_of_record_id: str | None = None
    recovery_reason: str | None = None
    reason: str | None = None


class CommandRejectedPayload(StrictEventPayload):
    command_type: str
    reason: str
    blockers: list[dict[str, Any]] | None = None
    patch_id: str | None = None
    base_graph_position: StrictInt | None = None
    actor_role: str | None = None
    proposed_by_node_id: str | None = None
    rejection_reason: str | None = None
    diagnostics: dict[str, Any] | list[Any] | None = None
    read_set_diff: dict[str, Any] | None = None
    budget: StrictInt | None = None
    count: StrictInt | None = None


class CallbackPayloadBase(StrictEventPayload):
    node_id: str
    lease_id: str
    lease_generation: StrictInt
    execution_id: str
    idempotency_key: str
    # ``payload`` is legacy replay compatibility only. New audit events carry
    # the canonical identity and bounded record references.
    payload: dict[str, Any] | None = None
    payload_hash: str | None = None
    payload_size_bytes: StrictInt | None = None
    record_ids: list[str] = Field(default_factory=list)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        data = super().model_dump(*args, **kwargs)
        if "payload" in self.model_fields_set:
            data["payload"] = self.payload
        return data

    @model_validator(mode="after")
    def callback_payload_has_legacy_body_or_compact_identity(self) -> "CallbackPayloadBase":
        if "payload" not in self.model_fields_set and self.payload_hash is None:
            raise ValueError("callback audit requires payload or payload_hash")
        return self


class CallbackAcceptedPayload(CallbackPayloadBase):
    reason: str


class CallbackRejectedPayload(CallbackPayloadBase):
    reason: str


class CallbackDuplicateReturnedPayload(CallbackPayloadBase):
    reason: str
    prior_result: dict[str, Any] | None


class RuntimeRetryScheduledPayload(StrictEventPayload):
    node_id: str
    lease_id: str
    generation: StrictInt
    policy: str
    reason: str
    retry_after_seconds: StrictInt | None = None
    retry_not_before: str | None = None


class HeartbeatRecordedPayload(StrictEventPayload):
    lease_id: str
    node_id: str
    generation: StrictInt | None = None
    execution_id: str | None = None
    observed_at: str
    expires_at: str


class AgentDiedPayload(StrictEventPayload):
    lease_id: str
    node_id: str
    generation: StrictInt | None = None
    execution_id: str | None = None
    reason: str


class RunnerBoundaryEntry(StrictEventPayload):
    """The sole immutable, complete identity for a runner boundary path."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    kind: Literal["tracked", "untracked", "ignored"]
    status: str = Field(max_length=128)
    fingerprint: str
    file_type: Literal["file", "directory", "symlink", "missing"]

    @field_validator("path")
    @classmethod
    def repo_relative_path(cls, value: str) -> str:
        try:
            return validate_repo_relative_path(value)
        except BoundaryValidationError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("fingerprint")
    @classmethod
    def sha256_fingerprint(cls, value: str) -> str:
        try:
            return validate_sha256(value)
        except BoundaryValidationError as exc:
            raise ValueError(str(exc)) from exc


class RunnerBaselineRecordedPayload(StrictEventPayload):
    execution_id: str
    node_id: str
    lease_id: str
    lease_generation: StrictInt
    lease_base_snapshot_id: str | None = None
    baseline_snapshot_id: str
    baseline_snapshot_ref: str | None = None
    baseline_commit_sha: str | None = None
    baseline_tree_sha: str
    entries: list[RunnerBoundaryEntry]
    boundary_hash: str
    cache_authority_hash: str | None = None
    # Historical facts may carry the derived roots. New facts retain only the
    # immutable policy hash and status evidence and derive roots during replay.
    cache_roots: list[RunnerCacheRoot | str] = Field(
        default_factory=lambda: cast(list[RunnerCacheRoot | str], [])
    )
    cache_status_evidence: list[CacheStatusEvidence] | None = None

    @model_validator(mode="after")
    def manifest_is_consistent(self) -> "RunnerBaselineRecordedPayload":
        try:
            _validate_event_cache_roots(self.cache_roots, self.cache_authority_hash)
            if self.boundary_hash != boundary_manifest_hash(
                self.baseline_tree_sha,
                self.entries,
                self.cache_status_evidence or (),
                self.cache_authority_hash,
            ):
                raise BoundaryValidationError("boundary_hash does not match baseline manifest")
        except BoundaryValidationError as exc:
            raise ValueError(str(exc)) from exc
        return self


class RunnerSubmissionStagedPayload(StrictEventPayload):
    execution_id: str
    node_id: str
    lease_id: str
    lease_generation: StrictInt
    idempotency_key: str
    # New events store only ``payload_ref``. ``payload`` remains optional for
    # replaying historical staged submissions written before CAS ownership.
    payload: dict[str, Any] | None = None
    payload_ref: StoredArtifactRef | None = None
    payload_hash: str
    # Schema-13/early-schema-14 streams omitted this metadata; zero makes the
    # absence explicit while new command emission always supplies the size.
    payload_size_bytes: StrictInt = 0
    staged_snapshot_id: str
    staged_snapshot_ref: str | None = None
    staged_commit_sha: str | None = None
    staged_tree_sha: str
    boundary_hash: str
    boundary_entries: list[RunnerBoundaryEntry]
    base_snapshot_id: str
    observed_graph_position: StrictInt
    is_mutating: bool
    complete_node: bool
    new_state: Literal["completed", "failed"]
    owns_file_state_snapshot: bool | None = None
    cache_authority_hash: str | None = None
    cache_roots: list[RunnerCacheRoot | str] = Field(
        default_factory=lambda: cast(list[RunnerCacheRoot | str], [])
    )
    cache_status_evidence: list[CacheStatusEvidence] | None = None

    @model_validator(mode="after")
    def manifest_is_consistent(self) -> "RunnerSubmissionStagedPayload":
        try:
            _validate_event_cache_roots(self.cache_roots, self.cache_authority_hash)
            if self.boundary_hash != boundary_manifest_hash(
                self.staged_tree_sha,
                self.boundary_entries,
                self.cache_status_evidence or (),
                self.cache_authority_hash,
            ):
                raise BoundaryValidationError("boundary_hash does not match staged manifest")
        except BoundaryValidationError as exc:
            raise ValueError(str(exc)) from exc
        if self.payload is None and self.payload_ref is None:
            raise ValueError("staged submission requires payload or payload_ref")
        if self.payload_ref is not None:
            if self.payload_ref.content_hash != self.payload_hash:
                raise ValueError("payload_ref content hash must match payload_hash")
            if self.payload_size_bytes and self.payload_ref.size_bytes != self.payload_size_bytes:
                raise ValueError("payload_ref size must match payload_size_bytes")
            if self.payload_ref.artifact_id != self.payload_ref.content_hash:
                raise ValueError("payload_ref artifact_id must be content-addressed")
        return self


class RunnerBoundaryMismatchPayload(StrictEventPayload):
    execution_id: str
    node_id: str
    lease_id: str
    lease_generation: StrictInt
    staged_boundary_hash: str
    final_boundary_hash: str
    final_snapshot_id: str | None = None
    final_snapshot_ref: str | None = None
    final_commit_sha: str | None = None
    final_tree_sha: str
    final_boundary_entries: list[RunnerBoundaryEntry]
    cache_authority_hash: str | None = None
    cache_roots: list[RunnerCacheRoot | str] = Field(
        default_factory=lambda: cast(list[RunnerCacheRoot | str], [])
    )
    cache_status_evidence: list[CacheStatusEvidence] | None = None
    observed_cache_roots: list[RunnerCacheRoot] | None = None
    authorized_cache_roots: list[RunnerCacheRoot] | None = None
    legacy_cache_root_paths: list[str] | None = None
    reason: Literal["boundary_mismatch"]

    @model_validator(mode="after")
    def final_manifest_is_consistent(self) -> "RunnerBoundaryMismatchPayload":
        try:
            _validate_event_cache_roots(self.cache_roots, self.cache_authority_hash)
            if self.observed_cache_roots is not None:
                self.observed_cache_roots = list(
                    canonicalize_cache_roots(self.observed_cache_roots)
                )
            if self.authorized_cache_roots is not None:
                self.authorized_cache_roots = list(
                    canonicalize_cache_roots(self.authorized_cache_roots)
                )
            if self.final_boundary_hash != boundary_manifest_hash(
                self.final_tree_sha,
                self.final_boundary_entries,
                self.cache_status_evidence or (),
                self.cache_authority_hash,
            ):
                raise BoundaryValidationError("final_boundary_hash does not match final manifest")
        except BoundaryValidationError as exc:
            raise ValueError(str(exc)) from exc
        return self


class RunnerRecoveryRequestedPayload(StrictEventPayload):
    execution_id: str
    recovery_id: str
    node_id: str
    lease_id: str
    lease_generation: StrictInt
    reason: Literal["boundary_mismatch", "runner_died", "cancelled"]
    max_attempts: StrictInt = 0
    recovery_snapshot_id: str | None = None
    recovery_snapshot_ref: str | None = None
    recovery_commit_sha: str | None = None
    baseline_snapshot_id: str
    baseline_tree_sha: str
    final_tree_sha: str
    final_snapshot_id: str | None = None
    final_snapshot_ref: str | None = None
    final_commit_sha: str | None = None
    final_boundary_hash: str
    final_boundary_entries: list[RunnerBoundaryEntry]
    cache_authority_hash: str | None = None
    cache_roots: list[RunnerCacheRoot | str] = Field(
        default_factory=lambda: cast(list[RunnerCacheRoot | str], [])
    )
    cache_status_evidence: list[CacheStatusEvidence] | None = None
    observed_cache_roots: list[RunnerCacheRoot] | None = None
    authorized_cache_roots: list[RunnerCacheRoot] | None = None
    legacy_cache_root_paths: list[str] | None = None
    paths: list[str]
    recovery_scope: Literal["selective", "full_baseline"] = "selective"

    @model_validator(mode="after")
    def bounded_paths(self) -> "RunnerRecoveryRequestedPayload":
        from orchestrator.graph.boundary_types import validate_recovery_paths

        try:
            _validate_event_cache_roots(self.cache_roots, self.cache_authority_hash)
            if self.observed_cache_roots is not None:
                self.observed_cache_roots = list(
                    canonicalize_cache_roots(self.observed_cache_roots)
                )
            if self.authorized_cache_roots is not None:
                self.authorized_cache_roots = list(
                    canonicalize_cache_roots(self.authorized_cache_roots)
                )
            if self.recovery_scope == "selective":
                validate_recovery_paths(self.paths)
            elif self.paths or self.final_boundary_entries:
                raise BoundaryValidationError(
                    "full-baseline recovery has no path or boundary manifest"
                )
            if self.final_boundary_hash != boundary_manifest_hash(
                self.final_tree_sha,
                self.final_boundary_entries,
                self.cache_status_evidence or (),
                self.cache_authority_hash,
            ):
                raise BoundaryValidationError("final_boundary_hash does not match final manifest")
        except BoundaryValidationError as exc:
            raise ValueError(str(exc)) from exc
        return self


class RunnerRecoveryCompletedPayload(StrictEventPayload):
    execution_id: str
    recovery_id: str
    node_id: str | None = None
    lease_id: str | None = None
    lease_generation: StrictInt | None = None
    baseline_snapshot_id: str | None = None
    baseline_tree_sha: str | None = None
    requested_paths: list[str] | None = None
    proof_hash: str | None = None
    restored_paths: list[str]
    removed_paths: list[str]
    recovery_scope: Literal["selective", "full_baseline"] = "selective"

    @model_validator(mode="after")
    def bounded_paths(self) -> "RunnerRecoveryCompletedPayload":
        from orchestrator.graph.boundary_types import validate_recovery_paths

        if self.recovery_scope == "selective":
            validate_recovery_paths(
                self.requested_paths or [], self.restored_paths, self.removed_paths
            )
        elif self.requested_paths or self.restored_paths or self.removed_paths:
            raise ValueError("full-baseline recovery has no path accounting")
        return self


class RunnerExecutionFinalizedPayload(StrictEventPayload):
    execution_id: str
    node_id: str
    lease_id: str
    lease_generation: StrictInt
    final_snapshot_id: str
    final_snapshot_ref: str | None = None
    final_commit_sha: str | None = None
    final_tree_sha: str
    boundary_hash: str
    boundary_entries: list[RunnerBoundaryEntry]
    cache_authority_hash: str | None = None
    cache_roots: list[RunnerCacheRoot | str] = Field(
        default_factory=lambda: cast(list[RunnerCacheRoot | str], [])
    )
    cache_status_evidence: list[CacheStatusEvidence] | None = None

    @model_validator(mode="after")
    def manifest_is_consistent(self) -> "RunnerExecutionFinalizedPayload":
        try:
            _validate_event_cache_roots(self.cache_roots, self.cache_authority_hash)
            if self.boundary_hash != boundary_manifest_hash(
                self.final_tree_sha,
                self.boundary_entries,
                self.cache_status_evidence or (),
                self.cache_authority_hash,
            ):
                raise BoundaryValidationError("boundary_hash does not match final manifest")
        except BoundaryValidationError as exc:
            raise ValueError(str(exc)) from exc
        return self


def _validate_event_cache_roots(
    roots: list[RunnerCacheRoot | str], cache_authority_hash: str | None
) -> None:
    """Permit pre-authority string history, never new hash-bound string roots."""
    if any(isinstance(root, str) for root in roots):
        if cache_authority_hash is not None:
            raise BoundaryValidationError("hash-bound cache roots must be typed")
        validate_cache_roots(cast(list[str], roots))
        return
    canonicalize_cache_roots(cast(list[RunnerCacheRoot], roots))


class DeadInputDetectedPayload(StrictEventPayload):
    node_id: str
    from_node_id: str
    to_port: str
    reason: str


class LeaseProjection(_AttributeProjection):
    model_config = ConfigDict(frozen=True)
    lease_id: str
    state: LeaseProjectionState
    node_id: str | None = None
    generation: int | None = None
    execution_id: str | None = None
    expires_at: str | None = None
    session_id: str | None = None
    base_snapshot_id: str | None = None
    task_region_id: str | None = None
    kind: str | None = None
    resource_claims: list[ResourceClaimProjection] = Field(
        default_factory=_empty_lease_resource_claims,
    )
    cache_authority_hash: str | None = None


class InvalidTestBlockProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    position: int
    accepted: bool | None = None
    appeal_open: bool | None = None
    candidate_id: str | None = None


class PendingGateDecisionProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    node_id: str | None = None
    gate_type: str | None = None
    prompt: str | None = None
    options: list[str] | None = None
    default_option: str | None = None
    consequence_summary: str | None = None
    expires_at: str | None = None
    requested_authority: list[str] | None = None
    target_node_id: str | None = None
    target_region_id: str | None = None

    @model_validator(mode="after")
    def contains_projected_detail(self) -> "PendingGateDecisionProjection":
        values = (
            self.node_id,
            self.gate_type,
            self.prompt,
            self.options,
            self.default_option,
            self.consequence_summary,
            self.expires_at,
            self.requested_authority,
            self.target_node_id,
            self.target_region_id,
        )
        if not any(value not in (None, [], "") for value in values):
            msg = "pending gate decision detail must include at least one field"
            raise ValueError(msg)
        return self


def _empty_cleanup_paths() -> list[str]:
    return []


class GraphEventPayloadBase(StrictEventPayload):
    pass


class NodeUsageRecordedPayload(GraphEventPayloadBase):
    """One immutable model-usage fact emitted by a graph node execution."""

    node_id: str
    node_kind: str
    node_role: str | None = None
    profile: str | None = None
    execution_id: str
    usage_index: int = Field(ge=0)
    usage_count: int = Field(gt=0)
    usage_key: str
    model: str
    gen_ai_usage_input_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_output_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_cache_read_input_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_cache_creation_input_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_reasoning_output_tokens: int = Field(default=0, ge=0)
    gen_ai_response_finish_reasons: list[str] = Field(default_factory=list)
    cost_usd: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    latency_ms: int = Field(default=0, ge=0)
    num_actions: int = Field(default=0, ge=0)
    rate_missing: bool = False

    @model_validator(mode="after")
    def usage_identity_is_stable(self) -> "NodeUsageRecordedPayload":
        expected = f"{self.execution_id}:{self.usage_index}"
        if self.usage_key != expected:
            raise ValueError("usage_key must match execution_id:usage_index")
        if self.usage_index >= self.usage_count:
            raise ValueError("usage_index must be less than usage_count")
        return self


class CleanupEventPayloadBase(GraphEventPayloadBase):
    pass


class AppealOpenedPayload(GraphEventPayloadBase):
    run_id: str | None = None
    node_id: str
    appealed_node_id: str
    candidate_id: str | None = None
    task_region_id: str | None = None
    appeal_type: str
    lease_id: str | None = None
    membership: dict[str, Any] | None = None
    kind: str | None = None
    state: str | None = None


class DecisionRecordedPayloadBase(GraphEventPayloadBase):
    run_id: str | None = None
    decision_type: str
    node_id: str
    task_region_id: str | None = None
    gate_id: str | None = None
    appeal_node_id: str | None = None
    appealed_node_id: str | None = None
    candidate_id: str | None = None
    appeal_type: str | None = None
    expires_at: str | None = None
    reason: str | None = None
    record_id: str | None = None
    membership: dict[str, Any] | None = None
    decider: Any
    scope: Any | None = None


class ApprovalDecisionRecordedPayload(DecisionRecordedPayloadBase):
    decision: Literal["approved", "rejected", "deferred"]


class AuthorityDecisionRecordedPayload(DecisionRecordedPayloadBase):
    decision: Literal["granted", "denied", "deferred"]


class OversightDecisionRecordedPayload(DecisionRecordedPayloadBase):
    decision: Literal["accepted", "rejected", "invalid_test_accepted"]


class PlannerSessionStateChangedPayload(GraphEventPayloadBase):
    session_id: str | None = None
    state: str | None = None
    node_id: str | None = None
    lease_generation: StrictInt | None = None
    carryover_record_id: str | None = None


class GraphPatchAcceptedPayload(GraphEventPayloadBase):
    patch_id: str
    base_graph_position: StrictInt | None = None
    actor_role: str | None = None
    proposed_by_node_id: str | None = None
    successor_planner_node_ids: list[str] = Field(default_factory=list)
    session_id: str | None = None
    carryover_record_id: str | None = None


class GraphPatchRejectedPayload(GraphEventPayloadBase):
    patch_id: str
    base_graph_position: StrictInt | None = None
    actor_role: str | None = None
    proposed_by_node_id: str | None = None
    reason: str | None = None
    rejection_reason: str | None = None
    read_set_diff: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None
    budget: StrictInt | None = None
    count: StrictInt | None = None


class RequirementRevisionPayload(GraphEventPayloadBase):
    run_id: str | None = None
    requirement_id: str | None = None
    id: str | None = None
    node_id: str | None = None
    revision_id: str | None = None
    version_id: str | None = None
    requirement_version_id: str | None = None
    proposal_id: str | None = None
    patch_id: str | None = None
    change_classification: str | None = None
    classification: str | None = None
    revision_type: str | None = None
    requires_authority: StrictBool | None = None
    explicit_authority_required: StrictBool | None = None
    new_behavior: StrictBool | None = None
    behavior_change: StrictBool | None = None
    semantic_change: StrictBool | None = None
    validation_strengthening: StrictBool | None = None
    active: StrictBool | None = None
    previous_version_id: str | None = None
    revision_index: StrictInt | None = None
    authority_required_reason: str | None = None
    requirement: dict[str, Any] | None = None


class SupportEvidencePayload(GraphEventPayloadBase):
    run_id: str | None = None
    support_id: str | None = None
    edge_id: str | None = None
    evidence_id: str | None = None
    requirement_id: str | None = None
    requirement_version_id: str | None = None
    version_id: str | None = None
    status: str | None = None
    stale_reason: str | None = None
    confidence: str | None = None


class CleanupRequestedPayload(CleanupEventPayloadBase):
    cleanup_id: str
    file_state_record_id: str | None = None
    snapshot_id: str | None = None
    paths: list[str] = Field(default_factory=_empty_cleanup_paths)
    authority: str | None = None
    reason: str | None = None
    execution_id: str | None = None
    producer_node_id: str | None = None
    # Managed-runner cleanup is exact ref ownership, deliberately separate from
    # legacy file-state cleanup which can rebuild a filtered snapshot.
    snapshot_ref: str | None = None
    tree_sha: str | None = None
    commit_sha: str | None = None
    node_id: str | None = None
    lease_id: str | None = None
    lease_generation: StrictInt | None = None
    snapshot_role: Literal["baseline", "staged", "final", "recovery"] | None = None

    @model_validator(mode="after")
    def managed_snapshot_identity_is_complete(self) -> "CleanupRequestedPayload":
        managed = self.snapshot_role is not None
        fields = (
            self.snapshot_id,
            self.snapshot_ref,
            self.tree_sha,
            self.commit_sha,
            self.node_id,
            self.lease_id,
        )
        if managed and any(value is None for value in fields):
            raise ValueError("managed snapshot cleanup requires complete ownership identity")
        if managed:
            try:
                validate_snapshot_ref(self.snapshot_ref or "", self.snapshot_id or "")
                validate_git_oid(self.tree_sha or "")
                validate_git_oid(self.commit_sha or "")
            except BoundaryValidationError as exc:
                raise ValueError(str(exc)) from exc
        return self


class CleanupAppliedPayload(CleanupEventPayloadBase):
    cleanup_id: str
    file_state_record_id: str | None = None
    superseding_record_id: str | None = None
    old_snapshot_id: str | None = None
    new_snapshot_id: str | None = None
    paths: list[str] = Field(default_factory=_empty_cleanup_paths)
    authority: str | None = None
    reason: str | None = None
    execution_id: str | None = None
    deleted_snapshot_ref: StrictBool | None = None
    snapshot_ref: str | None = None
    tree_sha: str | None = None
    commit_sha: str | None = None
    node_id: str | None = None
    lease_id: str | None = None
    lease_generation: StrictInt | None = None
    snapshot_role: Literal["baseline", "staged", "final", "recovery"] | None = None

    @model_validator(mode="after")
    def managed_snapshot_identity_is_complete(self) -> "CleanupAppliedPayload":
        managed = self.snapshot_role is not None
        fields = (
            self.old_snapshot_id,
            self.snapshot_ref,
            self.tree_sha,
            self.commit_sha,
            self.node_id,
            self.lease_id,
        )
        if managed and any(value is None for value in fields):
            raise ValueError(
                "managed snapshot cleanup application requires complete ownership identity"
            )
        if managed:
            try:
                validate_snapshot_ref(self.snapshot_ref or "", self.old_snapshot_id or "")
                validate_git_oid(self.tree_sha or "")
                validate_git_oid(self.commit_sha or "")
            except BoundaryValidationError as exc:
                raise ValueError(str(exc)) from exc
        return self


class PlannerChainRegionPayload(StrictNestedModel):
    generation_index: StrictInt | None = None
    region_label: str | None = None
    child_routine: str | None = None


def _empty_planner_chain_regions() -> list[PlannerChainRegionPayload]:
    return []


class PlannerChainPayload(StrictNestedModel):
    source: str | None = None
    regions: list[PlannerChainRegionPayload] = Field(default_factory=_empty_planner_chain_regions)


def _empty_node_created_resource_claims() -> list[ResourceClaimProjection]:
    return []


def _empty_node_created_ports() -> list[PortModel]:
    return []


class NodeCreatedPayload(GraphEventPayloadBase):
    """Canonical payload for every compiler and command-side node creation."""

    run_id: str | None = None
    node_id: str
    kind: str
    role: str | None = None
    state: str
    task_region_id: str | None = None
    attempt_number: StrictInt | None = None
    candidate_id: str | None = None
    failed_candidate_id: str | None = None
    predecessor_node_ids: list[str] = Field(default_factory=list)
    appealed_node_id: str | None = None
    membership: dict[str, Any] | None = None
    authority: Authority | None = None
    resource_claims: list[ResourceClaimProjection] = Field(
        default_factory=_empty_node_created_resource_claims,
    )
    allowed_actions: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    planner_generation_budget: StrictInt | None = None
    generation_index: StrictInt | None = None
    region_label: str | None = None
    session_id: str | None = None
    carryover_record_id: str | None = None
    session_intent: str | None = None
    planner_chain: PlannerChainPayload | None = None
    gate_type: str | None = None
    approval_type: str | None = None
    reason: str | None = None
    prompt: str | None = None
    approval_prompt: str | None = None
    human_prompt: str | None = None
    message: str | None = None
    blocker: str | None = None
    blocker_reason: str | None = None
    decision_request: dict[str, Any] | None = None
    authority_request_record: dict[str, Any] | None = None
    authority_request: dict[str, Any] | None = None
    decision_request_record_id: str | None = None
    authority_request_record_id: str | None = None
    command_definition: CommandDefinitionProjection | None = None
    command_definition_id: str | None = None
    hidden_oracle_command: str | None = None
    command_binding: str | None = None
    command: str | None = None
    command_text: str | None = None
    recovery_reason: str | None = None
    recovery_of_node_id: str | None = None
    recovery_of_record_id: str | None = None
    guarded_planner_node_id: str | None = None
    rejected_patch_id: str | None = None
    patch_id: str | None = None
    requirement_id: str | None = None
    id: str | None = None
    priority: str | None = None
    requirement: dict[str, Any] | None = None
    inputs: list[PortModel] = Field(default_factory=_empty_node_created_ports)
    outputs: list[PortModel] = Field(default_factory=_empty_node_created_ports)
    acceptance: list[str] | None = None
    artifact_reference_record: dict[str, Any] | None = None
    artifacts: list[Any] | None = None
    available_tools: list[Any] | None = None
    bound_requirement_ids: list[str] | None = None
    builder_agent: str | None = None
    candidate_record: dict[str, Any] | None = None
    check_index: StrictInt | None = None
    complexity: str | None = None
    context_source: dict[str, Any] | None = None
    dynamic_feature: dict[str, Any] | None = None
    execution_id: str | None = None
    fan_out: dict[str, Any] | None = None
    gate: dict[str, Any] | None = None
    invariants: list[str] | None = None
    max_attempts: StrictInt | None = None
    mcp_servers: list[Any] | None = None
    objective: str | None = None
    profile: str | None = None
    prohibited_actions: list[str] | None = None
    requirement_record: dict[str, Any] | None = None
    routine: dict[str, Any] | None = None
    routine_snapshot_record: dict[str, Any] | None = None
    rubric: list[Any] | None = None
    run_context_record: dict[str, Any] | None = None
    scope: str | None = None
    snapshot: dict[str, Any] | None = None
    step_id: str | None = None
    step_index: StrictInt | None = None
    step_context: str | None = None
    submission_template: dict[str, Any] | None = None
    task_context: str | None = None
    task_id: str | None = None
    task_index: StrictInt | None = None
    title: str | None = None
    verifier_agent: str | None = None
    work_mode: str | None = None
    cache_authority_hash: str | None = None

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("exclude_unset", True)
        kwargs.setdefault("exclude_none", False)
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)


class NodeStateChangedPayload(GraphEventPayloadBase):
    node_id: str
    new_state: str
    trigger: str | None = None
    reason: str | None = None
    attempt_number: StrictInt | None = None
    max_attempts: StrictInt | None = None
    completion_status: str | None = None
    completion_decision_record_id: str | None = None
    join_result_record_id: str | None = None
    retry_not_before: str | None = None
    prompt_summary: dict[str, Any] | None = None
    membership: dict[str, Any] | None = None
    blockers: list[Any] | None = None
    graph_verifier_grades: dict[str, Any] | None = None
    tokens_by_node: dict[str, int] | None = None
    tokens_by_node_kind: dict[str, int] | None = None
    operations: list[dict[str, Any]] | None = None


class NodeRetiredPayload(GraphEventPayloadBase):
    node_id: str
    reason: str | None = None


class NodeReadyPayload(GraphEventPayloadBase):
    node_id: str


class NodeDeferredPayload(GraphEventPayloadBase):
    node_id: str
    reason: str


class NodeAuthorityChangedPayload(GraphEventPayloadBase):
    node_id: str
    authority: Authority | None = None
    resource_claims: list[ResourceClaimProjection] = Field(
        default_factory=_empty_node_created_resource_claims
    )
    allowed_actions: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)


class NodeSuspectPayload(GraphEventPayloadBase):
    node_id: str | None = None
    node_ids: list[str] = Field(default_factory=list)
    region_node_ids: list[str] = Field(default_factory=list)
    region_id: str | None = None
    reason: str | None = None


class CleanupRequestedProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    cleanup_id: str
    position: int
    file_state_record_id: str | None = None
    snapshot_id: str | None = None
    paths: list[str] = Field(default_factory=_empty_cleanup_paths)
    authority: str | None = None
    reason: str | None = None
    execution_id: str | None = None
    producer_node_id: str | None = None
    snapshot_ref: str | None = None
    tree_sha: str | None = None
    commit_sha: str | None = None
    node_id: str | None = None
    lease_id: str | None = None
    lease_generation: StrictInt | None = None
    snapshot_role: Literal["baseline", "staged", "final", "recovery"] | None = None


class RequirementRevisionProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    requirement_id: str
    version_id: str
    change_classification: str
    requires_authority: bool
    position: int
    previous_version_id: str | None = None
    revision_index: int | None = None
    authority_required_reason: str | None = None
    validation_strengthening: bool


class SupportEvidenceProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    support_id: str
    evidence_id: str
    requirement_id: str
    requirement_version_id: str
    status: str
    position: int
    stale_reason: str | None = None
    confidence: str | None = None


class OversightDecisionProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    node_id: str
    decision: Literal["accepted", "rejected", "invalid_test_accepted"]
    position: int
    task_region_id: str | None = None
    candidate_id: str | None = None
    gate_id: str | None = None
    appeal_node_id: str | None = None
    appealed_node_id: str | None = None
    appeal_type: str | None = None
    decider: dict[str, Any] | str | None = None
    scope: dict[str, Any] | None = None
    expires_at: str | None = None
    reason: str | None = None


def _empty_completion_blockers() -> list[dict[str, Any]]:
    return []


class CompletionDecisionValue(StrictNestedModel):
    status: Literal["passed", "blocked"]
    blockers: list[dict[str, Any]] = Field(default_factory=_empty_completion_blockers)


class CompletionDecisionRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: str
    schema_: str = Field(alias="schema")
    value: CompletionDecisionValue

    @model_validator(mode="after")
    def completion_decision_fields_are_consistent(self) -> "CompletionDecisionRecord":
        if self.record_type != "completion_decision":
            msg = "record_type must be completion_decision"
            raise ValueError(msg)
        if self.port != "completion_decision":
            msg = "port must be completion_decision"
            raise ValueError(msg)
        if self.schema_ != "CompletionDecision":
            msg = "schema must be CompletionDecision"
            raise ValueError(msg)
        return self


def _empty_join_source_record_ids() -> list[str]:
    return []


def _empty_missing_optional_inputs() -> list[str]:
    return []


class JoinResultValue(StrictNestedModel):
    status: Literal["ready", "blocked"]
    source_record_ids: list[str] = Field(default_factory=_empty_join_source_record_ids)
    missing_optional_inputs: list[str] = Field(default_factory=_empty_missing_optional_inputs)


class JoinResultRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: str
    schema_: str = Field(alias="schema")
    value: JoinResultValue

    @model_validator(mode="after")
    def join_result_fields_are_consistent(self) -> "JoinResultRecord":
        if self.record_type != "join_result":
            msg = "record_type must be join_result"
            raise ValueError(msg)
        if self.port != "join_result":
            msg = "port must be join_result"
            raise ValueError(msg)
        if self.schema_ != "JoinResult":
            msg = "schema must be JoinResult"
            raise ValueError(msg)
        return self


class CheckResultValue(StrictNestedModel):
    status: Literal["passed", "failed", "timeout"]
    classification: Literal[
        "passed",
        "failed",
        "timeout",
        "environment_error",
        "tool_error",
        "tool_unavailable",
    ]
    command_id: str
    command_binding: Any | None = None
    command_text: str
    command: dict[str, Any]
    worktree_path: str
    source_worktree_path: str | None = None
    execution_worktree_path: str | None = None
    base_snapshot_id: str
    execution_snapshot_id: str | None = None
    execution_snapshot_ref: str | None = None
    execution_id: str
    exit_code: StrictInt | None = None
    duration_ms: StrictInt = Field(ge=0)
    stdout_tail: str
    stdout_ref: StoredArtifactRef | None = None
    stderr_tail: str
    stderr_ref: StoredArtifactRef | None = None
    stdout_truncated: StrictBool
    stderr_truncated: StrictBool
    timeout_seconds: StrictFloat = Field(gt=0)
    environment_policy: dict[str, Any]
    source: str | None = None
    cited_record_id: str | None = None
    citation_mode: str | None = None
    reused_verification_record_id: str | None = None
    candidate_record_ids: list[str] = Field(default_factory=list)
    file_state_record_ids: list[str] = Field(default_factory=list)
    verification_report_record_ids: list[str] = Field(default_factory=list)
    evaluated_record_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def truncation_matches_artifact_references(self) -> "CheckResultValue":
        if self.stdout_truncated != (self.stdout_ref is not None):
            raise ValueError("stdout_truncated must match stdout_ref presence")
        if self.stderr_truncated != (self.stderr_ref is not None):
            raise ValueError("stderr_truncated must match stderr_ref presence")
        return self


class CheckResultRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: str
    schema_: str = Field(alias="schema")
    candidate_id: str
    task_region_id: str
    attempt_number: int = Field(ge=0)
    value: CheckResultValue
    candidate_record_id: str | None = None
    candidate_record_ids: list[str] = Field(default_factory=list)
    file_state_record_ids: list[str] = Field(default_factory=list)
    verification_report_record_ids: list[str] = Field(default_factory=list)
    evaluated_record_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_result_fields_are_consistent(self) -> "CheckResultRecord":
        if self.record_type != "check_result":
            msg = "record_type must be check_result"
            raise ValueError(msg)
        if self.port != "check_result":
            msg = "port must be check_result"
            raise ValueError(msg)
        if self.schema_ != "CheckResult":
            msg = "schema must be CheckResult"
            raise ValueError(msg)
        return self


def _empty_check_result_record_ids() -> list[str]:
    return []


class CheckResultProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    node_id: str
    status: str
    position: int
    task_region_id: str | None = None
    record_id: str | None = None
    classification: str | None = None
    command_text: str | None = None
    stderr_tail: str | None = None
    stdout_tail: str | None = None
    exit_code: int | None = None
    candidate_record_ids: list[str] = Field(default_factory=_empty_check_result_record_ids)
    file_state_record_ids: list[str] = Field(default_factory=_empty_check_result_record_ids)
    evaluated_record_ids: list[str] = Field(default_factory=_empty_check_result_record_ids)


class EnvironmentFailureProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    position: int
    node_id: str | None = None
    classification: str | None = None
    reason: str | None = None
    task_region_id: str | None = None
    record_id: str | None = None
    command_text: str | None = None
    stderr_tail: str | None = None
    exit_code: int | None = None


def _empty_node_resource_claims() -> list[ResourceClaimProjection]:
    return []


class NodeCreationProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    node_id: str
    position: int
    kind: str | None = None
    role: str | None = None
    state: str | None = None
    task_region_id: str | None = None
    attempt_number: int | None = None
    candidate_id: str | None = None
    failed_candidate_id: str | None = None
    resource_claims: list[ResourceClaimProjection] = Field(
        default_factory=_empty_node_resource_claims,
    )
    allowed_actions: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    planner_generation_budget: int | None = None
    generation_index: int | None = None
    region_label: str | None = None
    session_id: str | None = None
    gate_type: str | None = None
    approval_type: str | None = None
    reason: str | None = None
    prompt: str | None = None
    approval_prompt: str | None = None
    human_prompt: str | None = None
    message: str | None = None
    blocker: str | None = None
    blocker_reason: str | None = None
    decision_request: dict[str, Any] | None = None
    authority_request_record: dict[str, Any] | None = None
    authority_request_record_id: str | None = None
    authority_request: dict[str, Any] | None = None
    authority: dict[str, Any] | None = None
    command_definition: CommandDefinitionProjection | None = None
    command_definition_id: str | None = None
    hidden_oracle_command: str | None = None
    command_binding: str | None = None
    max_attempts: StrictInt | None = None


def _empty_candidate_changed_paths() -> list[str]:
    return []


def _empty_candidate_requirements() -> list[str]:
    return []


def _empty_candidate_file_state_ids() -> list[str]:
    return []


class CandidateValue(StrictNestedModel):
    summary: str
    changed_paths: list[str] = Field(default_factory=_empty_candidate_changed_paths)
    requirements_addressed: list[str] = Field(default_factory=_empty_candidate_requirements)
    file_state_record_id: str | None = None
    file_state_record_ids: list[str] = Field(default_factory=_empty_candidate_file_state_ids)


class CandidateRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: str
    schema_: str = Field(alias="schema")
    candidate_id: str
    task_region_id: str | None = None
    attempt_number: int | None = Field(default=None, ge=0)
    value: CandidateValue
    file_state_record_id: str | None = None
    file_state_record_ids: list[str] = Field(default_factory=_empty_candidate_file_state_ids)
    supersedes_task_region_id: str | None = None
    supersedes_task_region_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def candidate_fields_are_consistent(self) -> "CandidateRecord":
        if self.record_type != "candidate":
            msg = "record_type must be candidate"
            raise ValueError(msg)
        if self.port != "candidate":
            msg = "port must be candidate"
            raise ValueError(msg)
        if self.schema_ != "ImplementationCandidate":
            msg = "schema must be ImplementationCandidate"
            raise ValueError(msg)
        return self


class GapClassificationValue(StrictNestedModel):
    milestone_kind: str
    classification: Literal[
        "corrective_work_required",
        "no_gap",
        "human_decision_required",
        "graph_mutation_required",
    ]
    source: str
    task_region_id: str
    attempt_number: StrictInt = Field(ge=0)


class GapClassificationRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: str
    schema_: str = Field(alias="schema")
    value: GapClassificationValue

    @model_validator(mode="after")
    def gap_classification_fields_are_consistent(self) -> "GapClassificationRecord":
        if self.record_type not in {"gap_plan", "gap_classification", "classified_gap"}:
            msg = "record_type must be a gap classification record type"
            raise ValueError(msg)
        if self.port not in {"gap_plan", "gap_classification", "classified_gap"}:
            msg = "port must be a gap classification port"
            raise ValueError(msg)
        valid_pair = self.record_type == self.port or (
            self.record_type == "classified_gap" and self.port == "gap_classification"
        )
        if not valid_pair:
            msg = "record_type must match port"
            raise ValueError(msg)
        if self.schema_ != "GapClassification":
            msg = "schema must be GapClassification"
            raise ValueError(msg)
        return self


class DecisionActor(StrictNestedModel):
    kind: str
    id: str | None = None


class ApprovalDecisionProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    node_id: str
    decision: Literal["approved", "rejected", "deferred"]
    task_region_id: str | None = None
    gate_id: str | None = None
    appeal_node_id: str | None = None
    decider: DecisionActor | str | None = None
    scope: dict[str, Any] | None = None
    expires_at: str | None = None
    reason: str | None = None


class DecisionRecordValue(StrictNestedModel):
    decision: Literal["approved", "rejected", "deferred"]
    decision_type: Literal["approval"]
    decider: DecisionActor | str
    scope: dict[str, Any] | None = None
    expires_at: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def decision_decider_is_nonempty(self) -> "DecisionRecordValue":
        if isinstance(self.decider, str) and not self.decider:
            msg = "decider must not be empty"
            raise ValueError(msg)
        return self


class DecisionRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: Literal["decision_record"]
    schema_: Literal["DecisionRecord"] = Field(alias="schema")
    value: DecisionRecordValue

    @model_validator(mode="after")
    def decision_record_fields_are_consistent(self) -> "DecisionRecord":
        if self.record_type != "decision_record":
            msg = "record_type must be decision_record"
            raise ValueError(msg)
        return self


class AuthorityDecisionValue(StrictNestedModel):
    decision: Literal["granted", "denied", "deferred"]
    decision_type: Literal["authority"]
    decider: DecisionActor | str
    scope: dict[str, Any] | None = None
    expires_at: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def authority_decider_is_nonempty(self) -> "AuthorityDecisionValue":
        if isinstance(self.decider, str) and not self.decider:
            msg = "decider must not be empty"
            raise ValueError(msg)
        return self


class AuthorityDecisionRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: Literal["authority_decision"]
    schema_: Literal["AuthorityDecision"] = Field(alias="schema")
    value: AuthorityDecisionValue

    @model_validator(mode="after")
    def authority_decision_fields_are_consistent(self) -> "AuthorityDecisionRecord":
        if self.record_type != "authority_decision":
            msg = "record_type must be authority_decision"
            raise ValueError(msg)
        return self


class AuthorityDecisionProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    node_id: str
    decision: Literal["granted", "denied", "deferred"]
    task_region_id: str | None = None
    appeal_node_id: str | None = None
    decider: DecisionActor | str | None = None
    scope: dict[str, Any] | None = None
    expires_at: str | None = None
    reason: str | None = None


class AnalysisSummaryValue(StrictNestedModel):
    summary: str
    source_record_ids: list[str]
    lossy: StrictBool
    omitted_details: list[str]


class AnalysisSummaryRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: Literal["analysis_summary", "planning_summary", "region_summary"]
    schema_: Literal["AnalysisSummary", "RegionSummary"] = Field(alias="schema")
    value: AnalysisSummaryValue

    @model_validator(mode="after")
    def analysis_summary_fields_are_consistent(self) -> "AnalysisSummaryRecord":
        if self.record_type != "analysis_summary":
            msg = "record_type must be analysis_summary"
            raise ValueError(msg)
        return self


def _empty_graph_patch_ops() -> list[dict[str, Any]]:
    return []


def _empty_graph_patch_macro_invocations() -> list[dict[str, Any]]:
    return []


def _empty_expected_downstream_effects() -> list[str]:
    return []


class GraphPatchProposalValue(StrictNestedModel):
    patch_id: str
    proposed_by_node_id: str
    base_graph_position: StrictInt = Field(ge=0)
    ops: list[dict[str, Any]] = Field(default_factory=_empty_graph_patch_ops)
    macro_invocations: list[dict[str, Any]] = Field(
        default_factory=_empty_graph_patch_macro_invocations
    )
    rationale: str | None = None
    rationale_record_id: str | None = None
    expected_downstream_effects: list[str] = Field(
        default_factory=_empty_expected_downstream_effects
    )

    @model_validator(mode="after")
    def proposal_has_mutation_plan(self) -> "GraphPatchProposalValue":
        if not self.ops and not self.macro_invocations:
            msg = "graph patch proposal must include ops or macro_invocations"
            raise ValueError(msg)
        return self


class GraphPatchProposalRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: Literal["graph_patch_proposal", "graph_patch"]
    schema_: Literal["GraphPatch"] = Field(alias="schema")
    value: GraphPatchProposalValue

    @model_validator(mode="after")
    def graph_patch_proposal_fields_are_consistent(self) -> "GraphPatchProposalRecord":
        if self.record_type != "graph_patch_proposal":
            msg = "record_type must be graph_patch_proposal"
            raise ValueError(msg)
        return self


def _empty_created_node_ids() -> list[str]:
    return []


def _empty_created_edge_ids() -> list[str]:
    return []


class GraphPatchResultRecord(GraphBaseModel):
    patch_id: str
    proposed_by_node_id: str | None = None
    base_graph_position: StrictInt | None = Field(default=None, ge=0)
    current_graph_position: StrictInt = Field(ge=0)
    status: Literal["accepted", "rejected"]
    rejection_reason: str | None = None
    diagnostics: dict[str, Any] | None = None
    read_set_diff: dict[str, Any] | None = None
    accepted_event_id: str | None = None
    accepted_position: int | None = Field(default=None, ge=0)
    rejected_event_id: str | None = None
    rejected_position: int | None = Field(default=None, ge=0)
    created_node_ids: list[str] = Field(default_factory=_empty_created_node_ids)
    created_edge_ids: list[str] = Field(default_factory=_empty_created_edge_ids)

    @model_validator(mode="after")
    def result_status_fields_are_consistent(self) -> "GraphPatchResultRecord":
        if self.status == "accepted" and self.accepted_position is None:
            msg = "accepted graph patch result requires accepted_position"
            raise ValueError(msg)
        if self.status == "rejected":
            if self.rejected_position is None:
                msg = "rejected graph patch result requires rejected_position"
                raise ValueError(msg)
            if not self.rejection_reason:
                msg = "rejected graph patch result requires rejection_reason"
                raise ValueError(msg)
        return self


def _empty_acceptance_criteria() -> list[str]:
    return []


class RequirementRecordValue(StrictNestedModel):
    id: str
    text: str
    desc: str | None = None
    priority: Literal["critical", "expected", "nice"] = "critical"
    acceptance_criteria: list[str] = Field(default_factory=_empty_acceptance_criteria)
    source: str | None = None
    version: str | None = None
    supersedes: str | None = None
    must: StrictBool = True


class RequirementRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["graph_record"]
    producer_node_id: str
    port: Literal["requirement"]
    schema_: Literal["RequirementRecord"] = Field(alias="schema")
    value: RequirementRecordValue

    @model_validator(mode="after")
    def requirement_fields_are_consistent(self) -> "RequirementRecord":
        if self.record_type != "requirement_record":
            msg = "record_type must be requirement_record"
            raise ValueError(msg)
        return self


class DecisionRequestValue(StrictNestedModel):
    decision_type: str
    options: list[str]
    default_option: str | None = None
    consequence_summary: str
    expires_at: str | None = None
    target_node_id: str | None = None
    target_region_id: str | None = None

    @model_validator(mode="after")
    def decision_options_are_consistent(self) -> "DecisionRequestValue":
        if not self.options:
            msg = "decision request requires at least one option"
            raise ValueError(msg)
        if self.default_option is not None and self.default_option not in self.options:
            msg = "decision request default_option must be one of options"
            raise ValueError(msg)
        return self


class DecisionRequestRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["graph_record"]
    producer_node_id: str
    port: Literal["decision_request"]
    schema_: Literal["DecisionRequest"] = Field(alias="schema")
    value: DecisionRequestValue

    @model_validator(mode="after")
    def decision_request_fields_are_consistent(self) -> "DecisionRequestRecord":
        if self.record_type != "decision_request":
            msg = "record_type must be decision_request"
            raise ValueError(msg)
        return self


class AuthorityRequestValue(StrictNestedModel):
    requested_authority: list[str]
    target_node_id: str | None = None
    target_region_id: str | None = None
    reason: str
    expires_at: str | None = None

    @model_validator(mode="after")
    def authority_target_is_present(self) -> "AuthorityRequestValue":
        if self.target_node_id is None and self.target_region_id is None:
            msg = "authority request requires target_node_id or target_region_id"
            raise ValueError(msg)
        return self


class AuthorityRequestRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["graph_record"]
    producer_node_id: str
    port: Literal["authority_request_record"]
    schema_: Literal["AuthorityRequest"] = Field(alias="schema")
    value: AuthorityRequestValue

    @model_validator(mode="after")
    def authority_request_fields_are_consistent(self) -> "AuthorityRequestRecord":
        if self.record_type != "authority_request_record":
            msg = "record_type must be authority_request_record"
            raise ValueError(msg)
        return self


class FailureRecordValue(StrictNestedModel):
    failed_node_id: str
    phase: str
    error_class: str
    retryable: StrictBool
    lease_id: str | None = None
    lease_generation: StrictInt | None = None
    execution_id: str | None = None
    reason: str | None = None
    expires_at: str | None = None
    attempt_number: StrictInt | None = None
    max_attempts: StrictInt | None = None


class FailureRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["graph_record"]
    producer_node_id: str
    port: Literal["failure_record"]
    schema_: Literal["FailureRecord"] = Field(alias="schema")
    task_region_id: str | None = None
    value: FailureRecordValue

    @model_validator(mode="after")
    def failure_record_fields_are_consistent(self) -> "FailureRecord":
        if self.record_type != "failure_record":
            msg = "record_type must be failure_record"
            raise ValueError(msg)
        return self


class RecoveryPlanValue(StrictNestedModel):
    action: Literal["retry", "supersede", "cancel", "cleanup"]
    responsible_actor: str
    graph_changes: list[dict[str, Any]]
    reason: str | None = None
    retry_after_seconds: StrictInt | None = None
    retry_not_before: str | None = None


class RecoveryPlanRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: Literal["recovery_plan"]
    schema_: Literal["RecoveryPlan"] = Field(alias="schema")
    value: RecoveryPlanValue

    @model_validator(mode="after")
    def recovery_plan_fields_are_consistent(self) -> "RecoveryPlanRecord":
        if self.record_type != "recovery_plan":
            msg = "record_type must be recovery_plan"
            raise ValueError(msg)
        return self


OutputRecordPayload = (
    OutputRecord
    | RunContextRecord
    | RoutineSnapshotRecord
    | ArtifactReferenceRecord
    | VerificationReportRecord
    | CompletionDecisionRecord
    | JoinResultRecord
    | CheckResultRecord
    | CandidateRecord
    | GapClassificationRecord
    | DecisionRecord
    | AuthorityDecisionRecord
    | AnalysisSummaryRecord
    | GraphPatchProposalRecord
    | RequirementRecord
    | DecisionRequestRecord
    | AuthorityRequestRecord
    | FailureRecord
    | RecoveryPlanRecord
)


class GitRef(StrictNestedModel):
    commit_sha: str | None = None
    tree_sha: str | None = None
    no_commit_reason: str | None = None
    ref: str | None = None
    diff_summary: dict[str, Any] | None = None


class FileEntry(StrictNestedModel):
    path: str
    source: str | None = None
    status: str | None = None
    classification: str | None = None
    policy: str | None = None
    matched_rule: str | None = None
    needs_gatekeeper: StrictBool | None = None
    rejected: StrictBool | None = None
    reason: str | None = None
    size_bytes: StrictInt | None = None
    entropy: StrictFloat | None = None
    gatekeeper_confidence: StrictFloat | None = None
    gatekeeper_rationale: str | None = None
    manifest: "ExternalArtifactManifest | None" = None


class ExternalArtifactManifest(StrictNestedModel):
    path: str
    hash: str
    origin: str
    retention: str


class ExternalFileEntry(FileEntry):
    @model_validator(mode="after")
    def external_entry_requires_manifest(self) -> "ExternalFileEntry":
        if self.manifest is None:
            msg = "external file entries require manifest"
            raise ValueError(msg)
        return self


def _empty_file_entries() -> list[FileEntry]:
    return []


class FileStateRecord(TypedRecordBase):
    model_config = ConfigDict(frozen=True)
    record_id: str
    record_kind: Literal["file_state"] = "file_state"
    snapshot_id: str | None = None
    base_snapshot_id: str | None = None
    producer_node_id: str | None = None
    port: str = "file_state"
    schema_: str = Field(default="FileStateRecord", alias="schema")
    git: GitRef | None = None
    # Canonical durable inventory. Historical payloads with repeated category
    # arrays are normalized by ``canonicalize_path_inventory`` below; category
    # views remain available as derived Python properties without being dumped
    # back into new events.
    paths: list[FileEntry] = Field(default_factory=_empty_file_entries)
    verdict: Literal["captured", "rejected"] = "captured"
    patch_bundle_id: str | None = None
    tree_snapshot_id: str | None = None
    position: int | None = None
    task_region_id: str | None = None
    candidate_id: str | None = None
    # Projection-only lineage/safety fields used when a later gatekeeper verdict
    # proves the original snapshot captured a secret. Historical records remain
    # immutable; reducers mark the old record compromised and point at the
    # superseding cleanup record.
    compromised: bool | None = None
    superseded_pending: bool | None = None
    supersedes_record_id: str | None = None
    superseded_by_record_id: str | None = None
    cleanup_id: str | None = None
    cleanup_excluded_paths: list[str] = Field(default_factory=list)
    cleanup_reason: str | None = None
    cleanup_applied_event_id: str | None = None
    compromised_snapshot_deleted: bool | None = None
    compromised_paths: list[str] | None = None
    acceptance_identity: str | None = None

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        dumped = super().model_dump(*args, **kwargs)
        if self.acceptance_identity is None:
            dumped.pop("acceptance_identity", None)
        return dumped

    @model_validator(mode="before")
    @classmethod
    def canonicalize_path_inventory(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(cast(dict[str, Any], value))
        groups = (
            "paths",
            "classifications",
            "tracked",
            "untracked",
            "ignored",
            "external",
            "residue",
            "rejected_paths",
        )
        inventory: dict[str, dict[str, Any]] = {}
        saw_inventory_field = False
        for group in groups:
            saw_inventory_field = saw_inventory_field or group in payload
            raw_entries = payload.pop(group, [])
            if not isinstance(raw_entries, (list, tuple)):
                continue
            for raw_entry in cast(list[Any] | tuple[Any, ...], raw_entries):
                if not isinstance(raw_entry, dict):
                    continue
                typed_entry = cast(dict[str, Any], raw_entry)
                if not isinstance(typed_entry.get("path"), str):
                    continue
                entry = dict(typed_entry)
                if group in {"tracked", "untracked", "ignored"}:
                    entry.setdefault("source", group)
                if group == "external":
                    entry.setdefault("classification", "external_artifact")
                if group == "rejected_paths":
                    entry.setdefault("rejected", True)
                path = cast(str, entry["path"])
                inventory[path] = {**inventory.get(path, {}), **entry}
        if saw_inventory_field:
            payload["paths"] = list(inventory.values())
        return payload

    @property
    def classifications(self) -> list[FileEntry]:
        return list(self.paths)

    @property
    def tracked(self) -> list[FileEntry]:
        return [entry for entry in self.paths if entry.source == "tracked"]

    @property
    def untracked(self) -> list[FileEntry]:
        return [entry for entry in self.paths if entry.source == "untracked"]

    @property
    def ignored(self) -> list[FileEntry]:
        return [entry for entry in self.paths if entry.source == "ignored"]

    @property
    def external(self) -> list[ExternalFileEntry]:
        return [
            ExternalFileEntry.model_validate(entry.model_dump(mode="json"))
            for entry in self.paths
            if entry.manifest is not None
        ]

    @property
    def residue(self) -> list[FileEntry]:
        return [
            entry
            for entry in self.paths
            if entry.source in {"untracked", "ignored"}
            or entry.classification == "external_artifact"
        ]

    @property
    def rejected_paths(self) -> list[FileEntry]:
        return [entry for entry in self.paths if entry.rejected is True]

    @model_validator(mode="after")
    def file_state_record_type_is_canonical(self) -> "FileStateRecord":
        if self.record_type != "file_state":
            msg = "record_type must be file_state"
            raise ValueError(msg)
        return self


AcceptedOutputRecordPayload: TypeAlias = OutputRecordPayload | FileStateRecord

OUTPUT_RECORD_MODELS_BY_TYPE: MappingProxyType[str, type[GraphBaseModel]] = MappingProxyType(
    {
        "analysis_summary": AnalysisSummaryRecord,
        "artifact_reference": ArtifactReferenceRecord,
        "authority_decision": AuthorityDecisionRecord,
        "authority_request_record": AuthorityRequestRecord,
        "candidate": CandidateRecord,
        "check_result": CheckResultRecord,
        "classified_gap": GapClassificationRecord,
        "completion_decision": CompletionDecisionRecord,
        "decision_record": DecisionRecord,
        "decision_request": DecisionRequestRecord,
        "failure_record": FailureRecord,
        "fan_out_inputs": OutputRecord,
        "file_state": FileStateRecord,
        "gap_classification": GapClassificationRecord,
        "gap_plan": GapClassificationRecord,
        "graph_patch_proposal": GraphPatchProposalRecord,
        "join_result": JoinResultRecord,
        "recovery_plan": RecoveryPlanRecord,
        "requirement_record": RequirementRecord,
        "routine_snapshot": RoutineSnapshotRecord,
        "run_context": RunContextRecord,
        "verification_report": VerificationReportRecord,
    }
)


class OutputRecordAcceptedPayload(RootModel[AcceptedOutputRecordPayload]):
    """Flat, canonical output-record acceptance event payload."""

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.root.model_dump(*args, **kwargs)


class VerificationOutcomePayload(StrictEventPayload):
    node_id: str
    verifier_node_id: str
    candidate_id: str
    task_region_id: str | None = None
    record_id: str
    outcome: Literal["passed", "failed"]
    evidence: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    value: VerificationReportValue

    @model_validator(mode="after")
    def outcome_matches_value(self) -> "VerificationOutcomePayload":
        if self.outcome != self.value.outcome:
            msg = "outcome must match value.outcome"
            raise ValueError(msg)
        return self


class VerificationPassedPayload(StrictEventPayload):
    node_id: str
    verifier_node_id: str
    candidate_id: str
    task_region_id: str | None = None
    record_id: str
    outcome: Literal["passed"]
    evidence: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    value: VerificationReportValue

    @model_validator(mode="after")
    def outcome_matches_value(self) -> "VerificationPassedPayload":
        if self.outcome != self.value.outcome:
            msg = "outcome must match value.outcome"
            raise ValueError(msg)
        return self


class VerificationFailedPayload(StrictEventPayload):
    node_id: str
    verifier_node_id: str
    candidate_id: str
    task_region_id: str | None = None
    record_id: str
    outcome: Literal["failed"]
    evidence: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    value: VerificationReportValue

    @model_validator(mode="after")
    def outcome_matches_value(self) -> "VerificationFailedPayload":
        if self.outcome != self.value.outcome:
            msg = "outcome must match value.outcome"
            raise ValueError(msg)
        return self


class InputBoundPayload(StrictEventPayload):
    edge_id: str
    to_node_id: str
    to_port: str
    record_ids: list[str] = Field(min_length=1)
    bound_at_position: int = Field(ge=0)
    binding_policy: str | None = None
    supersedes_record_id: str | None = None
    record_bound_positions: dict[str, int] = Field(default_factory=dict)
    trigger: str | None = None


class RevisionCreatedPayload(StrictEventPayload):
    node: NodeModel
    worker_node: NodeModel
    verifier_node: NodeModel


class CanonicalFileStateRecord(FileStateRecord):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class FileStateAcceptedPayload(RootModel[CanonicalFileStateRecord]):
    """Flat, canonical file-state acceptance event payload."""

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.root.model_dump(*args, **kwargs)


class FileStateRejectedPayload(CanonicalFileStateRecord):
    reason: str | None = None


class GatekeeperVerdictRow(StrictEventPayload):
    path: str
    classification: str
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    rationale: str
    model_id: str | None = None
    gen_ai_usage_input_tokens: StrictInt = Field(default=0, ge=0)
    gen_ai_usage_output_tokens: StrictInt = Field(default=0, ge=0)
    gen_ai_usage_cache_read_input_tokens: StrictInt = Field(default=0, ge=0)
    gen_ai_usage_cache_creation_input_tokens: StrictInt = Field(default=0, ge=0)
    cost_usd: StrictFloat = Field(default=0.0, ge=0.0)
    wall_time_ms: StrictInt = Field(default=0, ge=0)


class GatekeeperVerdictRecordedPayload(StrictEventPayload):
    file_state_record_id: str
    execution_id: str
    producer_node_id: str
    verdicts: list[GatekeeperVerdictRow] = Field(min_length=1)
    resolved_count: int = Field(ge=0)


class GatekeeperCostRecordedPayload(StrictEventPayload):
    execution_id: str
    file_state_record_id: str
    consult_id: str
    model_id: str | None = None
    gen_ai_usage_input_tokens: StrictInt = Field(default=0, ge=0)
    gen_ai_usage_output_tokens: StrictInt = Field(default=0, ge=0)
    gen_ai_usage_cache_read_input_tokens: StrictInt = Field(default=0, ge=0)
    gen_ai_usage_cache_creation_input_tokens: StrictInt = Field(default=0, ge=0)
    item_count: StrictInt = Field(default=0, ge=0)
    cost_usd: StrictFloat = Field(default=0.0, ge=0.0)
    wall_time_ms: StrictInt = Field(default=0, ge=0)


class OutboxRequeuedPayload(StrictEventPayload):
    run_id: StrictStr
    outbox_id: StrictInt
    event_id: StrictStr
    kind: StrictStr
    previous_status: StrictStr
    previous_attempts: StrictInt
    previous_last_error: StrictStr | None
    operator: StrictStr
    graph_position: StrictInt


class GraphRecordKind(str, Enum):
    NODE_CREATED = "node_created"
    EDGE_CREATED = "edge_created"
    NODE_RETIRED = "node_retired"
    NODE_STATE_CHANGED = "node_state_changed"
    LEASE_GRANTED = "lease_granted"
    LEASE_SUSPENDED = "lease_suspended"
    LEASE_REVOKED = "lease_revoked"
    CALLBACK_RECEIVED = "callback_received"
    CALLBACK_ACCEPTED = "callback_accepted"
    CALLBACK_REJECTED_STALE = "callback_rejected_stale"
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"
    REVISION_CREATED = "revision_created"
    APPEAL_OPENED = "appeal_opened"
    OVERSIGHT_DECISION_RECORDED = "oversight_decision_recorded"
    APPROVAL_DECISION_RECORDED = "approval_decision_recorded"
    GRAPH_PATCH_ACCEPTED = "graph_patch_accepted"
    FILE_STATE_ACCEPTED = "file_state_accepted"


class GraphRecord(GraphBaseModel):
    record_id: str
    record_kind: GraphRecordKind
    run_id: str | None = None
    producer_node_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ActorKind(str, Enum):
    CONTROLLER = "controller"
    AGENT = "agent"
    HUMAN = "human"
    SCHEDULER = "scheduler"
    SYSTEM = "system"


class Actor(GraphBaseModel):
    kind: ActorKind
    id: str | None = None
    node_id: str | None = None
    role: str | None = None


class EventEnvelope(GraphBaseModel):
    event_id: str
    run_id: str
    position: int
    event_type: str
    schema_version: int
    actor: Actor
    causation_id: str | None = None
    correlation_id: str | None = None
    timestamp: datetime
    payload: dict[str, Any]


class CallbackIdempotencyEvent(GraphBaseModel):
    model_config = ConfigDict(frozen=True)
    event_type: Literal[
        "callback_accepted",
        "callback_rejected_stale",
        "callback_rejected_conflict",
        "callback_duplicate_returned",
    ]
    node_id: str
    idempotency_key: str
    outcome: str
    payload: dict[str, Any] | None = None
    payload_hash: str | None = None
    payload_size_bytes: StrictInt | None = None
    record_ids: list[str] = Field(default_factory=list)


class PatchOp(StrictNestedModel):
    op: str
    kind: str | None = None
    state: str | None = None
    edge_id: str | None = None
    node: dict[str, Any] | None = None
    from_node_id: str | None = None
    from_node_kind: str | None = None
    from_node_role: str | None = None
    from_port: str | None = None
    to_node_id: str | None = None
    to_port: str | None = None
    required: bool | None = None
    dependency_type: Literal["input_binding", "state_dependency"] | None = None
    accepted_record_selector: RecordSelector | None = None
    binding_policy: str | None = None
    prompt_hydration_policy: str | None = None
    freshness_policy: str | None = None
    purpose: str | None = None
    description: str | None = None
    selection: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    node_id: str | None = None
    resource_claims: list[ResourceClaim] | None = None
    allowed_actions: list[str] | None = None
    task_region_id: str | None = None
    predecessor_node_ids: list[str] | None = None
    failed_candidate_id: str | None = None
    worker_node: dict[str, Any] | None = None
    verifier_node: dict[str, Any] | None = None
    appealed_node_id: str | None = None
    appeal_type: str | None = None
    region_node_ids: list[str] | None = None
    reason: str | None = None


class PatchEnvelope(GraphBaseModel):
    patch_id: str
    proposed_by_node_id: str
    base_graph_position: StrictInt
    ops: list[PatchOp]
    rationale_record_id: str | None = None


class LeaseState(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    EXPIRED = "expired"
    RELEASED = "released"


class LeaseModel(GraphBaseModel):
    lease_id: str
    generation: int
    run_id: str
    node_id: str
    session_id: str | None = None
    base_snapshot_id: str
    resource_claims: list[ResourceClaim] = Field(default_factory=_empty_resource_claims)
    expires_at: datetime
    state: LeaseState


def _empty_record_proposals() -> list[dict[str, Any]]:
    return []


def _empty_patch_envelopes() -> list[PatchEnvelope]:
    return []


class CallbackEnvelope(GraphBaseModel):
    run_id: str
    node_id: str
    execution_id: str
    lease_id: str
    lease_generation: int
    base_snapshot_id: str
    observed_graph_position: int
    idempotency_key: str
    records: list[dict[str, Any]] = Field(default_factory=_empty_record_proposals)
    proposed_graph_patches: list[PatchEnvelope] = Field(default_factory=_empty_patch_envelopes)
