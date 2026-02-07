"""User-managed agent.

A passive agent that waits for an external tool (e.g. a human using the UI,
or a third-party agent connecting via REST/MCP) to complete work and call
``submit_for_verification``.

The agent registers an ``asyncio.Event`` on ``WorkflowService`` and waits for
it to fire.  When the REST or MCP submit endpoint is called, the service sets
the event, and ``execute()`` returns successfully.

If the configured timeout expires before submit is called, execute() returns
with ``success=False``.
"""

from __future__ import annotations

import asyncio

from orchestrator.agents.errors import AgentCancelledError, AgentTimeoutError
from orchestrator.agents.types import (
    AgentInfo,
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from orchestrator.config.enums import AgentType
from orchestrator.workflow.service import WorkflowService


class UserManagedAgent:
    """Agent for externally-managed task execution.

    Does not run a subprocess or LLM.  Instead, it waits for an external
    actor to interact with the orchestrator via REST API or MCP tools
    and eventually call submit.

    The agent uses :meth:`WorkflowService.register_submit_event` to receive
    a notification when ``submit_for_verification`` is called for its task.
    """

    def __init__(
        self,
        service: WorkflowService,
        callback_channel: str = "mcp",
        timeout_minutes: int = 60,
        poll_interval: float = 1.0,
    ) -> None:
        self._service = service
        self._callback_channel = callback_channel
        self._timeout_minutes = timeout_minutes
        self._poll_interval = poll_interval
        self._cancelled = False

    @property
    def info(self) -> AgentInfo:
        return AgentInfo(
            agent_type=AgentType.USER_MANAGED,
            name="User Managed",
        )

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
    ) -> ExecutionResult:
        """Wait for an external submit notification, then return.

        Registers a submit event on the WorkflowService for the task and
        waits until either:
        - The submit event fires (success)
        - The timeout expires (failure)
        - The agent is cancelled
        """
        if self._cancelled:
            raise AgentCancelledError("user_managed")

        event = self._service.register_submit_event(context.task_id)
        try:
            await asyncio.wait_for(
                self._wait_for_event(event),
                timeout=self._timeout_minutes * 60,
            )
            return ExecutionResult(success=True, metrics=ExecutionMetrics())
        except TimeoutError:
            raise AgentTimeoutError(
                "user_managed",
                f"No submission received within {self._timeout_minutes} minutes",
            )
        except AgentCancelledError:
            raise
        finally:
            self._service.unregister_submit_event(context.task_id)

    async def _wait_for_event(self, event: asyncio.Event) -> None:
        """Wait for the event, checking cancellation periodically."""
        while not event.is_set():
            if self._cancelled:
                raise AgentCancelledError("user_managed")
            try:
                await asyncio.wait_for(event.wait(), timeout=self._poll_interval)
            except TimeoutError:
                continue

    async def cancel(self) -> None:
        """Cancel execution."""
        self._cancelled = True
