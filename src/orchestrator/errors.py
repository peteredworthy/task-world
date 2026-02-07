"""Central error types and error code definitions.

This module provides a unified error code system for categorizing errors
throughout the orchestrator. Domain-specific exceptions (RoutineNotFoundError,
RunNotFoundError, etc.) remain in their respective modules for backward
compatibility, but can optionally use OrchestratorError as a base.

Error codes are categorized into:
- User errors (4xx): Invalid input, missing resources, invalid state transitions
- System errors (5xx): Database failures, agent crashes, internal errors
"""

from enum import Enum


class ErrorCode(Enum):
    """Error codes categorized by HTTP status code ranges.

    4xx codes indicate user/client errors (bad input, missing resources).
    5xx codes indicate system/server errors (crashes, database failures).
    """

    # User errors (4xx)
    ROUTINE_NOT_FOUND = "routine_not_found"
    RUN_NOT_FOUND = "run_not_found"
    STEP_NOT_FOUND = "step_not_found"
    TASK_NOT_FOUND = "task_not_found"
    CHECKLIST_ITEM_NOT_FOUND = "checklist_item_not_found"
    INVALID_CONFIG = "invalid_config"
    INVALID_TRANSITION = "invalid_transition"
    GATE_FAILED = "gate_failed"
    TASK_LOCKED = "task_locked"
    MISSING_REQUIRED_INPUT = "missing_required_input"
    AUTHENTICATION_FAILED = "authentication_failed"

    # System errors (5xx)
    DATABASE_ERROR = "database_error"
    AGENT_ERROR = "agent_error"
    INTERNAL_ERROR = "internal_error"
    AGENT_NOT_AVAILABLE = "agent_not_available"

    @property
    def is_user_error(self) -> bool:
        """Return True if this is a user/client error (4xx)."""
        return self in {
            ErrorCode.ROUTINE_NOT_FOUND,
            ErrorCode.RUN_NOT_FOUND,
            ErrorCode.STEP_NOT_FOUND,
            ErrorCode.TASK_NOT_FOUND,
            ErrorCode.CHECKLIST_ITEM_NOT_FOUND,
            ErrorCode.INVALID_CONFIG,
            ErrorCode.INVALID_TRANSITION,
            ErrorCode.GATE_FAILED,
            ErrorCode.TASK_LOCKED,
            ErrorCode.MISSING_REQUIRED_INPUT,
            ErrorCode.AUTHENTICATION_FAILED,
        }

    @property
    def is_system_error(self) -> bool:
        """Return True if this is a system/server error (5xx)."""
        return not self.is_user_error


class OrchestratorError(Exception):
    """Base exception class with structured error code and details.

    Provides a consistent error format with:
    - error code (from ErrorCode enum)
    - human-readable message
    - optional details dict for additional context

    Example:
        raise OrchestratorError(
            code=ErrorCode.RUN_NOT_FOUND,
            message="Run abc123 does not exist",
            details={"run_id": "abc123"}
        )
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, object]:
        """Serialize error to dictionary format for API responses.

        Returns:
            Dictionary with 'error', 'message', and 'details' keys.
        """
        return {
            "error": self.code.value,
            "message": self.message,
            "details": self.details,
        }
