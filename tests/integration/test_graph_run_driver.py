from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType, RunStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db import RunRepository, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    project_run_state,
    project_task_states,
)
from orchestrator.graph_runtime import GraphController, GraphDispatchContext, GraphDispatchExecutor
from orchestrator.graph_runtime.outbox import OutboxDispatcher
from orchestrator.graph_runtime.store import GraphEventStore
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
from orchestrator.workflow import WorkflowService
from orchestrator.workflow.graph_driver import GraphRunDriver, _snapshot_from_events


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


class SubmitAgent:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="submit")

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
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class PlannerPatchAgent(SubmitAgent):
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
        if context.graph_patch_callback is not None:
            await context.graph_patch_callback(
                {
                    "patch_id": f"{context.node_id}-noop",
                    "base_graph_position": 0,
                    "ops": [],
                }
            )
        await on_submit()
        return ExecutionResult(success=True)


class GradingAgent(SubmitAgent):
    def __init__(self, grade: str) -> None:
        self._grade = grade

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
        if on_grade is not None:
            await on_grade("req-1", self._grade, None)
        await on_submit()
        return ExecutionResult(success=True)


@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph-driver.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-driver",
            "name": "Graph Driver",
            "execution_mode": "graph",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Touch the repo",
                            "task_context": "Produce one implementation candidate.",
                            "requirements": [{"id": "req-1", "desc": "Requirement passes."}],
                            "verifier": {
                                "rubric": [
                                    {
                                        "id": "req-1",
                                        "text": "Does the candidate satisfy req-1?",
                                    }
                                ]
                            },
                        }
                    ],
                }
            ],
        }
    )


def _planner_routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-driver-planner",
            "name": "Graph Driver Planner",
            "execution_mode": "graph",
            "planner_generation_budget": 1,
            "steps": [
                {"id": "plan", "kind": "planner", "title": "Plan"},
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Touch the repo",
                            "task_context": "Produce one implementation candidate.",
                            "requirements": [{"id": "req-1", "desc": "Requirement passes."}],
                            "verifier": {
                                "rubric": [
                                    {
                                        "id": "req-1",
                                        "text": "Does the candidate satisfy req-1?",
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
    (path / "README.md").write_text("# tmp repo\n")
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
        service = WorkflowService(session)
        await service.create_run(run)


def _driver(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    repo: Path,
    agents: dict[str, AgentRunner],
    dispatch_order: list[str],
) -> GraphRunDriver:
    clock = FixedClock()
    ids = SequentialIds()

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
            AgentFactory(agents, dispatch_order),
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


async def _events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
):
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


def _graph_event(
    run_id: str,
    position: int,
    event_type: str,
    payload: dict[str, Any],
) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id=run_id,
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


async def _run_status(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> RunStatus:
    async with session_factory() as session:
        return (await RunRepository(session).get(run_id)).status


@pytest.mark.asyncio
async def test_driver_runs_single_worker_verifier_to_accepted(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-accepted"
    _init_repo(repo)
    run_id = "graph-driver-accepted"
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)
    dispatch_order: list[str] = []
    driver = _driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=dispatch_order,
    )

    outcome = await driver.run(run_id)

    events = await _events(session_factory, run_id)
    assert dispatch_order == ["worker", "verifier"]
    assert project_task_states(events) == {"step-1/task-1": "accepted"}
    assert project_run_state(events) == "completed"
    assert outcome.completed is True
    assert await _run_status(session_factory, run_id) == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_driver_self_advances_across_node_boundaries(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-self-advance"
    _init_repo(repo)
    run_id = "graph-driver-self-advance"
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)
    dispatch_order: list[str] = []
    driver = _driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=dispatch_order,
    )

    await driver.run(run_id)

    assert dispatch_order == ["worker", "verifier"]


@pytest.mark.asyncio
async def test_driver_dispatches_final_check_after_verifier_acceptance(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-final-check"
    _init_repo(repo)
    run_id = "graph-driver-final-check"
    clock = FixedClock()
    ids = SequentialIds()
    events = [
        _graph_event(run_id, 1, "run_lifecycle_changed", {"to_state": "active"}),
        _graph_event(
            run_id,
            2,
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
                "task_region_id": "region-implementation",
            },
        ),
        _graph_event(
            run_id,
            3,
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "candidate_id": "candidate-1",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "task_region_id": "region-implementation",
                "value": {"summary": "candidate accepted"},
            },
        ),
        _graph_event(
            run_id,
            4,
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "candidate_id": "candidate-1",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "task_region_id": "region-implementation",
            },
        ),
        _graph_event(
            run_id,
            5,
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "task_region_id": "region-implementation",
            },
        ),
        _graph_event(
            run_id,
            6,
            "output_record_accepted",
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "record_type": "verification_report",
                "candidate_id": "candidate-1",
                "producer_node_id": "verifier-1",
                "port": "verification_report",
                "schema": "VerificationReport",
                "task_region_id": "region-implementation",
                "value": {"grades": [{"requirement_id": "req-1", "grade": "A"}]},
            },
        ),
        _graph_event(
            run_id,
            7,
            "verification_passed",
            {
                "node_id": "verifier-1",
                "record_id": "verification-1",
                "task_region_id": "region-implementation",
                "value": {"grades": [{"requirement_id": "req-1", "grade": "A"}]},
            },
        ),
        _graph_event(
            run_id,
            8,
            "node_created",
            {
                "node_id": "check-final",
                "kind": "check",
                "role": "invariant_gate",
                "state": "ready",
                "task_region_id": "region-final-invariant",
                "command_definition": {"id": "final-check", "cmd": "true", "must": True},
            },
        ),
        _graph_event(
            run_id,
            9,
            "input_bound",
            {
                "edge_id": "edge-verifier-check",
                "to_node_id": "check-final",
                "to_port": "verification_evidence",
                "record_ids": ["verification-1"],
                "bound_at_position": 9,
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()

    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    dispatch_order: list[str] = []
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({}, dispatch_order),
        worktree_path=repo,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)
    driver = GraphRunDriver.__new__(GraphRunDriver)

    async def read_projection(target_run_id: str):
        return _snapshot_from_events(await _events(session_factory, target_run_id))

    outcome = await driver.drive_to_quiescence(
        run_id,
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=read_projection,
    )

    final_events = await _events(session_factory, run_id)
    final_check_event_types = [
        event.event_type
        for event in final_events
        if event.payload.get("node_id") == "check-final"
        or event.payload.get("producer_node_id") == "check-final"
    ]
    assert dispatch_order == []
    assert "lease_granted" in final_check_event_types
    assert "callback_accepted" in final_check_event_types
    assert any(
        event.event_type == "output_record_accepted"
        and event.payload.get("producer_node_id") == "check-final"
        and event.payload.get("port") == "check_result"
        for event in final_events
    )
    assert project_task_states(final_events)["region-final-invariant"] == "accepted"
    assert outcome.completed is False
    assert outcome.blocked_reason is not None
    assert "ready node(s) not dispatched" not in outcome.blocked_reason


@pytest.mark.asyncio
async def test_driver_blocks_on_verifier_fail_without_completing(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-fail"
    _init_repo(repo)
    run_id = "graph-driver-fail"
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)
    dispatch_order: list[str] = []
    driver = _driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("C")},
        dispatch_order=dispatch_order,
    )

    outcome = await driver.run(run_id)

    assert outcome.completed is False
    assert outcome.blocked_reason is not None
    assert await _run_status(session_factory, run_id) == RunStatus.PAUSED


@pytest.mark.asyncio
async def test_driver_rejects_unsupported_graph_runner_before_seeding(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-unsupported-runner"
    _init_repo(repo)
    run_id = "graph-driver-unsupported-runner"
    await _create_graph_run(
        session_factory,
        _routine(),
        run_id=run_id,
        repo=repo,
        agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
    )
    dispatch_order: list[str] = []
    driver = _driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=dispatch_order,
    )

    outcome = await driver.run(run_id)
    events = await _events(session_factory, run_id)

    assert outcome.completed is False
    assert outcome.blocked_reason is not None
    assert "unsupported runner 'cli_subprocess'" in outcome.blocked_reason
    assert events == []
    assert dispatch_order == []
    assert await _run_status(session_factory, run_id) == RunStatus.PAUSED


@pytest.mark.asyncio
async def test_driver_seed_is_idempotent_on_reentry(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-reentry"
    _init_repo(repo)
    run_id = "graph-driver-reentry"
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)
    dispatch_order: list[str] = []
    driver = _driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=dispatch_order,
    )

    await driver.run(run_id)
    events_after_first = await _events(session_factory, run_id)
    dispatches_after_first = list(dispatch_order)
    await driver.run(run_id)
    events_after_second = await _events(session_factory, run_id)

    assert len(events_after_second) >= len(events_after_first)
    assert dispatch_order == dispatches_after_first
    assert len([event for event in events_after_second if event.event_type == "graph_seeded"]) <= 1


@pytest.mark.asyncio
async def test_driver_planner_run_completes_only_when_no_pending_planner(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-planner"
    _init_repo(repo)
    run_id = "graph-driver-planner"
    await _create_graph_run(session_factory, _planner_routine(), run_id=run_id, repo=repo)
    dispatch_order: list[str] = []
    driver = _driver(
        session_factory,
        repo=repo,
        agents={
            "planner": PlannerPatchAgent(),
            "worker": SubmitAgent(),
            "verifier": GradingAgent("A"),
        },
        dispatch_order=dispatch_order,
    )

    outcome = await driver.run(run_id)

    events = await _events(session_factory, run_id)
    assert dispatch_order == ["planner", "worker", "verifier"]
    assert project_run_state(events) == "completed"
    assert outcome.completed is True
    assert await _run_status(session_factory, run_id) == RunStatus.COMPLETED
