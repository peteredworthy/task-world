"""Unit tests for central error handling module."""

from typing import Any, cast

import pytest

from orchestrator.errors import ErrorCode, OrchestratorError


class TestErrorCode:
    """Tests for ErrorCode enum."""

    def test_error_code_values(self) -> None:
        """Error codes have correct string values."""
        assert ErrorCode.ROUTINE_NOT_FOUND.value == "routine_not_found"
        assert ErrorCode.RUN_NOT_FOUND.value == "run_not_found"
        assert ErrorCode.INVALID_TRANSITION.value == "invalid_transition"
        assert ErrorCode.DATABASE_ERROR.value == "database_error"

    def test_user_error_categorization(self) -> None:
        """User errors (4xx) are correctly identified."""
        user_errors = [
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
        ]

        for code in user_errors:
            assert code.is_user_error, f"{code} should be a user error"
            assert not code.is_system_error, f"{code} should not be a system error"

    def test_system_error_categorization(self) -> None:
        """System errors (5xx) are correctly identified."""
        system_errors = [
            ErrorCode.DATABASE_ERROR,
            ErrorCode.AGENT_ERROR,
            ErrorCode.INTERNAL_ERROR,
            ErrorCode.AGENT_NOT_AVAILABLE,
        ]

        for code in system_errors:
            assert code.is_system_error, f"{code} should be a system error"
            assert not code.is_user_error, f"{code} should not be a user error"

    def test_all_codes_categorized(self) -> None:
        """Every error code is either user or system error."""
        for code in ErrorCode:
            # Each code must be exactly one category
            assert code.is_user_error or code.is_system_error, f"{code} must be categorized"
            assert code.is_user_error != code.is_system_error, (
                f"{code} cannot be both user and system error"
            )


class TestOrchestratorError:
    """Tests for OrchestratorError exception class."""

    def test_error_creation_minimal(self) -> None:
        """Can create error with just code and message."""
        err = OrchestratorError(
            code=ErrorCode.RUN_NOT_FOUND,
            message="Run abc123 not found",
        )

        assert err.code == ErrorCode.RUN_NOT_FOUND
        assert err.message == "Run abc123 not found"
        assert err.details == {}
        assert str(err) == "Run abc123 not found"

    def test_error_creation_with_details(self) -> None:
        """Can create error with details dictionary."""
        err = OrchestratorError(
            code=ErrorCode.INVALID_TRANSITION,
            message="Cannot transition from building to completed",
            details={
                "from_status": "building",
                "to_status": "completed",
                "reason": "Must pass through verification",
            },
        )

        assert err.code == ErrorCode.INVALID_TRANSITION
        assert err.message == "Cannot transition from building to completed"
        assert err.details == {
            "from_status": "building",
            "to_status": "completed",
            "reason": "Must pass through verification",
        }

    def test_error_to_dict_minimal(self) -> None:
        """to_dict() returns correct format without details."""
        err = OrchestratorError(
            code=ErrorCode.ROUTINE_NOT_FOUND,
            message="Routine not found: demo.yaml",
        )

        result = err.to_dict()

        assert result == {
            "error": "routine_not_found",
            "message": "Routine not found: demo.yaml",
            "details": {},
        }

    def test_error_to_dict_with_details(self) -> None:
        """to_dict() includes details when present."""
        err = OrchestratorError(
            code=ErrorCode.GATE_FAILED,
            message="Checklist gate blocked",
            details={
                "gate_name": "pre_verification",
                "blocking_items": ["req1", "req2"],
                "completed_count": 3,
                "total_count": 5,
            },
        )

        result = err.to_dict()

        assert result == {
            "error": "gate_failed",
            "message": "Checklist gate blocked",
            "details": {
                "gate_name": "pre_verification",
                "blocking_items": ["req1", "req2"],
                "completed_count": 3,
                "total_count": 5,
            },
        }

    def test_error_to_dict_various_detail_types(self) -> None:
        """to_dict() handles various detail value types."""
        err = OrchestratorError(
            code=ErrorCode.DATABASE_ERROR,
            message="Database operation failed",
            details={
                "operation": "insert",
                "table": "runs",
                "retry_count": 3,
                "success": False,
                "last_error": None,
                "affected_rows": 0,
            },
        )

        result = err.to_dict()
        details = cast(dict[str, Any], result["details"])

        assert details["operation"] == "insert"
        assert details["retry_count"] == 3
        assert details["success"] is False
        assert details["last_error"] is None
        assert details["affected_rows"] == 0

    def test_error_is_exception(self) -> None:
        """OrchestratorError can be raised and caught as Exception."""
        with pytest.raises(OrchestratorError) as exc_info:
            raise OrchestratorError(
                code=ErrorCode.AGENT_ERROR,
                message="Agent crashed",
            )

        err = exc_info.value
        assert err.code == ErrorCode.AGENT_ERROR
        assert err.message == "Agent crashed"

    def test_error_inheritance(self) -> None:
        """OrchestratorError is subclass of Exception."""
        err = OrchestratorError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Something went wrong",
        )

        assert isinstance(err, Exception)
        assert isinstance(err, OrchestratorError)

    def test_error_equality_by_attributes(self) -> None:
        """Errors with same attributes are distinct objects."""
        err1 = OrchestratorError(
            code=ErrorCode.RUN_NOT_FOUND,
            message="Run not found",
            details={"run_id": "abc"},
        )
        err2 = OrchestratorError(
            code=ErrorCode.RUN_NOT_FOUND,
            message="Run not found",
            details={"run_id": "abc"},
        )

        # Different objects
        assert err1 is not err2

        # But same serialization
        assert err1.to_dict() == err2.to_dict()


class TestErrorUsageExamples:
    """Tests demonstrating typical error usage patterns."""

    def test_not_found_error_pattern(self) -> None:
        """Typical pattern for resource not found errors."""
        run_id = "abc123"

        err = OrchestratorError(
            code=ErrorCode.RUN_NOT_FOUND,
            message=f"Run {run_id} does not exist",
            details={"run_id": run_id},
        )

        # Useful for API responses
        response = err.to_dict()
        assert response["error"] == "run_not_found"
        assert run_id in cast(str, response["message"])

    def test_validation_error_pattern(self) -> None:
        """Typical pattern for validation errors."""
        errors = [
            "Field 'name' is required",
            "Field 'priority' must be one of: critical, expected, nice",
        ]

        err = OrchestratorError(
            code=ErrorCode.INVALID_CONFIG,
            message="Routine validation failed",
            details={
                "path": "routines/demo.yaml",
                "errors": errors,
                "error_count": len(errors),
            },
        )

        assert err.code.is_user_error
        assert err.details["error_count"] == 2

    def test_system_error_pattern(self) -> None:
        """Typical pattern for system errors."""
        err = OrchestratorError(
            code=ErrorCode.DATABASE_ERROR,
            message="Failed to connect to database",
            details={
                "database": "orchestrator.db",
                "error_type": "OperationalError",
                "retry_count": 3,
            },
        )

        assert err.code.is_system_error
        assert err.details["retry_count"] == 3

    def test_agent_error_pattern(self) -> None:
        """Typical pattern for agent execution errors."""
        err = OrchestratorError(
            code=ErrorCode.AGENT_ERROR,
            message="Agent execution failed",
            details={
                "agent_type": "openhands",
                "task_id": "task123",
                "error": "Connection timeout",
                "duration_seconds": 120,
            },
        )

        assert err.code == ErrorCode.AGENT_ERROR
        assert err.code.is_system_error
