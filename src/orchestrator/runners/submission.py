"""Shared runner-facing submission contract rendering."""

from __future__ import annotations

import json
from typing import Any

from orchestrator.runners.types import SubmissionContract


def submission_tool_input_schema(contract: SubmissionContract | None) -> dict[str, Any]:
    """Return the single canonical JSON Schema for the ``submit`` tool."""
    if contract is None or not contract.requires_arguments:
        return {"type": "object", "properties": {}}
    output_properties: dict[str, Any] = {}
    required_outputs: list[str] = []
    for output in contract.outputs:
        if output.content_json_schema is None:
            continue
        output_properties[output.port] = dict(output.content_json_schema)
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


__all__ = ["submission_prompt_instruction", "submission_tool_input_schema"]
