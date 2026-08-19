"""Safe rendering for validation failures persisted in graph events."""

import re
from typing import Any, cast

from pydantic import ValidationError


_MAX_VALIDATION_ERRORS = 32
_MAX_DURABLE_REASON_LENGTH = 4_000
_MAX_LOCATION_COMPONENT_LENGTH = 80
_SENSITIVE_LOCATION_COMPONENT = re.compile(
    r"(?:api[_-]?key|credential|password|secret|token|auth|sk[-_])",
    re.IGNORECASE,
)


_SAFE_MESSAGES_BY_TYPE = {
    "missing": "Field required",
    "extra_forbidden": "Extra field is not allowed",
    "bool_type": "Input must be a boolean",
    "dict_type": "Input must be an object",
    "int_type": "Input must be an integer",
    "int_parsing": "Input must be an integer",
    "list_type": "Input must be a list",
    "too_long": "Input exceeds the maximum allowed length",
    "literal_error": "Input must be one of the allowed values",
    "model_type": "Input must be an object",
    "string_type": "Input must be a string",
    "union_tag_invalid": "Input has an invalid variant tag",
    "union_tag_not_found": "Input is missing its variant tag",
}


def safe_validation_path(components: tuple[object, ...]) -> str:
    """Render a validation path without rendering rejected values.

    Both Pydantic locations and manually-created dynamic-tool paths use this
    renderer so field names cannot turn diagnostics into an unbounded or
    control-character-containing payload.
    """

    location = ""
    for component in components:
        if isinstance(component, int):
            location += f"[{component}]"
            continue
        if not isinstance(component, str):
            location += ".<redacted>"
            continue
        if _SENSITIVE_LOCATION_COMPONENT.search(component):
            location += ".<redacted>"
            continue
        escaped = component.encode("unicode_escape").decode("ascii")
        if len(escaped) > _MAX_LOCATION_COMPONENT_LENGTH:
            escaped = f"{escaped[:_MAX_LOCATION_COMPONENT_LENGTH]}…"
        location += f".{escaped}"
    return location.removeprefix(".") or "payload"


def _safe_location(error: dict[str, object]) -> str:
    """Render a Pydantic location without rendering rejected values."""

    raw_location = error.get("loc")
    if not isinstance(raw_location, tuple):
        return "payload"
    return safe_validation_path(cast(tuple[object, ...], raw_location))


def _safe_message(error_type: str) -> str:
    """Return a static explanation for a Pydantic error type.

    ``ValidationError.errors()[*]["msg"]`` can be constructed by arbitrary
    validators, so it must not be persisted or returned to an agent directly.
    The type is Pydantic-controlled and paired with a stable safe explanation.
    """

    return _SAFE_MESSAGES_BY_TYPE.get(error_type, "Validation failed")


def safe_validation_diagnostics(
    exc: ValidationError,
    *,
    max_errors: int | None = _MAX_VALIDATION_ERRORS,
) -> dict[str, Any]:
    """Return bounded, value-free validation diagnostics for durable events.

    The count covers every Pydantic error even when the detail list reaches its
    cap.  Neither ``input`` nor validator-provided ``msg`` is retained, so a
    rejected patch cannot leak arbitrary tool input into the event journal.
    """

    rendered = [
        {
            "path": _safe_location(dict(raw_error)),
            "code": str(raw_error.get("type", "validation_error")),
        }
        for raw_error in exc.errors(include_input=False)
    ]
    rendered.sort(key=lambda item: (item["path"], item["code"]))
    selected = rendered if max_errors is None else rendered[:max_errors]
    errors = [
        {
            **item,
            "message": _safe_message(item["code"]),
        }
        for item in selected
    ]
    omitted_error_count = len(rendered) - len(errors)
    return {
        "error_count": len(rendered),
        "errors": errors,
        "omitted_error_count": omitted_error_count,
    }


def safe_exception_reason(
    exc: TypeError | ValueError,
    *,
    code: str,
    message: str,
) -> str:
    """Render an exception without persisting rejected user input."""

    if not isinstance(exc, ValidationError):
        return f"{message} [{code}]"[:_MAX_DURABLE_REASON_LENGTH]

    diagnostics = safe_validation_diagnostics(exc)
    details = [
        f"payload [{item['code']}] at {item['path']}: {item['message']}"
        for item in diagnostics["errors"]
    ]
    omitted_error_count = diagnostics["omitted_error_count"]
    if omitted_error_count:
        details.append(f"{omitted_error_count} additional validation errors omitted")
    reason = f"{message} [{code}]: " + "; ".join(details)
    return reason[:_MAX_DURABLE_REASON_LENGTH]


__all__ = ["safe_exception_reason", "safe_validation_diagnostics", "safe_validation_path"]
