from __future__ import annotations

import argparse
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


CATALOG_MODELS: dict[str, type[CanonicalDocument]] = {
    "catalog/scope.yaml": ScopeCatalog,
    "catalog/ids.yaml": IdCatalog,
    "catalog/claims.yaml": ClaimCatalog,
    "catalog/invariants.yaml": InvariantCatalog,
    "catalog/conflicts.yaml": ConflictCatalog,
    "catalog/questions.yaml": QuestionCatalog,
    "catalog/decisions.yaml": DecisionCatalog,
    "catalog/evidence.yaml": EvidenceCatalog,
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
    evidence_ids: list[str] = []


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


class ActionTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    from_state_id: str | None = None
    to_state_id: str | None = None
    from_state_ids: list[str] | None = None
    to_state_ids: list[str] | None = None

    @model_validator(mode="after")
    def require_nonempty_sides(self) -> ActionTransition:
        starts = self.from_state_ids or ([self.from_state_id] if self.from_state_id else [])
        ends = self.to_state_ids or ([self.to_state_id] if self.to_state_id else [])
        if not starts or not ends:
            raise ValueError("transition requires nonempty from and to states")
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

    @model_validator(mode="after")
    def require_present_contract(self) -> ActionContract:
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
            "transition",
        )
        missing = [field for field in required if getattr(self, field) in (None, "", [])]
        if missing:
            raise ValueError(f"present action fields missing: {', '.join(missing)}")
        return self


class SourceSnapshotFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audited_at: str = Field(min_length=1)


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
    snapshot = evidence.get("snapshot") if isinstance(evidence, dict) else None
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
        )
    )

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
        if action.get("test_status") != "exercised":
            pass
        elif not any(
            _is_direct_evidence(record)
            and record.get("source_kind") in DIRECT_TEST_SOURCE_KINDS
            and record.get("test_status") == "exercised"
            and _has_valid_direct_locator(record, snapshot_paths)
            for record in records
        ):
            issues.append(
                _issue(
                    "EXERCISED_DIRECT_TEST_EVIDENCE_MISSING",
                    package.root / f"reality/actions/{identifier}.yaml",
                    identifier,
                )
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

    registry = canonical.get("capabilities/registry.yaml")
    if phase >= 2:
        issues.extend(
            _validate_phase_two_capability_coverage(
                package,
                registry if isinstance(registry, CapabilityCatalog) else None,
                evidence,
            )
        )
    for item in registry.items if registry else []:
        status = item.get("capability_status")
        implementation = item.get("implementation_status")
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
                question_id in decisive_question_ids_by_capability.get(str(item.get("id")), set())
                for question_id in question_ids
            ):
                issues.append(
                    _issue(
                        "CURRENT_QUESTION_UNRESOLVED",
                        package.root / "capabilities/registry.yaml",
                        item.get("id"),
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
        input_evidence_ids: set[str] = set()
        output_evidence_ids: set[str] = set()
        for capability_ids, target in (
            (inputs, input_evidence_ids),
            (value.get("capability_ids"), output_evidence_ids),
        ):
            if not isinstance(capability_ids, list):
                continue
            for capability_id in capability_ids:
                if not isinstance(capability_id, str):
                    continue
                evidence_ids = raw_capabilities.get(capability_id, {}).get("evidence_ids")
                if isinstance(evidence_ids, list):
                    target.update(
                        evidence_id for evidence_id in evidence_ids if isinstance(evidence_id, str)
                    )
        chain_ids = input_evidence_ids | output_evidence_ids
        invalid_chain = not contract_valid or any(
            not isinstance(evidence_id, str)
            or evidence_id not in chain_ids
            or evidence.get(evidence_id) is None
            or not evidence[evidence_id].reachable
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
    issues.extend(_validate_epistemics(package, canonical, evidence))
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
        "reversibility-action": "ActionContract",
        "authority-action": "ActionContract",
        "authority-policy": "PermissionContract",
        "usage-telemetry": "UsageTelemetry",
    }.get(role)
    if required is not None:
        return semantic_type == required
    return role in {
        "entity-input",
        "state-input",
        "action-contract",
        "permission-contract",
        "evidence-inventory",
    } and semantic_type in {
        "EntityRecord",
        "StateRecord",
        "ActionContract",
        "PermissionContract",
        "EvidenceInventory",
        "UsageTelemetry",
    }


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
        if item.get("capability_status") != "gap" or item.get("implementation_status") != "partial":
            continue
        identifier = item.get("id")
        raw_bindings = item.get("implementation_carrier_bindings")
        if not isinstance(raw_bindings, list) or not raw_bindings:
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
        cited_evidence = set(_string_list(item.get("evidence_ids")))
        invalid_binding = any(
            binding.id not in carrier_catalog_ids
            or binding.semantic_type != _carrier_semantic_type(binding.id)
            or not _role_accepts_semantic_type(binding.role, binding.semantic_type)
            for binding in bindings
        )
        unsupported_binding = any(
            not cited_evidence.intersection(set(binding.evidence_ids))
            and not cited_evidence.intersection(
                {
                    value
                    for value in _string_list(
                        carrier_records.get(binding.id, {}).get("evidence_ids")
                    )
                }
                | {
                    value
                    for value in _string_list(
                        carrier_records.get(binding.id, {}).get("audit_evidence_ids")
                    )
                }
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
                if status == "gap" and implementation_status == "partial":
                    if (
                        not isinstance(raw_bindings, list)
                        or not raw_bindings
                        or absence_basis not in (None, "")
                    ):
                        issues.append(
                            _issue(
                                "GAP_PARTIAL_CARRIERS_INVALID",
                                package.root / "capabilities/registry.yaml",
                                identifier,
                            )
                        )
                    else:
                        try:
                            bindings = [
                                CarrierBinding.model_validate(value) for value in raw_bindings
                            ]
                        except ValidationError:
                            bindings = []
                            issues.append(
                                _issue(
                                    "GAP_PARTIAL_CARRIER_UNRESOLVED",
                                    package.root / "capabilities/registry.yaml",
                                    identifier,
                                )
                            )
                        cited_evidence = set(_string_list(evidence_ids))
                        invalid_binding = any(
                            binding.id not in carrier_catalog_ids
                            or binding.semantic_type != _carrier_semantic_type(binding.id)
                            or not _role_accepts_semantic_type(binding.role, binding.semantic_type)
                            for binding in bindings
                        )
                        unsupported_binding = False
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
                    if not isinstance(raw_bindings, list) or not raw_bindings:
                        issues.append(
                            _issue(
                                "GAP_PARTIAL_CARRIER_UNRESOLVED",
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
                claims_conflict = "conflict" in basis_text
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


def _validate_semantic_evidence_admission(
    package: FoundationPackage,
    semantic_items: dict[str, SemanticItem],
    declarations: dict[str, str],
    evidence: dict[str, dict[str, JsonValue]],
    snapshot_paths: dict[str, set[str]],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for identifier, semantic in semantic_items.items():
        records = [
            evidence[evidence_id]
            for evidence_id in semantic.evidence_ids
            if evidence_id in evidence
        ]
        location = package.root / declarations.get(identifier, "unknown")
        if semantic.test_status == "exercised" and not any(
            _is_direct_evidence(record)
            and record.get("source_kind") in DIRECT_TEST_SOURCE_KINDS
            and record.get("test_status") == "exercised"
            and _has_valid_direct_locator(record, snapshot_paths)
            for record in records
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
                action.get("capability_status") not in {"gap", "proposed"}
                or action.get("executable") is not False
            ):
                issues.append(
                    _issue(
                        "ABSENT_INTERVENTION_INVALID",
                        path,
                        "must be a non-executable gap or proposal",
                    )
                )
            for field in absent_fields:
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
    snapshot = value.get("snapshot") if isinstance(value, dict) else None
    issues.extend(validate_source_snapshot_coverage(package, snapshot, phase))
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
