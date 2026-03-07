"""Claude CLI agent sub-package — registers CLI_SUBPROCESS."""

from orchestrator.config.enums import AgentRunnerType
from orchestrator.runners.agent_factory import register
from orchestrator.runners.agents.claude_cli.agent import CLIAgent, ClaudeCliQuotaAgent
from orchestrator.runners.agents.claude_cli.factory import create_cli_agent
from orchestrator.runners.agents.claude_cli.config import (
    CLI_SUBPROCESS_CONFIG,
    cli_config_for_command,
    cli_config_for_codex,
)

register(AgentRunnerType.CLI_SUBPROCESS, create_cli_agent)

__all__ = [
    "CLIAgent",
    "ClaudeCliQuotaAgent",
    "create_cli_agent",
    "CLI_SUBPROCESS_CONFIG",
    "cli_config_for_command",
    "cli_config_for_codex",
]
