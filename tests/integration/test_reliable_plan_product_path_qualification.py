from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from orchestrator.api import CreateRunRequest, create_app
from orchestrator.config import AgentRunnerType, RoutineConfig, RunStatus, load_routine_from_path
from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.db import RunRepository, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    GraphCommandContext,
    FakeClock,
    MAX_EVENT_ENVELOPE_BYTES,
    PatchCommandContext,
    ReliablePlanEvaluationConfig,
    ReliablePlanScenarioResult,
    ReliablePlanSkeletonQualification,
    SequentialIdGenerator,
    authorize_reliable_plan_one_horizon,
    build_projection,
    compile_routine,
    event_factory,
    execution_attempts_view,
    input_bindings_view,
    leases_view,
    node_kinds_view,
    node_attempts_view,
    node_payload_view,
    node_states_view,
    output_record_payloads_view,
    ready_nodes_view,
    runtime_retry_counts_view,
    require_reliable_plan_one_horizon_authorization,
    serialize_authorized_reliable_plan_run_config,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    OutboxItem,
    assemble_graph_dispatch_context,
    require_reliable_plan_qualification_for_run,
    run_reliable_plan_product_path_scenarios,
    verified_reliable_plan_seed_config,
)
from orchestrator.runners import AgentRunner, CodexServerAgent
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
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import GraphRunDriver, WorkflowService


FIXTURE = Path("tests/fixtures/graph/reliable_plan_fff4f6b7.json")


class _InjectedCodexTransport:
    """Queue-backed real JSON-RPC transport for the joined product seam."""

    def __init__(
        self,
        messages: list[dict[str, Any]],
        *,
        on_failed_tool_response: Callable[[], Awaitable[None]],
        on_successful_tool_response: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for message in messages:
            self._queue.put_nowait(message)
        self._on_failed_tool_response = on_failed_tool_response
        self._on_successful_tool_response = on_successful_tool_response
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)
        result = message.get("result")
        if isinstance(result, dict) and result.get("success") is False:
            await self._on_failed_tool_response()
        elif (
            isinstance(result, dict)
            and result.get("success") is True
            and self._on_successful_tool_response is not None
        ):
            await self._on_successful_tool_response()

    async def recv(self) -> dict[str, Any]:
        return await self._queue.get()

    async def close(self) -> None:
        return None


class _SingleCodexFactory:
    """Inject one real agent adapter into the production dispatch executor."""

    def __init__(self, agent: AgentRunner) -> None:
        self._agent = agent

    def preflight(
        self,
        context: Any,
        execution_context: Any,
        *,
        graph_mcp_available: bool,
    ) -> None:
        del context, execution_context, graph_mcp_available
        return None

    def create_runner(self, context: Any) -> AgentRunner:
        del context
        return self._agent


class _OversizedSemanticSubmitAgent:
    """Submit valid semantic content that genuinely exceeds the event envelope."""

    def __init__(self) -> None:
        self.attempts = 0

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
            name="oversized-semantic-submit",
        )

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
        del on_checklist_update, on_output, on_grade, on_agent_metadata, on_escalation
        assert context.submission_contract is not None
        assert context.submission_contract.requires_arguments
        self.attempts += 1
        typed_submit = cast(
            Callable[[dict[str, Any] | None], Awaitable[None]],
            on_submit,
        )
        await typed_submit(
            {
                "outputs": {
                    "semantic_artifact": {
                        "summary": "x" * 40_000,
                        "batches": [
                            {
                                "batch_id": "batch-1",
                                "objective": "Exercise terminal persistence recovery.",
                                "acceptance": ["failure remains observable"],
                            }
                        ],
                    }
                }
            }
        )
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


def _codex_messages(valid_content: dict[str, Any]) -> list[dict[str, Any]]:
    def tool_call(req_id: int, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "item/tool/call",
            "params": {"tool": "submit", "arguments": args},
        }

    return [
        {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "joined-test/1"}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"thread": {"id": "thread-joined", "modelProvider": "openai"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"turn": {"id": "turn-joined", "status": "inProgress", "items": []}},
        },
        tool_call(10, {"outputs": {}}),
        tool_call(11, {"outputs": {"semantic_artifact": {}}}),
        tool_call(12, {"outputs": {"semantic_artifact": valid_content}}),
        {
            "jsonrpc": "2.0",
            "method": "turn/completed",
            "params": {
                "turn": {
                    "id": "turn-joined",
                    "status": "completed",
                    "items": [],
                    "error": None,
                }
            },
        },
    ]


def _codex_exhaustion_messages(valid_content: dict[str, Any]) -> list[dict[str, Any]]:
    messages = _codex_messages(valid_content)[:3]

    def tool_call(req_id: int, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "item/tool/call",
            "params": {"tool": "submit", "arguments": args},
        }

    messages.extend(
        [
            tool_call(10, {"outputs": {}}),
            tool_call(11, {"outputs": {"semantic_artifact": {}}}),
            tool_call(
                12,
                {
                    "outputs": {
                        "semantic_artifact": {
                            **valid_content,
                            "producer_node_id": "spoofed-discovery",
                        }
                    }
                },
            ),
        ]
    )
    return messages


def _init_git_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("# joined product seam\n")
    (path / "test_authoritative_acceptance.py").write_text(
        "def test_authoritative_acceptance():\n    assert True\n"
    )
    subprocess.run(
        ["git", "add", "README.md", "test_authoritative_acceptance.py"],
        cwd=path,
        check=True,
    )
    subprocess.run(["git", "commit", "-q", "-m", "Initial"], cwd=path, check=True)


@pytest.mark.asyncio
async def test_codex_product_seam_composes_mixed_owned_outputs_and_unblocks_verifier(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "mixed-output-product-seam.db")
    sessions = create_session_factory(engine)
    await init_db(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    run_id = "mixed-output-product-seam"
    worker_id = "worker-reliable-plan-semantic-revision"
    verifier_id = "verifier-reliable-plan-semantic-revision"
    candidate_id = "semantic-artifact-revision-40a6d711-semantic_artifact"
    make_event = event_factory(run_id, "seed_compiled_events", clock, ids)
    semantic_content = {
        "batches": [
            {
                "batch_id": "batch-1",
                "objective": "Revise the failed implementation plan.",
                "acceptance": ["the failed grade is addressed"],
            }
        ]
    }
    worktree = tmp_path / "mixed-output-worktree"
    _init_git_repo(worktree)
    artifact_store = FilesystemArtifactStore(tmp_path / "mixed-output-artifacts")

    async def observe_tool_response() -> None:
        return None

    try:
        seeded = await controller.handle_command(
            run_id,
            0,
            "seed_compiled_events",
            {
                "events": [
                    make_event(
                        "node_created",
                        {
                            "node_id": "routine-snapshot",
                            "kind": "context",
                            "state": "completed",
                        },
                    ),
                    make_event(
                        "output_record_accepted",
                        {
                            "record_id": "semantic-schema-plan-v1",
                            "record_kind": "graph_record",
                            "record_type": "semantic_schema_declaration",
                            "producer_node_id": "routine-snapshot",
                            "port": "semantic_schema_declaration",
                            "schema": "SemanticSchemaDeclaration",
                            "schema_version": 1,
                            "value": {
                                "schema_id": "reliable-plan-implementation-plan",
                                "version": 1,
                                "semantic_role": "implementation_plan",
                                "json_schema": {
                                    "type": "object",
                                    "required": ["batches"],
                                    "properties": {"batches": {"type": "array", "minItems": 1}},
                                    "additionalProperties": False,
                                },
                                "authority": "routine_snapshot",
                            },
                        },
                    ),
                    make_event(
                        "node_created",
                        {
                            "node_id": worker_id,
                            "kind": "worker",
                            "role": "fixer",
                            "state": "planned",
                            "task_region_id": "corrective_work_region",
                            "attempt_number": 2,
                            "candidate_id": candidate_id,
                            "objective": "Revise the exact failed implementation-plan artifact.",
                            "access_mode": "write",
                            "effect_contract": "effectful_write",
                            "acceptance": ["the failed plan-verification report is addressed"],
                            "semantic_schema_id": "reliable-plan-implementation-plan",
                            "semantic_schema_version": 1,
                            "outputs": [
                                {
                                    "port": "candidate",
                                    "direction": "output",
                                    "schema": "ImplementationCandidate",
                                    "required": True,
                                },
                                {
                                    "port": "semantic_artifact",
                                    "direction": "output",
                                    "schema": "SemanticArtifact",
                                    "required": True,
                                },
                            ],
                        },
                    ),
                    make_event(
                        "node_created",
                        {
                            "node_id": verifier_id,
                            "kind": "verifier",
                            "role": "verifier",
                            "state": "planned",
                            "task_region_id": "corrective_work_region",
                            "inputs": [
                                {
                                    "port": "semantic_artifact",
                                    "direction": "input",
                                    "schema": "SemanticArtifact",
                                    "required": True,
                                }
                            ],
                            "outputs": [
                                {
                                    "port": "verification_report",
                                    "direction": "output",
                                    "schema": "VerificationReport",
                                    "required": True,
                                }
                            ],
                        },
                    ),
                    make_event(
                        "edge_created",
                        {
                            "edge_id": "edge-revised-semantic-artifact-to-verifier",
                            "from_node_id": worker_id,
                            "from_port": "semantic_artifact",
                            "to_node_id": verifier_id,
                            "to_port": "semantic_artifact",
                            "required": True,
                            "accepted_record_selector": {
                                "record_type": "semantic_artifact",
                                "semantic_schema_id": "reliable-plan-implementation-plan",
                                "semantic_schema_version": 1,
                                "authority_status": "accepted",
                            },
                        },
                    ),
                ]
            },
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        scheduled = await controller.handle_command(
            run_id,
            started.projection_position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {worker_id: 100},
            },
        )
        dispatch_item = next(
            item
            for item in scheduled.outbox_items
            if item.kind == "agent_dispatch" and item.payload.get("node_id") == worker_id
        )
        transport = _InjectedCodexTransport(
            _codex_messages(semantic_content),
            on_failed_tool_response=observe_tool_response,
        )
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            _SingleCodexFactory(CodexServerAgent(api_key=None, _transport=transport, _environ={})),
            worktree_path=worktree,
            artifact_store=artifact_store,
        )

        await executor.dispatch(dispatch_item)
        await executor.wait_for_all()

        async with sessions() as session:
            events = await GraphEventStore(session).read_bounded_runtime_events(run_id)
        assert transport.sent
        thread_start = next(
            message for message in transport.sent if message.get("method") == "thread/start"
        )
        submit_tool = next(
            tool for tool in thread_start["params"]["dynamicTools"] if tool["name"] == "submit"
        )
        outputs_schema = submit_tool["inputSchema"]["properties"]["outputs"]
        assert outputs_schema["required"] == ["semantic_artifact"]
        assert set(outputs_schema["properties"]) == {"semantic_artifact"}

        projection = await controller.read_projection(run_id)
        records = [
            record
            for record in output_record_payloads_view(projection).values()
            if record.producer_node_id == worker_id
        ]
        assert sorted(record.port for record in records) == ["candidate", "semantic_artifact"]
        candidate = next(record for record in records if record.port == "candidate")
        semantic = next(record for record in records if record.port == "semantic_artifact")
        assert candidate.record_id == candidate_id
        assert candidate.candidate_id == candidate_id
        assert semantic.value.content == semantic_content
        assert node_states_view(projection)[worker_id] == "completed"
        assert node_states_view(projection)[verifier_id] in {"planned", "ready"}
        assert input_bindings_view(projection)[verifier_id]["semantic_artifact"].record_ids == [
            semantic.record_id
        ]
        assert not any(
            lease.node_id == worker_id and lease.state == "active"
            for lease in leases_view(projection).values()
        )
        attempts = [
            attempt
            for attempt in execution_attempts_view(projection).values()
            if attempt.node_id == worker_id
        ]
        assert len(attempts) == 1
        assert attempts[0].state == "finalized"
        assert sum(event.event_type == "runner_submission_staged" for event in events) == 1
        assert sum(event.event_type == "runner_execution_finalized" for event in events) == 1
        assert not any(
            event.event_type in {"runner_recovery_requested", "runtime_retry_scheduled"}
            for event in events
        )
        verifier_scheduled = await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {verifier_id: 100},
            },
        )
        assert any(
            event.event_type == "lease_granted" and event.payload.get("node_id") == verifier_id
            for event in verifier_scheduled.events
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_codex_submit_repair_exhaustion_recovers_then_terminalizes(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "codex-submit-repair-exhaustion.db")
    sessions = create_session_factory(engine)
    await init_db(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    run_id = "codex-submit-repair-exhaustion"
    worker_id = "worker-discovery"
    make_event = event_factory(run_id, "seed_compiled_events", clock, ids)
    semantic_content = {
        "batches": [
            {
                "batch_id": "batch-1",
                "objective": "Produce a valid plan.",
                "acceptance": ["plan is valid"],
            }
        ]
    }
    worktree = tmp_path / "codex-submit-repair-exhaustion-worktree"
    _init_git_repo(worktree)
    artifact_store = FilesystemArtifactStore(tmp_path / "codex-submit-repair-artifacts")

    async def observe_rejection() -> None:
        return None

    try:
        seeded = await controller.handle_command(
            run_id,
            0,
            "seed_compiled_events",
            {
                "events": [
                    make_event(
                        "node_created",
                        {
                            "node_id": "routine-snapshot",
                            "kind": "context",
                            "state": "completed",
                        },
                    ),
                    make_event(
                        "output_record_accepted",
                        {
                            "record_id": "semantic-schema-plan-v1",
                            "record_kind": "graph_record",
                            "record_type": "semantic_schema_declaration",
                            "producer_node_id": "routine-snapshot",
                            "port": "semantic_schema_declaration",
                            "schema": "SemanticSchemaDeclaration",
                            "schema_version": 1,
                            "value": {
                                "schema_id": "reliable-plan-implementation-plan",
                                "version": 1,
                                "semantic_role": "implementation_plan",
                                "json_schema": {
                                    "type": "object",
                                    "required": ["batches"],
                                    "properties": {"batches": {"type": "array", "minItems": 1}},
                                    "additionalProperties": False,
                                },
                                "authority": "routine_snapshot",
                            },
                        },
                    ),
                    make_event(
                        "node_created",
                        {
                            "node_id": worker_id,
                            "kind": "worker",
                            "role": "discovery",
                            "state": "planned",
                            "attempt_number": 1,
                            "max_attempts": 3,
                            "objective": "Discover a bounded implementation plan.",
                            "access_mode": "read_only",
                            "effect_contract": "read_only_semantic",
                            "acceptance": ["plan is valid"],
                            "semantic_schema_id": "reliable-plan-implementation-plan",
                            "semantic_schema_version": 1,
                            "outputs": [
                                {
                                    "port": "semantic_artifact",
                                    "direction": "output",
                                    "schema": "SemanticArtifact",
                                    "required": True,
                                }
                            ],
                        },
                    ),
                ]
            },
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        scheduled = await controller.handle_command(
            run_id,
            started.projection_position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {worker_id: 100},
            },
        )
        dispatch_item = next(
            item for item in scheduled.outbox_items if item.kind == "agent_dispatch"
        )
        transport = _InjectedCodexTransport(
            _codex_exhaustion_messages(semantic_content),
            on_failed_tool_response=observe_rejection,
        )
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            _SingleCodexFactory(CodexServerAgent(api_key=None, _transport=transport, _environ={})),
            worktree_path=worktree,
            artifact_store=artifact_store,
        )

        await executor.dispatch(dispatch_item)
        await executor.wait_for_all()
        before_recovery = await controller.read_projection(run_id)
        attempt = next(iter(execution_attempts_view(before_recovery).values()))
        assert attempt.state == "recovery_requested"
        assert attempt.recovery_reason == "submission_repair_exhausted"
        assert attempt.recovery_error_detail is not None
        assert "first_cause=" in attempt.recovery_error_detail
        assert "missing required output port semantic_artifact" in attempt.recovery_error_detail
        assert "last_cause=" in attempt.recovery_error_detail
        assert "trusted identity fields are not authorable" in attempt.recovery_error_detail
        assert "operator_action=" in attempt.recovery_error_detail

        dispatcher = OutboxDispatcher(sessions, executor, clock)
        completed = await dispatcher.dispatch_pending(
            run_id=run_id,
            allowed_kinds=frozenset({"runner_recovery"}),
        )
        assert [item.kind for item in completed] == ["runner_recovery"]

        projection = await controller.read_projection(run_id)
        recovered_attempt = execution_attempts_view(projection)[attempt.execution_id]
        assert recovered_attempt.state == "recovered"
        assert node_states_view(projection)[worker_id] == "failed"
        assert all(lease.state != "active" for lease in leases_view(projection).values())
        async with sessions() as session:
            events = await GraphEventStore(session).read_run(run_id)
        terminal = next(
            event
            for event in events
            if event.event_type == "node_state_changed"
            and event.payload.get("trigger") == "submission_repair_exhausted"
        )
        assert terminal.payload["new_state"] == "failed"
        failure = next(
            event
            for event in events
            if event.event_type == "output_record_accepted"
            and event.payload.get("record_type") == "failure_record"
            and event.payload.get("value", {}).get("error_class") == "submission_repair_exhausted"
        )
        assert failure.payload["value"]["retryable"] is False
        assert not any(event.event_type == "runtime_retry_scheduled" for event in events)
        assert sum(event.event_type == "agent_dispatch_requested" for event in events) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_production_reliable_plan_controller_path_gates_first_effectful_lease(
    tmp_path: Path,
) -> None:
    routine_path = Path("routines/dynamic-graph-feature/routine.yaml")
    routine = load_routine_from_path(routine_path)
    evaluation = ReliablePlanEvaluationConfig.model_validate_json(FIXTURE.read_text())

    async def run_arm(
        outcome: str,
        *,
        staged_payload_fault: str | None = None,
    ) -> tuple[GraphController, AsyncEngine, int, str]:
        arm_id = f"{outcome}-{staged_payload_fault or 'ok'}"
        engine = create_engine(tmp_path / f"reliable-plan-{arm_id}.db")
        sessions = create_session_factory(engine)
        await init_db(engine)
        clock = FakeClock()
        controller = GraphController(sessions, clock, SequentialIdGenerator(), auto_dispatch=False)
        run_id = f"reliable-plan-{arm_id}"
        compiled = compile_routine(
            routine,
            clock,
            SequentialIdGenerator(),
            run_id=run_id,
            source_path=str(routine_path),
            run_config={
                "feature_spec_path": "docs/spec.md",
                "acceptance_command": "uv run pytest",
                "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
                "reliable_plan_selected_runner_type": "codex_server",
                "reliable_plan_model_assignments": evaluation.luna_arm.model_dump(mode="json"),
                "reliable_plan_one_horizon_authorized": True,
            },
        )
        seeded = await controller.handle_command(
            run_id, 0, "seed_compiled_events", {"events": compiled}
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        position = started.projection_position
        skeleton = await controller.handle_command(
            run_id,
            position,
            "submit_patch",
            {
                "patch_id": f"initial-skeleton-{outcome}",
                "base_graph_position": position,
                "macro_invocations": [
                    {
                        "macro": "create_discovery_region",
                        "args": {
                            "region_id": "discovery",
                            "worker_id": "worker-discovery",
                            "semantic_schema_id": "reliable-plan-implementation-plan",
                            "semantic_schema_version": 1,
                            "objective": "Discover the implementation plan.",
                            "acceptance": ["plan is complete"],
                            "requirement_source_node_ids": [
                                "requirement-dynamic-feature-acceptance"
                            ],
                        },
                    },
                    {
                        "macro": "create_plan_verification",
                        "args": {
                            "region_id": "plan-verification",
                            "verifier_id": "verifier-plan",
                            "artifact_source_node_id": "worker-discovery",
                            "semantic_schema_id": "reliable-plan-implementation-plan",
                            "semantic_schema_version": 1,
                            "objective": "Independently verify the plan.",
                            "acceptance": ["requirements are covered"],
                            "rubric": ["dynamic_feature_acceptance maps to batch-1"],
                            "requirement_source_node_ids": [
                                "requirement-dynamic-feature-acceptance"
                            ],
                        },
                    },
                    {
                        "macro": "create_successor_planner",
                        "args": {
                            "region_id": "successor",
                            "node_id": "planner-successor",
                            "evidence_source_node_id": "verifier-plan",
                            "evidence_source_port": "verification_report",
                            "planning_horizon": 1,
                        },
                    },
                ],
            },
            context=PatchCommandContext(
                run_id=run_id,
                current_graph_position=position,
                proposed_by_node_id="planner-s-01",
                actor_role="planner",
            ),
        )
        assert any(event.event_type == "graph_patch_accepted" for event in skeleton.events)
        position = skeleton.projection_position
        projection = await controller.read_projection(run_id)
        assert node_states_view(projection)["worker-discovery"] == "planned"
        assert node_states_view(projection)["verifier-plan"] == "planned"
        assert node_states_view(projection)["planner-successor"] == "planned"
        assert not input_bindings_view(projection).get("verifier-plan", {}).get("semantic_artifact")
        assert (
            not input_bindings_view(projection)
            .get("planner-successor", {})
            .get("verification_report")
        )
        assignment_expectations = {
            "worker-discovery": ("discovery_worker", "gpt-5.6-luna", "summarizer"),
            "verifier-plan": ("verifier", "gpt-5.6-sol", "coder"),
            "planner-successor": ("successor_planner", "gpt-5.6-luna", "architect"),
        }
        planner_assignment = node_payload_view(projection, "planner-s-01")
        assert planner_assignment is not None
        for node_id, (role, model, profile) in assignment_expectations.items():
            assigned = node_payload_view(projection, node_id)
            assert assigned is not None
            assert assigned["reliable_plan_assignment_role"] == role
            assert assigned["runner_model_override"] == model
            assert assigned["profile"] == profile
            assert assigned["reliable_plan_selected_runner_type"] == "codex_server"
            assert (
                assigned["reliable_plan_assignment_carrier"]
                == (planner_assignment["reliable_plan_assignment_carrier"])
            )

        async def lease(node_id: str) -> tuple[int, dict[str, object]]:
            nonlocal position
            scheduled = await controller.handle_command(
                run_id,
                position,
                "schedule_tick",
                {
                    "max_grants": 1,
                    "lease_seconds": 60,
                    "base_snapshot_id": "baseline",
                    "priorities": {node_id: 100},
                },
            )
            grant = next(
                event.payload
                for event in scheduled.events
                if event.event_type == "lease_granted" and event.payload.get("node_id") == node_id
            )
            if node_id == "verifier-plan":
                ready_index = next(
                    index
                    for index, event in enumerate(scheduled.events)
                    if event.event_type == "node_state_changed"
                    and event.payload.get("node_id") == node_id
                    and event.payload.get("new_state") == "ready"
                )
                lease_index = next(
                    index
                    for index, event in enumerate(scheduled.events)
                    if event.event_type == "lease_granted"
                    and event.payload.get("node_id") == node_id
                )
                assert ready_index < lease_index
            acknowledged = await controller.handle_command(
                run_id,
                scheduled.projection_position,
                "acknowledge_start",
                {
                    "node_id": node_id,
                    "lease_id": grant["lease_id"],
                    "lease_generation": grant["generation"],
                    "execution_id": grant["execution_id"],
                },
            )
            position = acknowledged.projection_position
            return position, grant

        async def callback(grant: dict[str, object], record: dict[str, object]) -> None:
            nonlocal position
            result = await controller.handle_command(
                run_id,
                position,
                "submit_callback",
                {
                    "node_id": grant["node_id"],
                    "execution_id": grant["execution_id"],
                    "lease_id": grant["lease_id"],
                    "lease_generation": grant["generation"],
                    "base_snapshot_id": grant["base_snapshot_id"],
                    "observed_graph_position": position,
                    "idempotency_key": f"callback-{grant['node_id']}-{outcome}",
                    "payload": {"output_records": [record]},
                    "complete_node": True,
                    "new_state": "completed",
                },
            )
            assert result.events[0].event_type == "callback_accepted", result.events
            position = result.projection_position

        discovery_scheduled = await controller.handle_command(
            run_id,
            position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {"worker-discovery": 100},
            },
        )
        discovery_dispatch = next(
            event
            for event in discovery_scheduled.events
            if event.event_type == "agent_dispatch_requested"
            and event.payload.get("node_id") == "worker-discovery"
        )
        position = discovery_scheduled.projection_position
        worktree = tmp_path / f"joined-codex-{arm_id}"
        _init_git_repo(worktree)
        semantic_content = {
            "summary": "x" * 28_000,
            "batches": [
                {
                    "batch_id": "batch-1",
                    "objective": "Implement batch 1.",
                    "acceptance": ["batch 1 passes"],
                }
            ],
        }
        rejected_snapshots: list[dict[str, object]] = []
        staged_fault_snapshots: list[dict[str, object]] = []

        async def capture_rejected_atomicity() -> None:
            projection = await controller.read_projection(run_id)
            async with sessions() as session:
                events = await GraphEventStore(session).read_bounded_runtime_events(run_id)
            records = [
                record
                for record in output_record_payloads_view(projection).values()
                if record.producer_node_id == "worker-discovery"
            ]
            rejected_snapshots.append(
                {
                    "record_count": len(records),
                    "discovery_state": node_states_view(projection)["worker-discovery"],
                    "verifier_state": node_states_view(projection)["verifier-plan"],
                    "active_discovery_leases": sum(
                        1
                        for item in leases_view(projection).values()
                        if item.node_id == "worker-discovery" and item.state == "active"
                    ),
                    "accepted_output_events": sum(
                        1
                        for event in events
                        if event.event_type == "output_record_accepted"
                        and event.payload.get("producer_node_id") == "worker-discovery"
                    ),
                    "discovery_completed_events": sum(
                        1
                        for event in events
                        if event.event_type == "node_state_changed"
                        and event.payload.get("node_id") == "worker-discovery"
                        and event.payload.get("new_state") == "completed"
                    ),
                    "verifier_ready_events": sum(
                        1
                        for event in events
                        if event.event_type == "node_state_changed"
                        and event.payload.get("node_id") == "verifier-plan"
                        and event.payload.get("new_state") == "ready"
                    ),
                    "discovery_lease_released_events": sum(
                        1
                        for event in events
                        if event.event_type == "lease_released"
                        and event.payload.get("node_id") == "worker-discovery"
                    ),
                }
            )

        artifact_root = tmp_path / f"joined-artifacts-{outcome}-{staged_payload_fault or 'ok'}"
        artifact_store = FilesystemArtifactStore(artifact_root)

        async def fault_staged_callback_payload() -> None:
            projection = await controller.read_projection(run_id)
            attempt = next(iter(execution_attempts_view(projection).values()))
            assert attempt.state == "submission_staged"
            assert attempt.payload_ref is not None
            ref = attempt.payload_ref
            if staged_payload_fault == "missing":
                await artifact_store.delete(ref)
            elif staged_payload_fault == "corrupt":
                digest = ref.content_hash.removeprefix("sha256:")
                blob_path = artifact_root / "sha256" / digest[:2] / digest[2:]
                blob_path.write_bytes(b"!" * ref.size_bytes)
            fault_projection = await controller.read_projection(run_id)
            async with sessions() as session:
                fault_events = await GraphEventStore(session).read_bounded_runtime_events(run_id)
            staged_fault_snapshots.append(
                {
                    "semantic_outputs": sum(
                        1
                        for event in fault_events
                        if event.event_type == "output_record_accepted"
                        and event.payload.get("producer_node_id") == "worker-discovery"
                        and event.payload.get("record_type") == "semantic_artifact"
                    ),
                    "discovery_completed": sum(
                        1
                        for event in fault_events
                        if event.event_type == "node_state_changed"
                        and event.payload.get("node_id") == "worker-discovery"
                        and event.payload.get("new_state") == "completed"
                    ),
                    "verifier_state": node_states_view(fault_projection)["verifier-plan"],
                    "verifier_ready": "verifier-plan" in ready_nodes_view(fault_projection),
                    "verifier_binding": bool(
                        input_bindings_view(fault_projection)
                        .get("verifier-plan", {})
                        .get("semantic_artifact")
                    ),
                    "verifier_active_leases": sum(
                        1
                        for lease in leases_view(fault_projection).values()
                        if lease.node_id == "verifier-plan" and lease.state == "active"
                    ),
                    "discovery_active_leases": sum(
                        1
                        for lease in leases_view(fault_projection).values()
                        if lease.node_id == "worker-discovery" and lease.state == "active"
                    ),
                    "discovery_lease_releases": sum(
                        1
                        for event in fault_events
                        if event.event_type == "lease_released"
                        and event.payload.get("node_id") == "worker-discovery"
                    ),
                }
            )

        transport = _InjectedCodexTransport(
            _codex_messages(semantic_content),
            on_failed_tool_response=capture_rejected_atomicity,
            on_successful_tool_response=(
                fault_staged_callback_payload if staged_payload_fault is not None else None
            ),
        )
        agent = CodexServerAgent(api_key=None, _transport=transport, _environ={})
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            _SingleCodexFactory(agent),
            worktree_path=worktree,
            artifact_store=artifact_store,
        )
        dispatch_item = OutboxItem(
            outbox_id=0,
            event_id=discovery_dispatch.event_id,
            run_id=run_id,
            kind="agent_dispatch",
            payload={
                "event_id": discovery_dispatch.event_id,
                "run_id": run_id,
                "classification": "agent_dispatch_pending",
                **discovery_dispatch.payload,
            },
            status="pending",
            attempts=0,
            created_at=clock.now(),
            updated_at=clock.now(),
            next_attempt_at=None,
            last_error=None,
        )
        await executor.dispatch(dispatch_item)
        await executor.wait_for_all()
        position = await controller.current_position(run_id)

        assert (
            rejected_snapshots
            == [
                {
                    "record_count": 0,
                    "discovery_state": "running",
                    "verifier_state": "planned",
                    "active_discovery_leases": 1,
                    "accepted_output_events": 0,
                    "discovery_completed_events": 0,
                    "verifier_ready_events": 0,
                    "discovery_lease_released_events": 0,
                }
            ]
            * 2
        )
        if staged_payload_fault is not None:
            assert staged_fault_snapshots == [
                {
                    "semantic_outputs": 0,
                    "discovery_completed": 0,
                    "verifier_state": "planned",
                    "verifier_ready": False,
                    "verifier_binding": False,
                    "verifier_active_leases": 0,
                    "discovery_active_leases": 1,
                    "discovery_lease_releases": 0,
                }
            ]
            projection = await controller.read_projection(run_id)
            async with sessions() as session:
                graph_events = await GraphEventStore(session).read_bounded_runtime_events(run_id)
            assert not any(
                event.event_type == "output_record_accepted"
                and event.payload.get("producer_node_id") == "worker-discovery"
                and event.payload.get("record_type") == "semantic_artifact"
                for event in graph_events
            )
            assert not any(
                event.event_type == "node_state_changed"
                and event.payload.get("node_id") == "worker-discovery"
                and event.payload.get("new_state") == "completed"
                for event in graph_events
            )
            assert node_states_view(projection)["worker-discovery"] != "completed"
            assert node_states_view(projection)["verifier-plan"] == "planned"
            assert "verifier-plan" not in ready_nodes_view(projection)
            assert (
                not input_bindings_view(projection)
                .get("verifier-plan", {})
                .get("semantic_artifact")
            )
            assert not any(
                event.event_type == "node_state_changed"
                and event.payload.get("node_id") == "verifier-plan"
                and event.payload.get("new_state") == "ready"
                for event in graph_events
            )
            assert not any(
                lease.node_id == "verifier-plan" and lease.state == "active"
                for lease in leases_view(projection).values()
            )
            assert not any(
                event.event_type == "lease_released"
                and event.payload.get("node_id") == "worker-discovery"
                for event in graph_events
            )
            return controller, engine, position, run_id
        tool_responses = {
            message["id"]: message["result"]
            for message in transport.sent
            if message.get("id") in {10, 11, 12}
        }
        assert tool_responses[10]["success"] is False
        assert (
            "node worker-discovery submit missing required output port semantic_artifact; "
            "expected schema=SemanticArtifact, semantic identity="
            "reliable-plan-implementation-plan@1" in tool_responses[10]["contentItems"][0]["text"]
        )
        assert "content validation failed" in tool_responses[11]["contentItems"][0]["text"]
        assert tool_responses[12]["success"] is True
        thread_start = next(
            message for message in transport.sent if message.get("method") == "thread/start"
        )
        submit_tool = next(
            tool for tool in thread_start["params"]["dynamicTools"] if tool["name"] == "submit"
        )
        assert submit_tool["inputSchema"]["properties"]["outputs"]["required"] == [
            "semantic_artifact"
        ]

        projection = await controller.read_projection(run_id)
        semantic_record = next(
            record
            for record in output_record_payloads_view(projection).values()
            if record.producer_node_id == "worker-discovery" and record.port == "semantic_artifact"
        )
        assert node_states_view(projection)["worker-discovery"] == "completed"
        assert node_states_view(projection)["verifier-plan"] in {"planned", "ready"}
        assert input_bindings_view(projection)["verifier-plan"]["semantic_artifact"]
        assert not any(
            lease.node_id == "worker-discovery" and lease.state == "active"
            for lease in leases_view(projection).values()
        )
        async with sessions() as session:
            store = GraphEventStore(session)
            graph_events = await store.read_bounded_runtime_events(run_id)
            projection_events = await store.read_run_projection(run_id)
        canonical_content_bytes = json.dumps(
            semantic_content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert len(canonical_content_bytes) >= 28_018
        assert graph_events
        assert all(
            len(event.model_dump_json().encode()) <= MAX_EVENT_ENVELOPE_BYTES
            for event in graph_events
        )
        accepted_event = next(
            event
            for event in graph_events
            if event.event_type == "output_record_accepted"
            and event.payload.get("record_id") == semantic_record.record_id
        )
        assert accepted_event.payload["value"]["content"] == semantic_content
        assert accepted_event.payload["value"]["schema_id"] == ("reliable-plan-implementation-plan")
        assert accepted_event.payload["value"]["schema_version"] == 1
        assert accepted_event.payload["producer_node_id"] == "worker-discovery"
        assert accepted_event.payload["producer_port"] == "semantic_artifact"
        assert accepted_event.payload["port"] == "semantic_artifact"
        assert accepted_event.payload["payload"] == {
            "semantic_artifact_value_owner": "event.payload.value",
            "canonical_value_sha256": (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        accepted_event.payload["value"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
            ),
            "canonical_value_size_bytes": len(
                json.dumps(
                    accepted_event.payload["value"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ),
        }
        replayed = build_projection(projection_events)
        replayed_record = output_record_payloads_view(replayed)[semantic_record.record_id]
        assert replayed_record == semantic_record

        split_position = accepted_event.position
        before_tail_events = [
            event for event in projection_events if event.position <= split_position
        ]
        async with sessions() as session:
            store = GraphEventStore(session)
            await store.persist_projection_snapshot(
                run_id,
                build_projection(before_tail_events),
                split_position,
            )
            await session.commit()
        async with sessions() as session:
            checkpoint_replayed, tail, checkpoint_position = await GraphEventStore(
                session
            ).load_projection_with_tail(run_id)
        assert tail
        assert checkpoint_position == graph_events[-1].position
        assert output_record_payloads_view(checkpoint_replayed)[semantic_record.record_id] == (
            semantic_record
        )
        assert not any(
            event.event_type
            in {"runner_recovery_requested", "agent_died", "runtime_retry_scheduled"}
            for event in graph_events
        )
        assert (
            not input_bindings_view(projection)
            .get("planner-successor", {})
            .get("verification_report")
        )

        _, verifier_lease = await lease("verifier-plan")
        await callback(
            verifier_lease,
            {
                "record_id": f"verification-{outcome}",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-plan",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": semantic_record.record_id,
                "task_region_id": "plan-verification",
                "outcome": outcome,
                "value": {
                    "outcome": outcome,
                    "grades": [
                        {
                            "requirement_id": "dynamic_feature_acceptance",
                            "grade": "grade-A" if outcome == "passed" else "grade-C",
                            "reason": "independent plan review",
                        }
                    ],
                },
            },
        )
        return controller, engine, position, run_id

    for staged_payload_fault in ("missing", "corrupt"):
        fault_controller, fault_engine, _, _ = await run_arm(
            "passed",
            staged_payload_fault=staged_payload_fault,
        )
        del fault_controller
        await fault_engine.dispose()

    failed_controller, failed_engine, failed_position, failed_run_id = await run_arm("failed")
    try:
        failed_projection = await failed_controller.read_projection(str(failed_run_id))
        assert (
            not input_bindings_view(failed_projection)
            .get("planner-successor", {})
            .get("verification_report")
        )
        assert not any(
            kind == "worker" and node_id != "worker-discovery"
            for node_id, kind in node_kinds_view(failed_projection).items()
        )
        assert all(lease.state != "active" for lease in leases_view(failed_projection).values())
    finally:
        await failed_engine.dispose()

    passed_controller, passed_engine, position, passed_run_id = await run_arm("passed")
    try:
        passed_projection = await passed_controller.read_projection(str(passed_run_id))
        assert (
            input_bindings_view(passed_projection)
            .get("planner-successor", {})
            .get("verification_report")
        ), {node_id: state for node_id, state in node_states_view(passed_projection).items()}
        scheduled_successor = await passed_controller.handle_command(
            str(passed_run_id),
            position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {"planner-successor": 100},
            },
        )
        assert any(
            event.event_type == "lease_granted"
            and event.payload.get("node_id") == "planner-successor"
            for event in scheduled_successor.events
        )
        effectful = await passed_controller.handle_command(
            str(passed_run_id),
            scheduled_successor.projection_position,
            "submit_patch",
            {
                "patch_id": "first-effectful-batch",
                "base_graph_position": scheduled_successor.projection_position,
                "macro_invocations": [
                    {
                        "macro": "create_effectful_batch",
                        "args": {
                            "region_id": "region-batch-1",
                            "batch_id": "batch-1",
                            "plan_source_node_id": "worker-discovery",
                            "plan_verification_source_node_id": "verifier-plan",
                            "semantic_schema_id": "reliable-plan-implementation-plan",
                            "semantic_schema_version": 1,
                            "objective": "Implement batch 1.",
                            "acceptance": ["batch 1 passes"],
                            "requirement_source_node_ids": [
                                "requirement-dynamic-feature-acceptance"
                            ],
                            "checks": [
                                {
                                    "check_id": "check-batch-1",
                                    "command_binding": "dynamic_feature_hidden_oracle",
                                }
                            ],
                            "rubric": ["batch 1 passes"],
                            "planning_horizon": 1,
                        },
                    }
                ],
            },
            context=PatchCommandContext(
                run_id=str(passed_run_id),
                current_graph_position=scheduled_successor.projection_position,
                proposed_by_node_id="planner-successor",
                actor_role="planner",
            ),
        )
        assert any(event.event_type == "graph_patch_accepted" for event in effectful.events)
        effectful_projection = await passed_controller.read_projection(str(passed_run_id))
        effectful_ids = {
            node_id
            for node_id, kind in node_kinds_view(effectful_projection).items()
            if kind == "worker" and node_id != "worker-discovery"
        }
        assert effectful_ids
        effectful_schedule = await passed_controller.handle_command(
            str(passed_run_id),
            effectful.projection_position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {next(iter(effectful_ids)): 100},
            },
        )
        assert any(
            event.event_type == "lease_granted" and event.payload.get("node_id") in effectful_ids
            for event in effectful_schedule.events
        )
    finally:
        await passed_engine.dispose()


@pytest.mark.asyncio
async def test_real_appeal_dispatch_context_and_callback_accept_recovery_plan(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "appeal-product-path.db")
    sessions = create_session_factory(engine)
    await init_db(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    run_id = "reliable-plan-real-appeal"
    make_event = event_factory(run_id, "seed_compiled_events", clock, ids)
    try:
        seeded = await controller.handle_command(
            run_id,
            0,
            "seed_compiled_events",
            {
                "events": [
                    make_event(
                        "node_created",
                        {
                            "node_id": "verifier-plan",
                            "kind": "verifier",
                            "role": "verifier",
                            "state": "blocked",
                        },
                    )
                ]
            },
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        appealed = await controller.handle_command(
            run_id,
            started.projection_position,
            "raise_appeal",
            {"node_id": "verifier-plan", "appeal_type": "invalid_test"},
            context=GraphCommandContext(
                run_id=run_id,
                current_graph_position=started.projection_position,
            ),
        )
        oversight = next(
            event.payload for event in appealed.events if event.event_type == "node_created"
        )
        oversight_id = str(oversight["node_id"])
        scheduled = await controller.handle_command(
            run_id,
            appealed.projection_position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {oversight_id: 100},
            },
        )
        dispatch_item = next(
            item
            for item in scheduled.outbox_items
            if item.kind == "agent_dispatch" and item.payload.get("node_id") == oversight_id
        )
        dispatch = await assemble_graph_dispatch_context(
            sessions, dispatch_item, worktree_path=str(tmp_path)
        )
        assert dispatch.node_kind == "oversight"
        assert dispatch.node_payload["outputs"] == [
            {
                "port": "recovery_plan",
                "direction": "output",
                "schema": "RecoveryPlan",
                "required": True,
            }
        ]
        acknowledged = await controller.handle_command(
            run_id,
            scheduled.projection_position,
            "acknowledge_start",
            {
                "node_id": oversight_id,
                "lease_id": dispatch.lease_id,
                "lease_generation": dispatch.lease_generation,
                "execution_id": dispatch.execution_id,
            },
        )
        record_id = "appeal-recovery-plan"
        callback = await controller.handle_command(
            run_id,
            acknowledged.projection_position,
            "submit_callback",
            {
                "node_id": oversight_id,
                "execution_id": dispatch.execution_id,
                "lease_id": dispatch.lease_id,
                "lease_generation": dispatch.lease_generation,
                "base_snapshot_id": dispatch.base_snapshot_id,
                "observed_graph_position": acknowledged.projection_position,
                "idempotency_key": "appeal-recovery-plan-callback",
                "payload": {
                    "output_records": [
                        {
                            "record_id": record_id,
                            "record_kind": "output",
                            "record_type": "recovery_plan",
                            "producer_node_id": oversight_id,
                            "port": "recovery_plan",
                            "schema": "RecoveryPlan",
                            "value": {
                                "action": "pause",
                                "responsible_actor": "oversight",
                                "graph_changes": [],
                                "reason": "bounded appeal decision",
                                "attempt_number": oversight["attempt_number"],
                                "max_attempts": oversight["max_attempts"],
                            },
                        }
                    ]
                },
                "complete_node": True,
                "new_state": "completed",
            },
        )
        assert callback.events[0].event_type == "callback_accepted"
        assert any(
            event.event_type == "output_record_accepted"
            and event.payload.get("record_id") == record_id
            and event.payload.get("record_type") == "recovery_plan"
            for event in callback.events
        ), [(event.event_type, event.payload) for event in callback.events]
        projection = await controller.read_projection(run_id)
        assert output_record_payloads_view(projection)[record_id].record_type == "recovery_plan"
        assert all(lease.state != "active" for lease in leases_view(projection).values())
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("historical_max_attempts", ["omitted", 0])
async def test_reconstructed_controller_honors_durable_three_attempt_retry_budget(
    tmp_path: Path,
    historical_max_attempts: str | int,
) -> None:
    """The persistent controller boundary survives the same reconstruction as a driver restart.

    A real GraphRunDriver needs runner/worktree orchestration to manufacture a
    runtime death. The durable decision is made below the driver by the public
    controller command, so recreating that controller before every attempt is
    the closest deterministic file-backed proof of the restart invariant.
    """
    suffix = str(historical_max_attempts)
    engine = create_engine(tmp_path / f"durable-retry-reconstruction-{suffix}.db")
    sessions = create_session_factory(engine)
    await init_db(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    run_id = f"durable-retry-reconstruction-{suffix}"
    make_event = event_factory(run_id, "seed_compiled_events", clock, ids)
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    health_record = {
        "record_id": "health-check-passed",
        "record_kind": "output",
        "record_type": "check_result",
        "producer_node_id": "health-check",
        "port": "check_result",
        "schema": "CheckResult",
        "candidate_id": "runtime-health",
        "task_region_id": "region-retry",
        "attempt_number": 1,
        "value": {
            "status": "passed",
            "classification": "passed",
            "command_id": "runtime-health",
            "command_text": "runner health probe",
            "command": {"argv": ["true"]},
            "worktree_path": "/work",
            "base_snapshot_id": "baseline",
            "execution_id": "health-exec",
            "exit_code": 0,
            "duration_ms": 1,
            "stdout_tail": "healthy",
            "stderr_tail": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timeout_seconds": 1.0,
            "environment_policy": {},
        },
        "evaluated_record_ids": [],
    }
    try:
        worker_node: dict[str, object] = {
            "node_id": "worker-retry",
            "kind": "worker",
            "role": "builder",
            "state": "planned",
            "attempt_number": 1,
            "objective": "Exercise bounded runtime recovery.",
            "access_mode": "read_only",
            "acceptance": ["retry is bounded"],
        }
        if historical_max_attempts != "omitted":
            worker_node["max_attempts"] = historical_max_attempts
        seeded = await controller.handle_command(
            run_id,
            0,
            "seed_compiled_events",
            {
                "events": [
                    make_event(
                        "node_created",
                        {"node_id": "health-check", "kind": "check", "state": "completed"},
                    ),
                    make_event("node_created", worker_node),
                    make_event("output_record_accepted", health_record),
                ]
            },
        )
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        position = started.projection_position

        lease_ids: list[str] = []
        retry_events = []
        exhausted_events = []
        for attempt in range(1, 4):
            # Recreate all process-local controller state before every drive.
            controller = GraphController(sessions, FakeClock(), ids, auto_dispatch=False)
            scheduled = await controller.handle_command(
                run_id,
                position,
                "schedule_tick",
                {
                    "max_grants": 1,
                    "lease_seconds": 60,
                    "base_snapshot_id": "baseline",
                    "priorities": {"worker-retry": 100},
                },
            )
            grant = next(
                event.payload
                for event in scheduled.events
                if event.event_type == "lease_granted"
                and event.payload.get("node_id") == "worker-retry"
            )
            lease_ids.append(str(grant["lease_id"]))
            died = await controller.handle_command(
                run_id,
                scheduled.projection_position,
                "agent_died",
                {
                    "lease_id": grant["lease_id"],
                    "execution_id": grant["execution_id"],
                    "reason": "callback contract conflict",
                    "health_evidence_record_id": "health-check-passed",
                },
            )
            retry_events.extend(
                event for event in died.events if event.event_type == "runtime_retry_scheduled"
            )
            exhausted_events.extend(
                event
                for event in died.events
                if event.event_type == "node_state_changed"
                and event.payload.get("trigger") == "max_attempts_exhausted"
            )
            position = died.projection_position
            if attempt < 3:
                assert len(retry_events) == attempt

        reconstructed = GraphController(sessions, FakeClock(), ids, auto_dispatch=False)
        projection = await reconstructed.read_projection(run_id)
        assert len(lease_ids) == 3
        assert len(set(lease_ids)) == 3
        assert len(retry_events) == 2
        assert len(exhausted_events) == 1
        assert node_attempts_view(projection)["worker-retry"] == 3
        assert runtime_retry_counts_view(projection)["worker-retry"] == 2
        assert node_states_view(projection)["worker-retry"] == "failed"
        assert all(lease.state != "active" for lease in leases_view(projection).values())
        fourth = await reconstructed.handle_command(
            run_id,
            position,
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {"worker-retry": 100},
            },
        )
        assert not any(event.event_type == "lease_granted" for event in fourth.events)
        async with sessions() as session:
            events = await GraphEventStore(session).read_run(run_id)
        assert sum(event.event_type == "lease_granted" for event in events) == 3
        assert sum(event.event_type == "runtime_retry_scheduled" for event in events) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_oversized_semantic_persistence_exhaustion_is_publicly_observable(
    tmp_path: Path,
) -> None:
    """FR-7: the public readbacks retain the upstream persistence root cause.

    The application, driver, controller, recovery outbox, workflow event store,
    and API all share a disposable file-backed SQLite database.  This is the
    production transaction topology; unlike the suite's shared in-memory
    StaticPool fixture, it permits the driver's concurrent graph and activity
    transactions without sharing one connection-level transaction.
    """
    db_path = tmp_path / "fr7-public-readback.db"
    app = create_app(db_path=str(db_path), routine_dirs=[])
    await init_db(app.state.engine)
    sessions = app.state.session_factory
    run_id = "fr7-oversized-semantic-exhaustion"
    worktree = tmp_path / "fr7-worktree"
    _init_git_repo(worktree)
    routine_path = Path("routines/dynamic-graph-feature/routine.yaml")
    routine = load_routine_from_path(routine_path)
    config = {
        "feature_spec_path": "docs/spec.md",
        "acceptance_command": "uv run pytest",
    }
    run = create_run_from_routine(
        routine,
        repo_name=worktree.name,
        source_branch="main",
        config=config,
    )
    run.id = run_id
    run.execution_mode = "graph"
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.worktree_path = str(worktree)
    run.agent_runner_type = AgentRunnerType.CODEX_SERVER
    async with sessions() as session:
        await WorkflowService(session).create_run(run)

    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    compiled = compile_routine(
        routine,
        clock,
        ids,
        run_id=run_id,
        source_path=str(routine_path),
        run_config={**config, "reliable_plan_one_horizon_authorized": True},
    )
    # The FR-7 scenario starts after the production planner has installed its
    # discovery horizon.  Marking that already-finished planner terminal in the
    # seed avoids introducing a second runner into this single-failure proof.
    compiled = [
        event.model_copy(update={"payload": {**event.payload, "state": "completed"}})
        if event.event_type == "node_created" and event.payload.get("node_id") == "planner-s-01"
        else event
        for event in compiled
    ]
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": compiled},
    )
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    patched = await controller.handle_command(
        run_id,
        started.projection_position,
        "submit_patch",
        {
            "patch_id": "fr7-discovery-horizon",
            "base_graph_position": started.projection_position,
            "macro_invocations": [
                {
                    "macro": "create_discovery_region",
                    "args": {
                        "region_id": "discovery",
                        "worker_id": "worker-discovery",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "objective": "Discover the implementation plan.",
                        "acceptance": ["plan is complete"],
                        "requirement_source_node_ids": ["requirement-dynamic-feature-acceptance"],
                    },
                },
                {
                    "macro": "create_plan_verification",
                    "args": {
                        "region_id": "plan-verification",
                        "verifier_id": "verifier-plan",
                        "artifact_source_node_id": "worker-discovery",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "objective": "Independently verify the plan.",
                        "acceptance": ["requirements are covered"],
                        "rubric": ["dynamic_feature_acceptance maps to batch-1"],
                        "requirement_source_node_ids": ["requirement-dynamic-feature-acceptance"],
                    },
                },
                {
                    "macro": "create_successor_planner",
                    "args": {
                        "region_id": "successor",
                        "node_id": "planner-successor",
                        "evidence_source_node_id": "verifier-plan",
                        "evidence_source_port": "verification_report",
                        "planning_horizon": 1,
                    },
                },
            ],
        },
        context=PatchCommandContext(
            run_id=run_id,
            current_graph_position=started.projection_position,
            proposed_by_node_id="planner-s-01",
            actor_role="planner",
        ),
    )
    assert any(event.event_type == "graph_patch_accepted" for event in patched.events)

    agent = _OversizedSemanticSubmitAgent()
    fr7_artifact_store = FilesystemArtifactStore(tmp_path / "fr7-artifacts")

    async def create_service(session: Any) -> WorkflowService:
        return WorkflowService(session)

    def runtime_builder(
        session_factory_arg: Any,
        clock_arg: Any,
        id_gen_arg: Any,
        *,
        worktree_path: str | Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
        artifact_store: Any,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        del worktree_path, runner_type, runner_config, artifact_store
        runtime_controller = GraphController(
            session_factory_arg,
            clock_arg,
            id_gen_arg,
            auto_dispatch=False,
        )
        return runtime_controller, GraphDispatchExecutor(
            session_factory_arg,
            runtime_controller,
            _SingleCodexFactory(agent),
            worktree_path=worktree,
            artifact_store=fr7_artifact_store,
        )

    driver = GraphRunDriver(
        sessions,
        create_service,
        clock=clock,
        id_gen=ids,
        runtime_builder=runtime_builder,
    )
    try:
        outcome = await driver.run(run_id)
        assert outcome.completed is False
        assert agent.attempts == 3

        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            run_response = await client.get(f"/api/runs/{run_id}")
            health_response = await client.get(f"/api/runs/{run_id}/graph/health")
            activity_response = await client.get(
                f"/api/runs/{run_id}/activity?limit=100&payload_mode=full"
            )
            scheduler_response = await client.get(f"/api/runs/{run_id}/graph/scheduler")
            graph_events: list[dict[str, Any]] = []
            from_position = 0
            while True:
                events_response = await client.get(
                    f"/api/runs/{run_id}/graph/events",
                    params={
                        "from_position": from_position,
                        "limit": 100,
                        "payload_mode": "full",
                    },
                )
                assert events_response.status_code == 200, events_response.text
                graph_events.extend(events_response.json())
                if events_response.headers["X-Has-More"] != "true":
                    break
                from_position = int(events_response.headers["X-Next-Position"])
        assert run_response.status_code == 200, run_response.text
        assert health_response.status_code == 200, health_response.text
        assert activity_response.status_code == 200, activity_response.text
        assert scheduler_response.status_code == 200, scheduler_response.text

        run_json = run_response.json()
        assert run_json["status"] == RunStatus.PAUSED.value
        assert run_json["pause_reason"] == "graph_blocked"
        assert "worker-discovery" in run_json["last_error"]
        assert "maximum is 32768 bytes" in run_json["last_error"]
        assert "verification_report" not in run_json["last_error"]

        health_json = health_response.json()
        assert health_json["status"] == "blocked"
        assert health_json["counts"]["failed_nodes"] == 1
        assert health_json["failed_nodes"] == [
            {
                "node_id": "worker-discovery",
                "reason": health_json["failed_nodes"][0]["reason"],
            }
        ]
        assert "maximum is 32768 bytes" in health_json["failed_nodes"][0]["reason"]

        activity = activity_response.json()["events"]
        correlated_errors = [
            event
            for event in activity
            if event["event_type"] == "agent_error"
            and event["payload"].get("node_id") == "worker-discovery"
            and event["payload"].get("error_type") == "GraphEventEnvelopeTooLargeError"
        ]
        assert len(correlated_errors) == 3
        assert all(
            "maximum is 32768 bytes" in event["payload"]["error_message"]
            for event in correlated_errors
        )

        assert sum(event["event_type"] == "runtime_retry_scheduled" for event in graph_events) == 2
        assert scheduler_response.json()["leases"] == {"active": [], "suspended": []}
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_run_api_consumes_server_qualification_once_and_rejects_forgery(
    _shared_app_fixture,
    git_repo: Path,
) -> None:
    client: AsyncClient = _shared_app_fixture[0]
    issued = await client.post("/api/runs/reliable-plan-qualification")
    assert issued.status_code == 201, issued.text
    reference = issued.json()["reference"]
    evaluation = ReliablePlanEvaluationConfig.model_validate_json(FIXTURE.read_text())
    base_request = {
        "routine_embedded": {
            "id": "reliable-plan-api",
            "name": "Reliable plan API",
            "execution_mode": "graph",
            "planner_generation_budget": 2,
            "semantic_artifact_schemas": [
                {
                    "schema_id": "reliable-plan-implementation-plan",
                    "version": 1,
                    "semantic_role": "implementation_plan",
                    "json_schema": {
                        "type": "object",
                        "required": ["batches"],
                        "properties": {"batches": {"type": "array"}},
                    },
                }
            ],
            "steps": [
                {
                    "id": "plan",
                    "kind": "planner",
                    "title": "Plan",
                    "tasks": [
                        {
                            "id": "scope",
                            "title": "Scope",
                            "requirements": [
                                {"id": "REQ-1", "desc": "Implement the qualified scope"}
                            ],
                        }
                    ],
                }
            ],
        },
        "repo_name": git_repo.name,
        "branch": "main",
        "execution_mode": "graph",
        "agent_runner_type": "codex_server",
        "config": {
            "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
            "reliable_plan_model_assignments": evaluation.luna_arm.model_dump(mode="json"),
        },
    }

    mismatched = await client.post(
        "/api/runs",
        json={
            **base_request,
            "agent_runner_type": "cli_subprocess",
            "reliable_plan_qualification_reference": reference,
        },
    )
    assert mismatched.status_code == 422
    assert mismatched.json()["detail"] == (
        "reliable-plan assignments must match the selected runner"
    )

    # Runner validation happens before grant consumption, so the same grant
    # remains valid for a corrected request.
    accepted = await client.post(
        "/api/runs",
        json={
            **base_request,
            "reliable_plan_qualification_reference": reference,
        },
    )
    assert accepted.status_code == 201, accepted.text
    accepted_body = accepted.json()
    run_id = accepted_body["id"]
    assert accepted_body["config"]["_reliable_plan_authorization"]["reference"] == reference

    app = _shared_app_fixture[4]
    async with app.state.session_factory() as session:
        run = await RunRepository(session).get(run_id)
        facts = await require_reliable_plan_qualification_for_run(
            session,
            run_id=run_id,
            run_config=run.config,
            selected_runner_type=run.agent_runner_type.value,
        )
    seed_config = verified_reliable_plan_seed_config(
        run.config,
        facts,
        selected_runner_type=run.agent_runner_type.value,
    )
    compiled = compile_routine(
        RoutineConfig.model_validate(run.routine_embedded),
        FakeClock(),
        SequentialIdGenerator(),
        run_id=run_id,
        run_config=seed_config,
    )
    planner_created = next(
        event
        for event in compiled
        if event.event_type == "node_created" and event.payload.get("kind") == "planner"
    )
    assert planner_created.payload["reliable_plan_one_horizon_authorized"] is True
    requirement_node_id = "requirement-qualified-scope"

    controller = GraphController(
        app.state.session_factory,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": compiled},
    )
    activated = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    activated = await controller.handle_command(
        run_id,
        activated.projection_position,
        "start",
    )
    first = await controller.handle_command(
        run_id,
        activated.projection_position,
        "submit_patch",
        {
            "patch_id": "authorized-horizon-one",
            "base_graph_position": activated.projection_position,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": requirement_node_id,
                        "kind": "requirement",
                        "role": "requirement",
                        "state": "completed",
                        "outputs": [
                            {
                                "port": "requirement",
                                "direction": "output",
                                "schema": "Requirement",
                            }
                        ],
                    },
                }
            ],
            "macro_invocations": [
                {
                    "macro": "create_discovery_region",
                    "args": {
                        "region_id": "discovery",
                        "worker_id": "worker-discovery",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "objective": "Discover the implementation plan.",
                        "acceptance": ["plan is complete"],
                        "requirement_source_node_ids": [requirement_node_id],
                    },
                },
                {
                    "macro": "create_plan_verification",
                    "args": {
                        "region_id": "plan-verification",
                        "verifier_id": "verifier-plan",
                        "artifact_source_node_id": "worker-discovery",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "objective": "Independently verify the plan.",
                        "acceptance": ["requirements are covered"],
                        "rubric": ["REQ-1 maps to a batch"],
                        "requirement_source_node_ids": [requirement_node_id],
                    },
                },
                {
                    "macro": "create_successor_planner",
                    "args": {
                        "region_id": "successor",
                        "node_id": "planner-successor-one",
                        "evidence_source_node_id": "verifier-plan",
                        "evidence_source_port": "verification_report",
                        "planning_horizon": 1,
                    },
                },
            ],
        },
        context=PatchCommandContext(
            run_id=run_id,
            current_graph_position=activated.projection_position,
            proposed_by_node_id="planner-plan",
            actor_role="planner",
        ),
    )
    assert any(event.event_type == "graph_patch_accepted" for event in first.events)
    successor_created = next(
        event
        for event in first.events
        if event.event_type == "node_created"
        and event.payload.get("node_id") == "planner-successor-one"
    )
    assert successor_created.payload["runner_model_override"] == (
        evaluation.luna_arm.successor_planner.model
    )
    assert successor_created.payload["reliable_plan_one_horizon_authorized"] is True
    assert successor_created.payload["reliable_plan_remaining_horizons"] == 2
    second = await controller.handle_command(
        run_id,
        first.projection_position,
        "submit_patch",
        {
            "patch_id": "copied-horizon-two",
            "base_graph_position": first.projection_position,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "planner-successor-two",
                        "kind": "planner",
                        "role": "planner",
                        "state": "planned",
                        "planning_horizon": 2,
                    },
                }
            ],
        },
        context=PatchCommandContext(
            run_id=run_id,
            current_graph_position=first.projection_position,
            proposed_by_node_id="planner-successor-one",
            actor_role="planner",
        ),
    )
    assert any(
        event.event_type == "graph_patch_rejected"
        and "cannot advance without materializing its bounded effectful batch"
        in event.payload["reason"]
        for event in second.events
    )

    copied = await client.post(
        "/api/runs",
        json={
            **base_request,
            "reliable_plan_qualification_reference": reference,
        },
    )
    assert copied.status_code == 409
    assert "already been consumed" in copied.json()["detail"]

    unknown = await client.post(
        "/api/runs",
        json={
            **base_request,
            "reliable_plan_qualification_reference": "rpq_" + "x" * 43,
        },
    )
    assert unknown.status_code == 422
    assert "unknown reliable-plan qualification reference" in unknown.json()["detail"]

    forged = await client.post(
        "/api/runs",
        json={
            **base_request,
            "config": {
                **base_request["config"],
                "_reliable_plan_authorization": {
                    "reference": "rpq_" + "f" * 43,
                    "evidence_hash": "sha256:" + "0" * 64,
                },
            },
            "reliable_plan_qualification_reference": "rpq_" + "f" * 43,
        },
    )
    assert forged.status_code == 422
    assert forged.json()["detail"] == "reliable-plan authorization is server-owned"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_product_path_runner_is_the_only_all_ten_one_horizon_gate(
    tmp_path: Path,
) -> None:
    config = ReliablePlanEvaluationConfig.model_validate_json(FIXTURE.read_text())
    assert config.qualification is None
    assert config.enable_luna_one_horizon_planning is False
    assert config.one_horizon_authorized is False

    qualification_run = await run_reliable_plan_product_path_scenarios(
        config.scenario_manifest,
        root=tmp_path / "qualification",
    )
    qualification = qualification_run.qualification

    assert qualification.qualified
    assert [result.number for result in qualification.results] == list(range(1, 11))
    assert all(result.product_path_passed for result in qualification.results)
    assert all(result.evidence for result in qualification.results)
    gated = authorize_reliable_plan_one_horizon(
        config,
        qualification_run.projection,
        qualification_run.accepted_receipt_record_id,
    )
    assert gated.one_horizon_authorized
    assert (
        require_reliable_plan_one_horizon_authorization(gated).evidence_hash
        == qualification_run.receipt.evidence_hash
    )
    live_run_config = serialize_authorized_reliable_plan_run_config(gated, gated.luna_arm)
    assert live_run_config == {
        "reliable_plan_skeleton_id": gated.skeleton_id,
        "reliable_plan_model_assignments": gated.luna_arm.model_dump(mode="json"),
    }
    assert {
        "enable_luna_one_horizon_planning",
        "qualification",
        "qualification_receipt",
        "qualification_receipt_record_id",
    }.isdisjoint(live_run_config)
    create_request = CreateRunRequest(
        routine_id="reliable-plan-live",
        repo_name="registered-repository",
        branch="main",
        config=live_run_config,
    )
    assert create_request.config == live_run_config

    gated_payload = config.model_dump(mode="json")
    gated_payload.update(
        qualification=qualification.model_dump(mode="json"),
        enable_luna_one_horizon_planning=True,
    )
    with pytest.raises(ValueError, match="public JSON cannot enable"):
        ReliablePlanEvaluationConfig.model_validate(gated_payload)

    artifact_payload = config.model_dump(mode="json")
    artifact_payload["qualification_receipt"] = qualification_run.receipt.model_dump(mode="json")
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ReliablePlanEvaluationConfig.model_validate(artifact_payload)

    failed_results = list(qualification.results)
    observed = failed_results[-1]
    failed_results[-1] = ReliablePlanScenarioResult(
        **{
            **observed.model_dump(exclude={"product_path_passed"}),
            "passed": False,
            "evidence": ("observed scenario failure",),
        }
    )
    failed_qualification = ReliablePlanSkeletonQualification.from_results(
        config.scenario_manifest,
        tuple(failed_results),
    )
    blocked_payload = config.model_dump(mode="json")
    blocked_payload.update(
        qualification=failed_qualification.model_dump(mode="json"),
        enable_luna_one_horizon_planning=True,
    )
    with pytest.raises(ValueError, match="public JSON cannot enable"):
        ReliablePlanEvaluationConfig.model_validate(json.loads(json.dumps(blocked_payload)))

    arbitrary = config.model_copy(
        update={
            "qualification": qualification,
            "enable_luna_one_horizon_planning": True,
        }
    )
    with pytest.raises(ValueError, match="controller-accepted qualification receipt"):
        require_reliable_plan_one_horizon_authorization(arbitrary)
    with pytest.raises(ValueError, match="controller-accepted qualification receipt"):
        serialize_authorized_reliable_plan_run_config(arbitrary, arbitrary.luna_arm)

    public_round_trip = ReliablePlanEvaluationConfig.model_validate_json(
        gated.model_dump_json(exclude={"enable_luna_one_horizon_planning", "qualification"})
    )
    with pytest.raises(ValueError, match="controller-accepted qualification receipt"):
        serialize_authorized_reliable_plan_run_config(
            public_round_trip,
            public_round_trip.luna_arm,
        )
