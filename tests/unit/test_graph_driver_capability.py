"""Unit tests for graph_driver's capability-derived supported runner set."""

from __future__ import annotations

from orchestrator.config.enums import AgentRunnerType
from orchestrator.runners import discover_agents
from orchestrator.workflow.graph_driver import get_supported_graph_runner_types

discover_agents()


def test_codex_server_is_supported() -> None:
    assert AgentRunnerType.CODEX_SERVER in get_supported_graph_runner_types()


def test_cli_subprocess_is_supported() -> None:
    assert AgentRunnerType.CLI_SUBPROCESS in get_supported_graph_runner_types()


def test_openhands_local_is_not_supported() -> None:
    assert AgentRunnerType.OPENHANDS_LOCAL not in get_supported_graph_runner_types()
