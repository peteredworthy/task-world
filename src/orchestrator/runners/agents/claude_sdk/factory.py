"""Factory for creating ClaudeSDKAgent instances."""

from typing import Any

from orchestrator.runners.agents.claude_sdk.agent import ClaudeSDKAgent


def create(
    agent_runner_config: dict[str, Any],
    run_id: str | None = None,
    phase: str = "building",
    **kwargs: Any,
) -> ClaudeSDKAgent:
    """Create a ClaudeSDKAgent from agent_runner_config."""
    model = agent_runner_config.get("model", "claude-sonnet-4-5")
    api_key = agent_runner_config.get("api_key")
    auth_token = agent_runner_config.get("auth_token")
    max_turns = agent_runner_config.get("max_turns", 200)

    return ClaudeSDKAgent(
        model=model,
        api_key=api_key,
        auth_token=auth_token,
        max_turns=max_turns,
    )
