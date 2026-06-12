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
    GraphRuntimeError,
    OutboxAppendError,
    StaleProjectionError,
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
    "OutboxAppendError",
    "OutboxDispatcher",
    "OutboxItem",
    "RecoveryReport",
    "SeedRunResult",
    "SideEffectExecutor",
    "StaleProjectionError",
    "StaticGraphAgentFactory",
    "build_graph_runtime",
    "recover",
    "reconcile_runtime",
    "seed_run",
]
