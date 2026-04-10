"""FastAPI application for the orchestrator."""

from orchestrator.api.app import create_app
from orchestrator.api.deps import get_connection_manager
from orchestrator.api.metrics import PRICING, CostEstimate, estimate_cost
from orchestrator.api.schemas.base import ApiModel
from orchestrator.api.schemas.runs import (
    CreateRunRequest,
    RecoverResponse,
    get_agent_display_name,
    get_agent_icon,
)
from orchestrator.api.schemas.tasks import CallbackInstructions

__all__ = [
    "ApiModel",
    "CallbackInstructions",
    "CostEstimate",
    "CreateRunRequest",
    "PRICING",
    "RecoverResponse",
    "create_app",
    "estimate_cost",
    "get_agent_display_name",
    "get_agent_icon",
    "get_connection_manager",
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
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
