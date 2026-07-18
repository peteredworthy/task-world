"""Regression guard for complete Claude Agent SDK runtime removal."""

from __future__ import annotations

import asyncio
from pathlib import Path

from orchestrator.config import AgentRunnerType
from orchestrator.runners import (
    ClaudeCliQuotaAgent,
    ToolDetector,
    cli_config_for_command,
    discover_agents,
    get_registered_agent_runner_types,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_claude_sdk_runtime_is_not_installed_registered_or_discoverable() -> None:
    """The retired historical value must have no executable SDK implementation."""
    sdk_source_directory = REPOSITORY_ROOT / "src/orchestrator/runners/agents/claude_sdk"
    assert not any(sdk_source_directory.glob("*.py"))

    import orchestrator.runners as runners

    for exported_name in (
        "ClaudeSDKAgent",
        "ClaudeSdkAgent",
        "build_claude_sdk_prompt",
        "build_mcp_servers",
        "build_orchestrator_mcp_server",
    ):
        assert not hasattr(runners, exported_name)

    discover_agents()
    registered_types = get_registered_agent_runner_types()
    assert AgentRunnerType.RETIRED not in registered_types
    assert {
        AgentRunnerType.CLI_SUBPROCESS,
        AgentRunnerType.CODEX_SERVER,
        AgentRunnerType.OPENHANDS_LOCAL,
        AgentRunnerType.OPENHANDS_DOCKER,
    }.issubset(registered_types)

    claude_config = cli_config_for_command("claude")
    claude_model = next(field for field in claude_config if field.name == "model")
    assert claude_model.field_type == "string"
    assert claude_model.options is None
    assert claude_model.default is None
    assert ClaudeCliQuotaAgent.name == "claude"
    assert callable(ClaudeCliQuotaAgent().get_quota)

    options = asyncio.run(ToolDetector().detect_all())
    assert all(option.agent_runner_type is not AgentRunnerType.RETIRED for option in options)
    assert all(option.name != "Claude SDK" for option in options)

    assert "claude-agent-sdk" not in (REPOSITORY_ROOT / "pyproject.toml").read_text()
    assert "claude-agent-sdk" not in (REPOSITORY_ROOT / "uv.lock").read_text()
