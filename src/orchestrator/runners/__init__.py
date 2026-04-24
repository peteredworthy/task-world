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
from orchestrator.runners.agents.claude_cli.parser import (
    RATE_LIMIT_PATTERN,
    RATE_LIMIT_RESET_PATTERN,
    ClaudeStreamParser,
    parse_reset_time,
)
from orchestrator.runners.agents.codex.parser import CodexStreamParser

# OpenHands agent and helpers
# NOTE: OpenHandsAgent is loaded lazily via __getattr__ to avoid eager openhands.sdk import
from orchestrator.runners.agents.openhands.common import (
    CallbackRegistry,
    DEFAULT_OPENHANDS_TOOLS,
    GetRequirementsExecutor,
    OPENHANDS_TOOL_IMPORTS,
    SetGradeExecutor,
    SubmitExecutor,
    UpdateChecklistExecutor,
    ValidateRoutineExecutor,
    build_openhands_prompt,
    extract_metrics,
    register_builtin_tools,
)
# NOTE: DockerOpenHandsAgent is loaded lazily via __getattr__ to avoid eager openhands.sdk import

# Codex agent and helpers
from orchestrator.runners.agents.codex.agent import (
    CodexServerAgent,
    RealStdioTransport,
)
from orchestrator.runners.agents.codex.common import (
    CODEX_SERVER_TOOL_ALLOWLIST,
    JsonRpcTransport,
    build_codex_server_prompt,
    build_dynamic_tool_call_response,
    build_dynamic_tool_specs,
    build_execution_result,
    build_jsonrpc_request,
    enforce_tool_allowlist,
    extract_agent_message_delta,
    extract_dynamic_tool_call,
    extract_tool_call_from_notification,
    extract_turn_usage,
    fetch_codex_models,
    is_allowed_tool,
    normalize_codex_metrics,
    normalize_codex_output_lines,
)

# Scaffolding and Profiles
from orchestrator.runners.scaffolding import (
    RoutineFilesResult as RoutineFilesResult,
    ScaffoldingError,
    ScaffoldingSpec,
    copy_routine_files_git as copy_routine_files_git,
    copy_routine_files_local as copy_routine_files_local,
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

# Cost rates
from orchestrator.runners.costs import get_model_costs, load_cost_table

# Execution infrastructure
from orchestrator.runners.execution import AttemptStore, EventBroadcaster, PhaseHandler

# Detection
from orchestrator.runners.agent_detector import AGENT_CONFIG_FIELDS, ToolDetector
from orchestrator.runners.detection.config_utils import coerce_llm_config
from orchestrator.runners.detection.profile_resolution import resolve_model_for_profile

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
    from orchestrator.runners.agents.openhands.agent import OpenHandsAgent
    from orchestrator.runners.agents.openhands.docker_agent import DockerOpenHandsAgent
    from orchestrator.runners.agents.openhands.parser import OpenHandsEventParser


def __getattr__(name: str):  # type: ignore[misc]
    if name == "UserManagedAgent":
        from orchestrator.runners.agents.user_managed.agent import UserManagedAgent

        return UserManagedAgent
    if name == "OpenHandsAgent":
        from orchestrator.runners.agents.openhands.agent import OpenHandsAgent  # noqa: PLC0415

        return OpenHandsAgent
    if name == "DockerOpenHandsAgent":
        from orchestrator.runners.agents.openhands.docker_agent import DockerOpenHandsAgent  # noqa: PLC0415

        return DockerOpenHandsAgent
    if name == "OpenHandsEventParser":
        from orchestrator.runners.agents.openhands.parser import OpenHandsEventParser

        return OpenHandsEventParser
    # Private names from openhands.agent used in tests
    if name == "_SDK_AVAILABLE":
        try:
            import orchestrator.runners.agents.openhands.agent as _oh_agent  # noqa: PLC0415

            return getattr(_oh_agent, "_SDK_AVAILABLE")  # pyright: ignore[reportPrivateUsage]
        except ImportError:
            return False
    if name == "_build_openhands_mcp_config":
        import orchestrator.runners.agents.openhands.agent as _oh_agent  # noqa: PLC0415

        return getattr(_oh_agent, "_build_openhands_mcp_config")  # pyright: ignore[reportPrivateUsage]
    if name == "_obs_get_req":
        import orchestrator.runners.agents.openhands.agent as _oh_agent  # noqa: PLC0415

        return getattr(_oh_agent, "_obs_get_req")  # pyright: ignore[reportPrivateUsage]
    # Private names from openhands.docker_agent used in tests
    if name == "_DOCKER_WORKSPACE_AVAILABLE":
        try:
            import orchestrator.runners.agents.openhands.docker_agent as _oh_docker  # noqa: PLC0415

            return getattr(_oh_docker, "_DOCKER_WORKSPACE_AVAILABLE")  # pyright: ignore[reportPrivateUsage]
        except ImportError:
            return False
    if name == "_detect_platform":
        import orchestrator.runners.agents.openhands.docker_agent as _oh_docker  # noqa: PLC0415

        return getattr(_oh_docker, "_detect_platform")  # pyright: ignore[reportPrivateUsage]
    # Private names from codex.common used in tests
    if name == "_CODEX_FALLBACK_MODELS":
        import orchestrator.runners.agents.codex.common as _codex_common  # noqa: PLC0415

        return getattr(_codex_common, "_CODEX_FALLBACK_MODELS")  # pyright: ignore[reportPrivateUsage]
    if name == "_sp":
        import orchestrator.runners.agents.codex.common as _codex_common  # noqa: PLC0415

        return getattr(_codex_common, "_sp")  # pyright: ignore[reportPrivateUsage]
    if name == "_build_workspace_write_config_toml":
        import orchestrator.runners.agents.codex.agent as _codex_agent  # noqa: PLC0415

        return getattr(_codex_agent, "_build_workspace_write_config_toml")  # pyright: ignore[reportPrivateUsage]
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
    "CodexServerAgent",
    "DockerOpenHandsAgent",
    "MockAgent",
    "MockBehavior",
    "OpenHandsAgent",
    "OpenHandsEventParser",
    "RealStdioTransport",
    "UserManagedAgent",
    "build_claude_sdk_prompt",
    "build_mcp_servers",
    "build_orchestrator_mcp_server",
    # Parsers
    "ClaudeStreamParser",
    "CodexStreamParser",
    "RATE_LIMIT_PATTERN",
    "RATE_LIMIT_RESET_PATTERN",
    "parse_reset_time",
    # OpenHands common
    "CallbackRegistry",
    "DEFAULT_OPENHANDS_TOOLS",
    "GetRequirementsExecutor",
    "OPENHANDS_TOOL_IMPORTS",
    "SetGradeExecutor",
    "SubmitExecutor",
    "UpdateChecklistExecutor",
    "ValidateRoutineExecutor",
    "build_openhands_prompt",
    "extract_metrics",
    "register_builtin_tools",
    # Codex common
    "CODEX_SERVER_TOOL_ALLOWLIST",
    "JsonRpcTransport",
    "build_codex_server_prompt",
    "build_dynamic_tool_call_response",
    "build_dynamic_tool_specs",
    "build_execution_result",
    "build_jsonrpc_request",
    "enforce_tool_allowlist",
    "extract_agent_message_delta",
    "extract_dynamic_tool_call",
    "extract_tool_call_from_notification",
    "extract_turn_usage",
    "fetch_codex_models",
    "is_allowed_tool",
    "normalize_codex_metrics",
    "normalize_codex_output_lines",
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
    # Costs
    "get_model_costs",
    "load_cost_table",
    # Execution
    "AttemptStore",
    "EventBroadcaster",
    "PhaseHandler",
    # Detection
    "AGENT_CONFIG_FIELDS",
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
