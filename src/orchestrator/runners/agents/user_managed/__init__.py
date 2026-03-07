"""User Managed agent package."""

try:
    from orchestrator.config.enums import AgentRunnerType
    from orchestrator.runners.agent_factory import register
    from orchestrator.runners.agents.user_managed.factory import create

    register(AgentRunnerType.USER_MANAGED, create)
except ImportError:
    pass  # Optional dependency not installed
