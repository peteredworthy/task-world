"""Agent protocol definition."""

from typing import Protocol, runtime_checkable

from orchestrator.runners.quota import QuotaFetcher
from orchestrator.runners.types import (
    AgentRunnerInfo,
    AgentMetadataCallback,
    AgentQuota,
    ChecklistUpdateCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)


@runtime_checkable
class AgentRunner(Protocol):
    """Protocol that all agent implementations must satisfy."""

    @property
    def info(self) -> AgentRunnerInfo: ...

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult: ...

    async def cancel(self) -> None: ...

    def get_quota(self, fetcher: QuotaFetcher | None = None) -> AgentQuota | None:
        return None
