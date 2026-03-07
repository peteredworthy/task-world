"""Claude SDK agent package."""

try:
    from orchestrator.config.enums import AgentRunnerType
    from orchestrator.runners.agent_factory import register
    from orchestrator.runners.agents.claude_sdk.factory import create

    register(AgentRunnerType.CLAUDE_SDK, create)
except ImportError:
    pass  # Optional dependency not installed
