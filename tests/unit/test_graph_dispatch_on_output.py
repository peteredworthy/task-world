from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config.enums import AgentRunnerType
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    GraphProjection,
    GraphCommandContext,
    initial_projection,
    reduce_event,
)
from orchestrator.git import snapshot
from orchestrator.graph_runtime import GraphDispatchContext, GraphDispatchExecutor
from orchestrator.graph_runtime.dispatch import (
    DEFAULT_GAP_PLANNER_RUNTIME_DEATH_MAX_ATTEMPTS,
    _callback_conflict_reason,
    _execute_check_command,
    _output_records_for_submit,
    _planner_evidence,
    _requirements_for_node,
    _runtime_death_max_attempts,
    _full_raw_patch_validation_diagnostics,
)
from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry
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
from orchestrator.runners.graph_tool_routing import normalize_patch_payload
from tests.unit.graph_test_utils import canonical_event_payload


def _context(
    *,
    node_id: str = "worker-1",
    node_kind: str = "worker",
    node_role: str = "",
    node_payload: dict[str, Any] | None = None,
    worktree_path: str = "/tmp/worktree",
    graph_events: list[EventEnvelope] | None = None,
    graph_projection: GraphProjection | None = None,
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
        graph_projection=graph_projection or _project(graph_events or []),
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
        payload=canonical_event_payload(event_type, payload),
    )


def _project(events: list[EventEnvelope]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def test_bound_record_hydration_policy_shapes_prompt_records() -> None:
    events = [
        _event(
            "edge_created",
            {
                "edge_id": "edge-structured",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "planner-1",
                "to_port": "structured",
                "prompt_hydration_policy": "structured_json",
            },
            1,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-inline",
                "from_node_id": "worker-2",
                "from_port": "candidate",
                "to_node_id": "planner-1",
                "to_port": "inline",
                "prompt_hydration_policy": "inline_summary",
            },
            2,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-artifact",
                "from_node_id": "context-1",
                "from_port": "artifact",
                "to_node_id": "planner-1",
                "to_port": "artifact",
                "prompt_hydration_policy": "artifact_reference",
            },
            3,
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-tool",
                "from_node_id": "worker-3",
                "from_port": "candidate",
                "to_node_id": "planner-1",
                "to_port": "tool",
                "prompt_hydration_policy": "tool_only",
            },
            4,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-structured",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "full candidate"},
            },
            5,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-inline",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-2",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "short candidate"},
            },
            6,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "artifact-1",
                "record_kind": "graph_record",
                "record_type": "artifact_reference",
                "producer_node_id": "context-1",
                "port": "artifact",
                "schema": "ContextArtifact",
                "value": {
                    "artifact_id": "spec",
                    "artifact_type": "context_source",
                    "uri": "docs/spec.md",
                    "summary": "Feature spec",
                },
            },
            7,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-tool",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-3",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "tool only candidate"},
            },
            8,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-structured",
                "to_node_id": "planner-1",
                "to_port": "structured",
                "record_ids": ["candidate-structured"],
            },
            9,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-inline",
                "to_node_id": "planner-1",
                "to_port": "inline",
                "record_ids": ["candidate-inline"],
            },
            10,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-artifact",
                "to_node_id": "planner-1",
                "to_port": "artifact",
                "record_ids": ["artifact-1"],
            },
            11,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-tool",
                "to_node_id": "planner-1",
                "to_port": "tool",
                "record_ids": ["candidate-tool"],
            },
            12,
        ),
    ]
    context = _context(
        node_id="planner-1",
        node_kind="planner",
        node_role="planner",
        graph_events=events,
    )

    bound_records = _planner_evidence(
        context,
        context.graph_projection,
        context.graph_events,
    )["bound_records"]

    structured = bound_records["structured"][0]
    assert structured["hydration_policy"] == "structured_json"
    assert structured["record_payload"]["value"] == {"summary": "full candidate"}

    inline = bound_records["inline"][0]
    assert inline["hydration_policy"] == "inline_summary"
    assert inline["record_summary"] == {
        "record_id": "candidate-inline",
        "record_type": "candidate",
        "schema": "ImplementationCandidate",
        "candidate_id": "candidate-inline",
        "summary": "short candidate",
    }
    assert "record_payload" not in inline

    artifact = bound_records["artifact"][0]
    assert artifact["hydration_policy"] == "artifact_reference"
    assert artifact["record_reference"] == {
        "record_id": "artifact-1",
        "record_type": "artifact_reference",
        "schema": "ContextArtifact",
        "producer_node_id": "context-1",
        "producer_port": "artifact",
        "artifact_id": "spec",
        "artifact_type": "context_source",
        "uri": "docs/spec.md",
        "summary": "Feature spec",
    }
    assert "record_payload" not in artifact

    tool_only = bound_records["tool"][0]
    assert tool_only == {
        "record_id": "candidate-tool",
        "record_kind": "output",
        "hydration_policy": "tool_only",
        "status": "accepted",
        "omitted_from_prompt": True,
    }


def test_requirements_for_node_prefers_typed_requirement_record() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "requirement-1",
                "kind": "requirement",
                "state": "completed",
                "requirement": {"id": "legacy", "desc": "legacy text"},
                "requirement_record": {
                    "record_id": "requirement-1",
                    "record_kind": "graph_record",
                    "record_type": "requirement_record",
                    "producer_node_id": "requirement-1",
                    "port": "requirement",
                    "schema": "RequirementRecord",
                    "value": {
                        "id": "R-01",
                        "text": "Typed requirement text.",
                        "desc": "Typed requirement text.",
                        "priority": "critical",
                    },
                },
            },
            1,
        ),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"}, 2),
        _event(
            "edge_created",
            {
                "edge_id": "edge-requirement",
                "from_node_id": "requirement-1",
                "from_port": "requirement",
                "to_node_id": "worker-1",
                "to_port": "requirement_requirement-1",
                "required": True,
            },
            3,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-requirement",
                "to_node_id": "worker-1",
                "to_port": "requirement_requirement-1",
                "record_ids": ["requirement-1"],
                "bound_at_position": 4,
            },
            4,
        ),
    ]

    assert _requirements_for_node(events, "worker-1") == ["R-01: Typed requirement text."]


def test_requirements_for_node_falls_back_to_dynamic_feature_acceptance() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "state": "completed",
                "snapshot": {
                    "dynamic_feature": {
                        "feature_spec_content": "Write the smoke artifact.",
                        "acceptance_command": "test -f smoke.txt",
                    }
                },
            },
            1,
        ),
        _event(
            "node_created",
            {"node_id": "verifier-1", "kind": "verifier", "state": "planned"},
            2,
        ),
    ]

    assert _requirements_for_node(events, "verifier-1") == [
        "dynamic_feature_acceptance: Write the smoke artifact. "
        "Acceptance command: test -f smoke.txt"
    ]


def test_bound_requirements_override_dynamic_feature_acceptance() -> None:
    events = [
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "state": "completed",
                "snapshot": {
                    "dynamic_feature": {
                        "feature_spec_content": "Fallback should not appear.",
                        "acceptance_command": "test -f fallback.txt",
                    }
                },
            },
            1,
        ),
        _event(
            "node_created",
            {
                "node_id": "requirement-1",
                "kind": "requirement",
                "state": "completed",
                "requirement": {"id": "R-01", "desc": "Explicit requirement."},
            },
            2,
        ),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "planned"}, 3),
        _event(
            "edge_created",
            {
                "edge_id": "edge-requirement",
                "from_node_id": "requirement-1",
                "from_port": "requirement",
                "to_node_id": "worker-1",
                "to_port": "requirement_requirement-1",
                "required": True,
            },
            4,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-requirement",
                "to_node_id": "worker-1",
                "to_port": "requirement_requirement-1",
                "record_ids": ["requirement-1"],
                "bound_at_position": 5,
            },
            5,
        ),
    ]

    assert _requirements_for_node(events, "worker-1") == ["R-01: Explicit requirement."]


def test_callback_conflict_reason_reports_submit_rejection() -> None:
    events = [
        _event(
            "callback_rejected_conflict",
            {"reason": "verification record at index 0 missing grades"},
            1,
        )
    ]

    assert _callback_conflict_reason(events) == "verification record at index 0 missing grades"


def test_callback_conflict_reason_reports_stale_rejection() -> None:
    events = [
        _event("callback_rejected_stale", {"reason": "lease revoked"}, 1),
    ]

    assert _callback_conflict_reason(events) == "lease revoked"


def test_callback_conflict_reason_raises_on_duplicate_of_conflict_rejection() -> None:
    events = [
        _event(
            "callback_duplicate_returned",
            {
                "reason": "duplicate idempotency key",
                "prior_result": {
                    "outcome": "callback_rejected_conflict",
                    "payload": {"reason": "node not running: completed"},
                },
            },
            1,
        )
    ]

    assert _callback_conflict_reason(events) == "node not running: completed"


def test_callback_conflict_reason_raises_on_duplicate_of_stale_rejection() -> None:
    events = [
        _event(
            "callback_duplicate_returned",
            {
                "reason": "duplicate idempotency key",
                "prior_result": {
                    "outcome": "callback_rejected_stale",
                    "payload": {"reason": "lease revoked"},
                },
            },
            1,
        )
    ]

    assert _callback_conflict_reason(events) == "lease revoked"


def test_callback_conflict_reason_ignores_duplicate_of_accepted_callback() -> None:
    events = [
        _event(
            "callback_duplicate_returned",
            {
                "reason": "duplicate idempotency key",
                "prior_result": {
                    "outcome": "callback_accepted",
                    "payload": {"node_id": "worker-1"},
                },
            },
            1,
        )
    ]

    assert _callback_conflict_reason(events) is None


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


class BlockingSubmitAgent(OutputAgent):
    def __init__(self, started: list[str], release: asyncio.Event) -> None:
        super().__init__([])
        self._started = started
        self._release = release

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
        self._started.append(context.node_id)
        await self._release.wait()
        await on_submit()
        return ExecutionResult(success=True)


class RecordingSubmitAgent(OutputAgent):
    def __init__(self, started: list[str]) -> None:
        super().__init__([])
        self._started = started

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
        self._started.append(context.node_id)
        await on_submit()
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


class NoOpPatchThenSubmitAgent(OutputAgent):
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
                "ops": [],
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
            artifact_store=FilesystemArtifactStore(Path("/tmp/test-graph-artifacts")),
            on_agent_output=on_agent_output,
        )
        self.started: list[GraphDispatchContext] = []
        self.submitted: list[GraphDispatchContext] = []
        self.submitted_checks: list[tuple[GraphDispatchContext, dict[str, Any]]] = []
        self.joins: list[GraphDispatchContext] = []
        self.final_gates: list[GraphDispatchContext] = []
        self.graph_patches: list[tuple[GraphDispatchContext, dict[str, Any]]] = []
        self.heartbeats: list[GraphDispatchContext] = []
        self.failures: list[str] = []
        self.graph_patch_feedback = graph_patch_feedback
        self.dispatch_context: GraphDispatchContext | None = None

    async def _build_dispatch_context(self, item: Any) -> GraphDispatchContext:
        if self.dispatch_context is None:
            return await super()._build_dispatch_context(item)
        return self.dispatch_context

    async def _acknowledge_start(self, context: GraphDispatchContext) -> None:
        self.started.append(context)

    async def _record_start_heartbeat(self, context: GraphDispatchContext) -> None:
        self.heartbeats.append(context)

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


class GraphMcpUrlCapturingAgent(OutputAgent):
    """Fake agent that asserts the per-execution graph MCP route is live
    during execute() and records the token for the caller to check
    afterward."""

    def __init__(self, registry: GraphMcpExecutionRegistry, captured_tokens: list[str]) -> None:
        super().__init__([])
        self._registry = registry
        self._captured_tokens = captured_tokens

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
        assert context.graph_mcp_url is not None
        assert context.graph_mcp_url.startswith("http://test-base:9000/mcp-graph/")
        token = context.graph_mcp_url.removeprefix("http://test-base:9000/mcp-graph/").removesuffix(
            "/sse"
        )
        self._captured_tokens.append(token)
        assert self._registry.get(token) is not None, "route must be mounted during execute()"
        # node_role="planner" requires an accepted graph patch before submit is
        # allowed (see _requires_graph_patch_before_submit) — go through the
        # same graph_patch_callback path a real claude_cli planner would use.
        if context.graph_patch_callback is not None:
            await context.graph_patch_callback(
                {"patch_id": "patch-1", "base_graph_position": 3, "ops": []}
            )
        await on_submit()
        self.submitted = True
        return ExecutionResult(success=True)


class RecordingExecutorWithGraphMcp(RecordingExecutor):
    def __init__(self, registry: GraphMcpExecutionRegistry) -> None:
        super().__init__()
        self._graph_mcp_registry = registry
        self._base_url = "http://test-base:9000"


@pytest.mark.asyncio
async def test_graph_mcp_route_mounted_during_execute_and_unmounted_after() -> None:
    registry = GraphMcpExecutionRegistry()
    context = _context(node_id="planner-1", node_kind="planner", node_role="planner")
    captured_tokens: list[str] = []
    agent = GraphMcpUrlCapturingAgent(registry, captured_tokens)
    executor = RecordingExecutorWithGraphMcp(registry)

    await executor._run_agent(context, agent)

    assert executor.submitted == [context]
    assert executor.failures == []
    assert len(captured_tokens) == 1
    assert registry.get(captured_tokens[0]) is None, "route must be unmounted after execute()"


@pytest.mark.asyncio
async def test_verifier_node_gets_graph_mcp_route_too() -> None:
    registry = GraphMcpExecutionRegistry()
    context = _context(node_id="verifier-1", node_kind="verifier", node_role="verifier")
    captured_tokens: list[str] = []
    agent = GraphMcpUrlCapturingAgent(registry, captured_tokens)
    executor = RecordingExecutorWithGraphMcp(registry)

    await executor._run_agent(context, agent)

    assert executor.submitted == [context]
    assert len(captured_tokens) == 1


class GraphMcpRaisingAgent(OutputAgent):
    """Fake agent that raises during execute() after confirming the
    per-execution graph MCP route is live, to prove the route is unmounted
    even when runner.execute() fails."""

    def __init__(self, registry: GraphMcpExecutionRegistry, captured_tokens: list[str]) -> None:
        super().__init__([])
        self._registry = registry
        self._captured_tokens = captured_tokens

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
        assert context.graph_mcp_url is not None
        token = context.graph_mcp_url.removeprefix("http://test-base:9000/mcp-graph/").removesuffix(
            "/sse"
        )
        self._captured_tokens.append(token)
        assert self._registry.get(token) is not None, "route must be mounted during execute()"
        raise RuntimeError("simulated runner crash")


@pytest.mark.asyncio
async def test_graph_mcp_route_unmounted_when_runner_execute_raises() -> None:
    registry = GraphMcpExecutionRegistry()
    context = _context(node_id="verifier-1", node_kind="verifier", node_role="verifier")
    captured_tokens: list[str] = []
    agent = GraphMcpRaisingAgent(registry, captured_tokens)
    executor = RecordingExecutorWithGraphMcp(registry)

    await executor._run_agent(context, agent)

    assert len(captured_tokens) == 1
    assert registry.get(captured_tokens[0]) is None, "route must be unmounted after a crash"
    assert executor.failures == ["simulated runner crash"]


@pytest.mark.asyncio
async def test_no_registry_configured_means_no_graph_mcp_url() -> None:
    """Every existing call site that doesn't pass graph_mcp_registry (the
    default in Task 6 Step 5) gets exactly the pre-Task-6 behavior."""
    context = _context(node_id="planner-1", node_kind="planner", node_role="planner")
    executor = RecordingExecutor()  # no graph_mcp_registry — the plain existing class

    execution_context = executor._execution_context(context, graph_patch_callback=None)

    assert execution_context.graph_mcp_url is None


class RecordingOutputSink:
    def __init__(self) -> None:
        self.calls: list[tuple[GraphDispatchContext, list[str]]] = []

    async def __call__(self, context: GraphDispatchContext, lines: list[str]) -> None:
        self.calls.append((context, lines))


class RaisingUsageObserver:
    async def __call__(self, context: GraphDispatchContext, result: Any) -> None:
        del context
        del result
        raise RuntimeError("usage observer unavailable")


@pytest.mark.asyncio
async def test_wait_for_all_timeout_returns_without_cancelling_active_task() -> None:
    release = asyncio.Event()

    async def _blocked() -> None:
        await release.wait()

    task = asyncio.create_task(_blocked())
    running = {"exec-active": task}
    executor = GraphDispatchExecutor(
        cast(async_sessionmaker[AsyncSession], object()),
        cast(Any, object()),
        cast(Any, object()),
        worktree_path="/tmp/worktree",
        artifact_store=FilesystemArtifactStore(Path("/tmp/test-graph-artifacts")),
        running_executions=running,
    )

    await executor.wait_for_all(timeout_seconds=0.0, active_execution_ids={"exec-active"})

    assert not task.done()
    assert running == {"exec-active": task}

    release.set()
    await executor.wait_for_all(active_execution_ids={"exec-active"})

    assert task.done()
    assert running == {}


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
async def test_serialized_worktree_execution_prevents_concurrent_baseline_overlap(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    executor = RecordingExecutor()
    started: list[str] = []
    release = asyncio.Event()
    first = _context(node_id="worker-1", worktree_path=str(repo))
    second = replace(_context(node_id="worker-2", worktree_path=str(repo)), execution_id="exec-2")

    first_task = asyncio.create_task(
        executor._run_agent_serialized(first, BlockingSubmitAgent(started, release))
    )
    while started != ["worker-1"]:
        await asyncio.sleep(0)
    second_task = asyncio.create_task(
        executor._run_agent_serialized(second, RecordingSubmitAgent(started))
    )
    await asyncio.sleep(0)

    assert started == ["worker-1"]
    release.set()
    await asyncio.gather(first_task, second_task)

    assert started == ["worker-1", "worker-2"]


@pytest.mark.asyncio
async def test_executor_logs_usage_observer_failure_without_marking_agent_dead(
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = _context()
    executor = RecordingExecutor()
    executor._on_agent_usage = RaisingUsageObserver()

    await executor._run_agent(context, OutputAgent(["line"]))

    assert executor.failures == []
    assert "graph usage observer failed" in caplog.text


@pytest.mark.asyncio
async def test_executor_marks_agent_died_when_runner_exits_without_submit() -> None:
    context = _context()
    executor = RecordingExecutor()
    agent = NoSubmitAgent(["done but not submitted"])

    await executor._run_agent(context, agent)

    assert executor.started == [context]
    assert executor.submitted == []
    assert executor.failures == ["agent exited without submit"]


def test_runtime_death_max_attempts_bounds_gap_planners_without_node_limit() -> None:
    assert (
        _runtime_death_max_attempts(_context(node_kind="planner", node_role="gap_planner"))
        == DEFAULT_GAP_PLANNER_RUNTIME_DEATH_MAX_ATTEMPTS
    )
    assert _runtime_death_max_attempts(_context(node_payload={"max_attempts": 7})) == 7
    assert _runtime_death_max_attempts(_context(node_payload={"max_attempts": True})) is None
    assert _runtime_death_max_attempts(_context(node_kind="worker", node_role="builder")) is None


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
    assert context.node_payload["_accepted_gap_planner_patch_had_ops"] is True


@pytest.mark.asyncio
async def test_gap_planner_no_op_graph_patch_callback_allows_submit() -> None:
    context = _context(node_id="gap-planner-1", node_kind="planner", node_role="gap_planner")
    executor = RecordingExecutor()
    agent = NoOpPatchThenSubmitAgent([])

    await executor._run_agent(context, agent)

    assert executor.graph_patches == [
        (
            context,
            {
                "patch_id": "patch-1",
                "base_graph_position": 3,
                "ops": [],
            },
        )
    ]
    assert executor.submitted == [context]
    assert executor.failures == []
    assert context.node_payload["_accepted_gap_planner_patch_had_ops"] is False
    assert "_accepted_graph_patch_had_ops" not in context.node_payload


@pytest.mark.asyncio
async def test_graph_patch_callback_rejects_unauthorized_node_contracts() -> None:
    executor = GraphDispatchExecutor(
        cast(async_sessionmaker[AsyncSession], object()),
        cast(Any, object()),
        cast(Any, object()),
        worktree_path="/tmp/worktree",
        artifact_store=FilesystemArtifactStore(Path("/tmp/test-graph-artifacts")),
    )

    for context in (
        _context(node_id="worker-1", node_kind="worker", node_role="builder"),
        _context(node_id="fan-out-reader-1", node_kind="planner", node_role="fan_out_reader"),
    ):
        with pytest.raises(ValueError, match=f"node {context.node_id} is not authorized"):
            await executor._submit_graph_patch_callback(
                context,
                {
                    "patch_id": "patch-unauthorized",
                    "base_graph_position": 1,
                    "ops": [],
                },
            )


def test_raw_patch_tool_feedback_includes_all_locations_beyond_durable_cap() -> None:
    diagnostics = _full_raw_patch_validation_diagnostics(
        {
            "patch_id": "patch-many-errors",
            "base_graph_position": -1,
            "ops": [
                {"op": "create_node", f"unexpected_{index}": "not-persisted"} for index in range(40)
            ],
        },
        "planner-1",
    )

    assert diagnostics is not None
    assert diagnostics["error_count"] == 40
    assert diagnostics["omitted_error_count"] == 0
    assert diagnostics["errors"][0]["path"] == "ops[0].unexpected_0"
    assert diagnostics["errors"][-1]["path"] == "ops[9].unexpected_9"
    assert all(item["message"] == "Extra field is not allowed" for item in diagnostics["errors"])


@pytest.mark.parametrize(
    "payload, expected_path",
    [
        (
            {
                "patch_id": "patch-extra-flat",
                "base_graph_position": -1,
                "ops": [],
                "unexpected_outer": "not-persisted",
            },
            "unexpected_outer",
        ),
        (
            {
                "patch_id": "patch-extra-nested",
                "base_graph_position": -1,
                "ops": [],
                "unexpected_nested": "not-persisted",
            },
            "unexpected_nested",
        ),
    ],
)
def test_raw_patch_feedback_preflight_locates_unknown_envelope_fields(
    payload: dict[str, Any],
    expected_path: str,
) -> None:
    diagnostics = _full_raw_patch_validation_diagnostics(payload, "planner-1")

    assert diagnostics is not None
    assert diagnostics["errors"] == [
        {
            "path": expected_path,
            "code": "extra_forbidden",
            "message": "Extra field is not allowed",
        }
    ]


def test_nested_patch_feedback_preserves_native_wrapper_paths_without_duplicates() -> None:
    diagnostics = _full_raw_patch_validation_diagnostics(
        normalize_patch_payload(
            {
                "patch": {
                    "patch_id": "",
                    "base_graph_position": "bad",
                    "ops": [{"op": "create_node", "unexpected": "not-persisted"}],
                    "unexpected_nested": "not-persisted",
                },
                "unexpected_wrapper": "not-persisted",
            }
        ),
        "planner-1",
    )

    assert diagnostics is not None
    paths = [item["path"] for item in diagnostics["errors"]]
    assert "patch.patch_id" in paths
    assert "patch.base_graph_position" in paths
    assert "patch.ops[0].unexpected" in paths
    assert "patch.unexpected_nested" in paths
    assert "unexpected_wrapper" in paths
    assert len(paths) == len(set(paths))


def test_non_object_nested_patch_has_one_precise_wrapper_error() -> None:
    diagnostics = _full_raw_patch_validation_diagnostics(
        normalize_patch_payload({"patch": "not-an-object"}),
        "planner-1",
    )

    assert diagnostics == {
        "error_count": 1,
        "errors": [
            {
                "path": "patch",
                "code": "model_type",
                "message": "Input must be an object",
            }
        ],
        "omitted_error_count": 0,
    }


def test_nested_patch_wrapper_paths_use_safe_validation_renderer() -> None:
    long_key = "x" * 100
    diagnostics = _full_raw_patch_validation_diagnostics(
        normalize_patch_payload(
            {
                "patch": {"patch_id": "patch-1", "base_graph_position": -1, "ops": []},
                "api_key": "not-persisted",
                "line\nbreak": "not-persisted",
                long_key: "not-persisted",
            }
        ),
        "planner-1",
    )

    assert diagnostics is not None
    paths = {item["path"] for item in diagnostics["errors"]}
    assert "api_key" not in paths
    assert "<redacted>" in paths
    assert "line\\nbreak" in paths
    assert f"{'x' * 80}…" in paths


def test_nested_patch_missing_envelope_fields_has_one_diagnostic_per_path() -> None:
    diagnostics = _full_raw_patch_validation_diagnostics(
        normalize_patch_payload({"patch": {"ops": []}}),
        "planner-1",
    )

    assert diagnostics is not None
    assert diagnostics["errors"] == [
        {
            "path": "patch.base_graph_position",
            "code": "missing",
            "message": "Field required",
        },
        {
            "path": "patch.patch_id",
            "code": "missing",
            "message": "Field required",
        },
    ]


def test_raw_patch_feedback_aggregates_outer_and_operation_errors() -> None:
    diagnostics = _full_raw_patch_validation_diagnostics(
        {
            "patch_id": "patch-combined-errors",
            "base_graph_position": -1,
            "ops": [
                {"op": "create_node", f"unexpected_{index}": "not-persisted"} for index in range(40)
            ],
            "unexpected_outer": "not-persisted",
        },
        "planner-1",
    )

    assert diagnostics is not None
    assert diagnostics["error_count"] == 41
    assert diagnostics["omitted_error_count"] == 0
    assert {item["path"] for item in diagnostics["errors"]} == {
        "unexpected_outer",
        *(f"ops[{index}].unexpected_{index}" for index in range(40)),
    }


def test_raw_patch_feedback_aggregates_envelope_and_operation_errors() -> None:
    diagnostics = _full_raw_patch_validation_diagnostics(
        {
            "patch_id": "",
            "base_graph_position": "bad-position",
            "ops": [
                {"op": "create_node", f"unexpected_{index}": "not-persisted"} for index in range(40)
            ],
            "unexpected_outer": "not-persisted",
        },
        "planner-1",
    )

    assert diagnostics is not None
    paths = {item["path"] for item in diagnostics["errors"]}
    assert {
        "patch_id",
        "base_graph_position",
        "unexpected_outer",
        *(f"ops[{index}].unexpected_{index}" for index in range(40)),
    } <= paths
    assert diagnostics["error_count"] == len(paths)
    assert diagnostics["omitted_error_count"] == 0


@pytest.mark.asyncio
async def test_graph_patch_callback_returns_all_safe_diagnostics_beyond_durable_cap() -> None:
    class _FeedbackExecutor(GraphDispatchExecutor):
        async def _current_position(self, run_id: str) -> int:
            assert run_id == "run-1"
            return -1

        async def _handle_command_retry_stale(self, *args: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(
                events=[
                    _event(
                        "command_rejected",
                        {
                            "command_type": "submit_patch",
                            "reason": "malformed patch [malformed_patch]",
                            "patch_id": "patch-many-errors",
                        },
                    )
                ]
            )

    executor = _FeedbackExecutor(
        cast(async_sessionmaker[AsyncSession], object()),
        cast(Any, object()),
        cast(Any, object()),
        worktree_path="/tmp/worktree",
        artifact_store=FilesystemArtifactStore(Path("/tmp/test-graph-artifacts")),
    )
    feedback = await executor._submit_graph_patch_callback(
        _context(node_id="planner-1", node_kind="planner", node_role="planner"),
        {
            "patch_id": "patch-many-errors",
            "base_graph_position": -1,
            "ops": [
                {"op": "create_node", f"unexpected_{index}": "not-persisted"} for index in range(40)
            ],
        },
    )

    diagnostics = json.loads(feedback.split("validation_diagnostics=", maxsplit=1)[1])
    assert diagnostics["error_count"] == 40
    assert diagnostics["omitted_error_count"] == 0
    assert {item["path"] for item in diagnostics["errors"]} == {
        f"ops[{index}].unexpected_{index}" for index in range(40)
    }


def test_gap_planner_submit_emits_classified_gap_after_accepted_nonempty_patch() -> None:
    context = _context(node_id="gap-planner-1", node_kind="planner", node_role="gap_planner")
    context.node_payload["_accepted_gap_planner_patch_had_ops"] = True

    records = _output_records_for_submit(context, [])

    assert records == [
        {
            "record_id": "gap-plan-exec-1",
            "record_kind": "output",
            "record_type": "gap_plan",
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
            "record_type": "gap_classification",
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
            "record_type": "classified_gap",
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


def test_gap_planner_submit_emits_no_gap_after_accepted_no_op_patch() -> None:
    context = _context(node_id="gap-planner-1", node_kind="planner", node_role="gap_planner")
    context.node_payload["_accepted_gap_planner_patch_had_ops"] = False

    records = _output_records_for_submit(context, [])

    assert [record["record_type"] for record in records] == [
        "gap_plan",
        "gap_classification",
        "classified_gap",
    ]
    assert {record["value"]["classification"] for record in records} == {"no_gap"}
    assert {record["value"]["source"] for record in records} == {"accepted_gap_planner_no_op_patch"}


def test_check_submit_does_not_fabricate_pass_record() -> None:
    context = _context(
        node_id="check-1",
        node_kind="check",
        node_payload={"command_definition": {"id": "unit-check", "cmd": "true"}},
    )

    assert _output_records_for_submit(context, []) == []


def test_worker_submit_emits_declared_artifact_references() -> None:
    context = _context(
        node_id="worker-1",
        node_kind="worker",
        node_payload={
            "candidate_id": "candidate-1",
            "artifacts": [
                {
                    "path": "docs/dynamic-graph/output-proof.txt",
                    "description": "Output proof artifact",
                }
            ],
        },
    )

    records = _output_records_for_submit(context, [])

    assert records[0]["record_id"] == "candidate-1"
    assert records[1] == {
        "record_id": "artifact-reference-exec-1-0",
        "record_kind": "graph_record",
        "record_type": "artifact_reference",
        "producer_node_id": "worker-1",
        "port": "artifact_reference",
        "schema": "ArtifactReference",
        "value": {
            "artifact_id": "docs/dynamic-graph/output-proof.txt",
            "artifact_type": "run_output",
            "uri": "docs/dynamic-graph/output-proof.txt",
            "summary": "Output proof artifact",
            "source_record_ids": ["candidate-1"],
        },
    }


def test_execution_context_uses_contract_tools_when_node_tools_are_absent() -> None:
    context = _context(node_id="planner-1", node_kind="planner", node_role="planner")
    executor = RecordingExecutor()

    execution_context = executor._execution_context(context)

    assert execution_context.available_tools is not None
    assert "submit_graph_patch" in execution_context.available_tools
    assert "create_work_region" in execution_context.available_tools


def test_execution_context_does_not_grant_graph_tools_to_fan_out_planner_role() -> None:
    context = _context(node_id="fan-out-reader-1", node_kind="planner", node_role="fan_out_reader")
    executor = RecordingExecutor()

    execution_context = executor._execution_context(context)

    assert execution_context.available_tools is None


def test_execution_context_preserves_explicit_node_tools() -> None:
    context = _context(
        node_id="planner-1",
        node_kind="planner",
        node_role="planner",
        node_payload={"available_tools": ["read_file"]},
    )
    executor = RecordingExecutor()

    execution_context = executor._execution_context(context)

    assert execution_context.available_tools == ["read_file"]


def test_verifier_submit_cites_bound_candidate_and_file_state_records() -> None:
    graph_events = [
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            1,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "file_state",
                "record_ids": ["file-state-1"],
            },
            2,
        ),
    ]
    context = _context(
        node_id="verifier-1",
        node_kind="verifier",
        graph_events=graph_events,
        node_payload={"candidate_id": "candidate-1", "task_region_id": "task-1"},
    )

    records = _output_records_for_submit(context, [("R1", "A", "verified")])

    record = records[0]
    assert record["outcome"] == "passed"
    assert "verdict" not in record
    assert record["value"]["outcome"] == "passed"
    assert record["candidate_record_id"] == "candidate-1"
    assert record["candidate_record_ids"] == ["candidate-1"]
    assert record["file_state_record_ids"] == ["file-state-1"]
    assert record["evaluated_record_ids"] == ["candidate-1", "file-state-1"]
    assert record["provenance"]["evaluated_record_ids"] == ["candidate-1", "file-state-1"]
    assert record["evidence"]["candidate_record_ids"] == ["candidate-1"]


def test_verifier_submit_uses_bound_candidate_over_node_metadata() -> None:
    graph_events = [
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-bound"],
            },
            1,
        ),
    ]
    context = _context(
        node_id="verifier-1",
        node_kind="verifier",
        graph_events=graph_events,
        node_payload={
            "candidate_id": "candidate-from-planner-metadata",
            "task_region_id": "task-1",
        },
    )

    records = _output_records_for_submit(context, [("R1", "A", "verified")])

    assert records[0]["candidate_id"] == "candidate-bound"
    assert records[0]["candidate_record_id"] == "candidate-bound"


def test_verifier_submit_inherits_file_state_citations_from_candidate_record() -> None:
    graph_events = [
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-1",
                "task_region_id": "task-1",
                "file_state_record_ids": ["file-state-1"],
                "value": {
                    "summary": "candidate with captured file state",
                    "file_state_record_ids": ["file-state-1"],
                },
            },
            1,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            2,
        ),
    ]
    context = _context(
        node_id="verifier-1",
        node_kind="verifier",
        graph_events=graph_events,
        node_payload={"candidate_id": "candidate-1", "task_region_id": "task-1"},
    )

    records = _output_records_for_submit(context, [("R1", "A", "verified")])

    record = records[0]
    assert record["candidate_record_ids"] == ["candidate-1"]
    assert record["file_state_record_ids"] == ["file-state-1"]
    assert record["evaluated_record_ids"] == ["candidate-1", "file-state-1"]
    assert record["evidence"]["file_state_record_ids"] == ["file-state-1"]


@pytest.mark.asyncio
async def test_execute_check_command_records_real_process_success(tmp_path: Path) -> None:
    graph_events = [
        _event(
            "input_bound",
            {
                "to_node_id": "check-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
            1,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "check-1",
                "to_port": "file_state",
                "record_ids": ["file-state-1"],
            },
            2,
        ),
    ]
    context = _context(
        node_id="check-1",
        node_kind="check",
        worktree_path=str(tmp_path),
        graph_events=graph_events,
        node_payload={
            "task_region_id": "task-1",
            "candidate_id": "stale-node-metadata-candidate",
            "attempt_number": 2,
            "command_definition": {
                "id": "pass-check",
                "argv": ["sh", "-c", "printf pass-output"],
                "timeout_seconds": 5,
            },
        },
    )

    record = await _execute_check_command(context, FilesystemArtifactStore(tmp_path / "artifacts"))

    assert record["record_type"] == "check_result"
    assert record["record_kind"] == "output"
    assert record["producer_node_id"] == "check-1"
    assert record["port"] == "check_result"
    assert record["candidate_id"] == "candidate-1"
    assert record["task_region_id"] == "task-1"
    assert record["attempt_number"] == 2
    assert record["candidate_record_id"] == "candidate-1"
    assert record["candidate_record_ids"] == ["candidate-1"]
    assert record["file_state_record_ids"] == ["file-state-1"]
    assert record["evaluated_record_ids"] == ["candidate-1", "file-state-1"]
    assert record["provenance"]["evaluated_record_ids"] == ["candidate-1", "file-state-1"]
    value = cast(dict[str, Any], record["value"])
    assert value["status"] == "passed"
    assert value["exit_code"] == 0
    assert value["stdout_tail"] == "pass-output"
    assert value["stderr_tail"] == ""
    assert value["command_id"] == "pass-check"
    assert value["command_text"] == "sh -c printf pass-output"
    assert value["base_snapshot_id"] == "routine-snapshot"
    assert value["worktree_path"] == str(tmp_path)
    assert value["candidate_record_ids"] == ["candidate-1"]
    assert value["file_state_record_ids"] == ["file-state-1"]
    assert value["evaluated_record_ids"] == ["candidate-1", "file-state-1"]
    assert isinstance(value["duration_ms"], int)


@pytest.mark.asyncio
async def test_execute_check_command_runs_against_bound_file_state_snapshot(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, text=True, check=True)
    (repo / "candidate.txt").write_text("snapshot-value", encoding="utf-8")
    snap = snapshot(repo, "candidate snapshot")
    (repo / "candidate.txt").write_text("mutated-value", encoding="utf-8")
    graph_events = [
        _event(
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "snapshot_id": snap.id,
                "base_snapshot_id": "routine-snapshot",
                "git": {"ref": snap.ref, "commit_sha": snap.commit_sha, "tree_sha": snap.tree_sha},
                "verdict": "captured",
            },
            1,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "check-1",
                "to_port": "file_state",
                "record_ids": ["file-state-1"],
            },
            2,
        ),
    ]
    context = _context(
        node_id="check-1",
        node_kind="check",
        worktree_path=str(repo),
        graph_events=graph_events,
        node_payload={
            "task_region_id": "task-1",
            "candidate_id": "candidate-1",
            "command_definition": {
                "id": "snapshot-check",
                "argv": ["sh", "-c", "cat candidate.txt"],
                "timeout_seconds": 5,
            },
        },
    )

    record = await _execute_check_command(context, FilesystemArtifactStore(tmp_path / "artifacts"))

    value = cast(dict[str, Any], record["value"])
    assert value["stdout_tail"] == "snapshot-value"
    assert value["worktree_path"] == str(repo)
    assert value["source_worktree_path"] == str(repo)
    assert value["execution_snapshot_id"] == snap.id
    assert value["execution_snapshot_ref"] == snap.ref
    assert value["execution_worktree_path"] != str(repo)
    assert not Path(cast(str, value["execution_worktree_path"])).exists()
    assert (repo / "candidate.txt").read_text(encoding="utf-8") == "mutated-value"


@pytest.mark.asyncio
async def test_execute_check_command_provisions_node_dependencies_for_snapshot(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, text=True, check=True)
    ui_dir = repo / "ui"
    ui_dir.mkdir()
    (ui_dir / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
    subprocess.run(["git", "add", "ui/package.json"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test User",
            "commit",
            "-m",
            "package",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    snap = snapshot(repo, "candidate snapshot")
    node_bin = ui_dir / "node_modules" / ".bin"
    node_bin.mkdir(parents=True)
    (node_bin / "vitest").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (node_bin / "vitest").chmod(0o755)
    graph_events = [
        _event(
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "snapshot_id": snap.id,
                "base_snapshot_id": "routine-snapshot",
                "git": {"ref": snap.ref, "commit_sha": snap.commit_sha, "tree_sha": snap.tree_sha},
                "verdict": "captured",
            },
            1,
        ),
        _event(
            "input_bound",
            {
                "to_node_id": "check-1",
                "to_port": "file_state",
                "record_ids": ["file-state-1"],
            },
            2,
        ),
    ]
    context = _context(
        node_id="check-1",
        node_kind="check",
        worktree_path=str(repo),
        graph_events=graph_events,
        node_payload={
            "task_region_id": "task-1",
            "candidate_id": "candidate-1",
            "command_definition": {
                "id": "snapshot-node-check",
                "cmd": "test -x ui/node_modules/.bin/vitest",
                "timeout_seconds": 5,
            },
        },
    )

    record = await _execute_check_command(context, FilesystemArtifactStore(tmp_path / "artifacts"))

    value = cast(dict[str, Any], record["value"])
    assert value["status"] == "passed"
    provisioning = value["environment_policy"]["dependency_provisioning"]
    assert provisioning == [
        {
            "package_dir": "ui",
            "strategy": "symlink_source_node_modules",
            "status": "provisioned",
            "detail": f"linked {ui_dir / 'node_modules'}",
        }
    ]


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

    record = await _execute_check_command(context, FilesystemArtifactStore(tmp_path / "artifacts"))

    value = cast(dict[str, Any], record["value"])
    assert value["status"] == "failed"
    assert value["classification"] == "failed"
    assert value["exit_code"] == 7
    assert value["stderr_tail"] == "fail-error"
    assert value["stdout_tail"] == ""


@pytest.mark.asyncio
async def test_execute_check_command_classifies_missing_tool_as_environment_issue(
    tmp_path: Path,
) -> None:
    context = _context(
        node_id="check-1",
        node_kind="check",
        worktree_path=str(tmp_path),
        node_payload={
            "command_definition": {
                "id": "missing-tool",
                "cmd": "definitely_missing_graph_tool_12345 --version",
                "timeout_seconds": 5,
            },
        },
    )

    record = await _execute_check_command(context, FilesystemArtifactStore(tmp_path / "artifacts"))

    value = cast(dict[str, Any], record["value"])
    assert value["status"] == "failed"
    assert value["classification"] == "tool_unavailable"
    assert value["exit_code"] == 127


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

    record = await _execute_check_command(context, FilesystemArtifactStore(tmp_path / "artifacts"))

    value = cast(dict[str, Any], record["value"])
    assert value["status"] == "passed"
    assert value["command_id"] == "check-1"
    assert value["command_binding"] == "dynamic_feature_hidden_oracle"
    assert value["command"]["source"] == "dynamic_feature_hidden_oracle_binding"
    assert value["stdout_tail"] == "bound-oracle"


@pytest.mark.asyncio
async def test_execute_check_command_cites_verification_when_oracle_falls_back_to_acceptance(
    tmp_path: Path,
) -> None:
    graph_events = [
        _event(
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "routine_snapshot",
                "state": "completed",
                "snapshot": {
                    "dynamic_feature": {
                        "acceptance_command": "definitely_missing_duplicate_acceptance_tool",
                        "hidden_oracle_command": "",
                    }
                },
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-1",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-1",
                "candidate_record_ids": ["candidate-1"],
                "task_region_id": "task-1",
                "outcome": "passed",
                "value": {"outcome": "passed"},
            },
            2,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-verification-check",
                "to_node_id": "check-1",
                "to_port": "verification_evidence",
                "record_ids": ["verification-1"],
            },
            3,
        ),
    ]
    context = _context(
        node_id="check-1",
        node_kind="check",
        worktree_path=str(tmp_path),
        graph_events=graph_events,
        node_payload={
            "task_region_id": "task-1",
            "command_binding": "dynamic_feature_hidden_oracle",
        },
    )

    record = await _execute_check_command(context, FilesystemArtifactStore(tmp_path / "artifacts"))

    value = cast(dict[str, Any], record["value"])
    assert value["status"] == "passed"
    assert value["classification"] == "passed"
    assert value["citation_mode"] == "verification_report_reused"
    assert record["evaluated_record_ids"] == ["verification-1", "candidate-1"]


@pytest.mark.asyncio
async def test_execute_check_command_cites_bound_verification_and_region_file_state(
    tmp_path: Path,
) -> None:
    graph_events = [
        _event(
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "task-1",
            },
            1,
        ),
        _event(
            "node_created",
            {
                "node_id": "check-1",
                "kind": "check",
                "state": "planned",
                "task_region_id": "task-1",
            },
            2,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-1",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-1",
                "candidate_record_ids": ["candidate-1"],
                "evaluated_record_ids": ["candidate-1"],
                "task_region_id": "task-1",
                "outcome": "passed",
                "value": {
                    "outcome": "passed",
                    "grades": [{"requirement_id": "R1", "grade": "A"}],
                },
            },
            3,
        ),
        _event(
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "record_type": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "snapshot_id": "snapshot-1",
                "base_snapshot_id": "routine-snapshot",
                "task_region_id": "task-1",
                "verdict": "captured",
            },
            4,
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-verification-check",
                "to_node_id": "check-1",
                "to_port": "verification_evidence",
                "record_ids": ["verification-1"],
            },
            5,
        ),
    ]
    context = _context(
        node_id="check-1",
        node_kind="check",
        worktree_path=str(tmp_path),
        graph_events=graph_events,
        node_payload={
            "task_region_id": "task-1",
            "command_definition": {
                "id": "runtime-check",
                "cmd": "printf runtime-ok",
                "timeout_seconds": 5,
            },
        },
    )

    record = await _execute_check_command(context, FilesystemArtifactStore(tmp_path / "artifacts"))

    assert record["candidate_id"] == "candidate-1"
    assert record["candidate_record_ids"] == ["candidate-1"]
    assert record["file_state_record_ids"] == ["file-state-1"]
    assert record["evaluated_record_ids"] == ["verification-1", "candidate-1", "file-state-1"]
    value = cast(dict[str, Any], record["value"])
    assert value["candidate_record_ids"] == ["candidate-1"]
    assert value["file_state_record_ids"] == ["file-state-1"]
    assert value["evaluated_record_ids"] == [
        "verification-1",
        "candidate-1",
        "file-state-1",
    ]


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
    assert value["stdout_tail"] == "runtime-ok"


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


class _FakeCommandResult:
    def __init__(self, events: list[Any]) -> None:
        self.events = events
        self.outbox_items: list[Any] = []
        self.projection_position = 1


def _locked_operational_error() -> OperationalError:
    return OperationalError(
        "INSERT INTO events_v2 ...",
        {},
        sqlite3.OperationalError("database is locked"),
    )


class LockedOnceController:
    """Fails the first ``handle_command`` call with a locked DB error, then succeeds."""

    def __init__(self, fail_times: int = 1) -> None:
        self.calls = 0
        self._fail_times = fail_times

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, Any] | None = None,
        *,
        context: GraphCommandContext | None = None,
    ) -> _FakeCommandResult:
        assert context is not None
        self.calls += 1
        if self.calls <= self._fail_times:
            raise _locked_operational_error()
        return _FakeCommandResult([])


class AlwaysNonLockedErrorController:
    """Raises a non-lock OperationalError that must never be retried."""

    def __init__(self) -> None:
        self.calls = 0

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, Any] | None = None,
        *,
        context: GraphCommandContext | None = None,
    ) -> _FakeCommandResult:
        assert context is not None
        self.calls += 1
        raise OperationalError("SELECT 1", {}, sqlite3.OperationalError("no such table"))


@pytest.mark.asyncio
async def test_handle_command_retry_stale_retries_locked_operational_error_then_succeeds() -> None:
    controller = LockedOnceController(fail_times=1)
    executor = GraphDispatchExecutor(
        cast(async_sessionmaker[AsyncSession], object()),
        cast(Any, controller),
        cast(Any, object()),
        worktree_path="/tmp/worktree",
        artifact_store=FilesystemArtifactStore(Path("/tmp/test-graph-artifacts")),
    )

    result = await executor._handle_command_retry_stale(
        "run-1",
        0,
        "record_heartbeat",
        {"lease_id": "lease-1"},
    )

    assert controller.calls == 2
    assert result.events == []


@pytest.mark.asyncio
async def test_handle_command_retry_stale_reraises_non_locked_operational_error_immediately() -> (
    None
):
    controller = AlwaysNonLockedErrorController()
    executor = GraphDispatchExecutor(
        cast(async_sessionmaker[AsyncSession], object()),
        cast(Any, controller),
        cast(Any, object()),
        worktree_path="/tmp/worktree",
        artifact_store=FilesystemArtifactStore(Path("/tmp/test-graph-artifacts")),
    )

    with pytest.raises(OperationalError):
        await executor._handle_command_retry_stale("run-1", 0, "record_heartbeat", {})

    assert controller.calls == 1
