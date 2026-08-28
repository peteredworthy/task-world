"""Shared JSON Schema declaration validation for configuration boundaries."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

from jsonschema import SchemaError, validators


type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


def json_schema_declaration_error(schema: Mapping[str, Any]) -> str | None:
    """Return a stable error when a declaration is not a valid JSON Schema."""
    plain_schema = cast(dict[str, Any], _plain_json(schema))
    validator_type = validators.validator_for(plain_schema)
    try:
        validator_type.check_schema(plain_schema)
    except SchemaError as exc:
        return _format_schema_error(exc)
    return None


def _format_schema_error(error: SchemaError) -> str:
    return f"{_path_from_parts('$', error.absolute_schema_path)}: {error.message}"


def _path_from_parts(root: str, parts: Iterable[object]) -> str:
    output = root
    for part in parts:
        if isinstance(part, int):
            output += f"[{part}]"
        else:
            output += f".{part}"
    return output


def _plain_json(value: Any) -> JsonValue:
    """Convert immutable mapping containers to validator-native JSON values."""
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _plain_json(child) for key, child in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(Sequence[object], value)
        return [_plain_json(child) for child in sequence]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"JSON Schema contains non-JSON value: {type(value).__name__}")
