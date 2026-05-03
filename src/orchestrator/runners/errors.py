"""Agent runner-related error types."""

from __future__ import annotations

from datetime import datetime


class AgentError(Exception):
    """Base class for agent runner errors."""


class AgentConfigError(AgentError):
    """Agent runner configuration is invalid or incomplete.

    Raised at construction time when required configuration (e.g. API token,
    base URL) is missing or fails validation before any network I/O is
    attempted.
    """

    def __init__(self, agent_runner_type: str, message: str) -> None:
        self.agent_runner_type = agent_runner_type
        self.message = message
        super().__init__(f"Agent runner '{agent_runner_type}' configuration error: {message}")


class AgentExecutionError(AgentError):
    """Error during agent execution."""

    def __init__(self, agent_runner_type: str, message: str) -> None:
        self.agent_runner_type = agent_runner_type
        self.message = message
        super().__init__(f"Agent runner '{agent_runner_type}' execution failed: {message}")


class AgentNotAvailableError(AgentError):
    """Agent runner is not available on this system."""

    def __init__(self, agent_runner_type: str, reason: str = "") -> None:
        self.agent_runner_type = agent_runner_type
        self.reason = reason
        msg = f"Agent runner '{agent_runner_type}' is not available"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class AgentCancelledError(AgentError):
    """Agent runner execution was cancelled."""

    def __init__(self, agent_runner_type: str) -> None:
        self.agent_runner_type = agent_runner_type
        super().__init__(f"Agent runner '{agent_runner_type}' execution was cancelled")


class AgentTimeoutError(AgentError):
    """Agent runner execution timed out waiting for external action."""

    def __init__(self, agent_runner_type: str, message: str) -> None:
        self.agent_runner_type = agent_runner_type
        self.message = message
        super().__init__(f"Agent runner '{agent_runner_type}' timed out: {message}")


class AgentRateLimitError(AgentError):
    """Agent runner hit an API rate or credit limit.

    Raised when the Claude CLI subprocess returns a rate-limit message instead
    of doing work.  The executor should pause the run immediately without
    consuming a retry slot.
    """

    def __init__(
        self,
        agent_runner_type: str,
        session_id: str | None = None,
        resets_at: datetime | None = None,
    ) -> None:
        self.agent_runner_type = agent_runner_type
        self.session_id = session_id
        self.resets_at = resets_at
        reset_info = f" (resets at {resets_at})" if resets_at else ""
        super().__init__(f"Agent runner '{agent_runner_type}' hit rate limit{reset_info}")
