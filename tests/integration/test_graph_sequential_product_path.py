"""Default-collected joined qualification for the supported sequential graph path.

Unlike the historical dynamic-graph E2E module, this test enters through the
public run APIs and lets the durable signal consumer own activation and the
production graph driver own graph creation and dispatch.  Only model behaviour
is deterministic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
import json
from pathlib import Path
import secrets
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orchestrator.api import create_app
from orchestrator.api.deps import make_service_factory, make_workflow_preparer
from orchestrator.config import AgentRunnerType, RoutineSource, load_routine_from_path
from orchestrator.db import EventV2Model, RunRepository, commit_with_event_outbox, init_db
from orchestrator.graph import (
    MAX_EVENT_ENVELOPE_BYTES,
    ReliablePlanEvaluationConfig,
    build_projection,
    execution_attempts_view,
    leases_view,
    node_payload_view,
    output_record_payloads_view,
    projection_from_checkpoint,
    projection_to_checkpoint,
    task_states_view,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    RunnerOwnedProcessRegistry,
    SelectedRunnerGraphToolCatalog,
    StaticGraphAgentFactory,
    issue_reliable_plan_qualification,
    run_reliable_plan_product_path_scenarios,
)
from orchestrator.runners import AgentRunner
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
from orchestrator.workflow import GraphRunDriver, SignalConsumer, WorkflowService

from tests.integration.git_helpers import _init_repo


ROUTINE_PATH = (
    Path(__file__).resolve().parents[2] / "routines" / "dynamic-graph-feature" / "routine.yaml"
)
QUALIFICATION_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "graph" / "reliable_plan_fff4f6b7.json"
)


@pytest_asyncio.fixture(scope="module")
async def canonical_qualification(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """Run the expensive canonical qualification once; issue fresh grants per app."""
    evaluation = ReliablePlanEvaluationConfig.model_validate(
        json.loads(QUALIFICATION_FIXTURE.read_text())
    )
    qualification_run = await run_reliable_plan_product_path_scenarios(
        evaluation.scenario_manifest,
        root=tmp_path_factory.mktemp("sequential-canonical-qualification"),
    )
    assert qualification_run.qualification.qualified
    return qualification_run


async def _issue_qualification_reference(app: Any, qualification_run: Any) -> str:
    async with app.state.session_factory() as session:
        grant = await issue_reliable_plan_qualification(
            session,
            qualification_run.qualification.manifest,
            qualification_run.projection,
            qualification_run.accepted_receipt_record_id,
            reference_factory=lambda: secrets.token_urlsafe(32),
        )
        await commit_with_event_outbox(session)
    return grant.reference


class _ScriptedAgent:
    def __init__(
        self,
        execute: Callable[..., Awaitable[ExecutionResult]],
        execution_contexts: list[ExecutionContext],
        cancel_callback: Callable[[], None] | None = None,
    ) -> None:
        self._execute = execute
        self._execution_contexts = execution_contexts
        self._cancel_callback = cancel_callback

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
            name="sequential-product-path",
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
        self._execution_contexts.append(context)
        return await self._execute(
            context,
            on_submit,
            on_grade,
        )

    async def cancel(self) -> None:
        if self._cancel_callback is not None:
            self._cancel_callback()
        return None


class _RecordingFactory:
    def __init__(self, scenario: str = "happy") -> None:
        self.scenario = scenario
        self.contexts: list[GraphDispatchContext] = []
        self.execution_contexts: list[ExecutionContext] = []
        self.effective_configs: dict[str, dict[str, Any]] = {}
        self.latched = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.discovery_attempts = 0
        self._building_context: GraphDispatchContext | None = None
        self._tool_catalog = SelectedRunnerGraphToolCatalog(
            AgentRunnerType.CODEX_SERVER,
            {"model": "controller-base-model", "reasoning_effort": "low"},
        )
        self._static = StaticGraphAgentFactory(
            AgentRunnerType.CODEX_SERVER,
            {"model": "controller-base-model", "reasoning_effort": "low"},
            graph_tool_catalog=self._tool_catalog,
            runner_builder=self._build_runner,
        )

    def preflight(
        self,
        _context: GraphDispatchContext,
        execution_context: ExecutionContext,
        *,
        graph_mcp_available: bool,
    ) -> None:
        self._static.preflight(
            _context,
            execution_context,
            graph_mcp_available=graph_mcp_available,
        )

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        self.contexts.append(context)
        self._building_context = context
        try:
            return self._static.create_runner(context)
        finally:
            self._building_context = None

    def _build_runner(
        self,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> AgentRunner:
        del run_id, phase
        assert runner_type == AgentRunnerType.CODEX_SERVER
        context = self._building_context
        assert context is not None
        self.effective_configs[context.node_id] = dict(runner_config)
        if context.node_kind == "planner":
            return _ScriptedAgent(
                partial(
                    _plan_reliable_horizon,
                    base_graph_position=context.graph_position,
                    dispatch_context=context,
                    scenario=self.scenario,
                ),
                self.execution_contexts,
            )
        if context.node_kind == "worker":
            if context.node_payload.get("semantic_stage") == "discovery":
                if self.scenario == "oversized":
                    return _ScriptedAgent(
                        partial(_discover_oversized, factory=self),
                        self.execution_contexts,
                    )
                return _ScriptedAgent(_discover, self.execution_contexts)
            if (
                self.scenario in {"cancel", "restart_latch"}
                and context.node_id == "worker-batch-1"
                and not self.cancelled.is_set()
            ):
                return _ScriptedAgent(
                    partial(_latch, factory=self),
                    self.execution_contexts,
                    cancel_callback=self.cancelled.set,
                )
            return _ScriptedAgent(_build, self.execution_contexts)
        if context.node_kind == "verifier":
            return _ScriptedAgent(
                partial(_verify, scenario=self.scenario),
                self.execution_contexts,
            )
        raise AssertionError(f"unexpected model-backed node: {context.node_kind}")


def _batch_macro(horizon: int, *, check_command: str = "true") -> dict[str, Any]:
    return {
        "macro": "create_effectful_batch",
        "args": {
            "region_id": f"batch-{horizon}",
            "batch_id": f"batch-{horizon}",
            "plan_source_node_id": "worker-discovery",
            "plan_verification_source_node_id": "verifier-plan",
            "worker_id": f"worker-batch-{horizon}",
            "verifier_id": f"verifier-batch-{horizon}",
            "semantic_schema_id": "reliable-plan-implementation-plan",
            "semantic_schema_version": 1,
            "objective": f"Implement declared batch {horizon}.",
            "acceptance": [f"batch {horizon} independently passes"],
            "requirement_source_node_ids": ["requirement-dynamic-feature-acceptance"],
            "checks": [
                {
                    "check_id": f"check-batch-{horizon}",
                    "command_definition": {
                        "id": f"check-batch-{horizon}",
                        "cmd": check_command,
                    },
                }
            ],
            "rubric": ["dynamic_feature_acceptance is satisfied"],
            "planning_horizon": horizon,
        },
    }


def _final_audit_and_gate_ops(
    *, batch_one_verifier: str = "verifier-batch-1"
) -> list[dict[str, Any]]:
    batch_inputs = [
        {
            "port": f"verification_report_batch_{batch}",
            "direction": "input",
            "schema": "VerificationReport",
            "required": True,
        }
        for batch in (1, 2)
    ]
    ops: list[dict[str, Any]] = [
        {
            "op": "create_node",
            "node": {
                "node_id": "final-audit",
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "semantic_stage": "final_audit",
                "task_region_id": "batch-2",
                "inputs": batch_inputs,
                "outputs": [
                    {
                        "port": "verification_report",
                        "direction": "output",
                        "schema": "VerificationReport",
                        "required": True,
                    }
                ],
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": "final-gate",
                "kind": "final_gate",
                "role": "final_gate",
                "state": "planned",
                "task_region_id": "batch-2",
                "declared_batch_ids": ["batch-1", "batch-2"],
                "inputs": [
                    *batch_inputs,
                    {
                        "port": "verification_report_final_audit",
                        "direction": "input",
                        "schema": "VerificationReport",
                        "required": True,
                    },
                ],
            },
        },
    ]
    for batch in (1, 2):
        source = batch_one_verifier if batch == 1 else f"verifier-batch-{batch}"
        for target, port in (
            ("final-audit", f"verification_report_batch_{batch}"),
            ("final-gate", f"verification_report_batch_{batch}"),
        ):
            ops.append(
                {
                    "op": "create_edge",
                    "edge_id": f"edge-batch-{batch}-to-{target}",
                    "from_node_id": source,
                    "from_port": "verification_report",
                    "to_node_id": target,
                    "to_port": port,
                    "required": True,
                    "accepted_record_selector": {
                        "record_type": "verification_report",
                        "schema": "VerificationReport",
                        "outcome": "passed",
                    },
                }
            )
    ops.append(
        {
            "op": "create_edge",
            "edge_id": "edge-final-audit-to-final-gate",
            "from_node_id": "final-audit",
            "from_port": "verification_report",
            "to_node_id": "final-gate",
            "to_port": "verification_report_final_audit",
            "required": True,
            "accepted_record_selector": {
                "record_type": "verification_report",
                "schema": "VerificationReport",
                "outcome": "passed",
            },
        }
    )
    return ops


async def _plan_reliable_horizon(
    context: ExecutionContext,
    on_submit: SubmitCallback,
    _on_grade: GradeCallback | None,
    *,
    base_graph_position: int,
    dispatch_context: GraphDispatchContext,
    scenario: str,
) -> ExecutionResult:
    assert context.graph_patch_callback is not None
    if context.node_id == "planner-s-01":
        invocations = [
            {
                "macro": "create_discovery_region",
                "args": {
                    "region_id": "discovery",
                    "worker_id": "worker-discovery",
                    "semantic_schema_id": "reliable-plan-implementation-plan",
                    "semantic_schema_version": 1,
                    "objective": "Discover a bounded two-batch implementation plan.",
                    "acceptance": ["the plan declares exactly two independently testable batches"],
                    "requirement_source_node_ids": ["requirement-dynamic-feature-acceptance"],
                },
            },
            {
                "macro": "create_plan_verification",
                "args": {
                    "region_id": "discovery",
                    "verifier_id": "verifier-plan",
                    "artifact_source_node_id": "worker-discovery",
                    "semantic_schema_id": "reliable-plan-implementation-plan",
                    "semantic_schema_version": 1,
                    "objective": "Verify the discovered implementation plan.",
                    "acceptance": ["both batches cover the bound requirement"],
                    "rubric": ["dynamic_feature_acceptance maps to both declared batches"],
                    "requirement_source_node_ids": ["requirement-dynamic-feature-acceptance"],
                },
            },
            {
                "macro": "create_successor_planner",
                "args": {
                    "region_id": "discovery",
                    "node_id": "planner-h1",
                    "evidence_source_node_id": "verifier-plan",
                    "evidence_source_port": "verification_report",
                    "planning_horizon": 1,
                },
            },
        ]
        ops: list[dict[str, Any]] = []
        patch_id = "reliable-plan-skeleton"
    elif context.node_id.startswith("planner-gap-"):
        records = output_record_payloads_view(dispatch_context.graph_projection).values()
        failed_verification = next(
            record
            for record in records
            if record.record_type == "verification_report"
            and record.producer_node_id == "verifier-batch-1"
            and getattr(record.value, "outcome", None) == "failed"
        )
        failed_check = next(
            record
            for record in records
            if record.record_type == "check_result"
            and record.producer_node_id == "check-batch-1"
            and getattr(record.value, "status", None) == "failed"
        )
        classified_gap_id = f"classified-gap-{dispatch_context.execution_id}"
        invocations = [
            {
                "macro": "create_corrective_region",
                "args": {
                    "region_id": "corrective_work_region",
                    "worker_id": "worker-corrective-batch-1",
                    "verifier_id": "verifier-corrective-batch-1",
                    "candidate_id": "candidate-corrective-batch-1",
                    "objective": "Correct the exact failed batch-one evidence.",
                    "access_mode": "write",
                    "acceptance": ["batch 1 independently passes after correction"],
                    "rubric": ["dynamic_feature_acceptance is satisfied"],
                    "classified_gap_source_node_id": context.node_id,
                    "failed_verification_source_node_id": "verifier-batch-1",
                    "failed_check_source_node_ids": ["check-batch-1"],
                    "failed_verification_record_id": failed_verification.record_id,
                    "failed_check_record_ids": [failed_check.record_id],
                    "classified_gap_record_id": classified_gap_id,
                    "base_snapshot_selection": "rejected_candidate",
                    "base_snapshot_candidate_id": failed_verification.candidate_id,
                    "declared_batch_id": "batch-1",
                    "planning_horizon": 1,
                    "checks": [
                        {
                            "check_id": "check-corrective-batch-1",
                            "command_definition": {
                                "id": "check-corrective-batch-1",
                                "cmd": "true",
                            },
                        }
                    ],
                },
            },
            {
                "macro": "create_successor_planner",
                "args": {
                    "region_id": "corrective_work_region",
                    "node_id": "planner-h2",
                    "evidence_source_node_id": "verifier-corrective-batch-1",
                    "evidence_source_port": "verification_report",
                    "planning_horizon": 2,
                },
            },
        ]
        ops = []
        patch_id = "reliable-plan-batch-1-correction"
    else:
        horizon = 2 if context.node_id == "planner-h2" else 1
        check_command = "false" if scenario == "correction" and horizon == 1 else "true"
        invocations = [_batch_macro(horizon, check_command=check_command)]
        ops = (
            _final_audit_and_gate_ops(
                batch_one_verifier=(
                    "verifier-corrective-batch-1"
                    if scenario == "correction"
                    else "verifier-batch-1"
                )
            )
            if horizon == 2
            else []
        )
        if horizon == 1:
            if scenario == "correction":
                ops.extend(
                    [
                        {
                            "op": "create_node",
                            "node": {
                                "node_id": "planner-gap-batch-1",
                                "kind": "planner",
                                "role": "gap_planner",
                                "state": "planned",
                                "task_region_id": "batch-1",
                                "planning_horizon": 1,
                                "inputs": [
                                    {
                                        "port": "verification_report",
                                        "direction": "input",
                                        "schema": "VerificationReport",
                                        "required": True,
                                    },
                                    {
                                        "port": "check_result",
                                        "direction": "input",
                                        "schema": "CheckResult",
                                        "required": True,
                                    },
                                ],
                            },
                        },
                        {
                            "op": "create_edge",
                            "edge_id": "edge-verifier-batch-1-to-planner-gap-batch-1",
                            "from_node_id": "verifier-batch-1",
                            "from_port": "verification_report",
                            "to_node_id": "planner-gap-batch-1",
                            "to_port": "verification_report",
                            "required": True,
                            "accepted_record_selector": {
                                "record_type": "verification_report",
                                "schema": "VerificationReport",
                                "outcome": "failed",
                            },
                            "prompt_hydration_policy": "structured_json",
                        },
                        {
                            "op": "create_edge",
                            "edge_id": "edge-check-batch-1-to-planner-gap-batch-1",
                            "from_node_id": "check-batch-1",
                            "from_port": "check_result",
                            "to_node_id": "planner-gap-batch-1",
                            "to_port": "check_result",
                            "required": True,
                            "accepted_record_selector": {
                                "record_type": "check_result",
                                "schema": "CheckResult",
                                "status": "failed",
                            },
                            "prompt_hydration_policy": "structured_json",
                        },
                    ]
                )
            else:
                invocations.append(
                    {
                        "macro": "create_successor_planner",
                        "args": {
                            "region_id": "batch-1",
                            "node_id": "planner-h2",
                            "evidence_source_node_id": "verifier-batch-1",
                            "evidence_source_port": "verification_report",
                            "planning_horizon": 2,
                        },
                    }
                )
        patch_id = f"reliable-plan-horizon-{horizon}"
    feedback = await context.graph_patch_callback(
        {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "ops": ops,
            "macro_invocations": invocations,
        }
    )
    assert "accepted" in feedback.lower(), feedback
    await on_submit()
    return ExecutionResult(success=True)


async def _discover(
    _context: ExecutionContext,
    on_submit: SubmitCallback,
    _on_grade: GradeCallback | None,
) -> ExecutionResult:
    acknowledgement = await on_submit(
        {
            "outputs": {
                "semantic_artifact": {
                    "summary": "Two bounded, sequential implementation batches.",
                    "batches": [
                        {
                            "batch_id": "batch-1",
                            "objective": "Create the first independently accepted change.",
                            "acceptance": ["batch 1 passes its check and verifier"],
                        },
                        {
                            "batch_id": "batch-2",
                            "objective": "Create the second independently accepted change.",
                            "acceptance": ["batch 2 passes its check and verifier"],
                        },
                    ],
                }
            }
        }
    )
    assert acknowledgement is not None
    return ExecutionResult(success=True)


async def _discover_oversized(
    _context: ExecutionContext,
    on_submit: SubmitCallback,
    _on_grade: GradeCallback | None,
    *,
    factory: _RecordingFactory,
) -> ExecutionResult:
    factory.discovery_attempts += 1
    await on_submit(
        {
            "outputs": {
                "semantic_artifact": {
                    "summary": "x" * (MAX_EVENT_ENVELOPE_BYTES * 2),
                    "batches": [
                        {
                            "batch_id": "batch-1",
                            "objective": "This record cannot fit the event envelope.",
                            "acceptance": ["the impossible contract terminalizes"],
                        }
                    ],
                }
            }
        }
    )
    return ExecutionResult(success=True)


async def _latch(
    _context: ExecutionContext,
    _on_submit: SubmitCallback,
    _on_grade: GradeCallback | None,
    *,
    factory: _RecordingFactory,
) -> ExecutionResult:
    factory.latched.set()
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


async def _build(
    context: ExecutionContext,
    on_submit: SubmitCallback,
    _on_grade: GradeCallback | None,
) -> ExecutionResult:
    output = Path(context.working_dir) / "docs/graph-approach/dynamic-smoke-output.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    prior = output.read_text() if output.exists() else ""
    output.write_text(f"{prior}{context.node_id}: dynamic-smoke\n")
    await on_submit()
    return ExecutionResult(success=True)


async def _verify(
    context: ExecutionContext,
    on_submit: SubmitCallback,
    on_grade: GradeCallback | None,
    *,
    scenario: str,
) -> ExecutionResult:
    assert on_grade is not None
    if context.requirements:
        requirement_id = context.requirements[0].partition(":")[0]
        grade = "C" if scenario == "correction" and context.node_id == "verifier-batch-1" else "A"
        await on_grade(
            requirement_id,
            grade,
            "candidate and check evidence satisfy the requirement",
        )
    await on_submit()
    return ExecutionResult(success=True)


@dataclass
class _JoinedHarness:
    app: Any
    client: AsyncClient
    consumer: SignalConsumer
    driver: GraphRunDriver
    factory: _RecordingFactory
    controllers: list[GraphController]
    outcomes: list[Any]
    repo: Path
    canonical_qualification: Any
    process_registry: RunnerOwnedProcessRegistry
    create_service: Callable[[Any], Awaitable[WorkflowService]]

    async def create_and_start(self) -> str:
        qualification_reference = await _issue_qualification_reference(
            self.app, self.canonical_qualification
        )
        evaluation = ReliablePlanEvaluationConfig.model_validate(
            json.loads(QUALIFICATION_FIXTURE.read_text())
        )
        created = await self.client.post(
            "/api/runs",
            json={
                "routine_embedded": load_routine_from_path(ROUTINE_PATH).model_dump(
                    mode="json", by_alias=True
                ),
                "repo_name": self.repo.name,
                "branch": "main",
                "execution_mode": "graph",
                "agent_runner_type": "codex_server",
                "agent_runner_config": {
                    "model": "gpt-5.6-luna",
                    "reasoning_effort": "low",
                },
                "reliable_plan_qualification_reference": qualification_reference,
                "config": {
                    "feature_spec_path": "docs/dynamic-smoke.md",
                    "feature_spec_content": "Produce the dynamic-smoke output.",
                    "acceptance_command": ("test -f docs/graph-approach/dynamic-smoke-output.txt"),
                    "hidden_oracle_command": (
                        "grep -q dynamic-smoke docs/graph-approach/dynamic-smoke-output.txt"
                    ),
                    "patch_budget": 8,
                    "gap_policy_profile": "standard",
                    "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
                    "reliable_plan_model_assignments": (
                        evaluation.luna_arm.model_dump(mode="json")
                    ),
                },
            },
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        started = await self.client.post(f"/api/runs/{run_id}/start")
        assert started.status_code == 202, started.text
        return run_id

    async def drain_start(self, run_id: str) -> None:
        await self.consumer._process_run(run_id)

    async def wait_driver(self, run_id: str) -> Any:
        await self.consumer._graph_driver_tasks[run_id]
        return self.outcomes[-1] if self.outcomes else None

    async def events(self, run_id: str) -> list[Any]:
        async with self.app.state.session_factory() as session:
            return await GraphEventStore(session).read_run(run_id)

    async def close(self) -> None:
        await self.consumer.stop()
        await self.client.aclose()
        await self.app.state.engine.dispose()


async def _make_joined_harness(
    tmp_path: Path,
    canonical_qualification: Any,
    *,
    scenario: str,
) -> _JoinedHarness:
    repos = tmp_path / "repos"
    worktrees = tmp_path / "worktrees"
    repos.mkdir()
    worktrees.mkdir()
    repo = repos / "project"
    repo.mkdir()
    _init_repo(repo)

    from orchestrator.config.global_config import GlobalConfig, PathsConfig

    app = create_app(
        db_path=str(tmp_path / f"sequential-product-path-{scenario}.db"),
        routine_dirs=[(ROUTINE_PATH.parent.parent, RoutineSource.LOCAL)],
        global_config=GlobalConfig(
            paths=PathsConfig(repos_dir=str(repos), worktrees_dir=str(worktrees))
        ),
        spawn_agents=False,
    )
    await init_db(app.state.engine)
    factory = _RecordingFactory(scenario)
    process_registry = RunnerOwnedProcessRegistry()
    controllers: list[GraphController] = []

    async def create_service(session: Any) -> WorkflowService:
        return await service_factory(session)

    def runtime_builder(
        sessions: Any,
        clock: Any,
        ids: Any,
        *,
        worktree_path: str | Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
        artifact_store: Any,
        process_registry: RunnerOwnedProcessRegistry,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        assert runner_type == AgentRunnerType.CODEX_SERVER
        controller = GraphController(sessions, clock, ids, auto_dispatch=False)
        controllers.append(controller)
        return controller, GraphDispatchExecutor(
            sessions,
            controller,
            factory,
            worktree_path=Path(worktree_path),
            artifact_store=artifact_store,
            process_registry=process_registry,
        )

    service_factory = make_service_factory(
        connection_manager=app.state.connection_manager,
        lock_manager=app.state.lock_manager,
        global_config=app.state.global_config,
        env_lifecycle=app.state.env_lifecycle,
        artifact_gc=app.state.artifact_gc,
    )
    driver = GraphRunDriver(
        app.state.session_factory,
        create_service,
        runtime_builder=runtime_builder,
        process_registry=process_registry,
    )
    outcomes: list[Any] = []

    async def run_graph(run_id: str) -> None:
        outcomes.append(await driver.run(run_id))

    consumer = SignalConsumer(
        app.state.session_factory,
        create_service,
        graph_runner=run_graph,
        graph_execution_quiescence_preparer=process_registry.prepare_run_quiescence,
        graph_execution_quiescer=process_registry.quiesce_run,
        graph_safe_effect_drainer=driver.quiesce_run,
        graph_owner_checker=process_registry.has_run_owners,
        workflow_preparer=make_workflow_preparer(app.state.runner_executor),
        poll_interval=100.0,
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]
    return _JoinedHarness(
        app=app,
        client=client,
        consumer=consumer,
        driver=driver,
        factory=factory,
        controllers=controllers,
        outcomes=outcomes,
        repo=repo,
        canonical_qualification=canonical_qualification,
        process_registry=process_registry,
        create_service=create_service,
    )


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_api_start_serializes_two_bounded_horizons_with_durable_signals(
    tmp_path: Path,
    canonical_qualification: Any,
) -> None:
    repos = tmp_path / "repos"
    worktrees = tmp_path / "worktrees"
    repos.mkdir()
    worktrees.mkdir()
    repo = repos / "project"
    repo.mkdir()
    _init_repo(repo)

    from orchestrator.config.global_config import GlobalConfig, PathsConfig

    app = create_app(
        db_path=str(tmp_path / "sequential-product-path.db"),
        routine_dirs=[(ROUTINE_PATH.parent.parent, RoutineSource.LOCAL)],
        global_config=GlobalConfig(
            paths=PathsConfig(repos_dir=str(repos), worktrees_dir=str(worktrees))
        ),
        spawn_agents=False,
    )
    await init_db(app.state.engine)
    factory = _RecordingFactory()
    controllers: list[GraphController] = []

    async def create_service(session: Any) -> WorkflowService:
        return await service_factory(session)

    def runtime_builder(
        sessions: Any,
        clock: Any,
        ids: Any,
        *,
        worktree_path: str | Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
        artifact_store: Any,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        assert runner_type == AgentRunnerType.CODEX_SERVER
        assert runner_config == {"model": "gpt-5.6-luna", "reasoning_effort": "low"}
        controller = GraphController(sessions, clock, ids, auto_dispatch=False)
        controllers.append(controller)
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            factory,
            worktree_path=Path(worktree_path),
            artifact_store=artifact_store,
        )
        return controller, executor

    service_factory = make_service_factory(
        connection_manager=app.state.connection_manager,
        lock_manager=app.state.lock_manager,
        global_config=app.state.global_config,
        env_lifecycle=app.state.env_lifecycle,
        artifact_gc=app.state.artifact_gc,
    )
    driver = GraphRunDriver(
        app.state.session_factory,
        create_service,
        runtime_builder=runtime_builder,
    )
    outcomes: list[Any] = []

    async def run_graph(run_id: str) -> None:
        outcomes.append(await driver.run(run_id))

    consumer = SignalConsumer(
        app.state.session_factory,
        create_service,
        graph_runner=run_graph,
        workflow_preparer=make_workflow_preparer(app.state.runner_executor),
        poll_interval=100.0,
    )
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            qualification_reference = await _issue_qualification_reference(
                app, canonical_qualification
            )
            evaluation = ReliablePlanEvaluationConfig.model_validate(
                json.loads(QUALIFICATION_FIXTURE.read_text())
            )
            created = await client.post(
                "/api/runs",
                json={
                    "routine_embedded": load_routine_from_path(ROUTINE_PATH).model_dump(
                        mode="json", by_alias=True
                    ),
                    "repo_name": repo.name,
                    "branch": "main",
                    "execution_mode": "graph",
                    "agent_runner_type": "codex_server",
                    "agent_runner_config": {
                        "model": "gpt-5.6-luna",
                        "reasoning_effort": "low",
                    },
                    "reliable_plan_qualification_reference": qualification_reference,
                    "config": {
                        "feature_spec_path": "docs/dynamic-smoke.md",
                        "feature_spec_content": "Produce the dynamic-smoke output.",
                        "acceptance_command": (
                            "test -f docs/graph-approach/dynamic-smoke-output.txt"
                        ),
                        "hidden_oracle_command": (
                            "grep -q dynamic-smoke docs/graph-approach/dynamic-smoke-output.txt"
                        ),
                        "patch_budget": 8,
                        "gap_policy_profile": "standard",
                        "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
                        "reliable_plan_model_assignments": (
                            evaluation.luna_arm.model_dump(mode="json")
                        ),
                    },
                },
            )
            assert created.status_code == 201, created.text
            run_id = created.json()["id"]
            started = await client.post(f"/api/runs/{run_id}/start")
            assert started.status_code == 202, started.text

            await consumer._process_run(run_id)
            await consumer._graph_driver_tasks[run_id]

            fetched = await client.get(f"/api/runs/{run_id}")
            assert fetched.status_code == 200
            body = fetched.json()
            failure_reasons: list[object] = []
            if body["status"] != "completed":
                async with app.state.session_factory() as failed_session:
                    failed_events = await GraphEventStore(failed_session).read_run(run_id)
                failure_reasons = [
                    event.payload.get("reason")
                    for event in failed_events
                    if event.event_type == "node_state_changed"
                    and event.payload.get("new_state") == "failed"
                ]
            assert body["status"] == "completed", (
                body["pause_reason"],
                body["last_error"],
                outcomes,
                failure_reasons,
            )

        assert outcomes and outcomes[0].completed is True, outcomes
        async with app.state.session_factory() as session:
            run = await RunRepository(session).get(run_id)
            graph_events = await GraphEventStore(session).read_run(run_id)
            durable_signals = list(
                (
                    await session.execute(
                        select(EventV2Model.event_type)
                        .where(EventV2Model.aggregate_id == run_id)
                        .where(EventV2Model.event_type.in_(["signal_enqueued", "signal_processed"]))
                        .order_by(EventV2Model.position)
                    )
                ).scalars()
            )
        assert run.agent_runner_type == AgentRunnerType.CODEX_SERVER
        assert run.agent_runner_config == {
            "model": "gpt-5.6-luna",
            "reasoning_effort": "low",
        }
        assert durable_signals == ["signal_enqueued", "signal_processed"]
        projection = await controllers[0].read_projection(run_id)
        records = output_record_payloads_view(projection).values()
        plan = next(
            record
            for record in records
            if record.record_type == "semantic_artifact"
            and getattr(record.value, "semantic_role", None) == "implementation_plan"
        )
        plan_report = next(
            record
            for record in records
            if record.record_type == "verification_report"
            and record.producer_node_id == "verifier-plan"
        )
        assert plan.record_id in plan_report.evaluated_record_ids
        batch_reports = []
        batch_candidates = []
        batch_file_states = []
        for batch in (1, 2):
            candidate = next(
                record
                for record in records
                if record.record_type == "candidate"
                and record.producer_node_id == f"worker-batch-{batch}"
            )
            assert len(candidate.file_state_record_ids) == 1
            file_state_record_id = candidate.file_state_record_ids[0]
            check = next(
                record
                for record in records
                if record.record_type == "check_result"
                and record.producer_node_id == f"check-batch-{batch}"
            )
            report = next(
                record
                for record in records
                if record.record_type == "verification_report"
                and record.producer_node_id == f"verifier-batch-{batch}"
            )
            assert report.evaluated_record_ids == [
                check.record_id,
                "requirement-dynamic-feature-acceptance",
                candidate.record_id,
                file_state_record_id,
            ]
            batch_reports.append(report.record_id)
            batch_candidates.append(candidate.record_id)
            batch_file_states.append(file_state_record_id)
        final_audit = next(
            record
            for record in records
            if record.record_type == "verification_report"
            and record.producer_node_id == "final-audit"
        )
        assert final_audit.evaluated_record_ids[:2] == batch_reports
        assert set(final_audit.evaluated_record_ids[2:]) == {
            *batch_candidates,
            *batch_file_states,
        }
        completion = next(
            record for record in records if record.record_type == "completion_decision"
        )
        assert getattr(completion.value, "status", None) == "passed"
        assert [context.node_kind for context in factory.contexts] == [
            "planner",
            "worker",
            "verifier",
            "planner",
            "worker",
            "verifier",
            "planner",
            "worker",
            "verifier",
            "verifier",
        ]
        assert [context.node_id for context in factory.execution_contexts] == [
            "planner-s-01",
            "worker-discovery",
            "verifier-plan",
            "planner-h1",
            "worker-batch-1",
            "verifier-batch-1",
            "planner-h2",
            "worker-batch-2",
            "verifier-batch-2",
            "final-audit",
        ]
        assert factory.execution_contexts[5] is not factory.execution_contexts[8]
        assert factory.execution_contexts[5].prompt != factory.execution_contexts[8].prompt
        expected_assignments = {
            "planner-s-01": ("planner", "gpt-5.6-sol", "architect"),
            "worker-discovery": ("discovery_worker", "gpt-5.6-luna", "summarizer"),
            "verifier-plan": ("verifier", "gpt-5.6-sol", "coder"),
            "planner-h1": ("successor_planner", "gpt-5.6-luna", "architect"),
            "worker-batch-1": ("implementation_worker", "gpt-5.6-luna", "coder"),
            "verifier-batch-1": ("verifier", "gpt-5.6-sol", "coder"),
            "planner-h2": ("successor_planner", "gpt-5.6-luna", "architect"),
            "worker-batch-2": ("implementation_worker", "gpt-5.6-luna", "coder"),
            "verifier-batch-2": ("verifier", "gpt-5.6-sol", "coder"),
            "final-audit": ("verifier", "gpt-5.6-sol", "coder"),
        }
        for node_id, (role, model, profile) in expected_assignments.items():
            created_index, created_event = next(
                (index, event)
                for index, event in enumerate(graph_events)
                if event.event_type == "node_created" and event.payload.get("node_id") == node_id
            )
            payload = created_event.payload
            assert payload.get("reliable_plan_assignment_role") == role
            assert (payload.get("runner_model_override"), payload.get("profile")) == (
                model,
                profile,
            )
            assert factory.effective_configs[node_id] == {
                "model": model,
                "reasoning_effort": "low",
            }
            assert len(created_event.model_dump_json().encode("utf-8")) <= (
                MAX_EVENT_ENVELOPE_BYTES
            )
            replayed_at_creation = build_projection(graph_events[: created_index + 1])
            replayed_payload = node_payload_view(replayed_at_creation, node_id)
            assert replayed_payload is not None
            assert (
                replayed_payload["reliable_plan_assignment_carrier"]
                == payload["reliable_plan_assignment_carrier"]
            )
            checkpoint = projection_to_checkpoint(
                replayed_at_creation,
                position=created_event.position,
            )
            checkpoint_payload = node_payload_view(
                projection_from_checkpoint(checkpoint),
                node_id,
            )
            assert checkpoint_payload is not None
            assert (
                checkpoint_payload["reliable_plan_assignment_carrier"]
                == payload["reliable_plan_assignment_carrier"]
            )

        def event_position(
            event_type: str,
            node_id: str,
            *,
            state: str | None = None,
        ) -> int:
            return next(
                event.position
                for event in graph_events
                if event.event_type == event_type
                and event.payload.get("node_id") == node_id
                and (state is None or event.payload.get("new_state") == state)
            )

        h1_created = event_position("node_created", "worker-batch-1")
        h2_created = event_position("node_created", "worker-batch-2")
        assert "worker-batch-2" not in {
            event.payload.get("node_id")
            for event in graph_events
            if event.position
            < event_position("node_state_changed", "verifier-batch-1", state="completed")
        }
        assert event_position("node_state_changed", "verifier-plan", state="completed") < h1_created
        assert (
            event_position("node_state_changed", "verifier-batch-1", state="completed") < h2_created
        )
        assert event_position("node_state_changed", "check-batch-1", state="completed") < h2_created
        assert (
            event_position("node_state_changed", "worker-batch-2", state="completed") > h2_created
        )
        assert event_position("node_state_changed", "check-batch-2", state="completed")
    finally:
        await consumer.stop()
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_api_correction_uses_exact_failure_evidence_then_completes_horizon_two(
    tmp_path: Path,
    canonical_qualification: Any,
) -> None:
    harness = await _make_joined_harness(
        tmp_path,
        canonical_qualification,
        scenario="correction",
    )
    try:
        run_id = await harness.create_and_start()
        await harness.drain_start(run_id)
        outcome = await harness.wait_driver(run_id)
        response = await harness.client.get(f"/api/runs/{run_id}")
        assert response.json()["status"] == "completed", (
            response.json(),
            outcome,
        )

        events = await harness.events(run_id)
        projection = await harness.controllers[-1].read_projection(run_id)
        records = list(output_record_payloads_view(projection).values())
        failed_report = next(
            record
            for record in records
            if record.producer_node_id == "verifier-batch-1"
            and record.record_type == "verification_report"
        )
        failed_check = next(
            record
            for record in records
            if record.producer_node_id == "check-batch-1" and record.record_type == "check_result"
        )
        classified_gap = next(
            record
            for record in records
            if record.producer_node_id == "planner-gap-batch-1" and record.port == "classified_gap"
        )
        corrective_payload = node_payload_view(projection, "worker-corrective-batch-1")
        assert corrective_payload is not None
        assert corrective_payload["failed_verification_record_id"] == failed_report.record_id
        assert corrective_payload["failed_check_record_ids"] == [failed_check.record_id]
        assert corrective_payload["classified_gap_record_id"] == classified_gap.record_id
        assert corrective_payload["base_snapshot_selection"] == "rejected_candidate"
        assert corrective_payload["base_snapshot_candidate_id"] == failed_report.candidate_id
        assert corrective_payload["recovery_reason"] == "failed_verification"
        assert corrective_payload["recovery_of_node_id"] == failed_report.producer_node_id
        assert corrective_payload["recovery_of_record_id"] == failed_report.record_id
        corrective_verifier = node_payload_view(projection, "verifier-corrective-batch-1")
        assert corrective_verifier is not None
        assert corrective_verifier["recovery_reason"] == "failed_verification"
        assert corrective_verifier["recovery_of_node_id"] == failed_report.producer_node_id
        assert corrective_verifier["recovery_of_record_id"] == failed_report.record_id
        corrective_candidate = next(
            record for record in records if record.record_id == "candidate-corrective-batch-1"
        )
        assert corrective_candidate.supersedes_task_region_id == "batch-1"
        assert all(
            state == "accepted"
            for region_id, state in task_states_view(projection).items()
            if region_id != "final-invariant-region"
        )
        assert output_record_payloads_view(projection)[failed_report.record_id] == failed_report
        assert output_record_payloads_view(projection)[failed_check.record_id] == failed_check

        def position(event_type: str, node_id: str, *, state: str | None = None) -> int:
            return next(
                event.position
                for event in events
                if event.event_type == event_type
                and event.payload.get("node_id") == node_id
                and (state is None or event.payload.get("new_state") == state)
            )

        assert (
            position("node_created", "planner-gap-batch-1")
            < position("node_state_changed", "verifier-batch-1", state="completed")
            < position("node_created", "worker-corrective-batch-1")
            < position(
                "node_state_changed",
                "verifier-corrective-batch-1",
                state="completed",
            )
            < position("node_created", "worker-batch-2")
        )
        assert not any(event.event_type == "runtime_retry_scheduled" for event in events)
        completion = next(
            record for record in records if record.record_type == "completion_decision"
        )
        assert getattr(completion.value, "status", None) == "passed"
    finally:
        await harness.close()


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_api_cancel_waits_for_runner_recovery_before_terminal_state(
    tmp_path: Path,
    canonical_qualification: Any,
) -> None:
    harness = await _make_joined_harness(
        tmp_path,
        canonical_qualification,
        scenario="cancel",
    )
    try:
        run_id = await harness.create_and_start()
        await harness.drain_start(run_id)
        await asyncio.wait_for(harness.factory.latched.wait(), timeout=10)
        assert harness.process_registry.run_owner_count(run_id) == 1

        requested = await harness.client.post(f"/api/runs/{run_id}/cancel")
        assert requested.status_code == 202, requested.text
        assert requested.json()["status"] == "stopping"
        await harness.consumer._process_run(run_id)

        response = await harness.client.get(f"/api/runs/{run_id}")
        assert response.json()["status"] == "cancelled"
        assert harness.factory.cancelled.is_set()
        assert harness.process_registry.run_owner_count(run_id) == 0
        assert harness.consumer.graph_driver_ownership(run_id).owned is False

        events = await harness.events(run_id)
        projection = await harness.controllers[-1].read_projection(run_id)
        worker_attempt = next(
            attempt
            for attempt in execution_attempts_view(projection).values()
            if attempt.node_id == "worker-batch-1"
        )
        assert worker_attempt.state == "recovered"
        assert worker_attempt.recovery_reason == "cancelled"
        assert all(lease.state != "active" for lease in leases_view(projection).values())

        recovery_requested = next(
            event.position
            for event in events
            if event.event_type == "runner_recovery_requested"
            and event.payload.get("node_id") == "worker-batch-1"
        )
        recovery_completed = next(
            event.position
            for event in events
            if event.event_type == "runner_recovery_completed"
            and event.payload.get("node_id") == "worker-batch-1"
        )
        graph_cancelled = next(
            event.position
            for event in events
            if event.event_type == "run_lifecycle_changed"
            and event.payload.get("to_state") == "cancelled"
        )
        assert recovery_requested < recovery_completed < graph_cancelled
        assert not any(
            event.event_type in {"runtime_retry_scheduled", "lease_granted"}
            and recovery_completed < event.position < graph_cancelled
            for event in events
        )
    finally:
        await harness.close()


@pytest.mark.asyncio
@pytest.mark.timeout(90)
async def test_server_restart_recovers_before_redispatch_without_duplicate_records(
    tmp_path: Path,
    canonical_qualification: Any,
) -> None:
    harness = await _make_joined_harness(
        tmp_path,
        canonical_qualification,
        scenario="restart_latch",
    )
    restarted_consumer: SignalConsumer | None = None
    try:
        run_id = await harness.create_and_start()
        await harness.drain_start(run_id)
        await asyncio.wait_for(harness.factory.latched.wait(), timeout=10)
        assert harness.process_registry.run_owner_count(run_id) == 1

        await harness.consumer.stop()
        response = await harness.client.get(f"/api/runs/{run_id}")
        assert response.json()["status"] == "paused"
        assert response.json()["pause_reason"] == "server_shutdown"
        assert harness.factory.cancelled.is_set()
        assert harness.process_registry.run_owner_count(run_id) == 0

        shutdown_events = await harness.events(run_id)
        recovery_completed = next(
            event.position
            for event in shutdown_events
            if event.event_type == "runner_recovery_completed"
            and event.payload.get("node_id") == "worker-batch-1"
        )
        assert not any(
            event.event_type == "lease_granted" and event.position > recovery_completed
            for event in shutdown_events
        )

        new_registry = RunnerOwnedProcessRegistry()

        def runtime_builder(
            sessions: Any,
            clock: Any,
            ids: Any,
            *,
            worktree_path: str | Path,
            runner_type: AgentRunnerType,
            runner_config: dict[str, Any] | None = None,
            artifact_store: Any,
            process_registry: RunnerOwnedProcessRegistry,
        ) -> tuple[GraphController, GraphDispatchExecutor]:
            del runner_config
            assert runner_type == AgentRunnerType.CODEX_SERVER
            assert process_registry is new_registry
            controller = GraphController(sessions, clock, ids, auto_dispatch=False)
            harness.controllers.append(controller)
            return controller, GraphDispatchExecutor(
                sessions,
                controller,
                harness.factory,
                worktree_path=Path(worktree_path),
                artifact_store=artifact_store,
                process_registry=process_registry,
            )

        new_driver = GraphRunDriver(
            harness.app.state.session_factory,
            harness.create_service,
            runtime_builder=runtime_builder,
            process_registry=new_registry,
        )
        restarted_outcomes: list[Any] = []

        async def run_graph(received_run_id: str) -> None:
            restarted_outcomes.append(await new_driver.run(received_run_id))

        restarted_consumer = SignalConsumer(
            harness.app.state.session_factory,
            harness.create_service,
            graph_runner=run_graph,
            graph_execution_quiescence_preparer=new_registry.prepare_run_quiescence,
            graph_execution_quiescer=new_registry.quiesce_run,
            graph_safe_effect_drainer=new_driver.quiesce_run,
            graph_owner_checker=new_registry.has_run_owners,
            workflow_preparer=make_workflow_preparer(harness.app.state.runner_executor),
            poll_interval=100.0,
        )
        resumed = await harness.client.post(f"/api/runs/{run_id}/resume", json={})
        assert resumed.status_code == 202, resumed.text
        await restarted_consumer._process_run(run_id)
        await restarted_consumer._graph_driver_tasks[run_id]

        response = await harness.client.get(f"/api/runs/{run_id}")
        assert response.json()["status"] == "completed", (response.json(), restarted_outcomes)
        events = await harness.events(run_id)
        redispatch = next(
            event.position
            for event in events
            if event.event_type == "lease_granted"
            and event.payload.get("node_id") == "worker-batch-1"
            and event.position > recovery_completed
        )
        assert recovery_completed < redispatch
        projection = await harness.controllers[-1].read_projection(run_id)
        record_ids = list(output_record_payloads_view(projection))
        assert len(record_ids) == len(set(record_ids))
        worker_attempts = [
            attempt
            for attempt in execution_attempts_view(projection).values()
            if attempt.node_id == "worker-batch-1"
        ]
        assert len(worker_attempts) == 2
        assert {attempt.state for attempt in worker_attempts} == {"recovered", "finalized"}
        assert new_registry.run_owner_count(run_id) == 0
        assert all(lease.state != "active" for lease in leases_view(projection).values())
    finally:
        if restarted_consumer is not None:
            await restarted_consumer.stop()
        await harness.client.aclose()
        await harness.app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_oversized_discovery_exhausts_bounded_retries_and_blocks_publicly(
    tmp_path: Path,
    canonical_qualification: Any,
) -> None:
    harness = await _make_joined_harness(
        tmp_path,
        canonical_qualification,
        scenario="oversized",
    )
    try:
        run_id = await harness.create_and_start()
        await harness.drain_start(run_id)
        outcome = await harness.wait_driver(run_id)
        response = await harness.client.get(f"/api/runs/{run_id}")
        assert response.json()["status"] == "paused"
        assert response.json()["pause_reason"] == "graph_blocked"
        assert "maximum is 32768 bytes" in response.json()["last_error"]
        assert outcome.completed is False
        assert harness.factory.discovery_attempts == 3

        events = await harness.events(run_id)
        projection = await harness.controllers[-1].read_projection(run_id)
        assert sum(event.event_type == "runtime_retry_scheduled" for event in events) == 2
        assert [context.node_id for context in harness.factory.execution_contexts] == [
            "planner-s-01",
            "worker-discovery",
            "worker-discovery",
            "worker-discovery",
        ]
        assert all(lease.state != "active" for lease in leases_view(projection).values())
        assert harness.process_registry.run_owner_count(run_id) == 0
    finally:
        await harness.close()
