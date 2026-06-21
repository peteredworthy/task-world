from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphDispatchContext, GraphDispatchExecutor
from orchestrator.graph_runtime.dispatch import _execute_check_command, _output_records_for_submit
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
    node_payload: dict[str, Any] | None = None,
    worktree_path: str = "/tmp/worktree",
    graph_events: list[EventEnvelope] | None = None,
) -> GraphDispatchContext:
    payload = {
        "node_id": node_id,
        "kind": node_kind,
        "role": node_role,
        "task_id": "task-1",
        "title": "Task 1",
        "task_context": "Do the work.",
    }
    payload.update(node_payload or {})
    return GraphDispatchContext(
        run_id="run-1",
        node_id=node_id,
        node_kind=node_kind,
        node_role=node_role,
        node_payload=payload,
        requirements=["R1: Pass"],
        worktree_path=worktree_path,
        lease_id="lease-1",
        lease_generation=1,
        execution_id="exec-1",
        base_snapshot_id="routine-snapshot",
        dispatch_event_id="dispatch-1",
        graph_events=graph_events or [],
    )


def _event(event_type: str, payload: dict[str, Any], position: int = -1) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
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
        self.submitted_checks: list[tuple[GraphDispatchContext, dict[str, Any]]] = []
        self.joins: list[GraphDispatchContext] = []
        self.final_gates: list[GraphDispatchContext] = []
        self.graph_patches: list[tuple[GraphDispatchContext, dict[str, Any]]] = []
        self.failures: list[str] = []
        self.graph_patch_feedback = graph_patch_feedback
        self.dispatch_context: GraphDispatchContext | None = None

    async def _build_dispatch_context(self, item: Any) -> GraphDispatchContext:
        if self.dispatch_context is None:
            return await super()._build_dispatch_context(item)
        return self.dispatch_context

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

    async def _submit_check_result(
        self,
        context: GraphDispatchContext,
        record: dict[str, Any],
    ) -> None:
        self.submitted_checks.append((context, record))

    async def _run_final_gate(self, context: GraphDispatchContext) -> None:
        self.final_gates.append(context)

    async def _run_join(self, context: GraphDispatchContext) -> None:
        self.joins.append(context)

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


def test_check_submit_does_not_fabricate_pass_record() -> None:
    context = _context(
        node_id="check-1",
        node_kind="check",
        node_payload={"command_definition": {"id": "unit-check", "cmd": "true"}},
    )

    assert _output_records_for_submit(context, []) == []


@pytest.mark.asyncio
async def test_execute_check_command_records_real_process_success(tmp_path: Path) -> None:
    context = _context(
        node_id="check-1",
        node_kind="check",
        worktree_path=str(tmp_path),
        node_payload={
            "task_region_id": "task-1",
            "candidate_id": "candidate-1",
            "attempt_number": 2,
            "command_definition": {
                "id": "pass-check",
                "argv": ["sh", "-c", "printf pass-output"],
                "timeout_seconds": 5,
            },
        },
    )

    record = await _execute_check_command(context)

    assert record["record_type"] == "check_result"
    assert record["record_kind"] == "output"
    assert record["producer_node_id"] == "check-1"
    assert record["port"] == "check_result"
    assert record["candidate_id"] == "candidate-1"
    assert record["task_region_id"] == "task-1"
    assert record["attempt_number"] == 2
    value = cast(dict[str, Any], record["value"])
    assert value["status"] == "passed"
    assert value["exit_code"] == 0
    assert value["stdout"] == "pass-output"
    assert value["stderr"] == ""
    assert value["command_id"] == "pass-check"
    assert value["command_text"] == "sh -c printf pass-output"
    assert value["base_snapshot_id"] == "routine-snapshot"
    assert value["worktree_path"] == str(tmp_path)
    assert isinstance(value["duration_ms"], int)


@pytest.mark.asyncio
async def test_execute_check_command_records_real_process_failure(tmp_path: Path) -> None:
    context = _context(
        node_id="check-1",
        node_kind="check",
        worktree_path=str(tmp_path),
        node_payload={
            "command_definition": {
                "id": "fail-check",
                "cmd": "printf fail-error >&2; exit 7",
                "timeout_seconds": 5,
            },
        },
    )

    record = await _execute_check_command(context)

    value = cast(dict[str, Any], record["value"])
    assert value["status"] == "failed"
    assert value["classification"] == "failed"
    assert value["exit_code"] == 7
    assert value["stderr"] == "fail-error"
    assert value["stdout"] == ""


@pytest.mark.asyncio
async def test_execute_check_command_resolves_bound_dynamic_feature_oracle(tmp_path: Path) -> None:
    context = _context(
        node_id="check-1",
        node_kind="check",
        worktree_path=str(tmp_path),
        node_payload={
            "command_binding": "dynamic_feature_hidden_oracle",
        },
        graph_events=[
            _event(
                "node_created",
                {
                    "node_id": "routine-snapshot",
                    "kind": "routine_snapshot",
                    "state": "completed",
                    "snapshot": {
                        "dynamic_feature": {
                            "hidden_oracle_command": "printf bound-oracle",
                        }
                    },
                },
                1,
            )
        ],
    )

    record = await _execute_check_command(context)

    value = cast(dict[str, Any], record["value"])
    assert value["status"] == "passed"
    assert value["command_id"] == "check-1"
    assert value["command_binding"] == "dynamic_feature_hidden_oracle"
    assert value["command"]["source"] == "dynamic_feature_hidden_oracle_binding"
    assert value["stdout"] == "bound-oracle"


@pytest.mark.asyncio
async def test_executor_runs_check_node_without_agent_submit(tmp_path: Path) -> None:
    context = _context(
        node_id="check-1",
        node_kind="check",
        worktree_path=str(tmp_path),
        node_payload={
            "command_definition": {
                "id": "runtime-check",
                "cmd": "printf runtime-ok",
                "timeout_seconds": 5,
            },
        },
    )
    executor = RecordingExecutor()

    await executor._run_check(context)

    assert executor.started == [context]
    assert executor.submitted == []
    assert executor.failures == []
    assert len(executor.submitted_checks) == 1
    check_context, record = executor.submitted_checks[0]
    assert check_context is context
    value = cast(dict[str, Any], record["value"])
    assert value["status"] == "passed"
    assert value["stdout"] == "runtime-ok"


@pytest.mark.asyncio
async def test_dispatch_routes_final_gate_without_agent() -> None:
    context = _context(node_id="gate-final", node_kind="final_gate")
    executor = RecordingExecutor()
    executor.dispatch_context = context

    await executor.dispatch(
        cast(
            Any,
            type(
                "Item",
                (),
                {
                    "kind": "agent_dispatch",
                    "run_id": context.run_id,
                    "event_id": context.dispatch_event_id,
                    "payload": {
                        "node_id": context.node_id,
                        "lease_id": context.lease_id,
                        "generation": context.lease_generation,
                        "execution_id": context.execution_id,
                        "base_snapshot_id": context.base_snapshot_id,
                    },
                },
            )(),
        )
    )
    await executor.wait_for_all()

    assert executor.final_gates == [context]
    assert executor.submitted == []
    assert executor.submitted_checks == []


@pytest.mark.asyncio
async def test_dispatch_routes_join_without_agent() -> None:
    context = _context(node_id="join-1", node_kind="join")
    executor = RecordingExecutor()
    executor.dispatch_context = context

    await executor.dispatch(
        cast(
            Any,
            type(
                "Item",
                (),
                {
                    "kind": "agent_dispatch",
                    "run_id": context.run_id,
                    "event_id": context.dispatch_event_id,
                    "payload": {
                        "node_id": context.node_id,
                        "lease_id": context.lease_id,
                        "generation": context.lease_generation,
                        "execution_id": context.execution_id,
                        "base_snapshot_id": context.base_snapshot_id,
                    },
                },
            )(),
        )
    )
    await executor.wait_for_all()

    assert executor.joins == [context]
    assert executor.submitted == []
    assert executor.submitted_checks == []


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
