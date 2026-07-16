"""Safe rendering for validation failures persisted in graph events."""

from pydantic import ValidationError


_MAX_VALIDATION_ERRORS = 8
_MAX_DURABLE_REASON_LENGTH = 1_000


def safe_exception_reason(
    exc: TypeError | ValueError,
    *,
    code: str,
    message: str,
) -> str:
    """Render an exception without persisting rejected user input."""

    if not isinstance(exc, ValidationError):
        return f"{message} [{code}]"[:_MAX_DURABLE_REASON_LENGTH]

    details: list[str] = []
    for error in exc.errors(include_input=False)[:_MAX_VALIDATION_ERRORS]:
        error_type = str(error["type"])
        safe_message = "Field required" if error_type == "missing" else "Validation failed"
        details.append(f"payload [{error_type}]: {safe_message}")
    reason = f"{message} [{code}]: " + "; ".join(details)
    return reason[:_MAX_DURABLE_REASON_LENGTH]


__all__ = ["safe_exception_reason"]
