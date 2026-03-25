"""Agent integrations for the orchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from orchestrator.runners.agents import discover as discover_agents
from orchestrator.runners.agents.claude_cli.agent import CLIAgent, ClaudeCliQuotaAgent
from orchestrator.runners.agents.claude_sdk.agent import (
    ClaudeSDKAgent,
    build_mcp_servers,
    build_orchestrator_mcp_server,
    build_claude_sdk_prompt,
)
from orchestrator.runners.agents.mock.agent import MockAgent, MockBehavior
from orchestrator.runners.parsers.claude_parser import ClaudeStreamParser
from orchestrator.runners.parsers.codex_parser import CodexStreamParser

if TYPE_CHECKING:
    from orchestrator.runners.execution.attempt_store import AttemptStore
    from orchestrator.runners.execution.event_broadcaster import EventBroadcaster
    from orchestrator.runners.agents.user_managed.agent import UserManagedAgent
    from orchestrator.runners.parsers.openhands_parser import OpenHandsEventParser


def __getattr__(name: str):  # type: ignore[misc]
    if name == "UserManagedAgent":
        from orchestrator.runners.agents.user_managed.agent import UserManagedAgent

        return UserManagedAgent
    if name == "OpenHandsEventParser":
        from orchestrator.runners.parsers.openhands_parser import OpenHandsEventParser

        return OpenHandsEventParser
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AttemptStore",
    "CLIAgent",
    "ClaudeCliQuotaAgent",
    "ClaudeSDKAgent",
    "ClaudeStreamParser",
    "CodexStreamParser",
    "EventBroadcaster",
    "MockAgent",
    "MockBehavior",
    "OpenHandsEventParser",
    "UserManagedAgent",
    "build_mcp_servers",
    "build_orchestrator_mcp_server",
    "build_claude_sdk_prompt",
    "discover_agents",
]
