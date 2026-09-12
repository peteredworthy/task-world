"""Codex Server agent sub-package — registers CODEX_SERVER."""

from orchestrator.config.enums import AgentRunnerType
from orchestrator.runners.agent_factory import register
from orchestrator.runners.agents.codex.agent import (  # noqa: F401
    CodexCommandExecutionReceipt,
    CodexDynamicToolReceipt,
    CodexServerAgent,
)
from orchestrator.runners.agents.codex.factory import create_codex_agent  # noqa: F401
from orchestrator.runners.agents.codex.config import (  # noqa: F401
    CODEX_SERVER_CONFIG,
    codex_server_config_with_models,
    prepare_codex_config,
)

register(AgentRunnerType.CODEX_SERVER, create_codex_agent, graph_capable=True)

__all__ = [
    "CodexServerAgent",
    "CodexCommandExecutionReceipt",
    "CodexDynamicToolReceipt",
    "create_codex_agent",
    "CODEX_SERVER_CONFIG",
    "codex_server_config_with_models",
    "prepare_codex_config",
]
