"""Prepare or run one isolated reliable-plan successor planner execution.

The default command is deterministic and never opens a model transport.  A paid
Codex execution requires the separate ``paid`` command plus an explicit opt-in.
Both modes use the production graph controller, outbox, dispatch executor, and
runner finalization path around a disposable Git repository and SQLite store.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from examples.recovery import deterministic_lifecycle as lifecycle
from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import AgentRunnerType, load_routine_from_path
from orchestrator.db import GraphOutboxModel, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    FakeClock,
    SequentialIdGenerator,
    StoredArtifactRef,
    edges_view,
    execution_attempts_view,
    leases_view,
    node_payload_view,
    node_states_view,
    non_gap_planner_completion_contract_satisfied,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    ReliablePlanRejectionRecorder,
    RunnerOwnedProcessRegistry,
    StaticGraphAgentFactory,
    capture_source_identity,
    replay_reliable_plan_rejection,
    resolve_orchestrator_source_root,
    seed_run,
)
from orchestrator.runners import (
    AgentRunner,
    CodexDynamicToolReceipt,
    CodexServerAgent,
    ExecutionContext,
    build_dynamic_tool_specs,
)
from orchestrator.state import create_run_from_routine
from orchestrator.workflow import WorkflowService


ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE_PATH = Path(__file__).with_name("deterministic_lifecycle.py")
MODEL = "gpt-5.6-luna"
EFFORT = "medium"
MAX_TIMEOUT_SECONDS = 180.0
MAX_REJECTIONS = 2
MAX_EXECUTIONS = 1
_AGENT_OUTBOX = frozenset({"agent_dispatch"})
_MAINTENANCE_OUTBOX = frozenset({"snapshot_publish", "snapshot_cleanup"})
_FORBIDDEN_RECOVERY_EVENTS = frozenset(
    {
        "agent_died",
        "runner_recovery_requested",
        "runner_recovery_completed",
        "runtime_retry_scheduled",
    }
)


class SuccessorProbeEvidence(BaseModel):
    """Bounded result for one deterministic or explicitly paid successor probe."""

    schema_version: Literal[1] = 1
    status: Literal["passed", "failed", "incomplete", "error"]
    mode: Literal["deterministic", "paid"]
    run_id: str
    model: str
    reasoning_effort: str
    timeout_seconds: float = Field(gt=0, le=MAX_TIMEOUT_SECONDS)
    planner_execution_limit: Literal[1] = MAX_EXECUTIONS
    rejected_proposal_limit: Literal[2] = MAX_REJECTIONS
    source_commit: str
    source_tree: str
    source_dirty: bool
    harness_sha256: str
    lifecycle_helper_sha256: str
    routine_sha256: str
    spec_sha256: str
    oracle_sha256: str
    orchestrator_source_identity: dict[str, Any]
    fixture_commit: str
    fixture_tree: str
    successor_node_id: str
    successor_execution_id: str | None
    successor_prompt_sha256: str
    successor_authority: dict[str, Any]
    phase_node_ids: list[str]
    phase_event_counts: dict[str, int]
    accepted_patch_ids: list[str]
    rejected_patch_ids: list[str]
    rejection_evidence: list[dict[str, Any]]
    dynamic_tool_receipts: list[dict[str, Any]]
    protected_context_ref: dict[str, Any]
    artifact_root: str
    result_path: str
    replayed_rejection_count: int
    execution_count: int
    recorded_execution_attempt_count: int
    downstream_dispatch_count: int
    downstream_active_lease_count: int
    pending_outbox_count: int
    remaining_node_states: dict[str, str]
    completion_contract_satisfied: bool
    topology: dict[str, Any]
    model_duration_ms: int
    usage: dict[str, int]
    cleanup_duration_ms: int
    total_duration_ms: int
    timed_out: bool
    cleanup_unbounded_for_ownership: Literal[True] = True
    owned_process_count_after: int
    fixture_unchanged: bool
    strict_predicates: dict[str, bool]
    incomplete_reason: str | None = None


class SuccessorProbeFailure(RuntimeError):
    """The isolated successor fixture violated a deterministic boundary."""


ProbeRunner = Callable[..., Coroutine[Any, Any, SuccessorProbeEvidence]]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assignments(*, paid: bool) -> dict[str, Any]:
    del paid
    assignments = lifecycle.lifecycle_assignments()
    assignments["arm_id"] = "isolated-successor-planner-probe"
    assignments["successor_planner"] = {
        "runner_type": "codex_server",
        "model": MODEL,
        "profile": "architect",
    }
    return assignments


def _source_identity() -> tuple[str, str, bool]:
    return (
        lifecycle.run_lifecycle_git(ROOT, "rev-parse", "HEAD"),
        lifecycle.run_lifecycle_git(ROOT, "rev-parse", "HEAD^{tree}"),
        bool(lifecycle.run_lifecycle_git(ROOT, "status", "--porcelain", "--untracked-files=no")),
    )


def _rpc_response(request_id: int, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_call(request_id: int, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "item/tool/call",
        "params": {"tool": tool, "arguments": arguments},
    }


class _SuccessorTransport:
    def __init__(
        self,
        oracle: Path,
        *,
        scenario: Literal["accept", "cap", "no_submit", "timeout"],
    ) -> None:
        self.oracle = oracle
        self.scenario: Literal["accept", "cap", "no_submit", "timeout"] = scenario
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.queue.put_nowait(_rpc_response(1, {"userAgent": "successor-probe"}))
        self.queue.put_nowait(
            _rpc_response(
                2,
                {
                    "thread": {
                        "id": "thread-successor-probe",
                        "preview": "",
                        "modelProvider": "openai",
                        "createdAt": 0,
                    }
                },
            )
        )
        self.queue.put_nowait(
            _rpc_response(
                3,
                {
                    "turn": {
                        "id": "turn-successor-probe",
                        "status": "inProgress",
                        "items": [],
                        "error": None,
                    }
                },
            )
        )

    def _valid_args(self) -> dict[str, Any]:
        return {
            "operation_key": "stage3-smoke",
            "scope": "stage3-smoke",
            "objective": "Create stage3-smoke.txt with the required exact bytes.",
            "requirement_ids": ["dynamic_feature_acceptance"],
            "dependencies": [],
            "acceptance": ["the independent Stage 3 oracle passes"],
            "checks": [
                {
                    "name": "stage3 exact-file oracle",
                    "command_definition": {
                        "id": "stage3-exact-file-oracle",
                        "cmd": str(self.oracle),
                    },
                }
            ],
            "rubric": ["Only stage3-smoke.txt changes and its bytes are exact."],
        }

    def _valid_patch(self, patch_id: str, position: int) -> dict[str, Any]:
        return {
            "patch_id": patch_id,
            "base_graph_position": position,
            **self._valid_args(),
        }

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)
        if message.get("method") != "turn/start" or self.scenario == "timeout":
            return
        prompt = str(message["params"]["input"][0]["text"])
        marker = '"current_graph_position":'
        position = int(prompt.split(marker, 1)[1].split(",", 1)[0].strip())
        rejection_count = MAX_REJECTIONS if self.scenario == "cap" else 1
        for index in range(rejection_count):
            rejected = self._valid_patch(f"successor-probe-rejected-{index + 1}", position)
            rejected["dependencies"] = ["not-materialized"]
            self.queue.put_nowait(
                _tool_call(10 + index, "construct_reliable_plan_region", rejected)
            )
        self.queue.put_nowait(
            _tool_call(
                20,
                "construct_reliable_plan_region",
                self._valid_patch(
                    "successor-probe-after-cap"
                    if self.scenario == "cap"
                    else "successor-probe-accepted",
                    position,
                ),
            )
        )
        if self.scenario not in {"cap", "no_submit"}:
            self.queue.put_nowait(_tool_call(21, "submit", {}))
        self.queue.put_nowait(
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {
                    "turn": {
                        "id": "turn-successor-probe",
                        "status": "completed",
                        "items": [],
                        "error": None,
                        "usage": {
                            "inputTokens": 120,
                            "outputTokens": 30,
                            "cachedInputTokens": 20,
                            "reasoningOutputTokens": 5,
                        },
                    }
                },
            }
        )

    async def recv(self) -> dict[str, Any]:
        return await self.queue.get()

    async def close(self) -> None:
        self.closed = True


class _HybridFactory(lifecycle.ScriptedLifecycleFactory):
    def __init__(
        self,
        oracle: Path,
        *,
        scenario: Literal["accept", "cap", "no_submit", "timeout"],
        paid: bool,
        artifact_store: FilesystemArtifactStore,
    ) -> None:
        super().__init__(oracle)
        self.scenario: Literal["accept", "cap", "no_submit", "timeout"] = scenario
        self.paid = paid
        self.successor_context: GraphDispatchContext | None = None
        self.successor_execution_context: ExecutionContext | None = None
        self.dynamic_tool_receipts: list[CodexDynamicToolReceipt] = []
        self.dynamic_tool_receipt_refs: list[StoredArtifactRef] = []
        self.dynamic_tool_receipt_overflow = False
        self._artifact_store = artifact_store
        self.transport: _SuccessorTransport | None = None
        self._paid = StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            {"model": MODEL, "reasoning_effort": EFFORT, "restrictions": "managed"},
            runner_builder=self._build_paid_runner,
        )

    async def _record_dynamic_tool_receipt(self, receipt: CodexDynamicToolReceipt) -> None:
        if len(self.dynamic_tool_receipts) >= 16:
            self.dynamic_tool_receipt_overflow = True
            raise SuccessorProbeFailure("dynamic tool receipt limit exceeded")
        ref = await self._artifact_store.put(
            receipt.model_dump_json().encode(),
            media_type="application/vnd.orchestrator.codex-dynamic-tool-receipt+json",
            encoding="utf-8",
        )
        self.dynamic_tool_receipts.append(receipt)
        self.dynamic_tool_receipt_refs.append(ref)
        if receipt.incomplete:
            raise SuccessorProbeFailure("dynamic tool receipt is incomplete")

    def _build_paid_runner(
        self,
        agent_runner_type: AgentRunnerType,
        agent_runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> AgentRunner:
        del run_id, phase
        if agent_runner_type != AgentRunnerType.CODEX_SERVER:
            raise SuccessorProbeFailure("successor assignment changed runner type")
        return cast(
            AgentRunner,
            CodexServerAgent(
                model=agent_runner_config.get("model"),
                reasoning_effort=agent_runner_config.get("reasoning_effort", EFFORT),
                restrictions=agent_runner_config.get("restrictions", "managed"),
                api_key=None,
                dynamic_tool_receipt_observer=self._record_dynamic_tool_receipt,
            ),
        )

    def preflight(
        self,
        context: GraphDispatchContext,
        execution_context: ExecutionContext,
        *,
        graph_mcp_available: bool,
    ) -> None:
        if context.node_payload.get("semantic_stage") == "successor_planning":
            self.successor_execution_context = execution_context
            if self.paid:
                self._paid.preflight(
                    context,
                    execution_context,
                    graph_mcp_available=graph_mcp_available,
                )
            else:
                super().preflight(
                    context,
                    execution_context,
                    graph_mcp_available=graph_mcp_available,
                )
            return
        super().preflight(
            context,
            execution_context,
            graph_mcp_available=graph_mcp_available,
        )

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        if context.node_payload.get("semantic_stage") != "successor_planning":
            return super().create_runner(context)
        if self.successor_context is not None:
            raise SuccessorProbeFailure("more than one successor execution was created")
        self.dispatch_contexts.append(context)
        self.successor_context = context
        if self.paid:
            return self._paid.create_runner(context)
        self.transport = _SuccessorTransport(self.oracle, scenario=self.scenario)
        return cast(
            AgentRunner,
            CodexServerAgent(
                model=MODEL,
                reasoning_effort=EFFORT,
                restrictions="managed",
                api_key=None,
                _transport=self.transport,
                _environ={},
                dynamic_tool_receipt_observer=self._record_dynamic_tool_receipt,
            ),
        )


@dataclass
class _PreparedProbe:
    run_id: str
    engine: Any
    sessions: Any
    controller: GraphController
    dispatcher: OutboxDispatcher
    executor: GraphDispatchExecutor
    registry: RunnerOwnedProcessRegistry
    factory: _HybridFactory
    worktree: Path
    fixture_commit: str
    fixture_tree: str
    artifacts: FilesystemArtifactStore
    artifact_root: Path
    clock: FakeClock
    ids: SequentialIdGenerator
    successor_usage: list[Any]


async def _prepare(
    workspace: Path,
    evidence_root: Path,
    *,
    scenario: Literal["accept", "cap", "no_submit", "timeout"],
    paid: bool,
) -> _PreparedProbe:
    repository, worktree, fixture_commit = await asyncio.to_thread(
        lifecycle.create_lifecycle_fixture, workspace
    )
    oracle = await asyncio.to_thread(lifecycle.create_lifecycle_oracle, workspace, fixture_commit)
    fixture_tree = await asyncio.to_thread(
        lifecycle.run_lifecycle_git,
        repository,
        "rev-parse",
        f"{fixture_commit}^{{tree}}",
    )
    run_id = f"successor-probe-{uuid4().hex[:12]}"
    engine = create_engine(workspace / "successor.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    registry = RunnerOwnedProcessRegistry()
    artifact_root = evidence_root / run_id
    artifact_root.mkdir(parents=True, exist_ok=False)
    artifacts = FilesystemArtifactStore(artifact_root)
    factory = _HybridFactory(oracle, scenario=scenario, paid=paid, artifact_store=artifacts)
    routine = load_routine_from_path(lifecycle.ROUTINE_PATH)
    run_config = {
        "feature_spec_path": "SMOKE_SPEC.md",
        "feature_spec_content": (worktree / "SMOKE_SPEC.md").read_text(),
        "acceptance_command": str(oracle),
        "acceptance_command_timeout_seconds": 10,
        "patch_budget": 2,
        "max_rejected_plan_proposals_per_planner": MAX_REJECTIONS,
        "max_planner_executions_per_node": MAX_EXECUTIONS,
        "gap_policy_profile": "standard",
        "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
        "reliable_plan_selected_runner_type": "codex_server",
        "reliable_plan_one_horizon_authorized": True,
        "reliable_plan_remaining_horizons": 1,
        "reliable_plan_qualification_evidence_hash": "sha256:" + "d" * 64,
        "reliable_plan_model_assignments": _assignments(paid=paid),
    }
    run = create_run_from_routine(
        routine, repo_name=repository.name, source_branch="main", config=run_config
    )
    run.id = run_id
    run.execution_mode = "graph"
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.worktree_path = str(worktree)
    run.worktree_enabled = True
    run.agent_runner_type = AgentRunnerType.CODEX_SERVER
    async with sessions() as session:
        service = WorkflowService(session)
        await service.create_run(run)
        await service.apply_start_run(run_id)
    await seed_run(
        sessions,
        routine,
        run_id=run_id,
        clock=clock,
        id_gen=ids,
        source_path=str(lifecycle.ROUTINE_PATH),
        run_config=run_config,
    )
    controller = GraphController(
        sessions,
        clock,
        ids,
        auto_dispatch=False,
        artifact_store=artifacts,
        reliable_plan_rejection_recorder=ReliablePlanRejectionRecorder(
            sessions, artifacts, resolve_orchestrator_source_root()
        ),
    )
    position = await controller.current_position(run_id)
    accepted = await controller.handle_command(run_id, position, "accept_run", {})
    await controller.handle_command(run_id, accepted.projection_position, "start", {})
    successor_usage: list[Any] = []

    async def record_usage(context: GraphDispatchContext, usage: Any) -> None:
        if context.node_payload.get("semantic_stage") == "successor_planning":
            successor_usage.append(usage)

    executor = GraphDispatchExecutor(
        sessions,
        controller,
        factory,
        worktree_path=worktree,
        artifact_store=artifacts,
        process_registry=registry,
        on_agent_usage=record_usage,
    )
    dispatcher = OutboxDispatcher(sessions, executor, clock)
    for expected_stage in ("initial_planning", "discovery", "plan_verification"):
        position = await controller.current_position(run_id)
        await controller.handle_command(
            run_id,
            position,
            "schedule_tick",
            {
                "lease_seconds": 3600,
                "max_grants": 10,
                "base_snapshot_id": "routine-snapshot",
            },
        )
        dispatched = await dispatcher.dispatch_pending(
            limit=1, run_id=run_id, allowed_kinds=_AGENT_OUTBOX
        )
        if len(dispatched) != 1:
            raise SuccessorProbeFailure(f"could not dispatch scripted {expected_stage} phase")
        await executor.wait_for_all()
        observed = factory.dispatch_contexts[-1]
        observed_stage = observed.node_payload.get("semantic_stage")
        if (
            observed.node_id == "planner-s-01"
            and observed.node_kind == "planner"
            and observed_stage is None
        ):
            observed_stage = "initial_planning"
        if observed_stage != expected_stage:
            raise SuccessorProbeFailure(
                f"expected scripted {expected_stage} phase, observed {observed_stage!r}"
            )
        await dispatcher.dispatch_pending(run_id=run_id, allowed_kinds=_MAINTENANCE_OUTBOX)
    if len(factory.dispatch_contexts) != 3:
        raise SuccessorProbeFailure("scripted preparation did not stop before successor")
    return _PreparedProbe(
        run_id=run_id,
        engine=engine,
        sessions=sessions,
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        registry=registry,
        factory=factory,
        worktree=worktree,
        fixture_commit=fixture_commit,
        fixture_tree=fixture_tree,
        artifacts=artifacts,
        artifact_root=artifact_root,
        clock=clock,
        ids=ids,
        successor_usage=successor_usage,
    )


async def _replay_rejections(prepared: _PreparedProbe, refs: list[StoredArtifactRef]) -> int:
    replayed = 0
    for index, ref in enumerate(refs):
        engine = create_engine(Path(prepared.worktree).parent / f"replay-{index}.db")
        await init_db(engine)
        sessions = create_session_factory(engine)
        try:
            await replay_reliable_plan_rejection(
                artifact_store=prepared.artifacts,
                evidence_ref=ref,
                isolated_session_factory=sessions,
                clock=FakeClock(),
                id_gen=SequentialIdGenerator(),
                worktree_path=resolve_orchestrator_source_root(),
            )
            replayed += 1
        finally:
            await engine.dispose()
    return replayed


def _topology(projection: Any, patch_ids: set[str]) -> dict[str, Any]:
    payloads = [
        node_payload_view(projection, node_id) or {}
        for node_id in projection.nodes
        if (node_payload_view(projection, node_id) or {}).get("patch_id") in patch_ids
    ]
    workers = [
        item
        for item in payloads
        if item.get("kind") == "worker" and item.get("semantic_stage") == "effectful_batch"
    ]
    worker_ids = {str(item["node_id"]) for item in workers if isinstance(item.get("node_id"), str)}
    edges = [edge for edge in edges_view(projection).values() if edge.to_node_id in worker_ids]
    return {
        "effectful_batches": sum(
            item.get("kind") == "worker" and item.get("semantic_stage") == "effectful_batch"
            for item in payloads
        ),
        "final_acceptance_checks": sum(
            item.get("kind") == "check"
            and item.get("semantic_stage") == "final_acceptance"
            and item.get("command_binding") == "dynamic_feature_acceptance"
            for item in payloads
        ),
        "final_audits": sum(
            item.get("kind") == "verifier" and item.get("semantic_stage") == "final_audit"
            for item in payloads
        ),
        "final_gates": sum(item.get("kind") == "final_gate" for item in payloads),
        "gap_planners": sum(
            item.get("kind") == "planner" and item.get("role") == "gap_planner" for item in payloads
        ),
        "child_successors": sum(
            item.get("kind") == "planner"
            and item.get("role") != "gap_planner"
            and item.get("semantic_stage") == "successor_planning"
            for item in payloads
        ),
        "batch_ids": [item.get("declared_batch_id") for item in workers],
        "batch_horizons": [item.get("planning_horizon") for item in workers],
        "batch_skeleton_ids": [item.get("reliable_plan_skeleton_id") for item in workers],
        "plan_source_node_ids": [
            edge.from_node_id for edge in edges if edge.to_port == "semantic_artifact"
        ],
        "plan_verification_source_node_ids": [
            edge.from_node_id for edge in edges if edge.to_port == "verification_report"
        ],
    }


async def run_probe(
    workspace: Path,
    evidence_root: Path,
    *,
    mode: Literal["deterministic", "paid"] = "deterministic",
    scenario: Literal["accept", "cap", "no_submit", "timeout"] = "accept",
    timeout_seconds: float = MAX_TIMEOUT_SECONDS,
) -> SuccessorProbeEvidence:
    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError("timeout_seconds must be greater than zero and at most 180")
    workspace = workspace.resolve(strict=True)
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence_root = evidence_root.resolve(strict=True)
    if evidence_root == workspace or workspace in evidence_root.parents:
        raise ValueError("evidence_root must be outside the disposable workspace")
    started = time.monotonic()
    source_commit, source_tree, source_dirty = await asyncio.to_thread(_source_identity)
    orchestrator_source_identity = await capture_source_identity(resolve_orchestrator_source_root())
    prepared = await _prepare(workspace, evidence_root, scenario=scenario, paid=mode == "paid")
    timed_out = False
    model_started = time.monotonic()
    cleanup_ms = 0
    try:
        successor_phase_start_position = await prepared.controller.current_position(prepared.run_id)
        position = await prepared.controller.current_position(prepared.run_id)
        await prepared.controller.handle_command(
            prepared.run_id,
            position,
            "schedule_tick",
            {
                "lease_seconds": 3600,
                "max_grants": 10,
                "base_snapshot_id": "routine-snapshot",
            },
        )
        dispatched = await prepared.dispatcher.dispatch_pending(
            limit=1, run_id=prepared.run_id, allowed_kinds=_AGENT_OUTBOX
        )
        if len(dispatched) != 1:
            raise SuccessorProbeFailure("exactly one successor dispatch was required")
        try:
            await asyncio.wait_for(prepared.executor.wait_for_all(), timeout=timeout_seconds)
        except TimeoutError:
            timed_out = True
            cleanup_started = time.monotonic()
            await prepared.registry.quiesce_run(
                prepared.run_id, runner_loss=False, retry_after_recovery=False
            )
            await prepared.executor.wait_for_all()
            cleanup_ms = int((time.monotonic() - cleanup_started) * 1000)
        model_ms = int((time.monotonic() - model_started) * 1000)
        await prepared.dispatcher.dispatch_pending(
            run_id=prepared.run_id, allowed_kinds=_MAINTENANCE_OUTBOX
        )
        projection = await prepared.controller.read_projection(prepared.run_id)
        async with prepared.sessions() as session:
            store = GraphEventStore(session)
            events = await store.read_run(prepared.run_id)
            pending = int(
                await session.scalar(
                    select(func.count(GraphOutboxModel.outbox_id)).where(
                        GraphOutboxModel.run_id == prepared.run_id,
                        GraphOutboxModel.status.in_(("pending", "dispatching")),
                    )
                )
                or 0
            )
        successor = prepared.factory.successor_context
        if successor is None:
            raise SuccessorProbeFailure("successor runner was not created")
        successor_id = successor.node_id
        execution_count = sum(
            item.node_id == successor_id for item in prepared.factory.dispatch_contexts
        )
        attempts = [
            attempt
            for attempt in execution_attempts_view(projection).values()
            if attempt.node_id == successor_id
        ]
        rejection_events = [
            event
            for event in events
            if event.event_type in {"graph_patch_rejected", "command_rejected"}
            and event.payload.get("proposed_by_node_id") == successor_id
        ]
        accepted_patch_ids = [
            str(event.payload["patch_id"])
            for event in events
            if event.event_type == "graph_patch_accepted"
            and event.payload.get("proposed_by_node_id") == successor_id
            and isinstance(event.payload.get("patch_id"), str)
        ]
        refs: list[StoredArtifactRef] = []
        rejection_evidence: list[dict[str, Any]] = []
        for event in rejection_events:
            raw = event.payload.get("rejection_evidence")
            if not isinstance(raw, dict):
                continue
            raw_dict = cast(dict[str, Any], raw)
            rejection_evidence.append(raw_dict)
            artifact_ref = raw_dict.get("artifact_ref")
            if isinstance(artifact_ref, dict) and raw_dict.get("replayable") is True:
                refs.append(StoredArtifactRef.model_validate(artifact_ref))
        replayed = await _replay_rejections(prepared, refs)
        topology = _topology(projection, set(accepted_patch_ids))
        completion_contract = non_gap_planner_completion_contract_satisfied(
            projection, successor_id
        )
        initial_id = prepared.factory.dispatch_contexts[0].node_id
        prompt = prepared.factory.successor_execution_context
        authority = {
            key: successor.node_payload.get(key)
            for key in (
                "semantic_stage",
                "planning_horizon",
                "reliable_plan_remaining_horizons",
                "reliable_plan_skeleton_id",
                "reliable_plan_assignment_role",
                "reliable_plan_selected_runner_type",
            )
        }
        fixture_unchanged = (
            await asyncio.to_thread(
                lifecycle.run_lifecycle_git,
                prepared.worktree,
                "status",
                "--porcelain",
                "--untracked-files=all",
            )
            == ""
            and await asyncio.to_thread(
                lifecycle.run_lifecycle_git, prepared.worktree, "rev-parse", "HEAD"
            )
            == prepared.fixture_commit
        )
        expected_plan_source = prepared.factory.dispatch_contexts[1].node_id
        expected_plan_verifier = prepared.factory.dispatch_contexts[2].node_id
        topology_exact = topology == {
            "effectful_batches": 1,
            "final_acceptance_checks": 1,
            "final_audits": 1,
            "final_gates": 1,
            "gap_planners": 3,
            "child_successors": 0,
            "batch_ids": ["stage3-smoke"],
            "batch_horizons": [1],
            "batch_skeleton_ids": ["reliable-plan-fff4f6b7-v1"],
            "plan_source_node_ids": [expected_plan_source],
            "plan_verification_source_node_ids": [expected_plan_verifier],
        }
        prompt_text = prompt.prompt if prompt is not None else ""
        thread_start = (
            next(
                (
                    message
                    for message in prepared.factory.transport.sent
                    if message.get("method") == "thread/start"
                ),
                None,
            )
            if prepared.factory.transport is not None
            else None
        )
        expected_dynamic_tools = (
            build_dynamic_tool_specs(
                is_verifier=False,
                context=prompt,
            )
            if prompt is not None
            else []
        )
        protected_context = {
            "source_identity": orchestrator_source_identity.model_dump(mode="json"),
            "harness_sha256": _sha256(Path(__file__)),
            "lifecycle_helper_sha256": _sha256(LIFECYCLE_PATH),
            "routine_sha256": _sha256(lifecycle.ROUTINE_PATH),
            "fixture_commit": prepared.fixture_commit,
            "fixture_tree": prepared.fixture_tree,
            "spec_sha256": _sha256(prepared.worktree / "SMOKE_SPEC.md"),
            "oracle_sha256": _sha256(prepared.factory.oracle),
            "successor_node_id": successor_id,
            "successor_node_payload": successor.node_payload,
            "successor_requirements": successor.requirements,
            "successor_prompt": prompt_text,
            "dynamic_tools": expected_dynamic_tools,
            "deterministic_transport_dynamic_tools": (
                thread_start["params"]["dynamicTools"] if thread_start is not None else None
            ),
            "dynamic_tool_receipt_refs": [
                ref.model_dump(mode="json") for ref in prepared.factory.dynamic_tool_receipt_refs
            ],
        }
        async with prepared.artifacts.publication():
            protected_context_ref = await prepared.artifacts.put(
                json.dumps(protected_context, sort_keys=True, separators=(",", ":")).encode(),
                media_type="application/vnd.orchestrator.successor-probe-context+json",
                encoding="utf-8",
            )
        phase_counts = Counter(
            event.event_type for event in events if event.position > successor_phase_start_position
        )
        expected_pass = scenario == "accept"
        usage_result = prepared.successor_usage[0] if len(prepared.successor_usage) == 1 else None
        usage = usage_result.metrics if usage_result is not None else None
        receipt_evidence_complete = (
            not prepared.factory.dynamic_tool_receipt_overflow
            and bool(prepared.factory.dynamic_tool_receipts)
            and len(prepared.factory.dynamic_tool_receipts)
            == len(prepared.factory.dynamic_tool_receipt_refs)
            and all(
                receipt.request_response_complete
                for receipt in prepared.factory.dynamic_tool_receipts
            )
        )
        predicates = {
            "real_successor_not_initial": successor_id != initial_id,
            "successor_authority_bound": (
                authority["semantic_stage"] == "successor_planning"
                and authority["planning_horizon"] == 1
                and authority["reliable_plan_remaining_horizons"] == 1
                and isinstance(authority["reliable_plan_skeleton_id"], str)
                and authority["reliable_plan_assignment_role"] == "successor_planner"
                and authority["reliable_plan_selected_runner_type"] == "codex_server"
            ),
            "successor_scope_prompt_bound": (
                "current_declared_batch" in prompt_text and "stage3-smoke" in prompt_text
            ),
            "one_execution": execution_count == 1,
            "one_successful_runner_result": usage_result is not None
            and usage_result.success is True,
            "completion_contract": completion_contract,
            "topology_exact": topology_exact,
            "plain_submission_finalized": len(attempts) == 1 and attempts[0].state == "finalized",
            "rejections_with_exact_replay": len(rejection_events) == len(refs) == replayed,
            "transport_receipts_complete": receipt_evidence_complete,
            "deterministic_schema_matches_paid": (
                mode == "paid"
                or (
                    thread_start is not None
                    and thread_start["params"]["dynamicTools"] == expected_dynamic_tools
                )
            ),
            "no_downstream_dispatch": len(prepared.factory.dispatch_contexts) == 4,
            "no_downstream_active_lease": not any(
                lease.state in {"active", "suspended"} for lease in leases_view(projection).values()
            ),
            "pending_outbox_empty": pending == 0,
            "fixture_unchanged": fixture_unchanged,
            "owned_processes_drained": prepared.registry.run_owner_count(prepared.run_id) == 0,
            "within_model_timeout": not timed_out,
            "no_runtime_recovery_or_retry": not any(
                phase_counts[event_type] for event_type in _FORBIDDEN_RECOVERY_EVENTS
            ),
        }
        passed = expected_pass and all(predicates.values())
        status: Literal["passed", "failed", "incomplete", "error"]
        status = "incomplete" if timed_out else ("passed" if passed else "failed")
        result_path = prepared.artifact_root / "probe-result.json"
        evidence = SuccessorProbeEvidence(
            status=status,
            mode=mode,
            run_id=prepared.run_id,
            model=MODEL,
            reasoning_effort=EFFORT,
            timeout_seconds=timeout_seconds,
            source_commit=source_commit,
            source_tree=source_tree,
            source_dirty=source_dirty,
            harness_sha256=_sha256(Path(__file__)),
            lifecycle_helper_sha256=_sha256(LIFECYCLE_PATH),
            routine_sha256=_sha256(lifecycle.ROUTINE_PATH),
            spec_sha256=_sha256(prepared.worktree / "SMOKE_SPEC.md"),
            oracle_sha256=_sha256(prepared.factory.oracle),
            orchestrator_source_identity=orchestrator_source_identity.model_dump(mode="json"),
            fixture_commit=prepared.fixture_commit,
            fixture_tree=prepared.fixture_tree,
            successor_node_id=successor_id,
            successor_execution_id=successor.execution_id,
            successor_prompt_sha256=hashlib.sha256(prompt_text.encode()).hexdigest(),
            successor_authority=authority,
            phase_node_ids=[item.node_id for item in prepared.factory.dispatch_contexts],
            phase_event_counts=dict(sorted(phase_counts.items())),
            accepted_patch_ids=accepted_patch_ids,
            rejected_patch_ids=[str(event.payload.get("patch_id")) for event in rejection_events],
            rejection_evidence=rejection_evidence,
            dynamic_tool_receipts=[
                {
                    **receipt.model_dump(mode="json", exclude={"request", "response"}),
                    "artifact_ref": ref.model_dump(mode="json"),
                }
                for receipt, ref in zip(
                    prepared.factory.dynamic_tool_receipts,
                    prepared.factory.dynamic_tool_receipt_refs,
                    strict=True,
                )
            ],
            protected_context_ref=protected_context_ref.model_dump(mode="json"),
            artifact_root=str(prepared.artifact_root),
            result_path=str(result_path),
            replayed_rejection_count=replayed,
            execution_count=execution_count,
            recorded_execution_attempt_count=len(attempts),
            downstream_dispatch_count=max(0, len(prepared.factory.dispatch_contexts) - 4),
            downstream_active_lease_count=sum(
                lease.state in {"active", "suspended"} and lease.node_id != successor_id
                for lease in leases_view(projection).values()
            ),
            pending_outbox_count=pending,
            remaining_node_states=node_states_view(projection),
            completion_contract_satisfied=completion_contract,
            topology=topology,
            model_duration_ms=model_ms,
            usage=(
                {
                    "duration_ms": usage.duration_ms,
                    "num_actions": usage.num_actions,
                    "input_tokens": usage.gen_ai_usage_input_tokens,
                    "output_tokens": usage.gen_ai_usage_output_tokens,
                    "cache_read_input_tokens": usage.gen_ai_usage_cache_read_input_tokens,
                }
                if usage is not None
                else {}
            ),
            cleanup_duration_ms=cleanup_ms,
            total_duration_ms=int((time.monotonic() - started) * 1000),
            timed_out=timed_out,
            owned_process_count_after=prepared.registry.run_owner_count(prepared.run_id),
            fixture_unchanged=fixture_unchanged,
            strict_predicates=predicates,
            incomplete_reason="model wall timeout expired" if timed_out else None,
        )
        await asyncio.to_thread(
            result_path.write_text,
            evidence.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return evidence
    finally:
        if prepared.registry.has_run_owners(prepared.run_id):
            await prepared.registry.quiesce_run(
                prepared.run_id, runner_loss=False, retry_after_recovery=False
            )
        await prepared.executor.wait_for_all()
        await prepared.engine.dispose()


def main(
    argv: list[str] | None = None,
    *,
    run_probe_fn: ProbeRunner = run_probe,
) -> int:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    if not raw_args or raw_args[0].startswith("-"):
        raw_args.insert(0, "deterministic")
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    deterministic = subparsers.add_parser("deterministic")
    deterministic.add_argument("--workspace", type=Path)
    deterministic.add_argument("--evidence-root", type=Path)
    deterministic.add_argument("--timeout-seconds", type=float, default=MAX_TIMEOUT_SECONDS)
    paid = subparsers.add_parser("paid")
    paid.add_argument("--workspace", type=Path)
    paid.add_argument("--evidence-root", type=Path, required=True)
    paid.add_argument("--timeout-seconds", type=float, default=MAX_TIMEOUT_SECONDS)
    paid.add_argument("--confirm-one-paid-successor", action="store_true")
    args = parser.parse_args(raw_args)
    command = args.command or "deterministic"
    if command == "paid" and not args.confirm_one_paid_successor:
        parser.error("paid requires --confirm-one-paid-successor")
    canonical_temp = Path(tempfile.gettempdir()).resolve(strict=True)
    evidence_root = (
        args.evidence_root if args.evidence_root else canonical_temp / "successor-evidence"
    )
    try:
        if args.workspace:
            args.workspace.mkdir(parents=True, exist_ok=True)
            evidence = asyncio.run(
                run_probe_fn(
                    args.workspace,
                    evidence_root,
                    mode="paid" if command == "paid" else "deterministic",
                    timeout_seconds=args.timeout_seconds,
                )
            )
        else:
            with tempfile.TemporaryDirectory(
                prefix="recovery-successor-probe-", dir=canonical_temp
            ) as raw:
                evidence = asyncio.run(
                    run_probe_fn(
                        Path(raw),
                        evidence_root,
                        mode="paid" if command == "paid" else "deterministic",
                        timeout_seconds=args.timeout_seconds,
                    )
                )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": "successor probe failed; inspect protected evidence if available",
                },
                sort_keys=True,
            )
        )
        return 2
    print(evidence.model_dump_json())
    return 0 if evidence.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
