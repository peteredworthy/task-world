"""Agent protocol definition."""

from typing import Protocol, runtime_checkable

from orchestrator.agents.quota import QuotaFetcher
from orchestrator.agents.types import (
    AgentInfo,
    AgentMetadataCallback,
    AgentQuota,
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)


class EscalationCallback(Protocol):
    """Protocol for escalation callbacks.

    Called when an agent flags a requirement as unfulfillable so the run can be
    paused and a human can intervene.
    """

    async def __call__(self, requirement_id: str, reason: str) -> None: ...


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

    def get_quota(self, fetcher: QuotaFetcher | None = None) -> AgentQuota | None:
        return None
