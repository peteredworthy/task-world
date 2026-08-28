"""Run-scoped semantic artifact declaration and content validation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

from jsonschema import SchemaError, ValidationError, validators

from orchestrator.config import json_schema_declaration_error
from orchestrator.graph.models import (
    SemanticArtifactRecord,
    SemanticSchemaDeclarationRecord,
)


type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


def semantic_schema_declarations(
    records: Mapping[str, object],
) -> dict[tuple[str, int], SemanticSchemaDeclarationRecord]:
    """Return accepted declarations by immutable schema identity."""
    output: dict[tuple[str, int], SemanticSchemaDeclarationRecord] = {}
    for record in records.values():
        if isinstance(record, SemanticSchemaDeclarationRecord):
            output[(record.value.schema_id, record.value.version)] = record
    return output


def validate_semantic_artifact_content(
    artifact: SemanticArtifactRecord,
    declarations: dict[tuple[str, int], SemanticSchemaDeclarationRecord],
) -> str | None:
    """Validate one artifact against its accepted, exact-version declaration."""
    declared = declarations.get((artifact.value.schema_id, artifact.value.schema_version))
    if declared is not None:
        declaration_error = json_schema_declaration_error(declared.value.json_schema)
        if declaration_error is not None:
            return (
                "semantic artifact schema declaration "
                f"{artifact.value.schema_id}@{artifact.value.schema_version} is invalid: "
                f"{declaration_error}"
            )
    declaration = accepted_semantic_declaration(
        declarations, artifact.value.schema_id, artifact.value.schema_version
    )
    if declaration is None:
        return (
            "semantic artifact references undeclared schema "
            f"{artifact.value.schema_id}@{artifact.value.schema_version}"
        )
    if artifact.value.semantic_role != declaration.value.semantic_role:
        return "semantic artifact role does not match its accepted schema declaration"
    content = artifact.value.content
    if content is None:
        validation = artifact.value.artifact_validation
        if validation is None:
            return "referenced semantic artifact has no controller validation evidence"
        if validation.declaration_record_id != declaration.record_id:
            return "referenced semantic artifact was not validated against its exact declaration"
        content = validation.validated_json
    return _json_schema_error(content, declaration.value.json_schema, path="$")


def semantic_declaration_conflict(
    declaration: SemanticSchemaDeclarationRecord,
    accepted: dict[tuple[str, int], SemanticSchemaDeclarationRecord],
) -> str | None:
    """Reject silent weakening or replacement of an accepted schema identity."""
    identity = (declaration.value.schema_id, declaration.value.version)
    declaration_error = json_schema_declaration_error(declaration.value.json_schema)
    if declaration_error is not None:
        return (
            f"semantic schema declaration {identity[0]}@{identity[1]} is invalid: "
            f"{declaration_error}"
        )
    existing = accepted.get(identity)
    if existing is not None:
        if existing.record_id == declaration.record_id:
            return None
        if existing.value.model_dump(mode="json") != declaration.value.model_dump(mode="json"):
            return f"semantic schema identity already accepted: {identity[0]}@{identity[1]}"
    if declaration.value.authority != "planner_amendment":
        return None
    superseded_id = declaration.value.supersedes_declaration_record_id
    if superseded_id is None:
        return "planner semantic schema amendment requires supersedes_declaration_record_id"
    predecessors = [
        item
        for (schema_id, _), item in accepted.items()
        if schema_id == declaration.value.schema_id
    ]
    predecessor = next(
        (item for item in predecessors if item.record_id == superseded_id),
        None,
    )
    if predecessor is None:
        return "planner semantic schema amendment must supersede an accepted declaration"
    latest = max(predecessors, key=lambda item: item.value.version)
    if predecessor.record_id != latest.record_id:
        return "planner semantic schema amendment must extend the latest accepted declaration"
    if declaration.value.version <= predecessor.value.version:
        return "planner semantic schema amendment version must increase"
    if declaration.value.semantic_role != predecessor.value.semantic_role:
        return "planner semantic schema amendment cannot change semantic_role"
    weakening = _schema_weakening_error(
        predecessor.value.json_schema,
        declaration.value.json_schema,
        path="$",
    )
    if weakening is not None:
        return f"planner semantic schema amendment weakens accepted schema: {weakening}"
    return None


def accepted_semantic_declaration(
    declarations: dict[tuple[str, int], SemanticSchemaDeclarationRecord],
    schema_id: str,
    schema_version: int,
) -> SemanticSchemaDeclarationRecord | None:
    """Resolve an exact declaration only when its authority chain is valid."""
    declaration = declarations.get((schema_id, schema_version))
    if declaration is None:
        return None
    remaining = dict(declarations)
    ordered = sorted(
        (item for (candidate_id, _), item in remaining.items() if candidate_id == schema_id),
        key=lambda item: item.value.version,
    )
    accepted: dict[tuple[str, int], SemanticSchemaDeclarationRecord] = {}
    for item in ordered:
        if semantic_declaration_conflict(item, accepted) is not None:
            return None
        accepted[(item.value.schema_id, item.value.version)] = item
    return declaration


def _schema_weakening_error(
    previous: Mapping[str, Any], amended: Mapping[str, Any], *, path: str
) -> str | None:
    """Reject schema amendments unless an exact semantic-equivalence proof exists.

    JSON Schema implication is deliberately not approximated here.  A partial
    keyword checker is unsafe because an unknown or newly introduced keyword
    can silently broaden the accepted language.  Until a separately authorized
    and complete implication engine is part of the contract, planner amendments
    may version a declaration but may not alter its schema.
    """
    if dict(previous) != dict(amended):
        return f"{path} changes schema without an authorized equivalence proof"
    return None


def _json_schema_error(value: Any, schema: Mapping[str, Any], *, path: str) -> str | None:
    """Validate with the declaration's draft and return the first stable error."""
    plain_schema = _plain_json(schema)
    if not isinstance(plain_schema, dict):
        return "semantic artifact content schema is invalid: $: declaration must be an object"
    validator_type = validators.validator_for(plain_schema)
    try:
        validator_type.check_schema(plain_schema)
    except SchemaError as exc:
        return f"semantic artifact content schema is invalid: {_format_schema_error(exc)}"
    errors = sorted(
        validator_type(plain_schema).iter_errors(_plain_json(value)),
        key=_validation_error_key,
    )
    if not errors:
        return None
    error = errors[0]
    return (
        f"semantic artifact content {_json_path(path, error)}: {error.message} "
        f"[keyword={error.validator}]"
    )


def _validation_error_key(error: ValidationError) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    return (
        tuple(str(item) for item in error.absolute_path),
        tuple(str(item) for item in error.absolute_schema_path),
        error.message,
    )


def _format_schema_error(error: SchemaError) -> str:
    location = _path_from_parts("$", error.absolute_schema_path)
    return f"{location}: {error.message}"


def _json_path(root: str, error: ValidationError) -> str:
    return _path_from_parts(root, error.absolute_path)


def _path_from_parts(root: str, parts: Iterable[object]) -> str:
    output = root
    for part in parts:
        if isinstance(part, int):
            output += f"[{part}]"
        else:
            output += f".{part}"
    return output


def _plain_json(value: Any) -> JsonValue:
    """Convert immutable projection containers to validator-native JSON values."""
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _plain_json(child) for key, child in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(Sequence[object], value)
        return [_plain_json(child) for child in sequence]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"semantic artifact contains non-JSON value: {type(value).__name__}")
