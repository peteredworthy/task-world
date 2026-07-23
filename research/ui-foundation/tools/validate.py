from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError
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
    "executable-schema",
    "implementation",
    "invariant-check",
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
    issues: tuple[ValidationIssue, ...]


class CanonicalDocument(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    schema_version: str
    items: list[dict[str, JsonValue]]


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

    id: str
    source_kind: str
    reachable: bool = False
    test_status: Literal["exercised", "unexercised", "contradicted", "unknown"] | None = None


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
    issues: list[ValidationIssue] = []
    for path in sorted((*root.rglob("*.yaml"), *root.rglob("*.yml"))):
        relative = path.relative_to(root).as_posix()
        try:
            documents[relative] = cast(JsonValue, yaml.safe_load(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            issues.append(_issue("YAML_INVALID", path, error))
    return FoundationPackage(root, documents, tuple(issues))


def _canonical_documents(
    package: FoundationPackage,
) -> tuple[dict[str, CanonicalDocument], list[ValidationIssue]]:
    documents: dict[str, CanonicalDocument] = {}
    issues: list[ValidationIssue] = []
    for relative in sorted(CANONICAL_COLLECTIONS & package.documents.keys()):
        try:
            documents[relative] = CanonicalDocument.model_validate(package.documents[relative])
        except ValidationError as error:
            issues.append(_issue("CANONICAL_DOCUMENT_INVALID", package.root / relative, error))
    return documents, issues


def _all_dicts(value: JsonValue) -> list[dict[str, JsonValue]]:
    found: list[dict[str, JsonValue]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_all_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_all_dicts(child))
    return found


def _ids(package: FoundationPackage) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative, value in package.documents.items():
        for item in _all_dicts(value):
            identifier = item.get("id")
            if isinstance(identifier, str):
                result.setdefault(identifier, relative)
    return result


def validate_semantics(package: FoundationPackage, phase: int) -> list[ValidationIssue]:
    """Pure typed validation over an already loaded package."""
    issues = list(package.issues)
    canonical, boundary_issues = _canonical_documents(package)
    issues.extend(boundary_issues)

    for relative in sorted(SEMANTIC_COLLECTIONS & canonical.keys()):
        for index, item in enumerate(canonical[relative].items):
            try:
                SemanticItem.model_validate(item)
            except ValidationError as error:
                issues.append(
                    _issue(
                        "SEMANTIC_ITEM_INVALID", f"{package.root / relative}:items[{index}]", error
                    )
                )

    declared: dict[str, str] = {}
    references: list[tuple[str, str]] = []
    for relative, value in package.documents.items():
        for item in _all_dicts(value):
            identifier = item.get("id")
            if isinstance(identifier, str):
                if identifier in declared:
                    issues.append(
                        _issue(
                            "ID_DUPLICATE",
                            package.root / relative,
                            f"{identifier} already declared in {declared[identifier]}",
                        )
                    )
                else:
                    declared[identifier] = relative
            for field, candidate in item.items():
                if field in {"repository_revision", "source_snapshot"}:
                    continue
                if field.endswith("_id") and field != "id" and isinstance(candidate, str):
                    references.append((candidate, relative))
                elif (field.endswith("_ids") or field in {"inputs", "evidence"}) and isinstance(
                    candidate, list
                ):
                    references.extend(
                        (reference, relative)
                        for reference in candidate
                        if isinstance(reference, str) and re.fullmatch(r"[A-Z]+-\d+", reference)
                    )
    for reference, relative in references:
        if reference not in declared:
            issues.append(_issue("REFERENCE_UNRESOLVED", package.root / relative, reference))

    evidence_document = canonical.get("catalog/evidence.yaml")
    evidence: dict[str, EvidenceRecord] = {}
    if evidence_document:
        for index, item in enumerate(evidence_document.items):
            try:
                record = EvidenceRecord.model_validate(item)
                evidence[record.id] = record
            except ValidationError as error:
                issues.append(
                    _issue(
                        "EVIDENCE_RECORD_INVALID",
                        f"{package.root / 'catalog/evidence.yaml'}:items[{index}]",
                        error,
                    )
                )

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
                item.get("conflict_ids")
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

    derivations: dict[str, tuple[str, dict[str, JsonValue]]] = {}
    for relative, value in package.documents.items():
        if relative.startswith("capabilities/derivations/") and isinstance(value, dict):
            identifier = value.get("id")
            if isinstance(identifier, str):
                derivations[identifier] = (relative, value)
    required_derivation = {
        "inputs": "DERIVATION_INPUTS_MISSING",
        "algorithm": "DERIVATION_ALGORITHM_MISSING",
        "output_type": "DERIVATION_OUTPUT_TYPE_MISSING",
        "unknown_behavior": "DERIVATION_UNKNOWN_BEHAVIOR_MISSING",
        "failure_behavior": "DERIVATION_FAILURE_BEHAVIOR_MISSING",
        "freshness": "DERIVATION_FRESHNESS_MISSING",
        "implementation_evidence_ids": "DERIVATION_IMPLEMENTATION_EVIDENCE_MISSING",
        "limitations": "DERIVATION_LIMITATIONS_MISSING",
        "prohibited_interpretations": "DERIVATION_PROHIBITED_INTERPRETATIONS_MISSING",
    }
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
        for field, code in required_derivation.items():
            if derivation.get(field) in (None, "", []):
                issues.append(_issue(code, package.root / relative, field))

    issues.extend(_validate_actions(package, declared))
    issues.extend(_validate_epistemics(package))
    return issues


def _validate_actions(
    package: FoundationPackage, declared: dict[str, str]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    state_value = package.documents.get("reality/state-model.yaml")
    states = {
        identifier
        for item in _all_dicts(state_value)
        if isinstance((identifier := item.get("id")), str) and identifier.startswith("STA-")
    }
    legal: set[tuple[str, str]] = set()
    if isinstance(state_value, dict):
        transitions = state_value.get("transitions")
        if isinstance(transitions, list):
            for transition in transitions:
                if isinstance(transition, dict):
                    start, end = transition.get("from_state_id"), transition.get("to_state_id")
                    if isinstance(start, str) and isinstance(end, str):
                        legal.add((start, end))
    absent_fields = (
        "required_outcome",
        "source_demand_ids",
        "implementation_constraints",
        "required_evidence",
        "unresolved_command_decisions",
    )
    for relative, action in package.documents.items():
        if not relative.startswith("reality/actions/") or not isinstance(action, dict):
            continue
        path = package.root / relative
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
            if not isinstance(command, str) or command not in declared:
                issues.append(_issue("ACTION_COMMAND_UNRESOLVED", path, command))
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
    return issues


def _validate_epistemics(package: FoundationPackage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for relative, value in package.documents.items():
        for item in _all_dicts(value):
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
    for required_phase in range(phase + 1):
        for relative in PHASE_FILES[required_phase]:
            if not (package.root / relative).is_file():
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


def validate_schema_contracts(root: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    expected_enums = {
        "implementation_status": IMPLEMENTATION_STATUSES,
        "test_status": TEST_STATUSES,
        "documentation_status": DOCUMENTATION_STATUSES,
        "capability_status": CAPABILITY_STATUSES,
        "epistemic_status": EPISTEMIC_STATUSES,
    }
    for path in sorted((root / "schemas").glob("*.json")):
        try:
            value = cast(JsonValue, json.loads(path.read_text(encoding="utf-8")))
            schema = SchemaBoundary.model_validate(value)
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
            issues.append(_issue("SCHEMA_INVALID", path, error))
            continue
        if path.name == "semantic-item.schema.json":
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
    files = snapshot.get("files") if isinstance(snapshot, dict) else None
    if not isinstance(files, list):
        return issues
    repository_root = package.root.parents[1]
    for record in files:
        if not isinstance(record, dict):
            issues.append(
                _issue("SOURCE_RECORD_INVALID", package.root / "catalog/evidence.yaml", record)
            )
            continue
        relative, expected = record.get("path"), record.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            issues.append(
                _issue("SOURCE_HASH_MISSING", package.root / "catalog/evidence.yaml", record)
            )
            continue
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            issues.append(
                _issue("SOURCE_PATH_UNSAFE", package.root / "catalog/evidence.yaml", relative)
            )
            continue
        source = repository_root / candidate
        if not source.exists():
            issues.append(_issue("SOURCE_FILE_MISSING", source, relative))
            continue
        try:
            actual = hashlib.sha256(source.read_bytes()).hexdigest()
        except OSError as error:
            issues.append(_issue("SOURCE_READ_ERROR", source, error))
            continue
        if actual != expected:
            issues.append(_issue("SOURCE_HASH_STALE", source, f"expected {expected}, got {actual}"))
    return issues


def validate_review_references(package: FoundationPackage, phase: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if phase < 3:
        return issues
    batches = sorted((package.root / "reviews").glob("phase-3-reality-capability-*.html"))
    if not batches:
        return [
            _issue(
                "REQUIRED_FILE_MISSING", package.root / "reviews", "Phase 3 review batch is missing"
            )
        ]
    declared = _ids(package)
    evidence_value = package.documents.get("catalog/evidence.yaml")
    evidence_ids = {
        identifier
        for item in _all_dicts(evidence_value)
        if isinstance((identifier := item.get("id")), str) and identifier.startswith("EVD-")
    }
    item_pattern = re.compile(r"<[^>]+data-item-id=[\"']([A-Z]+-\d+)[\"'][^>]*>")
    evidence_pattern = re.compile(r"data-evidence-ids=[\"']([^\"']*)[\"']")
    for path in batches:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            issues.append(_issue("REVIEW_INVALID", path, error))
            continue
        items = item_pattern.findall(text)
        if not items:
            issues.append(_issue("REVIEW_ITEMS_MISSING", path, "no review items"))
        for identifier in items:
            if identifier not in declared:
                issues.append(_issue("REVIEW_REFERENCE_UNRESOLVED", path, identifier))
        evidence_matches = evidence_pattern.findall(text)
        if len(evidence_matches) < len(items):
            issues.append(
                _issue("REVIEW_EVIDENCE_MISSING", path, "each review item requires evidence")
            )
        for match in evidence_matches:
            for identifier in match.split():
                if identifier not in evidence_ids:
                    issues.append(_issue("REVIEW_EVIDENCE_UNRESOLVED", path, identifier))
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
    issues.extend(validate_schema_contracts(root))
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
