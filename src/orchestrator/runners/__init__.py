"""Agent runner integrations for the orchestrator."""

# Agent interface and types
from orchestrator.runners.interface import AgentRunner
from orchestrator.runners.types import AgentMetadataCallback, BroadcastCallback

# S-06: Scaffolding and Profiles re-exports (preserved)
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
from orchestrator.runners.parsers.claude_parser import ClaudeStreamParser
from orchestrator.runners.parsers.codex_parser import CodexStreamParser
from orchestrator.runners.agents.claude_sdk.agent import ClaudeSDKAgent
from orchestrator.runners.agents.claude_cli.agent import ClaudeCliQuotaAgent
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

__all__ = [
    # Core
    "AgentRunner",
    "AgentMetadataCallback",
    "BroadcastCallback",
    # S-06: Scaffolding
    "copy_scaffolding",
    "ensure_gitignore",
    "ScaffoldingError",
    "ScaffoldingSpec",
    # S-06: Profiles
    "AgentConfigModel",
    "AgentSchema",
    "CreateAgentRequest",
    "UpdateAgentRequest",
    "AgentService",
    "AgentNotFoundError",
    "AgentNameConflictError",
    "AgentNoDefaultPromptError",
    "get_agent_system_prompt",
    "resolve_agent_name",
    "seed_default_agents",
    # Parsers
    "ClaudeStreamParser",
    "CodexStreamParser",
    # Agent classes
    "ClaudeCliQuotaAgent",
    "ClaudeSDKAgent",
    # Execution
    "AttemptStore",
    "EventBroadcaster",
    # Detection
    "ToolDetector",
    "coerce_llm_config",
    "resolve_model_for_profile",
    # Runtime
    "AgentRunnerMonitor",
    "NudgeAction",
    "Nudger",
    "NudgerConfig",
    "TimeProvider",
    "FakeQuotaFetcher",
    "HttpQuotaFetcher",
    "QuotaFetcher",
    "ActionBudget",
    "ActionBudgetConfig",
    "ReasoningDetectorConfig",
    "ReasoningRepetitionDetector",
    "RepetitionAction",
    "RepetitionDetector",
    "RepetitionDetectorConfig",
]
