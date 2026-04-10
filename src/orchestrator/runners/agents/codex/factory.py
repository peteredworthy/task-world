"""Factory for CODEX_SERVER agents.

Extracted from ``executor._create_agent`` CODEX_SERVER branch.
"""

from __future__ import annotations

from typing import Any

from orchestrator.runners.agents.codex.agent import CodexServerAgent


def create_codex_agent(
    agent_config: dict[str, Any],
    **kwargs: Any,
) -> CodexServerAgent:
    """Create a CodexServerAgent from agent_config.

    Args:
        agent_config: Configuration dict from the run (model, callback_channel,
            api_key, restrictions).
        **kwargs: Ignored (for forward compatibility).

    Returns:
        A configured CodexServerAgent instance.
    """
    model = agent_config.get("model")
    callback_channel = agent_config.get("callback_channel", "rest")
    api_key = agent_config.get("api_key")
    restrictions = agent_config.get("restrictions", "no-network")

    return CodexServerAgent(
        model=model,
        callback_channel=callback_channel,
        api_key=api_key,
        restrictions=str(restrictions),
    )
