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
    inputs: list[str] = Field(min_length=1)
    algorithm: str = Field(min_length=1)
    output_type: str = Field(min_length=1)
    unknown_behavior: str = Field(min_length=1)
    failure_behavior: str = Field(min_length=1)
    freshness: str = Field(min_length=1)
    recomputation_behavior: str = Field(min_length=1)
    implementation_evidence_ids: list[str] = Field(min_length=1)
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

    declarations: dict[str, str] = {}
    for relative, document in canonical.items():
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

    registry = canonical.get("capabilities/registry.yaml")
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
    for relative, value in package.documents.items():
        if not relative.startswith("capabilities/derivations/") or not isinstance(value, dict):
            continue
        for field, code in required_derivation.items():
            if value.get(field) in (None, "", []):
                issues.append(_issue(code, package.root / relative, field))
    for item in registry.items if registry else []:
        if item.get("capability_status") != "derived":
            continue
        derivation_id = item.get("derivation_id")
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
                action.get("capability_status") != "current" or action.get("executable") is not True
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


def validate_source_hashes(package: FoundationPackage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    value = package.documents.get("catalog/evidence.yaml")
    snapshot = value.get("snapshot") if isinstance(value, dict) else None
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
    issues.extend(validate_source_hashes(package))
    issues.extend(validate_review_references(package, phase))
    return issues


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the grounded UI/UX foundation")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--phase", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--report", type=Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
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
