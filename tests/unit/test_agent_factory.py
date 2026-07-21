"""Unit tests for the graph-capability extension to the agent factory registry."""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.config.enums import AgentRunnerType
from orchestrator.runners import agent_factory


@pytest.fixture(autouse=True)
def _clear_registry() -> Any:
    # Snapshot and restore rather than leaving the registry cleared: the
    # real sub-packages (codex, claude_cli, ...) register themselves via
    # discover_agents(), which imports each sub-module exactly once per
    # process (importlib.import_module is a no-op on an already-imported
    # module, so it does not re-run the register() call). Under
    # pytest-xdist, other test files in the same worker process may run
    # after this one and expect those real registrations to still be
    # present. Clearing without restoring would permanently blank the
    # registry for the rest of that worker's lifetime.
    saved_registry = agent_factory.get_registry()
    saved_graph_capable = agent_factory.get_graph_capable_agent_runner_types()
    agent_factory.clear_registry()
    yield
    agent_factory.clear_registry()
    for runner_type, factory in saved_registry.items():
        agent_factory.register(
            runner_type, factory, graph_capable=runner_type in saved_graph_capable
        )


def _noop_factory(agent_runner_config: dict[str, Any], **kwargs: Any) -> Any:
    return object()


def test_register_defaults_to_not_graph_capable() -> None:
    agent_factory.register(AgentRunnerType.OPENHANDS_LOCAL, _noop_factory)
    assert (
        AgentRunnerType.OPENHANDS_LOCAL not in agent_factory.get_graph_capable_agent_runner_types()
    )


def test_register_graph_capable_true_is_tracked() -> None:
    agent_factory.register(AgentRunnerType.CODEX_SERVER, _noop_factory, graph_capable=True)
    assert AgentRunnerType.CODEX_SERVER in agent_factory.get_graph_capable_agent_runner_types()


def test_get_graph_capable_agent_runner_types_is_a_snapshot() -> None:
    agent_factory.register(AgentRunnerType.CODEX_SERVER, _noop_factory, graph_capable=True)
    snapshot = agent_factory.get_graph_capable_agent_runner_types()
    agent_factory.register(AgentRunnerType.CLI_SUBPROCESS, _noop_factory, graph_capable=True)
    assert AgentRunnerType.CLI_SUBPROCESS not in snapshot
