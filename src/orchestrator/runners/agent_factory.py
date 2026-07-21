"""Agent factory with registry-based dispatch.

Agent packages register themselves via register() on import.
The executor calls create() to instantiate agents without a type-switch.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from orchestrator.config import AgentRunnerType, is_selectable_agent_runner_type
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

# Runner types whose adapter implements the graph callback contract (patch
# submission, grade). Declared at registration time alongside the factory,
# rather than a hand-maintained frozenset elsewhere — see graph_driver.py's
# get_supported_graph_runner_types().
_GRAPH_CAPABLE: dict[AgentRunnerType, bool] = {}


def register(
    agent_runner_type: AgentRunnerType,
    factory: AgentFactory,
    *,
    graph_capable: bool = False,
) -> None:
    """Register an agent factory for a given type.

    Args:
        graph_capable: Whether this runner's adapter can deliver graph
            callback tool calls (submit_graph_patch and friends, grade) into
            the graph dispatcher's in-process closures. Defaults to False.
    """
    _REGISTRY[agent_runner_type] = factory
    _GRAPH_CAPABLE[agent_runner_type] = graph_capable
    logger.debug(
        "Registered agent factory for %s (graph_capable=%s)",
        agent_runner_type.value,
        graph_capable,
    )


def create(
    agent_runner_type: AgentRunnerType,
    agent_runner_config: dict[str, Any],
    run_id: str | None = None,
    phase: str = "building",
    **kwargs: Any,
) -> AgentRunner:
    """Create an agent instance via the registry."""
    if not is_selectable_agent_runner_type(agent_runner_type):
        raise AgentNotAvailableError(
            agent_runner_type.value,
            "Retired agent runners cannot be used for execution",
        )
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


def get_registered_agent_runner_types() -> frozenset[AgentRunnerType]:
    """Return an immutable snapshot of registered runner types."""
    return frozenset(_REGISTRY)


def get_graph_capable_agent_runner_types() -> frozenset[AgentRunnerType]:
    """Return an immutable snapshot of runner types declared graph-capable."""
    return frozenset(runner_type for runner_type, capable in _GRAPH_CAPABLE.items() if capable)


def clear_registry() -> None:
    """Clear all registered factories (for testing)."""
    _REGISTRY.clear()
    _GRAPH_CAPABLE.clear()
