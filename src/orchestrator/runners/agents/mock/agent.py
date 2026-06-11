"""Mock agent for testing."""

from dataclasses import dataclass, field
from typing import Any

from orchestrator.runners.errors import AgentCancelledError, AgentExecutionError
from orchestrator.runners.runtime.quota import QuotaFetcher
from orchestrator.runners.types import (
    AgentRunnerInfo,
    AgentMetadataCallback,
    AgentQuota,
    ChecklistUpdateCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from orchestrator.config.enums import AgentRunnerType, ChecklistStatus


def _empty_output_lines() -> list[str]:
    return []


@dataclass
class MockBehavior:
    """Configurable behavior for MockAgent.

    Attributes:
        complete_requirements: Requirement IDs to mark as DONE.
        fail_requirements: Requirement IDs to mark as BLOCKED.
        should_submit: Whether to call on_submit after checklist updates.
        should_fail: Whether execute() raises AgentExecutionError.
        tokens_read: Simulated tokens read.
        tokens_write: Simulated tokens written.
        tokens_cache: Simulated cache tokens.
        duration_ms: Simulated duration in milliseconds.
    """

    complete_requirements: list[str] = field(default_factory=lambda: [])
    fail_requirements: list[str] = field(default_factory=lambda: [])
    should_submit: bool = True
    should_fail: bool = False
    tokens_read: int = 100
    tokens_write: int = 50
    tokens_cache: int = 0
    duration_ms: int = 1000
    output_lines: list[str] = field(default_factory=_empty_output_lines)
    action_log: Any = None


class MockAgent:
    """Agent that simulates behavior without real I/O.

    Deterministic: same MockBehavior produces same results.
    """

    def __init__(self, behavior: MockBehavior | None = None) -> None:
        self._behavior = behavior or MockBehavior()
        self._cancelled = False

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
            name="mock",
            version="1.0.0",
        )

    def get_quota(self, fetcher: QuotaFetcher | None = None) -> AgentQuota | None:
        """Mock agents do not report quota."""
        return None

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        """Execute mock agent behavior."""
        if self._behavior.should_fail:
            raise AgentExecutionError("mock", "Simulated failure")

        # Mark requirements as DONE
        for req_id in self._behavior.complete_requirements:
            if self._cancelled:
                raise AgentCancelledError("mock")
            await on_checklist_update(req_id, ChecklistStatus.DONE, None)

        # Mark requirements as BLOCKED
        for req_id in self._behavior.fail_requirements:
            if self._cancelled:
                raise AgentCancelledError("mock")
            await on_checklist_update(req_id, ChecklistStatus.BLOCKED, "Blocked by mock agent")

        # Submit if configured
        if self._behavior.should_submit:
            if self._cancelled:
                raise AgentCancelledError("mock")
            await on_submit()

        return ExecutionResult(
            success=True,
            metrics=ExecutionMetrics(
                tokens_read=self._behavior.tokens_read,
                tokens_write=self._behavior.tokens_write,
                tokens_cache=self._behavior.tokens_cache,
                duration_ms=self._behavior.duration_ms,
            ),
            output_lines=list(self._behavior.output_lines),
            action_log=self._behavior.action_log,
        )

    async def cancel(self) -> None:
        """Cancel execution."""
        self._cancelled = True
