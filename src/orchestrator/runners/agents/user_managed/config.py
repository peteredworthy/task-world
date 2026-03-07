"""Config schema and detection for the User Managed agent."""

from __future__ import annotations

from orchestrator.runners.types import AgentConfigField, AgentOption
from orchestrator.config.enums import AgentRunnerType


_USER_MANAGED_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="callback_channel",
        field_type="select",
        default="mcp",
        description="How the external agent calls back to the orchestrator",
        options=["rest", "mcp"],
    ),
    AgentConfigField(
        name="timeout_minutes",
        field_type="number",
        default=60,
        description="Minutes to wait for agent to submit before timing out",
    ),
]


def detect() -> AgentOption:
    """User Managed is always available for external agent connections."""
    return AgentOption(
        agent_type=AgentRunnerType.USER_MANAGED,
        name="User Managed",
        title="User Managed Agent",
        description="Passive agent that waits for external actors (humans or third-party tools) to complete work via REST API or MCP.",
        available=True,
        detail="Always available for external agent connections",
        config_schema=_USER_MANAGED_CONFIG,
    )
