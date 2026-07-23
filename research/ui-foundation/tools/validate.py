from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import cast

import yaml


type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None


IMPLEMENTATION_STATUSES = {"present", "absent", "partial", "unknown"}
TEST_STATUSES = {"exercised", "unexercised", "contradicted", "unknown"}
DOCUMENTATION_STATUSES = {
    "documented",
    "undocumented",
    "stale",
    "conflicting",
    "unknown",
}
CAPABILITY_STATUSES = {"current", "derived", "proposed", "gap", "unknown"}
EPISTEMIC_STATUSES = {
    "observed",
    "deterministically-derived",
    "inferred",
    "operator-asserted",
    "proposed",
    "unknown",
}
STATUS_FIELDS = {
    "implementation_status": IMPLEMENTATION_STATUSES,
    "test_status": TEST_STATUSES,
    "documentation_status": DOCUMENTATION_STATUSES,
    "capability_status": CAPABILITY_STATUSES,
    "epistemic_status": EPISTEMIC_STATUSES,
}
IMPLEMENTATION_SOURCE_KINDS = {
    "api",
    "command",
    "event",
    "executable-schema",
    "implementation",
    "invariant-check",
    "persisted-record",
    "test",
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


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str


def _yaml_files(root: Path) -> list[Path]:
    return sorted((*root.rglob("*.yaml"), *root.rglob("*.yml")))


def _load_yaml(path: Path) -> tuple[JsonValue, ValidationIssue | None]:
    try:
        return cast(JsonValue, yaml.safe_load(path.read_text(encoding="utf-8"))), None
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        return None, ValidationIssue("YAML_INVALID", str(path), str(error))


def _walk(value: JsonValue, location: str = "$") -> Iterable[tuple[str, JsonValue]]:
    yield location, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{location}[{index}]")


def _documents(root: Path) -> Iterable[tuple[Path, JsonValue]]:
    for path in _yaml_files(root):
        value, error = _load_yaml(path)
        if error is None:
            yield path, value


def _items(value: JsonValue) -> list[dict[str, JsonValue]]:
    if not isinstance(value, dict):
        return []
    items = value.get("items", [])
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def validate_required_files(root: Path, phase: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for required_phase in range(phase + 1):
        for relative in PHASE_FILES[required_phase]:
            path = root / relative
            if not path.is_file():
                issues.append(
                    ValidationIssue(
                        "REQUIRED_FILE_MISSING", str(path), f"required for phase {required_phase}"
                    )
                )

    if phase >= 1:
        for relative in PHASE_FILES[1]:
            path = root / relative
            value, error = _load_yaml(path) if path.is_file() else (None, None)
            if error is None and path.is_file() and not _items(value):
                issues.append(
                    ValidationIssue(
                        "PHASE_COLLECTION_INCOMPLETE", str(path), "Phase 1 collection is empty"
                    )
                )
    if phase >= 2:
        path = root / "capabilities/registry.yaml"
        value, error = _load_yaml(path) if path.is_file() else (None, None)
        if error is None and path.is_file() and not _items(value):
            issues.append(
                ValidationIssue(
                    "PHASE_COLLECTION_INCOMPLETE", str(path), "Phase 2 capability registry is empty"
                )
            )
    if phase >= 3 and not list((root / "reviews").glob("phase-3-reality-capability-*.html")):
        issues.append(
            ValidationIssue(
                "REQUIRED_FILE_MISSING", str(root / "reviews"), "Phase 3 review batch is missing"
            )
        )
    return issues


def validate_yaml_and_statuses(root: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for path in _yaml_files(root):
        value, error = _load_yaml(path)
        if error is not None:
            issues.append(error)
            continue
        if not isinstance(value, (dict, list)):
            issues.append(
                ValidationIssue("YAML_DOCUMENT_INVALID", str(path), "expected a mapping or list")
            )
            continue
        for location, child in _walk(value):
            if not isinstance(child, dict):
                continue
            for field, allowed in STATUS_FIELDS.items():
                status = child.get(field)
                if status is not None and status not in allowed:
                    issues.append(
                        ValidationIssue(
                            "STATUS_INVALID",
                            f"{path}:{location}.{field}",
                            f"{status!r}; expected one of {sorted(allowed)}",
                        )
                    )
    for path in sorted((root / "schemas").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            issues.append(ValidationIssue("JSON_INVALID", str(path), str(error)))
    return issues


def _declared_ids(root: Path) -> dict[str, Path]:
    declared: dict[str, Path] = {}
    for path, value in _documents(root):
        for _, child in _walk(value):
            if isinstance(child, dict):
                identifier = child.get("id")
                if isinstance(identifier, str):
                    declared.setdefault(identifier, path)
    return declared


def validate_unique_ids_and_references(root: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    declared: dict[str, Path] = {}
    references: list[tuple[str, Path, str]] = []
    ignored_reference_fields = {"repository_revision", "source_snapshot"}
    for path, value in _documents(root):
        for location, child in _walk(value):
            if not isinstance(child, dict):
                continue
            identifier = child.get("id")
            if isinstance(identifier, str):
                if identifier in declared:
                    issues.append(
                        ValidationIssue(
                            "ID_DUPLICATE",
                            str(path),
                            f"{identifier} already declared in {declared[identifier]}",
                        )
                    )
                else:
                    declared[identifier] = path
            for field, candidate in child.items():
                if field in ignored_reference_fields:
                    continue
                if field.endswith("_id") and field != "id" and isinstance(candidate, str):
                    references.append((candidate, path, f"{location}.{field}"))
                elif (field.endswith("_ids") or field in {"inputs", "evidence"}) and isinstance(
                    candidate, list
                ):
                    references.extend(
                        (reference, path, f"{location}.{field}")
                        for reference in candidate
                        if isinstance(reference, str) and re.fullmatch(r"[A-Z]+-\d+", reference)
                    )
    for reference, path, location in references:
        if reference not in declared:
            issues.append(ValidationIssue("REFERENCE_UNRESOLVED", f"{path}:{location}", reference))
    return issues


def validate_source_hashes(root: Path) -> list[ValidationIssue]:
    evidence_path = root / "catalog/evidence.yaml"
    if not evidence_path.is_file():
        return []
    value, error = _load_yaml(evidence_path)
    if error is not None or not isinstance(value, dict):
        return []
    snapshot = value.get("snapshot")
    files: list[JsonValue] = []
    if isinstance(snapshot, dict):
        snapshot_files = snapshot.get("files")
        if isinstance(snapshot_files, list):
            files = snapshot_files
    issues: list[ValidationIssue] = []
    repository_root = root.parents[1] if len(root.parents) > 1 else root
    for record in files:
        if not isinstance(record, dict):
            continue
        relative = record.get("path")
        expected = record.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            issues.append(ValidationIssue("SOURCE_HASH_MISSING", str(evidence_path), repr(record)))
            continue
        source = repository_root / relative
        if not source.is_file():
            issues.append(ValidationIssue("SOURCE_FILE_MISSING", str(source), relative))
            continue
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != expected:
            issues.append(
                ValidationIssue(
                    "SOURCE_HASH_STALE", str(source), f"expected {expected}, got {actual}"
                )
            )
    return issues


def validate_current_evidence(root: Path) -> list[ValidationIssue]:
    evidence_path = root / "catalog/evidence.yaml"
    value, error = _load_yaml(evidence_path) if evidence_path.is_file() else (None, None)
    evidence = (
        {item.get("id"): item for item in _items(value) if isinstance(item.get("id"), str)}
        if error is None
        else {}
    )
    issues: list[ValidationIssue] = []
    for path, document in _documents(root):
        for _, item in _walk(document):
            if not isinstance(item, dict) or item.get("capability_status") != "current":
                continue
            evidence_ids = item.get("evidence_ids", [])
            records = (
                [evidence[identifier] for identifier in evidence_ids if identifier in evidence]
                if isinstance(evidence_ids, list)
                else []
            )
            if not any(
                record.get("source_kind") in IMPLEMENTATION_SOURCE_KINDS for record in records
            ):
                issues.append(
                    ValidationIssue(
                        "CURRENT_IMPLEMENTATION_EVIDENCE_MISSING",
                        str(path),
                        str(item.get("id", "unknown item")),
                    )
                )
    return issues


def validate_derivations(root: Path) -> list[ValidationIssue]:
    registry = root / "capabilities/registry.yaml"
    value, error = _load_yaml(registry) if registry.is_file() else (None, None)
    derivations: dict[str, tuple[Path, dict[str, JsonValue]]] = {}
    for path in sorted((root / "capabilities/derivations").glob("*.yaml")):
        document, document_error = _load_yaml(path)
        if document_error is None and isinstance(document, dict):
            identifier = document.get("id")
            if isinstance(identifier, str):
                derivations[identifier] = (path, document)
    issues: list[ValidationIssue] = []
    if error is not None:
        return issues
    required = {
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
    for item in _items(value):
        if item.get("capability_status") != "derived":
            continue
        identifier = item.get("derivation_id")
        if not isinstance(identifier, str) or identifier not in derivations:
            issues.append(
                ValidationIssue(
                    "DERIVATION_MISSING", str(registry), str(item.get("id", "unknown item"))
                )
            )
            continue
        path, derivation = derivations[identifier]
        for field, code in required.items():
            if field not in derivation or derivation[field] in (None, "", []):
                issues.append(ValidationIssue(code, str(path), field))
    return issues


def validate_actions_and_transitions(root: Path) -> list[ValidationIssue]:
    state_path = root / "reality/state-model.yaml"
    state_value, state_error = _load_yaml(state_path) if state_path.is_file() else (None, None)
    states: set[str] = set()
    if state_error is None:
        for item in _items(state_value):
            identifier = item.get("id")
            if isinstance(identifier, str):
                states.add(identifier)
    issues: list[ValidationIssue] = []
    for path in sorted((root / "reality/actions").glob("*.yaml")):
        action, error = _load_yaml(path)
        if error is not None or not isinstance(action, dict):
            continue
        current = (
            action.get("capability_status") == "current"
            or action.get("implementation_status") == "present"
        )
        if current and not action.get("command_id"):
            issues.append(
                ValidationIssue(
                    "ACTION_COMMAND_MISSING",
                    str(path),
                    "current action requires an implemented command",
                )
            )
        transition = action.get("transition")
        if current and not isinstance(transition, dict):
            issues.append(
                ValidationIssue(
                    "ACTION_TRANSITION_MISSING", str(path), "current action requires a transition"
                )
            )
        if isinstance(transition, dict):
            for field in ("from_state_id", "to_state_id"):
                state = transition.get(field)
                if isinstance(state, str) and state not in states:
                    issues.append(ValidationIssue("STATE_UNKNOWN", str(path), state))
        if (
            action.get("capability_status") in {"gap", "proposed"}
            and action.get("executable") is True
        ):
            issues.append(
                ValidationIssue(
                    "FUTURE_ACTION_EXECUTABLE",
                    str(path),
                    "gap or proposed action cannot be executable",
                )
            )
    return issues


def validate_epistemics(root: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for path, document in _documents(root):
        for _, item in _walk(document):
            if not isinstance(item, dict):
                continue
            causal = (
                item.get("causal") is True
                or item.get("relationship_type") == "causal"
                or item.get("claim_type") == "causal"
            )
            if causal and not item.get("epistemic_status"):
                issues.append(
                    ValidationIssue(
                        "CAUSAL_EPISTEMIC_MISSING", str(path), str(item.get("id", "unknown item"))
                    )
                )
            if causal and not (item.get("evidence_ids") or item.get("evidence")):
                issues.append(
                    ValidationIssue(
                        "CAUSAL_EVIDENCE_MISSING", str(path), str(item.get("id", "unknown item"))
                    )
                )
            aliases = item.get("aliases", [])
            if isinstance(aliases, list) and any(
                isinstance(alias, str) and "/" in alias for alias in aliases
            ):
                issues.append(
                    ValidationIssue(
                        "SLASH_ALIAS_UNPROVEN", str(path), str(item.get("id", "unknown item"))
                    )
                )
    return issues


def validate_review_references(root: Path) -> list[ValidationIssue]:
    declared = _declared_ids(root)
    issues: list[ValidationIssue] = []
    pattern = re.compile(r"data-(?:item-)?id=[\"']([A-Z]+-\d+)[\"']")
    for path in sorted((root / "reviews").glob("phase-3-*.html")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            issues.append(ValidationIssue("REVIEW_INVALID", str(path), str(error)))
            continue
        for reference in pattern.findall(text):
            if reference not in declared:
                issues.append(ValidationIssue("REVIEW_REFERENCE_UNRESOLVED", str(path), reference))
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
        return [ValidationIssue("REPORT_INVALID", str(path), str(error))]
    return [
        ValidationIssue("REPORT_SECTION_MISSING", str(path), heading)
        for heading in required
        if f"## {heading}" not in text
    ]


def validate_foundation(root: Path, phase: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(validate_required_files(root, phase))
    issues.extend(validate_yaml_and_statuses(root))
    issues.extend(validate_unique_ids_and_references(root))
    issues.extend(validate_source_hashes(root))
    issues.extend(validate_current_evidence(root))
    issues.extend(validate_derivations(root))
    issues.extend(validate_actions_and_transitions(root))
    issues.extend(validate_epistemics(root))
    issues.extend(validate_review_references(root))
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
