"""Agent protocol definition."""

from typing import Protocol, runtime_checkable

from orchestrator.agents.types import (
    AgentInfo,
    AgentMetadataCallback,
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
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
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
    ) -> ExecutionResult: ...

    async def cancel(self) -> None: ...
