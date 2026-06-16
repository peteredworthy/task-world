from __future__ import annotations

from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType
from orchestrator.graph_runtime import GraphDispatchContext, GraphDispatchExecutor
from orchestrator.graph_runtime.dispatch import _output_records_for_submit
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


def _context(
    *,
    node_id: str = "worker-1",
    node_kind: str = "worker",
    node_role: str = "",
) -> GraphDispatchContext:
    return GraphDispatchContext(
        run_id="run-1",
        node_id=node_id,
        node_kind=node_kind,
        node_role=node_role,
        node_payload={
            "node_id": node_id,
            "kind": node_kind,
            "role": node_role,
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


class NoSubmitAgent(OutputAgent):
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
        return ExecutionResult(success=True)


class PatchThenSubmitAgent(OutputAgent):
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
        assert context.graph_patch_callback is not None
        await context.graph_patch_callback(
            {
                "patch_id": "patch-1",
                "base_graph_position": 3,
                "ops": [{"op": "create_node", "node": {"node_id": "worker-2"}}],
            }
        )
        await on_submit()
        self.submitted = True
        return ExecutionResult(success=True)


class RecordingExecutor(GraphDispatchExecutor):
    def __init__(
        self,
        on_agent_output: Any = None,
        graph_patch_feedback: str = "graph patch accepted",
    ) -> None:
        super().__init__(
            cast(async_sessionmaker[AsyncSession], object()),
            cast(Any, object()),
            cast(Any, object()),
            worktree_path="/tmp/worktree",
            on_agent_output=on_agent_output,
        )
        self.started: list[GraphDispatchContext] = []
        self.submitted: list[GraphDispatchContext] = []
        self.graph_patches: list[tuple[GraphDispatchContext, dict[str, Any]]] = []
        self.failures: list[str] = []
        self.graph_patch_feedback = graph_patch_feedback

    async def _acknowledge_start(self, context: GraphDispatchContext) -> None:
        self.started.append(context)

    async def _submit_callback(
        self,
        context: GraphDispatchContext,
        grades: list[tuple[str, str, str | None]],
    ) -> None:
        self.submitted.append(context)

    async def _submit_graph_patch_callback(
        self,
        context: GraphDispatchContext,
        patch_payload: dict[str, Any],
    ) -> str:
        self.graph_patches.append((context, patch_payload))
        return self.graph_patch_feedback

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


@pytest.mark.asyncio
async def test_executor_marks_agent_died_when_runner_exits_without_submit() -> None:
    context = _context()
    executor = RecordingExecutor()
    agent = NoSubmitAgent(["done but not submitted"])

    await executor._run_agent(context, agent)

    assert executor.started == [context]
    assert executor.submitted == []
    assert executor.failures == ["agent exited without submit"]


@pytest.mark.asyncio
async def test_planner_graph_patch_callback_allows_submit() -> None:
    context = _context(node_id="planner-1", node_kind="planner", node_role="planner")
    executor = RecordingExecutor()
    agent = PatchThenSubmitAgent([])

    await executor._run_agent(context, agent)

    assert executor.graph_patches == [
        (
            context,
            {
                "patch_id": "patch-1",
                "base_graph_position": 3,
                "ops": [{"op": "create_node", "node": {"node_id": "worker-2"}}],
            },
        )
    ]
    assert executor.submitted == [context]
    assert executor.failures == []


@pytest.mark.asyncio
async def test_planner_rejected_graph_patch_does_not_allow_submit() -> None:
    context = _context(node_id="planner-1", node_kind="planner", node_role="planner")
    executor = RecordingExecutor(graph_patch_feedback="graph patch patch-1 rejected: invalid")
    agent = PatchThenSubmitAgent([])

    await executor._run_agent(context, agent)

    assert executor.graph_patches == [
        (
            context,
            {
                "patch_id": "patch-1",
                "base_graph_position": 3,
                "ops": [{"op": "create_node", "node": {"node_id": "worker-2"}}],
            },
        )
    ]
    assert executor.submitted == []
    assert executor.failures == [
        "planner nodes must have an accepted submit_graph_patch before submit; "
        "use patch rejection feedback to submit a corrected patch"
    ]


@pytest.mark.asyncio
async def test_gap_planner_graph_patch_callback_allows_submit() -> None:
    context = _context(node_id="gap-planner-1", node_kind="planner", node_role="gap_planner")
    executor = RecordingExecutor()
    agent = PatchThenSubmitAgent([])

    await executor._run_agent(context, agent)

    assert executor.graph_patches == [
        (
            context,
            {
                "patch_id": "patch-1",
                "base_graph_position": 3,
                "ops": [{"op": "create_node", "node": {"node_id": "worker-2"}}],
            },
        )
    ]
    assert executor.submitted == [context]
    assert executor.failures == []
    assert context.node_payload["_accepted_graph_patch_had_ops"] is True


def test_gap_planner_submit_emits_classified_gap_after_accepted_nonempty_patch() -> None:
    context = _context(node_id="gap-planner-1", node_kind="planner", node_role="gap_planner")
    context.node_payload["_accepted_graph_patch_had_ops"] = True

    records = _output_records_for_submit(context, [])

    assert records == [
        {
            "record_id": "gap-plan-exec-1",
            "record_kind": "output",
            "producer_node_id": "gap-planner-1",
            "port": "gap_plan",
            "schema": "GapClassification",
            "value": {
                "milestone_kind": "gap_analysis",
                "classification": "corrective_work_required",
                "source": "accepted_gap_planner_patch",
                "task_region_id": "gap-planner-1",
                "attempt_number": 0,
            },
        },
        {
            "record_id": "gap-classification-exec-1",
            "record_kind": "output",
            "producer_node_id": "gap-planner-1",
            "port": "gap_classification",
            "schema": "GapClassification",
            "value": {
                "milestone_kind": "gap_analysis",
                "classification": "corrective_work_required",
                "source": "accepted_gap_planner_patch",
                "task_region_id": "gap-planner-1",
                "attempt_number": 0,
            },
        },
        {
            "record_id": "classified-gap-exec-1",
            "record_kind": "output",
            "producer_node_id": "gap-planner-1",
            "port": "classified_gap",
            "schema": "GapClassification",
            "value": {
                "milestone_kind": "gap_analysis",
                "classification": "corrective_work_required",
                "source": "accepted_gap_planner_patch",
                "task_region_id": "gap-planner-1",
                "attempt_number": 0,
            },
        },
    ]


@pytest.mark.asyncio
async def test_generic_planner_submit_without_patch_is_rejected() -> None:
    context = _context(node_id="planner-1", node_kind="planner", node_role="planner")
    executor = RecordingExecutor()
    agent = OutputAgent([])

    await executor._run_agent(context, agent)

    assert executor.submitted == []
    assert executor.graph_patches == []
    assert executor.failures == [
        "planner nodes must call submit_graph_patch before submit; "
        "submit an accepted graph patch first"
    ]


@pytest.mark.asyncio
async def test_gap_planner_submit_without_patch_is_rejected() -> None:
    context = _context(node_id="gap-planner-1", node_kind="planner", node_role="gap_planner")
    executor = RecordingExecutor()
    agent = OutputAgent([])

    await executor._run_agent(context, agent)

    assert executor.submitted == []
    assert executor.graph_patches == []
    assert executor.failures == [
        "planner nodes must call submit_graph_patch before submit; "
        "submit an accepted graph patch first"
    ]


@pytest.mark.asyncio
async def test_special_planner_roles_can_submit_without_graph_patch() -> None:
    for role in ("fan_out_reader", "fan_out_join"):
        context = _context(node_id=f"{role}-1", node_kind="planner", node_role=role)
        executor = RecordingExecutor()
        agent = OutputAgent([])

        await executor._run_agent(context, agent)

        assert executor.submitted == [context]
        assert executor.graph_patches == []
        assert executor.failures == []
