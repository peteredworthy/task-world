"""Workflow signal handling and runtime execution."""

from orchestrator.workflow.signals.signals import (
    DbSignalTransport,
    InMemorySignalTransport,
    PendingSignal,
    SignalQueue,
    SignalTransport,
    WorkflowSignal,
)
from orchestrator.workflow.signals.handlers import (
    build_registry,
    signal_handler,
)
from orchestrator.workflow.signals.runtime import (
    ExecutorCallbacks,
    LoopAction,
    NoTaskReason,
    RunWorkflow,
    resolve_no_task_action,
)

# Consumer must be imported AFTER signals.signals and handlers are loaded
# to avoid circular imports (handlers.py imports WorkflowSignal from this __init__)
from orchestrator.workflow.signals.consumer import SignalConsumer

__all__ = [
    "DbSignalTransport",
    "ExecutorCallbacks",
    "InMemorySignalTransport",
    "LoopAction",
    "NoTaskReason",
    "PendingSignal",
    "RunWorkflow",
    "SignalConsumer",
    "SignalQueue",
    "SignalTransport",
    "WorkflowSignal",
    "build_registry",
    "resolve_no_task_action",
    "signal_handler",
]
