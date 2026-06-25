from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api import create_app
from orchestrator.config import AgentRunnerType, RunStatus, RoutineConfig
from orchestrator.db import init_db
from orchestrator.graph_runtime import GraphController, GraphDispatchContext, GraphDispatchExecutor
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
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import GraphRunDriver, WorkflowService


@pytest.fixture
async def final_gate_app(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncClient, Any], None]:
    app = create_app(db_path=str(tmp_path / "fr14-final-gate.db"), routine_dirs=[])
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app
    await app.state.engine.dispose()


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class SequentialIds:
    def __init__(self, namespace: str) -> None:
        self._namespace = namespace
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{self._namespace}-{prefix}-{self._next}"
        self._next += 1
        return value


class AgentFactory:
    def __init__(self, agents: dict[str, AgentRunner]) -> None:
        self._agents = agents

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        return self._agents[context.node_kind]


class PlannerFinalGateAgent:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CODEX_SERVER, name="planner")

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
        feedback = await context.graph_patch_callback(
            {
                "patch_id": "patch-fr14-final-gate",
                "base_graph_position": 0,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "final-gate-s-01-t-01",
                            "kind": "final_gate",
                            "role": "final_gate",
                            "state": "planned",
                            "task_region_id": "s-01/t-01",
                        },
                    },
                    {
                        "op": "create_edge",
                        "edge_id": "edge-fr14-check-final-gate",
                        "from_node_id": "check-s-01-t-01-auto_verify-acceptance",
                        "from_port": "check_result",
                        "to_node_id": "final-gate-s-01-t-01",
                        "to_port": "check_result",
                        "required": True,
                        "accepted_record_selector": {"record_kinds": ["check_result"]},
                    },
                ],
            }
        )
        assert "accepted" in feedback
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class WorkerAgent(PlannerFinalGateAgent):
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CODEX_SERVER, name="worker")

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
        artifact = Path(context.working_dir, "docs/fr14-final-gate.txt")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("final gate acceptance\n")
        await on_submit()
        return ExecutionResult(success=True)


class VerifierAgent(PlannerFinalGateAgent):
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CODEX_SERVER, name="verifier")

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
        assert on_grade is not None
        await on_grade("req-1", "A", "final gate evidence is complete")
        await on_submit()
        return ExecutionResult(success=True)


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "fr14-final-gate-acceptance",
            "name": "FR-14 Final Gate Acceptance",
            "execution_mode": "graph",
            "planner_generation_budget": 1,
            "steps": [
                {"id": "plan", "kind": "planner", "title": "Plan final gate"},
                {
                    "id": "s-01",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "t-01",
                            "title": "Produce gated artifact",
                            "task_context": "Write the final-gate acceptance artifact.",
                            "artifacts": [{"path": "docs/fr14-final-gate.txt"}],
                            "requirements": [{"id": "req-1", "desc": "Artifact is accepted."}],
                            "verifier": {
                                "rubric": [{"id": "req-1", "text": "Artifact is accepted."}]
                            },
                            "auto_verify": {
                                "items": [
                                    {
                                        "id": "acceptance",
                                        "cmd": "test -f docs/fr14-final-gate.txt",
                                    }
                                ]
                            },
                        }
                    ],
                },
            ],
        }
    )


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# final gate acceptance\n")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


async def _create_service(session: AsyncSession) -> WorkflowService:
    return WorkflowService(session)


async def _create_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    routine: RoutineConfig,
    *,
    run_id: str,
    repo: Path,
) -> None:
    run = create_run_from_routine(routine, repo_name=repo.name, source_branch="main")
    run.id = run_id
    run.execution_mode = "graph"
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.worktree_path = str(repo)
    run.agent_runner_type = AgentRunnerType.CODEX_SERVER
    async with session_factory() as session:
        await WorkflowService(session).create_run(run)


def _driver(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    repo: Path,
    run_id: str,
) -> GraphRunDriver:
    clock = FixedClock()
    ids = SequentialIds(run_id)

    def runtime_builder(
        session_factory_arg: async_sessionmaker[AsyncSession],
        clock_arg: Any,
        id_gen_arg: Any,
        *,
        worktree_path: str | Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        controller = GraphController(
            session_factory_arg, clock_arg, id_gen_arg, auto_dispatch=False
        )
        executor = GraphDispatchExecutor(
            session_factory_arg,
            controller,
            AgentFactory(
                {
                    "planner": PlannerFinalGateAgent(),
                    "worker": WorkerAgent(),
                    "verifier": VerifierAgent(),
                }
            ),
            worktree_path=repo,
        )
        return controller, executor

    return GraphRunDriver(
        session_factory,
        _create_service,
        clock=clock,
        id_gen=ids,
        runtime_builder=runtime_builder,
    )


async def _get_json(client: AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200
    return response.json()


def _run_id() -> str:
    return f"fr14-final-gate-{uuid4().hex[:8]}"


async def test_final_gate_completion_decision_and_region_readbacks(
    final_gate_app: tuple[AsyncClient, Any],
    tmp_path: Path,
) -> None:
    client, app = final_gate_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    repo = tmp_path / "fr14-final-gate"
    _init_repo(repo)
    run_id = _run_id()
    routine = _routine()
    await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)

    outcome = await _driver(session_factory, repo=repo, run_id=run_id).run(run_id)

    assert outcome.completed is True, outcome.blocked_reason
    run = await _get_json(client, f"/api/runs/{run_id}")
    graph = await _get_json(client, f"/api/runs/{run_id}/graph")
    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    gate = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/final-gate-s-01-t-01?payload_mode=full",
    )
    topology = await _get_json(client, f"/api/runs/{run_id}/graph/topology")
    regions = await _get_json(client, f"/api/runs/{run_id}/graph/regions")
    blockers = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")
    scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")

    completion_decisions = [
        event
        for event in events
        if event["event_type"] == "output_record_accepted"
        and event["payload"].get("record_type") == "completion_decision"
    ]
    assert len(completion_decisions) == 1
    decision_event = completion_decisions[0]
    decision = decision_event["payload"]
    assert decision["record_id"]
    assert decision["record_kind"] == "output"
    assert decision["record_type"] == "completion_decision"
    assert decision["producer_node_id"] == "final-gate-s-01-t-01"
    assert decision["port"] == "completion_decision"
    assert decision["schema"] == "CompletionDecision"
    assert decision["value"] == {"status": "passed", "blockers": []}
    assert decision["provenance"] == {"source": "final_gate_evaluated"}
    assert decision_event["run_id"] == run_id
    assert decision_event["position"] > 0
    assert decision_event["timestamp"]

    assert run["status"] == RunStatus.COMPLETED.value
    assert run["execution_mode"] == "graph"
    assert run["agent_runner_type"] == "codex_server"
    assert graph["run_state"] == "completed"
    assert graph["node_states"]["final-gate-s-01-t-01"] == "completed"
    assert scheduler["leases"] == {"active": [], "suspended": []}
    assert blockers["blockers"] == []
    region = next(
        region for region in regions["regions"] if region["task_region_id"] == "s-01/t-01"
    )
    assert region["state"] == "accepted"

    assert gate["kind"] == "final_gate"
    assert gate["role"] == "final_gate"
    assert gate["state"] == "completed"
    assert gate["task_region_id"] == "s-01/t-01"
    final_edge = next(
        edge for edge in topology["edges"] if edge["edge_id"] == "edge-fr14-check-final-gate"
    )
    assert gate["input_ports"] == {"check_result": final_edge["binding"]["record_ids"]}
    assert len(gate["output_records"]) == 1
    gate_record = gate["output_records"][0]
    assert gate_record["record_id"] == decision["record_id"]
    assert gate_record["record_kind"] == "output"
    assert gate_record["record_type"] == "completion_decision"
    assert gate_record["schema"] == "CompletionDecision"
    assert gate_record["producer_node_id"] == "final-gate-s-01-t-01"
    assert gate_record["producer_port"] == "completion_decision"
    assert gate_record["run_id"] == run_id
    assert gate_record["created_at"]
    assert gate_record["graph_position"] == decision_event["position"]
    assert gate_record["value"] == {"status": "passed", "blockers": []}
    assert gate_record["provenance"] == {"source": "final_gate_evaluated"}
    callback_types = [event["event_type"] for event in gate["callback_history"]]
    assert callback_types == ["node_state_changed"]
    assert gate["callback_history"][0]["payload"]["trigger"] == "runtime_start_acknowledged"
    completion_events = [
        event
        for event in gate["events"]
        if event["event_type"] == "node_state_changed"
        and event["payload"].get("trigger") == "final_gate_evaluated"
    ]
    assert len(completion_events) == 1
    completed_event = completion_events[0]["payload"]
    assert completed_event["completion_status"] == "passed"
    assert completed_event["completion_decision_record_id"] == decision["record_id"]

    assert final_edge["binding"]["binding_policy"] == "bind_first"
    assert final_edge["binding"]["to_node_id"] == "final-gate-s-01-t-01"
    assert final_edge["binding"]["to_port"] == "check_result"
    assert final_edge["binding"]["record_ids"]
    assert final_edge["bound_records"][0]["record_type"] == "check_result"
    assert final_edge["bound_records"][0]["producer_port"] == "check_result"

    candidate_position = next(
        event["position"]
        for event in events
        if event["event_type"] == "output_record_accepted"
        and event["payload"].get("record_type") == "candidate"
    )
    file_state_position = next(
        event["position"] for event in events if event["event_type"] == "file_state_accepted"
    )
    verification_position = next(
        event["position"]
        for event in events
        if event["event_type"] == "output_record_accepted"
        and event["payload"].get("record_type") == "verification_report"
    )
    check_position = next(
        event["position"]
        for event in events
        if event["event_type"] == "output_record_accepted"
        and event["payload"].get("record_type") == "check_result"
    )
    assert (
        max(
            candidate_position,
            file_state_position,
            verification_position,
            check_position,
        )
        < decision_event["position"]
    )
