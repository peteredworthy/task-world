"""FastAPI application for the orchestrator."""

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
    "CreateRunRequest",
    "RecoverResponse",
    "get_agent_display_name",
    "get_agent_icon",
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


def __getattr__(name: str) -> object:
    if name in _TASKS_ROUTER_SYMBOLS:
        import orchestrator.api.routers.tasks as _tasks  # noqa: PLC0415

        return getattr(_tasks, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
