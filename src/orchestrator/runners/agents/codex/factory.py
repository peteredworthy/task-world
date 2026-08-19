"""Factory for CODEX_SERVER agents.

Extracted from ``executor._create_agent`` CODEX_SERVER branch.
"""

from __future__ import annotations

from typing import Any

from orchestrator.runners.agents.codex.agent import CodexServerAgent


def create_codex_agent(
    agent_runner_config: dict[str, Any],
    **kwargs: Any,
) -> CodexServerAgent:
    """Create a CodexServerAgent from agent_runner_config.

    Args:
        agent_runner_config: Configuration dict from the run (model, api_key,
            restrictions).
        **kwargs: Ignored (for forward compatibility).

    Returns:
        A configured CodexServerAgent instance.
    """
    model = agent_runner_config.get("model")
    api_key = agent_runner_config.get("api_key")
    restrictions = agent_runner_config.get("restrictions", "managed")
    reasoning_effort = agent_runner_config.get("reasoning_effort", "high")
    local_provider = agent_runner_config.get("local_provider", "openai")

    return CodexServerAgent(
        model=model,
        api_key=api_key,
        restrictions=str(restrictions),
        reasoning_effort=str(reasoning_effort),
        local_provider=str(local_provider),
    )
