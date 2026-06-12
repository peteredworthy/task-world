"""Effectful runtime adapters for the pure execution graph kernel."""

from orchestrator.graph_runtime.controller import GraphCommandResult, GraphController
from orchestrator.graph_runtime.dispatch import (
    GraphAgentFactory,
    GraphDispatchContext,
    GraphDispatchExecutor,
    StaticGraphAgentFactory,
    build_graph_runtime,
    reconcile_runtime,
)
from orchestrator.graph_runtime.errors import (
    CompromisedFileStateError,
    GraphRuntimeError,
    OutboxAppendError,
    StaleProjectionError,
)
from orchestrator.graph_runtime.file_state import (
    CleanupApplication,
    FileStateBoundaryResult,
    apply_cleanup_requested,
    capture_file_state_boundary,
    collect_worktree_status,
)
from orchestrator.graph_runtime.gatekeeper import (
    ClaudeGatekeeperClassifier,
    GatekeeperVerdict,
    ResidueClassifier,
    ResidueMetadata,
    metadata_from_file_state_record,
    policy_with_pattern_library,
)
from orchestrator.graph_runtime.outbox import OutboxDispatcher, OutboxItem, SideEffectExecutor
from orchestrator.graph_runtime.recovery import RecoveryReport, recover
from orchestrator.graph_runtime.seeding import SeedRunResult, seed_run
from orchestrator.graph_runtime.store import GraphEventStore

__all__ = [
    "GraphCommandResult",
    "GraphAgentFactory",
    "GraphController",
    "GraphDispatchContext",
    "GraphDispatchExecutor",
    "GraphEventStore",
    "GraphRuntimeError",
    "CompromisedFileStateError",
    "CleanupApplication",
    "FileStateBoundaryResult",
    "ClaudeGatekeeperClassifier",
    "GatekeeperVerdict",
    "OutboxAppendError",
    "OutboxDispatcher",
    "OutboxItem",
    "RecoveryReport",
    "ResidueClassifier",
    "ResidueMetadata",
    "SeedRunResult",
    "SideEffectExecutor",
    "StaleProjectionError",
    "StaticGraphAgentFactory",
    "build_graph_runtime",
    "apply_cleanup_requested",
    "capture_file_state_boundary",
    "collect_worktree_status",
    "metadata_from_file_state_record",
    "policy_with_pattern_library",
    "recover",
    "reconcile_runtime",
    "seed_run",
]
