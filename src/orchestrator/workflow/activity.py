"""ActivityAdapter protocol and base implementation.

Defines the start/cancel boundary for agent runners via the ActivityAdapter
Protocol and provides BaseActivityAdapter with shared implementation.

The four concrete adapters (CLI, ClaudeSdk, CodexServer, OpenHands) live in
the ``orchestrator.workflow.adapters`` subpackage.
"""

from __future__ import annotations

import asyncio
import typing
from abc import ABC
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from orchestrator.runners.types import ExecutionContext

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class ActivityContext:
    """Context provided to an ActivityAdapter when starting an agent.

    Carries all information needed to launch an agent for a given task.
    Immutable (frozen) so adapters cannot accidentally mutate shared state.
    """

    run_id: str
    task_id: str
    worktree_path: str
    prompt: str
    requirements: list[str] = field(default_factory=list)
    api_base_url: str | None = None
    auth_token: str | None = None
    end_commit: str | None = None
    step_id: str | None = None
    available_tools: list[str] | None = None
    mcp_servers: list[Any] | None = None  # list[MCPServerConfig] | None


class ActivityAdapter(typing.Protocol):
    """Protocol defining the start/cancel boundary for agent runners.

    Any object implementing these two methods satisfies the protocol.
    Concrete implementations inherit from BaseActivityAdapter, but the
    protocol is the stable contract used for type annotations.
    """

    async def start(self, task_id: str, context: ActivityContext) -> None:
        """Start an agent activity for the given task.

        Implementations should launch the agent asynchronously (e.g. via an
        asyncio Task) and track it so that cancel() can stop it later.
        """
        ...

    async def cancel(self, task_id: str) -> None:
        """Cancel a running agent activity.

        Implementations should cancel the underlying asyncio Task and await
        its completion to ensure clean teardown.
        """
        ...


class BaseActivityAdapter(ABC):
    """Abstract base class for all four concrete activity adapters.

    Provides shared implementation of:
    - ``_agent``: the wrapped runner instance
    - ``_tasks``: dict tracking live asyncio Tasks by task_id
    - ``_build_execution_context()``: single mapping from ActivityContext
      to ExecutionContext (not duplicated per adapter)
    - ``start()`` / ``cancel()``: default implementations using the above

    Runner-specific differences are expressed as explicit overrides in the
    concrete subclass — not silent copies of this code.
    """

    def __init__(self, agent: Any) -> None:
        self._agent = agent
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    # ------------------------------------------------------------------
    # Shared mapping logic — single implementation, not duplicated
    # ------------------------------------------------------------------

    def _build_execution_context(self, context: ActivityContext) -> ExecutionContext:
        """Map an ActivityContext to an ExecutionContext for the runner."""
        return ExecutionContext(
            run_id=context.run_id,
            task_id=context.task_id,
            working_dir=context.worktree_path,
            prompt=context.prompt,
            requirements=list(context.requirements),
            api_base_url=context.api_base_url,
            auth_token=context.auth_token,
            end_commit=context.end_commit,
            step_id=context.step_id,
            available_tools=context.available_tools,
            mcp_servers=context.mcp_servers,
        )

    # ------------------------------------------------------------------
    # Default start / cancel implementations
    # ------------------------------------------------------------------

    async def start(self, task_id: str, context: ActivityContext) -> None:
        """Launch the agent as a background asyncio Task.

        Uses no-op callbacks — agents are expected to call back via the REST
        API using ``api_base_url`` from the context.  Concrete adapters may
        override this to wire real in-process callbacks (e.g. ClaudeSdk).
        """
        exec_ctx = self._build_execution_context(context)

        async def _noop_checklist_update(req_id: str, status: Any, note: str | None) -> None:
            pass

        async def _noop_submit() -> None:
            pass

        task = asyncio.create_task(
            self._agent.execute(exec_ctx, _noop_checklist_update, _noop_submit),
            name=f"activity-{task_id}",
        )
        self._tasks[task_id] = task

    async def cancel(self, task_id: str) -> None:
        """Cancel the agent task for task_id and await its teardown."""
        task = self._tasks.pop(task_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
