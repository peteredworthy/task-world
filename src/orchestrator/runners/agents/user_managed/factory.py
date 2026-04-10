"""Factory for creating UserManagedAgent instances."""

from typing import Any

from orchestrator.runners.agents.user_managed.agent import UserManagedAgent


def create(
    agent_config: dict[str, Any],
    run_id: str | None = None,
    phase: str = "building",
    **kwargs: Any,
) -> UserManagedAgent:
    """Create a UserManagedAgent from agent_config.

    Requires ``service`` in kwargs (a TaskSubmitCallback implementation).
    WorkflowService implements this protocol.
    """
    service = kwargs.get("service")
    if service is None:
        raise ValueError(
            "UserManagedAgent factory requires 'service' kwarg (TaskSubmitCallback implementation)"
        )

    callback_channel = agent_config.get("callback_channel", "mcp")
    timeout_minutes = int(agent_config.get("timeout_minutes", 60))

    return UserManagedAgent(
        service=service,
        callback_channel=callback_channel,
        timeout_minutes=timeout_minutes,
    )
