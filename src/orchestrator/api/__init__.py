"""FastAPI application for the orchestrator."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.app import create_app
from orchestrator.api.deps import (
    get_artifact_garbage_collector,
    get_artifact_store_resolver,
    get_codex_models_fn,
    get_connection_manager,
    get_runner_executor,
)
from orchestrator.api.metrics import PRICING, CostEstimate, estimate_cost
from orchestrator.api.mcp.clarification_tools import validate_clarification_question_payloads
from orchestrator.api.presenters import (
    build_run_evidence_digest_response,
    compute_cost_rollup,
    compute_run_totals_from_attempts,
    run_to_trace_response,
    token_usage_to_schema,
)
from orchestrator.api.schemas.cost_rollup import (
    CostRollupDimension,
    CostRollupFact,
    CostRollupFilters,
    CostRollupResponse,
    CostRollupRow,
)
from orchestrator.api.schemas.base import ApiModel
from orchestrator.api.schemas.envfiles import CopyBackRequest, RevertEnvFileRequest
from orchestrator.api.schemas.repos import AddRepoRequest
from orchestrator.api.schemas.review import FilePrune, PruneSelection, RevertFileRequest
from orchestrator.api.schemas.runs import (
    BackwardTransitionRequest,
    CreateRunRequest,
    EvidenceBundleSchema,
    InvalidEvidenceItem,
    RepresentativeNodeEvidence,
    RunEvidenceResponse,
    RunEvidenceDigestMetrics,
    RunEvidenceDigestResponse,
    RunEvidenceDigestRunSummary,
    RunEvidenceDigestScheduler,
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
    "append_requeue_audit_event",
    "BackwardTransitionRequest",
    "CallbackInstructions",
    "CopyBackRequest",
    "CostEstimate",
    "CostRollupDimension",
    "CostRollupFact",
    "CostRollupFilters",
    "CostRollupResponse",
    "CostRollupRow",
    "CreateRunRequest",
    "EvidenceBundleSchema",
    "InvalidEvidenceItem",
    "FilePrune",
    "MergeBackRequest",
    "PRICING",
    "RepresentativeNodeEvidence",
    "build_run_evidence_digest_response",
    "PruneSelection",
    "RecoverRequest",
    "RecoverResponse",
    "ResumeRunRequest",
    "RunEvidenceDigestMetrics",
    "RunEvidenceDigestResponse",
    "RunEvidenceDigestRunSummary",
    "RunEvidenceDigestScheduler",
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
    "compute_cost_rollup",
    "estimate_cost",
    "build_graph_patch_attempts_response",
    "build_graph_health_response",
    "build_expired_lease_rows",
    "build_final_invariant_blockers_response",
    "build_graph_regions_response",
    "build_graph_topology_response",
    "get_codex_models_fn",
    "get_artifact_store_resolver",
    "get_artifact_garbage_collector",
    "get_agent_runner_display_name",
    "get_agent_runner_icon",
    "get_connection_manager",
    "get_runner_executor",
    "load_cost_rollup_facts",
    "is_clarification_pause_reason",
    "run_to_trace_response",
    "token_usage_to_schema",
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
_MCP_GRAPH_DISPATCHER_SYMBOLS = {"GraphMcpDispatcher"}

# Pure helpers from graph router + runs router, exposed here so tests don't
# reach into orchestrator.api.routers.* sub-packages directly.
_GRAPH_ROUTER_SYMBOLS = {
    "build_graph_projection_response_from_snapshot",
    "build_final_invariant_blockers_response",
    "build_graph_patch_attempts_response",
    "build_graph_health_response",
    "build_graph_projection_response",
    "build_graph_regions_response",
    "build_graph_topology_response",
    "build_scheduler_view_response_from_snapshot",
    "build_node_detail_response",
    "build_node_detail_response_from_summary",
}
_RUNS_ROUTER_SYMBOLS = {"_graph_backed_run_ids_from_rows"}
_CLARIFICATION_ROUTER_SYMBOLS = {"is_clarification_pause_reason"}


def build_graph_patch_attempts_response(*args: Any, **kwargs: Any) -> Any:
    import orchestrator.api.routers.graph as _graph_router  # noqa: PLC0415

    return _graph_router.build_graph_patch_attempts_response(*args, **kwargs)


def build_graph_health_response(*args: Any, **kwargs: Any) -> Any:
    import orchestrator.api.routers.graph as _graph_router  # noqa: PLC0415

    return _graph_router.build_graph_health_response(*args, **kwargs)


def build_expired_lease_rows(*args: Any, **kwargs: Any) -> Any:
    import orchestrator.api.routers.graph as _graph_router  # noqa: PLC0415

    return _graph_router.build_expired_lease_rows(*args, **kwargs)


def build_final_invariant_blockers_response(*args: Any, **kwargs: Any) -> Any:
    import orchestrator.api.routers.graph as _graph_router  # noqa: PLC0415

    return _graph_router.build_final_invariant_blockers_response(*args, **kwargs)


def append_requeue_audit_event(*args: Any, **kwargs: Any) -> Any:
    import orchestrator.api.routers.graph as _graph_router  # noqa: PLC0415

    return _graph_router.append_requeue_audit_event(*args, **kwargs)


def build_graph_regions_response(*args: Any, **kwargs: Any) -> Any:
    import orchestrator.api.routers.graph as _graph_router  # noqa: PLC0415

    return _graph_router.build_graph_regions_response(*args, **kwargs)


def build_graph_topology_response(*args: Any, **kwargs: Any) -> Any:
    import orchestrator.api.routers.graph as _graph_router  # noqa: PLC0415

    return _graph_router.build_graph_topology_response(*args, **kwargs)


def is_clarification_pause_reason(*args: Any, **kwargs: Any) -> Any:
    import orchestrator.api.routers.clarifications as _clarifications_router  # noqa: PLC0415

    return _clarifications_router.is_clarification_pause_reason(*args, **kwargs)


async def load_cost_rollup_facts(
    session: AsyncSession,
    filters: CostRollupFilters,
    *,
    max_facts: int | None = None,
) -> list[CostRollupFact]:
    """Load canonical graph usage facts through the public API module."""
    from orchestrator.api.routers.cost_rollup import (  # noqa: PLC0415
        load_cost_rollup_facts as _load_cost_rollup_facts,
    )

    if max_facts is None:
        return await _load_cost_rollup_facts(session, filters)
    return await _load_cost_rollup_facts(session, filters, max_facts=max_facts)


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
    if name in _MCP_GRAPH_DISPATCHER_SYMBOLS:
        import orchestrator.api.mcp.graph_dispatcher as _mcp_graph_dispatcher  # noqa: PLC0415

        return getattr(_mcp_graph_dispatcher, name)
    if name in _GRAPH_ROUTER_SYMBOLS:
        import orchestrator.api.routers.graph as _graph_router  # noqa: PLC0415

        return getattr(_graph_router, name)
    if name in _RUNS_ROUTER_SYMBOLS:
        import orchestrator.api.routers.runs as _runs_router  # noqa: PLC0415

        return getattr(_runs_router, name)
    if name in _CLARIFICATION_ROUTER_SYMBOLS:
        import orchestrator.api.routers.clarifications as _clarifications_router  # noqa: PLC0415

        return getattr(_clarifications_router, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
