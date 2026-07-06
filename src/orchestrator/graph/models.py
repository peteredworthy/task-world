"""Pydantic models for the execution graph PRD data contracts."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class GraphBaseModel(BaseModel):
    """Base model that preserves forward-compatible PRD fields."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Dump the supplied PRD shape unless callers choose a different policy."""
        kwargs.setdefault("by_alias", True)
        kwargs.setdefault("exclude_unset", True)
        return super().model_dump(*args, **kwargs)


class TypedRecordBase(GraphBaseModel):
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


class ResourceClaim(GraphBaseModel):
    mode: str
    scope: str
    paths: list[str] | None = None
    external_resource_key: str | None = None

    @model_validator(mode="after")
    def external_claims_require_keys(self) -> "ResourceClaim":
        if self.mode == "external" and self.external_resource_key is None:
            msg = "external claims require external_resource_key"
            raise ValueError(msg)
        return self


def _empty_resource_claims() -> list[ResourceClaim]:
    return []


class Authority(GraphBaseModel):
    allowed_actions: list[str] = Field(default_factory=list)
    resource_claims: list[ResourceClaim] = Field(default_factory=_empty_resource_claims)


class PortModel(GraphBaseModel):
    node_id: str | None = None
    port: str
    direction: Literal["input", "output"] | None = None
    schema_: str | None = Field(default=None, alias="schema")
    record_layers: list[str] | None = None
    required: bool | None = None


def _empty_ports() -> list[PortModel]:
    return []


class NodeMembership(GraphBaseModel):
    task_region_id: str
    attempt_number: int
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
        "completion_decision",
        "decision_record",
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

_LEGACY_SELECTOR_KIND_MAP: dict[str, dict[str, Any]] = {
    "accepted_file_state": {"record_type": "file_state", "schema": "FileStateRecord"},
    "accepted_candidate": {"record_type": "candidate", "schema": "ImplementationCandidate"},
    "artifact": {"record_type": "artifact_reference", "schema": "ContextArtifact"},
    "artifact_reference": {"record_type": "artifact_reference", "schema": "ArtifactReference"},
    "authority_decision": {"record_type": "authority_decision", "schema": "AuthorityDecision"},
    "candidate": {"record_type": "candidate", "schema": "ImplementationCandidate"},
    "candidate_under_test": {"record_type": "candidate", "schema": "ImplementationCandidate"},
    "check_result": {"record_type": "check_result", "schema": "CheckResult"},
    "classified_gap": {"record_type": "gap_classification", "schema": "GapClassification"},
    "completion_decision": {"record_type": "completion_decision", "schema": "CompletionDecision"},
    "decision_record": {"record_type": "decision_record", "schema": "DecisionRecord"},
    "failure_record": {"record_type": "failure_record", "schema": "FailureRecord"},
    "file_state": {"record_type": "file_state", "schema": "FileStateRecord"},
    "gap_analysis": {"record_type": "gap_classification", "schema": "GapClassification"},
    "gap_classification": {"record_type": "gap_classification", "schema": "GapClassification"},
    "gap_plan": {"record_type": "gap_classification", "schema": "GapClassification"},
    "graph_patch": {"record_type": "graph_patch_proposal", "schema": "GraphPatch"},
    "graph_patch_proposal": {"record_type": "graph_patch_proposal", "schema": "GraphPatch"},
    "output": {"record_type": "candidate", "schema": "ImplementationCandidate"},
    "region_summary": {"record_type": "analysis_summary"},
    "requirement": {"record_type": "requirement_record", "schema": "RequirementRecord"},
    "requirement_record": {"record_type": "requirement_record", "schema": "RequirementRecord"},
    "routine_snapshot": {"record_type": "routine_snapshot", "schema": "RoutineSnapshot"},
    "run_context": {"record_type": "run_context", "schema": "RunContext"},
    "snapshot": {"record_type": "routine_snapshot", "schema": "RoutineSnapshot"},
    "verification": {"record_type": "verification_report", "schema": "VerificationReport"},
    "verification_evidence": {"record_type": "verification_report", "schema": "VerificationReport"},
    "verification_report": {"record_type": "verification_report", "schema": "VerificationReport"},
    "verification_result": {"record_type": "verification_report", "schema": "VerificationReport"},
}


def _normalize_legacy_selector(value: Any) -> Any:
    if isinstance(value, RecordSelector):
        return value.root.model_dump(mode="json")
    if not isinstance(value, dict):
        return value
    selector = dict(cast(dict[str, Any], value))
    if isinstance(selector.get("record_type"), str):
        _reject_legacy_value_paths(selector)
        return selector

    raw_kinds = selector.get("record_kinds")
    if not isinstance(raw_kinds, list):
        _reject_legacy_value_paths(selector)
        return selector
    normalized_parts: list[dict[str, Any]] = []
    unknown_kinds: list[str] = []
    for raw_kind in cast(list[Any], raw_kinds):
        if not isinstance(raw_kind, str) or raw_kind not in _LEGACY_SELECTOR_KIND_MAP:
            unknown_kinds.append(str(raw_kind))
            continue
        normalized_parts.append(dict(_LEGACY_SELECTOR_KIND_MAP[raw_kind]))
    if unknown_kinds:
        msg = f"unknown selector record_kinds: {', '.join(unknown_kinds)}"
        raise ValueError(msg)
    if not normalized_parts:
        return selector
    schema = selector.get("schema")
    if isinstance(schema, str) and len(normalized_parts) == 1:
        normalized_parts[0]["schema"] = schema
    value_matches = selector.get("value_matches")
    if isinstance(value_matches, dict):
        _apply_legacy_value_matches(normalized_parts, cast(dict[str, Any], value_matches))
    if len(normalized_parts) == 1:
        return normalized_parts[0]
    return {"record_type": "any_of", "selectors": normalized_parts}


def _reject_legacy_value_paths(selector: dict[str, Any]) -> None:
    value_matches = selector.get("value_matches")
    if value_matches is not None:
        msg = "typed selectors must use schema fields, not value_matches"
        raise ValueError(msg)


def _apply_legacy_value_matches(
    parts: list[dict[str, Any]],
    value_matches: dict[str, Any],
) -> None:
    for key, expected in value_matches.items():
        applied = False
        for part in parts:
            record_type = part.get("record_type")
            if record_type == "verification_report" and key in {"verdict", "outcome"}:
                if expected in {"pass", "passed"}:
                    part["outcome"] = "passed"
                    applied = True
                    continue
                if expected in {"fail", "failed"}:
                    part["outcome"] = "failed"
                    applied = True
                    continue
            if record_type == "check_result" and key == "status":
                part["status"] = expected
                applied = True
                continue
            if record_type == "gap_classification" and key == "classification":
                part["classification"] = expected
                applied = True
                continue
        if not applied:
            msg = f"unsupported selector value match: {key}"
            raise ValueError(msg)


class RecordSelector(RootModel[AcceptedRecordSelector]):
    """Schema-aware selector wrapper for accepted graph edge records."""

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_shape(cls, value: Any) -> Any:
        return _normalize_legacy_selector(value)

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
    normalized_candidates: set[str] = set()
    for candidate in candidates:
        normalized = _LEGACY_SELECTOR_KIND_MAP.get(candidate)
        if normalized is not None:
            record_type = normalized.get("record_type")
            if isinstance(record_type, str):
                normalized_candidates.add(record_type)
    candidates.update(normalized_candidates)
    output: set[str] = set()
    for candidate in candidates:
        normalized = _LEGACY_SELECTOR_KIND_MAP.get(candidate)
        if normalized is not None:
            record_type = normalized.get("record_type")
            if isinstance(record_type, str):
                output.add(record_type)
            continue
        if candidate in {
            "analysis_summary",
            "artifact_reference",
            "authority_decision",
            "candidate",
            "check_result",
            "completion_decision",
            "decision_record",
            "failure_record",
            "file_state",
            "gap_classification",
            "graph_patch_proposal",
            "requirement_record",
            "routine_snapshot",
            "run_context",
            "verification_report",
        }:
            output.add(candidate)
    return output


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
    verdict = record_payload.get("verdict")
    if verdict in {"passed", "pass"}:
        return "passed"
    if verdict in {"failed", "fail"}:
        return "failed"
    if isinstance(value, dict):
        value_verdict = cast(dict[str, Any], value).get("verdict")
        if value_verdict in {"passed", "pass"}:
            return "passed"
        if value_verdict in {"failed", "fail"}:
            return "failed"
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


class OutputRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["output"]
    producer_node_id: str
    port: str
    schema_: str = Field(alias="schema")
    value: dict[str, Any]


class LegacyOutputRecord(TypedRecordBase):
    """Typed projection wrapper for historical output records with partial shape."""

    record_id: str
    record_kind: str = "output"
    producer_node_id: str
    port: str
    schema_: str | None = Field(default=None, alias="schema")
    value: Any | None = None


class RunContextValue(GraphBaseModel):
    routine_id: str
    routine_name: str
    planner_generation_budget: int | None = None


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


class RoutineSnapshotValue(GraphBaseModel):
    routine_id: str
    name: str
    description: str | None = None
    content_hash: str
    source_path: str | None = None
    source_ref: str | None = None
    step_count: int = Field(ge=0)
    task_count: int = Field(ge=0)
    builder_agent: str | None = None
    verifier_agent: str | None = None
    dynamic_feature: dict[str, Any] | None = None


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


class ArtifactReferenceValue(GraphBaseModel):
    artifact_id: str
    artifact_type: str
    uri: str
    summary: str | None = None
    source_record_ids: list[str] = Field(default_factory=list)


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


def _empty_verification_grades() -> list[dict[str, Any]]:
    return []


class VerificationReportValue(GraphBaseModel):
    outcome: Literal["passed", "failed"]
    grades: list[dict[str, Any]] = Field(default_factory=_empty_verification_grades)
    reason: str | None = None


class VerificationReportRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["verification"]
    producer_node_id: str
    port: Literal["verification_report", "verification_result"] = "verification_report"
    schema_: Literal["VerificationReport"] = Field(default="VerificationReport", alias="schema")
    candidate_id: str
    outcome: Literal["passed", "failed"] | None = None
    verdict: Literal["passed", "failed", "pass", "fail"] | None = None
    value: VerificationReportValue
    evidence: Any | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_explicit_outcome(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(cast(dict[str, Any], value))
        if "status" in payload:
            msg = "VerificationReport uses outcome, not status"
            raise ValueError(msg)
        raw_value = payload.get("value")
        value_payload = dict(cast(dict[str, Any], raw_value)) if isinstance(raw_value, dict) else {}
        if "status" in value_payload:
            msg = "VerificationReport value uses outcome, not status"
            raise ValueError(msg)
        outcome = payload.get("outcome") or value_payload.get("outcome")
        verdict = payload.get("verdict") or value_payload.get("verdict")
        normalized = _normalize_verification_outcome(outcome)
        if normalized is None:
            normalized = _normalize_verification_outcome(verdict)
        if normalized is not None:
            payload["outcome"] = normalized
            value_payload["outcome"] = normalized
        if "grades" in payload and "grades" not in value_payload:
            value_payload["grades"] = payload["grades"]
        if "reason" in payload and "reason" not in value_payload:
            value_payload["reason"] = payload["reason"]
        payload["value"] = value_payload
        return payload

    @model_validator(mode="after")
    def verification_report_fields_are_consistent(self) -> "VerificationReportRecord":
        if self.record_type not in {None, "verification_report"}:
            msg = "record_type must be verification_report"
            raise ValueError(msg)
        if self.outcome != self.value.outcome:
            msg = "outcome must match value.outcome"
            raise ValueError(msg)
        if self.verdict is not None:
            verdict_outcome = _normalize_verification_outcome(self.verdict)
            if verdict_outcome != self.outcome:
                msg = "verdict must match outcome"
                raise ValueError(msg)
        return self


def _normalize_verification_outcome(value: Any) -> Literal["passed", "failed"] | None:
    if value in {"passed", "pass"}:
        return "passed"
    if value in {"failed", "fail"}:
        return "failed"
    return None


def _empty_completion_blockers() -> list[dict[str, Any]]:
    return []


class CompletionDecisionValue(GraphBaseModel):
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


class JoinResultValue(GraphBaseModel):
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


class CheckResultValue(GraphBaseModel):
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
    base_snapshot_id: str
    execution_id: str
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    timeout_seconds: int = Field(gt=0)
    environment_policy: dict[str, Any]


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


def _empty_candidate_changed_paths() -> list[str]:
    return []


def _empty_candidate_requirements() -> list[str]:
    return []


def _empty_candidate_file_state_ids() -> list[str]:
    return []


class CandidateValue(GraphBaseModel):
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


class GapClassificationValue(GraphBaseModel):
    milestone_kind: str
    classification: Literal[
        "corrective_work_required",
        "no_gap",
        "human_decision_required",
        "graph_mutation_required",
    ]
    source: str
    task_region_id: str
    attempt_number: int = Field(ge=0)


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
        if self.record_type != self.port:
            msg = "record_type must match port"
            raise ValueError(msg)
        if self.schema_ != "GapClassification":
            msg = "schema must be GapClassification"
            raise ValueError(msg)
        return self


class DecisionActor(GraphBaseModel):
    kind: str
    id: str | None = None


class DecisionRecordValue(GraphBaseModel):
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


class AuthorityDecisionValue(GraphBaseModel):
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


class AnalysisSummaryValue(GraphBaseModel):
    summary: str
    source_record_ids: list[str]
    lossy: bool
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


class GraphPatchProposalValue(GraphBaseModel):
    patch_id: str
    proposed_by_node_id: str
    base_graph_position: int = Field(ge=0)
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
    base_graph_position: int | None = Field(default=None, ge=0)
    current_graph_position: int = Field(ge=0)
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


class RequirementRecordValue(GraphBaseModel):
    id: str
    text: str
    desc: str | None = None
    priority: Literal["critical", "expected", "nice"] = "critical"
    acceptance_criteria: list[str] = Field(default_factory=_empty_acceptance_criteria)
    source: str | None = None
    version: str | None = None
    supersedes: str | None = None
    must: bool = True


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


class DecisionRequestValue(GraphBaseModel):
    decision_type: str
    options: list[str]
    default_option: str | None = None
    consequence_summary: str

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


class AuthorityRequestValue(GraphBaseModel):
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


class FailureRecordValue(GraphBaseModel):
    failed_node_id: str
    phase: str
    error_class: str
    retryable: bool
    lease_id: str | None = None
    execution_id: str | None = None
    reason: str | None = None


class FailureRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["graph_record"]
    producer_node_id: str
    port: Literal["failure_record"]
    schema_: Literal["FailureRecord"] = Field(alias="schema")
    value: FailureRecordValue

    @model_validator(mode="after")
    def failure_record_fields_are_consistent(self) -> "FailureRecord":
        if self.record_type != "failure_record":
            msg = "record_type must be failure_record"
            raise ValueError(msg)
        return self


class RecoveryPlanValue(GraphBaseModel):
    action: Literal["retry", "supersede", "cancel", "cleanup"]
    responsible_actor: str
    graph_changes: list[dict[str, Any]]
    reason: str | None = None


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
    | LegacyOutputRecord
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


class GitRef(GraphBaseModel):
    commit_sha: str | None = None
    tree_sha: str | None = None
    no_commit_reason: str | None = None
    ref: str | None = None


class FileEntry(GraphBaseModel):
    path: str
    status: str | None = None
    classification: str | None = None
    policy: str | None = None
    matched_rule: str | None = None
    needs_gatekeeper: bool | None = None
    rejected: bool | None = None
    reason: str | None = None


class ExternalArtifactManifest(GraphBaseModel):
    path: str
    hash: str
    origin: str
    retention: str


class ExternalFileEntry(FileEntry):
    manifest: ExternalArtifactManifest


def _empty_file_entries() -> list[FileEntry]:
    return []


def _empty_external_file_entries() -> list[ExternalFileEntry]:
    return []


class FileStateRecord(TypedRecordBase):
    record_id: str
    record_kind: Literal["file_state"]
    snapshot_id: str
    base_snapshot_id: str | None = None
    producer_node_id: str | None = None
    port: str = "file_state"
    schema_: str = Field(default="FileStateRecord", alias="schema")
    git: GitRef | None = None
    tracked: list[FileEntry] = Field(default_factory=_empty_file_entries)
    untracked: list[FileEntry] = Field(default_factory=_empty_file_entries)
    ignored: list[FileEntry] = Field(default_factory=_empty_file_entries)
    external: list[ExternalFileEntry] = Field(default_factory=_empty_external_file_entries)
    classifications: list[FileEntry] = Field(default_factory=_empty_file_entries)
    residue: list[FileEntry] = Field(default_factory=_empty_file_entries)
    rejected_paths: list[FileEntry] = Field(default_factory=_empty_file_entries)
    verdict: Literal["captured", "rejected"] = "captured"
    patch_bundle_id: str | None = None
    tree_snapshot_id: str | None = None
    # Projection-only lineage/safety fields used when a later gatekeeper verdict
    # proves the original snapshot captured a secret. Historical records remain
    # immutable; reducers mark the old record compromised and point at the
    # superseding cleanup record.
    compromised: bool | None = None
    superseded_pending: bool | None = None
    supersedes_record_id: str | None = None
    superseded_by_record_id: str | None = None
    cleanup_id: str | None = None
    compromised_paths: list[str] | None = None


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
    event_type: Literal[
        "callback_accepted",
        "callback_rejected_stale",
        "callback_rejected_conflict",
        "callback_duplicate_returned",
    ]
    node_id: str
    idempotency_key: str
    outcome: str
    payload: dict[str, Any] | None


class PatchOp(GraphBaseModel):
    op: str
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


class PatchEnvelope(GraphBaseModel):
    patch_id: str
    proposed_by_node_id: str
    base_graph_position: int
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
