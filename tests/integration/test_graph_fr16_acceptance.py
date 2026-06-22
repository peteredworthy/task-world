from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api import create_app
from orchestrator.config import AgentRunnerType, RunStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db import init_db
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
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
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import GraphRunDriver, WorkflowService


@pytest.fixture
async def fr16_app(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncClient, Any], None]:
    app = create_app(db_path=str(tmp_path / "fr16-app.db"), routine_dirs=[])
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


class CodexSubmitAgent:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CODEX_SERVER, name="codex-submit")

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
        path = Path(context.working_dir, "docs/fr16-acceptance.txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"artifact from {context.task_id}\n")
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class CodexPlannerPatchAgent(CodexSubmitAgent):
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
                "patch_id": f"{context.node_id}-fr16-noop",
                "base_graph_position": 0,
                "ops": [],
            }
        )
        assert "accepted" in feedback
        await on_submit()
        return ExecutionResult(success=True)


class CodexGradingAgent(CodexSubmitAgent):
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
        await on_grade("req-1", "A", "accepted by FR-16 harness")
        await on_submit()
        return ExecutionResult(success=True)


class CodexRaisingAgent(CodexSubmitAgent):
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
        raise RuntimeError("fr16 terminal failure")


def _routine(*, planner: bool = False, max_attempts: int = 3) -> RoutineConfig:
    steps: list[dict[str, Any]] = []
    if planner:
        steps.append({"id": "plan", "kind": "planner", "title": "Plan"})
    steps.append(
        {
            "id": "step-1",
            "title": "Step 1",
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Produce artifact",
                    "task_context": "Write the FR-16 acceptance artifact.",
                    "artifacts": [{"path": "docs/fr16-acceptance.txt"}],
                    "retry": {"max_attempts": max_attempts},
                    "requirements": [{"id": "req-1", "desc": "Requirement passes."}],
                    "verifier": {
                        "rubric": [{"id": "req-1", "text": "The artifact is acceptable."}]
                    },
                }
            ],
        }
    )
    return RoutineConfig.model_validate(
        {
            "id": "fr16-acceptance",
            "name": "FR-16 Acceptance",
            "execution_mode": "graph",
            "planner_generation_budget": 1 if planner else 0,
            "steps": steps,
        }
    )


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# fr16 acceptance\n")
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
    agent_runner_type: AgentRunnerType = AgentRunnerType.CODEX_SERVER,
) -> None:
    run = create_run_from_routine(routine, repo_name=repo.name, source_branch="main")
    run.id = run_id
    run.execution_mode = "graph"
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.worktree_path = str(repo)
    run.agent_runner_type = agent_runner_type
    async with session_factory() as session:
        await WorkflowService(session).create_run(run)


def _driver(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    repo: Path,
    run_id: str,
    agents: dict[str, AgentRunner],
    clock: FixedClock | None = None,
) -> GraphRunDriver:
    fixed_clock = clock or FixedClock()
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
            AgentFactory(agents),
            worktree_path=repo,
        )
        return controller, executor

    return GraphRunDriver(
        session_factory,
        _create_service,
        clock=fixed_clock,
        id_gen=ids,
        runtime_builder=runtime_builder,
    )


async def _read_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
):
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _get_json(client: AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200
    return response.json()


def _run_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


async def test_fr16_supported_codex_callbacks_complete_and_read_back(
    fr16_app: tuple[AsyncClient, Any],
    tmp_path: Path,
) -> None:
    client, app = fr16_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    repo = tmp_path / "fr16-supported"
    _init_repo(repo)
    run_id = _run_id("fr16-supported-callbacks")
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)

    outcome = await _driver(
        session_factory,
        repo=repo,
        run_id=run_id,
        agents={"worker": CodexSubmitAgent(), "verifier": CodexGradingAgent()},
    ).run(run_id)

    assert outcome.completed is True
    run = await _get_json(client, f"/api/runs/{run_id}")
    graph = await _get_json(client, f"/api/runs/{run_id}/graph")
    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    node = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/worker-step-1-task-1?payload_mode=full",
    )
    scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")
    blockers = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")

    event_types = [event["event_type"] for event in events]
    output_types = [record["record_type"] for record in node["output_records"]]
    assert run["status"] == "completed"
    assert run["execution_mode"] == "graph"
    assert run["agent_runner_type"] == "codex_server"
    assert graph["run_state"] == "completed"
    assert graph["node_states"]["worker-step-1-task-1"] == "completed"
    assert "heartbeat_recorded" in event_types
    assert "lease_renewed" in event_types
    assert "callback_accepted" in event_types
    assert "candidate" in output_types
    assert "artifact_reference" in output_types
    assert scheduler["leases"] == {"active": [], "suspended": []}
    assert blockers["blockers"] == []


async def test_fr16_submit_graph_patch_callback_is_required_and_readable(
    fr16_app: tuple[AsyncClient, Any],
    tmp_path: Path,
) -> None:
    client, app = fr16_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    repo = tmp_path / "fr16-patch"
    _init_repo(repo)
    run_id = _run_id("fr16-submit-graph-patch")
    await _create_graph_run(session_factory, _routine(planner=True), run_id=run_id, repo=repo)

    outcome = await _driver(
        session_factory,
        repo=repo,
        run_id=run_id,
        agents={
            "planner": CodexPlannerPatchAgent(),
            "worker": CodexSubmitAgent(),
            "verifier": CodexGradingAgent(),
        },
    ).run(run_id)

    assert outcome.completed is True
    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    planner = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/planner-plan?payload_mode=full",
    )
    event_types = [event["event_type"] for event in events]
    assert "graph_patch_accepted" in event_types
    assert "callback_accepted" in event_types
    assert "callback_accepted" in [event["event_type"] for event in planner["callback_history"]]


async def test_fr16_stale_callback_rejection_is_readable(
    fr16_app: tuple[AsyncClient, Any],
    tmp_path: Path,
) -> None:
    client, app = fr16_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    repo = tmp_path / "fr16-stale"
    _init_repo(repo)
    run_id = _run_id("fr16-stale-callback")
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)
    driver = _driver(
        session_factory,
        repo=repo,
        run_id=run_id,
        agents={"worker": CodexSubmitAgent(), "verifier": CodexGradingAgent()},
    )
    await driver.run(run_id)

    events = await _read_events(session_factory, run_id)
    lease = next(
        event.payload
        for event in events
        if event.event_type == "lease_granted"
        and event.payload.get("node_id") == "worker-step-1-task-1"
    )
    controller = GraphController(
        session_factory,
        FixedClock(),
        SequentialIds(f"{run_id}-stale"),
        auto_dispatch=False,
    )
    position = await controller.current_position(run_id)
    await controller.handle_command(
        run_id,
        position,
        "submit_callback",
        {
            "node_id": "worker-step-1-task-1",
            "execution_id": lease["execution_id"],
            "lease_id": lease["lease_id"],
            "lease_generation": lease["generation"],
            "base_snapshot_id": lease["base_snapshot_id"],
            "observed_graph_position": position,
            "idempotency_key": "fr16-stale-after-terminal",
            "payload_hash": "fr16-stale",
            "payload": {"payload_hash": "fr16-stale", "output_records": []},
        },
    )

    graph = await _get_json(client, f"/api/runs/{run_id}/graph")
    events_json = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")
    event_types = [event["event_type"] for event in events_json]
    assert graph["run_state"] == "completed"
    assert "callback_rejected_stale" in event_types
    assert scheduler["leases"] == {"active": [], "suspended": []}


async def test_fr16_unsupported_runner_fails_before_graph_seeding(
    fr16_app: tuple[AsyncClient, Any],
    tmp_path: Path,
) -> None:
    client, app = fr16_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    repo = tmp_path / "fr16-unsupported"
    _init_repo(repo)
    run_id = _run_id("fr16-unsupported-runner")
    await _create_graph_run(
        session_factory,
        _routine(),
        run_id=run_id,
        repo=repo,
        agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
    )

    outcome = await _driver(
        session_factory,
        repo=repo,
        run_id=run_id,
        agents={"worker": CodexSubmitAgent(), "verifier": CodexGradingAgent()},
    ).run(run_id)

    run = await _get_json(client, f"/api/runs/{run_id}")
    assert outcome.completed is False
    assert run["status"] == "paused"
    assert run["pause_reason"] == "graph_runner_unsupported"
    assert await _read_events(session_factory, run_id) == []


async def test_fr16_terminal_exhausted_failure_record_callback_readbacks(
    fr16_app: tuple[AsyncClient, Any],
    tmp_path: Path,
) -> None:
    client, app = fr16_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    repo = tmp_path / "fr16-terminal-failure"
    _init_repo(repo)
    run_id = _run_id("fr16-terminal-failure")
    await _create_graph_run(
        session_factory,
        _routine(max_attempts=2),
        run_id=run_id,
        repo=repo,
    )

    outcome = await _driver(
        session_factory,
        repo=repo,
        run_id=run_id,
        agents={"worker": CodexRaisingAgent(), "verifier": CodexGradingAgent()},
    ).run(run_id)

    assert outcome.completed is False
    run = await _get_json(client, f"/api/runs/{run_id}")
    graph = await _get_json(client, f"/api/runs/{run_id}/graph")
    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    node = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/worker-step-1-task-1?payload_mode=full",
    )
    scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")
    blockers = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")

    event_types = [event["event_type"] for event in events]
    failure_records = [
        record for record in node["output_records"] if record["record_type"] == "failure_record"
    ]
    assert run["status"] == RunStatus.PAUSED.value
    assert run["pause_reason"] == "graph_blocked"
    assert graph["run_state"] == "paused"
    assert graph["node_states"]["worker-step-1-task-1"] == "failed"
    assert event_types.count("agent_died") == 2
    assert "runtime_retry_scheduled" in event_types
    assert len(failure_records) == 1
    failure = failure_records[0]
    assert failure["value"]["error_class"] == "max_attempts_exhausted"
    assert failure["value"]["retryable"] is False
    assert failure["value"]["attempt_number"] == 2
    assert failure["value"]["max_attempts"] == 2
    assert scheduler["leases"] == {"active": [], "suspended": []}
    assert blockers["blockers"]
