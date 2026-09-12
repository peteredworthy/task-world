"""Canonical model-authored decision contracts for reliable-plan graphs.

The models in this module own only authored judgment.  Graph identity,
candidate identity, command execution, and lifecycle effects remain owned by
the graph/runtime boundaries that consume these answers in later slices.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    StrictInt,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue

from orchestrator.config import SemanticArtifactSchemaConfig
from orchestrator.graph.boundary_types import validate_callback_json, validate_sha256
from orchestrator.graph.command_bindings import (
    check_command_definition_tool_schema,
    check_command_invocation,
)
from orchestrator.graph.contracts import (
    DEFAULT_NODE_CONTRACTS,
    NodeContract,
    binding_policy_for_edge,
    input_port_contract,
    validate_edge_payload,
    validate_node_payload,
)
from orchestrator.graph.models import (
    CheckResultRecord,
    DecisionAnswerRecord,
    DecisionAnswerValue,
    GapClassificationValue,
    GapClassificationRecord,
    RequirementRecord,
    RoutineSnapshotRecord,
    SemanticArtifactRecord,
    StoredArtifactRef,
    VerificationReportRecord,
    record_selector_matches,
)
from orchestrator.graph.projection_queries import (
    edges_view,
    input_bindings_view,
    leases_view,
    node_payload_view,
    output_record_payloads_view,
    routine_snapshot_dynamic_feature_view,
    semantic_schema_declarations_view,
)
from orchestrator.graph.projections import GraphProjection
from orchestrator.graph.projection_collections import (
    FrozenJsonValue,
    FrozenMap,
    freeze_json,
    thaw_json,
)


DECISION_PLAN_SCHEMA_ID = "orchestrator.reliable-plan.decision-plan"
DECISION_PLAN_SCHEMA_VERSION = 1
BATCH_DECISION_SCHEMA_ID = "orchestrator.reliable-plan.batch-decision"
BATCH_DECISION_SCHEMA_VERSION = 1
CORRECTION_DECISION_SCHEMA_ID = "orchestrator.reliable-plan.correction-decision"
CORRECTION_DECISION_SCHEMA_VERSION = 1
DECISION_COMPILER_CONTRACT_VERSION = 1

RequirementAlias: TypeAlias = Annotated[str, Field(pattern=r"^r[1-9][0-9]*$")]
EvidenceAlias: TypeAlias = Annotated[str, Field(pattern=r"^e[1-9][0-9]*$")]
ObligationAlias: TypeAlias = Annotated[str, Field(pattern=r"^o[1-9][0-9]*$")]
BatchKey: TypeAlias = Annotated[
    str,
    Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
NonEmptyText: TypeAlias = Annotated[str, Field(min_length=1)]


class _DecisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DecisionContractResolutionError(ValueError):
    """Raised when claimed decision authority cannot be resolved exactly."""


def _require_non_whitespace(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must contain non-whitespace text")
    return value


def _require_non_whitespace_items(values: list[str], field_name: str) -> list[str]:
    for index, value in enumerate(values):
        if not value.strip():
            raise ValueError(f"{field_name}[{index}] must contain non-whitespace text")
    return values


def _require_unique(values: list[str], field_name: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


class CheckChoice(_DecisionModel):
    """One executable check choice without controller-owned identities."""

    name: NonEmptyText
    command_binding: Literal["dynamic_feature_hidden_oracle"] | None = None
    command_definition: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def name_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "name")

    @field_validator("command_definition")
    @classmethod
    def explicit_command_is_executable(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and check_command_invocation(value) is None:
            raise ValueError("command_definition requires non-empty argv, cmd, or command")
        return value

    @model_validator(mode="after")
    def command_is_declared(self) -> "CheckChoice":
        if (self.command_binding is None) == (self.command_definition is None):
            raise ValueError("check requires exactly one command binding or command definition")
        return self

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: Any,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        """Expose the existing extensible command syntax from the owning model."""
        schema = handler(core_schema)
        properties = cast(dict[str, dict[str, Any]], schema["properties"])
        binding_schema = properties["command_binding"]
        binding_alternatives = cast(list[dict[str, Any]], binding_schema.pop("anyOf"))
        non_null_bindings = [
            alternative for alternative in binding_alternatives if alternative.get("type") != "null"
        ]
        if len(non_null_bindings) != 1:
            raise RuntimeError("unexpected nullable schema for command_binding")
        properties["command_binding"] = {
            **non_null_bindings[0],
            "title": binding_schema["title"],
        }
        properties["command_definition"] = {
            **check_command_definition_tool_schema(),
            "title": properties["command_definition"]["title"],
        }
        schema["oneOf"] = [
            {"required": ["command_binding"]},
            {"required": ["command_definition"]},
        ]
        return schema


# The old macro-local name remains import-compatible while CheckChoice is now
# the sole owning class.
ReliablePlanCheckDecision = CheckChoice


class Blocker(_DecisionModel):
    reason: NonEmptyText
    needed_information: Annotated[list[NonEmptyText], Field(min_length=1)]
    evidence: list[EvidenceAlias]

    @field_validator("reason")
    @classmethod
    def reason_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "reason")

    @field_validator("needed_information")
    @classmethod
    def needed_information_is_substantive(cls, values: list[str]) -> list[str]:
        return _require_unique(
            _require_non_whitespace_items(values, "needed_information"),
            "needed_information",
        )

    @field_validator("evidence")
    @classmethod
    def evidence_is_unique(cls, values: list[str]) -> list[str]:
        return _require_unique(values, "evidence")


class Batch(_DecisionModel):
    key: BatchKey
    objective: NonEmptyText
    scope: Annotated[list[NonEmptyText], Field(min_length=1)]
    requirements: Annotated[list[RequirementAlias], Field(min_length=1)]
    depends_on: list[BatchKey] = Field(default_factory=list)
    acceptance: Annotated[list[NonEmptyText], Field(min_length=1)]
    checks: Annotated[list[CheckChoice], Field(min_length=1)]
    review_points: list[NonEmptyText] = Field(default_factory=list)

    @field_validator("objective")
    @classmethod
    def objective_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "objective")

    @field_validator("scope", "acceptance", "review_points")
    @classmethod
    def text_lists_are_substantive(cls, values: list[str], info: Any) -> list[str]:
        return _require_unique(
            _require_non_whitespace_items(values, info.field_name),
            info.field_name,
        )

    @field_validator("requirements", "depends_on")
    @classmethod
    def alias_lists_are_unique(cls, values: list[str], info: Any) -> list[str]:
        return _require_unique(values, info.field_name)


class ImplementationPlan(_DecisionModel):
    summary: NonEmptyText
    batches: Annotated[list[Batch], Field(min_length=1)]

    @field_validator("summary")
    @classmethod
    def summary_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "summary")

    @model_validator(mode="after")
    def batch_graph_is_complete_and_acyclic(self) -> "ImplementationPlan":
        keys = [batch.key for batch in self.batches]
        if len(keys) != len(set(keys)):
            raise ValueError("batches must use unique keys")
        known = set(keys)
        for batch in self.batches:
            dangling = [dependency for dependency in batch.depends_on if dependency not in known]
            if dangling:
                raise ValueError(
                    f"batch {batch.key!r} has unknown dependencies: {', '.join(dangling)}"
                )
        dependencies = {batch.key: tuple(batch.depends_on) for batch in self.batches}
        visiting: list[str] = []
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                cycle = " -> ".join([*visiting[visiting.index(key) :], key])
                raise ValueError(f"batch dependency cycle: {cycle}")
            if key in visited:
                return
            visiting.append(key)
            for dependency in dependencies[key]:
                visit(dependency)
            visiting.pop()
            visited.add(key)

        for key in keys:
            visit(key)
        return self


class DiscoveryBrief(_DecisionModel):
    questions: Annotated[list[NonEmptyText], Field(min_length=1)]
    rationale: NonEmptyText
    focus: list[NonEmptyText] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def rationale_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "rationale")

    @field_validator("questions", "focus")
    @classmethod
    def lists_are_substantive(cls, values: list[str], info: Any) -> list[str]:
        return _require_unique(
            _require_non_whitespace_items(values, info.field_name),
            info.field_name,
        )


class BatchRefinement(_DecisionModel):
    batch: BatchKey
    objective: NonEmptyText | None = None
    scope: Annotated[list[NonEmptyText], Field(min_length=1)] | None = None
    acceptance: list[NonEmptyText] = Field(default_factory=list)
    checks: list[CheckChoice] = Field(default_factory=lambda: cast(list[CheckChoice], []))
    review_points: list[NonEmptyText] = Field(default_factory=list)
    depends_on: list[BatchKey] = Field(default_factory=list)

    @field_validator("objective")
    @classmethod
    def optional_objective_is_substantive(cls, value: str | None) -> str | None:
        return None if value is None else _require_non_whitespace(value, "objective")

    @field_validator("scope", "acceptance", "review_points")
    @classmethod
    def text_lists_are_substantive(cls, values: list[str] | None, info: Any) -> list[str] | None:
        if values is None:
            return None
        return _require_unique(
            _require_non_whitespace_items(values, info.field_name),
            info.field_name,
        )

    @field_validator("depends_on")
    @classmethod
    def dependencies_are_unique(cls, values: list[str]) -> list[str]:
        return _require_unique(values, "depends_on")

    @model_validator(mode="after")
    def contains_a_change(self) -> "BatchRefinement":
        if (
            self.objective is None
            and self.scope is None
            and not self.acceptance
            and not self.checks
            and not self.review_points
            and not self.depends_on
        ):
            raise ValueError("batch refinement requires at least one actual change")
        return self


class PlanAmendment(_DecisionModel):
    refinements: list[BatchRefinement] = Field(
        default_factory=lambda: cast(list[BatchRefinement], [])
    )
    additional_batches: list[Batch] = Field(default_factory=lambda: cast(list[Batch], []))

    @model_validator(mode="after")
    def contains_unique_changes(self) -> "PlanAmendment":
        if not self.refinements and not self.additional_batches:
            raise ValueError("plan amendment requires at least one actual change")
        targets = [refinement.batch for refinement in self.refinements]
        if len(targets) != len(set(targets)):
            raise ValueError("plan amendment must not repeat refinement targets")
        additions = [batch.key for batch in self.additional_batches]
        if len(additions) != len(set(additions)):
            raise ValueError("plan amendment must not repeat additional batch keys")
        if set(targets) & set(additions):
            raise ValueError("plan amendment cannot refine and add the same batch key")
        return self


class ProceedBatchDecision(_DecisionModel):
    disposition: Literal["proceed"]
    implementation_notes: str


class RevisePlanBatchDecision(_DecisionModel):
    disposition: Literal["revise_plan"]
    reason: NonEmptyText
    amendment: PlanAmendment

    @field_validator("reason")
    @classmethod
    def reason_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "reason")


class BlockedBatchDecision(_DecisionModel):
    disposition: Literal["blocked"]
    blocker: Blocker


BatchDecision: TypeAlias = Annotated[
    ProceedBatchDecision | RevisePlanBatchDecision | BlockedBatchDecision,
    Field(discriminator="disposition"),
]


class NoGapCorrectionDecision(_DecisionModel):
    disposition: Literal["no_gap"]
    reason: NonEmptyText
    evidence: Annotated[list[EvidenceAlias], Field(min_length=1)]

    @field_validator("reason")
    @classmethod
    def reason_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "reason")

    @field_validator("evidence")
    @classmethod
    def evidence_is_unique(cls, values: list[str]) -> list[str]:
        return _require_unique(values, "evidence")


class CorrectiveWorkDecision(_DecisionModel):
    disposition: Literal["corrective_work"]
    diagnosis: NonEmptyText
    remedy: NonEmptyText
    focus: Annotated[list[NonEmptyText], Field(min_length=1)]
    evidence: Annotated[list[EvidenceAlias], Field(min_length=1)]

    @field_validator("diagnosis", "remedy")
    @classmethod
    def text_is_substantive(cls, value: str, info: Any) -> str:
        return _require_non_whitespace(value, info.field_name)

    @field_validator("focus")
    @classmethod
    def focus_is_substantive(cls, values: list[str]) -> list[str]:
        return _require_unique(_require_non_whitespace_items(values, "focus"), "focus")

    @field_validator("evidence")
    @classmethod
    def evidence_is_unique(cls, values: list[str]) -> list[str]:
        return _require_unique(values, "evidence")


class PlanRevisionCorrectionDecision(_DecisionModel):
    disposition: Literal["plan_revision"]
    reason: NonEmptyText
    amendment: PlanAmendment

    @field_validator("reason")
    @classmethod
    def reason_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "reason")


class EscalateCorrectionDecision(_DecisionModel):
    disposition: Literal["escalate"]
    blocker: Blocker


CorrectionDecision: TypeAlias = Annotated[
    NoGapCorrectionDecision
    | CorrectiveWorkDecision
    | PlanRevisionCorrectionDecision
    | EscalateCorrectionDecision,
    Field(discriminator="disposition"),
]


class Finding(_DecisionModel):
    obligation: ObligationAlias
    grade: Literal["A", "B", "C", "D", "F"]
    reason: NonEmptyText
    evidence: list[EvidenceAlias]

    @field_validator("reason")
    @classmethod
    def reason_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "reason")

    @field_validator("evidence")
    @classmethod
    def evidence_is_unique(cls, values: list[str]) -> list[str]:
        return _require_unique(values, "evidence")


class VerificationDecision(_DecisionModel):
    findings: Annotated[list[Finding], Field(min_length=1)]

    @model_validator(mode="after")
    def obligations_are_unique(self) -> "VerificationDecision":
        aliases = [finding.obligation for finding in self.findings]
        if len(aliases) != len(set(aliases)):
            raise ValueError("findings must contain each obligation at most once")
        return self


class ReadyWorkResult(_DecisionModel):
    status: Literal["ready"]
    summary: NonEmptyText

    @field_validator("summary")
    @classmethod
    def summary_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "summary")


class BlockedWorkResult(_DecisionModel):
    status: Literal["blocked"]
    blocker: Blocker


WorkResult: TypeAlias = Annotated[
    ReadyWorkResult | BlockedWorkResult,
    Field(discriminator="status"),
]


def reliable_plan_check_decision_tool_schema() -> dict[str, Any]:
    """Return the schema generated by the single executable-check owner."""
    schema = CheckChoice.model_json_schema(mode="validation")
    schema.pop("title", None)
    return schema


def decision_plan_schema() -> dict[str, Any]:
    """Generate the canonical decision-v1 implementation-plan content schema."""
    return ImplementationPlan.model_json_schema(mode="validation")


def decision_plan_schema_sha256() -> str:
    encoded = json.dumps(
        decision_plan_schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def decision_plan_declaration() -> SemanticArtifactSchemaConfig:
    """Build the exact generated declaration frozen into decision-v1 snapshots."""
    return SemanticArtifactSchemaConfig(
        schema_id=DECISION_PLAN_SCHEMA_ID,
        version=DECISION_PLAN_SCHEMA_VERSION,
        semantic_role="implementation_plan",
        json_schema=decision_plan_schema(),
    )


DISCOVERY_BRIEF_SCHEMA_ID = "orchestrator.reliable-plan.discovery-brief"
DISCOVERY_BRIEF_SCHEMA_VERSION = 1


def batch_decision_schema() -> dict[str, Any]:
    """Return the schema generated from the sole BatchDecision owner."""
    return TypeAdapter(BatchDecision).json_schema(mode="validation")


def batch_decision_schema_sha256() -> str:
    encoded = json.dumps(
        batch_decision_schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def discovery_brief_schema() -> dict[str, Any]:
    """Return the schema generated from the sole DiscoveryBrief owner."""
    return DiscoveryBrief.model_json_schema(mode="validation")


def discovery_brief_schema_sha256() -> str:
    encoded = json.dumps(
        discovery_brief_schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def correction_decision_schema() -> dict[str, Any]:
    """Return the schema generated from the canonical correction answer owner."""
    return TypeAdapter(CorrectionDecision).json_schema(mode="validation")


def correction_decision_schema_sha256() -> str:
    encoded = json.dumps(
        correction_decision_schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def decision_answer_schema(
    family: Literal[
        "discovery_brief", "implementation_plan", "batch_decision", "correction_decision"
    ],
) -> tuple[str, int, str, dict[str, Any]]:
    """Resolve the activated answer contract from the graph-owned family."""
    if family == "discovery_brief":
        return (
            DISCOVERY_BRIEF_SCHEMA_ID,
            DISCOVERY_BRIEF_SCHEMA_VERSION,
            discovery_brief_schema_sha256(),
            discovery_brief_schema(),
        )
    if family == "implementation_plan":
        return (
            DECISION_PLAN_SCHEMA_ID,
            DECISION_PLAN_SCHEMA_VERSION,
            decision_plan_schema_sha256(),
            decision_plan_schema(),
        )
    if family == "correction_decision":
        return (
            CORRECTION_DECISION_SCHEMA_ID,
            CORRECTION_DECISION_SCHEMA_VERSION,
            correction_decision_schema_sha256(),
            correction_decision_schema(),
        )
    return (
        BATCH_DECISION_SCHEMA_ID,
        BATCH_DECISION_SCHEMA_VERSION,
        batch_decision_schema_sha256(),
        batch_decision_schema(),
    )


class ResolvedDiscoveryBriefContext(_DecisionModel):
    """Exact protected facts for one initial reliable-plan judgment."""

    node_id: str
    routine_snapshot_record_id: str
    scope_choices: tuple[str, ...]
    requirement_aliases: FrozenMap[str, str]
    requirement_alias_order: tuple[str, ...]
    requirement_record_ids: tuple[str, ...]
    requirement_texts: tuple[str, ...]
    bound_inputs: tuple[DecisionBoundInput, ...]
    feature_spec_path: str | None = None
    feature_spec_content: str | None = None
    hidden_oracle_available: bool = False

    @field_validator("requirement_aliases", mode="before")
    @classmethod
    def freeze_initial_requirement_aliases(cls, value: object) -> FrozenMap[str, str]:
        if isinstance(value, FrozenMap):
            return cast(FrozenMap[str, str], value)
        if not isinstance(value, dict):
            raise ValueError("requirement_aliases must be an object")
        return FrozenMap(cast(dict[str, str], value))

    @field_validator(
        "scope_choices",
        "requirement_alias_order",
        "requirement_record_ids",
        "requirement_texts",
        "bound_inputs",
        mode="before",
    )
    @classmethod
    def freeze_initial_context_sequences(cls, value: object) -> object:
        return tuple(cast(list[object], value)) if isinstance(value, list) else value

    def protected_question_context(self) -> dict[str, Any]:
        evidence: dict[str, Any] = {
            "requirements": [
                {"alias": alias, "text": text}
                for alias, text in zip(
                    self.requirement_alias_order, self.requirement_texts, strict=True
                )
            ],
            "check_policy": {
                "hidden_oracle_available": self.hidden_oracle_available,
                "final_dynamic_acceptance_is_runtime_owned": True,
            },
        }
        if self.feature_spec_path is not None:
            evidence["feature_spec_path"] = self.feature_spec_path
        if self.feature_spec_content is not None:
            evidence["feature_spec_content"] = self.feature_spec_content
        return {
            "question": (
                "What unresolved discovery questions and constraints must be answered "
                "before producing the implementation plan?"
            ),
            "answer_family": "discovery_brief",
            "scope_choices": list(self.scope_choices),
            "bound_evidence": evidence,
            "source_references": {
                "routine_snapshot_record_id": self.routine_snapshot_record_id,
                "requirement_record_ids": list(self.requirement_record_ids),
            },
        }


class ResolvedBatchDecisionContext(_DecisionModel):
    """Exact protected facts for one successor judgment."""

    node_id: str
    routine_snapshot_record_id: str
    plan_record_id: str
    plan_verification_record_id: str
    horizon_verification_record_id: str
    accepted_plan: ImplementationPlan
    selected_batch: Batch
    requirement_aliases: FrozenMap[str, str]
    plan_requirement_aliases: FrozenMap[str, str]
    plan_requirement_record_ids: FrozenMap[str, str]
    plan_requirement_alias_order: tuple[str, ...]
    ordered_plan_requirement_record_ids: tuple[str, ...]
    evidence_aliases: FrozenMap[str, str]
    requirement_record_ids: tuple[str, ...]
    remaining_horizons: StrictInt = Field(ge=1)
    planning_horizon: StrictInt = Field(ge=1)
    maximum_batches: StrictInt = Field(ge=1)
    bound_inputs: tuple[DecisionBoundInput, ...]
    hidden_oracle_available: bool = False

    @field_validator(
        "requirement_aliases",
        "plan_requirement_aliases",
        "plan_requirement_record_ids",
        "evidence_aliases",
        mode="before",
    )
    @classmethod
    def freeze_requirement_aliases(cls, value: object) -> FrozenMap[str, str]:
        if isinstance(value, FrozenMap):
            return cast(FrozenMap[str, str], value)
        if not isinstance(value, dict):
            raise ValueError("requirement_aliases must be an object")
        return FrozenMap(cast(dict[str, str], value))

    @field_validator(
        "requirement_record_ids",
        "plan_requirement_alias_order",
        "ordered_plan_requirement_record_ids",
        "bound_inputs",
        mode="before",
    )
    @classmethod
    def freeze_context_sequences(cls, value: object) -> object:
        return tuple(cast(list[object], value)) if isinstance(value, list) else value

    def protected_question_context(self) -> dict[str, Any]:
        return {
            "question": "How should the selected verified implementation batch proceed?",
            "answer_family": "batch_decision",
            "selected_batch": self.selected_batch.model_dump(mode="json"),
            "requirement_aliases": dict(self.requirement_aliases.object_items()),
            "evidence_aliases": dict(self.evidence_aliases.object_items()),
            "remaining_horizons": self.remaining_horizons,
            "planning_horizon": self.planning_horizon,
            "maximum_batches": self.maximum_batches,
            "available_dispositions": ["proceed", "revise_plan", "blocked"],
            "check_policy": {
                "selected_batch_checks": [
                    check.model_dump(mode="json", exclude_none=True)
                    for check in self.selected_batch.checks
                ],
                "hidden_oracle_available": self.hidden_oracle_available,
                "final_dynamic_acceptance_is_runtime_owned": True,
            },
            "source_references": {
                "routine_snapshot_record_id": self.routine_snapshot_record_id,
                "plan_record_id": self.plan_record_id,
                "plan_verification_record_id": self.plan_verification_record_id,
                "horizon_verification_record_id": self.horizon_verification_record_id,
                "requirement_record_ids": list(self.requirement_record_ids),
            },
        }


class ResolvedCorrectionDecisionContext(_DecisionModel):
    """Exact failed-candidate evidence and accepted baseline for a gap answer."""

    node_id: str
    routine_snapshot_record_id: str
    plan_record_id: str
    plan_verification_record_id: str
    failed_verification_record_id: str
    failed_check_record_ids: tuple[str, ...]
    task_region_id: str
    accepted_plan: ImplementationPlan
    selected_batch: Batch
    scope: str
    planning_horizon: StrictInt = Field(ge=1)
    remaining_horizons: StrictInt = Field(ge=1)
    maximum_batches: StrictInt = Field(ge=1)
    plan_requirement_aliases: FrozenMap[str, str]
    plan_requirement_record_ids: FrozenMap[str, str]
    plan_requirement_alias_order: tuple[str, ...]
    ordered_plan_requirement_record_ids: tuple[str, ...]
    requirement_aliases: FrozenMap[str, str]
    requirement_record_ids: tuple[str, ...]
    evidence_aliases: FrozenMap[str, str]
    bound_inputs: tuple[DecisionBoundInput, ...]
    hidden_oracle_available: bool = False

    @field_validator(
        "plan_requirement_aliases",
        "plan_requirement_record_ids",
        "requirement_aliases",
        "evidence_aliases",
        mode="before",
    )
    @classmethod
    def freeze_correction_maps(cls, value: object) -> FrozenMap[str, str]:
        if isinstance(value, FrozenMap):
            return cast(FrozenMap[str, str], value)
        if not isinstance(value, dict):
            raise ValueError("correction context maps must be objects")
        return FrozenMap(cast(dict[str, str], value))

    @field_validator(
        "failed_check_record_ids",
        "plan_requirement_alias_order",
        "ordered_plan_requirement_record_ids",
        "requirement_record_ids",
        "bound_inputs",
        mode="before",
    )
    @classmethod
    def freeze_correction_sequences(cls, value: object) -> object:
        return tuple(cast(list[object], value)) if isinstance(value, list) else value

    def protected_question_context(self) -> dict[str, Any]:
        return {
            "question": (
                "Does the bounded failed candidate need no action, corrective work, "
                "a conservative plan revision, or human escalation?"
            ),
            "answer_family": "correction_decision",
            "scope": self.scope,
            "task_region_id": self.task_region_id,
            "selected_batch": self.selected_batch.model_dump(mode="json"),
            "requirement_aliases": dict(self.requirement_aliases.object_items()),
            "evidence_aliases": dict(self.evidence_aliases.object_items()),
            "accepted_baseline": {
                "plan_record_id": self.plan_record_id,
                "plan_verification_record_id": self.plan_verification_record_id,
                "failed_verification_record_id": self.failed_verification_record_id,
                "failed_check_record_ids": list(self.failed_check_record_ids),
            },
            "planning_horizon": self.planning_horizon,
            "remaining_horizons": self.remaining_horizons,
            "maximum_batches": self.maximum_batches,
            "available_dispositions": [
                "no_gap",
                "corrective_work",
                "plan_revision",
                "escalate",
            ],
            "check_policy": {
                "selected_batch_checks": [
                    check.model_dump(mode="json", exclude_none=True)
                    for check in self.selected_batch.checks
                ],
                "hidden_oracle_available": self.hidden_oracle_available,
                "final_dynamic_acceptance_is_runtime_owned": True,
            },
        }


class ResolvedImplementationPlanContext(_DecisionModel):
    """Exact frozen authority for a read-only discovery plan answer."""

    node_id: str
    routine_snapshot_record_id: str
    declaration_record_id: str
    plan_verifier_node_id: str
    successor_node_id: str
    requirement_aliases: FrozenMap[str, str]
    requirement_alias_order: tuple[str, ...]
    requirement_record_ids: tuple[str, ...]
    requirement_texts: tuple[str, ...]
    bound_inputs: tuple[DecisionBoundInput, ...]
    maximum_batches: StrictInt = Field(ge=1)
    hidden_oracle_available: bool = False

    @field_validator("requirement_aliases", mode="before")
    @classmethod
    def freeze_plan_requirement_aliases(cls, value: object) -> FrozenMap[str, str]:
        if isinstance(value, FrozenMap):
            return cast(FrozenMap[str, str], value)
        if not isinstance(value, dict):
            raise ValueError("requirement_aliases must be an object")
        return FrozenMap(cast(dict[str, str], value))

    @field_validator(
        "requirement_alias_order",
        "requirement_record_ids",
        "requirement_texts",
        "bound_inputs",
        mode="before",
    )
    @classmethod
    def freeze_plan_context_sequences(cls, value: object) -> object:
        return tuple(cast(list[object], value)) if isinstance(value, list) else value

    def validate_answer(self, answer: Mapping[str, Any]) -> ImplementationPlan:
        plan = ImplementationPlan.model_validate(dict(answer))
        available = set(self.requirement_aliases)
        selected = {alias for batch in plan.batches for alias in batch.requirements}
        unknown = sorted(selected - available)
        if unknown:
            raise ValueError(f"implementation plan contains unknown requirement aliases: {unknown}")
        missing = sorted(available - selected)
        if missing:
            raise ValueError(f"implementation plan omits bound requirement aliases: {missing}")
        if len(plan.batches) > self.maximum_batches:
            raise ValueError(
                "implementation plan exceeds frozen planning horizon: "
                f"{len(plan.batches)} > {self.maximum_batches}"
            )
        if not self.hidden_oracle_available and any(
            check.command_binding == "dynamic_feature_hidden_oracle"
            for batch in plan.batches
            for check in batch.checks
        ):
            raise ValueError("implementation plan selected an unavailable check binding")
        return plan

    def protected_question_context(self) -> dict[str, Any]:
        return {
            "question": "What exact implementation plan should be independently verified?",
            "answer_family": "implementation_plan",
            "requirements": [
                {"alias": alias, "text": text}
                for (alias, _requirement_id), text in zip(
                    self.requirement_aliases.object_items(),
                    self.requirement_texts,
                    strict=True,
                )
            ],
            "plan_contract": {
                "schema_id": DECISION_PLAN_SCHEMA_ID,
                "schema_version": DECISION_PLAN_SCHEMA_VERSION,
                "schema_sha256": decision_plan_schema_sha256(),
                "maximum_batches": self.maximum_batches,
            },
            "check_policy": {
                "available_bindings": (
                    ["dynamic_feature_hidden_oracle"] if self.hidden_oracle_available else []
                ),
                "explicit_command_definitions_allowed": True,
                "final_dynamic_acceptance_is_runtime_owned": True,
            },
            "source_references": {
                "routine_snapshot_record_id": self.routine_snapshot_record_id,
                "declaration_record_id": self.declaration_record_id,
                "requirement_record_ids": list(self.requirement_record_ids),
                "plan_verifier_node_id": self.plan_verifier_node_id,
                "successor_node_id": self.successor_node_id,
            },
        }


class DecisionCompilation(_DecisionModel):
    patch_id: str
    base_graph_position: StrictInt = Field(ge=0)
    ops: tuple[dict[str, Any], ...]
    decision_record: DecisionAnswerRecord
    gap_records: tuple[GapClassificationRecord, ...] = ()
    semantic_records: tuple[SemanticArtifactRecord, ...] = ()
    bound_inputs: tuple[DecisionBoundInput, ...]
    read_set: tuple[str, ...]
    disposition: Literal[
        "discovery_brief",
        "proceed",
        "revise_plan",
        "blocked",
        "no_gap",
        "corrective_work",
        "plan_revision",
        "escalate",
    ] = "proceed"
    completion_state: Literal["completed", "failed"] = "completed"
    failure_reason: str | None = None

    @field_validator(
        "ops", "gap_records", "semantic_records", "bound_inputs", "read_set", mode="before"
    )
    @classmethod
    def freeze_compilation_sequences(cls, value: object) -> object:
        return tuple(cast(list[object], value)) if isinstance(value, list) else value

    @property
    def output_records(
        self,
    ) -> tuple[DecisionAnswerRecord | GapClassificationRecord | SemanticArtifactRecord, ...]:
        return (self.decision_record, *self.gap_records, *self.semantic_records)


class ImplementationPlanCompilation(_DecisionModel):
    patch_id: str
    ops: tuple[dict[str, Any], ...]
    semantic_record: SemanticArtifactRecord
    bound_inputs: tuple[DecisionBoundInput, ...]
    read_set: tuple[str, ...]

    @field_validator("ops", "bound_inputs", "read_set", mode="before")
    @classmethod
    def freeze_plan_compilation_sequences(cls, value: object) -> object:
        return tuple(cast(list[object], value)) if isinstance(value, list) else value


def _bound_input(
    projection: GraphProjection,
    *,
    node_id: str,
    port: str,
    record_id: str,
) -> DecisionBoundInput:
    binding = input_bindings_view(projection).get(node_id, {}).get(port)
    record = output_record_payloads_view(projection).get(record_id)
    positions = binding.record_bound_positions if binding is not None else None
    if (
        binding is None
        or record is None
        or record_id not in binding.record_ids
        or positions is None
        or record_id not in positions
        or record.graph_position is None
    ):
        raise DecisionContractResolutionError(
            f"decision input {port!r} is not bound to exact durable record {record_id!r}"
        )
    return DecisionBoundInput(
        port=port,
        record_id=record_id,
        record_type=cast(str, record.record_type),
        schema=record.schema_,
        schema_version=record.schema_version,
        record_position=record.graph_position,
        bound_at_position=binding.bound_at_position,
    )


def _bound_requirement_rows(
    projection: GraphProjection,
    node_id: str,
) -> list[tuple[str, RequirementRecord, str]]:
    bindings = input_bindings_view(projection).get(node_id, {})
    records = output_record_payloads_view(projection)

    def requirement_port_order(item: tuple[str, object]) -> tuple[int, str]:
        port = item[0]
        suffix = port.removeprefix("requirement_")
        return (int(suffix), port) if suffix.isdigit() else (2**31 - 1, port)

    rows: list[tuple[str, RequirementRecord, str]] = []
    for port, binding in sorted(bindings.items(), key=requirement_port_order):
        if not port.startswith("requirement_"):
            continue
        if len(binding.record_ids) != 1:
            raise DecisionContractResolutionError(
                f"decision requirement input {port!r} must bind one exact record"
            )
        record_id = binding.record_ids[0]
        record = records.get(record_id)
        if not isinstance(record, RequirementRecord):
            raise DecisionContractResolutionError("bound requirement has invalid record type")
        rows.append((port, record, record_id))
    return rows


def resolve_discovery_brief_context(
    projection: GraphProjection,
    node_id: str,
) -> ResolvedDiscoveryBriefContext:
    """Resolve initial scope and evidence only from exact frozen inputs."""
    applicability = resolve_decision_applicability(projection, node_id)
    if applicability is None or applicability.family != "discovery_brief":
        raise DecisionContractResolutionError("node is not a decision-v1 initial planner")
    node = node_payload_view(projection, node_id) or {}
    if not isinstance(node.get("reliable_plan_skeleton_id"), str):
        raise DecisionContractResolutionError(
            "initial decision requires frozen reliable-plan authority"
        )
    rows = _bound_requirement_rows(projection, node_id)
    if not rows:
        raise DecisionContractResolutionError(
            "initial decision requires at least one exact bound requirement"
        )
    aliases = {
        f"r{index}": record.value.id for index, (_port, record, _record_id) in enumerate(rows, 1)
    }
    records = output_record_payloads_view(projection)
    snapshot = records.get(applicability.routine_snapshot_record_id)
    if not isinstance(snapshot, RoutineSnapshotRecord):
        raise DecisionContractResolutionError("initial decision snapshot is unavailable")
    raw_dynamic = snapshot.value.dynamic_feature
    dynamic = (
        thaw_json(raw_dynamic)
        if isinstance(raw_dynamic, FrozenMap)
        else dict(raw_dynamic)
        if isinstance(raw_dynamic, dict)
        else None
    )
    if not isinstance(dynamic, dict):
        raise DecisionContractResolutionError(
            "initial decision requires frozen dynamic-feature inputs"
        )
    feature_spec_path = dynamic.get("feature_spec_path")
    feature_spec_content = dynamic.get("feature_spec_content")
    path = (
        feature_spec_path.strip()
        if isinstance(feature_spec_path, str) and feature_spec_path.strip()
        else None
    )
    content = (
        feature_spec_content.strip()
        if isinstance(feature_spec_content, str) and feature_spec_content.strip()
        else None
    )
    if path is None and content is None:
        raise DecisionContractResolutionError(
            "initial decision requires a supplied feature specification"
        )
    scope_choices = (path or "embedded feature specification",)
    bound_inputs = [
        _bound_input(
            projection,
            node_id=node_id,
            port="routine_snapshot",
            record_id=applicability.routine_snapshot_record_id,
        ),
        *[
            _bound_input(projection, node_id=node_id, port=port, record_id=record_id)
            for port, _record, record_id in rows
        ],
    ]
    return ResolvedDiscoveryBriefContext(
        node_id=node_id,
        routine_snapshot_record_id=applicability.routine_snapshot_record_id,
        scope_choices=scope_choices,
        requirement_aliases=FrozenMap(aliases),
        requirement_alias_order=tuple(aliases),
        requirement_record_ids=tuple(row[2] for row in rows),
        requirement_texts=tuple(f"{row[1].value.id}: {row[1].value.text}" for row in rows),
        bound_inputs=tuple(bound_inputs),
        feature_spec_path=path,
        feature_spec_content=content,
        hidden_oracle_available=bool(dynamic.get("hidden_oracle_command")),
    )


def resolve_implementation_plan_context(
    projection: GraphProjection,
    node_id: str,
) -> ResolvedImplementationPlanContext:
    """Resolve the built-in discovery plan and its independent verifier handoff."""
    applicability = resolve_decision_applicability(projection, node_id)
    if applicability is None or applicability.family != "implementation_plan":
        raise DecisionContractResolutionError("node is not a decision-v1 discovery worker")
    node = node_payload_view(projection, node_id) or {}
    if (
        node.get("access_mode") != "read_only"
        or node.get("effect_contract") != "read_only_semantic"
        or node.get("semantic_schema_id") != DECISION_PLAN_SCHEMA_ID
        or node.get("semantic_schema_version") != DECISION_PLAN_SCHEMA_VERSION
    ):
        raise DecisionContractResolutionError(
            "decision discovery requires the exact read-only built-in plan contract"
        )
    declarations = semantic_schema_declarations_view(projection)
    declaration = declarations.get((DECISION_PLAN_SCHEMA_ID, DECISION_PLAN_SCHEMA_VERSION))
    if declaration is None or thaw_json(declaration.value.json_schema) != decision_plan_schema():
        raise DecisionContractResolutionError(
            "decision discovery built-in plan declaration is unavailable or changed"
        )
    rows = _bound_requirement_rows(projection, node_id)
    if not rows:
        raise DecisionContractResolutionError(
            "decision discovery requires at least one exact bound requirement"
        )
    requirement_ids = tuple(row[2] for row in rows)
    aliases = {
        f"r{index}": record.value.id for index, (_port, record, _record_id) in enumerate(rows, 1)
    }

    plan_edges = [
        edge
        for edge in edges_view(projection).values()
        if edge.from_node_id == node_id
        and edge.from_port == "semantic_artifact"
        and edge.to_port == "semantic_artifact"
        and edge.required
    ]
    if len(plan_edges) != 1:
        raise DecisionContractResolutionError(
            "decision discovery plan must feed one independent verifier"
        )
    verifier_edges = [
        edge
        for edge in plan_edges
        if (target := node_payload_view(projection, edge.to_node_id)) is not None
        and target.get("kind") == "verifier"
        and target.get("role") == "verifier"
        and target.get("semantic_stage") == "plan_verification"
    ]
    if len(verifier_edges) != 1:
        raise DecisionContractResolutionError(
            "decision discovery requires one independent verifier"
        )
    verifier_id = verifier_edges[0].to_node_id
    successor_id = node.get("decision_successor_node_id")
    if (
        not isinstance(successor_id, str)
        or not successor_id
        or node_payload_view(projection, successor_id) is not None
    ):
        raise DecisionContractResolutionError(
            "decision discovery successor identity is unavailable or already materialized"
        )
    verifier = node_payload_view(projection, verifier_id) or {}
    if (
        verifier.get("semantic_schema_id") != DECISION_PLAN_SCHEMA_ID
        or verifier.get("semantic_schema_version") != DECISION_PLAN_SCHEMA_VERSION
        or tuple(row[2] for row in _bound_requirement_rows(projection, verifier_id))
        != requirement_ids
    ):
        raise DecisionContractResolutionError(
            "independent plan verifier does not bind the exact schema and requirements"
        )
    dynamic = routine_snapshot_dynamic_feature_view(projection) or {}
    maximum_batches = dynamic.get("patch_budget")
    if (
        not isinstance(maximum_batches, int)
        or isinstance(maximum_batches, bool)
        or maximum_batches < 1
    ):
        raise DecisionContractResolutionError("decision discovery has no frozen horizon budget")
    bound_inputs = [
        _bound_input(
            projection,
            node_id=node_id,
            port="routine_snapshot",
            record_id=applicability.routine_snapshot_record_id,
        ),
        *[
            _bound_input(projection, node_id=node_id, port=port, record_id=record_id)
            for port, _record, record_id in rows
        ],
    ]
    return ResolvedImplementationPlanContext(
        node_id=node_id,
        routine_snapshot_record_id=applicability.routine_snapshot_record_id,
        declaration_record_id=declaration.record_id,
        plan_verifier_node_id=verifier_id,
        successor_node_id=successor_id,
        requirement_aliases=FrozenMap(aliases),
        requirement_alias_order=tuple(aliases),
        requirement_record_ids=requirement_ids,
        requirement_texts=tuple(f"{row[1].value.id}: {row[1].value.text}" for row in rows),
        bound_inputs=tuple(bound_inputs),
        maximum_batches=maximum_batches,
        hidden_oracle_available=bool(dynamic.get("hidden_oracle_command")),
    )


def _plan_requirement_authority(
    plan_record: SemanticArtifactRecord,
    records: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    """Recover the plan's frozen global aliases and their exact source records."""
    requirement_ids = list(plan_record.value.requirement_ids)
    if not requirement_ids or len(requirement_ids) != len(set(requirement_ids)):
        raise DecisionContractResolutionError(
            "bound decision plan requirement authority is malformed"
        )
    source_by_requirement: dict[str, str] = {}
    for record_id in plan_record.value.source_record_ids:
        record = records.get(record_id)
        if not isinstance(record, RequirementRecord):
            continue
        requirement_id = record.value.id
        if requirement_id in source_by_requirement:
            raise DecisionContractResolutionError(
                "bound decision plan requirement authority is ambiguous"
            )
        source_by_requirement[requirement_id] = record_id
    missing = [item for item in requirement_ids if item not in source_by_requirement]
    if missing:
        raise DecisionContractResolutionError(
            "bound decision plan requirement authority is incomplete"
        )
    aliases = {
        f"r{index}": requirement_id for index, requirement_id in enumerate(requirement_ids, start=1)
    }
    return aliases, {
        alias: source_by_requirement[requirement_id] for alias, requirement_id in aliases.items()
    }


def resolve_batch_decision_context(
    projection: GraphProjection,
    node_id: str,
) -> ResolvedBatchDecisionContext:
    """Resolve the selected batch only from exact accepted successor inputs."""
    applicability = resolve_decision_applicability(projection, node_id)
    if applicability is None or applicability.family != "batch_decision":
        raise DecisionContractResolutionError("node is not a decision-v1 successor")
    node = node_payload_view(projection, node_id) or {}
    bindings = input_bindings_view(projection).get(node_id, {})
    horizon_verifier_binding = bindings.get("verification_report")
    plan_verifier_binding = bindings.get("plan_verification_report")
    plan_binding = bindings.get("semantic_artifact")
    if horizon_verifier_binding is None or len(horizon_verifier_binding.record_ids) != 1:
        raise DecisionContractResolutionError(
            "decision successor requires one exact horizon verification record"
        )
    if plan_binding is None or len(plan_binding.record_ids) != 1:
        raise DecisionContractResolutionError("decision successor requires one exact accepted plan")
    plan_id = plan_binding.record_ids[0]
    records = output_record_payloads_view(projection)
    plan_record = records.get(plan_id)
    if not isinstance(plan_record, SemanticArtifactRecord):
        raise DecisionContractResolutionError("bound plan is not a semantic artifact")
    if (
        plan_record.value.authority_status != "accepted"
        or plan_record.value.schema_id != DECISION_PLAN_SCHEMA_ID
        or plan_record.value.schema_version != DECISION_PLAN_SCHEMA_VERSION
        or plan_record.value.semantic_role != "implementation_plan"
        or plan_record.value.content is None
    ):
        raise DecisionContractResolutionError("bound plan is not the accepted decision plan")
    raw_plan = (
        thaw_json(plan_record.value.content)
        if isinstance(plan_record.value.content, FrozenMap)
        else plan_record.value.content
    )
    if not isinstance(raw_plan, dict):
        raise DecisionContractResolutionError("bound decision plan content is malformed")
    try:
        plan = ImplementationPlan.model_validate(raw_plan)
    except ValueError as exc:
        raise DecisionContractResolutionError("bound decision plan content is invalid") from exc
    horizon = node.get("planning_horizon")
    remaining = node.get("reliable_plan_remaining_horizons")
    if (
        not isinstance(horizon, int)
        or isinstance(horizon, bool)
        or horizon < 1
        or horizon > len(plan.batches)
        or not isinstance(remaining, int)
        or isinstance(remaining, bool)
        or remaining != len(plan.batches) - horizon + 1
    ):
        raise DecisionContractResolutionError("successor horizon does not match the accepted plan")
    selected = plan.batches[horizon - 1]
    if node.get("scope") != selected.key:
        raise DecisionContractResolutionError("successor scope does not match selected plan batch")

    horizon_verifier_id = horizon_verifier_binding.record_ids[0]
    horizon_verifier = records.get(horizon_verifier_id)
    if not isinstance(horizon_verifier, VerificationReportRecord) or horizon_verifier.outcome != (
        "passed"
    ):
        raise DecisionContractResolutionError("bound horizon verifier is not passing")
    if plan_verifier_binding is None:
        if horizon != 1:
            raise DecisionContractResolutionError(
                "decision successor requires one exact independent plan verification record"
            )
        plan_verifier_id = horizon_verifier_id
        plan_verifier_port = "verification_report"
    elif len(plan_verifier_binding.record_ids) != 1:
        raise DecisionContractResolutionError(
            "decision successor requires one exact independent plan verification record"
        )
    else:
        plan_verifier_id = plan_verifier_binding.record_ids[0]
        plan_verifier_port = "plan_verification_report"
    plan_verifier = records.get(plan_verifier_id)
    plan_verifier_node = (
        node_payload_view(projection, plan_verifier.producer_node_id)
        if isinstance(plan_verifier, VerificationReportRecord)
        else None
    )
    if (
        not isinstance(plan_verifier, VerificationReportRecord)
        or plan_verifier.outcome != "passed"
        or plan_id not in plan_verifier.evaluated_record_ids
        or plan_verifier_node is None
        or plan_verifier_node.get("semantic_stage") != "plan_verification"
    ):
        raise DecisionContractResolutionError("bound independent plan verifier is unavailable")
    if horizon == 1:
        if horizon_verifier_id != plan_verifier_id:
            raise DecisionContractResolutionError(
                "initial successor horizon must be gated by its exact plan verification"
            )
    else:
        horizon_verifier_node = (
            node_payload_view(projection, horizon_verifier.producer_node_id) or {}
        )
        prior_batch = plan.batches[horizon - 2]
        if (
            horizon_verifier_node.get("semantic_stage")
            not in {"effectful_batch", "corrective_work"}
            or horizon_verifier_node.get("planning_horizon") != horizon - 1
            or horizon_verifier_node.get("declared_batch_id") != prior_batch.key
        ):
            raise DecisionContractResolutionError(
                "successor horizon is not gated by the exact prior batch verification"
            )

    plan_aliases, plan_requirement_records = _plan_requirement_authority(
        plan_record,
        records,
    )
    unknown_selected_aliases = [
        alias for alias in selected.requirements if alias not in plan_aliases
    ]
    if unknown_selected_aliases:
        raise DecisionContractResolutionError("selected batch contains unknown requirement aliases")
    requirement_rows = _bound_requirement_rows(projection, node_id)
    expected_record_ids = tuple(plan_requirement_records[alias] for alias in selected.requirements)
    if tuple(row[2] for row in requirement_rows) != expected_record_ids:
        raise DecisionContractResolutionError(
            "selected batch requirements do not match exact supplied aliases"
        )
    aliases = {alias: plan_aliases[alias] for alias in selected.requirements}
    bound = [
        _bound_input(
            projection,
            node_id=node_id,
            port="routine_snapshot",
            record_id=applicability.routine_snapshot_record_id,
        ),
        _bound_input(projection, node_id=node_id, port="semantic_artifact", record_id=plan_id),
        _bound_input(
            projection,
            node_id=node_id,
            port="verification_report",
            record_id=horizon_verifier_id,
        ),
        *(
            [
                _bound_input(
                    projection,
                    node_id=node_id,
                    port=plan_verifier_port,
                    record_id=plan_verifier_id,
                )
            ]
            if plan_verifier_port != "verification_report"
            else []
        ),
        *[
            _bound_input(projection, node_id=node_id, port=port, record_id=record_id)
            for port, _record, record_id in requirement_rows
        ],
    ]
    dynamic = routine_snapshot_dynamic_feature_view(projection) or {}
    patch_budget = dynamic.get("patch_budget")
    if (
        not isinstance(patch_budget, int)
        or isinstance(patch_budget, bool)
        or patch_budget < 1
        or len(plan.batches) > patch_budget
    ):
        raise DecisionContractResolutionError(
            "successor plan exceeds or lacks the frozen dynamic-feature patch budget"
        )
    evidence_ids = sorted({plan_id, plan_verifier_id, horizon_verifier_id})
    return ResolvedBatchDecisionContext(
        node_id=node_id,
        routine_snapshot_record_id=applicability.routine_snapshot_record_id,
        plan_record_id=plan_id,
        plan_verification_record_id=plan_verifier_id,
        horizon_verification_record_id=horizon_verifier_id,
        accepted_plan=plan,
        selected_batch=selected,
        requirement_aliases=FrozenMap(aliases),
        plan_requirement_aliases=FrozenMap(plan_aliases),
        plan_requirement_record_ids=FrozenMap(plan_requirement_records),
        plan_requirement_alias_order=tuple(plan_aliases),
        ordered_plan_requirement_record_ids=tuple(
            plan_requirement_records[alias] for alias in plan_aliases
        ),
        evidence_aliases=FrozenMap(
            {f"e{index}": record_id for index, record_id in enumerate(evidence_ids, 1)}
        ),
        requirement_record_ids=tuple(row[2] for row in requirement_rows),
        remaining_horizons=remaining,
        planning_horizon=horizon,
        maximum_batches=patch_budget,
        bound_inputs=tuple(bound),
        hidden_oracle_available=bool(dynamic.get("hidden_oracle_command")),
    )


def resolve_correction_decision_context(
    projection: GraphProjection,
    node_id: str,
) -> ResolvedCorrectionDecisionContext:
    """Resolve one gap answer from exact failed evidence and the accepted plan."""
    applicability = resolve_decision_applicability(projection, node_id)
    if applicability is None or applicability.family != "correction_decision":
        raise DecisionContractResolutionError("node is not a decision-v1 gap planner")
    node = node_payload_view(projection, node_id) or {}
    bindings = input_bindings_view(projection).get(node_id, {})
    records = output_record_payloads_view(projection)
    snapshot_id = applicability.routine_snapshot_record_id
    snapshot = records.get(snapshot_id)
    if not isinstance(snapshot, RoutineSnapshotRecord):
        raise DecisionContractResolutionError("correction decision snapshot is unavailable")

    bound_rows: list[tuple[str, str]] = []
    evidence_ports = {
        "verification_evidence",
        "verification_report",
        "check_result",
        "candidate",
        "file_state",
        "graph_status_summary",
    }
    candidate_bound_ports = (
        {"verification_evidence"} if "verification_evidence" in bindings else evidence_ports
    )
    for port, binding in sorted(bindings.items()):
        if port not in candidate_bound_ports:
            continue
        if len(binding.record_ids) != 1:
            raise DecisionContractResolutionError(
                f"correction evidence input {port!r} must bind one exact record"
            )
        bound_rows.append((port, binding.record_ids[0]))
    if not bound_rows:
        raise DecisionContractResolutionError("correction decision requires bound evidence")
    ordered_evidence_ids = [record_id for _port, record_id in bound_rows]
    evidence_ids = set(ordered_evidence_ids)
    for record_id in tuple(ordered_evidence_ids):
        record = records.get(record_id)
        if isinstance(record, VerificationReportRecord):
            for evaluated_id in record.evaluated_record_ids:
                if evaluated_id not in evidence_ids:
                    ordered_evidence_ids.append(evaluated_id)
                    evidence_ids.add(evaluated_id)
        if isinstance(record, CheckResultRecord):
            for related_id in [
                *record.value.evaluated_record_ids,
                *record.value.verification_report_record_ids,
            ]:
                if related_id not in evidence_ids:
                    ordered_evidence_ids.append(related_id)
                    evidence_ids.add(related_id)
    evidence_records = [
        records[record_id] for record_id in ordered_evidence_ids if record_id in records
    ]
    reports = [
        record for record in evidence_records if isinstance(record, VerificationReportRecord)
    ]
    checks = [record for record in evidence_records if isinstance(record, CheckResultRecord)]
    failed_reports = [record for record in reports if record.outcome == "failed"]
    failed_checks = [record for record in checks if record.value.status in {"failed", "timeout"}]
    if len(failed_reports) > 1:
        raise DecisionContractResolutionError("correction evidence has multiple failure anchors")
    anchor_report = failed_reports[0] if failed_reports else (reports[0] if reports else None)
    if anchor_report is None:
        raise DecisionContractResolutionError(
            "correction evidence requires one verification report"
        )
    anchor_node = node_payload_view(projection, anchor_report.producer_node_id) or {}
    scope = node.get("scope")
    if not isinstance(scope, str) or not scope:
        scope = anchor_node.get("declared_batch_id")
    if not isinstance(scope, str) or not scope:
        raise DecisionContractResolutionError("correction evidence has no declared batch scope")

    plan_candidates = [
        record
        for record in records.values()
        if isinstance(record, SemanticArtifactRecord)
        and record.value.authority_status == "accepted"
        and record.value.schema_id == DECISION_PLAN_SCHEMA_ID
        and record.value.schema_version == DECISION_PLAN_SCHEMA_VERSION
        and record.value.semantic_role == "implementation_plan"
    ]
    plan_binding = bindings.get("semantic_artifact")
    if plan_binding is not None and len(plan_binding.record_ids) == 1:
        bound_plan = records.get(plan_binding.record_ids[0])
        plan_candidates = [bound_plan] if isinstance(bound_plan, SemanticArtifactRecord) else []
    if len(plan_candidates) != 1:
        raise DecisionContractResolutionError(
            "correction decision requires one accepted baseline plan"
        )
    plan_record = plan_candidates[0]
    raw_plan = (
        thaw_json(plan_record.value.content)
        if isinstance(plan_record.value.content, FrozenMap)
        else plan_record.value.content
    )
    if not isinstance(raw_plan, dict):
        raise DecisionContractResolutionError("accepted correction baseline plan is malformed")
    try:
        plan = ImplementationPlan.model_validate(raw_plan)
    except ValueError as exc:
        raise DecisionContractResolutionError(
            "accepted correction baseline plan is invalid"
        ) from exc
    selected = next((batch for batch in plan.batches if batch.key == scope), None)
    if selected is None:
        raise DecisionContractResolutionError(
            "correction scope is outside the accepted baseline plan"
        )
    horizon = anchor_node.get("planning_horizon")
    if anchor_node.get("semantic_stage") == "final_audit":
        horizon = len(plan.batches)
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
        raise DecisionContractResolutionError("correction evidence has no valid planning horizon")
    if horizon > len(plan.batches) or plan.batches[horizon - 1].key != scope:
        raise DecisionContractResolutionError("correction evidence horizon does not match scope")

    plan_verifiers = [
        record
        for record in records.values()
        if isinstance(record, VerificationReportRecord)
        and record.outcome == "passed"
        and plan_record.record_id in record.evaluated_record_ids
        and (node_payload_view(projection, record.producer_node_id) or {}).get("semantic_stage")
        == "plan_verification"
    ]
    if len(plan_verifiers) != 1:
        raise DecisionContractResolutionError(
            "correction decision requires one accepted plan verification"
        )
    plan_verifier = plan_verifiers[0]
    plan_aliases, plan_requirement_records = _plan_requirement_authority(plan_record, records)
    selected_aliases = {alias: plan_aliases[alias] for alias in selected.requirements}
    dynamic = routine_snapshot_dynamic_feature_view(projection) or {}
    budget = dynamic.get("patch_budget")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < len(plan.batches):
        raise DecisionContractResolutionError("correction plan exceeds frozen patch budget")
    actual_bound = [
        _bound_input(projection, node_id=node_id, port="routine_snapshot", record_id=snapshot_id)
    ]
    actual_bound.extend(
        _bound_input(projection, node_id=node_id, port=port, record_id=record_id)
        for port, record_id in bound_rows
    )
    evidence_aliases = {
        f"e{index}": record_id for index, record_id in enumerate(ordered_evidence_ids, 1)
    }
    return ResolvedCorrectionDecisionContext(
        node_id=node_id,
        routine_snapshot_record_id=snapshot_id,
        plan_record_id=plan_record.record_id,
        plan_verification_record_id=plan_verifier.record_id,
        failed_verification_record_id=anchor_report.record_id,
        failed_check_record_ids=tuple(record.record_id for record in failed_checks),
        task_region_id=str(node.get("task_region_id") or node_id),
        accepted_plan=plan,
        selected_batch=selected,
        scope=scope,
        planning_horizon=horizon,
        remaining_horizons=len(plan.batches) - horizon + 1,
        maximum_batches=budget,
        plan_requirement_aliases=FrozenMap(plan_aliases),
        plan_requirement_record_ids=FrozenMap(plan_requirement_records),
        plan_requirement_alias_order=tuple(plan_aliases),
        ordered_plan_requirement_record_ids=tuple(plan_requirement_records.values()),
        requirement_aliases=FrozenMap(selected_aliases),
        requirement_record_ids=tuple(
            plan_requirement_records[alias] for alias in selected.requirements
        ),
        evidence_aliases=FrozenMap(evidence_aliases),
        bound_inputs=tuple(actual_bound),
        hidden_oracle_available=bool(dynamic.get("hidden_oracle_command")),
    )


def compile_batch_decision(
    projection: GraphProjection,
    *,
    node_id: str,
    decision_request_id: str,
    base_graph_position: int,
    answer: Mapping[str, Any],
) -> DecisionCompilation:
    """Purely derive one successor patch and canonical judgment record."""
    resolved = resolve_batch_decision_context(projection, node_id)
    parsed = cast(
        BatchDecision,
        TypeAdapter(BatchDecision).validate_python(dict(answer)),
    )
    canonical_answer = parsed.model_dump(mode="json")
    answer_hash = canonical_decision_answer_hash(canonical_answer)
    digest = hashlib.sha256(
        "\x00".join((decision_request_id, node_id, answer_hash)).encode("utf-8")
    ).hexdigest()
    patch_id = f"decision-patch-{digest[:24]}"
    operation_key = f"decision-{digest[:24]}"
    aliases = cast(dict[str, str], dict(resolved.requirement_aliases.object_items()))
    records = output_record_payloads_view(projection)
    horizon_verification = records.get(resolved.horizon_verification_record_id)
    if not isinstance(horizon_verification, VerificationReportRecord):
        raise DecisionContractResolutionError("bound horizon verification became unavailable")
    semantic_records: tuple[SemanticArtifactRecord, ...] = ()
    completion_state: Literal["completed", "failed"] = "completed"
    failure_reason: str | None = None
    if isinstance(parsed, ProceedBatchDecision):
        batch = resolved.selected_batch
        requirement_ids = [aliases[alias] for alias in batch.requirements]
        next_batch = (
            resolved.accepted_plan.batches[resolved.planning_horizon]
            if resolved.remaining_horizons > 1
            else None
        )
        plan_aliases = cast(dict[str, str], dict(resolved.plan_requirement_aliases.object_items()))
        plan_requirement_records = cast(
            dict[str, str], dict(resolved.plan_requirement_record_ids.object_items())
        )
        from orchestrator.graph.macros import compile_reliable_plan_region_ops

        ops = compile_reliable_plan_region_ops(
            {
                "operation_key": operation_key,
                "scope": batch.key,
                "objective": batch.objective,
                "requirement_ids": requirement_ids,
                "dependencies": list(batch.depends_on),
                "acceptance": list(batch.acceptance),
                "checks": [
                    item.model_dump(mode="json", exclude_none=True) for item in batch.checks
                ],
                "rubric": list(batch.review_points) or list(batch.acceptance),
            },
            projection=projection,
            proposed_by_node_id=node_id,
            patch_id=patch_id,
            trusted_plan_record_id=resolved.plan_record_id,
            trusted_plan_verification_record_id=resolved.plan_verification_record_id,
            trusted_requirement_record_ids=resolved.requirement_record_ids,
            implementation_notes=parsed.implementation_notes,
            next_scope=next_batch.key if next_batch is not None else None,
            next_requirement_ids=(
                [plan_aliases[alias] for alias in next_batch.requirements]
                if next_batch is not None
                else None
            ),
            trusted_next_requirement_record_ids=(
                tuple(plan_requirement_records[alias] for alias in next_batch.requirements)
                if next_batch is not None
                else None
            ),
        )
    elif isinstance(parsed, RevisePlanBatchDecision):
        prospective = _apply_plan_amendment(resolved, parsed.amendment)
        amendment_record_id = f"semantic-artifact-amendment-{digest[:24]}"
        current_node = node_payload_view(projection, node_id) or {}
        plan_aliases = cast(dict[str, str], dict(resolved.plan_requirement_aliases.object_items()))
        plan_requirement_records = cast(
            dict[str, str], dict(resolved.plan_requirement_record_ids.object_items())
        )
        ordered_aliases = resolved.plan_requirement_alias_order
        semantic_record = SemanticArtifactRecord.model_validate(
            {
                "record_id": amendment_record_id,
                "record_kind": "graph_record",
                "record_type": "semantic_artifact",
                "schema_version": DECISION_PLAN_SCHEMA_VERSION,
                "producer_node_id": node_id,
                "port": "semantic_artifact",
                "schema": "SemanticArtifact",
                "value": {
                    "semantic_role": "implementation_plan",
                    "schema_id": DECISION_PLAN_SCHEMA_ID,
                    "schema_version": DECISION_PLAN_SCHEMA_VERSION,
                    "content": prospective.model_dump(mode="json", exclude_none=True),
                    "provenance": {
                        "source": "controller_decision_compiler",
                        "decision_request_id": decision_request_id,
                        "reason": parsed.reason,
                    },
                    "source_record_ids": [
                        resolved.plan_record_id,
                        resolved.plan_verification_record_id,
                        *resolved.ordered_plan_requirement_record_ids,
                    ],
                    "requirement_ids": [plan_aliases[alias] for alias in ordered_aliases],
                    "task_region_id": str(current_node.get("task_region_id") or node_id),
                    "validation_status": "validated",
                    "authority_status": "accepted",
                    "supersedes_record_id": resolved.plan_record_id,
                },
            }
        )
        from orchestrator.graph.macros import compile_reliable_plan_amendment_ops

        ops = compile_reliable_plan_amendment_ops(
            projection=projection,
            proposed_by_node_id=node_id,
            patch_id=patch_id,
            operation_key=operation_key,
            amendment_record_id=amendment_record_id,
            prospective_plan=prospective.model_dump(mode="json", exclude_none=True),
            reason=parsed.reason,
            planning_horizon=resolved.planning_horizon,
            remaining_horizons=len(prospective.batches) - resolved.planning_horizon + 1,
            requirement_ids=[plan_aliases[alias] for alias in ordered_aliases],
            trusted_requirement_record_ids=resolved.ordered_plan_requirement_record_ids,
            successor_requirement_ids=[
                plan_aliases[alias]
                for alias in prospective.batches[resolved.planning_horizon - 1].requirements
            ],
            trusted_successor_requirement_record_ids=tuple(
                plan_requirement_records[alias]
                for alias in prospective.batches[resolved.planning_horizon - 1].requirements
            ),
            horizon_verification_source_node_id=horizon_verification.producer_node_id,
        )
        semantic_records = (semantic_record,)
    else:
        unknown_evidence = sorted(set(parsed.blocker.evidence) - set(resolved.evidence_aliases))
        if unknown_evidence:
            raise ValueError(f"blocker contains unknown evidence alias: {unknown_evidence}")
        evidence = cast(dict[str, str], dict(resolved.evidence_aliases.object_items()))
        evidence_ids = [evidence[alias] for alias in parsed.blocker.evidence]
        from orchestrator.graph.macros import compile_reliable_plan_blocker_ops

        ops = compile_reliable_plan_blocker_ops(
            projection=projection,
            proposed_by_node_id=node_id,
            gate_id=f"human-gate-{digest[:24]}",
            reason=parsed.blocker.reason,
            needed_information=list(parsed.blocker.needed_information),
            evidence_record_ids=evidence_ids,
        )
        completion_state = "failed"
        needed = "; ".join(parsed.blocker.needed_information)
        failure_reason = (
            f"successor decision blocked: {parsed.blocker.reason} Needed information: {needed}."
        )[:1000]
    record_id = f"decision-answer-{digest[:24]}"
    record = DecisionAnswerRecord(
        record_id=record_id,
        record_kind="graph_record",
        record_type="decision_answer",
        producer_node_id=node_id,
        producer_port="decision",
        port="decision",
        schema="DecisionAnswer",
        schema_version=BATCH_DECISION_SCHEMA_VERSION,
        value=DecisionAnswerValue(
            interaction_contract="decision-v1",
            family="batch_decision",
            decision_request_id=decision_request_id,
            answer_schema_id=BATCH_DECISION_SCHEMA_ID,
            answer_schema_version=BATCH_DECISION_SCHEMA_VERSION,
            answer_schema_sha256=batch_decision_schema_sha256(),
            compiler_contract_version=DECISION_COMPILER_CONTRACT_VERSION,
            answer_sha256=answer_hash,
            answer=canonical_answer,
            consequence_patch_id=patch_id,
            bound_input_record_ids=[item.record_id for item in resolved.bound_inputs],
        ),
    )
    read_authority = [node_id, *(item.record_id for item in resolved.bound_inputs)]
    for record_id in resolved.requirement_record_ids:
        requirement = records.get(record_id)
        if not isinstance(requirement, RequirementRecord):
            raise DecisionContractResolutionError(
                f"bound requirement record {record_id!r} became unavailable"
            )
        read_authority.extend(
            value
            for value in (requirement.value.id, requirement.value.version)
            if value is not None
        )
    for record_id in (
        resolved.routine_snapshot_record_id,
        resolved.plan_record_id,
        resolved.plan_verification_record_id,
        resolved.horizon_verification_record_id,
    ):
        bound_record = records.get(record_id)
        if bound_record is not None and bound_record.producer_node_id is not None:
            read_authority.append(bound_record.producer_node_id)
    return DecisionCompilation(
        patch_id=patch_id,
        base_graph_position=base_graph_position,
        ops=tuple(ops),
        decision_record=record,
        semantic_records=semantic_records,
        bound_inputs=resolved.bound_inputs,
        read_set=tuple(dict.fromkeys(read_authority)),
        disposition=parsed.disposition,
        completion_state=completion_state,
        failure_reason=failure_reason,
    )


def _correction_gap_record(
    *,
    node_id: str,
    resolved: ResolvedCorrectionDecisionContext,
    record_id: str,
    classification: Literal[
        "corrective_work_required",
        "no_gap",
        "human_decision_required",
        "graph_mutation_required",
    ],
) -> GapClassificationRecord:
    return GapClassificationRecord(
        record_id=record_id,
        record_kind="output",
        record_type="classified_gap",
        producer_node_id=node_id,
        producer_port="classified_gap",
        port="classified_gap",
        schema="GapClassification",
        schema_version=1,
        provenance={
            "source": "decision-v1",
            "evaluated_record_ids": [
                resolved.failed_verification_record_id,
                *resolved.failed_check_record_ids,
            ],
        },
        value=GapClassificationValue(
            milestone_kind=resolved.scope,
            classification=classification,
            source="decision-v1",
            task_region_id=resolved.task_region_id,
            attempt_number=1,
        ),
    )


def compile_correction_decision(
    projection: GraphProjection,
    *,
    node_id: str,
    decision_request_id: str,
    base_graph_position: int,
    answer: Mapping[str, Any],
) -> DecisionCompilation:
    """Compile a canonical gap answer into bounded topology and durable records."""
    resolved = resolve_correction_decision_context(projection, node_id)
    read_set = [
        node_id,
        *(item.record_id for item in resolved.bound_inputs),
        resolved.plan_record_id,
        resolved.plan_verification_record_id,
        resolved.failed_verification_record_id,
        *resolved.failed_check_record_ids,
        *resolved.ordered_plan_requirement_record_ids,
        *(resolved.evidence_aliases[alias] for alias in sorted(resolved.evidence_aliases)),
    ]
    records = output_record_payloads_view(projection)
    current_position = max(
        (records[record_id].graph_position or 0 for record_id in read_set if record_id in records),
        default=0,
    )
    if base_graph_position < current_position:
        raise ValueError("correction decision baseline is stale")
    for record_id in resolved.ordered_plan_requirement_record_ids:
        requirement = records.get(record_id)
        if not isinstance(requirement, RequirementRecord):
            raise DecisionContractResolutionError(
                f"bound requirement record {record_id!r} became unavailable"
            )
        read_set.extend(
            value
            for value in (requirement.value.id, requirement.value.version)
            if value is not None
        )
    read_set.extend(
        record.producer_node_id
        for record_id in tuple(read_set)
        if (record := records.get(record_id)) is not None and record.producer_node_id is not None
    )
    parsed = cast(
        CorrectionDecision,
        TypeAdapter(CorrectionDecision).validate_python(dict(answer)),
    )
    canonical_answer = parsed.model_dump(mode="json")
    answer_hash = canonical_decision_answer_hash(canonical_answer)
    digest = hashlib.sha256(
        "\x00".join((decision_request_id, node_id, answer_hash)).encode("utf-8")
    ).hexdigest()
    patch_id = f"decision-patch-{digest[:24]}"
    operation_key = f"decision-{digest[:24]}"
    evidence = cast(dict[str, str], dict(resolved.evidence_aliases.object_items()))
    semantic_records: tuple[SemanticArtifactRecord, ...] = ()
    if isinstance(parsed, NoGapCorrectionDecision):
        unknown = sorted(set(parsed.evidence) - set(evidence))
        if unknown:
            raise ValueError(f"no_gap contains unknown evidence alias: {unknown}")
        if resolved.failed_check_record_ids or (
            output_record_payloads_view(projection).get(resolved.failed_verification_record_id)
            and cast(
                VerificationReportRecord,
                output_record_payloads_view(projection)[resolved.failed_verification_record_id],
            ).outcome
            == "failed"
        ):
            raise ValueError("no_gap cannot dismiss a failed mandatory check or verification")
        classification = "no_gap"
        ops: list[dict[str, Any]] = []
        completion_state: Literal["completed", "failed"] = "completed"
        failure_reason = None
    elif isinstance(parsed, CorrectiveWorkDecision):
        unknown = sorted(set(parsed.evidence) - set(evidence))
        if unknown:
            raise ValueError(f"corrective work contains unknown evidence alias: {unknown}")
        if not set(parsed.focus).issubset(set(resolved.selected_batch.scope)):
            raise ValueError("corrective work focus exceeds the failed batch scope")
        classification = "corrective_work_required"
        ops = []
        completion_state = "completed"
        failure_reason = None
    elif isinstance(parsed, PlanRevisionCorrectionDecision):
        classification = "graph_mutation_required"
        ops = []
        completion_state = "completed"
        failure_reason = None
    else:
        unknown = sorted(set(parsed.blocker.evidence) - set(evidence))
        if unknown:
            raise ValueError(f"blocker contains unknown evidence alias: {unknown}")
        classification = "human_decision_required"
        ops = []
        completion_state = "failed"
        needed = "; ".join(parsed.blocker.needed_information)
        failure_reason = (
            f"gap decision escalated: {parsed.blocker.reason} Needed information: {needed}."
        )[:1000]

    leases = [
        lease
        for lease in leases_view(projection).values()
        if lease.node_id == node_id and lease.state == "active" and lease.execution_id
    ]
    gap_record_id = (
        f"classified-gap-{leases[0].execution_id}"
        if len(leases) == 1
        else f"classified-gap-{digest[:24]}"
    )
    gap_record = _correction_gap_record(
        node_id=node_id,
        resolved=resolved,
        record_id=gap_record_id,
        classification=classification,
    )
    if isinstance(parsed, CorrectiveWorkDecision):
        from orchestrator.graph.macros import compile_reliable_plan_correction_ops

        batch = resolved.selected_batch
        aliases = cast(dict[str, str], dict(resolved.requirement_aliases.object_items()))
        ops = compile_reliable_plan_correction_ops(
            projection=projection,
            proposed_by_node_id=node_id,
            patch_id=patch_id,
            operation_key=operation_key,
            scope=resolved.scope,
            objective=(
                f"{batch.objective} Diagnosis: {parsed.diagnosis} "
                f"Remedy: {parsed.remedy} Focus: {', '.join(parsed.focus)}"
            ),
            acceptance=list(batch.acceptance),
            checks=[check.model_dump(mode="json", exclude_none=True) for check in batch.checks],
            rubric=list(batch.review_points) or list(batch.acceptance),
            requirement_ids=[aliases[alias] for alias in batch.requirements],
            requirement_sources=[
                cast(
                    RequirementRecord, output_record_payloads_view(projection)[record_id]
                ).producer_node_id
                for record_id in (
                    cast(dict[str, str], dict(resolved.plan_requirement_record_ids.object_items()))[
                        alias
                    ]
                    for alias in batch.requirements
                )
            ],
            requirement_bindings=tuple(
                (
                    record_id,
                    cast(
                        RequirementRecord, output_record_payloads_view(projection)[record_id]
                    ).producer_node_id,
                )
                for record_id in (
                    cast(dict[str, str], dict(resolved.plan_requirement_record_ids.object_items()))[
                        alias
                    ]
                    for alias in batch.requirements
                )
            ),
            classification_record_id=gap_record_id,
        )
    elif isinstance(parsed, PlanRevisionCorrectionDecision):
        prospective = _apply_plan_amendment(resolved, parsed.amendment)
        amendment_record_id = f"semantic-artifact-amendment-{digest[:24]}"
        plan_aliases = cast(dict[str, str], dict(resolved.plan_requirement_aliases.object_items()))
        plan_requirement_records = cast(
            dict[str, str], dict(resolved.plan_requirement_record_ids.object_items())
        )
        semantic_record = SemanticArtifactRecord.model_validate(
            {
                "record_id": amendment_record_id,
                "record_kind": "graph_record",
                "record_type": "semantic_artifact",
                "schema_version": DECISION_PLAN_SCHEMA_VERSION,
                "producer_node_id": node_id,
                "port": "semantic_artifact",
                "schema": "SemanticArtifact",
                "value": {
                    "semantic_role": "implementation_plan",
                    "schema_id": DECISION_PLAN_SCHEMA_ID,
                    "schema_version": DECISION_PLAN_SCHEMA_VERSION,
                    "content": prospective.model_dump(mode="json", exclude_none=True),
                    "provenance": {
                        "source": "controller_correction_compiler",
                        "reason": parsed.reason,
                    },
                    "source_record_ids": [
                        resolved.plan_record_id,
                        resolved.plan_verification_record_id,
                        *resolved.ordered_plan_requirement_record_ids,
                        *resolved.failed_check_record_ids,
                        resolved.failed_verification_record_id,
                    ],
                    "requirement_ids": [
                        plan_aliases[alias] for alias in resolved.plan_requirement_alias_order
                    ],
                    "task_region_id": node_id,
                    "validation_status": "validated",
                    "authority_status": "accepted",
                    "supersedes_record_id": resolved.plan_record_id,
                },
            }
        )
        from orchestrator.graph.macros import compile_reliable_plan_amendment_ops

        selected = prospective.batches[resolved.planning_horizon - 1]
        ops = compile_reliable_plan_amendment_ops(
            projection=projection,
            proposed_by_node_id=node_id,
            patch_id=patch_id,
            operation_key=operation_key,
            amendment_record_id=amendment_record_id,
            prospective_plan=prospective.model_dump(mode="json", exclude_none=True),
            reason=parsed.reason,
            planning_horizon=resolved.planning_horizon,
            remaining_horizons=len(prospective.batches) - resolved.planning_horizon + 1,
            requirement_ids=[
                plan_aliases[alias] for alias in resolved.plan_requirement_alias_order
            ],
            trusted_requirement_record_ids=resolved.ordered_plan_requirement_record_ids,
            successor_requirement_ids=[plan_aliases[alias] for alias in selected.requirements],
            trusted_successor_requirement_record_ids=tuple(
                plan_requirement_records[alias] for alias in selected.requirements
            ),
            horizon_verification_source_node_id=(
                cast(
                    VerificationReportRecord,
                    output_record_payloads_view(projection)[resolved.plan_verification_record_id],
                ).producer_node_id
            ),
        )
        semantic_records = (semantic_record,)
    elif isinstance(parsed, EscalateCorrectionDecision):
        from orchestrator.graph.macros import compile_reliable_plan_blocker_ops

        ops = compile_reliable_plan_blocker_ops(
            projection=projection,
            proposed_by_node_id=node_id,
            gate_id=f"human-gate-{digest[:24]}",
            reason=parsed.blocker.reason,
            needed_information=list(parsed.blocker.needed_information),
            evidence_record_ids=[evidence[alias] for alias in parsed.blocker.evidence],
        )
    record = DecisionAnswerRecord(
        record_id=f"decision-answer-{digest[:24]}",
        record_kind="graph_record",
        record_type="decision_answer",
        producer_node_id=node_id,
        producer_port="decision",
        port="decision",
        schema="DecisionAnswer",
        schema_version=CORRECTION_DECISION_SCHEMA_VERSION,
        value=DecisionAnswerValue(
            interaction_contract="decision-v1",
            family="correction_decision",
            decision_request_id=decision_request_id,
            answer_schema_id=CORRECTION_DECISION_SCHEMA_ID,
            answer_schema_version=CORRECTION_DECISION_SCHEMA_VERSION,
            answer_schema_sha256=correction_decision_schema_sha256(),
            compiler_contract_version=DECISION_COMPILER_CONTRACT_VERSION,
            answer_sha256=answer_hash,
            answer=canonical_answer,
            consequence_patch_id=patch_id,
            bound_input_record_ids=[item.record_id for item in resolved.bound_inputs],
        ),
    )
    return DecisionCompilation(
        patch_id=patch_id,
        base_graph_position=base_graph_position,
        ops=tuple(ops),
        decision_record=record,
        gap_records=(gap_record,),
        semantic_records=semantic_records,
        bound_inputs=resolved.bound_inputs,
        read_set=tuple(dict.fromkeys(read_set)),
        disposition=cast(Any, parsed.disposition),
        completion_state=completion_state,
        failure_reason=failure_reason,
    )


def _apply_plan_amendment(
    resolved: ResolvedBatchDecisionContext | ResolvedCorrectionDecisionContext,
    amendment: PlanAmendment,
) -> ImplementationPlan:
    """Construct the full conservative prospective plan from one narrow proposal."""
    original = resolved.accepted_plan
    batches = list(original.batches)
    key_indexes = {batch.key: index for index, batch in enumerate(batches)}
    authorized_scope = {path for batch in batches for path in batch.scope}
    aliases = set(resolved.plan_requirement_aliases)

    if len(batches) + len(amendment.additional_batches) > resolved.maximum_batches:
        raise ValueError("plan amendment exceeds frozen dynamic-feature patch budget")

    def append_only(existing: list[Any], additions: list[Any], field_name: str) -> list[Any]:
        repeated = [item for item in additions if item in existing]
        if repeated:
            raise ValueError(f"plan amendment {field_name} must contain additions only")
        return [*existing, *additions]

    for refinement in amendment.refinements:
        index = key_indexes.get(refinement.batch)
        if index is None:
            raise ValueError(f"plan amendment targets unknown batch {refinement.batch!r}")
        if index < resolved.planning_horizon - 1:
            raise ValueError("plan amendment cannot refine the accepted prefix")
        current = batches[index]
        if refinement.scope is not None and not set(refinement.scope).issubset(current.scope):
            raise ValueError("plan amendment refinement scope exceeds previously authorized scope")
        refined_scope = (
            [path for path in current.scope if path in refinement.scope]
            if refinement.scope is not None
            else current.scope
        )
        batches[index] = current.model_copy(
            update={
                "objective": refinement.objective or current.objective,
                "scope": refined_scope,
                "acceptance": append_only(
                    list(current.acceptance), refinement.acceptance, "acceptance"
                ),
                "checks": append_only(list(current.checks), refinement.checks, "checks"),
                "review_points": append_only(
                    list(current.review_points), refinement.review_points, "review points"
                ),
                "depends_on": append_only(
                    list(current.depends_on), refinement.depends_on, "dependencies"
                ),
            }
        )

    for additional in amendment.additional_batches:
        if additional.key in key_indexes:
            raise ValueError(f"plan amendment cannot replace existing batch {additional.key!r}")
        unknown_requirements = sorted(set(additional.requirements) - aliases)
        if unknown_requirements:
            raise ValueError(
                f"plan amendment contains unknown requirement aliases: {unknown_requirements}"
            )
        if not set(additional.scope).issubset(authorized_scope):
            raise ValueError("plan amendment additional batch exceeds authorized scope")
        key_indexes[additional.key] = len(batches)
        batches.append(additional)

    if not resolved.hidden_oracle_available and any(
        check.command_binding == "dynamic_feature_hidden_oracle"
        for batch in batches
        for check in batch.checks
    ):
        raise ValueError("plan amendment selected an unavailable check binding")

    prospective = ImplementationPlan(summary=original.summary, batches=batches)
    if prospective == original:
        raise ValueError("plan amendment does not change the accepted plan")
    final_indexes = {batch.key: index for index, batch in enumerate(prospective.batches)}
    for index, batch in enumerate(prospective.batches):
        forward = [
            dependency for dependency in batch.depends_on if final_indexes[dependency] >= index
        ]
        if forward:
            raise ValueError(
                f"plan amendment dependencies must precede batch {batch.key!r}: {forward}"
            )
    return prospective


def compile_discovery_brief(
    projection: GraphProjection,
    *,
    node_id: str,
    decision_request_id: str,
    base_graph_position: int,
    answer: Mapping[str, Any],
) -> DecisionCompilation:
    """Purely derive the initial discovery and plan-verification topology."""
    resolved = resolve_discovery_brief_context(projection, node_id)
    parsed = DiscoveryBrief.model_validate(dict(answer))
    unknown_focus = sorted(set(parsed.focus) - set(resolved.scope_choices))
    if unknown_focus:
        raise ValueError(
            "discovery brief focus contains choices outside supplied scope: "
            + ", ".join(unknown_focus)
        )
    canonical_answer = parsed.model_dump(mode="json")
    answer_hash = canonical_decision_answer_hash(canonical_answer)
    digest = hashlib.sha256(
        "\x00".join((decision_request_id, node_id, answer_hash)).encode("utf-8")
    ).hexdigest()
    patch_id = f"decision-patch-{digest[:24]}"
    operation_key = f"decision-{digest[:24]}"
    aliases = cast(dict[str, str], dict(resolved.requirement_aliases.object_items()))
    requirement_ids = [aliases[alias] for alias in resolved.requirement_alias_order]
    focus = list(parsed.focus) or list(resolved.scope_choices)
    objective = (
        "Produce the implementation plan after resolving the accepted discovery brief "
        f"for {', '.join(focus)}. Rationale: {parsed.rationale}"
    )
    acceptance = [
        f"The implementation plan resolves discovery question: {question}"
        for question in parsed.questions
    ]
    rubric = [
        "The plan is grounded in every exact bound requirement and supplied scope.",
        *acceptance,
    ]
    from orchestrator.graph.macros import compile_reliable_plan_region_ops

    ops = compile_reliable_plan_region_ops(
        {
            "operation_key": operation_key,
            "scope": resolved.scope_choices[0],
            "objective": objective,
            "requirement_ids": requirement_ids,
            "dependencies": [],
            "acceptance": acceptance,
            "checks": [],
            "rubric": rubric,
        },
        projection=projection,
        proposed_by_node_id=node_id,
        patch_id=patch_id,
        trusted_requirement_record_ids=resolved.requirement_record_ids,
    )
    record_id = f"decision-answer-{digest[:24]}"
    record = DecisionAnswerRecord(
        record_id=record_id,
        record_kind="graph_record",
        record_type="decision_answer",
        producer_node_id=node_id,
        producer_port="decision",
        port="decision",
        schema="DecisionAnswer",
        schema_version=DISCOVERY_BRIEF_SCHEMA_VERSION,
        value=DecisionAnswerValue(
            interaction_contract="decision-v1",
            family="discovery_brief",
            decision_request_id=decision_request_id,
            answer_schema_id=DISCOVERY_BRIEF_SCHEMA_ID,
            answer_schema_version=DISCOVERY_BRIEF_SCHEMA_VERSION,
            answer_schema_sha256=discovery_brief_schema_sha256(),
            compiler_contract_version=DECISION_COMPILER_CONTRACT_VERSION,
            answer_sha256=answer_hash,
            answer=canonical_answer,
            consequence_patch_id=patch_id,
            bound_input_record_ids=[item.record_id for item in resolved.bound_inputs],
        ),
    )
    records = output_record_payloads_view(projection)
    read_authority = [node_id, *(item.record_id for item in resolved.bound_inputs)]
    for record_id in resolved.requirement_record_ids:
        requirement = records.get(record_id)
        if not isinstance(requirement, RequirementRecord):
            raise DecisionContractResolutionError(
                f"bound requirement record {record_id!r} became unavailable"
            )
        read_authority.extend(
            value
            for value in (requirement.value.id, requirement.value.version)
            if value is not None
        )
    snapshot = records.get(resolved.routine_snapshot_record_id)
    if snapshot is not None and snapshot.producer_node_id is not None:
        read_authority.append(snapshot.producer_node_id)
    return DecisionCompilation(
        patch_id=patch_id,
        base_graph_position=base_graph_position,
        ops=tuple(ops),
        decision_record=record,
        bound_inputs=resolved.bound_inputs,
        read_set=tuple(dict.fromkeys(read_authority)),
    )


def compile_implementation_plan(
    projection: GraphProjection,
    *,
    node_id: str,
    execution_id: str,
    answer: Mapping[str, Any],
) -> ImplementationPlanCompilation:
    """Validate and assemble one controller-owned discovery plan record."""
    resolved = resolve_implementation_plan_context(projection, node_id)
    plan = resolved.validate_answer(answer)
    aliases = cast(dict[str, str], dict(resolved.requirement_aliases.object_items()))
    alias_order = resolved.requirement_alias_order
    requirement_ids = [aliases[alias] for alias in alias_order]
    requirement_records = dict(zip(alias_order, resolved.requirement_record_ids, strict=True))
    first_batch = plan.batches[0]
    first_requirement_ids = [aliases[alias] for alias in first_batch.requirements]
    first_requirement_record_ids = tuple(
        requirement_records[alias] for alias in first_batch.requirements
    )
    plan_hash = canonical_decision_answer_hash(plan.model_dump(mode="json"))
    patch_id = (
        "decision-plan-successor-"
        + hashlib.sha256(f"{execution_id}\x00{node_id}\x00{plan_hash}".encode("utf-8")).hexdigest()[
            :24
        ]
    )
    from orchestrator.graph.macros import compile_decision_plan_successor_ops

    ops = compile_decision_plan_successor_ops(
        projection=projection,
        proposed_by_node_id=node_id,
        successor_node_id=resolved.successor_node_id,
        verifier_node_id=resolved.plan_verifier_node_id,
        plan_scope=first_batch.key,
        remaining_horizons=len(plan.batches),
        requirement_ids=first_requirement_ids,
        trusted_requirement_record_ids=first_requirement_record_ids,
    )
    record = SemanticArtifactRecord.model_validate(
        {
            "record_id": f"semantic-artifact-{execution_id}-semantic_artifact",
            "record_kind": "graph_record",
            "record_type": "semantic_artifact",
            "schema_version": DECISION_PLAN_SCHEMA_VERSION,
            "producer_node_id": node_id,
            "port": "semantic_artifact",
            "schema": "SemanticArtifact",
            "value": {
                "semantic_role": "implementation_plan",
                "schema_id": DECISION_PLAN_SCHEMA_ID,
                "schema_version": DECISION_PLAN_SCHEMA_VERSION,
                "content": plan.model_dump(mode="json", exclude_none=True),
                "provenance": {
                    "source": "agent_submit",
                    "execution_id": execution_id,
                },
                "source_record_ids": [item.record_id for item in resolved.bound_inputs],
                "requirement_ids": requirement_ids,
                "task_region_id": str(
                    (node_payload_view(projection, node_id) or {}).get("task_region_id") or node_id
                ),
                "validation_status": "validated",
                "authority_status": "accepted",
            },
        }
    )
    read_authority = [
        node_id,
        resolved.declaration_record_id,
        resolved.plan_verifier_node_id,
        resolved.successor_node_id,
        *(item.record_id for item in resolved.bound_inputs),
    ]
    records = output_record_payloads_view(projection)
    for record_id in resolved.requirement_record_ids:
        requirement = records.get(record_id)
        if not isinstance(requirement, RequirementRecord):
            raise DecisionContractResolutionError(
                f"bound requirement record {record_id!r} became unavailable"
            )
        read_authority.extend(
            value
            for value in (requirement.value.id, requirement.value.version)
            if value is not None
        )
    return ImplementationPlanCompilation(
        patch_id=patch_id,
        ops=tuple(ops),
        semantic_record=record,
        bound_inputs=resolved.bound_inputs,
        read_set=tuple(dict.fromkeys(read_authority)),
    )


ResolvedDecisionContext: TypeAlias = (
    ResolvedDiscoveryBriefContext
    | ResolvedImplementationPlanContext
    | ResolvedBatchDecisionContext
    | ResolvedCorrectionDecisionContext
)


def resolve_decision_context(
    projection: GraphProjection,
    node_id: str,
) -> ResolvedDecisionContext:
    applicability = resolve_decision_applicability(projection, node_id)
    if applicability is None:
        raise DecisionContractResolutionError("node is not a decision-v1 target")
    if applicability.family == "discovery_brief":
        return resolve_discovery_brief_context(projection, node_id)
    if applicability.family == "implementation_plan":
        return resolve_implementation_plan_context(projection, node_id)
    if applicability.family == "batch_decision":
        return resolve_batch_decision_context(projection, node_id)
    if applicability.family == "correction_decision":
        return resolve_correction_decision_context(projection, node_id)
    raise DecisionContractResolutionError(
        f"decision family {applicability.family!r} is not activated"
    )


def canonical_decision_answer(
    family: Literal[
        "discovery_brief", "implementation_plan", "batch_decision", "correction_decision"
    ],
    answer: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one authored answer through its canonical Pydantic owner."""
    if family == "discovery_brief":
        return DiscoveryBrief.model_validate(dict(answer)).model_dump(mode="json")
    if family == "implementation_plan":
        return ImplementationPlan.model_validate(dict(answer)).model_dump(mode="json")
    if family == "correction_decision":
        return cast(
            BaseModel, TypeAdapter(CorrectionDecision).validate_python(dict(answer))
        ).model_dump(mode="json")
    parsed = cast(BatchDecision, TypeAdapter(BatchDecision).validate_python(dict(answer)))
    return parsed.model_dump(mode="json")


def compile_decision(
    projection: GraphProjection,
    *,
    node_id: str,
    decision_request_id: str,
    base_graph_position: int,
    answer: Mapping[str, Any],
) -> DecisionCompilation:
    """Compile only the decision family selected by frozen graph authority."""
    applicability = resolve_decision_applicability(projection, node_id)
    if applicability is None:
        raise DecisionContractResolutionError("node is not a decision-v1 target")
    if applicability.family == "discovery_brief":
        return compile_discovery_brief(
            projection,
            node_id=node_id,
            decision_request_id=decision_request_id,
            base_graph_position=base_graph_position,
            answer=answer,
        )
    if applicability.family == "batch_decision":
        return compile_batch_decision(
            projection,
            node_id=node_id,
            decision_request_id=decision_request_id,
            base_graph_position=base_graph_position,
            answer=answer,
        )
    if applicability.family == "correction_decision":
        return compile_correction_decision(
            projection,
            node_id=node_id,
            decision_request_id=decision_request_id,
            base_graph_position=base_graph_position,
            answer=answer,
        )
    raise DecisionContractResolutionError(
        f"decision family {applicability.family!r} is not activated"
    )


DecisionAnswerFamily: TypeAlias = Literal[
    "discovery_brief",
    "implementation_plan",
    "batch_decision",
    "correction_decision",
    "verification_decision",
    "work_result",
]


class DecisionApplicability(_DecisionModel):
    """Trusted answer family selected from graph contract and frozen snapshot."""

    interaction_contract: Literal["decision-v1"]
    family: DecisionAnswerFamily
    output_port: Literal["decision", "semantic_artifact"]
    routine_snapshot_record_id: str = Field(min_length=1)

    @field_validator("routine_snapshot_record_id")
    @classmethod
    def snapshot_identity_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "routine_snapshot_record_id")


def _decision_answer_target(
    kind: str,
    role: str | None,
    stage: object,
) -> tuple[DecisionAnswerFamily, Literal["decision", "semantic_artifact"]] | None:
    if kind == "planner" and role == "planner" and stage == "initial_planning":
        return "discovery_brief", "decision"
    if kind == "worker" and role == "discovery" and stage == "discovery":
        return "implementation_plan", "semantic_artifact"
    if kind == "planner" and role == "planner" and stage == "successor_planning":
        return "batch_decision", "decision"
    if kind == "planner" and role == "gap_planner" and stage == "gap_planning":
        return "correction_decision", "decision"
    if (
        kind == "worker"
        and role in {"implementer", "fixer"}
        and stage
        in {
            "effectful_batch",
            "corrective_work",
        }
    ):
        return "work_result", "decision"
    if (
        kind == "verifier"
        and role == "verifier"
        and stage
        in {
            "plan_verification",
            "effectful_batch",
            "final_audit",
        }
    ):
        return "verification_decision", "decision"
    return None


def _contract_explicitly_allows_role(
    contract_roles: frozenset[str] | None,
    role: str | None,
) -> bool:
    return contract_roles is None or (role is not None and role in contract_roles)


def _concrete_port_is_declared(
    node: dict[str, Any],
    *,
    field_name: Literal["inputs", "outputs"],
    node_id: str,
    port: str,
    direction: Literal["input", "output"],
    required: bool | None,
    require_graph_record_layer: bool = False,
) -> bool:
    raw_ports = node.get(field_name)
    if not isinstance(raw_ports, list):
        return False
    matches: list[dict[str, Any]] = []
    for raw_port in cast(list[Any], raw_ports):
        if not isinstance(raw_port, dict):
            continue
        typed_port = cast(dict[str, Any], raw_port)
        if typed_port.get("port") == port:
            matches.append(typed_port)
    if len(matches) != 1:
        return False
    declaration = matches[0]
    if (
        declaration.get("direction") != direction
        or declaration.get("schema") != "RoutineSnapshot"
        or declaration.get("node_id") not in {None, node_id}
    ):
        return False
    if required is not None and declaration.get("required") is not required:
        return False
    if require_graph_record_layer:
        layers = declaration.get("record_layers")
        if not isinstance(layers, list) or "graph_record" not in layers:
            return False
    return True


def _canonical_node_contract(
    node: dict[str, Any],
    *,
    expected_handler: Literal["agent", "controller"],
) -> NodeContract | None:
    kind = node.get("kind")
    role = node.get("role")
    if not isinstance(kind, str) or not isinstance(role, str):
        return None
    contract = DEFAULT_NODE_CONTRACTS.contract_for(kind, role)
    if (
        contract is None
        or contract.contract_version != 1
        or contract.handler_type != expected_handler
        or not _contract_explicitly_allows_role(contract.roles, role)
        or validate_node_payload(node) is not None
    ):
        return None
    return contract


def _resolve_bound_interaction_contract(
    projection: GraphProjection,
    node_id: str,
) -> tuple[Literal["decision-v1"] | None, str] | None:
    """Resolve frozen interaction selection through one exact binding authority."""
    binding = input_bindings_view(projection).get(node_id, {}).get("routine_snapshot")
    if binding is None:
        return None
    if binding.to_node_id != node_id or binding.to_port != "routine_snapshot":
        raise DecisionContractResolutionError("routine snapshot binding target is inconsistent")

    target = node_payload_view(projection, node_id)
    target_contract = (
        _canonical_node_contract(target, expected_handler="agent") if target is not None else None
    )
    target_port_contract = (
        input_port_contract(target_contract, "routine_snapshot")
        if target_contract is not None
        else None
    )
    if (
        target is None
        or target_contract is None
        or target_port_contract is None
        or not target_port_contract.required
        or target_port_contract.cardinality != "one"
        or not _concrete_port_is_declared(
            target,
            field_name="inputs",
            node_id=node_id,
            port="routine_snapshot",
            direction="input",
            required=True,
        )
    ):
        raise DecisionContractResolutionError(
            "decision target does not declare its canonical routine snapshot input"
        )
    record_ids = list(binding.record_ids)
    if len(record_ids) != 1:
        raise DecisionContractResolutionError(
            "decision applicability requires one exact routine snapshot record"
        )
    bound_positions = binding.record_bound_positions
    if bound_positions is None or set(bound_positions) != set(record_ids):
        raise DecisionContractResolutionError(
            "routine snapshot binding requires exact record positions"
        )

    record_id = record_ids[0]
    record = output_record_payloads_view(projection).get(record_id)
    if not isinstance(record, RoutineSnapshotRecord):
        raise DecisionContractResolutionError(
            "routine snapshot binding does not reference a routine snapshot record"
        )
    if (
        record.record_id != record_id
        or record.record_kind != "graph_record"
        or record.record_type != "routine_snapshot"
        or record.schema_ != "RoutineSnapshot"
        or record.schema_version is not None
    ):
        raise DecisionContractResolutionError(
            "routine snapshot record identity or schema contract is inconsistent"
        )
    record_bound_position = bound_positions[record_id]
    pre_store_authority = (
        record.graph_position is None
        and record_bound_position == -1
        and binding.bound_at_position == 0
    )
    durable_authority = (
        record.graph_position is not None
        and record.graph_position >= 0
        and record_bound_position >= 0
        and binding.bound_at_position >= 0
        and record.graph_position <= record_bound_position
        and record_bound_position == binding.bound_at_position
    )
    if not (pre_store_authority or durable_authority):
        raise DecisionContractResolutionError(
            "routine snapshot bound position is inconsistent with record and binding positions"
        )

    edge = edges_view(projection).get(binding.edge_id or "")
    producer = node_payload_view(projection, record.producer_node_id)
    expected_producer_contract = DEFAULT_NODE_CONTRACTS.contract_for(
        "routine_snapshot",
        "routine_snapshot",
    )
    producer_kind = producer.get("kind") if producer is not None else None
    producer_role = producer.get("role") if producer is not None else None
    typed_producer_kind = producer_kind if isinstance(producer_kind, str) else None
    typed_producer_role = producer_role if isinstance(producer_role, str) else None
    producer_contract = (
        _canonical_node_contract(producer, expected_handler="controller")
        if producer is not None
        else None
    )
    edge_payload = edge.model_dump(mode="json", exclude_none=True) if edge is not None else None
    edge_contract_error = (
        validate_edge_payload(
            edge_payload,
            source_kind=typed_producer_kind or "",
            source_role=typed_producer_role,
            target_kind=cast(str, target.get("kind")),
            target_role=cast(str, target.get("role")),
        )
        if edge_payload is not None
        else "missing edge"
    )
    if (
        edge is None
        or edge_payload is None
        or edge_contract_error is not None
        or not edge.required
        or edge.dependency_type != "input_binding"
        or edge.to_node_id != node_id
        or edge.to_port != "routine_snapshot"
        or edge.from_node_id != record.producer_node_id
        or edge.from_port not in {"snapshot", "routine_snapshot"}
        or edge.from_port != record.port
        or expected_producer_contract is None
        or producer_contract is not expected_producer_contract
        or not _contract_explicitly_allows_role(
            expected_producer_contract.roles,
            typed_producer_role,
        )
        or expected_producer_contract.handler_type != "controller"
        or producer is None
        or not _concrete_port_is_declared(
            producer,
            field_name="outputs",
            node_id=record.producer_node_id,
            port=record.port,
            direction="output",
            required=None,
            require_graph_record_layer=True,
        )
    ):
        raise DecisionContractResolutionError("routine snapshot binding authority is inconsistent")

    selector = edge.accepted_record_selector
    if not isinstance(selector, dict):
        raise DecisionContractResolutionError(
            "routine snapshot binding requires an accepted record selector"
        )
    record_payload = record.model_dump(mode="json", by_alias=True)
    try:
        selector_matches = record_selector_matches(selector, record_payload)
    except ValueError as exc:
        raise DecisionContractResolutionError(
            "routine snapshot accepted record selector is invalid"
        ) from exc
    if not selector_matches:
        raise DecisionContractResolutionError(
            "routine snapshot accepted record selector does not match the bound record"
        )

    edge_policy = binding_policy_for_edge(edge_payload, target_port_contract)
    binding_policy_payload = dict(edge_payload)
    if binding.binding_policy is None:
        binding_policy_payload.pop("binding_policy", None)
    else:
        binding_policy_payload["binding_policy"] = binding.binding_policy
    binding_policy_error = validate_edge_payload(
        binding_policy_payload,
        source_kind=typed_producer_kind or "",
        source_role=typed_producer_role,
        target_kind=cast(str, target.get("kind")),
        target_role=cast(str, target.get("role")),
    )
    projected_policy = binding_policy_for_edge(
        binding_policy_payload,
        target_port_contract,
    )
    if binding_policy_error is not None or projected_policy != edge_policy:
        raise DecisionContractResolutionError(
            "routine snapshot edge and projected binding policies are inconsistent"
        )

    selected = record.value.agent_interaction_contract
    if selected is not None and selected != "decision-v1":
        raise DecisionContractResolutionError(f"unknown agent interaction contract: {selected}")
    return selected, record_id


def resolve_decision_applicability(
    projection: GraphProjection,
    node_id: str,
) -> DecisionApplicability | None:
    """Resolve decision-v1 only from a valid node contract and exact snapshot binding.

    Ordinary non-decision nodes and exact legacy snapshots return ``None``.
    Decision-capable nodes with missing/malformed authority, and nodes that
    claim decision-v1 under an unrecognized role/stage, raise rather than
    silently falling back or trusting copied node metadata.
    """
    node = node_payload_view(projection, node_id)
    if node is None:
        return None
    kind = node.get("kind")
    role = node.get("role")
    typed_kind = kind if isinstance(kind, str) else None
    typed_role = role if isinstance(role, str) else None
    stage = node.get("semantic_stage")
    target = (
        _decision_answer_target(typed_kind, typed_role, stage) if typed_kind is not None else None
    )
    contract = _canonical_node_contract(node, expected_handler="agent")
    contract_is_valid = (
        contract is not None
        and contract.contract_version == 1
        and contract.handler_type == "agent"
        and _contract_explicitly_allows_role(contract.roles, typed_role)
        and (port_contract := input_port_contract(contract, "routine_snapshot")) is not None
        and port_contract.required
        and port_contract.cardinality == "one"
        and _concrete_port_is_declared(
            node,
            field_name="inputs",
            node_id=node_id,
            port="routine_snapshot",
            direction="input",
            required=True,
        )
    )

    resolved_binding = _resolve_bound_interaction_contract(projection, node_id)
    if resolved_binding is None:
        # Semantic stages predate decision-v1 and are deliberately shared by
        # legacy reliable-plan nodes.  A stage name alone is therefore not an
        # interaction-contract claim.  Only fail closed when the graph still
        # carries concrete decision-v1 authority for this target (for example,
        # an exact decision snapshot edge whose projected input binding was
        # lost).  Ordinary legacy macro-created nodes have neither and remain
        # on the legacy path.
        claims_decision_v1 = any(
            isinstance(record, RoutineSnapshotRecord)
            and record.value.agent_interaction_contract == "decision-v1"
            and edge.to_node_id == node_id
            and edge.to_port == "routine_snapshot"
            and edge.from_node_id == record.producer_node_id
            and edge.from_port == record.port
            for edge in edges_view(projection).values()
            for record in output_record_payloads_view(projection).values()
        )
        if not claims_decision_v1:
            return None
        if not contract_is_valid:
            raise DecisionContractResolutionError(
                "decision-capable role is not allowed by its canonical node contract"
            )
        raise DecisionContractResolutionError(
            "decision-capable node requires an exact routine snapshot binding"
        )
    selected, record_id = resolved_binding
    if selected is None:
        return None
    if target is None or not contract_is_valid:
        raise DecisionContractResolutionError(
            "decision-v1 snapshot is bound to an unrecognized role/stage or invalid canonical contract"
        )
    family, port = target
    return DecisionApplicability(
        interaction_contract="decision-v1",
        family=family,
        output_port=port,
        routine_snapshot_record_id=record_id,
    )


class DecisionBoundInput(_DecisionModel):
    """One exact record/version binding frozen into a decision request."""

    port: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    record_type: str = Field(min_length=1)
    schema_name: str = Field(min_length=1, alias="schema")
    schema_version: Annotated[StrictInt, Field(ge=1)] | None
    record_position: StrictInt = Field(ge=0)
    bound_at_position: StrictInt = Field(ge=0)

    @field_validator("port", "record_id", "record_type", "schema_name")
    @classmethod
    def binding_identity_is_substantive(cls, value: str, info: Any) -> str:
        return _require_non_whitespace(value, info.field_name)

    @model_validator(mode="after")
    def record_precedes_binding(self) -> "DecisionBoundInput":
        if self.record_position > self.bound_at_position:
            raise ValueError("bound input record position cannot follow its binding")
        return self


class DecisionSubmissionRequest(_DecisionModel):
    decision_request_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    routine_snapshot_record_id: str = Field(min_length=1)
    interaction_contract: Literal["decision-v1"]
    answer_schema_id: str = Field(min_length=1)
    answer_schema_version: StrictInt = Field(ge=1)
    answer_schema_sha256: str
    compiler_contract_version: Literal[1]
    question_context_ref: StoredArtifactRef
    question_context_sha256: str
    bound_inputs: Annotated[tuple[DecisionBoundInput, ...], Field(min_length=1)]

    @field_validator("bound_inputs", mode="before")
    @classmethod
    def freeze_bound_inputs(cls, value: object) -> object:
        return tuple(cast(list[object], value)) if isinstance(value, list) else value

    @field_validator(
        "decision_request_id",
        "execution_id",
        "routine_snapshot_record_id",
        "answer_schema_id",
    )
    @classmethod
    def trusted_identity_is_substantive(cls, value: str, info: Any) -> str:
        return _require_non_whitespace(value, info.field_name)

    @field_validator("answer_schema_sha256", "question_context_sha256")
    @classmethod
    def hashes_are_canonical(cls, value: str) -> str:
        return validate_sha256(value)

    @model_validator(mode="after")
    def context_ref_matches_hash(self) -> "DecisionSubmissionRequest":
        if self.question_context_ref.content_hash != self.question_context_sha256:
            raise ValueError("question context reference does not match its hash")
        if self.question_context_ref.artifact_id != self.question_context_sha256:
            raise ValueError("question context reference must be content-addressed")
        identities = [(item.port, item.record_id) for item in self.bound_inputs]
        if len(identities) != len(set(identities)):
            raise ValueError("bound inputs must not duplicate a port/record identity")
        snapshot_rows = [item for item in self.bound_inputs if item.port == "routine_snapshot"]
        if len(snapshot_rows) != 1:
            raise ValueError("bound inputs must include exactly one routine snapshot port row")
        snapshot = snapshot_rows[0]
        if (
            snapshot.record_id != self.routine_snapshot_record_id
            or snapshot.record_type != "routine_snapshot"
            or snapshot.schema_name != "RoutineSnapshot"
            or snapshot.schema_version is not None
        ):
            raise ValueError("routine snapshot bound input has an invalid record contract")
        return self


def canonical_decision_answer_hash(answer: Mapping[str, Any]) -> str:
    """Hash the exact canonical authored outputs carried by a staged answer."""
    if type(answer) is FrozenMap:
        frozen = cast(FrozenMap[str, FrozenJsonValue], answer)
    else:
        frozen_value = freeze_json(dict(answer))
        if type(frozen_value) is not FrozenMap:
            raise ValueError("decision answer must be a JSON object")
        frozen = cast(FrozenMap[str, FrozenJsonValue], frozen_value)
    thawed = thaw_json(frozen)
    if not isinstance(thawed, dict):
        raise ValueError("decision answer must be a JSON object")
    validate_callback_json(thawed)
    encoded = json.dumps(thawed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class DecisionSubmissionEnvelope(_DecisionModel):
    format: Literal["decision-submission-v1"]
    request: DecisionSubmissionRequest
    answer_attempt_id: str = Field(min_length=1)
    answer: FrozenMap[str, FrozenJsonValue]
    answer_sha256: str

    @field_validator("answer", mode="before")
    @classmethod
    def freeze_answer(cls, value: object) -> FrozenMap[str, FrozenJsonValue]:
        frozen = freeze_json(value)
        if type(frozen) is not FrozenMap:
            raise ValueError("answer must be a JSON object")
        return cast(FrozenMap[str, FrozenJsonValue], frozen)

    @field_serializer("answer")
    def serialize_answer(self, value: FrozenMap[str, FrozenJsonValue]) -> dict[str, Any]:
        thawed = thaw_json(value)
        if not isinstance(thawed, dict):
            raise ValueError("answer must be a JSON object")
        return thawed

    @field_validator("answer_attempt_id")
    @classmethod
    def answer_attempt_identity_is_substantive(cls, value: str) -> str:
        return _require_non_whitespace(value, "answer_attempt_id")

    @field_validator("answer_sha256")
    @classmethod
    def answer_hash_is_canonical(cls, value: str) -> str:
        return validate_sha256(value)

    @model_validator(mode="after")
    def answer_matches_hash(self) -> "DecisionSubmissionEnvelope":
        if canonical_decision_answer_hash(self.answer) != self.answer_sha256:
            raise ValueError("answer_sha256 does not match canonical answer")
        return self


class LegacySubmissionPayload(BaseModel):
    """Explicit decoder for the established output-record callback payload."""

    model_config = ConfigDict(extra="allow", frozen=True)

    output_records: tuple[dict[str, Any], ...] = ()

    @model_validator(mode="before")
    @classmethod
    def nonempty_payload_declares_records(cls, value: object) -> object:
        if isinstance(value, Mapping):
            payload = dict(cast(Mapping[str, Any], value))
            if payload and "output_records" not in payload:
                raise ValueError("non-empty legacy submission requires output_records")
            return payload
        return value


DecodedSubmissionPayload: TypeAlias = DecisionSubmissionEnvelope | LegacySubmissionPayload


def decode_submission_payload(
    payload: Mapping[str, Any],
    *,
    interaction_contract: Literal["legacy", "decision-v1"],
) -> DecodedSubmissionPayload:
    """Decode only the payload shape selected by trusted frozen authority."""
    if interaction_contract == "decision-v1":
        return DecisionSubmissionEnvelope.model_validate(dict(payload))
    if interaction_contract == "legacy":
        return LegacySubmissionPayload.model_validate(dict(payload))
    raise ValueError(f"unknown agent interaction contract: {interaction_contract}")


__all__ = [
    "BATCH_DECISION_SCHEMA_ID",
    "BATCH_DECISION_SCHEMA_VERSION",
    "CORRECTION_DECISION_SCHEMA_ID",
    "CORRECTION_DECISION_SCHEMA_VERSION",
    "Batch",
    "BatchDecision",
    "BatchKey",
    "BatchRefinement",
    "Blocker",
    "CheckChoice",
    "CorrectionDecision",
    "DECISION_COMPILER_CONTRACT_VERSION",
    "DECISION_PLAN_SCHEMA_ID",
    "DECISION_PLAN_SCHEMA_VERSION",
    "DISCOVERY_BRIEF_SCHEMA_ID",
    "DISCOVERY_BRIEF_SCHEMA_VERSION",
    "DecisionApplicability",
    "DecisionCompilation",
    "DecisionBoundInput",
    "DecisionContractResolutionError",
    "DecisionSubmissionEnvelope",
    "DecisionSubmissionRequest",
    "DiscoveryBrief",
    "EvidenceAlias",
    "Finding",
    "ImplementationPlan",
    "ImplementationPlanCompilation",
    "LegacySubmissionPayload",
    "ObligationAlias",
    "PlanAmendment",
    "ReliablePlanCheckDecision",
    "ResolvedBatchDecisionContext",
    "ResolvedCorrectionDecisionContext",
    "ResolvedDiscoveryBriefContext",
    "ResolvedImplementationPlanContext",
    "RequirementAlias",
    "VerificationDecision",
    "WorkResult",
    "batch_decision_schema",
    "batch_decision_schema_sha256",
    "correction_decision_schema",
    "correction_decision_schema_sha256",
    "canonical_decision_answer",
    "canonical_decision_answer_hash",
    "compile_batch_decision",
    "compile_correction_decision",
    "compile_decision",
    "compile_discovery_brief",
    "compile_implementation_plan",
    "decision_answer_schema",
    "decision_plan_declaration",
    "decision_plan_schema",
    "decision_plan_schema_sha256",
    "discovery_brief_schema",
    "discovery_brief_schema_sha256",
    "decode_submission_payload",
    "reliable_plan_check_decision_tool_schema",
    "resolve_decision_applicability",
    "resolve_batch_decision_context",
    "resolve_correction_decision_context",
    "resolve_decision_context",
    "resolve_discovery_brief_context",
    "resolve_implementation_plan_context",
]
