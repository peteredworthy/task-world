"""Agent runner integrations for the orchestrator."""

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

# Detection sub-package
from orchestrator.runners.detection import (
    AGENT_CONFIG_FIELDS,
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
    # Detection
    "AGENT_CONFIG_FIELDS",
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
