"""Agent resolution logic.

Resolves which agent to use for a given phase by cascading:
    task -> step -> routine -> system default
"""

import logging
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.runners.profiles.models import AgentConfigModel

logger = logging.getLogger(__name__)

Phase = Literal["builder", "verifier"]

# System defaults match the seeded agent names
_SYSTEM_DEFAULTS: dict[Phase, str] = {
    "builder": "Builder",
    "verifier": "Verifier",
}


def resolve_agent_name(
    phase: Phase,
    task_agent: str | None = None,
    step_agent: str | None = None,
    routine_agent: str | None = None,
) -> str:
    """Resolve the agent name for a given phase using cascading lookup.

    Resolution order (first non-None wins):
        1. Task-level override  (task_agent)
        2. Step-level override  (step_agent)
        3. Routine-level override (routine_agent)
        4. System default ("Builder" or "Verifier")

    Args:
        phase: One of "builder" or "verifier".
        task_agent: Agent name from task config, or None if not set.
        step_agent: Agent name from step config, or None if not set.
        routine_agent: Agent name from routine config, or None if not set.

    Returns:
        The resolved agent name.
    """
    if task_agent is not None:
        return task_agent
    if step_agent is not None:
        return step_agent
    if routine_agent is not None:
        return routine_agent
    return _SYSTEM_DEFAULTS[phase]


async def get_agent_system_prompt(session: AsyncSession, agent_name: str) -> str | None:
    """Look up an agent's system_prompt by name.

    Logs a warning if the agent does not exist in the database.

    Args:
        session: Async SQLAlchemy session.
        agent_name: The agent name to look up.

    Returns:
        The agent's system_prompt, or None if the agent does not exist.
    """
    result = await session.execute(
        select(AgentConfigModel).where(AgentConfigModel.name == agent_name)
    )
    model = result.scalar_one_or_none()
    if model is None:
        logger.warning(
            "Agent '%s' referenced in config does not exist in the database.",
            agent_name,
        )
        return None
    return model.system_prompt
