"""Factory for OPENHANDS_LOCAL and OPENHANDS_DOCKER agents.

Extracted from ``executor._create_agent`` OPENHANDS_LOCAL and
OPENHANDS_DOCKER branches.
"""

from __future__ import annotations

from typing import Any

from orchestrator.runners.detection.config_utils import coerce_llm_config


def create_local(
    agent_config: dict[str, Any],
    **kwargs: Any,
) -> Any:
    """Create an OpenHandsAgent (local) from agent_config.

    Import is deferred to avoid pulling in optional ``openhands`` dependency
    at module load time.

    Args:
        agent_config: Configuration dict from the run.
        **kwargs: Ignored (for forward compatibility).

    Returns:
        A configured OpenHandsAgent instance.
    """
    from orchestrator.runners.agents.openhands.agent import OpenHandsAgent

    api_key = agent_config.get("api_key")
    model = agent_config.get("model", "gpt-5-mini")
    max_iterations = int(agent_config.get("max_iterations", 100))
    max_actions = int(agent_config.get("max_actions", 200))
    llm_config = coerce_llm_config(agent_config)

    return OpenHandsAgent(
        api_key=api_key,
        model=model,
        max_iterations=max_iterations,
        max_actions=max_actions,
        llm_config=llm_config,
    )


def create_docker(
    agent_config: dict[str, Any],
    **kwargs: Any,
) -> Any:
    """Create a DockerOpenHandsAgent from agent_config.

    Import is deferred to avoid pulling in optional ``openhands`` dependency
    at module load time.

    Args:
        agent_config: Configuration dict from the run.
        **kwargs: Ignored (for forward compatibility).

    Returns:
        A configured DockerOpenHandsAgent instance.
    """
    from orchestrator.runners.agents.openhands.docker_agent import DockerOpenHandsAgent

    api_key = agent_config.get("api_key")
    model = agent_config.get("model", "gpt-5-mini")
    max_iterations = int(agent_config.get("max_iterations", 100))
    server_image = agent_config.get("server_image")
    llm_config = coerce_llm_config(agent_config)

    build_kwargs: dict[str, Any] = {
        "api_key": api_key,
        "model": model,
        "max_iterations": max_iterations,
        "llm_config": llm_config,
    }
    if server_image is not None:
        build_kwargs["server_image"] = server_image

    return DockerOpenHandsAgent(**build_kwargs)
