"""FastAPI application for the orchestrator."""

from orchestrator.api.app import create_app
from orchestrator.api.deps import get_codex_models_fn, get_connection_manager, get_runner_executor
from orchestrator.api.metrics import PRICING, CostEstimate, estimate_cost
from orchestrator.api.mcp.clarification_tools import validate_clarification_question_payloads
from orchestrator.api.presenters import compute_run_totals_from_attempts, run_to_trace_response
from orchestrator.api.schemas.base import ApiModel
from orchestrator.api.schemas.envfiles import CopyBackRequest, RevertEnvFileRequest
from orchestrator.api.schemas.repos import AddRepoRequest
from orchestrator.api.schemas.review import FilePrune, PruneSelection, RevertFileRequest
from orchestrator.api.schemas.runs import (
    BackwardTransitionRequest,
    CreateRunRequest,
    EvidenceBundleSchema,
    InvalidEvidenceItem,
    RunEvidenceResponse,
    MergeBackRequest,
    RecoverRequest,
    RecoverResponse,
    ResumeRunRequest,
    RunTracePhase,
    RunTraceResponse,
    get_agent_runner_display_name,
    get_agent_runner_icon,
)
from orchestrator.api.schemas.tasks import (
    ActionLogSchema,
    CallbackInstructions,
    SetGradeRequest,
    TurnMetricsSchema,
    UpdateChecklistRequest,
)

__all__ = [
    "AddRepoRequest",
    "ApiModel",
    "ActionLogSchema",
    "BackwardTransitionRequest",
    "CallbackInstructions",
    "CopyBackRequest",
    "CostEstimate",
    "CreateRunRequest",
    "EvidenceBundleSchema",
    "InvalidEvidenceItem",
    "FilePrune",
    "MergeBackRequest",
    "PRICING",
    "PruneSelection",
    "RecoverRequest",
    "RecoverResponse",
    "ResumeRunRequest",
    "RunEvidenceResponse",
    "RunTracePhase",
    "RunTraceResponse",
    "RevertEnvFileRequest",
    "RevertFileRequest",
    "SetGradeRequest",
    "TurnMetricsSchema",
    "UpdateChecklistRequest",
    "create_app",
    "compute_run_totals_from_attempts",
    "estimate_cost",
    "get_codex_models_fn",
    "get_agent_runner_display_name",
    "get_agent_runner_icon",
    "get_connection_manager",
    "get_runner_executor",
    "run_to_trace_response",
    "validate_clarification_question_payloads",
]

# Symbols in this dict are lazy-loaded from routers.tasks to avoid circular
# imports at module-load time (routers.tasks imports from api.deps etc.).
_TASKS_ROUTER_SYMBOLS = {
    "router",
    "get_attempt_logs",
    "get_task",
    "_looks_like_ndjson_agent_stream",
    "_parse_action_log_from_raw",
}

_MCP_SYMBOLS = {"ORCHESTRATOR_TOOLS", "ToolHandler"}
_MCP_SERVER_SYMBOLS = {"OrchestratorMCPServer", "ALL_TOOLS"}

# Pure helpers from graph router + runs router, exposed here so tests don't
# reach into orchestrator.api.routers.* sub-packages directly.
_GRAPH_ROUTER_SYMBOLS = {
    "build_graph_projection_response",
    "build_node_detail_response",
    "build_node_detail_response_from_summary",
}
_RUNS_ROUTER_SYMBOLS = {"_graph_backed_run_ids_from_rows"}


def __getattr__(name: str) -> object:
    if name in _TASKS_ROUTER_SYMBOLS:
        import orchestrator.api.routers.tasks as _tasks  # noqa: PLC0415

        return getattr(_tasks, name)
    if name in _MCP_SYMBOLS:
        import orchestrator.api.mcp.tools as _mcp_tools  # noqa: PLC0415

        return getattr(_mcp_tools, name)
    if name in _MCP_SERVER_SYMBOLS:
        import orchestrator.api.mcp.server as _mcp_server  # noqa: PLC0415

        return getattr(_mcp_server, name)
    if name in _GRAPH_ROUTER_SYMBOLS:
        import orchestrator.api.routers.graph as _graph_router  # noqa: PLC0415

        return getattr(_graph_router, name)
    if name in _RUNS_ROUTER_SYMBOLS:
        import orchestrator.api.routers.runs as _runs_router  # noqa: PLC0415

        return getattr(_runs_router, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
