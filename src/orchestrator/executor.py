"""Re-export shim for the agent executor.

The signal consumer (SignalConsumer) is wired into the app lifespan in
``orchestrator.api.app.create_app``, which starts the consumer before
any signals can be enqueued.  The actual executor lives at
``orchestrator.runners.executor``.
"""

from orchestrator.runners.executor import AgentRunnerExecutor as AgentRunnerExecutor  # noqa: F401
from orchestrator.workflow import SignalConsumer as SignalConsumer  # noqa: F401
