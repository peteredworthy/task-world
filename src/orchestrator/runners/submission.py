"""Shared runner-facing submission contract rendering."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, cast

from jsonschema import ValidationError as JsonSchemaValidationError, validators

from orchestrator.runners.types import SubmissionContract


def is_decision_submission(contract: SubmissionContract | None) -> bool:
    """Return whether runtime explicitly selected the decision-v1 interaction."""
    return contract is not None and contract.interaction_contract == "decision-v1"


def _resolve_local_definitions(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a self-contained schema with local ``$defs`` references inlined.

    Output schemas are embedded below ``submit.properties.outputs``.  A Pydantic
    schema's ``#/$defs/...`` references are document-root references, so merely
    nesting that schema makes those references point at the wrong root.  Resolve
    them here, at the one canonical submit-schema boundary used by every runner.
    """
    source = deepcopy(schema)
    raw_definitions = source.pop("$defs", {})
    definitions: dict[str, Any] = (
        cast(dict[str, Any], raw_definitions) if isinstance(raw_definitions, dict) else {}
    )

    def resolve(value: Any, resolving: tuple[str, ...] = ()) -> Any:
        if isinstance(value, list):
            items = cast(list[Any], value)
            return [resolve(item, resolving) for item in items]
        if not isinstance(value, dict):
            return value
        object_value = cast(dict[str, Any], value)
        reference = object_value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.removeprefix("#/$defs/")
            definition = definitions.get(name)
            if not isinstance(definition, dict):
                raise ValueError(f"unresolved local schema definition: {name}")
            definition_object = cast(dict[str, Any], definition)
            if name in resolving:
                raise ValueError(f"recursive local schema definition is unsupported: {name}")
            siblings: dict[str, Any] = {
                key: item for key, item in object_value.items() if key != "$ref"
            }
            resolved = resolve(deepcopy(definition_object), (*resolving, name))
            if not isinstance(resolved, dict):
                raise ValueError(f"invalid local schema definition: {name}")
            resolved_object = cast(dict[str, Any], resolved)
            resolved_siblings = resolve(siblings, resolving)
            if not isinstance(resolved_siblings, dict):
                raise ValueError("schema reference siblings must be an object")
            return {
                **resolved_object,
                **cast(dict[str, Any], resolved_siblings),
            }
        return {key: resolve(item, resolving) for key, item in object_value.items()}

    resolved_schema = resolve(source)
    if not isinstance(resolved_schema, dict):
        raise ValueError("submission output schema must be an object")
    return cast(dict[str, Any], resolved_schema)


def submission_tool_input_schema(contract: SubmissionContract | None) -> dict[str, Any]:
    """Return the single canonical JSON Schema for the ``submit`` tool."""
    if contract is None or not contract.requires_arguments:
        return {"type": "object", "properties": {}}
    output_properties: dict[str, Any] = {}
    required_outputs: list[str] = []
    for output in contract.outputs:
        if output.content_json_schema is None:
            continue
        output_properties[output.port] = _resolve_local_definitions(
            dict(output.content_json_schema)
        )
        if output.required:
            required_outputs.append(output.port)
    outputs_schema: dict[str, Any] = {
        "type": "object",
        "properties": output_properties,
        "additionalProperties": False,
    }
    if required_outputs:
        outputs_schema["required"] = required_outputs
    return {
        "type": "object",
        "properties": {"outputs": outputs_schema},
        "required": ["outputs"],
        "additionalProperties": False,
    }


def validate_submission_arguments(
    contract: SubmissionContract | None,
    arguments: dict[str, Any],
) -> None:
    """Validate authored arguments against the same schema every adapter advertises."""
    schema = submission_tool_input_schema(contract)
    try:
        validators.validator_for(schema)(schema).validate(arguments)
    except JsonSchemaValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path)
        location = f" at {path}" if path else ""
        raise ValueError(f"Input validation error{location}: {exc.message}") from exc


def submission_prompt_instruction(contract: SubmissionContract | None) -> str:
    """Render exact model instructions from the canonical submit schema."""
    if contract is None or not contract.requires_arguments:
        return "- **submit**()"
    schema = submission_tool_input_schema(contract)
    return (
        "- **submit**(outputs=...)\n"
        "  Required typed completion payload; do not call submit() without outputs.\n"
        "  The exact input JSON Schema is: "
        + json.dumps(schema, sort_keys=True, separators=(",", ":"))
    )


__all__ = [
    "is_decision_submission",
    "submission_prompt_instruction",
    "submission_tool_input_schema",
    "validate_submission_arguments",
]
