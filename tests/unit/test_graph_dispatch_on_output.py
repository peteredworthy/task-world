from __future__ import annotations

from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType
from orchestrator.graph_runtime import GraphDispatchContext, GraphDispatchExecutor
from orchestrator.runners.types import (
    AgentMetadataCallback,
    AgentRunnerInfo,
    ChecklistUpdateCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)


def _context() -> GraphDispatchContext:
    return GraphDispatchContext(
        run_id="run-1",
        node_id="worker-1",
        node_kind="worker",
        node_payload={
            "node_id": "worker-1",
            "kind": "worker",
            "task_id": "task-1",
            "title": "Task 1",
            "task_context": "Do the work.",
        },
        requirements=["R1: Pass"],
        worktree_path="/tmp/worktree",
        lease_id="lease-1",
        lease_generation=1,
        execution_id="exec-1",
        base_snapshot_id="routine-snapshot",
        dispatch_event_id="dispatch-1",
    )


class OutputAgent:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.submitted = False

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="output")

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
        if on_output is not None:
            await on_output(self._lines)
        await on_submit()
        self.submitted = True
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class RecordingExecutor(GraphDispatchExecutor):
    def __init__(self, on_agent_output: Any = None) -> None:
        super().__init__(
            cast(async_sessionmaker[AsyncSession], object()),
            cast(Any, object()),
            cast(Any, object()),
            worktree_path="/tmp/worktree",
            on_agent_output=on_agent_output,
        )
        self.started: list[GraphDispatchContext] = []
        self.submitted: list[GraphDispatchContext] = []
        self.failures: list[str] = []

    async def _acknowledge_start(self, context: GraphDispatchContext) -> None:
        self.started.append(context)

    async def _submit_callback(
        self,
        context: GraphDispatchContext,
        grades: list[tuple[str, str, str | None]],
    ) -> None:
        self.submitted.append(context)

    async def _agent_died(self, context: GraphDispatchContext, reason: str) -> None:
        self.failures.append(reason)


class RecordingOutputSink:
    def __init__(self) -> None:
        self.calls: list[tuple[GraphDispatchContext, list[str]]] = []

    async def __call__(self, context: GraphDispatchContext, lines: list[str]) -> None:
        self.calls.append((context, lines))


@pytest.mark.asyncio
async def test_executor_forwards_agent_output_to_callback() -> None:
    context = _context()
    sink = RecordingOutputSink()
    executor = RecordingExecutor(on_agent_output=sink)
    agent = OutputAgent(["line"])

    await executor._run_agent(context, agent)

    assert sink.calls == [(context, ["line"])]
    assert executor.started == [context]
    assert executor.submitted == [context]
    assert executor.failures == []
    assert agent.submitted is True


@pytest.mark.asyncio
async def test_executor_runs_without_output_callback() -> None:
    context = _context()
    executor = RecordingExecutor()
    agent = OutputAgent(["line"])

    await executor._run_agent(context, agent)

    assert executor.started == [context]
    assert executor.submitted == [context]
    assert executor.failures == []
    assert agent.submitted is True
