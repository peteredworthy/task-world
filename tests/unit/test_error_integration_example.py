"""Integration example showing how to use central error types with domain-specific exceptions.

This demonstrates how the new central error types (ErrorCode, OrchestratorError)
can coexist with existing domain-specific exceptions for backward compatibility.
"""

from orchestrator.runners.errors import AgentExecutionError
from orchestrator.errors import ErrorCode, OrchestratorError
from orchestrator.config.routines.errors import RoutineNotFoundError
from orchestrator.state.errors import RunNotFoundError, TaskNotFoundError
from orchestrator.workflow import GateBlockedError, InvalidTransitionError


class TestErrorIntegration:
    """Examples showing error type integration patterns."""

    def test_new_code_can_use_orchestrator_error(self) -> None:
        """New code can use OrchestratorError directly."""
        error = OrchestratorError(
            code=ErrorCode.DATABASE_ERROR,
            message="Connection failed",
            details={"retry_count": 3},
        )

        # Error has structured format
        assert error.code == ErrorCode.DATABASE_ERROR
        assert error.code.is_system_error

        # Can be serialized for API responses
        error_dict = error.to_dict()
        assert error_dict["error"] == "database_error"
        details = error_dict["details"]
        assert isinstance(details, dict)
        assert details["retry_count"] == 3

    def test_existing_domain_errors_still_work(self) -> None:
        """Existing domain-specific errors continue to work."""
        # These are all still valid and continue to work
        routine_error = RoutineNotFoundError("demo.yaml")
        run_error = RunNotFoundError("abc123")
        task_error = TaskNotFoundError("abc123", "task1")
        gate_error = GateBlockedError("pre_verification", ["req1", "req2"])
        transition_error = InvalidTransitionError("building", "completed")
        agent_error = AgentExecutionError("cli", "timeout")

        # All are exceptions
        assert isinstance(routine_error, Exception)
        assert isinstance(run_error, Exception)
        assert isinstance(task_error, Exception)
        assert isinstance(gate_error, Exception)
        assert isinstance(transition_error, Exception)
        assert isinstance(agent_error, Exception)

    def test_error_codes_map_to_domain_errors(self) -> None:
        """ErrorCode enum values match domain error conventions."""
        # Error codes match the error field in API responses
        assert ErrorCode.ROUTINE_NOT_FOUND.value == "routine_not_found"
        assert ErrorCode.RUN_NOT_FOUND.value == "run_not_found"
        assert ErrorCode.TASK_NOT_FOUND.value == "task_not_found"
        assert ErrorCode.INVALID_TRANSITION.value == "invalid_transition"
        assert ErrorCode.GATE_FAILED.value == "gate_failed"
        assert ErrorCode.AGENT_ERROR.value == "agent_error"

    def test_error_categorization_helps_api_responses(self) -> None:
        """Error codes can be categorized for HTTP status mapping."""
        # User errors (4xx)
        assert ErrorCode.ROUTINE_NOT_FOUND.is_user_error
        assert ErrorCode.RUN_NOT_FOUND.is_user_error
        assert ErrorCode.INVALID_TRANSITION.is_user_error
        assert ErrorCode.GATE_FAILED.is_user_error

        # System errors (5xx)
        assert ErrorCode.DATABASE_ERROR.is_system_error
        assert ErrorCode.AGENT_ERROR.is_system_error
        assert ErrorCode.AGENT_NOT_AVAILABLE.is_system_error

    def test_wrapping_domain_errors_in_orchestrator_error(self) -> None:
        """Domain errors can be wrapped in OrchestratorError for new code."""
        # Old domain error
        domain_error = RunNotFoundError("abc123")

        # Can be wrapped with structured error code
        wrapped = OrchestratorError(
            code=ErrorCode.RUN_NOT_FOUND,
            message=str(domain_error),
            details={"run_id": domain_error.run_id},
        )

        # Now has structured format
        assert wrapped.code.is_user_error
        error_dict = wrapped.to_dict()
        assert error_dict["error"] == "run_not_found"
        details = error_dict["details"]
        assert isinstance(details, dict)
        assert details["run_id"] == "abc123"

    def test_consistent_error_format_for_cli(self) -> None:
        """CLI can use to_dict() for consistent error formatting."""
        errors = [
            OrchestratorError(
                ErrorCode.RUN_NOT_FOUND,
                "Run not found",
                {"run_id": "abc"},
            ),
            OrchestratorError(
                ErrorCode.AGENT_ERROR,
                "Agent crashed",
                {"agent_type": "cli"},
            ),
            OrchestratorError(
                ErrorCode.INVALID_CONFIG,
                "Missing field",
                {"field": "name"},
            ),
        ]

        # All have consistent format
        for error in errors:
            error_dict = error.to_dict()
            assert "error" in error_dict
            assert "message" in error_dict
            assert "details" in error_dict
            assert isinstance(error_dict["error"], str)
            assert isinstance(error_dict["message"], str)
            assert isinstance(error_dict["details"], dict)

    def test_future_api_error_handlers_can_use_error_codes(self) -> None:
        """Future API handlers can map ErrorCode to HTTP status."""

        # Hypothetical mapping function (not implemented yet)
        def get_http_status(code: ErrorCode) -> int:
            if code == ErrorCode.RUN_NOT_FOUND:
                return 404
            elif code == ErrorCode.INVALID_TRANSITION:
                return 409
            elif code == ErrorCode.GATE_FAILED:
                return 409
            elif code == ErrorCode.DATABASE_ERROR:
                return 500
            elif code == ErrorCode.AGENT_ERROR:
                return 500
            else:
                return 500

        # User errors typically 4xx
        assert get_http_status(ErrorCode.RUN_NOT_FOUND) == 404
        assert get_http_status(ErrorCode.INVALID_TRANSITION) == 409

        # System errors typically 5xx
        assert get_http_status(ErrorCode.DATABASE_ERROR) == 500
        assert get_http_status(ErrorCode.AGENT_ERROR) == 500
