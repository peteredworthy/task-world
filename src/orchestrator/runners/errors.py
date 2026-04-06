"""Agent-related error types."""

from __future__ import annotations

from datetime import datetime


class AgentError(Exception):
    """Base class for agent errors."""


class AgentConfigError(AgentError):
    """Agent configuration is invalid or incomplete.

    Raised at construction time when required configuration (e.g. API token,
    base URL) is missing or fails validation before any network I/O is
    attempted.
    """

    def __init__(self, agent_type: str, message: str) -> None:
        self.agent_type = agent_type
        self.message = message
        super().__init__(f"Agent '{agent_type}' configuration error: {message}")


class AgentExecutionError(AgentError):
    """Error during agent execution."""

    def __init__(self, agent_type: str, message: str) -> None:
        self.agent_type = agent_type
        self.message = message
        super().__init__(f"Agent '{agent_type}' execution failed: {message}")


class AgentNotAvailableError(AgentError):
    """Agent is not available on this system."""

    def __init__(self, agent_type: str, reason: str = "") -> None:
        self.agent_type = agent_type
        self.reason = reason
        msg = f"Agent '{agent_type}' is not available"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class AgentCancelledError(AgentError):
    """Agent execution was cancelled."""

    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type
        super().__init__(f"Agent '{agent_type}' execution was cancelled")


class AgentTimeoutError(AgentError):
    """Agent execution timed out waiting for external action."""

    def __init__(self, agent_type: str, message: str) -> None:
        self.agent_type = agent_type
        self.message = message
        super().__init__(f"Agent '{agent_type}' timed out: {message}")


class AgentRateLimitError(AgentError):
    """Agent hit an API rate or credit limit.

    Raised when the Claude CLI subprocess returns a rate-limit message instead
    of doing work.  The executor should pause the run immediately without
    consuming a retry slot.
    """

    def __init__(
        self,
        agent_type: str,
        session_id: str | None = None,
        resets_at: datetime | None = None,
    ) -> None:
        self.agent_type = agent_type
        self.session_id = session_id
        self.resets_at = resets_at
        reset_info = f" (resets at {resets_at})" if resets_at else ""
        super().__init__(f"Agent '{agent_type}' hit rate limit{reset_info}")
