from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.api import create_app
from orchestrator.config import AgentRunnerType, GlobalConfig, PathsConfig, RoutineConfig
from orchestrator.config.enums import RunStatus
from orchestrator.db import RunRepository, create_engine, create_session_factory, init_db
from orchestrator.graph import project_run_state, project_task_states
from orchestrator.graph_runtime import GraphController, GraphDispatchContext, GraphDispatchExecutor
from orchestrator.graph_runtime.store import GraphEventStore
from orchestrator.runners import AgentRunner, OutputBatcher
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


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class SequentialIds:
    def __init__(self) -> None:
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value


class AgentFactory:
    def __init__(self, agents: dict[str, AgentRunner], dispatch_order: list[str]) -> None:
        self._agents = agents
        self._dispatch_order = dispatch_order

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        self._dispatch_order.append(context.node_kind)
        return self._agents[context.node_kind]


class CompletingAgent:
    def __init__(self, *, grade: str | None = None, lines: list[str] | None = None) -> None:
        self._grade = grade
        self._lines = lines or ["graph default carrier output"]

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="complete")

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
        if self._grade is not None and on_grade is not None:
            await on_grade("req-1", self._grade, None)
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph-default-carrier.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# tmp repo\n")
    (path / "inputs").mkdir()
    (path / "inputs" / "one.txt").write_text("one\n")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "add", "README.md", "inputs/one.txt"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
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


def _routine_payload(
    routine_id: str = "default-carrier",
    *,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": routine_id,
        "name": routine_id.replace("-", " ").title(),
        "steps": [
            {
                "id": "step-1",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Task 1",
                        "task_context": "Complete the task.",
                        "requirements": [{"id": "req-1", "desc": "Requirement passes."}],
                        "verifier": {
                            "rubric": [
                                {
                                    "id": "req-1",
                                    "text": "Does the implementation satisfy req-1?",
                                }
                            ]
                        },
                    }
                ],
            }
        ],
    }
    if execution_mode is not None:
        payload["execution_mode"] = execution_mode
    return payload


def _single_step_routine() -> RoutineConfig:
    return RoutineConfig.model_validate(_routine_payload("single-step"))


def _fan_out_routine() -> RoutineConfig:
    payload = _routine_payload("fan-out")
    task = payload["steps"][0]["tasks"][0]
    task.pop("task_context")
    task["fan_out"] = {
        "input_glob": "inputs/*.txt",
        "output_pattern": "outputs/{stem}.md",
        "per_item_prompt": "Summarize each input.",
    }
    return RoutineConfig.model_validate(payload)


def _auto_verify_routine() -> RoutineConfig:
    payload = _routine_payload("auto-verify")
    task = payload["steps"][0]["tasks"][0]
    task["auto_verify"] = {"items": [{"id": "check-readme", "cmd": "test -f README.md"}]}
    return RoutineConfig.model_validate(payload)


def _checklist_gate_routine() -> RoutineConfig:
    payload = _routine_payload("checklist-gate")
    payload["steps"][0]["tasks"][0]["requirements"].append(
        {"id": "req-2", "desc": "A second checklist item is present."}
    )
    return RoutineConfig.model_validate(payload)


def _global_config(tmp_path: Path, *, default_execution_mode: str = "graph") -> GlobalConfig:
    config = GlobalConfig(
        paths=PathsConfig(
            repos_dir=str(tmp_path / "repos"),
            worktrees_dir=str(tmp_path / "worktrees"),
        )
    )
    config.execution.default_execution_mode = default_execution_mode  # type: ignore[assignment]
    return config


async def _create_api_client(
    tmp_path: Path,
    *,
    default_execution_mode: str = "graph",
) -> AsyncGenerator[tuple[AsyncClient, Path], None]:
    config = _global_config(tmp_path, default_execution_mode=default_execution_mode)
    repos_dir = Path(config.paths.repos_dir)
    worktrees_dir = Path(config.paths.worktrees_dir)
    repos_dir.mkdir()
    worktrees_dir.mkdir()
    repo = repos_dir / "repo"
    _init_repo(repo)

    app = create_app(
        db_path=":memory:",
        routine_dirs=[],
        global_config=config,
    )
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, repo
    await app.state.engine.dispose()


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
    dispatch_order: list[str],
    on_agent_output: Any = None,
) -> GraphRunDriver:
    clock = FixedClock()
    ids = SequentialIds()
    agents = {
        "planner": CompletingAgent(),
        "worker": CompletingAgent(),
        "verifier": CompletingAgent(grade="A"),
        "check": CompletingAgent(),
    }

    def runtime_builder(
        session_factory_arg: async_sessionmaker[AsyncSession],
        clock_arg: Any,
        id_gen_arg: Any,
        *,
        worktree_path: str | Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
        on_agent_output: Any = None,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        controller = GraphController(
            session_factory_arg, clock_arg, id_gen_arg, auto_dispatch=False
        )
        executor = GraphDispatchExecutor(
            session_factory_arg,
            controller,
            AgentFactory(agents, dispatch_order),
            worktree_path=repo,
            on_agent_output=on_agent_output,
        )
        return controller, executor

    return GraphRunDriver(
        session_factory,
        _create_service,
        clock=clock,
        id_gen=ids,
        runtime_builder=runtime_builder,
        on_agent_output=on_agent_output,
    )


async def _events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
):
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _run_status(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> RunStatus:
    async with session_factory() as session:
        return (await RunRepository(session).get(run_id)).status


async def test_new_run_defaults_to_graph_mode(tmp_path: Path) -> None:
    async for client, repo in _create_api_client(tmp_path):
        response = await client.post(
            "/api/runs",
            json={
                "repo_name": repo.name,
                "branch": "main",
                "routine_embedded": _routine_payload(),
                "agent_runner_type": "cli_subprocess",
            },
        )

        assert response.status_code == 201
        assert response.json()["execution_mode"] == "graph"


async def test_routine_pinned_legacy_still_runs_legacy(tmp_path: Path) -> None:
    async for client, repo in _create_api_client(tmp_path):
        pinned = await client.post(
            "/api/runs",
            json={
                "repo_name": repo.name,
                "branch": "main",
                "routine_embedded": _routine_payload("pinned-legacy", execution_mode="legacy"),
                "agent_runner_type": "cli_subprocess",
            },
        )
        explicit = await client.post(
            "/api/runs",
            json={
                "repo_name": repo.name,
                "branch": "main",
                "routine_embedded": _routine_payload("explicit-legacy"),
                "execution_mode": "legacy",
                "agent_runner_type": "cli_subprocess",
            },
        )
        override = await client.post(
            "/api/runs",
            json={
                "repo_name": repo.name,
                "branch": "main",
                "routine_embedded": _routine_payload("request-wins", execution_mode="legacy"),
                "execution_mode": "graph",
                "agent_runner_type": "cli_subprocess",
            },
        )

        assert pinned.status_code == 201
        assert pinned.json()["execution_mode"] == "legacy"
        assert explicit.status_code == 201
        assert explicit.json()["execution_mode"] == "legacy"
        assert override.status_code == 201
        assert override.json()["execution_mode"] == "graph"


async def test_default_carrier_switch_round_trips(tmp_path: Path) -> None:
    async for client, repo in _create_api_client(tmp_path, default_execution_mode="legacy"):
        legacy_response = await client.post(
            "/api/runs",
            json={
                "repo_name": repo.name,
                "branch": "main",
                "routine_embedded": _routine_payload("rollback-legacy"),
                "agent_runner_type": "cli_subprocess",
            },
        )
        graph_response = await client.post(
            "/api/runs",
            json={
                "repo_name": repo.name,
                "branch": "main",
                "routine_embedded": _routine_payload("rollback-graph"),
                "execution_mode": "graph",
                "agent_runner_type": "cli_subprocess",
            },
        )

        assert legacy_response.status_code == 201
        assert legacy_response.json()["execution_mode"] == "legacy"
        assert graph_response.status_code == 201
        assert graph_response.json()["execution_mode"] == "graph"


@pytest.mark.asyncio
async def test_common_routine_shapes_seed_and_complete_as_graph(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    routines = [
        _single_step_routine(),
        _fan_out_routine(),
        _auto_verify_routine(),
        _checklist_gate_routine(),
    ]

    for routine in routines:
        repo = tmp_path / f"repo-{routine.id}"
        _init_repo(repo)
        run_id = f"graph-{routine.id}"
        await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)
        dispatch_order: list[str] = []

        outcome = await _driver(session_factory, repo=repo, dispatch_order=dispatch_order).run(
            run_id
        )
        events = await _events(session_factory, run_id)

        assert outcome.completed is True
        assert await _run_status(session_factory, run_id) == RunStatus.COMPLETED
        assert project_run_state(events) == "completed"
        assert project_task_states(events)["step-1/task-1"] == "accepted"
        assert "worker" in dispatch_order
        if routine.id == "auto-verify":
            assert any(
                event.event_type == "output_record_accepted"
                and event.payload.get("record_type") == "check_result"
                for event in events
            )
        assert "verifier" in dispatch_order


async def test_graph_run_observability_parity_through_run_apis(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    engine, session_factory = file_db
    repo = tmp_path / "repo-observability"
    _init_repo(repo)
    run_id = "graph-observability"
    await _create_graph_run(session_factory, _single_step_routine(), run_id=run_id, repo=repo)

    batcher = OutputBatcher(session_factory=session_factory)

    async def on_agent_output(context: GraphDispatchContext, lines: list[str]) -> None:
        task_id = str(
            context.node_payload.get("task_id")
            or context.node_payload.get("task_region_id")
            or context.node_id
        )
        for line in lines:
            await batcher.add_line(context.run_id, task_id, 1, line)

    dispatch_order: list[str] = []
    outcome = await _driver(
        session_factory,
        repo=repo,
        dispatch_order=dispatch_order,
        on_agent_output=on_agent_output,
    ).run(run_id)
    assert outcome.completed is True

    app = create_app(db_path=":memory:", routine_dirs=[])
    app.state.engine = engine
    app.state.session_factory = session_factory
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        run_response = await client.get(f"/api/runs/{run_id}")
        activity_response = await client.get(f"/api/runs/{run_id}/activity")
        projection_response = await client.get(f"/api/runs/{run_id}/graph")
        events_response = await client.get(f"/api/runs/{run_id}/graph/events")

        assert run_response.status_code == 200
        run_json = run_response.json()
        assert run_json["status"] == "completed"
        assert run_json["execution_mode"] == "graph"
        assert run_json["is_graph_backed"] is True
        assert run_json["steps"][0]["tasks"][0]["status"] == "pending"

        assert activity_response.status_code == 200
        activity_json = activity_response.json()
        assert any(event["event_type"] == "agent_output" for event in activity_json["events"])

        assert projection_response.status_code == 200
        projection = projection_response.json()
        assert projection["run_state"] == "completed"
        assert projection["task_states"]["step-1/task-1"] == "accepted"
        verifier_node = next(
            node_id for node_id in projection["node_states"] if node_id.startswith("verifier-")
        )

        assert events_response.status_code == 200
        assert any(event["event_type"] == "callback_accepted" for event in events_response.json())

        node_response = await client.get(
            f"/api/runs/{run_id}/graph/nodes/{verifier_node}?payload_mode=full"
        )
        assert node_response.status_code == 200
        node_json = node_response.json()
        assert node_json["state"] == "completed"
        assert node_json["output_records"][0]["record_kind"] == "verification"
        assert node_json["output_records"][0]["value"]["grades"][0]["grade"] == "A"
