"""Agent factory with registry-based dispatch.

Agent packages register themselves via register() on import.
The executor calls create() to instantiate agents without a type-switch.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from orchestrator.config.enums import AgentRunnerType
from orchestrator.runners.errors import AgentNotAvailableError

if TYPE_CHECKING:
    from orchestrator.runners.interface import AgentRunner

logger = logging.getLogger(__name__)


class AgentFactory(Protocol):
    """Protocol that agent factory functions must satisfy.

    Return type is ``Any`` rather than ``AgentRunner`` because concrete agent
    classes may extend the protocol with additional ``execute`` parameters
    (e.g. ``on_complete_recovery``) which makes pyright reject a strict
    ``AgentRunner`` return annotation.  Conformance is verified at runtime.
    """

    def __call__(
        self,
        agent_runner_config: dict[str, Any],
        **kwargs: Any,
    ) -> Any: ...


# Global registry: AgentRunnerType -> factory callable
_REGISTRY: dict[AgentRunnerType, AgentFactory] = {}


def register(agent_runner_type: AgentRunnerType, factory: AgentFactory) -> None:
    """Register an agent factory for a given type."""
    _REGISTRY[agent_runner_type] = factory
    logger.debug("Registered agent factory for %s", agent_runner_type.value)


def create(
    agent_runner_type: AgentRunnerType,
    agent_runner_config: dict[str, Any],
    run_id: str | None = None,
    phase: str = "building",
    **kwargs: Any,
) -> AgentRunner:
    """Create an agent instance via the registry."""
    factory = _REGISTRY.get(agent_runner_type)
    if factory is None:
        raise AgentNotAvailableError(
            agent_runner_type.value if agent_runner_type else "none",
            f"No registered factory for agent runner type: {agent_runner_type}",
        )
    return factory(agent_runner_config, run_id=run_id, phase=phase, **kwargs)


def get_registry() -> dict[AgentRunnerType, AgentFactory]:
    """Return a copy of the current registry (for inspection/testing)."""
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Clear all registered factories (for testing)."""
    _REGISTRY.clear()
