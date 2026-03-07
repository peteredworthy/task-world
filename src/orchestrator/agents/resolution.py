"""Agent resolution logic.

Resolves which agent to use for a given phase by cascading:
    task -> step -> routine -> system default
"""

import logging
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.agents.models import AgentConfigModel
from orchestrator.config.models import RoutineConfig, StepConfig, TaskConfig

logger = logging.getLogger(__name__)

Phase = Literal["planner", "builder", "verifier"]

# System defaults match the seeded agent names
_SYSTEM_DEFAULTS: dict[Phase, str] = {
    "planner": "Planner",
    "builder": "Builder",
    "verifier": "Verifier",
}


def resolve_agent_name(
    phase: Phase,
    task_config: TaskConfig | None = None,
    step_config: StepConfig | None = None,
    routine_config: RoutineConfig | None = None,
) -> str:
    """Resolve the agent name for a given phase using cascading lookup.

    Resolution order (first non-None wins):
        1. Task-level override
        2. Step-level override
        3. Routine-level override
        4. System default ("Planner", "Builder", or "Verifier")

    Args:
        phase: One of "planner", "builder", or "verifier".
        task_config: Optional task-level config.
        step_config: Optional step-level config.
        routine_config: Optional routine-level config.

    Returns:
        The resolved agent name.
    """
    attr = f"{phase}_agent"

    if task_config is not None:
        value = getattr(task_config, attr, None)
        if value is not None:
            return value

    if step_config is not None:
        value = getattr(step_config, attr, None)
        if value is not None:
            return value

    if routine_config is not None:
        value = getattr(routine_config, attr, None)
        if value is not None:
            return value

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
