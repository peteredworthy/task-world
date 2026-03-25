"""Agent runner integrations for the orchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING

# Agent interface and types
from orchestrator.runners.interface import AgentRunner
from orchestrator.runners.types import AgentMetadataCallback, BroadcastCallback

# Agent discovery
from orchestrator.runners.agents import discover as discover_agents

# Concrete agent implementations
from orchestrator.runners.agents.claude_cli.agent import CLIAgent, ClaudeCliQuotaAgent
from orchestrator.runners.agents.claude_sdk.agent import (
    ClaudeSDKAgent,
    build_claude_sdk_prompt,
    build_mcp_servers,
    build_orchestrator_mcp_server,
)
from orchestrator.runners.agents.mock.agent import MockAgent, MockBehavior
from orchestrator.runners.parsers.claude_parser import ClaudeStreamParser
from orchestrator.runners.parsers.codex_parser import CodexStreamParser

# Scaffolding and Profiles
from orchestrator.runners.scaffolding import (
    ScaffoldingError,
    ScaffoldingSpec,
    copy_scaffolding,
    ensure_gitignore,
)
from orchestrator.runners.profiles import (
    AgentConfigModel,
    AgentNameConflictError,
    AgentNoDefaultPromptError,
    AgentNotFoundError,
    AgentSchema,
    AgentService,
    CreateAgentRequest,
    UpdateAgentRequest,
)
from orchestrator.runners.profiles.resolution import get_agent_system_prompt, resolve_agent_name
from orchestrator.runners.profiles.service import seed_default_agents

# Execution infrastructure
from orchestrator.runners.execution import AttemptStore, EventBroadcaster

# Detection sub-package
from orchestrator.runners.detection import (
    ToolDetector,
    coerce_llm_config,
    resolve_model_for_profile,
)

# Runtime sub-package
from orchestrator.runners.runtime import (
    ActionBudget,
    ActionBudgetConfig,
    AgentRunnerMonitor,
    FakeQuotaFetcher,
    HttpQuotaFetcher,
    NudgeAction,
    Nudger,
    NudgerConfig,
    QuotaFetcher,
    ReasoningDetectorConfig,
    ReasoningRepetitionDetector,
    RepetitionAction,
    RepetitionDetector,
    RepetitionDetectorConfig,
    TimeProvider,
)

if TYPE_CHECKING:
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
    # Core
    "AgentRunner",
    "AgentMetadataCallback",
    "BroadcastCallback",
    # Discovery
    "discover_agents",
    # Agent classes
    "CLIAgent",
    "ClaudeCliQuotaAgent",
    "ClaudeSDKAgent",
    "MockAgent",
    "MockBehavior",
    "OpenHandsEventParser",
    "UserManagedAgent",
    "build_claude_sdk_prompt",
    "build_mcp_servers",
    "build_orchestrator_mcp_server",
    # Parsers
    "ClaudeStreamParser",
    "CodexStreamParser",
    # Scaffolding
    "ScaffoldingError",
    "ScaffoldingSpec",
    "copy_scaffolding",
    "ensure_gitignore",
    # Profiles
    "AgentConfigModel",
    "AgentNameConflictError",
    "AgentNoDefaultPromptError",
    "AgentNotFoundError",
    "AgentSchema",
    "AgentService",
    "CreateAgentRequest",
    "UpdateAgentRequest",
    "get_agent_system_prompt",
    "resolve_agent_name",
    "seed_default_agents",
    # Execution
    "AttemptStore",
    "EventBroadcaster",
    # Detection
    "ToolDetector",
    "coerce_llm_config",
    "resolve_model_for_profile",
    # Runtime
    "ActionBudget",
    "ActionBudgetConfig",
    "AgentRunnerMonitor",
    "FakeQuotaFetcher",
    "HttpQuotaFetcher",
    "NudgeAction",
    "Nudger",
    "NudgerConfig",
    "QuotaFetcher",
    "ReasoningDetectorConfig",
    "ReasoningRepetitionDetector",
    "RepetitionAction",
    "RepetitionDetector",
    "RepetitionDetectorConfig",
    "TimeProvider",
]
