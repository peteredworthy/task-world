from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from typing import ClassVar, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import yaml

from orchestrator.graph.models import NodeState


type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None

IMPLEMENTATION_STATUSES = ("present", "absent", "partial", "unknown")
TEST_STATUSES = ("exercised", "unexercised", "contradicted", "unknown")
DOCUMENTATION_STATUSES = ("documented", "undocumented", "stale", "conflicting", "unknown")
CAPABILITY_STATUSES = ("current", "derived", "proposed", "gap", "unknown")
EPISTEMIC_STATUSES = (
    "observed",
    "deterministically-derived",
    "inferred",
    "operator-asserted",
    "proposed",
    "unknown",
)
IMPLEMENTATION_SOURCE_KINDS = {
    "api",
    "command",
    "event",
    "implementation",
    "persisted-record",
}
DIRECT_EVIDENCE_SOURCE_KINDS = {
    "api",
    "command",
    "executable-schema",
    "implementation",
    "invariant-check",
    "test",
}
DIRECT_TEST_SOURCE_KINDS = {"test", "integration-test", "unit-test"}
DIRECT_IMPLEMENTATION_SOURCE_KINDS = {
    "api",
    "command",
    "executable-schema",
    "implementation",
    "invariant-check",
}
PHASE_ONE_SNAPSHOT_INCLUDE_PATTERNS = (
    "src/orchestrator/**/*.py",
    "tests/**/*.py",
    "ui/src/**/*.ts",
    "ui/src/**/*.tsx",
    "docs/jtbd/jobs.md",
    "docs/jtbd/journeys.md",
    "docs/jtbd/decision-information.md",
    "docs/jtbd/information-architecture.md",
    "docs/jtbd/evaluation-rubric.md",
    "docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md",
    "research/ui-foundation/agent-reports/*.md",
    "research/ui-foundation/tools/validate.py",
    "tests/integration/test_ui_foundation_tools.py",
)
PHASE_FILES = {
    0: (
        "index.md",
        "status.md",
        "source-map.md",
        "decision-log.md",
        "open-questions.md",
        "catalog/scope.yaml",
        "catalog/ids.yaml",
        "catalog/claims.yaml",
        "catalog/invariants.yaml",
        "catalog/conflicts.yaml",
        "catalog/questions.yaml",
        "catalog/decisions.yaml",
        "catalog/evidence.yaml",
        "reviews/index.html",
    ),
    1: (
        "catalog/action-authority-surfaces.yaml",
        "reality/domain-model.yaml",
        "reality/relationships.yaml",
        "reality/state-model.yaml",
        "reality/permissions.yaml",
        "reality/evidence/inventory.yaml",
    ),
    2: ("capabilities/registry.yaml", "capabilities/gaps.md"),
    3: (),
}
CANONICAL_COLLECTIONS = {
    "catalog/scope.yaml",
    "catalog/ids.yaml",
    "catalog/claims.yaml",
    "catalog/invariants.yaml",
    "catalog/conflicts.yaml",
    "catalog/questions.yaml",
    "catalog/decisions.yaml",
    "catalog/evidence.yaml",
    "catalog/action-authority-surfaces.yaml",
    "reality/domain-model.yaml",
    "reality/relationships.yaml",
    "reality/state-model.yaml",
    "reality/permissions.yaml",
    "reality/evidence/inventory.yaml",
    "capabilities/registry.yaml",
}
SEMANTIC_COLLECTIONS = {
    "catalog/claims.yaml",
    "catalog/invariants.yaml",
    "reality/domain-model.yaml",
    "reality/relationships.yaml",
    "reality/state-model.yaml",
    "reality/permissions.yaml",
    "reality/evidence/inventory.yaml",
    "capabilities/registry.yaml",
}


def _normalized_list_value(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class FoundationPackage:
    root: Path
    documents: dict[str, JsonValue]
    existing_files: frozenset[str]
    schemas: dict[str, JsonValue]
    reviews: dict[str, str]
    source_loads: tuple[SourceLoad, ...]
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class SourceLoad:
    relative: str
    expected_sha256: str
    resolved: Path | None
    content: bytes | None
    error: str | None
    unsafe: bool


class CanonicalDocument(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    schema_version: str
    items: list[dict[str, JsonValue]]


class SemanticCatalog(CanonicalDocument):
    expected_prefix: ClassVar[str]

    @model_validator(mode="after")
    def validate_semantic_items(self) -> SemanticCatalog:
        for item in self.items:
            semantic = SemanticItem.model_validate(item)
            if not semantic.id.startswith(f"{self.expected_prefix}-"):
                raise ValueError(f"expected {self.expected_prefix} namespace")
        return self


class NamespacedCatalog(CanonicalDocument):
    expected_prefix: ClassVar[str]

    @model_validator(mode="after")
    def validate_item_namespaces(self) -> NamespacedCatalog:
        for item in self.items:
            identifier = item.get("id")
            if not isinstance(identifier, str) or not identifier.startswith(
                f"{self.expected_prefix}-"
            ):
                raise ValueError(f"expected {self.expected_prefix} namespace")
        return self


class ScopeCatalog(CanonicalDocument):
    @model_validator(mode="after")
    def validate_scope_items(self) -> ScopeCatalog:
        required = {
            "key",
            "source",
            "source_anchor",
            "demand_type",
            "label",
            "audit_owner",
            "downstream_jobs",
            "blocking",
        }
        for item in self.items:
            if not required <= item.keys():
                raise ValueError("scope demand fields missing")
        return self


class IdCatalog(CanonicalDocument):
    pass


class ClaimCatalog(SemanticCatalog):
    expected_prefix = "CAP"


class InvariantCatalog(SemanticCatalog):
    expected_prefix = "INV"


class ConflictCatalog(NamespacedCatalog):
    expected_prefix = "CON"


class QuestionCatalog(NamespacedCatalog):
    expected_prefix = "Q"


class DecisionCatalog(NamespacedCatalog):
    expected_prefix = "DEC"


class EvidenceCatalog(CanonicalDocument):
    snapshot: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_evidence_items(self) -> EvidenceCatalog:
        SourceSnapshot.model_validate(self.snapshot)
        for item in self.items:
            if item.get("source_kind") == "command":
                CommandDeclaration.model_validate(item)
            else:
                EvidenceRecord.model_validate(item)
        return self


class DomainCatalog(SemanticCatalog):
    expected_prefix = "ENT"


class RelationshipCatalog(SemanticCatalog):
    expected_prefix = "REL"


class StateCatalog(SemanticCatalog):
    expected_prefix = "STA"
    transitions: list[dict[str, JsonValue]] = []

    @model_validator(mode="after")
    def validate_transitions(self) -> StateCatalog:
        for transition in self.transitions:
            StateTransition.model_validate(transition)
        return self


class PermissionCatalog(SemanticCatalog):
    expected_prefix = "PER"


class EvidenceInventoryCatalog(SemanticCatalog):
    expected_prefix = "EVI"


class CapabilityCatalog(SemanticCatalog):
    expected_prefix = "CAP"


class ActionAuthoritySurface(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action_id: str = Field(pattern=r"^ACT-[0-9]+$")
    command_id: str | None = Field(default=None, pattern=r"^CMD-[0-9]+$")
    surface_kind: Literal[
        "independent-external-mutation",
        "derived-same-command-consequence",
        "absent-gap",
        "non-mutating",
        "internal",
    ]
    independently_callable: bool
    mutates_state: bool
    enforced_authorization: Literal["absent", "partial", "present", "not-applicable"]
    authority_owner_action_id: str | None = Field(default=None, pattern=r"^ACT-[0-9]+$")
    q5_required: bool
    route_family: str = Field(min_length=1)
    implementation_locators: list[str]
    evidence_ids: list[str]
    rationale: str = Field(min_length=1)


class MutationRouteInventoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    route_family: str = Field(min_length=1)
    action_id: str = Field(pattern=r"^ACT-[0-9]+$")
    command_id: str = Field(pattern=r"^CMD-[0-9]+$")
    implementation_locator: str = Field(min_length=1)


class ActionAuthorityCatalog(CanonicalDocument):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    question_id: Literal["Q-5"]
    route_inventory: list[MutationRouteInventoryItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_authority_items(self) -> ActionAuthorityCatalog:
        if not self.items:
            raise ValueError("action authority items must not be empty")
        for item in self.items:
            ActionAuthoritySurface.model_validate(item)
        return self


CATALOG_MODELS: dict[str, type[CanonicalDocument]] = {
    "catalog/scope.yaml": ScopeCatalog,
    "catalog/ids.yaml": IdCatalog,
    "catalog/claims.yaml": ClaimCatalog,
    "catalog/invariants.yaml": InvariantCatalog,
    "catalog/conflicts.yaml": ConflictCatalog,
    "catalog/questions.yaml": QuestionCatalog,
    "catalog/decisions.yaml": DecisionCatalog,
    "catalog/evidence.yaml": EvidenceCatalog,
    "catalog/action-authority-surfaces.yaml": ActionAuthorityCatalog,
    "reality/domain-model.yaml": DomainCatalog,
    "reality/relationships.yaml": RelationshipCatalog,
    "reality/state-model.yaml": StateCatalog,
    "reality/permissions.yaml": PermissionCatalog,
    "reality/evidence/inventory.yaml": EvidenceInventoryCatalog,
    "capabilities/registry.yaml": CapabilityCatalog,
}


class SemanticItem(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    id: str = Field(pattern=r"^[A-Z]+-[0-9]+$")
    title: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    implementation_status: Literal["present", "absent", "partial", "unknown"]
    test_status: Literal["exercised", "unexercised", "contradicted", "unknown"]
    documentation_status: Literal["documented", "undocumented", "stale", "conflicting", "unknown"]
    capability_status: Literal["current", "derived", "proposed", "gap", "unknown"] | None = None
    epistemic_status: (
        Literal[
            "observed",
            "deterministically-derived",
            "inferred",
            "operator-asserted",
            "proposed",
            "unknown",
        ]
        | None
    ) = None
    confidence: float | str
    confidence_basis: str = Field(min_length=1)
    evidence_ids: list[str]
    conflict_ids: list[str]
    question_ids: list[str]
    limitations: list[str]
    prohibited_interpretations: list[str]


class CarrierBinding(BaseModel):
    """A demand-specific use of a Phase 1 canonical carrier."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^(?:ENT|STA|EVI|ACT|PER)-[0-9]+$")
    role: str = Field(min_length=1)
    semantic_type: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class DerivationEvidenceBinding(BaseModel):
    """Evidence bound to a derivation operation rather than copied to its output."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^EVD-[0-9]+$")
    role: Literal["input-carrier", "pure-projection-implementation"]
    path: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    semantic_type: str = Field(min_length=1)


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    id: str = Field(pattern=r"^EVD-[0-9]+$")
    source_kind: str
    reachable: bool = False
    test_status: Literal["exercised", "unexercised", "contradicted", "unknown"] | None = None
    evidence_type: str | None = None
    supported_semantic_types: list[str] = []


class CommandDeclaration(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    id: str = Field(pattern=r"^CMD-[0-9]+$")
    source_kind: Literal["command"]
    implementation_status: Literal["present", "absent", "partial", "unknown"]
    reachable: bool


class StateTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    from_state_id: str = Field(pattern=r"^STA-[0-9]+$")
    to_state_id: str = Field(pattern=r"^STA-[0-9]+$")
    command_id: str | None = Field(default=None, pattern=r"^CMD-[0-9]+$")
    mechanism: str | None = None
    evidence_ids: list[str] | None = None
    limitations: list[str] | None = None


class ActionTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    from_state_id: str | None = None
    to_state_id: str | None = None
    from_state_ids: list[str] | None = None
    to_state_ids: list[str] | None = None

    @model_validator(mode="after")
    def require_nonempty_sides(self) -> ActionTransition:
        if self.from_state_id is not None and self.from_state_ids is not None:
            raise ValueError("transition cannot define both singular and plural from states")
        if self.to_state_id is not None and self.to_state_ids is not None:
            raise ValueError("transition cannot define both singular and plural to states")
        starts = self.from_state_ids or ([self.from_state_id] if self.from_state_id else [])
        ends = self.to_state_ids or ([self.to_state_id] if self.to_state_id else [])
        if not starts or not ends:
            raise ValueError("transition requires nonempty from and to states")
        for name, values in (("from_state_ids", starts), ("to_state_ids", ends)):
            if len(values) != len({_normalized_list_value(value) for value in values}):
                raise ValueError(f"{name} contains normalized duplicates")
        return self


class ActionTransitionVariant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    carrier: Literal["task", "run", "result", "file", "projection"]
    from_state_id: str = Field(pattern=r"^STA-[0-9]+$")
    to_state_id: str = Field(pattern=r"^STA-[0-9]+$")
    eligibility_precondition: str = Field(min_length=1)
    effect_kind: Literal["state-change", "self-loop-field-mutation", "accepted-no-op"]
    evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_effect_and_evidence(self) -> ActionTransitionVariant:
        is_self_loop = self.from_state_id == self.to_state_id
        if self.effect_kind == "state-change" and is_self_loop:
            raise ValueError("state-change variant must change state")
        if self.effect_kind != "state-change" and not is_self_loop:
            raise ValueError(f"{self.effect_kind} variant must be a self-loop")
        if any(not re.fullmatch(r"EVD-[0-9]+", value) for value in self.evidence_ids):
            raise ValueError("variant evidence_ids must use the EVD namespace")
        if len(self.evidence_ids) != len(
            {_normalized_list_value(value) for value in self.evidence_ids}
        ):
            raise ValueError("variant evidence_ids contains normalized duplicates")
        return self


class DerivationContract(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    id: str = Field(pattern=r"^DRV-[0-9]+$")
    status: Literal["admitted", "rejected"]
    capability_ids: list[str] = []
    inputs: list[str] = Field(min_length=1)
    typed_inputs: dict[str, str] = {}
    algorithm: str = Field(min_length=1)
    output_type: str = Field(min_length=1)
    produced_fields: list[str] = []
    unknown_behavior: str = Field(min_length=1)
    failure_behavior: str = Field(min_length=1)
    freshness: str = Field(min_length=1)
    recomputation_behavior: str = Field(min_length=1)
    implementation_evidence_ids: list[str] = Field(min_length=1)
    evidence_bindings: list[DerivationEvidenceBinding] = []
    limitations: list[str]
    prohibited_interpretations: list[str]


class ActionContract(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    id: str = Field(pattern=r"^ACT-[0-9]+$")
    implementation_status: Literal["present", "absent", "partial", "unknown"]
    capability_status: Literal["current", "derived", "proposed", "gap", "unknown"] | None = None
    executable: bool | None = None
    command_id: str | None = None
    actor: str | None = None
    permission_requirements: list[str] | None = None
    preconditions: list[str] | None = None
    expected_source_version: str | None = None
    required_input: JsonValue = None
    validation: list[str] | None = None
    durable_effect: str | None = None
    resulting_state_id: str | None = None
    failure_modes: list[str] | None = None
    stale_state_behavior: str | None = None
    idempotency: str | None = None
    retry_behavior: str | None = None
    reversibility: str | None = None
    audit_evidence_ids: list[str] | None = None
    transition: ActionTransition | None = None
    transition_variants: list[ActionTransitionVariant] | None = None
    implementation_locators: list[str] | None = None
    test_locators: list[str] | None = None
    bounded_test_locators: list[str] | None = None

    @model_validator(mode="after")
    def require_present_contract(self) -> ActionContract:
        if self.transition is not None and self.transition_variants is not None:
            raise ValueError("action cannot define both transition and transition_variants")
        for field in (
            "permission_requirements",
            "preconditions",
            "validation",
            "failure_modes",
            "audit_evidence_ids",
            "implementation_locators",
            "test_locators",
            "bounded_test_locators",
        ):
            values = getattr(self, field)
            if values is not None and len(values) != len(
                {_normalized_list_value(value) for value in values}
            ):
                raise ValueError(f"{field} contains normalized duplicates")
        if self.transition_variants is not None:
            normalized_variants = {
                (
                    variant.carrier,
                    variant.from_state_id,
                    variant.to_state_id,
                    _normalized_list_value(variant.eligibility_precondition),
                    variant.effect_kind,
                    tuple(sorted(_normalized_list_value(value) for value in variant.evidence_ids)),
                )
                for variant in self.transition_variants
            }
            if len(normalized_variants) != len(self.transition_variants):
                raise ValueError("transition_variants contains normalized duplicates")
        if self.implementation_status != "present":
            return self
        required = (
            "command_id",
            "actor",
            "permission_requirements",
            "preconditions",
            "expected_source_version",
            "required_input",
            "validation",
            "durable_effect",
            "resulting_state_id",
            "failure_modes",
            "stale_state_behavior",
            "idempotency",
            "retry_behavior",
            "reversibility",
            "audit_evidence_ids",
        )
        missing = [field for field in required if getattr(self, field) in (None, "", [])]
        if self.transition is None and not self.transition_variants:
            missing.append("transition or transition_variants")
        if missing:
            raise ValueError(f"present action fields missing: {', '.join(missing)}")
        return self


class SourceSnapshotFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    audited_at: str | None = Field(default=None, min_length=1)
    tombstone: bool = False

    @model_validator(mode="after")
    def validate_delta_record(self) -> SourceSnapshotFile:
        if self.tombstone:
            if self.sha256 is not None or self.audited_at is not None:
                raise ValueError("tombstone cannot carry hash or audit time")
        elif self.sha256 is None or self.audited_at is None:
            raise ValueError("source file requires hash and audit time")
        return self


class SourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    id: str = Field(min_length=1)
    files: list[SourceSnapshotFile]


class ConflictRecord(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    id: str = Field(pattern=r"^CON-[0-9]+$")
    status: Literal["unresolved", "resolved"]


class SchemaBoundary(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    schema_uri: str = Field(alias="$schema")
    type: Literal["object"]
    required: list[str]
    properties: dict[str, dict[str, JsonValue]]


class StatusEvidenceReviewMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1"]
    scope_manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    active_snapshot_id: str = Field(min_length=1)
    reviewer_model: str = Field(min_length=1)
    reviewer_role: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)


class StatusEvidenceLocatorReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    review_id: str = Field(pattern=r"^SER-[0-9]{4}$")
    record_id: str = Field(pattern=r"^(?:REL|STA|ACT|EVI|INV)-[0-9]+$")
    dimension: Literal["implementation", "test"]
    locator_kind: str = Field(min_length=1)
    locator: str | None
    record_proposition: str = Field(min_length=1)
    observed_source_or_test_fact: str = Field(min_length=1)
    boundary: str = Field(min_length=1)
    verdict: Literal["proves", "partially-proves", "does-not-prove", "contradicts"]
    status_compatibility: Literal["present", "partial", "absent", "exercised", "unexercised"]
    review_rationale: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)
    admission: Literal["admitted", "bounded", "rejected"]
    covered_clause_ids: list[str] = []


class StatusEvidenceDimensionReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    review_id: str = Field(pattern=r"^SDR-[0-9]{4}$")
    record_id: str = Field(pattern=r"^(?:REL|STA|ACT|EVI|INV)-[0-9]+$")
    dimension: Literal["implementation", "test", "documentation", "capability", "epistemic"]
    combined_verdict: Literal[
        "proves",
        "partially-proves",
        "absent",
        "unexercised",
        "contradicts",
        "proposed",
        "gap",
        "unknown",
    ]
    compatible_status: Literal[
        "present",
        "partial",
        "absent",
        "unknown",
        "exercised",
        "unexercised",
        "contradicted",
        "documented",
        "undocumented",
        "stale",
        "conflicting",
        "current",
        "derived",
        "proposed",
        "gap",
        "observed",
        "deterministically-derived",
        "inferred",
        "operator-asserted",
    ]
    admitted_locators: list[str] = []
    bounded_locators: list[str] = []
    rejected_locators: list[str] = []
    evidence_ids: list[str] = []
    conflict_ids: list[str] = []
    question_ids: list[str] = []
    record_proposition: str = Field(min_length=1)
    observed_fact: str = Field(min_length=1)
    boundary: str = Field(min_length=1)
    uncovered_boundary: str = ""
    rationale: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)
    required_clause_ids: list[str] = []
    clauses: dict[str, str] = {}
    documentation_evidence_ids: list[str] = []
    freshness_state: Literal["current", "stale", "unknown"] | None = None
    freshness_boundary: str = ""
    evidence_age: str = ""
    missing_documentation_boundary: str = ""
    contradiction_clauses: dict[str, str] = {}
    unresolved_issue_ids: list[str] = []
    absence_evidence_ids: list[str] = []
    authority_ids: list[str] = []
    gap_contract_ids: list[str] = []
    unresolved_boundary: str = ""
    observation_evidence_ids: list[str] = []
    derivation_contract_ids: list[str] = []
    inference_rule: str = ""
    inference_evidence_ids: list[str] = []
    assertion_evidence_ids: list[str] = []
    proposal_authority_ids: list[str] = []


class StatusEvidenceReviewCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    metadata: StatusEvidenceReviewMetadata
    reviews: list[StatusEvidenceLocatorReview]
    dimension_reviews: list[StatusEvidenceDimensionReview]


def _issue(code: str, path: Path | str, message: object) -> ValidationIssue:
    return ValidationIssue(code, str(path), " ".join(str(message).splitlines()))


def load_foundation(root: Path) -> FoundationPackage:
    """Load filesystem YAML at the boundary; semantic validation stays pure."""
    documents: dict[str, JsonValue] = {}
    existing_files: set[str] = set()
    schemas: dict[str, JsonValue] = {}
    reviews: dict[str, str] = {}
    issues: list[ValidationIssue] = []
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        relative = path.relative_to(root).as_posix()
        existing_files.add(relative)
        if relative.startswith("schemas/") and path.suffix == ".json":
            try:
                schemas[relative] = cast(JsonValue, json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                issues.append(_issue("SCHEMA_INVALID", path, error))
            continue
        if relative.startswith("reviews/phase-3-") and path.suffix == ".html":
            try:
                reviews[relative] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                issues.append(_issue("REVIEW_INVALID", path, error))
            continue
        if path.suffix not in {".yaml", ".yml"}:
            continue
        try:
            documents[relative] = cast(JsonValue, yaml.safe_load(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            issues.append(_issue("YAML_INVALID", path, error))

    source_loads: list[SourceLoad] = []
    evidence = documents.get("catalog/evidence.yaml")
    snapshot = _active_snapshot(evidence) if isinstance(evidence, dict) else None
    files = snapshot.get("files") if isinstance(snapshot, dict) else None
    repository_root = root.parents[1].resolve()
    for record in files if isinstance(files, list) else []:
        if not isinstance(record, dict):
            continue
        relative, expected = record.get("path"), record.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            continue
        candidate = Path(relative)
        unsafe = candidate.is_absolute() or ".." in candidate.parts
        resolved: Path | None = None
        if not unsafe:
            try:
                resolved = (repository_root / candidate).resolve()
                unsafe = not resolved.is_relative_to(repository_root)
            except OSError as error:
                source_loads.append(SourceLoad(relative, expected, None, None, str(error), True))
                continue
        if unsafe or resolved is None:
            source_loads.append(SourceLoad(relative, expected, resolved, None, None, True))
            continue
        try:
            source_loads.append(
                SourceLoad(relative, expected, resolved, resolved.read_bytes(), None, False)
            )
        except OSError as error:
            source_loads.append(SourceLoad(relative, expected, resolved, None, str(error), False))
    return FoundationPackage(
        root,
        documents,
        frozenset(existing_files),
        schemas,
        reviews,
        tuple(source_loads),
        tuple(issues),
    )


def _canonical_documents(
    package: FoundationPackage,
) -> tuple[dict[str, CanonicalDocument], list[ValidationIssue]]:
    documents: dict[str, CanonicalDocument] = {}
    issues: list[ValidationIssue] = []
    for relative in sorted(CANONICAL_COLLECTIONS & package.documents.keys()):
        try:
            documents[relative] = CATALOG_MODELS[relative].model_validate(
                package.documents[relative]
            )
        except ValidationError as error:
            issues.append(_issue("CANONICAL_DOCUMENT_INVALID", package.root / relative, error))
    return documents, issues


def _declare(
    declarations: dict[str, str],
    identifier: str,
    relative: str,
    package: FoundationPackage,
    issues: list[ValidationIssue],
) -> None:
    if identifier in declarations:
        issues.append(
            _issue(
                "ID_DUPLICATE",
                package.root / relative,
                f"{identifier} already declared in {declarations[identifier]}",
            )
        )
    else:
        declarations[identifier] = relative


def validate_semantics(package: FoundationPackage, phase: int) -> list[ValidationIssue]:
    """Pure typed validation over an already loaded package."""
    issues = list(package.issues)
    canonical, boundary_issues = _canonical_documents(package)
    issues.extend(boundary_issues)
    allocation_document = package.documents.get("catalog/ids.yaml")
    allocated: set[str] = set()
    allocated_suffixes: set[tuple[str, str]] = set()
    raw_allocations = (
        allocation_document.get("items") if isinstance(allocation_document, dict) else None
    )
    if isinstance(raw_allocations, list):
        for index, raw_allocation in enumerate(raw_allocations):
            if not isinstance(raw_allocation, dict):
                continue
            allocation = cast(dict[str, JsonValue], raw_allocation)
            identifier = allocation.get("canonical_id")
            if not isinstance(identifier, str):
                continue
            location = f"{package.root / 'catalog/ids.yaml'}:items[{index}]"
            match = re.fullmatch(r"([A-Z]+)-(\d+)", identifier)
            if identifier in allocated:
                issues.append(_issue("ID_ALLOCATION_DUPLICATE", location, identifier))
            allocated.add(identifier)
            if match:
                suffix = (match.group(1), str(int(match.group(2))))
                if suffix in allocated_suffixes:
                    issues.append(_issue("ID_ALLOCATION_SUFFIX_DUPLICATE", location, identifier))
                allocated_suffixes.add(suffix)

    semantic_items: dict[str, SemanticItem] = {}
    for relative in sorted(SEMANTIC_COLLECTIONS & package.documents.keys()):
        value = package.documents[relative]
        raw_items = value.get("items") if isinstance(value, dict) else None
        for index, item in enumerate(raw_items if isinstance(raw_items, list) else []):
            if not isinstance(item, dict):
                issues.append(
                    _issue(
                        "SEMANTIC_ITEM_INVALID",
                        f"{package.root / relative}:items[{index}]",
                        "item must be a mapping",
                    )
                )
                continue
            try:
                semantic = SemanticItem.model_validate(item)
                semantic_items[semantic.id] = semantic
            except ValidationError as error:
                issues.append(
                    _issue(
                        "SEMANTIC_ITEM_INVALID", f"{package.root / relative}:items[{index}]", error
                    )
                )

    for identifier, semantic in semantic_items.items():
        for field, code in (
            ("limitations", "CAPABILITY_LIMITATIONS_DUPLICATE"),
            ("prohibited_interpretations", "CAPABILITY_PROHIBITED_INTERPRETATIONS_DUPLICATE"),
        ):
            values = getattr(semantic, field)
            normalized = [" ".join(value.split()).casefold() for value in values]
            if len(normalized) != len(set(normalized)):
                issues.append(_issue(code, package.root / "capabilities/registry.yaml", identifier))

    declarations: dict[str, str] = {}
    for relative, document in canonical.items():
        raw_document = package.documents.get(relative)
        is_phase_two_claim_projection = (
            phase >= 2
            and relative == "catalog/claims.yaml"
            and isinstance(raw_document, dict)
            and raw_document.get("registry") == "capabilities/registry.yaml"
        )
        if is_phase_two_claim_projection:
            continue
        for item in document.items:
            identifier = item.get("id")
            if isinstance(identifier, str):
                _declare(declarations, identifier, relative, package, issues)

    evidence_document = canonical.get("catalog/evidence.yaml")
    evidence: dict[str, EvidenceRecord] = {}
    commands: dict[str, CommandDeclaration] = {}
    if evidence_document:
        for index, item in enumerate(evidence_document.items):
            location = f"{package.root / 'catalog/evidence.yaml'}:items[{index}]"
            if item.get("source_kind") == "command":
                try:
                    command = CommandDeclaration.model_validate(item)
                    commands[command.id] = command
                except ValidationError as error:
                    issues.append(_issue("COMMAND_DECLARATION_INVALID", location, error))
                continue
            try:
                record = EvidenceRecord.model_validate(item)
                evidence[record.id] = record
            except ValidationError as error:
                issues.append(_issue("EVIDENCE_RECORD_INVALID", location, error))

    conflicts: dict[str, ConflictRecord] = {}
    conflict_document = canonical.get("catalog/conflicts.yaml")
    for index, item in enumerate(conflict_document.items if conflict_document else []):
        try:
            conflict = ConflictRecord.model_validate(item)
            conflicts[conflict.id] = conflict
        except ValidationError as error:
            issues.append(
                _issue(
                    "CONFLICT_RECORD_INVALID",
                    f"{package.root / 'catalog/conflicts.yaml'}:items[{index}]",
                    error,
                )
            )

    question_document = canonical.get("catalog/questions.yaml")
    typed_question_ids = {
        identifier
        for item in (question_document.items if question_document else [])
        if isinstance((identifier := item.get("id")), str)
    }
    open_blocking_question_ids = {
        identifier
        for item in (question_document.items if question_document else [])
        if isinstance((identifier := item.get("id")), str)
        and item.get("blocking") is True
        and item.get("status") != "resolved"
    }
    decisive_question_ids_by_capability: dict[str, set[str]] = {
        capability_id: set() for capability_id in semantic_items
    }
    for item in question_document.items if question_document else []:
        question_id = item.get("id")
        affected_ids = item.get("affected_ids")
        if (
            not isinstance(question_id, str)
            or not isinstance(affected_ids, list)
            or item.get("blocking") is not True
            or item.get("status") == "resolved"
        ):
            continue
        for capability_id in semantic_items:
            if capability_id in affected_ids:
                decisive_question_ids_by_capability[capability_id].add(question_id)
    for identifier, semantic in semantic_items.items():
        relative = declarations.get(identifier, "unknown")
        for reference in semantic.evidence_ids:
            if reference not in evidence:
                issues.append(_issue("REFERENCE_UNRESOLVED", package.root / relative, reference))
        for reference in semantic.conflict_ids:
            if reference not in conflicts:
                issues.append(_issue("REFERENCE_UNRESOLVED", package.root / relative, reference))
        for reference in semantic.question_ids:
            if not re.fullmatch(r"Q-\d+", reference):
                issues.append(
                    _issue(
                        "QUESTION_REFERENCE_WRONG_NAMESPACE",
                        package.root / relative,
                        reference,
                    )
                )
            elif reference not in typed_question_ids:
                issues.append(
                    _issue(
                        "QUESTION_REFERENCE_UNRESOLVED",
                        package.root / relative,
                        reference,
                    )
                )

        if semantic.documentation_status == "conflicting" and not (
            semantic.conflict_ids or semantic.question_ids
        ):
            issues.append(
                _issue(
                    "CONFLICTING_SEMANTIC_REFERENCE_MISSING",
                    package.root / relative,
                    identifier,
                )
            )

    for index, item in enumerate(conflict_document.items if conflict_document else []):
        if item.get("status") != "unresolved":
            continue
        location = f"{package.root / 'catalog/conflicts.yaml'}:items[{index}]"
        claims_value = item.get("claims")
        claims = claims_value if isinstance(claims_value, list) else []
        if len(claims) < 2:
            issues.append(_issue("CONFLICT_CLAIMS_INSUFFICIENT", location, item.get("id")))
        propositions = [
            claim.get("proposition") if isinstance(claim, dict) else claim for claim in claims
        ]
        if len(propositions) >= 2 and len({str(value) for value in propositions}) < 2:
            issues.append(_issue("CONFLICT_CLAIMS_NOT_DISTINCT", location, item.get("id")))
        claim_evidence = item.get("claim_evidence")
        if not isinstance(claim_evidence, list) or len(claim_evidence) < 2:
            issues.append(_issue("CONFLICT_EVIDENCE_INSUFFICIENT", location, item.get("id")))
        if not isinstance(item.get("affected_ids"), list) or not item["affected_ids"]:
            issues.append(_issue("CONFLICT_AFFECTED_IDS_MISSING", location, item.get("id")))
        if not isinstance(item.get("settlement_method"), str) or not item["settlement_method"]:
            issues.append(_issue("CONFLICT_SETTLEMENT_METHOD_MISSING", location, item.get("id")))

    scope_document = canonical.get("catalog/scope.yaml")
    evidence_paths = {
        identifier: path
        for item in (evidence_document.items if evidence_document else [])
        if isinstance((identifier := item.get("id")), str)
        and isinstance((path := item.get("path")), str)
    }
    for index, demand in enumerate(scope_document.items if scope_document else []):
        finding = demand.get("phase_1_finding")
        location = f"{package.root / 'catalog/scope.yaml'}:items[{index}]"
        raw_finding_ids = finding.get("evidence_ids") if isinstance(finding, dict) else None
        if not isinstance(raw_finding_ids, list):
            issues.append(_issue("SCOPE_FINDING_MISSING", location, demand.get("key")))
            continue
        finding_ids: list[JsonValue] = raw_finding_ids
        if not finding_ids:
            issues.append(_issue("SCOPE_FINDING_MISSING", location, demand.get("key")))
            continue
        for raw_evidence_id in finding_ids:
            if not isinstance(raw_evidence_id, str):
                issues.append(
                    _issue("SCOPE_FINDING_EVIDENCE_UNRESOLVED", location, raw_evidence_id)
                )
                continue
            evidence_id = raw_evidence_id
            record = evidence.get(evidence_id)
            if record is None:
                issues.append(_issue("SCOPE_FINDING_EVIDENCE_UNRESOLVED", location, evidence_id))
            elif (
                record.source_kind == "audit-report"
                and "00-delegation-plan" in evidence_paths.get(evidence_id, "")
            ):
                issues.append(_issue("SCOPE_FINDING_NOT_SUBSTANTIVE", location, evidence_id))

    raw_evidence_document = package.documents.get("catalog/evidence.yaml")
    issues.extend(_validate_snapshot_lineage(package, raw_evidence_document))
    snapshot_values: list[dict[str, JsonValue]] = []
    if isinstance(raw_evidence_document, dict):
        raw_snapshot = raw_evidence_document.get("snapshot")
        if isinstance(raw_snapshot, dict):
            snapshot_values.append(raw_snapshot)
        extra_snapshots = raw_evidence_document.get("snapshots")
        if isinstance(extra_snapshots, list):
            snapshot_values.extend(
                snapshot for snapshot in extra_snapshots if isinstance(snapshot, dict)
            )
    snapshot_paths: dict[str, set[str]] = {}
    for snapshot in snapshot_values:
        identifier = snapshot.get("id")
        files = snapshot.get("files")
        if isinstance(identifier, str) and isinstance(files, list):
            snapshot_paths[identifier] = {
                path
                for file in files
                if isinstance(file, dict) and isinstance((path := file.get("path")), str)
            }
    raw_items_value = (
        raw_evidence_document.get("items") if isinstance(raw_evidence_document, dict) else None
    )
    raw_evidence_items: list[dict[str, JsonValue]] = (
        [cast(dict[str, JsonValue], value) for value in raw_items_value if isinstance(value, dict)]
        if isinstance(raw_items_value, list)
        else []
    )
    raw_evidence_by_id = {
        identifier: item
        for item in raw_evidence_items
        if isinstance((identifier := item.get("id")), str)
    }
    phase_one_snapshot = (
        raw_evidence_document.get("snapshot") if isinstance(raw_evidence_document, dict) else None
    )
    active_snapshot = _active_snapshot(raw_evidence_document)
    phase_one_files = (
        phase_one_snapshot.get("files", []) if isinstance(phase_one_snapshot, dict) else []
    )
    active_snapshot_files = (
        active_snapshot.get("files", []) if isinstance(active_snapshot, dict) else []
    )
    active_snapshot_hashes = {
        path: sha256
        for record in active_snapshot_files
        if isinstance(record, dict)
        and isinstance((path := record.get("path")), str)
        and isinstance((sha256 := record.get("sha256")), str)
    }
    for index, item in enumerate(raw_evidence_items):
        identifier = item.get("id")
        if not isinstance(identifier, str):
            continue
        location = f"{package.root / 'catalog/evidence.yaml'}:items[{index}]"
        snapshot_id = item.get("snapshot_id")
        snapshot_path = item.get("snapshot_path")
        source_kind = item.get("source_kind")
        is_direct = (
            item.get("provenance_role") == "direct" or source_kind in DIRECT_EVIDENCE_SOURCE_KINDS
        )
        if is_direct:
            for field in ("path", "symbol", "snapshot_id", "snapshot_path"):
                field_value = item.get(field)
                if not isinstance(field_value, str) or not field_value.strip():
                    issues.append(_issue("DIRECT_EVIDENCE_FIELD_MISSING", location, field))
            path = item.get("path")
            if isinstance(path, str) and isinstance(snapshot_path, str) and path != snapshot_path:
                issues.append(_issue("DIRECT_EVIDENCE_PATH_MISMATCH", location, identifier))
        if identifier.startswith("EVD-") and snapshot_id not in snapshot_paths:
            issues.append(_issue("EVIDENCE_SNAPSHOT_UNRESOLVED", location, identifier))
        elif (
            isinstance(snapshot_id, str)
            and isinstance(snapshot_path, str)
            and snapshot_path not in snapshot_paths[snapshot_id]
        ):
            issues.append(_issue("EVIDENCE_SNAPSHOT_PATH_UNRESOLVED", location, identifier))
        if item.get("source_kind") == "command":
            direct_tests = item.get("test_evidence_ids", [])
            if not isinstance(direct_tests, list):
                issues.append(_issue("COMMAND_TEST_EVIDENCE_INVALID", location, identifier))
                continue
            for test_id in direct_tests:
                record = evidence.get(test_id) if isinstance(test_id, str) else None
                raw_record = next(
                    (
                        candidate
                        for candidate in raw_evidence_items
                        if candidate.get("id") == test_id
                    ),
                    None,
                )
                if (
                    record is None
                    or record.source_kind != "test"
                    or record.test_status != "exercised"
                    or not isinstance(raw_record, dict)
                    or not isinstance(raw_record.get("path"), str)
                    or not isinstance(raw_record.get("symbol"), str)
                ):
                    issues.append(_issue("COMMAND_TEST_EVIDENCE_INVALID", location, test_id))

    source_text = {
        source.relative: source.content.decode("utf-8")
        for source in package.source_loads
        if source.content is not None
    }
    phase_one_files = (
        phase_one_snapshot.get("files") if isinstance(phase_one_snapshot, dict) else []
    )
    repository_root = package.root.parents[1]
    for record in phase_one_files if isinstance(phase_one_files, list) else []:
        path = record.get("path") if isinstance(record, dict) else None
        if not isinstance(path, str) or not path.startswith(
            "research/ui-foundation/agent-reports/"
        ):
            continue
        candidate = repository_root / path
        try:
            source_text.setdefault(path, candidate.read_text(encoding="utf-8"))
        except OSError:
            continue
    issues.extend(
        _validate_synthesis_report_anchors(
            package,
            raw_evidence_items,
            snapshot_paths,
            source_text,
        )
    )

    issues.extend(
        _validate_semantic_evidence_admission(
            package,
            semantic_items,
            declarations,
            raw_evidence_by_id,
            snapshot_paths,
            active_snapshot_hashes,
        )
    )
    if phase >= 2:
        issues.extend(
            _validate_status_scope(
                package,
                active_snapshot_hashes,
                conflict_document.items if conflict_document else [],
                question_document.items if question_document else [],
            )
        )
    issues.extend(_validate_entity_allocations(package, semantic_items, raw_allocations))

    if phase >= 1:
        _validate_q7_coverage_attestation(
            package,
            question_document if isinstance(question_document, QuestionCatalog) else None,
            raw_evidence_items,
            snapshot_values,
            issues,
        )

    affected_semantic = {identifier: item for identifier, item in semantic_items.items()}
    action_records = {
        item.get("id"): item
        for relative, item in package.documents.items()
        if relative.startswith("reality/actions/")
        and isinstance(item, dict)
        and isinstance(item.get("id"), str)
    }
    for identifier, action in action_records.items():
        location = package.root / f"reality/actions/{identifier}.yaml"
        evidence_ids = action.get("audit_evidence_ids")
        records = (
            [
                raw_evidence_by_id[evidence_id]
                for evidence_id in evidence_ids
                if evidence_id in raw_evidence_by_id
            ]
            if isinstance(evidence_ids, list)
            else []
        )
        if action.get("capability_status") == "current" and not any(
            _is_direct_evidence(record)
            and record.get("source_kind") in DIRECT_IMPLEMENTATION_SOURCE_KINDS
            and record.get("reachable") is True
            and _has_valid_direct_locator(record, snapshot_paths)
            for record in records
        ):
            issues.append(
                _issue(
                    "CURRENT_DIRECT_IMPLEMENTATION_EVIDENCE_MISSING",
                    package.root / f"reality/actions/{identifier}.yaml",
                    identifier,
                )
            )
    for item in conflict_document.items if conflict_document else []:
        if item.get("status") != "unresolved":
            continue
        conflict_id = item.get("id")
        affected_ids = item.get("affected_ids")
        if not isinstance(conflict_id, str) or not isinstance(affected_ids, list):
            continue
        for affected_id in affected_ids:
            target = affected_semantic.get(affected_id) if isinstance(affected_id, str) else None
            target_raw = action_records.get(affected_id) if isinstance(affected_id, str) else None
            raw_links = (
                target.conflict_ids
                if target
                else target_raw.get("conflict_ids", [])
                if target_raw
                else []
            )
            links = (
                [value for value in raw_links if isinstance(value, str)]
                if isinstance(raw_links, list)
                else []
            )
            if conflict_id not in links:
                issues.append(
                    _issue(
                        "CONFLICT_BACKLINK_MISSING",
                        package.root / "catalog/conflicts.yaml",
                        f"{conflict_id}:{affected_id}",
                    )
                )
            if target and target.capability_status in {"current", "derived"}:
                issues.append(
                    _issue(
                        "UNRESOLVED_ADMISSION_BLOCKED",
                        package.root / "catalog/conflicts.yaml",
                        f"{conflict_id}:{affected_id}",
                    )
                )
            if target_raw and target_raw.get("capability_status") in {"current", "derived"}:
                issues.append(
                    _issue(
                        "UNRESOLVED_ACTION_ADMISSION_BLOCKED",
                        package.root / "catalog/conflicts.yaml",
                        f"{conflict_id}:{affected_id}",
                    )
                )
    for item in question_document.items if question_document else []:
        if not (item.get("blocking") is True and item.get("status") != "resolved"):
            continue
        question_id = item.get("id")
        affected_ids = item.get("affected_ids")
        if not isinstance(question_id, str) or not isinstance(affected_ids, list):
            continue
        for affected_id in affected_ids:
            target = affected_semantic.get(affected_id) if isinstance(affected_id, str) else None
            target_raw = action_records.get(affected_id) if isinstance(affected_id, str) else None
            raw_links = (
                target.question_ids
                if target
                else target_raw.get("question_ids", [])
                if target_raw
                else []
            )
            links = (
                [value for value in raw_links if isinstance(value, str)]
                if isinstance(raw_links, list)
                else []
            )
            if question_id not in links:
                issues.append(
                    _issue(
                        "QUESTION_BACKLINK_MISSING",
                        package.root / "catalog/questions.yaml",
                        f"{question_id}:{affected_id}",
                    )
                )
            if target and target.capability_status in {"current", "derived"}:
                issues.append(
                    _issue(
                        "UNRESOLVED_ADMISSION_BLOCKED",
                        package.root / "catalog/questions.yaml",
                        f"{question_id}:{affected_id}",
                    )
                )
            if target_raw and target_raw.get("capability_status") in {"current", "derived"}:
                issues.append(
                    _issue(
                        "UNRESOLVED_ACTION_ADMISSION_BLOCKED",
                        package.root / "catalog/questions.yaml",
                        f"{question_id}:{affected_id}",
                    )
                )

    issues.extend(
        _validate_action_authority_surfaces(
            package,
            question_document,
            action_records,
            commands,
            active_snapshot_hashes,
        )
    )

    registry = canonical.get("capabilities/registry.yaml")
    if phase >= 2:
        issues.extend(
            _validate_phase_two_capability_coverage(
                package,
                registry if isinstance(registry, CapabilityCatalog) else None,
                evidence,
            )
        )
    current_contracts: list[tuple[str, str, tuple[str, ...], str]] = []
    for item in registry.items if registry else []:
        status = item.get("capability_status")
        implementation = item.get("implementation_status")
        output_contract = item.get("output_contract")
        output_variants = _output_variants(output_contract)
        if status in {"current", "derived"} and (
            not isinstance(output_contract, dict)
            or not output_variants
            or not all(_valid_output_variant(variant) for variant in output_variants)
        ):
            issues.append(
                _issue(
                    "CAPABILITY_OUTPUT_CONTRACT_INVALID",
                    package.root / "capabilities/registry.yaml",
                    item.get("id"),
                )
            )
        asserted_variant_type_list = _string_list(item.get("asserted_output_variant_types"))
        asserted_variant_types = set(asserted_variant_type_list)
        contract_variant_type_list = [
            variant["semantic_type"]
            for variant in output_variants
            if isinstance(variant.get("semantic_type"), str)
        ]
        contract_variant_types = set(contract_variant_type_list)
        if status in {"current", "derived"} and (
            not _nonempty_string_list(item.get("asserted_output_variant_types"))
            or len(asserted_variant_type_list) != len(asserted_variant_types)
            or len(contract_variant_type_list) != len(contract_variant_types)
            or asserted_variant_types != contract_variant_types
        ):
            issues.append(
                _issue(
                    "CAPABILITY_OUTPUT_VARIANT_CONTRACT_INVALID",
                    package.root / "capabilities/registry.yaml",
                    item.get("id"),
                )
            )
        if status == "current":
            evidence_ids = item.get("evidence_ids")
            records = (
                [evidence[value] for value in evidence_ids if value in evidence]
                if isinstance(evidence_ids, list)
                else []
            )
            if not any(
                record.source_kind in IMPLEMENTATION_SOURCE_KINDS and record.reachable
                for record in records
            ):
                issues.append(
                    _issue(
                        "CURRENT_IMPLEMENTATION_EVIDENCE_MISSING",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            if any(record.test_status == "contradicted" for record in records):
                issues.append(
                    _issue(
                        "CURRENT_EVIDENCE_CONTRADICTED",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            conflict_ids = item.get("conflict_ids")
            unresolved_conflict = isinstance(conflict_ids, list) and any(
                reference not in conflicts or conflicts[reference].status != "resolved"
                for reference in conflict_ids
                if isinstance(reference, str)
            )
            if unresolved_conflict:
                issues.append(
                    _issue(
                        "CURRENT_CONFLICT_UNRESOLVED",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            if not any(
                record.source_kind == "test" and record.test_status == "exercised"
                for record in records
            ):
                issues.append(
                    _issue(
                        "CURRENT_EXERCISED_EVIDENCE_MISSING",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            if (
                unresolved_conflict
                or item.get("test_status") == "contradicted"
                or item.get("documentation_status") == "conflicting"
            ):
                issues.append(
                    _issue(
                        "CURRENT_CONFLICTING",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            if implementation != "present":
                issues.append(
                    _issue(
                        "CURRENT_FUTURE_LEAKAGE",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            raw_records = (
                [raw_evidence_by_id[value] for value in evidence_ids if value in raw_evidence_by_id]
                if isinstance(evidence_ids, list)
                else []
            )
            current_command_identities = _string_list(item.get("current_command_identities"))
            if not _nonempty_string_list(item.get("current_command_identities")) or len(
                current_command_identities
            ) != len(set(current_command_identities)):
                issues.append(
                    _issue(
                        "CURRENT_COMMAND_IDENTITIES_INVALID",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            required_command_identities = _string_list(
                item.get("required_current_command_identities")
            )
            for command_identity in required_command_identities:
                has_implementation = any(
                    _is_direct_evidence(record)
                    and record.get("source_kind") in DIRECT_IMPLEMENTATION_SOURCE_KINDS
                    and record.get("reachable") is True
                    and _has_valid_direct_locator(record, snapshot_paths)
                    and command_identity in _string_list(record.get("supported_command_identities"))
                    for record in raw_records
                )
                has_test = any(
                    _is_direct_evidence(record)
                    and record.get("source_kind") in DIRECT_TEST_SOURCE_KINDS
                    and record.get("reachable") is True
                    and record.get("test_status") == "exercised"
                    and _has_valid_direct_locator(record, snapshot_paths)
                    and command_identity in _string_list(record.get("supported_command_identities"))
                    for record in raw_records
                )
                if not has_implementation or not has_test:
                    issues.append(
                        _issue(
                            "CURRENT_REQUIRED_COMMAND_EVIDENCE_MISSING",
                            package.root / "capabilities/registry.yaml",
                            f"{item.get('id')}:{command_identity}",
                        )
                    )
            for variant in output_variants:
                variant_type = variant.get("semantic_type")
                if not isinstance(variant_type, str):
                    continue
                command_identity = variant.get("command_identity")
                if (
                    not isinstance(command_identity, str)
                    or not command_identity.strip()
                    or command_identity not in current_command_identities
                ):
                    issues.append(
                        _issue(
                            "CURRENT_OUTPUT_VARIANT_DEMAND_MISMATCH",
                            package.root / "capabilities/registry.yaml",
                            f"{item.get('id')}:{variant_type}",
                        )
                    )
                    continue
                has_implementation = any(
                    _is_direct_evidence(record)
                    and record.get("source_kind") in DIRECT_IMPLEMENTATION_SOURCE_KINDS
                    and record.get("reachable") is True
                    and _has_valid_direct_locator(record, snapshot_paths)
                    and variant_type in _string_list(record.get("supported_semantic_types"))
                    and command_identity in _string_list(record.get("supported_command_identities"))
                    for record in raw_records
                )
                has_test = any(
                    _is_direct_evidence(record)
                    and record.get("source_kind") in DIRECT_TEST_SOURCE_KINDS
                    and record.get("reachable") is True
                    and record.get("test_status") == "exercised"
                    and _has_valid_direct_locator(record, snapshot_paths)
                    and variant_type in _string_list(record.get("supported_semantic_types"))
                    and command_identity in _string_list(record.get("supported_command_identities"))
                    for record in raw_records
                )
                if not has_implementation or not has_test:
                    issues.append(
                        _issue(
                            "CURRENT_OUTPUT_VARIANT_EVIDENCE_MISSING",
                            package.root / "capabilities/registry.yaml",
                            f"{item.get('id')}:{variant_type}",
                        )
                    )
                if not has_implementation or not has_test:
                    issues.append(
                        _issue(
                            "CURRENT_OUTPUT_VARIANT_COMMAND_EVIDENCE_MISSING",
                            package.root / "capabilities/registry.yaml",
                            f"{item.get('id')}:{variant_type}:{command_identity}",
                        )
                    )
            if not any(
                _is_direct_evidence(record)
                and record.get("source_kind") in DIRECT_IMPLEMENTATION_SOURCE_KINDS
                and record.get("reachable") is True
                and _has_valid_direct_locator(record, snapshot_paths)
                for record in raw_records
            ):
                issues.append(
                    _issue(
                        "CURRENT_DIRECT_IMPLEMENTATION_EVIDENCE_MISSING",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            if not any(
                _is_direct_evidence(record)
                and record.get("source_kind") in DIRECT_TEST_SOURCE_KINDS
                and record.get("reachable") is True
                and record.get("test_status") == "exercised"
                and _has_valid_direct_locator(record, snapshot_paths)
                for record in raw_records
            ):
                issues.append(
                    _issue(
                        "CURRENT_DIRECT_TEST_EVIDENCE_MISSING",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            if implementation != "present" or item.get("test_status") != "exercised":
                issues.append(
                    _issue(
                        "CURRENT_STATUS_INCONSISTENT",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            question_ids = item.get("question_ids")
            if isinstance(question_ids, list) and any(
                question_id in open_blocking_question_ids for question_id in question_ids
            ):
                issues.append(
                    _issue(
                        "CURRENT_QUESTION_UNRESOLVED",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            contract_signature = json.dumps(output_variants, sort_keys=True)
            definition = item.get("definition")
            if isinstance(definition, str):
                for (
                    previous_id,
                    previous_definition,
                    previous_identities,
                    previous_signature,
                ) in current_contracts:
                    if previous_signature == contract_signature and (
                        previous_definition != definition
                        or previous_identities != tuple(sorted(current_command_identities))
                    ):
                        issues.append(
                            _issue(
                                "CURRENT_OUTPUT_CONTRACT_COPIED_CROSS_DEMAND",
                                package.root / "capabilities/registry.yaml",
                                f"{previous_id}:{item.get('id')}",
                            )
                        )
                current_contracts.append(
                    (
                        str(item.get("id")),
                        definition,
                        tuple(sorted(current_command_identities)),
                        contract_signature,
                    )
                )
        if status in {"proposed", "gap"} and implementation == "present":
            issues.append(
                _issue(
                    "FUTURE_CURRENT_LEAKAGE",
                    package.root / "capabilities/registry.yaml",
                    item.get("id"),
                )
            )
        if status == "derived":
            conflict_ids = item.get("conflict_ids")
            unresolved_conflict = isinstance(conflict_ids, list) and any(
                reference not in conflicts or conflicts[reference].status != "resolved"
                for reference in conflict_ids
                if isinstance(reference, str)
            )
            if unresolved_conflict:
                issues.append(
                    _issue(
                        "DERIVED_CONFLICT_UNRESOLVED",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            evidence_ids = item.get("evidence_ids")
            records = (
                [evidence[value] for value in evidence_ids if value in evidence]
                if isinstance(evidence_ids, list)
                else []
            )
            evidence_contradicted = any(record.test_status == "contradicted" for record in records)
            if evidence_contradicted:
                issues.append(
                    _issue(
                        "DERIVED_EVIDENCE_CONTRADICTED",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            if (
                unresolved_conflict
                or evidence_contradicted
                or item.get("test_status") == "contradicted"
                or item.get("documentation_status") == "conflicting"
            ):
                issues.append(
                    _issue(
                        "DERIVED_CONFLICTING",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )

    derivations: dict[str, tuple[str, DerivationContract]] = {}
    for relative, value in package.documents.items():
        if not relative.startswith("capabilities/derivations/"):
            continue
        if not isinstance(value, dict):
            issues.append(
                _issue(
                    "DERIVATION_CONTRACT_INVALID",
                    package.root / relative,
                    "derivation root must be a mapping",
                )
            )
            continue
        try:
            derivation = DerivationContract.model_validate(value)
            derivations[derivation.id] = (relative, derivation)
            _declare(declarations, derivation.id, relative, package, issues)
        except ValidationError as error:
            issues.append(_issue("DERIVATION_CONTRACT_INVALID", package.root / relative, error))
    required_derivation = {
        "inputs": "DERIVATION_INPUTS_MISSING",
        "algorithm": "DERIVATION_ALGORITHM_MISSING",
        "output_type": "DERIVATION_OUTPUT_TYPE_MISSING",
        "unknown_behavior": "DERIVATION_UNKNOWN_BEHAVIOR_MISSING",
        "failure_behavior": "DERIVATION_FAILURE_BEHAVIOR_MISSING",
        "freshness": "DERIVATION_FRESHNESS_MISSING",
        "recomputation_behavior": "DERIVATION_RECOMPUTATION_BEHAVIOR_MISSING",
        "implementation_evidence_ids": "DERIVATION_IMPLEMENTATION_EVIDENCE_MISSING",
        "limitations": "DERIVATION_LIMITATIONS_MISSING",
        "prohibited_interpretations": "DERIVATION_PROHIBITED_INTERPRETATIONS_MISSING",
    }
    if phase >= 2:
        required_derivation |= {
            "capability_ids": "DERIVATION_CAPABILITY_IDS_MISSING",
            "typed_inputs": "DERIVATION_TYPED_INPUTS_MISSING",
        }
    for relative, value in package.documents.items():
        if not relative.startswith("capabilities/derivations/") or not isinstance(value, dict):
            continue
        for field, code in required_derivation.items():
            if value.get(field) in (None, "", []):
                issues.append(_issue(code, package.root / relative, field))
        algorithm = value.get("algorithm")
        if (
            phase >= 2
            and isinstance(algorithm, str)
            and not all(term in algorithm.lower() for term in ("determin", "tie", "round"))
        ):
            issues.append(
                _issue("DERIVATION_ALGORITHM_INCOMPLETE", package.root / relative, "algorithm")
            )
        capability_ids = value.get("capability_ids")
        if isinstance(capability_ids, list):
            for capability_id in capability_ids:
                capability = (
                    semantic_items.get(capability_id) if isinstance(capability_id, str) else None
                )
                if capability is None or capability.capability_status != "derived":
                    issues.append(
                        _issue(
                            "DERIVATION_CAPABILITY_LINK_UNRESOLVED",
                            package.root / relative,
                            capability_id,
                        )
                    )
    raw_derivation_capability_ids = {
        identifier: value.get("capability_ids")
        for relative, value in package.documents.items()
        if relative.startswith("capabilities/derivations/")
        and isinstance(value, dict)
        and isinstance((identifier := value.get("id")), str)
    }
    derived_output_ids: set[str] = set()
    for item in registry.items if registry else []:
        identifier = item.get("id")
        if item.get("capability_status") == "derived" and isinstance(identifier, str):
            derived_output_ids.add(identifier)
    for derivation_id, capability_ids in raw_derivation_capability_ids.items():
        if not isinstance(capability_ids, list) or not any(
            capability_id in derived_output_ids for capability_id in capability_ids
        ):
            issues.append(
                _issue(
                    "DERIVATION_OUTPUTS_MISSING",
                    package.root / "capabilities/derivations",
                    derivation_id,
                )
            )
    raw_capabilities = {
        item.get("id"): item
        for item in (registry.items if registry else [])
        if isinstance(item.get("id"), str)
    }
    for relative, value in package.documents.items():
        if not relative.startswith("capabilities/derivations/") or not isinstance(value, dict):
            continue
        typed_inputs = value.get("typed_inputs")
        inputs = value.get("inputs")
        implementation_evidence_ids = value.get("implementation_evidence_ids")
        if not isinstance(typed_inputs, dict) or not isinstance(inputs, list):
            continue
        contract_valid = True
        for input_id in inputs:
            binding = typed_inputs.get(input_id) if isinstance(input_id, str) else None
            capability = raw_capabilities.get(input_id) if isinstance(input_id, str) else None
            output_contract = capability.get("output_contract") if capability else None
            if not isinstance(binding, dict) or not isinstance(output_contract, dict):
                contract_valid = False
                continue
            expected = (
                output_contract.get("semantic_type"),
                output_contract.get("fields"),
                output_contract.get("role"),
            )
            actual = (
                binding.get("semantic_type"),
                binding.get("consumed_fields"),
                binding.get("role"),
            )
            if expected != actual:
                contract_valid = False
        if not contract_valid:
            issues.append(
                _issue(
                    "DERIVATION_TYPED_INPUT_CONTRACT_MISMATCH",
                    package.root / relative,
                    value.get("id"),
                )
            )
        if not isinstance(implementation_evidence_ids, list):
            continue
        invalid_chain = not contract_valid or any(
            not isinstance(evidence_id, str)
            or evidence.get(evidence_id) is None
            or not evidence[evidence_id].reachable
            or evidence[evidence_id].source_kind not in DIRECT_IMPLEMENTATION_SOURCE_KINDS
            for evidence_id in implementation_evidence_ids
        )
        if invalid_chain:
            issues.append(
                _issue(
                    "DERIVATION_IMPLEMENTATION_EVIDENCE_CHAIN_INVALID",
                    package.root / relative,
                    value.get("id"),
                )
            )
        if phase < 2:
            continue
        output_ids = value.get("capability_ids")
        output_contract_valid = True
        if not isinstance(output_ids, list):
            output_contract_valid = False
        else:
            for output_id in output_ids:
                output = raw_capabilities.get(output_id) if isinstance(output_id, str) else None
                contract = output.get("output_contract") if output else None
                if not isinstance(contract, dict) or (
                    contract.get("semantic_type"),
                    contract.get("fields"),
                ) != (value.get("output_type"), value.get("produced_fields")):
                    output_contract_valid = False
        if not output_contract_valid:
            issues.append(
                _issue(
                    "DERIVATION_OUTPUT_CONTRACT_MISMATCH", package.root / relative, value.get("id")
                )
            )
        raw_bindings = value.get("evidence_bindings")
        if not isinstance(raw_bindings, list) or not raw_bindings:
            issues.append(
                _issue(
                    "DERIVATION_EVIDENCE_BINDING_MISSING", package.root / relative, value.get("id")
                )
            )
            continue
        try:
            evidence_bindings = [
                DerivationEvidenceBinding.model_validate(binding) for binding in raw_bindings
            ]
        except ValidationError:
            issues.append(
                _issue(
                    "DERIVATION_EVIDENCE_BINDING_INVALID", package.root / relative, value.get("id")
                )
            )
            continue
        implementation_bindings = [
            binding
            for binding in evidence_bindings
            if binding.role == "pure-projection-implementation"
        ]
        if not implementation_bindings:
            issues.append(
                _issue(
                    "DERIVATION_EVIDENCE_BINDING_MISSING", package.root / relative, value.get("id")
                )
            )
            continue
        locator_invalid = any(
            binding.id not in implementation_evidence_ids
            or binding.semantic_type != value.get("output_type")
            or raw_evidence_by_id.get(binding.id, {}).get("path") != binding.path
            or raw_evidence_by_id.get(binding.id, {}).get("symbol") != binding.symbol
            for binding in implementation_bindings
        )
        if locator_invalid:
            issues.append(
                _issue(
                    "DERIVATION_EVIDENCE_BINDING_LOCATOR_INVALID",
                    package.root / relative,
                    value.get("id"),
                )
            )
        output_type = value.get("output_type")
        semantic_unsupported = not isinstance(output_type, str) or any(
            output_type
            not in _string_list(
                raw_evidence_by_id.get(binding.id, {}).get("supported_semantic_types")
            )
            for binding in implementation_bindings
        )
        if semantic_unsupported:
            issues.append(
                _issue(
                    "DERIVATION_IMPLEMENTATION_SEMANTIC_UNSUPPORTED",
                    package.root / relative,
                    value.get("id"),
                )
            )
    for item in registry.items if registry else []:
        if item.get("capability_status") != "derived":
            continue
        derivation_id = item.get("derivation_id")
        raw_backlinks = (
            raw_derivation_capability_ids.get(derivation_id)
            if isinstance(derivation_id, str)
            else None
        )
        if not isinstance(raw_backlinks, list) or item.get("id") not in raw_backlinks:
            issues.append(
                _issue(
                    "DERIVATION_CAPABILITY_BACKLINK_MISSING",
                    package.root / "capabilities/registry.yaml",
                    item.get("id"),
                )
            )
        if not isinstance(derivation_id, str) or derivation_id not in derivations:
            issues.append(
                _issue(
                    "DERIVATION_MISSING",
                    package.root / "capabilities/registry.yaml",
                    item.get("id"),
                )
            )
            continue
        relative, derivation = derivations[derivation_id]
        if derivation.status != "admitted":
            issues.append(_issue("DERIVATION_NOT_ADMITTED", package.root / relative, derivation.id))
        for input_id in derivation.inputs:
            capability = semantic_items.get(input_id)
            if capability is None or capability.capability_status != "current":
                issues.append(
                    _issue("DERIVATION_INPUT_NOT_CURRENT", package.root / relative, input_id)
                )
        for evidence_id in derivation.implementation_evidence_ids:
            record = evidence.get(evidence_id)
            if record is None:
                issues.append(_issue("REFERENCE_UNRESOLVED", package.root / relative, evidence_id))
            elif record.source_kind not in IMPLEMENTATION_SOURCE_KINDS or not record.reachable:
                issues.append(
                    _issue(
                        "DERIVATION_IMPLEMENTATION_EVIDENCE_INVALID",
                        package.root / relative,
                        evidence_id,
                    )
                )

    issues.extend(_validate_actions(package, declarations, commands, evidence))
    if phase >= 1:
        issues.extend(validate_graph_node_state_contract(package.root))
        issues.extend(validate_graph_retirement_transition_contract(package.root))
    issues.extend(_validate_epistemics(package, canonical, evidence))
    return issues


def _authority_locator_target(locator: str) -> str:
    """Return the exact source locator from a reviewed transport annotation."""
    return locator.rsplit(" -> ", 1)[-1]


def _validate_action_authority_surfaces(
    package: FoundationPackage,
    questions: QuestionCatalog | None,
    actions: dict[object, dict[str, JsonValue]],
    commands: dict[str, CommandDeclaration],
    active_snapshot_hashes: dict[str, str],
) -> list[ValidationIssue]:
    """Keep action, command, route, and Q5 authority coverage mechanically aligned."""
    location = package.root / "catalog/action-authority-surfaces.yaml"
    raw_catalog = package.documents.get("catalog/action-authority-surfaces.yaml")
    if not isinstance(raw_catalog, dict):
        return []
    raw_items = raw_catalog.get("items")
    if not isinstance(raw_items, list):
        return []
    items = [item for item in raw_items if isinstance(item, dict)]
    identifiers = [item.get("action_id") for item in items]
    authority_by_action = {
        identifier: item for item in items if isinstance((identifier := item.get("action_id")), str)
    }
    action_ids = {identifier for identifier in actions if isinstance(identifier, str)}
    issues: list[ValidationIssue] = []
    if len(identifiers) != len(set(identifiers)):
        issues.append(_issue("ACTION_AUTHORITY_ACTION_DUPLICATE", location, "action_id"))
    if set(authority_by_action) != action_ids:
        issues.append(
            _issue(
                "ACTION_AUTHORITY_ACTION_PARITY",
                location,
                f"map={sorted(authority_by_action)} actions={sorted(action_ids)}",
            )
        )

    repository_root = package.root.parents[1]
    for action_id, item in authority_by_action.items():
        action = actions.get(action_id)
        command_id = item.get("command_id")
        if isinstance(action, dict) and action.get("command_id") != command_id:
            issues.append(_issue("ACTION_AUTHORITY_COMMAND_PARITY", location, action_id))
        if isinstance(command_id, str) and command_id not in commands:
            issues.append(_issue("ACTION_AUTHORITY_COMMAND_MISSING", location, command_id))

        surface_kind = item.get("surface_kind")
        owner_id = item.get("authority_owner_action_id")
        if surface_kind == "derived-same-command-consequence":
            owner = authority_by_action.get(owner_id) if isinstance(owner_id, str) else None
            if (
                not isinstance(owner, dict)
                or owner.get("surface_kind") != "independent-external-mutation"
                or owner.get("command_id") != command_id
                or owner.get("q5_required") is not True
            ):
                issues.append(_issue("ACTION_AUTHORITY_DERIVED_OWNER_INVALID", location, action_id))

        if (
            surface_kind == "independent-external-mutation"
            and item.get("independently_callable") is not True
        ):
            issues.append(_issue("ACTION_AUTHORITY_CALLABILITY_MISMATCH", location, action_id))
        expected_q5 = (
            surface_kind == "independent-external-mutation"
            and item.get("mutates_state") is True
            and item.get("enforced_authorization") in {"absent", "partial"}
        )
        if item.get("q5_required") is not expected_q5:
            issues.append(_issue("ACTION_AUTHORITY_Q5_RULE_MISMATCH", location, action_id))
        if not isinstance(item.get("rationale"), str) or not str(item.get("rationale")).strip():
            issues.append(_issue("ACTION_AUTHORITY_RATIONALE_MISSING", location, action_id))

        locators = item.get("implementation_locators")
        for locator in locators if isinstance(locators, list) else []:
            exact = _authority_locator_target(locator) if isinstance(locator, str) else ""
            if not _implementation_locator_is_snapshot_resolvable(
                exact, repository_root, active_snapshot_hashes
            ):
                issues.append(
                    _issue(
                        "ACTION_AUTHORITY_IMPLEMENTATION_LOCATOR_UNRESOLVED",
                        location,
                        f"{action_id}:{locator}",
                    )
                )

    q5 = next(
        (item for item in (questions.items if questions else []) if item.get("id") == "Q-5"), None
    )
    if not isinstance(q5, dict):
        return issues
    affected_actions = {
        identifier
        for identifier in _string_list(q5.get("affected_ids"))
        if identifier.startswith("ACT-")
    }
    required_actions = {
        action_id
        for action_id, item in authority_by_action.items()
        if item.get("q5_required") is True
    }
    if affected_actions != required_actions:
        issues.append(
            _issue(
                "Q5_AUTHORIZATION_COVERAGE_MISSING"
                if required_actions - affected_actions
                else "Q5_AUTHORIZATION_COVERAGE_EXTRA",
                package.root / "catalog/questions.yaml",
                f"required={sorted(required_actions)} affected={sorted(affected_actions)}",
            )
        )
    backlink_actions = {
        identifier
        for identifier, action in actions.items()
        if isinstance(identifier, str) and "Q-5" in _string_list(action.get("question_ids"))
    }
    if backlink_actions != required_actions:
        issues.append(
            _issue(
                "Q5_AUTHORIZATION_COVERAGE_MISSING"
                if required_actions - backlink_actions
                else "Q5_AUTHORIZATION_COVERAGE_EXTRA",
                location,
                f"required={sorted(required_actions)} backlinks={sorted(backlink_actions)}",
            )
        )

    route_inventory = raw_catalog.get("route_inventory")
    inventory_items = route_inventory if isinstance(route_inventory, list) else []
    route_families = [
        item.get("route_family") for item in inventory_items if isinstance(item, dict)
    ]
    if len(route_families) != len(set(route_families)):
        issues.append(
            _issue("ACTION_AUTHORITY_ROUTE_INVENTORY_DUPLICATE", location, "route_family")
        )
    for inventory_item in inventory_items:
        if not isinstance(inventory_item, dict):
            continue
        action_id = inventory_item.get("action_id")
        command_id = inventory_item.get("command_id")
        locator = inventory_item.get("implementation_locator")
        action = actions.get(action_id)
        if not isinstance(action, dict):
            issues.append(
                _issue("ACTION_AUTHORITY_ROUTE_INVENTORY_ACTION_MISSING", location, action_id)
            )
        if not isinstance(command_id, str) or command_id not in commands:
            issues.append(
                _issue("ACTION_AUTHORITY_ROUTE_INVENTORY_COMMAND_MISSING", location, command_id)
            )
        authority = authority_by_action.get(action_id) if isinstance(action_id, str) else None
        authority_locators = (
            {
                _authority_locator_target(value)
                for value in _string_list(authority.get("implementation_locators"))
            }
            if isinstance(authority, dict)
            else set()
        )
        if (
            not isinstance(authority, dict)
            or authority.get("command_id") != command_id
            or locator not in authority_locators
        ):
            issues.append(_issue("ACTION_AUTHORITY_ROUTE_INVENTORY_PARITY", location, action_id))
        if not isinstance(locator, str) or not _implementation_locator_is_snapshot_resolvable(
            locator, repository_root, active_snapshot_hashes
        ):
            issues.append(
                _issue("ACTION_AUTHORITY_ROUTE_INVENTORY_LOCATOR_UNRESOLVED", location, locator)
            )
    return issues


def validate_graph_node_state_contract(root: Path) -> list[ValidationIssue]:
    """Check that canonical graph-node state names match the executable enum exactly."""
    state_path = root / "reality/state-model.yaml"
    ids_path = root / "catalog/ids.yaml"
    if not state_path.exists() or not ids_path.exists():
        return []
    state_document = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
    ids_document = yaml.safe_load(ids_path.read_text(encoding="utf-8")) or {}
    state_items = state_document.get("items", []) if isinstance(state_document, dict) else []
    allocations = ids_document.get("items", []) if isinstance(ids_document, dict) else []
    allocation_by_id = {
        item.get("canonical_id"): item for item in allocations if isinstance(item, dict)
    }
    issues: list[ValidationIssue] = []
    expected = {state.value for state in NodeState}
    active_graph_states: set[str] = set()
    for item in state_items if isinstance(state_items, list) else []:
        if not isinstance(item, dict) or not str(item.get("title", "")).startswith("Graph node "):
            continue
        identifier = item.get("id")
        title_value = str(item.get("title", ""))[len("Graph node ") :]
        allocation = allocation_by_id.get(identifier)
        if title_value not in expected:
            issues.append(
                _issue("GRAPH_NODE_STATE_ALIAS", state_path, f"{identifier}:{title_value}")
            )
        if isinstance(allocation, dict) and allocation.get("status") == "active":
            active_graph_states.add(title_value)
    if active_graph_states != expected:
        issues.append(
            _issue(
                "GRAPH_NODE_STATE_COVERAGE_MISMATCH",
                state_path,
                f"canonical={sorted(active_graph_states)} executable={sorted(expected)}",
            )
        )
    inactive_ids: set[str] = set()
    for allocation in allocations if isinstance(allocations, list) else []:
        if not isinstance(allocation, dict) or allocation.get("namespace") != "STA":
            continue
        if allocation.get("status") == "active":
            continue
        identifier = allocation.get("canonical_id")
        if isinstance(identifier, str):
            inactive_ids.add(identifier)
            history = allocation.get("history")
            if not isinstance(history, list) or not history:
                issues.append(_issue("RETIRED_SEMANTIC_ID_HISTORY_MISSING", ids_path, identifier))

    def references_in(value: object) -> set[str]:
        if isinstance(value, dict):
            references = {
                item
                for key, item in value.items()
                if key.endswith("state_id") and isinstance(item, str)
            }
            for nested in value.values():
                references.update(references_in(nested))
            return references
        if isinstance(value, list):
            return set().union(*(references_in(item) for item in value)) if value else set()
        return set()

    for relative in ("capabilities/registry.yaml", "catalog/claims.yaml"):
        path = root / relative
        if not path.exists():
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in document.get("items", []) if isinstance(document, dict) else []:
            if isinstance(item, dict) and (references_in(item) & inactive_ids):
                issues.append(_issue("INACTIVE_STATE_REFERENCE", path, item.get("id")))
            if isinstance(item, dict):
                bindings = item.get("implementation_carrier_bindings")
                if isinstance(bindings, list) and any(
                    isinstance(binding, dict) and binding.get("id") in inactive_ids
                    for binding in bindings
                ):
                    issues.append(_issue("INACTIVE_STATE_REFERENCE", path, item.get("id")))
    actions = root / "reality/actions"
    for path in actions.glob("*.yaml") if actions.exists() else []:
        action = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(action, dict) and references_in(action) & inactive_ids:
            issues.append(_issue("INACTIVE_STATE_REFERENCE", path, action.get("id")))
    return issues


def validate_graph_retirement_transition_contract(root: Path) -> list[ValidationIssue]:
    """Keep retirement transition mechanisms aligned with executable guards."""
    state_path = root / "reality/state-model.yaml"
    if not state_path.exists():
        return []
    loaded = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return []
    state_document = cast(dict[str, object], loaded)
    raw_transitions = state_document.get("transitions", [])
    if not isinstance(raw_transitions, list):
        return []

    patch_mechanism = "accepted retire_node patch"
    reconciliation_mechanism = "reconciliation retirement after passed terminal evidence"
    patch_sources = {"STA-71", "STA-72", "STA-29", "STA-32"}
    reconciliation_sources = {"STA-71", "STA-72", "STA-32"}
    observed_sources = {patch_mechanism: set[str](), reconciliation_mechanism: set[str]()}
    issues: list[ValidationIssue] = []

    for index, raw_transition in enumerate(raw_transitions):
        try:
            transition = StateTransition.model_validate(raw_transition)
        except ValidationError:
            continue
        if transition.to_state_id != "STA-73":
            continue
        location = f"{state_path}:transitions[{index}]"
        if transition.mechanism == patch_mechanism:
            observed_sources[patch_mechanism].add(transition.from_state_id)
            if transition.command_id != "CMD-12":
                issues.append(
                    _issue(
                        "STATE_RETIREMENT_COMMAND_MISMATCH",
                        location,
                        "accepted retire_node patch must use CMD-12",
                    )
                )
            if transition.from_state_id not in patch_sources:
                issues.append(
                    _issue(
                        "STATE_RETIREMENT_SOURCE_INELIGIBLE",
                        location,
                        f"patch source {transition.from_state_id}",
                    )
                )
        elif transition.mechanism == reconciliation_mechanism:
            observed_sources[reconciliation_mechanism].add(transition.from_state_id)
            if transition.command_id is not None:
                issues.append(
                    _issue(
                        "STATE_RETIREMENT_COMMAND_MISMATCH",
                        location,
                        "reconciliation retirement must not claim a command",
                    )
                )
            if transition.from_state_id not in reconciliation_sources:
                issues.append(
                    _issue(
                        "STATE_RETIREMENT_SOURCE_INELIGIBLE",
                        location,
                        f"reconciliation source {transition.from_state_id}",
                    )
                )
        else:
            issues.append(
                _issue(
                    "STATE_RETIREMENT_MECHANISM_INVALID",
                    location,
                    transition.mechanism,
                )
            )

    expected_sources = {
        patch_mechanism: patch_sources,
        reconciliation_mechanism: reconciliation_sources,
    }
    for mechanism, expected in expected_sources.items():
        if observed_sources[mechanism] != expected:
            issues.append(
                _issue(
                    "STATE_RETIREMENT_SOURCE_SET_MISMATCH",
                    state_path,
                    f"{mechanism}: expected {sorted(expected)}, "
                    f"observed {sorted(observed_sources[mechanism])}",
                )
            )
    return issues


def _carrier_semantic_type(identifier: str) -> str:
    """Return the canonical semantic type exposed by a Phase 1 carrier kind."""
    if identifier == "EVI-9":
        return "UsageTelemetry"
    prefix = identifier.split("-", 1)[0]
    return {
        "ENT": "EntityRecord",
        "STA": "StateRecord",
        "EVI": "EvidenceInventory",
        "ACT": "ActionContract",
        "PER": "PermissionContract",
    }.get(prefix, "")


def _role_accepts_semantic_type(role: str, semantic_type: str) -> bool:
    """Check typed carrier roles without encoding capability-specific allowlists."""
    required = {
        "entity-input": "EntityRecord",
        "state-input": "StateRecord",
        "action-contract": "ActionContract",
        "permission-contract": "PermissionContract",
        "evidence-inventory": "EvidenceInventory",
        "reversibility-action": "ActionContract",
        "authority-action": "ActionContract",
        "authority-policy": "PermissionContract",
        "usage-telemetry": "UsageTelemetry",
        "graph-usage-rollup": "UsageTelemetry",
        "structured-tool-trace": "EvidenceInventory",
    }.get(role)
    return required == semantic_type


def _role_accepts_canonical_carrier(role: str, identifier: str) -> bool:
    """Keep demand-specific roles attached to the carrier that establishes them."""
    required = {
        "EVI-5": "structured-tool-trace",
        "EVI-9": "graph-usage-rollup",
    }.get(identifier)
    return required is None or role == required


def _carrier_records(package: FoundationPackage) -> dict[str, dict[str, JsonValue]]:
    records: dict[str, dict[str, JsonValue]] = {}
    for relative, value in package.documents.items():
        if relative.startswith("reality/actions/") and isinstance(value, dict):
            identifier = value.get("id")
            if isinstance(identifier, str):
                records[identifier] = value
            continue
        if not isinstance(value, dict):
            continue
        items = value.get("items")
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance((identifier := item.get("id")), str):
                records[identifier] = item
    return records


def _string_list(value: JsonValue) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _nonempty_string_list(value: JsonValue) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def _output_variants(output_contract: JsonValue) -> list[dict[str, JsonValue]]:
    """Normalize a singleton output contract or its explicit discriminated variants."""
    if not isinstance(output_contract, dict):
        return []
    variants = output_contract.get("variants")
    if isinstance(variants, list):
        return [variant for variant in variants if isinstance(variant, dict)]
    return [output_contract]


def _valid_output_variant(variant: dict[str, JsonValue]) -> bool:
    fields = variant.get("fields")
    return (
        isinstance(variant.get("semantic_type"), str)
        and bool(variant["semantic_type"].strip())
        and _nonempty_string_list(fields)
        and isinstance(fields, list)
        and len(fields) == len(set(fields))
        and isinstance(variant.get("role"), str)
        and bool(variant["role"].strip())
    )


def _carrier_is_executable(record: dict[str, JsonValue]) -> bool:
    identifier = record.get("id")
    if isinstance(identifier, str) and identifier.startswith("ACT-"):
        return record.get("implementation_status") == "present" and record.get("executable") is True
    return record.get("implementation_status") in {"present", "partial"}


def _validate_phase_two_capability_coverage(
    package: FoundationPackage,
    registry: CapabilityCatalog | None,
    evidence: dict[str, EvidenceRecord],
) -> list[ValidationIssue]:
    """Require one honest capability classification for every closed scope demand."""
    issues: list[ValidationIssue] = []
    scope_value = package.documents.get("catalog/scope.yaml")
    scope_items = scope_value.get("items") if isinstance(scope_value, dict) else None
    scope_keys: set[str] = set()
    if isinstance(scope_items, list):
        for item in scope_items:
            if isinstance(item, dict) and isinstance((key := item.get("key")), str):
                if key in scope_keys:
                    issues.append(
                        _issue(
                            "SCOPE_DEMAND_KEY_DUPLICATE",
                            package.root / "catalog/scope.yaml",
                            key,
                        )
                    )
                scope_keys.add(key)
    registry_items = registry.items if registry else []
    gap_definitions: dict[str, list[str]] = {}
    for item in registry_items:
        if item.get("capability_status") != "gap":
            continue
        identifier = item.get("id")
        definition = item.get("definition")
        if not isinstance(identifier, str) or not isinstance(definition, str):
            continue
        normalized_definition = " ".join(definition.split())
        if "source demand with audited partial or absent Phase 1 evidence" in normalized_definition:
            issues.append(
                _issue(
                    "CAPABILITY_GAP_FALLBACK_GENERIC",
                    package.root / "capabilities/registry.yaml",
                    identifier,
                )
            )
        gap_definitions.setdefault(normalized_definition, []).append(identifier)
    for definition, identifiers in gap_definitions.items():
        if len(identifiers) > 1:
            issues.append(
                _issue(
                    "CAPABILITY_GAP_DEFINITION_DUPLICATE",
                    package.root / "capabilities/registry.yaml",
                    f"{','.join(sorted(identifiers))}: {definition}",
                )
            )
    capability_catalog_ids = {
        identifier for item in registry_items if isinstance((identifier := item.get("id")), str)
    }
    carrier_records = _carrier_records(package)
    carrier_catalog_ids = set(carrier_records)
    by_demand: dict[str, list[dict[str, JsonValue]]] = {}
    for item in registry_items:
        key = item.get("scope_demand_key")
        if not isinstance(key, str):
            issues.append(
                _issue(
                    "CAPABILITY_DEMAND_LINK_MISSING",
                    package.root / "capabilities/registry.yaml",
                    item.get("id"),
                )
            )
            continue
        by_demand.setdefault(key, []).append(item)
        if key not in scope_keys:
            issues.append(
                _issue(
                    "CAPABILITY_DEMAND_UNRESOLVED",
                    package.root / "capabilities/registry.yaml",
                    key,
                )
            )
            issues.append(
                _issue(
                    "CAPABILITY_DEMAND_EXTRA",
                    package.root / "capabilities/registry.yaml",
                    key,
                )
            )
    for item in registry_items:
        identifier = item.get("id")
        raw_bindings = item.get("implementation_carrier_bindings")
        raw_absence_ids = item.get("absence_contract_ids")
        absence_ids = set(_string_list(raw_absence_ids))
        binding_ids = {
            binding_id
            for binding in (raw_bindings if isinstance(raw_bindings, list) else [])
            if isinstance(binding, dict) and isinstance((binding_id := binding.get("id")), str)
        }
        if raw_absence_ids not in (None, []) and (
            not isinstance(raw_absence_ids, list)
            or not absence_ids
            or any(
                absence_id not in carrier_records
                or _carrier_is_executable(carrier_records[absence_id])
                for absence_id in absence_ids
            )
        ):
            issues.append(
                _issue(
                    "GAP_PARTIAL_ABSENCE_CARRIER_INVALID",
                    package.root / "capabilities/registry.yaml",
                    identifier,
                )
            )
        if absence_ids & binding_ids:
            issues.append(
                _issue(
                    "GAP_PARTIAL_ABSENCE_CARRIER_OVERLAP",
                    package.root / "capabilities/registry.yaml",
                    identifier,
                )
            )
        if (
            item.get("capability_status") not in {"gap", "unknown"}
            or item.get("implementation_status") != "partial"
        ):
            continue
        if not isinstance(raw_bindings, list) or not raw_bindings:
            issues.append(
                _issue(
                    "GAP_PARTIAL_CARRIER_UNRESOLVED",
                    package.root / "capabilities/registry.yaml",
                    identifier,
                )
            )
            continue
        try:
            bindings = [CarrierBinding.model_validate(value) for value in raw_bindings]
        except ValidationError:
            issues.append(
                _issue(
                    "GAP_PARTIAL_CARRIER_UNRESOLVED",
                    package.root / "capabilities/registry.yaml",
                    identifier,
                )
            )
            continue
        invalid_binding = any(
            binding.id not in carrier_catalog_ids
            or binding.semantic_type != _carrier_semantic_type(binding.id)
            or not _role_accepts_semantic_type(binding.role, binding.semantic_type)
            or not _role_accepts_canonical_carrier(binding.role, binding.id)
            for binding in bindings
        )
        non_executable_binding = any(
            binding.id in carrier_records
            and not _carrier_is_executable(carrier_records[binding.id])
            for binding in bindings
        )
        unsupported_binding = any(
            not set(binding.evidence_ids).issubset(
                set(_string_list(carrier_records.get(binding.id, {}).get("evidence_ids")))
                | set(_string_list(carrier_records.get(binding.id, {}).get("audit_evidence_ids")))
            )
            for binding in bindings
        )
        if invalid_binding:
            issues.append(
                _issue(
                    "GAP_PARTIAL_CARRIER_ROLE_TYPE_INVALID",
                    package.root / "capabilities/registry.yaml",
                    identifier,
                )
            )
        if unsupported_binding:
            issues.append(
                _issue(
                    "GAP_PARTIAL_CARRIER_EVIDENCE_UNSUPPORTED",
                    package.root / "capabilities/registry.yaml",
                    identifier,
                )
            )
        if non_executable_binding:
            issues.append(
                _issue(
                    "GAP_PARTIAL_CARRIER_NON_EXECUTABLE",
                    package.root / "capabilities/registry.yaml",
                    identifier,
                )
            )
    for key in sorted(scope_keys - by_demand.keys()):
        issues.append(
            _issue(
                "CAPABILITY_DEMAND_COVERAGE_MISSING",
                package.root / "capabilities/registry.yaml",
                key,
            )
        )
    for key, items in by_demand.items():
        if len(items) != 1:
            issues.append(
                _issue(
                    "CAPABILITY_DEMAND_STATUS_DUPLICATE",
                    package.root / "capabilities/registry.yaml",
                    key,
                )
            )
        for item in items:
            if item.get("capability_status") not in CAPABILITY_STATUSES:
                issues.append(
                    _issue(
                        "CAPABILITY_STATUS_MISSING",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
                    )
                )
            identifier = item.get("id")
            title = item.get("title")
            definition = item.get("definition")
            generic = (
                not isinstance(title, str)
                or title == identifier
                or bool(re.fullmatch(r"(?:Capability demand|Admitted derivation) \d+", title))
                or not isinstance(definition, str)
                or definition == "Definition"
            )
            if generic:
                issues.append(
                    _issue(
                        "CAPABILITY_ADJUDICATION_GENERIC",
                        package.root / "capabilities/registry.yaml",
                        identifier,
                    )
                )
            if (
                item.get("capability_status") == "unknown"
                and isinstance(definition, str)
                and re.fullmatch(
                    r".+ cannot be established across the audited Phase 1 carrier boundaries?\.?",
                    " ".join(definition.split()),
                )
            ):
                issues.append(
                    _issue(
                        "CAPABILITY_UNKNOWN_FALLBACK_GENERIC",
                        package.root / "capabilities/registry.yaml",
                        identifier,
                    )
                )
            if any(
                item.get(field) in (None, "", [])
                for field in (
                    "implementation_status",
                    "test_status",
                    "documentation_status",
                    "evidence_ids",
                    "confidence_basis",
                    "limitations",
                    "prohibited_interpretations",
                )
            ):
                issues.append(
                    _issue(
                        "CAPABILITY_ORTHOGONAL_STATUS_MISSING",
                        package.root / "capabilities/registry.yaml",
                        identifier,
                    )
                )
            status = item.get("capability_status")
            implementation_status = item.get("implementation_status")
            evidence_ids = item.get("evidence_ids")
            records = (
                [evidence[value] for value in evidence_ids if value in evidence]
                if isinstance(evidence_ids, list)
                else []
            )
            basis = item.get("classification_basis")
            basis_text = " ".join(
                str(value).lower()
                for value in (basis, item.get("confidence_basis"), item.get("definition"))
                if isinstance(value, str)
            )
            if status in {"gap", "unknown"}:
                carrier_ids = item.get("implementation_carrier_ids")
                raw_bindings = item.get("implementation_carrier_bindings")
                absence_basis = item.get("absence_basis")
                if implementation_status == "partial" and absence_basis not in (None, ""):
                    issues.append(
                        _issue(
                            "GAP_PARTIAL_CARRIERS_INVALID",
                            package.root / "capabilities/registry.yaml",
                            identifier,
                        )
                    )
                if status == "gap" and implementation_status == "absent":
                    if (
                        carrier_ids not in (None, [])
                        or not isinstance(absence_basis, str)
                        or not absence_basis.strip()
                    ):
                        issues.append(
                            _issue(
                                "GAP_ABSENCE_BASIS_INVALID",
                                package.root / "capabilities/registry.yaml",
                                identifier,
                            )
                        )
                if (
                    implementation_status == "absent"
                    and (
                        "partial" in basis_text
                        or any(
                            record.reachable and record.source_kind in IMPLEMENTATION_SOURCE_KINDS
                            for record in records
                        )
                    )
                    and item.get("absence_verified") is not True
                ):
                    issues.append(
                        _issue(
                            "CAPABILITY_FALSE_ABSENCE",
                            package.root / "capabilities/registry.yaml",
                            identifier,
                        )
                    )
                claims_conflict = bool(
                    re.search(
                        r"\b(?:unresolved )?conflict(?:ing| exists| remains| between|:)", basis_text
                    )
                )
                claims_question = bool(
                    re.search(
                        r"(?:blocking|unresolved) question|question (?:blocks|remains)", basis_text
                    )
                )
                if (claims_conflict and not item.get("conflict_ids")) or (
                    claims_question and not item.get("question_ids")
                ):
                    issues.append(
                        _issue(
                            "CAPABILITY_BASIS_LINK_MISSING",
                            package.root / "capabilities/registry.yaml",
                            identifier,
                        )
                    )
            if item.get("capability_status") == "current" and key in {
                "decisions.steer-context",
                "decisions.apply-steering-patch",
            }:
                issues.append(
                    _issue(
                        "FORBIDDEN_CURRENT_MANIFEST",
                        package.root / "capabilities/registry.yaml",
                        key,
                    )
                )
    allocation_value = package.documents.get("catalog/ids.yaml")
    allocation_items = allocation_value.get("items") if isinstance(allocation_value, dict) else None
    cap_allocations: dict[str, list[dict[str, JsonValue]]] = {}
    for allocation in allocation_items if isinstance(allocation_items, list) else []:
        if not isinstance(allocation, dict) or allocation.get("namespace") != "CAP":
            continue
        identifier = allocation.get("canonical_id")
        if isinstance(identifier, str):
            cap_allocations.setdefault(identifier, []).append(allocation)
        provisional_key = allocation.get("provisional_key")
        title = allocation.get("title")
        if (
            isinstance(provisional_key, str) and re.fullmatch(r"scope-demand-\d+", provisional_key)
        ) or (isinstance(title, str) and re.fullmatch(r"Capability demand \d+", title)):
            issues.append(
                _issue(
                    "CAPABILITY_ALLOCATION_PLACEHOLDER",
                    package.root / "catalog/ids.yaml",
                    identifier,
                )
            )
    for item in registry_items:
        identifier = item.get("id")
        key = item.get("scope_demand_key")
        allocations = cap_allocations.get(identifier, []) if isinstance(identifier, str) else []
        if len(allocations) != 1 or allocations[0].get("provisional_key") != key:
            issues.append(
                _issue(
                    "CAPABILITY_ALLOCATION_BINDING_INVALID",
                    package.root / "catalog/ids.yaml",
                    identifier,
                )
            )
    derivation_allocations: dict[str, dict[str, JsonValue]] = {}
    for allocation in allocation_items if isinstance(allocation_items, list) else []:
        if not isinstance(allocation, dict) or allocation.get("namespace") != "DRV":
            continue
        identifier = allocation.get("canonical_id")
        if isinstance(identifier, str):
            derivation_allocations[identifier] = allocation
    active_derivations: dict[str, dict[str, JsonValue]] = {}
    for relative, value in package.documents.items():
        if not relative.startswith("capabilities/derivations/") or not isinstance(value, dict):
            continue
        identifier = value.get("id")
        if isinstance(identifier, str):
            active_derivations[identifier] = value
    active_derivation_ids = set(active_derivations)
    for derivation_id, derivation in active_derivations.items():
        allocation = derivation_allocations.get(derivation_id)
        if not isinstance(allocation, dict) or allocation.get("status") != "active":
            issues.append(
                _issue(
                    "DERIVATION_LEDGER_ALLOCATION_MISSING",
                    package.root / "catalog/ids.yaml",
                    derivation_id,
                )
            )
            continue
        key = allocation.get("provisional_key")
        title = allocation.get("title")
        outputs = allocation.get("output_capability_ids")
        if (
            not isinstance(key, str)
            or not isinstance(title, str)
            or bool(re.fullmatch(r"derivation-\d+", key))
            or bool(re.fullmatch(r"Admitted derivation \d+", title))
            or outputs != derivation.get("capability_ids")
        ):
            issues.append(
                _issue(
                    "DERIVATION_LEDGER_BINDING_INVALID",
                    package.root / "catalog/ids.yaml",
                    derivation_id,
                )
            )
    for derivation_id, allocation in derivation_allocations.items():
        if allocation.get("status") == "active" and derivation_id not in active_derivation_ids:
            issues.append(
                _issue(
                    "DERIVATION_LEDGER_ACTIVE_ORPHAN",
                    package.root / "catalog/ids.yaml",
                    derivation_id,
                )
            )
        if allocation.get("status") == "superseded":
            key = allocation.get("provisional_key")
            title = allocation.get("title")
            outputs = allocation.get("output_capability_ids")
            if (
                not isinstance(key, str)
                or not key.strip()
                or not isinstance(title, str)
                or not title.strip()
                or not isinstance(outputs, list)
                or not outputs
                or any(output not in capability_catalog_ids for output in outputs)
            ):
                issues.append(
                    _issue(
                        "DERIVATION_LEDGER_SUPERSEDED_INVALID",
                        package.root / "catalog/ids.yaml",
                        derivation_id,
                    )
                )
    issues.extend(_validate_phase_two_projections(package, registry_items))
    return issues


def _capability_sort_key(item: dict[str, JsonValue]) -> tuple[int, str]:
    identifier = item.get("id")
    match = re.fullmatch(r"CAP-(\d+)", identifier) if isinstance(identifier, str) else None
    return (int(match.group(1)) if match else sys.maxsize, str(identifier))


def _phase_two_counts(items: list[dict[str, JsonValue]]) -> dict[str, int]:
    return {
        status: sum(item.get("capability_status") == status for item in items)
        for status in CAPABILITY_STATUSES
    }


def _phase_two_claims_projection(
    package: FoundationPackage, items: list[dict[str, JsonValue]]
) -> dict[str, JsonValue]:
    derivation_count = sum(
        relative.startswith("capabilities/derivations/")
        and isinstance(value, dict)
        and value.get("status") == "admitted"
        for relative, value in package.documents.items()
    )
    counts: dict[str, JsonValue] = {
        status: count for status, count in _phase_two_counts(items).items()
    }
    projected_items = cast(list[JsonValue], sorted(items, key=_capability_sort_key))
    projection: dict[str, JsonValue] = {
        "schema_version": "1",
        "phase_status": "complete",
        "completion_phase": 2,
        "registry": "capabilities/registry.yaml",
        "registry_status": "complete",
        "scope_demand_count": len(items),
        "classification_counts": counts,
        "derivation_count": derivation_count,
        "items": projected_items,
    }
    return projection


def _phase_two_gaps_projection(items: list[dict[str, JsonValue]]) -> str:
    counts = _phase_two_counts(items)
    lines = [
        "# Capability classifications",
        "",
        "Generated from `capabilities/registry.yaml`; do not edit by hand.",
        "",
    ]
    for status in CAPABILITY_STATUSES:
        lines.extend((f"## {status.title()} ({counts[status]})", ""))
        status_items = [item for item in items if item.get("capability_status") == status]
        if not status_items:
            lines.append("- None")
        for item in sorted(status_items, key=_capability_sort_key):
            lines.append(f"- `{item.get('id')}` **{item.get('title')}** — {item.get('definition')}")
        lines.append("")
    return "\n".join(lines)


def _phase_two_status_projection(items: list[dict[str, JsonValue]]) -> str:
    counts = _phase_two_counts(items)
    identifiers = {
        status: [
            str(item.get("id"))
            for item in sorted(items, key=_capability_sort_key)
            if item.get("capability_status") == status
        ]
        for status in CAPABILITY_STATUSES
    }
    lines = [
        "# UI foundation status",
        "",
        f"Phase 2 is complete with {len(items)} one-to-one scope-demand classifications and {sum(counts.values())} projected claims.",
        "",
        "Task15 remains IN PROGRESS pending independent review. The current semantic-clause "
        "projection covers 210 records (35 REL, 74 STA, 86 ACT, 9 EVI, 6 INV), with 139 exact "
        "and 49 bounded test locators in a 118-node collected manifest under "
        "snapshot-2026-07-25-task-15-semantic-clauses. Test distributions are REL 13/22, "
        "STA 57/17, ACT 57/29, EVI 2/7, and INV 6/0 exercised/unexercised; 62 actions retain Q-5.",
        "",
    ]
    for status in CAPABILITY_STATUSES:
        rendered_ids = ", ".join(f"`{identifier}`" for identifier in identifiers[status]) or "none"
        lines.append(f"- **{status} ({counts[status]})**: {rendered_ids}")
    lines.extend(
        (
            "",
            "Typed steering and planner-assisted replanning are forbidden from the current manifest.",
            "",
        )
    )
    return "\n".join(lines)


def _validate_phase_two_projections(
    package: FoundationPackage, items: list[dict[str, JsonValue]]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    registry_value = package.documents.get("capabilities/registry.yaml")
    expected_claims = _phase_two_claims_projection(package, items)
    actual_claims = package.documents.get("catalog/claims.yaml")
    if (
        not isinstance(registry_value, dict)
        or registry_value.get("phase_status") != "complete"
        or registry_value.get("completion_phase") != 2
    ):
        issues.append(
            _issue(
                "PHASE_TWO_METADATA_MISMATCH",
                package.root / "capabilities/registry.yaml",
                "completion metadata",
            )
        )
    if actual_claims != expected_claims:
        issues.append(
            _issue(
                "PHASE_TWO_CLAIMS_PROJECTION_STALE",
                package.root / "catalog/claims.yaml",
                "regenerate from capability registry",
            )
        )
        if not isinstance(actual_claims, dict) or any(
            actual_claims.get(field) != expected_claims[field]
            for field in (
                "phase_status",
                "completion_phase",
                "registry_status",
                "scope_demand_count",
                "classification_counts",
                "derivation_count",
            )
        ):
            issues.append(
                _issue(
                    "PHASE_TWO_METADATA_MISMATCH",
                    package.root / "catalog/claims.yaml",
                    "completion metadata",
                )
            )
    expected_text = {
        "capabilities/gaps.md": _phase_two_gaps_projection(items),
        "status.md": _phase_two_status_projection(items),
    }
    codes = {
        "capabilities/gaps.md": "PHASE_TWO_GAPS_PROJECTION_STALE",
        "status.md": "PHASE_TWO_STATUS_PROJECTION_STALE",
    }
    for relative, expected in expected_text.items():
        path = package.root / relative
        try:
            actual = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            actual = ""
        if actual != expected:
            issues.append(_issue(codes[relative], path, "regenerate from capability registry"))
    return issues


def write_phase_two_projections(root: Path) -> None:
    package = load_foundation(root)
    registry_value = package.documents.get("capabilities/registry.yaml")
    raw_items = registry_value.get("items") if isinstance(registry_value, dict) else None
    items = (
        [cast(dict[str, JsonValue], item) for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
    (root / "catalog/claims.yaml").write_text(
        yaml.safe_dump(_phase_two_claims_projection(package, items), sort_keys=False),
        encoding="utf-8",
    )
    (root / "capabilities/gaps.md").write_text(_phase_two_gaps_projection(items), encoding="utf-8")
    (root / "status.md").write_text(_phase_two_status_projection(items), encoding="utf-8")


def _markdown_heading_slugs(markdown: str) -> set[str]:
    headings = re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", markdown)
    return {re.sub(r"[^a-z0-9_ -]", "", heading.lower()).replace(" ", "-") for heading in headings}


def _validate_synthesis_report_anchors(
    package: FoundationPackage,
    evidence_items: list[dict[str, JsonValue]],
    snapshot_paths: dict[str, set[str]],
    source_text: dict[str, str],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for index, item in enumerate(evidence_items):
        if item.get("source_kind") != "audit-report" and item.get("provenance_role") != "synthesis":
            continue
        location = f"{package.root / 'catalog/evidence.yaml'}:items[{index}]"
        path = item.get("path")
        symbol = item.get("symbol")
        source_label = item.get("source_label")
        snapshot_id = item.get("snapshot_id")
        snapshot_path = item.get("snapshot_path")
        fields = {
            "path": path,
            "symbol": symbol,
            "source_label": source_label,
            "snapshot_id": snapshot_id,
            "snapshot_path": snapshot_path,
        }
        for field, value in fields.items():
            if not isinstance(value, str) or not value.strip():
                issues.append(_issue("SYNTHESIS_EVIDENCE_FIELD_MISSING", location, field))
        if not isinstance(path, str) or not path.strip() or "#" not in path:
            if isinstance(path, str) and path.strip():
                issues.append(_issue("SYNTHESIS_EVIDENCE_PATH_ANCHOR_MISSING", location, path))
            continue
        report_path, anchor = path.split("#", maxsplit=1)
        if not anchor:
            issues.append(_issue("SYNTHESIS_EVIDENCE_PATH_ANCHOR_MISSING", location, path))
            continue
        if not isinstance(snapshot_id, str) or not isinstance(snapshot_path, str):
            continue
        if snapshot_path != report_path:
            issues.append(
                _issue("SYNTHESIS_EVIDENCE_SNAPSHOT_PATH_MISMATCH", location, report_path)
            )
        if report_path not in snapshot_paths.get(snapshot_id, set()):
            issues.append(
                _issue("SYNTHESIS_EVIDENCE_SNAPSHOT_PATH_UNRESOLVED", location, report_path)
            )
        if report_path not in snapshot_paths.get(
            snapshot_id, set()
        ) or anchor not in _markdown_heading_slugs(source_text.get(report_path, "")):
            issues.append(_issue("SYNTHESIS_REPORT_ANCHOR_UNRESOLVED", location, path))
        source_reports: set[str] = (
            set(cast(list[str], re.findall(r"([A-Za-z0-9_-]+\.md)#", source_label)))
            if isinstance(source_label, str)
            else set()
        )
        if source_reports and Path(report_path).name not in source_reports:
            issues.append(_issue("SYNTHESIS_REPORT_SOURCE_LABEL_MISMATCH", location, source_label))
    return issues


def _has_valid_direct_locator(
    item: dict[str, JsonValue], snapshot_paths: dict[str, set[str]]
) -> bool:
    path = item.get("path")
    symbol = item.get("symbol")
    snapshot_id = item.get("snapshot_id")
    snapshot_path = item.get("snapshot_path")
    return (
        isinstance(path, str)
        and bool(path.strip())
        and isinstance(symbol, str)
        and bool(symbol.strip())
        and isinstance(snapshot_id, str)
        and bool(snapshot_id.strip())
        and isinstance(snapshot_path, str)
        and bool(snapshot_path.strip())
        and path == snapshot_path
        and snapshot_path in snapshot_paths.get(snapshot_id, set())
    )


def _is_direct_evidence(item: dict[str, JsonValue]) -> bool:
    return (
        item.get("provenance_role") == "direct"
        or item.get("source_kind") in DIRECT_EVIDENCE_SOURCE_KINDS
    )


STATUS_BASIS_DIMENSIONS = (
    "implementation",
    "test",
    "documentation",
    "capability",
    "epistemic",
)
STATUS_ADJUDICATION_PREFIXES = ("REL-", "STA-", "ACT-", "EVI-", "INV-")
GENERIC_STATUS_BASES = {
    "carrier exists",
    "evidence",
    "n a",
    "no evidence",
    "none",
    "not applicable",
    "not assessed",
    "same as above",
    "tbd",
    "unknown",
    "unspecified",
}


def _normalized_status_basis(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _basis_test_locator_is_snapshot_resolvable(
    basis: str,
    snapshot_paths: dict[str, set[str]],
    repository_root: Path,
    active_snapshot_hashes: dict[str, str],
) -> bool:
    """Resolve only exact pytest symbols whose active-snapshot bytes remain current."""
    locator_pattern = re.compile(r"(tests/[\w/.-]+\.py)::([A-Za-z_]\w*)(?:::(test_[A-Za-z_]\w*))?")
    if re.search(r"tests/[\w/.-]+\.py::[A-Za-z_]\w*::(?!test_)[A-Za-z_]\w*", basis):
        return False
    locators = locator_pattern.findall(basis)
    if not locators:
        return False
    active_paths = set(active_snapshot_hashes)
    for path, first, method in locators:
        if (not method and not first.startswith("test_")) or (
            method and not first.startswith("Test")
        ):
            return False
        if path not in active_paths or path not in set().union(*snapshot_paths.values()):
            return False
        candidate = repository_root / path
        try:
            content = candidate.read_bytes()
            tree = ast.parse(content, filename=path)
        except (OSError, SyntaxError):
            return False
        if hashlib.sha256(content).hexdigest() != active_snapshot_hashes[path]:
            return False
        if not method:
            if not any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == first
                for node in tree.body
            ):
                return False
        else:
            matching_class = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == first
                ),
                None,
            )
            if matching_class is None or not any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method
                for node in matching_class.body
            ):
                return False
    return True


def _exact_test_locators_are_snapshot_resolvable(
    locators: object,
    snapshot_paths: dict[str, set[str]],
    repository_root: Path,
    active_snapshot_hashes: dict[str, str],
) -> bool:
    """Resolve a non-empty list of exact pytest function or class-method locators."""
    if not isinstance(locators, list) or not locators:
        return False
    exact = re.compile(r"tests/[\w/.-]+\.py::[A-Za-z_]\w*(?:::(?:test_)[A-Za-z_]\w*)?")
    return all(
        isinstance(locator, str)
        and exact.fullmatch(locator) is not None
        and _basis_test_locator_is_snapshot_resolvable(
            locator, snapshot_paths, repository_root, active_snapshot_hashes
        )
        for locator in locators
    )


def _yaml_ids(value: object) -> set[str]:
    identifiers: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"id", "canonical_id"} and isinstance(child, str):
                identifiers.add(child)
            identifiers.update(_yaml_ids(child))
    elif isinstance(value, list):
        for child in value:
            identifiers.update(_yaml_ids(child))
    return identifiers


def _implementation_locator_is_snapshot_resolvable(
    locator: str, repository_root: Path, active_snapshot_hashes: dict[str, str]
) -> bool:
    """Resolve one exact Python symbol or YAML id against current snapshot bytes."""
    match = re.fullmatch(
        r"(?P<path>[A-Za-z0-9_./-]+\.(?P<suffix>py|ya?ml))::"
        r"(?P<symbol>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*|[A-Z][A-Z0-9]*-\d+)",
        locator,
    )
    if match is None:
        return False
    path = match.group("path")
    symbol = match.group("symbol")
    expected_hash = active_snapshot_hashes.get(path)
    candidate = repository_root / path
    try:
        content = candidate.read_bytes()
    except OSError:
        return False
    if expected_hash != hashlib.sha256(content).hexdigest():
        return False
    if match.group("suffix") in {"yaml", "yml"}:
        try:
            value = yaml.safe_load(content)
        except yaml.YAMLError:
            return False
        return symbol in _yaml_ids(value)
    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError:
        return False
    parent, *members = symbol.split(".")
    top_level = next(
        (
            node
            for node in tree.body
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name == parent
            )
            or (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == parent
            )
            or (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == parent for target in node.targets
                )
            )
        ),
        None,
    )
    if top_level is None:
        # MCP server tool functions are registered inside the server factory;
        # their stable public callable names remain exact AST symbols even
        # though they are not module-level declarations.
        return not members and any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == parent
            for node in ast.walk(tree)
        )
    current = top_level
    for member in members:
        body = (
            current.body
            if isinstance(current, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            else []
        )
        current = next(
            (
                node
                for node in body
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and node.name == member
                )
                or (
                    isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.target.id == member
                )
                or (
                    isinstance(node, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == member
                        for target in node.targets
                    )
                )
            ),
            None,
        )
        if current is None:
            return False
    return True


def _implementation_locators_are_snapshot_resolvable(
    locators: object, repository_root: Path, active_snapshot_hashes: dict[str, str]
) -> bool:
    return (
        isinstance(locators, list)
        and bool(locators)
        and all(
            isinstance(locator, str)
            and _implementation_locator_is_snapshot_resolvable(
                locator, repository_root, active_snapshot_hashes
            )
            for locator in locators
        )
    )


def _expected_status_scope_ids() -> set[str]:
    return (
        {f"REL-{number}" for number in range(1, 36)}
        | ({f"STA-{number}" for number in range(1, 76)} - {"STA-28"})
        | {f"ACT-{number}" for number in range(1, 87)}
        | {f"EVI-{number}" for number in range(1, 10)}
        | {f"INV-{number}" for number in range(2, 8)}
    )


def _reciprocal_unresolved_issue(
    identifier: str,
    record: dict[str, JsonValue],
    conflicts: list[dict[str, JsonValue]],
    questions: list[dict[str, JsonValue]],
    *,
    conflict_only: bool = False,
) -> bool:
    conflict_ids = set(_string_list(record.get("conflict_ids")))
    if any(
        item.get("id") in conflict_ids
        and item.get("status") == "unresolved"
        and identifier in _string_list(item.get("affected_ids"))
        for item in conflicts
    ):
        return True
    if conflict_only:
        return False
    question_ids = set(_string_list(record.get("question_ids")))
    return any(
        item.get("id") in question_ids
        and item.get("status") != "resolved"
        and identifier in _string_list(item.get("affected_ids"))
        for item in questions
    )


def _validate_status_evidence_reviews(
    package: FoundationPackage,
    records: dict[str, tuple[str, dict[str, JsonValue]]],
    active_snapshot_id: str,
) -> list[ValidationIssue]:
    """Mechanically bind every status claim to its independently reviewed locator rows."""
    path = package.root / "catalog/status-evidence-reviews.yaml"
    raw = package.documents.get("catalog/status-evidence-reviews.yaml")
    issues: list[ValidationIssue] = []
    try:
        catalog = StatusEvidenceReviewCatalog.model_validate(raw)
    except ValidationError as error:
        return [_issue("STATUS_EVIDENCE_REVIEW_CATALOG_INVALID", path, error)]

    expected_digest = f"sha256:{hashlib.sha256((package.root / 'catalog/status-scope.yaml').read_bytes()).hexdigest()}"
    if catalog.metadata.scope_manifest_digest != expected_digest:
        issues.append(_issue("STATUS_EVIDENCE_REVIEW_METADATA_MISMATCH", path, "scope digest"))
    if catalog.metadata.active_snapshot_id != active_snapshot_id:
        issues.append(_issue("STATUS_EVIDENCE_REVIEW_METADATA_MISMATCH", path, "active snapshot"))

    review_ids = [review.review_id for review in catalog.reviews]
    summary_ids = [summary.review_id for summary in catalog.dimension_reviews]
    if len(review_ids) != len(set(review_ids)):
        issues.append(_issue("STATUS_EVIDENCE_REVIEW_ID_INVALID", path, "SER ids"))
    if len(summary_ids) != len(set(summary_ids)):
        issues.append(_issue("STATUS_EVIDENCE_DIMENSION_ID_INVALID", path, "SDR ids"))

    rows_by_key: dict[tuple[str, str], list[StatusEvidenceLocatorReview]] = {}
    for row in catalog.reviews:
        key = (row.record_id, row.dimension)
        rows_by_key.setdefault(key, []).append(row)
        if row.record_id not in records:
            issues.append(_issue("STATUS_EVIDENCE_REVIEW_UNKNOWN_RECORD", path, row.review_id))
        if row.dimension == "test":
            if row.admission == "admitted" and row.verdict not in {"proves", "partially-proves"}:
                issues.append(_issue("STATUS_EVIDENCE_TEST_ADMISSION_INVALID", path, row.review_id))
            if row.admission == "bounded" and row.verdict != "partially-proves":
                issues.append(_issue("STATUS_EVIDENCE_TEST_BOUNDARY_INVALID", path, row.review_id))
            if row.admission == "rejected" and row.verdict not in {"does-not-prove", "contradicts"}:
                issues.append(_issue("STATUS_EVIDENCE_TEST_REJECTION_INVALID", path, row.review_id))
        elif row.admission == "admitted" and row.verdict not in {"proves", "partially-proves"}:
            issues.append(
                _issue("STATUS_EVIDENCE_IMPLEMENTATION_ADMISSION_INVALID", path, row.review_id)
            )

    summaries_by_key: dict[tuple[str, str], StatusEvidenceDimensionReview] = {}
    canonical_status_field = {
        "implementation": "implementation_status",
        "test": "test_status",
        "documentation": "documentation_status",
        "capability": "capability_status",
        "epistemic": "epistemic_status",
    }
    evidence_document = package.documents.get("catalog/evidence.yaml")
    evidence_ids = (
        {
            item.get("id")
            for item in evidence_document.get("items", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if isinstance(evidence_document, dict)
        else set()
    )
    conflicts_document = package.documents.get("catalog/conflicts.yaml")
    conflicts = (
        {
            item.get("id"): item
            for item in conflicts_document.get("items", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if isinstance(conflicts_document, dict)
        else {}
    )
    registry = package.documents.get("capabilities/registry.yaml")
    capability_statuses = (
        {
            item.get("id"): item.get("capability_status")
            for item in registry.get("items", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if isinstance(registry, dict)
        else {}
    )
    derivation_ids = {
        value.get("id")
        for relative, value in package.documents.items()
        if relative.startswith("capabilities/derivations/")
        and isinstance(value, dict)
        and isinstance(value.get("id"), str)
    }
    for summary in catalog.dimension_reviews:
        key = (summary.record_id, summary.dimension)
        if summary.record_id not in records:
            issues.append(
                _issue("STATUS_EVIDENCE_DIMENSION_UNKNOWN_RECORD", path, summary.review_id)
            )
        if key in summaries_by_key:
            issues.append(
                _issue("STATUS_EVIDENCE_DIMENSION_SUMMARY_DUPLICATE", path, summary.record_id)
            )
        summaries_by_key[key] = summary

    for identifier, (record_path, record) in records.items():
        location = package.root / record_path
        for dimension in STATUS_BASIS_DIMENSIONS:
            key = (identifier, dimension)
            summary = summaries_by_key.get(key)
            rows = rows_by_key.get(key, [])
            if summary is None:
                issues.append(
                    _issue("STATUS_EVIDENCE_DIMENSION_SUMMARY_MISSING", location, identifier)
                )
                continue
            if (
                summary.compatible_status != record.get(canonical_status_field[dimension])
                or len(
                    {
                        summary.record_proposition,
                        summary.observed_fact,
                        summary.boundary,
                        summary.rationale,
                    }
                )
                < 4
                or any(
                    len(value.strip()) < 20
                    for value in (
                        summary.record_proposition,
                        summary.observed_fact,
                        summary.boundary,
                        summary.rationale,
                    )
                )
            ):
                issues.append(
                    _issue("STATUS_EVIDENCE_DIMENSION_CANONICAL_MISMATCH", location, identifier)
                )
            if (
                not set(summary.evidence_ids) <= evidence_ids
                or set(summary.conflict_ids) != set(_string_list(record.get("conflict_ids")))
                or set(summary.question_ids) != set(_string_list(record.get("question_ids")))
            ):
                issues.append(
                    _issue("STATUS_EVIDENCE_DIMENSION_REFERENCES_INVALID", location, identifier)
                )
            expected_locators = (
                _string_list(record.get("implementation_locators"))
                if dimension == "implementation"
                else (
                    _string_list(record.get("test_locators"))
                    + _string_list(record.get("bounded_test_locators"))
                    if dimension == "test"
                    else []
                )
            )
            expected_row_keys = {(identifier, dimension, locator) for locator in expected_locators}
            expected_row_keys.update(
                (identifier, dimension, row.locator)
                for row in rows
                if row.admission == "rejected" and row.locator is not None
            )
            if dimension == "implementation" and record.get("implementation_status") == "absent":
                expected_row_keys.add((identifier, dimension, None))
            actual_row_keys = {(row.record_id, row.dimension, row.locator) for row in rows}
            if actual_row_keys != expected_row_keys or len(rows) != len(actual_row_keys):
                issues.append(
                    _issue("STATUS_EVIDENCE_LOCATOR_PARTITION_INVALID", location, identifier)
                )

            row_by_id = {row.review_id: row for row in rows}
            listed = (
                summary.admitted_locators + summary.bounded_locators + summary.rejected_locators
            )
            if len(listed) != len(set(listed)) or set(listed) != set(row_by_id):
                issues.append(
                    _issue("STATUS_EVIDENCE_SUMMARY_PARTITION_INVALID", location, identifier)
                )
            for admission, values in (
                ("admitted", summary.admitted_locators),
                ("bounded", summary.bounded_locators),
                ("rejected", summary.rejected_locators),
            ):
                if any(
                    row_by_id.get(value) is None or row_by_id[value].admission != admission
                    for value in values
                ):
                    issues.append(
                        _issue("STATUS_EVIDENCE_SUMMARY_PARTITION_INVALID", location, identifier)
                    )
                    break

            admitted = [
                row_by_id[value] for value in summary.admitted_locators if value in row_by_id
            ]
            bounded = [row_by_id[value] for value in summary.bounded_locators if value in row_by_id]
            rejected = [
                row_by_id[value] for value in summary.rejected_locators if value in row_by_id
            ]
            if dimension == "test":
                required_clauses = summary.required_clause_ids
                required_clause_set = set(required_clauses)
                clauses_are_complete = (
                    _nonempty_string_list(required_clauses)
                    and len(required_clauses) == len(required_clause_set)
                    and set(summary.clauses) == required_clause_set
                    and all(value.strip() for value in summary.clauses.values())
                )
                all_row_clauses_are_known = all(
                    set(row.covered_clause_ids) <= required_clause_set for row in rows
                )
                admitted_coverage = (
                    set().union(*(set(row.covered_clause_ids) for row in admitted))
                    if admitted
                    else set()
                )
                partial_coverages = [
                    set(row.covered_clause_ids)
                    for row in admitted
                    if row.verdict == "partially-proves"
                ]
                partials_are_complementary = all(
                    left and right and not left.intersection(right)
                    for index, left in enumerate(partial_coverages)
                    for right in partial_coverages[index + 1 :]
                )
                if (
                    not clauses_are_complete
                    or not all_row_clauses_are_known
                    or not partials_are_complementary
                    or any(
                        row.locator in _string_list(record.get("bounded_test_locators"))
                        for row in admitted
                    )
                    or (
                        summary.combined_verdict == "proves"
                        and admitted_coverage != required_clause_set
                    )
                    or (
                        summary.combined_verdict == "unexercised"
                        and admitted_coverage == required_clause_set
                    )
                ):
                    issues.append(
                        _issue("STATUS_EVIDENCE_CLAUSE_COVERAGE_INVALID", location, identifier)
                    )
                admitted_proving = [row for row in admitted if row.verdict == "proves"]
                admitted_composition_proves = bool(admitted_proving) or (
                    len(partial_coverages) >= 2
                    and partials_are_complementary
                    and admitted_coverage == required_clause_set
                )
                active_rejected = [row for row in rejected if row.locator in expected_locators]
                expected_status = (
                    "exercised"
                    if admitted_composition_proves and not active_rejected
                    else "unexercised"
                )
                if summary.compatible_status != expected_status or (
                    summary.combined_verdict != "proves"
                    if expected_status == "exercised"
                    else summary.combined_verdict != "unexercised"
                ):
                    issues.append(
                        _issue("STATUS_EVIDENCE_SUMMARY_STATUS_INVALID", location, identifier)
                    )
                if any(row.locator in _string_list(record.get("test_locators")) for row in bounded):
                    issues.append(
                        _issue("STATUS_EVIDENCE_TEST_PARTIAL_EXACT", location, identifier)
                    )
                if rejected and any(row.locator in expected_locators for row in rejected):
                    issues.append(
                        _issue("STATUS_EVIDENCE_REJECTED_LOCATOR_ACTIVE", location, identifier)
                    )
                if record.get("test_status") != summary.compatible_status:
                    issues.append(
                        _issue("STATUS_EVIDENCE_CANONICAL_STATUS_MISMATCH", location, identifier)
                    )
                admitted_locators = [row.locator for row in admitted if row.locator is not None]
                bounded_locators = [row.locator for row in bounded if row.locator is not None]
                if (
                    _string_list(record.get("test_locators")) != admitted_locators
                    or _string_list(record.get("bounded_test_locators")) != bounded_locators
                ):
                    issues.append(
                        _issue(
                            "STATUS_EVIDENCE_CANONICAL_TEST_PARTITION_MISMATCH",
                            location,
                            identifier,
                        )
                    )
            elif dimension == "implementation":
                canonical_status = record.get("implementation_status")
                canonical_paths = {locator.partition("::")[0] for locator in expected_locators}
                if record_path in canonical_paths:
                    issues.append(_issue("STATUS_EVIDENCE_SELF_PROOF", location, identifier))
                if canonical_status == "absent":
                    if not (
                        summary.combined_verdict == "absent"
                        and summary.compatible_status == "absent"
                        and len(rows) == 1
                        and rows[0].locator is None
                    ):
                        issues.append(
                            _issue(
                                "STATUS_EVIDENCE_IMPLEMENTATION_ABSENCE_INVALID",
                                location,
                                identifier,
                            )
                        )
                elif canonical_status == "present":
                    if not (
                        summary.combined_verdict == "proves"
                        and summary.compatible_status == "present"
                        and admitted
                        and summary.rationale.strip()
                    ):
                        issues.append(
                            _issue("STATUS_EVIDENCE_SUMMARY_STATUS_INVALID", location, identifier)
                        )
                elif canonical_status == "partial" and not (
                    summary.combined_verdict == "partially-proves"
                    and summary.compatible_status == "partial"
                    and (admitted or bounded)
                    and (summary.uncovered_boundary.strip() or summary.boundary.strip())
                ):
                    issues.append(
                        _issue("STATUS_EVIDENCE_SUMMARY_STATUS_INVALID", location, identifier)
                    )
                if canonical_status != summary.compatible_status:
                    issues.append(
                        _issue("STATUS_EVIDENCE_CANONICAL_STATUS_MISMATCH", location, identifier)
                    )
            elif dimension == "documentation":
                unresolved_reciprocal = any(
                    conflict_id in conflicts
                    and conflicts[conflict_id].get("status") == "unresolved"
                    and identifier in _string_list(conflicts[conflict_id].get("affected_ids"))
                    for conflict_id in summary.conflict_ids
                )
                documentation_evidence_resolves = (
                    bool(summary.documentation_evidence_ids)
                    and set(summary.documentation_evidence_ids) <= evidence_ids
                )
                documented = (
                    summary.combined_verdict == "proves"
                    and documentation_evidence_resolves
                    and summary.freshness_state == "current"
                )
                conflicting = (
                    summary.combined_verdict == "contradicts"
                    and bool(summary.contradiction_clauses)
                    and unresolved_reciprocal
                )
                unknown = "unknown" in summary.boundary.casefold()
                if not (
                    (summary.compatible_status == "documented" and documented)
                    or (summary.compatible_status == "conflicting" and conflicting)
                    or (summary.compatible_status == "unknown" and unknown)
                    or (
                        summary.compatible_status == "stale"
                        and bool(summary.freshness_boundary.strip())
                        and bool(summary.evidence_age.strip())
                    )
                    or (
                        summary.compatible_status == "undocumented"
                        and bool(summary.missing_documentation_boundary.strip())
                        and not summary.documentation_evidence_ids
                    )
                ):
                    issues.append(
                        _issue("STATUS_EVIDENCE_DOCUMENTATION_STATUS_INVALID", location, identifier)
                    )
            elif dimension == "capability":
                expected_verdict = {
                    "current": "proves",
                    "derived": "proves",
                    "proposed": "proposed",
                    "gap": "absent",
                    "unknown": "unknown",
                }.get(summary.compatible_status)
                capability_records = registry.get("items", []) if isinstance(registry, dict) else []
                linked_capability_authority = any(
                    isinstance(capability, dict)
                    and capability.get("capability_status") in {"current", "derived"}
                    and identifier in str(capability.get("implementation_carrier_bindings", []))
                    for capability in capability_records
                )
                authority_statuses = [
                    capability_statuses.get(value) for value in summary.authority_ids
                ]
                authority_ids_resolve = len(summary.authority_ids) == len(
                    set(summary.authority_ids)
                ) and all(status is not None for status in authority_statuses)
                matching_authority = (
                    bool(summary.authority_ids)
                    and authority_ids_resolve
                    and all(status == summary.compatible_status for status in authority_statuses)
                )
                valid_capability_status = summary.combined_verdict == expected_verdict and (
                    summary.compatible_status in {"current", "derived", "proposed"}
                    and matching_authority
                    and (linked_capability_authority or summary.compatible_status == "proposed")
                    or summary.compatible_status == "unknown"
                    and bool(summary.unresolved_boundary.strip())
                    and authority_ids_resolve
                    and not any(
                        status in {"current", "derived", "proposed"}
                        for status in authority_statuses
                    )
                    or summary.compatible_status == "gap"
                    and bool(summary.gap_contract_ids)
                    and all(
                        capability_statuses.get(value) == "gap"
                        for value in summary.gap_contract_ids
                    )
                )
                if not valid_capability_status:
                    issues.append(
                        _issue("STATUS_EVIDENCE_CAPABILITY_STATUS_INVALID", location, identifier)
                    )
            elif dimension == "epistemic":
                valid = (
                    (
                        summary.compatible_status == "observed"
                        and summary.combined_verdict == "proves"
                        and bool(summary.observation_evidence_ids)
                        and set(summary.observation_evidence_ids) <= evidence_ids
                    )
                    or (
                        summary.compatible_status == "deterministically-derived"
                        and summary.combined_verdict == "proves"
                        and bool(summary.derivation_contract_ids)
                        and set(summary.derivation_contract_ids) <= derivation_ids
                    )
                    or (
                        summary.compatible_status == "inferred"
                        and summary.combined_verdict == "partially-proves"
                        and bool(summary.inference_rule.strip())
                        and bool(summary.inference_evidence_ids)
                        and set(summary.inference_evidence_ids) <= evidence_ids
                    )
                    or (
                        summary.compatible_status == "operator-asserted"
                        and summary.combined_verdict == "proves"
                        and bool(summary.assertion_evidence_ids)
                        and set(summary.assertion_evidence_ids) <= evidence_ids
                    )
                    or (
                        summary.compatible_status == "proposed"
                        and summary.combined_verdict == "proposed"
                        and bool(summary.proposal_authority_ids)
                        and set(summary.proposal_authority_ids) <= evidence_ids
                    )
                    or (
                        summary.compatible_status == "unknown"
                        and bool(summary.unresolved_boundary.strip())
                    )
                )
                if not valid:
                    issues.append(
                        _issue("STATUS_EVIDENCE_EPISTEMIC_STATUS_INVALID", location, identifier)
                    )
    return issues


def _validate_status_scope(
    package: FoundationPackage,
    active_snapshot_hashes: dict[str, str],
    conflicts: list[dict[str, JsonValue]],
    questions: list[dict[str, JsonValue]],
) -> list[ValidationIssue]:
    """Validate every active SV-008 record through one mechanical path."""
    issues: list[ValidationIssue] = []
    expected_ids = _expected_status_scope_ids()
    scope_path = package.root / "catalog/status-scope.yaml"
    scope = package.documents.get("catalog/status-scope.yaml")
    raw_scope_items = scope.get("items") if isinstance(scope, dict) else None
    scope_items = raw_scope_items if isinstance(raw_scope_items, list) else []
    manifest: dict[str, str] = {}
    manifest_counts: dict[str, int] = {}
    for item in scope_items:
        if not isinstance(item, dict):
            continue
        identifier, path = item.get("id"), item.get("path")
        if not isinstance(identifier, str) or not isinstance(path, str):
            issues.append(_issue("STATUS_SCOPE_ITEM_INVALID", scope_path, item))
            continue
        manifest_counts[identifier] = manifest_counts.get(identifier, 0) + 1
        manifest.setdefault(identifier, path)
    for identifier, count in manifest_counts.items():
        if count != 1:
            issues.append(_issue("STATUS_SCOPE_DUPLICATE", scope_path, identifier))
    manifest_ids = set(manifest)
    if "STA-28" in manifest_ids:
        issues.append(_issue("STATUS_SCOPE_REACTIVATED", scope_path, "STA-28"))
    for identifier in sorted(expected_ids - manifest_ids):
        issues.append(_issue("STATUS_SCOPE_MISSING", scope_path, identifier))
    for identifier in sorted(manifest_ids - expected_ids - {"STA-28"}):
        issues.append(_issue("STATUS_SCOPE_EXTRA", scope_path, identifier))

    declarations: list[tuple[str, str, dict[str, JsonValue]]] = []
    fixed = {
        "reality/relationships.yaml": "REL-",
        "reality/state-model.yaml": "STA-",
        "reality/evidence/inventory.yaml": "EVI-",
        "catalog/invariants.yaml": "INV-",
    }
    for path, prefix in fixed.items():
        document = package.documents.get(path)
        items = document.get("items") if isinstance(document, dict) else None
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            identifier = cast(str, item["id"])
            excluded_invariants = {"INV-1", "INV-8", "INV-9", "INV-10", "INV-11"}
            if identifier.startswith(STATUS_ADJUDICATION_PREFIXES) and (
                not identifier.startswith("INV-") or identifier not in excluded_invariants
            ):
                declarations.append((identifier, path, cast(dict[str, JsonValue], item)))
                if not identifier.startswith(prefix):
                    issues.append(
                        _issue("STATUS_SCOPE_WRONG_FAMILY", package.root / path, identifier)
                    )
    for path, value in package.documents.items():
        if not path.startswith("reality/actions/") or not isinstance(value, dict):
            continue
        identifier = value.get("id")
        if isinstance(identifier, str):
            declarations.append((identifier, path, value))
            if not identifier.startswith("ACT-"):
                issues.append(_issue("STATUS_SCOPE_WRONG_FAMILY", package.root / path, identifier))

    actual_counts: dict[str, int] = {}
    for identifier, _, _ in declarations:
        actual_counts[identifier] = actual_counts.get(identifier, 0) + 1
    for identifier in sorted(expected_ids):
        count = actual_counts.get(identifier, 0)
        if count == 0:
            issues.append(_issue("STATUS_SCOPE_DECLARATION_MISSING", scope_path, identifier))
        elif count > 1:
            issues.append(_issue("STATUS_SCOPE_DECLARATION_DUPLICATE", scope_path, identifier))

    repository_root = package.root.parents[1]
    family_records: dict[str, list[dict[str, JsonValue]]] = {}
    status_records: dict[str, tuple[str, dict[str, JsonValue]]] = {}
    exercised_locators: set[str] = set()
    permitted_locators: set[str] = set()
    for identifier, path, record in declarations:
        if identifier not in expected_ids:
            if identifier == "STA-28":
                issues.append(_issue("STATUS_SCOPE_REACTIVATED", package.root / path, identifier))
            elif identifier.startswith(STATUS_ADJUDICATION_PREFIXES):
                issues.append(_issue("STATUS_SCOPE_EXTRA", package.root / path, identifier))
            continue
        location = package.root / path
        if manifest.get(identifier) != path:
            issues.append(_issue("STATUS_SCOPE_WRONG_PATH", location, identifier))
        family_records.setdefault(identifier.split("-", 1)[0], []).append(record)
        status_records[identifier] = (path, record)

        basis = record.get("status_basis")
        if (
            not isinstance(basis, dict)
            or set(basis) != set(STATUS_BASIS_DIMENSIONS)
            or any(
                not isinstance(basis.get(dimension), str) or not str(basis[dimension]).strip()
                for dimension in STATUS_BASIS_DIMENSIONS
            )
        ):
            issues.append(_issue("STATUS_BASIS_MISSING", location, identifier))
        if isinstance(basis, dict) and any(
            isinstance(value, str) and _normalized_status_basis(value) in GENERIC_STATUS_BASES
            for value in basis.values()
        ):
            issues.append(_issue("STATUS_BASIS_GENERIC", location, identifier))

        for field in (
            "implementation_locators",
            "test_locators",
            "bounded_test_locators",
        ):
            values = record.get(field)
            if isinstance(values, list) and all(isinstance(value, str) for value in values):
                if len(values) != len({_normalized_list_value(value) for value in values}):
                    issues.append(_issue("STATUS_LOCATOR_DUPLICATE", location, field))

        implementation_status = record.get("implementation_status")
        implementation_locators = record.get("implementation_locators")
        has_implementation_locators = isinstance(implementation_locators, list) and bool(
            implementation_locators
        )
        if implementation_status in {"present", "partial"}:
            if not _implementation_locators_are_snapshot_resolvable(
                implementation_locators, repository_root, active_snapshot_hashes
            ) or any(
                isinstance(locator, str) and locator.partition("::")[0] == path
                for locator in implementation_locators
                if isinstance(implementation_locators, list)
            ):
                issues.append(_issue("IMPLEMENTATION_LOCATOR_UNRESOLVED", location, identifier))
        elif has_implementation_locators:
            code = (
                "ABSENT_IMPLEMENTATION_LOCATORS_NONEMPTY"
                if implementation_status == "absent"
                else "NONPRESENT_IMPLEMENTATION_LOCATORS_NONEMPTY"
            )
            issues.append(_issue(code, location, identifier))
        if (
            implementation_status == "absent"
            and identifier.startswith("ACT-")
            and record.get("executable") is not False
        ):
            issues.append(_issue("ABSENT_ACTION_EXECUTABLE", location, identifier))

        test_status = record.get("test_status")
        test_locators = record.get("test_locators")
        bounded_test_locators = record.get("bounded_test_locators")
        for locators in (test_locators, bounded_test_locators):
            if isinstance(locators, list):
                permitted_locators.update(
                    locator for locator in locators if isinstance(locator, str)
                )
        if test_status == "exercised":
            for locators in (test_locators, bounded_test_locators):
                if isinstance(locators, list):
                    exercised_locators.update(
                        locator for locator in locators if isinstance(locator, str)
                    )
        if test_status in {"exercised", "contradicted"}:
            if not isinstance(test_locators, list) or not test_locators:
                issues.append(_issue("EXERCISED_TEST_LOCATORS_EMPTY", location, identifier))
            elif not _exact_test_locators_are_snapshot_resolvable(
                test_locators,
                {"active": set(active_snapshot_hashes)},
                package.root.parents[1],
                active_snapshot_hashes,
            ):
                issues.append(_issue("EXERCISED_TEST_BASIS_UNRESOLVED", location, identifier))
            if test_status == "contradicted" and not _reciprocal_unresolved_issue(
                identifier, record, conflicts, questions, conflict_only=True
            ):
                issues.append(_issue("CONTRADICTED_TEST_CONFLICT_MISSING", location, identifier))
        elif isinstance(test_locators, list) and test_locators:
            issues.append(_issue("NONEXERCISED_TEST_LOCATORS_NONEMPTY", location, identifier))

        if record.get("documentation_status") == "conflicting" and not (
            _reciprocal_unresolved_issue(identifier, record, conflicts, questions)
        ):
            issues.append(
                _issue("CONFLICTING_STATUS_RECIPROCAL_ISSUE_MISSING", location, identifier)
            )

    for family, records in family_records.items():
        if (
            records
            and all(record.get("test_status") == "unexercised" for record in records)
            and any(record.get("test_locators") for record in records)
        ):
            issues.append(
                _issue(
                    "STATUS_FAMILY_MECHANICAL_UNEXERCISED",
                    scope_path,
                    family,
                )
            )
    evidence = package.documents.get("catalog/evidence.yaml")
    active_snapshot = _active_snapshot(evidence) if isinstance(evidence, dict) else None
    active_snapshot_id = active_snapshot.get("id") if isinstance(active_snapshot, dict) else None
    if isinstance(active_snapshot_id, str):
        issues.extend(
            _validate_status_evidence_reviews(package, status_records, active_snapshot_id)
        )
        issues.extend(
            _validate_status_test_manifest(
                package,
                active_snapshot_id,
                active_snapshot_hashes,
                exercised_locators,
                permitted_locators,
            )
        )
    return issues


def _validate_status_test_manifest(
    package: FoundationPackage,
    active_snapshot_id: str,
    active_snapshot_hashes: dict[str, str],
    exercised_locators: set[str],
    permitted_locators: set[str] | None = None,
) -> list[ValidationIssue]:
    """Validate the pytest-collected manifest as the exercised-test authority."""
    manifest_path = package.root / "catalog/status-test-nodes.yaml"
    manifest = package.documents.get("catalog/status-test-nodes.yaml")
    issues: list[ValidationIssue] = []
    if not isinstance(manifest, dict):
        return [_issue("STATUS_TEST_MANIFEST_MISSING", manifest_path, "required")]
    if (
        manifest.get("schema_version") != "1"
        or manifest.get("tool_schema") != "status-test-nodes/v1"
    ):
        issues.append(_issue("STATUS_TEST_MANIFEST_SCHEMA_INVALID", manifest_path, "schema"))
    if manifest.get("active_snapshot_id") != active_snapshot_id:
        issues.append(_issue("STATUS_TEST_MANIFEST_SNAPSHOT_MISMATCH", manifest_path, "snapshot"))
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        return issues + [_issue("STATUS_TEST_MANIFEST_ENTRIES_INVALID", manifest_path, "entries")]
    seen_bases: set[str] = set()
    seen_nodes: set[str] = set()
    manifest_bases: set[str] = set()
    for index, entry in enumerate(entries):
        location = f"{manifest_path}:entries[{index}]"
        if not isinstance(entry, dict):
            issues.append(_issue("STATUS_TEST_MANIFEST_ENTRY_INVALID", location, entry))
            continue
        base = entry.get("base_locator")
        path = entry.get("source_path")
        source_hash = entry.get("source_sha256")
        nodes = entry.get("concrete_node_ids")
        entry_snapshot = entry.get("active_snapshot_id")
        if not isinstance(base, str) or not isinstance(path, str) or not isinstance(nodes, list):
            issues.append(_issue("STATUS_TEST_MANIFEST_ENTRY_INVALID", location, entry))
            continue
        manifest_bases.add(base)
        if base in seen_bases:
            issues.append(_issue("STATUS_TEST_MANIFEST_DUPLICATE_LOCATOR", location, base))
        seen_bases.add(base)
        if base not in (
            permitted_locators if permitted_locators is not None else exercised_locators
        ):
            issues.append(_issue("STATUS_TEST_MANIFEST_UNKNOWN_BASE", location, base))
        if path != base.partition("::")[0]:
            issues.append(_issue("STATUS_TEST_MANIFEST_WRONG_SOURCE_PATH", location, base))
        expected_hash = active_snapshot_hashes.get(path)
        if expected_hash is None:
            issues.append(_issue("STATUS_TEST_MANIFEST_PATH_NOT_ACTIVE", location, path))
        elif source_hash != expected_hash:
            issues.append(_issue("STATUS_TEST_MANIFEST_STALE_HASH", location, path))
        if entry_snapshot != active_snapshot_id:
            issues.append(_issue("STATUS_TEST_MANIFEST_SNAPSHOT_MISMATCH", location, base))
        if not nodes:
            issues.append(_issue("STATUS_TEST_MANIFEST_NODES_EMPTY", location, base))
        for node in nodes:
            if (
                not isinstance(node, str)
                or not (node == base or node.startswith(f"{base}["))
                or (isinstance(node, str) and not node.endswith("]") and node != base)
            ):
                issues.append(_issue("STATUS_TEST_MANIFEST_NODE_MALFORMED", location, node))
                continue
            if node in seen_nodes:
                issues.append(_issue("STATUS_TEST_MANIFEST_DUPLICATE_NODE", location, node))
            seen_nodes.add(node)
    for base in sorted(exercised_locators - manifest_bases):
        issues.append(_issue("STATUS_TEST_MANIFEST_LOCATOR_MISSING", manifest_path, base))
    return issues


def _validate_entity_allocations(
    package: FoundationPackage,
    semantic_items: dict[str, SemanticItem],
    raw_allocations: object,
) -> list[ValidationIssue]:
    """Keep the entity namespace for durable identity carriers, not classifications."""
    issues: list[ValidationIssue] = []
    allocations = (
        [item for item in raw_allocations if isinstance(item, dict)]
        if isinstance(raw_allocations, list)
        else []
    )
    allocation_by_id = {
        item.get("canonical_id"): item
        for item in allocations
        if isinstance(item.get("canonical_id"), str)
    }
    for identifier, semantic in semantic_items.items():
        if not identifier.startswith("ENT-"):
            continue
        fields = ("identity", "ownership", "persistence", "lifecycle")
        values = [
            semantic.model_extra.get(field) if semantic.model_extra else None for field in fields
        ]
        invalid = any(
            not isinstance(value, str) or not value.strip() or value.strip().casefold() == "none"
            for value in values
        )
        allocation = allocation_by_id.get(identifier)
        location = package.root / "reality/domain-model.yaml"
        if invalid:
            issues.append(_issue("ENTITY_LIFECYCLE_FIELDS_INVALID", location, identifier))
            if not isinstance(allocation, dict) or allocation.get("status") == "active":
                issues.append(_issue("ENTITY_ALLOCATION_RETIREMENT_MISSING", location, identifier))
        elif isinstance(allocation, dict) and allocation.get("status") in {
            "rejected",
            "superseded",
        }:
            reason = allocation.get("retirement_reason")
            if not isinstance(reason, str) or not reason.strip():
                issues.append(_issue("ENTITY_ALLOCATION_RETIREMENT_MISSING", location, identifier))
    return issues


def _validate_semantic_evidence_admission(
    package: FoundationPackage,
    semantic_items: dict[str, SemanticItem],
    declarations: dict[str, str],
    evidence: dict[str, dict[str, JsonValue]],
    snapshot_paths: dict[str, set[str]],
    active_snapshot_hashes: dict[str, str],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for identifier, semantic in semantic_items.items():
        records = [
            evidence[evidence_id]
            for evidence_id in semantic.evidence_ids
            if evidence_id in evidence
        ]
        location = package.root / declarations.get(identifier, "unknown")
        status_basis = semantic.model_extra.get("status_basis") if semantic.model_extra else None
        test_locators = semantic.model_extra.get("test_locators") if semantic.model_extra else None
        approved_test_index = _exact_test_locators_are_snapshot_resolvable(
            test_locators,
            snapshot_paths,
            package.root.parents[1],
            active_snapshot_hashes,
        ) or (
            isinstance(status_basis, dict)
            and isinstance(status_basis.get("test"), str)
            and _basis_test_locator_is_snapshot_resolvable(
                status_basis["test"],
                snapshot_paths,
                package.root.parents[1],
                active_snapshot_hashes,
            )
        )
        if semantic.test_status == "exercised" and not (
            any(
                _is_direct_evidence(record)
                and record.get("source_kind") in DIRECT_TEST_SOURCE_KINDS
                and record.get("test_status") == "exercised"
                and _has_valid_direct_locator(record, snapshot_paths)
                for record in records
            )
            or approved_test_index
        ):
            issues.append(_issue("EXERCISED_DIRECT_TEST_EVIDENCE_MISSING", location, identifier))
        if semantic.capability_status == "current" and not any(
            _is_direct_evidence(record)
            and record.get("source_kind") in DIRECT_IMPLEMENTATION_SOURCE_KINDS
            and record.get("reachable") is True
            and _has_valid_direct_locator(record, snapshot_paths)
            for record in records
        ):
            issues.append(
                _issue("CURRENT_DIRECT_IMPLEMENTATION_EVIDENCE_MISSING", location, identifier)
            )
    return issues


def _validate_actions(
    package: FoundationPackage,
    declarations: dict[str, str],
    commands: dict[str, CommandDeclaration],
    evidence: dict[str, EvidenceRecord],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    state_value = package.documents.get("reality/state-model.yaml")
    state_items = state_value.get("items") if isinstance(state_value, dict) else None
    states: set[str] = set()
    if isinstance(state_items, list):
        for item in state_items:
            if not isinstance(item, dict):
                continue
            identifier = item.get("id")
            if isinstance(identifier, str) and identifier.startswith("STA-"):
                states.add(identifier)
    legal: set[tuple[str, str]] = set()
    if isinstance(state_value, dict):
        transitions = state_value.get("transitions")
        if isinstance(transitions, list):
            for index, transition in enumerate(transitions):
                try:
                    typed_transition = StateTransition.model_validate(transition)
                    legal.add((typed_transition.from_state_id, typed_transition.to_state_id))
                except ValidationError as error:
                    issues.append(
                        _issue(
                            "STATE_TRANSITION_INVALID",
                            f"{package.root / 'reality/state-model.yaml'}:transitions[{index}]",
                            error,
                        )
                    )
    absent_fields = (
        "required_outcome",
        "source_demand_ids",
        "implementation_constraints",
        "required_evidence",
        "unresolved_command_decisions",
    )
    for relative, action in package.documents.items():
        if not relative.startswith("reality/actions/"):
            continue
        path = package.root / relative
        if not isinstance(action, dict):
            issues.append(_issue("ACTION_CONTRACT_INVALID", path, "action root must be a mapping"))
            continue
        try:
            typed_action = ActionContract.model_validate(action)
            _declare(declarations, typed_action.id, relative, package, issues)
        except ValidationError as error:
            issues.append(_issue("ACTION_CONTRACT_INVALID", path, error))
        status_incompatible = (
            action.get("implementation_status") == "present"
            and (
                action.get("capability_status") not in {"current", "unknown"}
                or action.get("executable") is not True
            )
        ) or (
            action.get("capability_status") == "current"
            and (
                action.get("implementation_status") != "present"
                or action.get("executable") is not True
            )
        )
        if status_incompatible:
            issues.append(
                _issue(
                    "ACTION_STATUS_INCOMPATIBLE",
                    path,
                    "current executable action must be present and vice versa",
                )
            )
        if action.get("implementation_status") == "present":
            if action.get("enforced_authorization") in {None, "absent", "unknown"} and action.get(
                "proposed_role_policy"
            ):
                issues.append(
                    _issue(
                        "AUTHORITY_CONFLICT",
                        path,
                        "proposed role policy cannot substitute for enforced authorization",
                    )
                )
            command = action.get("command_id")
            if not isinstance(command, str) or not re.fullmatch(r"CMD-\d+", command):
                issues.append(_issue("ACTION_COMMAND_WRONG_NAMESPACE", path, command))
            elif command not in commands:
                issues.append(_issue("ACTION_COMMAND_UNRESOLVED", path, command))
            elif (
                commands[command].implementation_status != "present"
                or not commands[command].reachable
            ):
                issues.append(_issue("ACTION_COMMAND_UNAVAILABLE", path, command))
            resulting_state = action.get("resulting_state_id")
            if isinstance(resulting_state, str) and resulting_state not in states:
                issues.append(_issue("STATE_UNKNOWN", path, resulting_state))
            audit_evidence_ids = action.get("audit_evidence_ids")
            if isinstance(audit_evidence_ids, list):
                for evidence_id in audit_evidence_ids:
                    if isinstance(evidence_id, str) and evidence_id not in evidence:
                        issues.append(_issue("ACTION_AUDIT_EVIDENCE_UNRESOLVED", path, evidence_id))
            transition = action.get("transition")
            transition_variants = action.get("transition_variants")
            if isinstance(transition_variants, list):
                typed_variants: list[ActionTransitionVariant] = []
                for variant in transition_variants:
                    try:
                        typed_variants.append(ActionTransitionVariant.model_validate(variant))
                    except ValidationError:
                        continue
                variant_states = {
                    state
                    for variant in typed_variants
                    for state in (variant.from_state_id, variant.to_state_id)
                }
                for state in variant_states:
                    if state not in states:
                        issues.append(_issue("STATE_UNKNOWN", path, state))
                for variant in typed_variants:
                    if (variant.from_state_id, variant.to_state_id) not in legal:
                        issues.append(
                            _issue(
                                "ACTION_TRANSITION_UNREACHABLE",
                                path,
                                f"{variant.carrier}:{variant.from_state_id}->{variant.to_state_id}",
                            )
                        )
                    for evidence_id in variant.evidence_ids:
                        if evidence_id not in evidence:
                            issues.append(
                                _issue("ACTION_AUDIT_EVIDENCE_UNRESOLVED", path, evidence_id)
                            )
                        if (
                            isinstance(audit_evidence_ids, list)
                            and evidence_id not in audit_evidence_ids
                        ):
                            issues.append(
                                _issue("ACTION_VARIANT_EVIDENCE_NOT_AUDITED", path, evidence_id)
                            )
                resulting_state = action.get("resulting_state_id")
                if not isinstance(resulting_state, str) or resulting_state not in {
                    variant.to_state_id for variant in typed_variants
                }:
                    issues.append(
                        _issue(
                            "ACTION_RESULT_STATE_MISMATCH",
                            path,
                            "resulting_state_id must be a transition variant target",
                        )
                    )
                continue
            if not isinstance(transition, dict):
                issues.append(_issue("ACTION_TRANSITION_MISSING", path, "transition"))
                continue
            starts, ends = transition.get("from_state_ids"), transition.get("to_state_ids")
            if starts is None and isinstance(transition.get("from_state_id"), str):
                starts = [transition["from_state_id"]]
            if ends is None and isinstance(transition.get("to_state_id"), str):
                ends = [transition["to_state_id"]]
            if not isinstance(starts, list) or not starts or not isinstance(ends, list) or not ends:
                issues.append(
                    _issue(
                        "ACTION_TRANSITION_EMPTY",
                        path,
                        "from_state_ids and to_state_ids must be nonempty",
                    )
                )
            start_states = (
                [value for value in starts if isinstance(value, str)]
                if isinstance(starts, list)
                else []
            )
            end_states = (
                [value for value in ends if isinstance(value, str)]
                if isinstance(ends, list)
                else []
            )
            state_names = [*start_states, *end_states]
            for state in state_names:
                if state not in states:
                    issues.append(_issue("STATE_UNKNOWN", path, state))
            if (
                not start_states
                or not end_states
                or not any((start, end) in legal for start in start_states for end in end_states)
            ):
                issues.append(
                    _issue("ACTION_TRANSITION_UNREACHABLE", path, "no declared legal transition")
                )
            resulting_state = action.get("resulting_state_id")
            if (
                not isinstance(resulting_state, str)
                or resulting_state not in end_states
                or not any((start, resulting_state) in legal for start in start_states)
            ):
                issues.append(
                    _issue(
                        "ACTION_RESULT_STATE_MISMATCH",
                        path,
                        "resulting_state_id must be a legal transition target",
                    )
                )
        elif action.get("implementation_status") == "absent":
            if (
                action.get("capability_status") not in {"gap", "proposed", "unknown"}
                or action.get("executable") is not False
            ):
                issues.append(
                    _issue(
                        "ABSENT_INTERVENTION_INVALID",
                        path,
                        "must be a non-executable gap or proposal",
                    )
                )
            required_absent_fields = (
                tuple(field for field in absent_fields if field != "source_demand_ids")
                if action.get("capability_status") == "unknown"
                else absent_fields
            )
            for field in required_absent_fields:
                if action.get(field) in (None, "", []):
                    issues.append(_issue("ABSENT_INTERVENTION_REQUIREMENT_MISSING", path, field))
            completed_fields = (
                "command_id",
                "transition",
                "actor",
                "permission_requirements",
                "preconditions",
                "expected_source_version",
                "required_input",
                "validation",
                "durable_effect",
                "resulting_state_id",
                "failure_modes",
                "stale_state_behavior",
                "idempotency",
                "retry_behavior",
                "reversibility",
                "audit_evidence_ids",
            )
            present_completed = [
                field for field in completed_fields if action.get(field) not in (None, "", [])
            ]
            if present_completed:
                issues.append(
                    _issue(
                        "ABSENT_INTERVENTION_COMPLETED_SEMANTICS",
                        path,
                        ", ".join(present_completed),
                    )
                )
    return issues


def _validate_epistemics(
    package: FoundationPackage,
    canonical: dict[str, CanonicalDocument],
    evidence: dict[str, EvidenceRecord],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for relative in sorted(SEMANTIC_COLLECTIONS & canonical.keys()):
        for item in canonical[relative].items:
            causal = (
                item.get("causal") is True
                or item.get("relationship_type") == "causal"
                or item.get("claim_type") == "causal"
            )
            if causal and not item.get("epistemic_status"):
                issues.append(
                    _issue("CAUSAL_EPISTEMIC_MISSING", package.root / relative, item.get("id"))
                )
            if causal and not (item.get("evidence_ids") or item.get("evidence")):
                issues.append(
                    _issue("CAUSAL_EVIDENCE_MISSING", package.root / relative, item.get("id"))
                )
            if causal:
                epistemic = item.get("epistemic_status")
                evidence_ids = item.get("evidence_ids")
                referenced = (
                    [evidence[value] for value in evidence_ids if value in evidence]
                    if isinstance(evidence_ids, list)
                    else []
                )
                insufficient = epistemic not in {"observed", "deterministically-derived"}
                mechanism_missing = not any(
                    record.evidence_type == "causal-mechanism" for record in referenced
                )
                if insufficient:
                    issues.append(
                        _issue(
                            "CAUSAL_EPISTEMIC_INSUFFICIENT",
                            package.root / relative,
                            item.get("id"),
                        )
                    )
                if mechanism_missing:
                    issues.append(
                        _issue(
                            "CAUSAL_MECHANISM_EVIDENCE_MISSING",
                            package.root / relative,
                            item.get("id"),
                        )
                    )
                if insufficient or mechanism_missing:
                    issues.append(
                        _issue(
                            "CAUSAL_LABEL_UNRESOLVED",
                            package.root / relative,
                            item.get("id"),
                        )
                    )
            aliases = item.get("aliases")
            if isinstance(aliases, list) and any(
                isinstance(alias, str) and "/" in alias for alias in aliases
            ):
                issues.append(
                    _issue("SLASH_ALIAS_UNPROVEN", package.root / relative, item.get("id"))
                )
    return issues


def validate_required_files(package: FoundationPackage, phase: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for relative in (
        "schemas/semantic-item.schema.json",
        "schemas/review-feedback.schema.json",
    ):
        if relative not in package.existing_files:
            issues.append(
                _issue(
                    "REQUIRED_SCHEMA_MISSING", package.root / relative, "required at every phase"
                )
            )
    for required_phase in range(phase + 1):
        for relative in PHASE_FILES[required_phase]:
            if relative not in package.existing_files:
                issues.append(
                    _issue(
                        "REQUIRED_FILE_MISSING",
                        package.root / relative,
                        f"required for phase {required_phase}",
                    )
                )
    canonical, _ = _canonical_documents(package)
    if phase >= 1:
        for relative in PHASE_FILES[1]:
            document = canonical.get(relative)
            if document is not None and not document.items:
                issues.append(
                    _issue(
                        "PHASE_COLLECTION_INCOMPLETE",
                        package.root / relative,
                        "Phase 1 collection is empty",
                    )
                )
    if phase >= 2:
        registry = canonical.get("capabilities/registry.yaml")
        if registry is not None and not registry.items:
            issues.append(
                _issue(
                    "PHASE_COLLECTION_INCOMPLETE",
                    package.root / "capabilities/registry.yaml",
                    "Phase 2 capability registry is empty",
                )
            )
    return issues


def validate_schema_contracts(package: FoundationPackage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    expected_enums = {
        "implementation_status": IMPLEMENTATION_STATUSES,
        "test_status": TEST_STATUSES,
        "documentation_status": DOCUMENTATION_STATUSES,
        "capability_status": CAPABILITY_STATUSES,
        "epistemic_status": EPISTEMIC_STATUSES,
    }
    semantic_required = {
        "id",
        "title",
        "definition",
        "implementation_status",
        "test_status",
        "documentation_status",
        "confidence",
        "confidence_basis",
        "evidence_ids",
        "conflict_ids",
        "question_ids",
        "limitations",
        "prohibited_interpretations",
    }
    for relative, value in sorted(package.schemas.items()):
        path = package.root / relative
        try:
            schema = SchemaBoundary.model_validate(value)
        except ValidationError as error:
            issues.append(_issue("SCHEMA_INVALID", path, error))
            continue
        if path.name == "semantic-item.schema.json":
            if not semantic_required <= set(schema.required):
                issues.append(_issue("SCHEMA_CONTRACT_INVALID", path, "semantic required fields"))
            for field, expected in expected_enums.items():
                actual = schema.properties.get(field, {}).get("enum")
                if actual != list(expected):
                    issues.append(_issue("SCHEMA_CONTRACT_INVALID", path, field))
        elif path.name == "review-feedback.schema.json":
            required_export = {
                "schema_version",
                "review_version",
                "batch_id",
                "source_snapshot",
                "exported_at",
                "response_history",
            }
            if not required_export <= set(schema.required):
                issues.append(_issue("SCHEMA_CONTRACT_INVALID", path, "export required fields"))
            history = schema.properties.get("response_history")
            history_items = history.get("items") if isinstance(history, dict) else None
            history_required = (
                history_items.get("required") if isinstance(history_items, dict) else None
            )
            if not isinstance(history_required, list) or not {
                "item_id",
                "response",
                "note",
                "recorded_at",
            } <= {value for value in history_required if isinstance(value, str)}:
                issues.append(
                    _issue("SCHEMA_CONTRACT_INVALID", path, "response history required fields")
                )
            history_properties = (
                history_items.get("properties") if isinstance(history_items, dict) else None
            )
            response_schema = (
                history_properties.get("response") if isinstance(history_properties, dict) else None
            )
            response_values = (
                response_schema.get("enum") if isinstance(response_schema, dict) else None
            )
            if response_values != ["accept", "reject", "revise", "uncertain"]:
                issues.append(
                    _issue("SCHEMA_CONTRACT_INVALID", path, "response history response enum")
                )
    return issues


def validate_source_hashes(package: FoundationPackage, phase: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    value = package.documents.get("catalog/evidence.yaml")
    phase_one_snapshot = value.get("snapshot") if isinstance(value, dict) else None
    snapshot = _active_snapshot(value) if isinstance(value, dict) else None
    has_active_snapshot = isinstance(value, dict) and value.get("active_snapshot_id") is not None
    if not has_active_snapshot:
        issues.extend(validate_source_snapshot_coverage(package, phase_one_snapshot, phase))
    if has_active_snapshot:
        issues.extend(_validate_phase_one_snapshot_immutable(package, phase_one_snapshot))
        issues.extend(
            _validate_active_snapshot_lineage(package, phase_one_snapshot, snapshot, phase)
        )
    if isinstance(snapshot, dict):
        try:
            SourceSnapshot.model_validate(snapshot)
        except ValidationError as error:
            issues.append(
                _issue("SOURCE_SNAPSHOT_INVALID", package.root / "catalog/evidence.yaml", error)
            )
    elif snapshot is not None:
        issues.append(
            _issue("SOURCE_SNAPSHOT_INVALID", package.root / "catalog/evidence.yaml", "snapshot")
        )
    for loaded in package.source_loads:
        if loaded.unsafe:
            issues.append(
                _issue(
                    "SOURCE_PATH_UNSAFE",
                    package.root / "catalog/evidence.yaml",
                    loaded.relative,
                )
            )
        elif loaded.error is not None:
            code = "SOURCE_FILE_MISSING" if "No such file" in loaded.error else "SOURCE_READ_ERROR"
            issues.append(_issue(code, loaded.resolved or loaded.relative, loaded.error))
        elif loaded.content is not None:
            actual = hashlib.sha256(loaded.content).hexdigest()
            if actual != loaded.expected_sha256:
                issues.append(
                    _issue(
                        "SOURCE_HASH_STALE",
                        loaded.resolved or loaded.relative,
                        f"expected {loaded.expected_sha256}, got {actual}",
                    )
                )
    return issues


def validate_source_snapshot_coverage(
    package: FoundationPackage, snapshot: JsonValue, phase: int = 0
) -> list[ValidationIssue]:
    """Purely prove that declared Phase 1 include patterns cover current files."""
    location = package.root / "catalog/evidence.yaml"
    if phase >= 1 and not _has_valid_snapshot_coverage_shape(snapshot):
        return [_issue("SOURCE_SNAPSHOT_COVERAGE_INVALID", location, "Phase 1 snapshot")]
    if not isinstance(snapshot, dict):
        return []
    patterns = snapshot.get("include_patterns")
    files = snapshot.get("files")
    if not isinstance(patterns, list) or not isinstance(files, list):
        return []
    text_patterns = [value for value in patterns if isinstance(value, str)]
    repository = package.root.parents[1]
    expected = {
        path.relative_to(repository).as_posix()
        for pattern in text_patterns
        for path in repository.glob(pattern)
        if path.is_file()
    }
    covered = {
        path
        for item in files
        if isinstance(item, dict) and isinstance((path := item.get("path")), str)
    }
    issues: list[ValidationIssue] = []
    if phase >= 1 and not set(PHASE_ONE_SNAPSHOT_INCLUDE_PATTERNS) <= set(text_patterns):
        issues.append(_issue("SOURCE_SNAPSHOT_PATTERN_MISSING", location, snapshot.get("id")))
    if not expected <= covered:
        issues.append(
            _issue("SOURCE_SNAPSHOT_COVERAGE_MISSING", location, sorted(expected - covered))
        )
    if snapshot.get("expected_count") != len(expected) or snapshot.get("covered_count") != len(
        covered
    ):
        issues.append(_issue("SOURCE_SNAPSHOT_COUNT_MISMATCH", location, snapshot.get("id")))
    return issues


def _active_snapshot(evidence: dict[str, JsonValue]) -> dict[str, JsonValue] | None:
    active_id = evidence.get("active_snapshot_id")
    snapshots = evidence.get("snapshots")
    if not isinstance(active_id, str) or not isinstance(snapshots, list):
        return evidence.get("snapshot") if isinstance(evidence.get("snapshot"), dict) else None
    active = next(
        (
            snapshot
            for snapshot in snapshots
            if isinstance(snapshot, dict) and snapshot.get("id") == active_id
        ),
        None,
    )
    if not isinstance(active, dict):
        return None
    all_snapshots = [
        value for value in [evidence.get("snapshot"), *snapshots] if isinstance(value, dict)
    ]
    by_id: dict[str, dict[str, JsonValue]] = {}
    for snapshot in all_snapshots:
        identifier = snapshot.get("id")
        if not isinstance(identifier, str):
            return None
        if identifier in by_id and by_id[identifier] != snapshot:
            return None
        by_id.setdefault(identifier, snapshot)
    chain: list[dict[str, JsonValue]] = []
    current = active
    visited: set[str] = set()
    while True:
        identifier = current.get("id")
        if not isinstance(identifier, str) or identifier in visited:
            return None
        visited.add(identifier)
        chain.append(current)
        parent = current.get("parent_snapshot_id")
        if parent is None:
            break
        if not isinstance(parent, str) or parent not in by_id:
            return None
        current = by_id[parent]
    resolved = dict(active)
    files: dict[str, dict[str, JsonValue]] = {}
    for snapshot in reversed(chain):
        records = snapshot.get("files")
        if not isinstance(records, list):
            return None
        for record in records:
            if not isinstance(record, dict) or not isinstance((path := record.get("path")), str):
                return None
            if record.get("tombstone") is True:
                if path not in files:
                    return None
                files.pop(path)
            else:
                files[path] = record
    resolved["files"] = list(files.values())
    return resolved


def _snapshot_digest(snapshot: dict[str, JsonValue]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _lineage_entry_digest(entry: dict[str, JsonValue]) -> str:
    """Hash a lineage registration without recursively hashing its digest field."""
    value = {key: item for key, item in entry.items() if key != "lineage_entry_digest"}
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _evidence_snapshots(evidence: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    snapshots: list[dict[str, JsonValue]] = []
    phase_one = evidence.get("snapshot")
    if isinstance(phase_one, dict):
        snapshots.append(phase_one)
    registered = evidence.get("snapshots")
    if isinstance(registered, list):
        snapshots.extend(value for value in registered if isinstance(value, dict))
    by_id: dict[str, dict[str, JsonValue]] = {}
    for snapshot in snapshots:
        identifier = snapshot.get("id")
        if isinstance(identifier, str) and identifier not in by_id:
            by_id[identifier] = snapshot
    return list(by_id.values())


def _validate_snapshot_lineage(
    package: FoundationPackage, evidence_value: JsonValue
) -> list[ValidationIssue]:
    """Mechanically bind each evidence snapshot to an append-only lineage entry."""
    location = package.root / "catalog/snapshot-lineage.yaml"
    if not isinstance(evidence_value, dict):
        return [_issue("SNAPSHOT_LINEAGE_MISSING", location, "evidence missing")]
    lineage_value = package.documents.get("catalog/snapshot-lineage.yaml")
    if not isinstance(lineage_value, dict) or not isinstance(lineage_value.get("entries"), list):
        return [_issue("SNAPSHOT_LINEAGE_MISSING", location, "entries missing")]

    issues: list[ValidationIssue] = []
    entries = [entry for entry in lineage_value["entries"] if isinstance(entry, dict)]
    if len(entries) != len(lineage_value["entries"]):
        issues.append(_issue("SNAPSHOT_LINEAGE_ENTRY_INVALID", location, "entry must be mapping"))
    evidence_by_id = {
        identifier: snapshot
        for snapshot in _evidence_snapshots(evidence_value)
        if isinstance((identifier := snapshot.get("id")), str)
    }
    entry_by_id: dict[str, dict[str, JsonValue]] = {}
    for index, entry in enumerate(entries):
        identifier = entry.get("snapshot_id")
        entry_location = f"{location}:entries[{index}]"
        if not isinstance(identifier, str) or not identifier:
            issues.append(_issue("SNAPSHOT_LINEAGE_ENTRY_INVALID", entry_location, "snapshot_id"))
            continue
        if identifier in entry_by_id:
            issues.append(_issue("SNAPSHOT_LINEAGE_ID_DUPLICATE", entry_location, identifier))
        else:
            entry_by_id[identifier] = entry
        if entry.get("status") not in {"historical", "active"}:
            issues.append(_issue("SNAPSHOT_LINEAGE_ENTRY_INVALID", entry_location, "status"))
        if entry.get("snapshot_digest") != _snapshot_digest(evidence_by_id.get(identifier, {})):
            issues.append(_issue("SNAPSHOT_LINEAGE_SNAPSHOT_MISMATCH", entry_location, identifier))
        if identifier in evidence_by_id and entry.get("parent_snapshot_id") != evidence_by_id[
            identifier
        ].get("parent_snapshot_id"):
            issues.append(_issue("SNAPSHOT_LINEAGE_REPARENTED", entry_location, identifier))
        if entry.get("lineage_entry_digest") != _lineage_entry_digest(entry):
            issues.append(
                _issue("SNAPSHOT_LINEAGE_ENTRY_DIGEST_INVALID", entry_location, identifier)
            )

    if set(entry_by_id) != set(evidence_by_id):
        issues.append(
            _issue(
                "SNAPSHOT_LINEAGE_SET_MISMATCH",
                location,
                sorted(set(entry_by_id) ^ set(evidence_by_id)),
            )
        )
    phase_one = evidence_value.get("snapshot")
    phase_one_id = phase_one.get("id") if isinstance(phase_one, dict) else None

    def lineage_root(identifier: str) -> str | None:
        seen: set[str] = set()
        current = identifier
        while current in entry_by_id:
            if current in seen:
                return None
            seen.add(current)
            parent = entry_by_id[current].get("parent_snapshot_id")
            if not isinstance(parent, str):
                return current
            current = parent
        return None

    active_entries = [entry for entry in entries if entry.get("status") == "active"]
    active_identifier = active_entries[0].get("snapshot_id") if len(active_entries) == 1 else None
    active_root = (
        lineage_root(active_identifier)
        if isinstance(active_identifier, str) and active_identifier in entry_by_id
        else None
    )
    if not isinstance(phase_one_id, str) or active_root != phase_one_id:
        issues.append(_issue("SNAPSHOT_LINEAGE_ROOT_INVALID", location, "active chain root"))
    for index, entry in enumerate(entries):
        identifier = entry.get("snapshot_id")
        parent = entry.get("parent_snapshot_id")
        if parent is not None and (not isinstance(parent, str) or parent not in entry_by_id):
            issues.append(
                _issue("SNAPSHOT_LINEAGE_PARENT_UNKNOWN", f"{location}:entries[{index}]", parent)
            )
        if index == 0:
            expected_predecessor: str | None = None
        else:
            expected_predecessor = entries[index - 1].get("lineage_entry_digest")
        if entry.get("predecessor_lineage_digest") != expected_predecessor:
            issues.append(
                _issue(
                    "SNAPSHOT_LINEAGE_PREDECESSOR_INVALID",
                    f"{location}:entries[{index}]",
                    identifier,
                )
            )

    def reaches_cycle(identifier: str) -> bool:
        seen: set[str] = set()
        current = identifier
        while current in entry_by_id:
            if current in seen:
                return True
            seen.add(current)
            parent = entry_by_id[current].get("parent_snapshot_id")
            if not isinstance(parent, str):
                return False
            current = parent
        return False

    if any(reaches_cycle(identifier) for identifier in entry_by_id):
        issues.append(_issue("SNAPSHOT_LINEAGE_CYCLE", location, "parent cycle"))
    children = {
        parent for entry in entries if isinstance((parent := entry.get("parent_snapshot_id")), str)
    }
    active = active_entries
    if len(active) != 1:
        issues.append(_issue("SNAPSHOT_LINEAGE_ACTIVE_INVALID", location, "exactly one active"))
    elif active[0].get("snapshot_id") in children:
        issues.append(
            _issue("SNAPSHOT_LINEAGE_ACTIVE_NONLEAF", location, active[0].get("snapshot_id"))
        )
    active_id = evidence_value.get("active_snapshot_id")
    if len(active) == 1 and active[0].get("snapshot_id") != active_id:
        issues.append(_issue("SNAPSHOT_LINEAGE_ACTIVE_TARGET_MISSING", location, active_id))
    active_snapshot = evidence_by_id.get(active_id) if isinstance(active_id, str) else None
    if not isinstance(active_snapshot, dict) or not active_snapshot.get("files"):
        issues.append(_issue("SNAPSHOT_LINEAGE_ACTIVE_EMPTY", location, active_id))
    for snapshot in _evidence_snapshots(evidence_value):
        files = snapshot.get("files")
        seen_paths: dict[str, str] = {}
        if not isinstance(files, list):
            continue
        for record in files:
            if not isinstance(record, dict):
                continue
            path, digest = record.get("path"), record.get("sha256")
            if not isinstance(path, str) or not isinstance(digest, str):
                continue
            if path in seen_paths:
                code = (
                    "SNAPSHOT_FILE_PATH_CONFLICT"
                    if seen_paths[path] != digest
                    else "SNAPSHOT_FILE_PATH_DUPLICATE"
                )
                issues.append(_issue(code, location, f"{snapshot.get('id')}:{path}"))
            seen_paths[path] = digest
    return issues


def _validate_phase_one_snapshot_immutable(
    package: FoundationPackage, snapshot: JsonValue
) -> list[ValidationIssue]:
    if not isinstance(snapshot, dict):
        return [_issue("PHASE_ONE_SNAPSHOT_IMMUTABLE_MISMATCH", package.root, "snapshot missing")]
    digest_path = package.root / "catalog/phase-1-snapshot.sha256"
    try:
        expected = digest_path.read_text(encoding="utf-8").strip()
    except OSError:
        return [_issue("PHASE_ONE_SNAPSHOT_BASELINE_MISSING", digest_path, "immutable digest")]
    if expected != _snapshot_digest(snapshot):
        return [_issue("PHASE_ONE_SNAPSHOT_IMMUTABLE_MISMATCH", digest_path, snapshot.get("id"))]
    return []


def _validate_active_snapshot_lineage(
    package: FoundationPackage,
    phase_one_snapshot: JsonValue,
    active_snapshot: JsonValue,
    phase: int,
) -> list[ValidationIssue]:
    if phase < 1:
        return []
    location = package.root / "catalog/evidence.yaml"
    if not isinstance(phase_one_snapshot, dict) or not isinstance(active_snapshot, dict):
        return [_issue("ACTIVE_SNAPSHOT_LINEAGE_INVALID", location, "missing snapshot")]
    if active_snapshot.get("id") == phase_one_snapshot.get("id"):
        return [_issue("ACTIVE_SNAPSHOT_LINEAGE_INVALID", location, "active snapshot is Phase 1")]
    try:
        SourceSnapshot.model_validate(active_snapshot)
    except ValidationError as error:
        return [_issue("ACTIVE_SNAPSHOT_LINEAGE_INVALID", location, error)]
    return []


def _has_valid_snapshot_coverage_shape(snapshot: JsonValue) -> bool:
    if not isinstance(snapshot, dict):
        return False
    patterns = snapshot.get("include_patterns")
    files = snapshot.get("files")
    expected_count = snapshot.get("expected_count")
    covered_count = snapshot.get("covered_count")
    return (
        isinstance(patterns, list)
        and all(isinstance(pattern, str) and pattern for pattern in patterns)
        and isinstance(files, list)
        and all(isinstance(file, dict) for file in files)
        and type(expected_count) is int
        and type(covered_count) is int
    )


def _validate_q7_coverage_attestation(
    package: FoundationPackage,
    questions: QuestionCatalog | None,
    evidence_items: list[dict[str, JsonValue]],
    snapshots: list[dict[str, JsonValue]],
    issues: list[ValidationIssue],
) -> None:
    q7 = next(
        (item for item in (questions.items if questions else []) if item.get("id") == "Q-7"), None
    )
    if q7 is None or q7.get("status") != "resolved":
        return
    location = package.root / "catalog/questions.yaml"
    attestation = next((item for item in evidence_items if item.get("id") == "EVD-113"), None)
    decisive = q7.get("decisive_evidence_ids")
    primary_snapshot = snapshots[0] if snapshots else None
    valid = (
        isinstance(attestation, dict)
        and isinstance(decisive, list)
        and decisive == ["EVD-113"]
        and attestation.get("source_kind") == "snapshot-coverage-attestation"
        and isinstance(primary_snapshot, dict)
        and _has_valid_snapshot_coverage_shape(primary_snapshot)
        and attestation.get("snapshot_id") == primary_snapshot.get("id")
        and attestation.get("include_patterns") == primary_snapshot.get("include_patterns")
        and attestation.get("expected_count") == primary_snapshot.get("expected_count")
        and attestation.get("covered_count") == primary_snapshot.get("covered_count")
    )
    if not valid:
        issues.append(_issue("Q7_COVERAGE_ATTESTATION_INVALID", location, "Q-7"))


class ReviewItemParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, tuple[str, ...]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        identifier = attributes.get("data-item-id")
        if identifier is None:
            return
        evidence = attributes.get("data-evidence-ids")
        evidence_ids = tuple(evidence.split()) if evidence else ()
        self.items.append((identifier, evidence_ids))


def validate_review_references(package: FoundationPackage, phase: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if phase < 3:
        return issues
    batches = {
        relative: text
        for relative, text in package.reviews.items()
        if relative.startswith("reviews/phase-3-reality-capability-")
    }
    if not batches:
        return [
            _issue(
                "REQUIRED_FILE_MISSING", package.root / "reviews", "Phase 3 review batch is missing"
            )
        ]
    canonical, _ = _canonical_documents(package)
    declared = {
        identifier
        for document in canonical.values()
        for item in document.items
        if isinstance((identifier := item.get("id")), str)
    }
    evidence_document = canonical.get("catalog/evidence.yaml")
    evidence_ids = {
        identifier
        for item in (evidence_document.items if evidence_document else [])
        if isinstance((identifier := item.get("id")), str) and identifier.startswith("EVD-")
    }
    for relative, text in sorted(batches.items()):
        path = package.root / relative
        parser = ReviewItemParser()
        parser.feed(text)
        if not parser.items:
            issues.append(_issue("REVIEW_ITEMS_MISSING", path, "no review items"))
        for identifier, item_evidence_ids in parser.items:
            if identifier not in declared:
                issues.append(_issue("REVIEW_REFERENCE_UNRESOLVED", path, identifier))
            if not item_evidence_ids:
                issues.append(
                    _issue("REVIEW_EVIDENCE_MISSING", path, f"{identifier} requires evidence")
                )
            for evidence_id in item_evidence_ids:
                if evidence_id not in evidence_ids:
                    issues.append(_issue("REVIEW_EVIDENCE_UNRESOLVED", path, evidence_id))
    return issues


def validate_report(path: Path) -> list[ValidationIssue]:
    required = (
        "Purpose",
        "Scope inspected",
        "Key findings",
        "Important uncertainties",
        "Conflicts found",
        "Decisions required",
        "Artifact paths",
        "Evidence pointers",
        "Recommended next delegation",
    )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [_issue("REPORT_INVALID", path, error)]
    headings = set(re.findall(r"(?m)^## ([^\r\n]+)\s*$", text))
    return [
        _issue("REPORT_SECTION_MISSING", path, heading)
        for heading in required
        if heading not in headings
    ]


def validate_foundation(root: Path, phase: int) -> list[ValidationIssue]:
    if type(phase) is not int or phase not in PHASE_FILES:
        return [_issue("PHASE_INVALID", root, "phase must be one of 0, 1, 2, 3")]
    package = load_foundation(root)
    issues = validate_required_files(package, phase)
    issues.extend(validate_schema_contracts(package))
    issues.extend(validate_semantics(package, phase))
    issues.extend(validate_source_hashes(package, phase))
    issues.extend(validate_review_references(package, phase))
    return issues


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the grounded UI/UX foundation")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--phase", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--write-phase-two-projections", action="store_true")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.write_phase_two_projections:
        write_phase_two_projections(arguments.root)
    issues = (
        validate_report(arguments.report)
        if arguments.report
        else validate_foundation(arguments.root, arguments.phase)
    )
    for issue in issues:
        print(f"{issue.code}: {issue.path}: {issue.message}", file=sys.stderr)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
