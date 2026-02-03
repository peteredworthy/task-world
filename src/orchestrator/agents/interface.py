"""Agent protocol definition."""

from typing import Protocol, runtime_checkable

from orchestrator.agents.types import (
    AgentInfo,
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionResult,
    SubmitCallback,
)


@runtime_checkable
class Agent(Protocol):
    """Protocol that all agent implementations must satisfy."""

    @property
    def info(self) -> AgentInfo: ...

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
    ) -> ExecutionResult: ...

    async def cancel(self) -> None: ...
