"""Backwards-compatible shim: re-exports orchestrator.runners.executor.

The canonical module is ``orchestrator.runners.executor``.  This shim exists
so that tools importing ``orchestrator.executor`` still work.

AgentRunnerExecutor._run_agent_loop() delegates to RunWorkflow (from
orchestrator.workflow.runtime) rather than running the loop directly.
"""

from orchestrator.runners.executor import (  # noqa: F401
    AgentRunnerExecutor,
    LoopAction,
    NoTaskReason,
    resolve_no_task_action,
    resolve_verifier_config,
)

# RunWorkflow is imported by executor._run_agent_loop at runtime.
# Listed here so static analysis tools can confirm the delegation.
from orchestrator.workflow.signals import RunWorkflow as RunWorkflow  # noqa: F401

__all__ = [
    "AgentRunnerExecutor",
    "LoopAction",
    "NoTaskReason",
    "RunWorkflow",
    "resolve_no_task_action",
    "resolve_verifier_config",
]
