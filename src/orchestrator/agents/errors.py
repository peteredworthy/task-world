"""Agent-related error types."""


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
