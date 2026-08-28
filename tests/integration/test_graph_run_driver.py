from __future__ import annotations

import asyncio
import subprocess
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.artifacts import ArtifactStore, FilesystemArtifactStore
from orchestrator.config.enums import AgentRunnerType, RunStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db import (
    EventV2Model,
    RunRepository,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    project_graph_projection_snapshot,
    project_run_state,
    project_task_states,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    MANAGED_LEASE_TTL_SECONDS,
    seed_run,
)
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
from orchestrator.workflow.graph_driver import (
    GRAPH_OPERATOR_REOPEN_PAUSE_REASON,
    GraphRunDriver,
    _renew_running_leases_near_expiry,
)

pytestmark = pytest.mark.slow


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
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


class HoldingSubmitAgent(SubmitAgent):
    """Keep a real dispatch task live until the lease-boundary assertion."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

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
        del context, on_checklist_update, on_output, on_grade, on_agent_metadata, on_escalation
        self.started.set()
        await self.release.wait()
        await on_submit()
        return ExecutionResult(success=True)


class WritingSubmitAgent(SubmitAgent):
    """A real graph worker that leaves a finalization-worthy worktree change."""

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
        (Path(context.working_dir) / "graph-finalized.txt").write_text("accepted\n")
        await on_submit()
        return ExecutionResult(success=True)


class FinalizationLockAgent(WritingSubmitAgent):
    """Creates a real Git write conflict only after its graph callback succeeds."""

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
        result = await super().execute(
            context,
            on_checklist_update,
            on_submit,
            on_output,
            on_grade,
            on_agent_metadata,
            on_escalation,
        )
        (Path(context.working_dir) / ".git" / "index.lock").write_text("held by test\n")
        return result


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


class CrashingOutboxDispatcher(OutboxDispatcher):
    entered = False

    async def dispatch_pending(
        self,
        limit: int | None = None,
        *,
        run_id: str | None = None,
        allowed_kinds: frozenset[str] | None = None,
    ) -> list[Any]:
        del limit, run_id, allowed_kinds
        self.entered = True
        raise RuntimeError("drive loop escaped after entry")


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
    dispatcher_factory: Any = None,
) -> GraphRunDriver:
    clock = FixedClock()
    ids = SequentialIds()

    async def advance_clock(seconds: float) -> None:
        clock.advance(seconds)

    def runtime_builder(
        session_factory_arg: async_sessionmaker[AsyncSession],
        clock_arg: Any,
        id_gen_arg: Any,
        *,
        worktree_path: str | Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
        artifact_store: ArtifactStore,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        controller = GraphController(
            session_factory_arg, clock_arg, id_gen_arg, auto_dispatch=False
        )
        executor = GraphDispatchExecutor(
            session_factory_arg,
            controller,
            AgentFactory(agents, dispatch_order),
            worktree_path=repo,
            artifact_store=artifact_store,
        )
        return controller, executor

    return GraphRunDriver(
        session_factory,
        _create_service,
        clock=clock,
        id_gen=ids,
        runtime_builder=runtime_builder,
        dispatcher_factory=dispatcher_factory,
        sleep=advance_clock,
    )


async def _events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
):
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _workflow_events(
    session_factory: async_sessionmaker[AsyncSession], run_id: str
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = await session.execute(
            select(EventV2Model.event_type, EventV2Model.payload)
            .where(EventV2Model.aggregate_id == run_id)
            .order_by(EventV2Model.position)
        )
    return [
        {"event_type": event_type, "payload": json.loads(payload)}
        for event_type, payload in rows.all()
    ]


def _graph_event(
    run_id: str,
    position: int,
    event_type: str,
    payload: dict[str, Any],
) -> EventEnvelope:
    from tests.unit.graph_test_utils import canonical_event_payload

    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id=run_id,
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )


async def _run_status(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> RunStatus:
    async with session_factory() as session:
        return (await RunRepository(session).get(run_id)).status


@pytest.mark.asyncio
async def test_live_execution_is_renewed_before_expiry_sweep(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """Cross an actual SQLite lease deadline while its dispatch task is live."""
    _, session_factory = file_db
    repo = tmp_path / "repo-live-lease-boundary"
    _init_repo(repo)
    run_id = "graph-live-lease-boundary"
    clock = FixedClock()
    ids = SequentialIds()
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)
    await seed_run(session_factory, _routine(), run_id=run_id, clock=clock, id_gen=ids)
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    await controller.handle_command(run_id, await controller.current_position(run_id), "accept_run")
    await controller.handle_command(run_id, await controller.current_position(run_id), "start")

    agent = HoldingSubmitAgent()
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": agent}, []),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts-live-boundary"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)
    try:
        await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 30, "max_grants": 1, "base_snapshot_id": "S0"},
        )
        await dispatcher.dispatch_pending(run_id=run_id)
        await asyncio.wait_for(agent.started.wait(), timeout=1.0)

        # Dispatch acknowledgement extends the initial grant using the same
        # lease policy as the driver. Cross that real persisted deadline by 1ms.
        clock.advance(MANAGED_LEASE_TTL_SECONDS + 0.001)
        projection = project_graph_projection_snapshot(await _events(session_factory, run_id))
        assert projection.active_leases
        execution_ids = {lease.get("execution_id") for lease in projection.active_leases.values()}
        assert any(
            isinstance(execution_id, str) and executor.is_running(execution_id)
            for execution_id in execution_ids
        ), (projection.active_leases, execution_ids)
        renewed = await _renew_running_leases_near_expiry(
            run_id,
            controller,
            executor,
            projection,
            clock.now(),
        )
        assert renewed, [
            (event.event_type, event.payload)
            for event in (await _events(session_factory, run_id))[-5:]
        ]
        await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 3600, "max_grants": 1, "base_snapshot_id": "S0"},
        )

        boundary_events = await _events(session_factory, run_id)
        assert any(event.event_type == "lease_renewed" for event in boundary_events)
        assert not any(
            event.event_type == "node_state_changed"
            and event.payload.get("reason") == "lease_expired_without_callback"
            for event in boundary_events
        )
    finally:
        agent.release.set()
        await executor.wait_for_all()


@pytest.mark.asyncio
async def test_driver_snapshot_projection_matches_full_recovery_projection(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """A persisted projection must be sufficient for driver readback semantics."""
    _, session_factory = file_db
    repo = tmp_path / "repo-snapshot-readback"
    _init_repo(repo)
    run_id = "graph-driver-snapshot-readback"
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)
    driver = _driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("C")},
        dispatch_order=[],
    )

    await driver.run(run_id)
    events = await _events(session_factory, run_id)
    async with session_factory() as session:
        persisted_projection, tail, _ = await GraphEventStore(session).load_projection_with_tail(
            run_id
        )

    full_snapshot = project_graph_projection_snapshot(events)
    snapshot_backed = project_graph_projection_snapshot(events, projection=persisted_projection)

    assert tail == []
    assert snapshot_backed == full_snapshot
    assert await driver._read_projection(run_id) == full_snapshot


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
async def test_driver_durably_finalizes_worktree_before_completed(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """The graph kernel cannot publish COMPLETED ahead of its final worktree commit."""
    _, session_factory = file_db
    repo = tmp_path / "repo-finalization"
    _init_repo(repo)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    run_id = "graph-driver-finalization"
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)
    driver = _driver(
        session_factory,
        repo=repo,
        agents={"worker": WritingSubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=[],
    )

    outcome = await driver.run(run_id)

    assert outcome.completed is True
    assert await _run_status(session_factory, run_id) == RunStatus.COMPLETED
    workflow_events = await _workflow_events(session_factory, run_id)
    finalization = next(
        event["payload"]
        for event in workflow_events
        if event["event_type"] == "run_worktree_commit_completed"
        and event["payload"]["commit_type"] == "graph_run_finalization"
    )
    assert finalization["task_id"] == "__run_finalization__"
    assert finalization["created_commit"] is True
    assert finalization["head_before"] != finalization["head_after"]
    status_events = [
        event
        for event in workflow_events
        if event["event_type"] == "run_status_changed"
        and event["payload"]["new_status"] == RunStatus.COMPLETED.value
    ]
    assert status_events
    assert workflow_events.index(
        next(
            event
            for event in workflow_events
            if event["event_type"] == "run_worktree_commit_completed"
            and event["payload"]["commit_type"] == "graph_run_finalization"
        )
    ) < workflow_events.index(status_events[-1])


@pytest.mark.asyncio
async def test_finalization_retry_reuses_durable_receipt_after_crash_window(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """A retry completes from the finalization receipt without a second Git outcome."""
    _, session_factory = file_db
    repo = tmp_path / "repo-finalization-retry"
    _init_repo(repo)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    run_id = "graph-driver-finalization-retry"
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)
    async with session_factory() as session:
        await WorkflowService(session).apply_start_run(run_id)
    (repo / "graph-finalized.txt").write_text("accepted\n")

    # Simulate the process dying after the durable finalization receipt commits
    # and before it can append ACTIVE -> COMPLETED.  This is a separate real
    # SQLite session, not a mocked lifecycle transition.
    async with session_factory() as session:
        service = WorkflowService(session)
        await service._run_event_sourced_worktree_commit(
            run_id=run_id,
            task_id="__run_finalization__",
            attempt_id=None,
            worktree_path=str(repo),
            message=f"Finalize graph run {run_id}",
            commit_type="graph_run_finalization",
            reason="graph_run_completion",
        )

    assert await _run_status(session_factory, run_id) == RunStatus.ACTIVE

    async with session_factory() as session:
        retry = WorkflowService(session)
        completed = await retry.finalize_graph_run_completion(run_id)

    assert completed.status == RunStatus.COMPLETED
    workflow_events = await _workflow_events(session_factory, run_id)
    finalizations = [
        event
        for event in workflow_events
        if event["event_type"] == "run_worktree_commit_completed"
        and event["payload"]["commit_type"] == "graph_run_finalization"
    ]
    assert len(finalizations) == 1
    assert finalizations[0]["payload"]["created_commit"] is True
    assert (
        sum(
            event["event_type"] == "run_worktree_commit_requested"
            and event["payload"]["commit_type"] == "graph_run_finalization"
            for event in workflow_events
        )
        == 1
    )
    assert not any(
        event["event_type"] == "run_worktree_commit_failed"
        and event["payload"]["commit_type"] == "graph_run_finalization"
        for event in workflow_events
    )
    assert (
        sum(
            event["event_type"] == "run_status_changed"
            and event["payload"]["new_status"] == RunStatus.COMPLETED.value
            for event in workflow_events
        )
        == 1
    )


@pytest.mark.asyncio
async def test_driver_keeps_run_recoverable_when_finalization_commit_fails(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """A real git finalization error is visible and cannot produce COMPLETED."""
    _, session_factory = file_db
    repo = tmp_path / "repo-finalization-failure"
    _init_repo(repo)
    run_id = "graph-driver-finalization-failure"
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)
    driver = _driver(
        session_factory,
        repo=repo,
        agents={"worker": FinalizationLockAgent(), "verifier": GradingAgent("A")},
        dispatch_order=[],
    )

    outcome = await driver.run(run_id)

    assert outcome.completed is False
    assert outcome.blocked_reason is not None
    assert "finalization failed" in outcome.blocked_reason
    async with session_factory() as session:
        run = await RunRepository(session).get(run_id)
    assert run.status == RunStatus.PAUSED
    assert run.pause_reason == "graph_finalization_failed"
    assert run.last_error == outcome.blocked_reason
    workflow_events = await _workflow_events(session_factory, run_id)
    failed = next(
        event["payload"]
        for event in workflow_events
        if event["event_type"] == "run_worktree_commit_failed"
        and event["payload"]["commit_type"] == "graph_run_finalization"
    )
    assert failed["task_id"] == "__run_finalization__"
    assert not any(
        event["event_type"] == "run_status_changed"
        and event["payload"]["new_status"] == RunStatus.COMPLETED.value
        for event in workflow_events
    )


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
                "node_id": "requirement-req-1",
                "kind": "requirement",
                "state": "completed",
            },
        ),
        _graph_event(
            run_id,
            6,
            "output_record_accepted",
            {
                "record_id": "requirement-req-1",
                "record_kind": "graph_record",
                "record_type": "requirement_record",
                "producer_node_id": "requirement-req-1",
                "port": "requirement",
                "schema": "RequirementRecord",
                "value": {
                    "id": "req-1",
                    "text": "Final check requirement",
                    "source": "routine",
                },
            },
        ),
        _graph_event(
            run_id,
            7,
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
            8,
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
                "outcome": "passed",
                "value": {
                    "outcome": "passed",
                    "grades": [{"requirement_id": "req-1", "grade": "A"}],
                },
            },
        ),
        _graph_event(
            run_id,
            9,
            "verification_passed",
            {
                "node_id": "verifier-1",
                "record_id": "verification-1",
                "task_region_id": "region-implementation",
                "value": {
                    "outcome": "passed",
                    "grades": [{"requirement_id": "req-1", "grade": "A"}],
                },
            },
        ),
        _graph_event(
            run_id,
            10,
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
            11,
            "edge_created",
            {
                "edge_id": "edge-verifier-check",
                "from_node_id": "verifier-1",
                "from_port": "verification_report",
                "to_node_id": "check-final",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                },
            },
        ),
        _graph_event(
            run_id,
            12,
            "input_bound",
            {
                "edge_id": "edge-verifier-check",
                "to_node_id": "check-final",
                "to_port": "verification_evidence",
                "record_ids": ["verification-1"],
                "bound_at_position": 12,
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
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)
    driver = GraphRunDriver.__new__(GraphRunDriver)

    async def read_projection(target_run_id: str):
        return project_graph_projection_snapshot(await _events(session_factory, target_run_id))

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
    assert outcome.completed is True
    assert outcome.blocked_reason is None


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
async def test_driver_crash_bridge_persists_pause_and_reraises(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-crash-bridge"
    _init_repo(repo)
    run_id = "graph-driver-crash-bridge"
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)
    dispatcher: CrashingOutboxDispatcher | None = None

    def dispatcher_factory(*args: Any) -> OutboxDispatcher:
        nonlocal dispatcher
        dispatcher = CrashingOutboxDispatcher(*args)
        return dispatcher

    driver = _driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=[],
        dispatcher_factory=dispatcher_factory,
    )

    with pytest.raises(RuntimeError, match="drive loop escaped after entry"):
        await driver.run(run_id)

    assert dispatcher is not None and dispatcher.entered is True
    async with session_factory() as session:
        crashed = await RunRepository(session).get(run_id)
    assert crashed.status == RunStatus.PAUSED
    assert crashed.pause_reason == "graph_driver_crashed"
    assert crashed.last_error == "drive loop escaped after entry"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent_runner_type", "expected_runner", "expected_status"),
    [
        (AgentRunnerType.OPENHANDS_LOCAL, "openhands_local", RunStatus.PAUSED),
        (AgentRunnerType.RETIRED, "retired", RunStatus.DRAFT),
    ],
)
async def test_driver_rejects_unsupported_graph_runner_before_seeding(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
    agent_runner_type: AgentRunnerType,
    expected_runner: str,
    expected_status: RunStatus,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / f"repo-unsupported-runner-{expected_runner}"
    _init_repo(repo)
    run_id = f"graph-driver-unsupported-runner-{expected_runner}"
    await _create_graph_run(
        session_factory,
        _routine(),
        run_id=run_id,
        repo=repo,
        agent_runner_type=agent_runner_type,
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
    assert f"unsupported runner '{expected_runner}'" in outcome.blocked_reason
    assert events == []
    assert dispatch_order == []
    assert await _run_status(session_factory, run_id) == expected_status


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


async def _seed_and_force_failed_graph(
    session_factory: async_sessionmaker[AsyncSession],
    routine: RoutineConfig,
    *,
    run_id: str,
    clock: FixedClock,
    ids: SequentialIds,
) -> None:
    """Seed a graph, bring the kernel to active, then force run_state failed.

    The worker node is left schedulable (never dispatched), mirroring a run
    that failed with recovery work still outstanding.
    """
    await seed_run(
        session_factory,
        routine,
        run_id=run_id,
        clock=clock,
        id_gen=ids,
        run_config={},
    )
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    for command in ("accept_run", "start"):
        position = await controller.current_position(run_id)
        await controller.handle_command(run_id, position, command, {})
    position = await controller.current_position(run_id)
    await controller.handle_command(run_id, position, "fail", {"reason": "forced_for_test"})


def _shared_driver(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    repo: Path,
    agents: dict[str, AgentRunner],
    dispatch_order: list[str],
    clock: FixedClock,
    ids: SequentialIds,
) -> GraphRunDriver:
    """Like ``_driver`` but reuses an existing clock/id generator.

    A shared, monotonic id source keeps driver-appended event ids from
    colliding with the ids the caller already used to seed/force-fail the run.
    """

    async def advance_clock(seconds: float) -> None:
        clock.advance(seconds)

    def runtime_builder(
        session_factory_arg: async_sessionmaker[AsyncSession],
        clock_arg: Any,
        id_gen_arg: Any,
        *,
        worktree_path: str | Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
        artifact_store: ArtifactStore,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        controller = GraphController(
            session_factory_arg, clock_arg, id_gen_arg, auto_dispatch=False
        )
        executor = GraphDispatchExecutor(
            session_factory_arg,
            controller,
            AgentFactory(agents, dispatch_order),
            worktree_path=repo,
            artifact_store=artifact_store,
        )
        return controller, executor

    return GraphRunDriver(
        session_factory,
        _create_service,
        clock=clock,
        id_gen=ids,
        runtime_builder=runtime_builder,
        sleep=advance_clock,
    )


@pytest.mark.asyncio
async def test_operator_resume_reopens_failed_graph_run(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-operator-reopen"
    _init_repo(repo)
    run_id = "graph-operator-reopen"
    routine = _routine()
    await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)

    clock = FixedClock()
    ids = SequentialIds()
    await _seed_and_force_failed_graph(
        session_factory, routine, run_id=run_id, clock=clock, ids=ids
    )
    assert project_run_state(await _events(session_factory, run_id)) == "failed"

    # Drive the run row to FAILED (operator-visible terminal state).
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.apply_start_run(run_id)
        await service.apply_fail_run(run_id, reason="forced_for_test")
    assert await _run_status(session_factory, run_id) == RunStatus.FAILED

    # Operator resume flips the row FAILED -> ACTIVE but the service alone does
    # not touch the kernel: run_state is still "failed" afterwards.
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.apply_resume_run(run_id, resume_strategy="continue")
    assert await _run_status(session_factory, run_id) == RunStatus.ACTIVE
    assert project_run_state(await _events(session_factory, run_id)) == "failed"

    # Re-arming the driver issues the kernel resume command so the graph reopens
    # and the previously-stranded worker node becomes schedulable again.
    dispatch_order: list[str] = []
    driver = _shared_driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=dispatch_order,
        clock=clock,
        ids=ids,
    )
    await driver.run(run_id)

    events_after = await _events(session_factory, run_id)
    assert project_run_state(events_after) != "failed"
    assert "worker" in dispatch_order


@pytest.mark.asyncio
async def test_paused_graph_resume_dispatches_ready_node_before_blocking(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """A real paused-row resume gives the ready graph node a dispatch turn."""
    _, session_factory = file_db
    repo = tmp_path / "repo-paused-ready-resume"
    _init_repo(repo)
    run_id = "graph-paused-ready-resume"
    routine = _routine()
    await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)

    clock = FixedClock()
    ids = SequentialIds()
    await seed_run(
        session_factory,
        routine,
        run_id=run_id,
        clock=clock,
        id_gen=ids,
        run_config={},
    )
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    for command in ("accept_run", "start"):
        position = await controller.current_position(run_id)
        await controller.handle_command(run_id, position, command, {})
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.apply_start_run(run_id)
        await service.apply_pause_run(run_id, reason="ready_for_resume_test")

    dispatch_order: list[str] = []
    driver = _shared_driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=dispatch_order,
        clock=clock,
        ids=ids,
    )

    outcome = await driver.run(run_id)

    assert outcome.completed is True
    assert dispatch_order == ["worker", "verifier"]
    events = await _events(session_factory, run_id)
    dispatch_positions = [
        event.position for event in events if event.event_type == "agent_dispatch_requested"
    ]
    assert dispatch_positions
    assert await _run_status(session_factory, run_id) == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_driver_does_not_reopen_failed_graph_without_operator_resume(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-no-reopen"
    _init_repo(repo)
    run_id = "graph-no-reopen"
    routine = _routine()
    await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)

    clock = FixedClock()
    ids = SequentialIds()
    await _seed_and_force_failed_graph(
        session_factory, routine, run_id=run_id, clock=clock, ids=ids
    )

    # Row driven to FAILED and left there: no operator resume occurred.
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.apply_start_run(run_id)
        await service.apply_fail_run(run_id, reason="forced_for_test")
    assert await _run_status(session_factory, run_id) == RunStatus.FAILED

    dispatch_order: list[str] = []
    driver = _shared_driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=dispatch_order,
        clock=clock,
        ids=ids,
    )
    await driver.run(run_id)

    # The kernel stays failed and nothing dispatches: an un-resumed FAILED run
    # is never silently reopened by the driver.
    assert project_run_state(await _events(session_factory, run_id)) == "failed"
    assert dispatch_order == []


@pytest.mark.asyncio
async def test_driver_does_not_reopen_crash_window_stranded_active_run(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """Row ACTIVE + kernel failed with NO operator resume must self-heal FAILED.

    This is the crash-window stranded-ACTIVE incident: the kernel autonomously
    failed the run (run_state "failed") but the process died before run() could
    persist the row FAILED, so the row is still ACTIVE. select_graph_runs_to_rearm
    re-arms such runs. The driver must NOT treat this as an operator reopen: with
    no persisted reopen marker it falls through to the drive loop, which
    re-classifies the failed kernel so _apply_fail persists FAILED. No kernel
    resume command is issued and nothing is dispatched.
    """
    _, session_factory = file_db
    repo = tmp_path / "repo-stranded-active"
    _init_repo(repo)
    run_id = "graph-stranded-active"
    routine = _routine()
    await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)

    clock = FixedClock()
    ids = SequentialIds()
    await _seed_and_force_failed_graph(
        session_factory, routine, run_id=run_id, clock=clock, ids=ids
    )

    # Crash window: drive the row to ACTIVE but never fail it and never resume it.
    # No operator involvement => no reopen marker is stamped on pause_reason.
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.apply_start_run(run_id)
    assert await _run_status(session_factory, run_id) == RunStatus.ACTIVE
    assert project_run_state(await _events(session_factory, run_id)) == "failed"
    async with session_factory() as session:
        stranded = await RunRepository(session).get(run_id)
    assert stranded.pause_reason != GRAPH_OPERATOR_REOPEN_PAUSE_REASON

    dispatch_order: list[str] = []
    driver = _shared_driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=dispatch_order,
        clock=clock,
        ids=ids,
    )
    await driver.run(run_id)

    events_after = await _events(session_factory, run_id)
    # Kernel stays failed, nothing dispatched, no reopen (resuming) transition,
    # and the row self-heals to FAILED.
    assert project_run_state(events_after) == "failed"
    assert dispatch_order == []
    # A "resuming" lifecycle transition is produced ONLY by the reopen path's
    # kernel resume command, so its absence proves no reopen was issued.
    assert not any(
        event.event_type == "run_lifecycle_changed" and event.payload.get("to_state") == "resuming"
        for event in events_after
    )
    assert await _run_status(session_factory, run_id) == RunStatus.FAILED


@pytest.mark.asyncio
async def test_operator_reopen_marker_is_consumed_once(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """The reopen marker is stamped by the resume and cleared by the driver.

    Consume-once: once the driver has acted on the marker it is cleared from the
    row, so a subsequent autonomous failure + re-arm (which would leave the row
    ACTIVE with a failed kernel again) is not replayed as another spurious
    reopen — the absence of the marker routes it back to the self-heal path.
    """
    _, session_factory = file_db
    repo = tmp_path / "repo-marker-consume"
    _init_repo(repo)
    run_id = "graph-marker-consume"
    routine = _routine()
    await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)

    clock = FixedClock()
    ids = SequentialIds()
    await _seed_and_force_failed_graph(
        session_factory, routine, run_id=run_id, clock=clock, ids=ids
    )

    async with session_factory() as session:
        service = WorkflowService(session)
        await service.apply_start_run(run_id)
        await service.apply_fail_run(run_id, reason="forced_for_test")
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.apply_resume_run(run_id, resume_strategy="continue")

    # apply_resume_run stamped the persisted reopen marker on the ACTIVE row.
    async with session_factory() as session:
        resumed = await RunRepository(session).get(run_id)
    assert resumed.status == RunStatus.ACTIVE
    assert resumed.pause_reason == GRAPH_OPERATOR_REOPEN_PAUSE_REASON

    dispatch_order: list[str] = []
    driver = _shared_driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=dispatch_order,
        clock=clock,
        ids=ids,
    )
    await driver.run(run_id)

    # The marker is consumed: it no longer lingers on the row after the driver
    # acted on it, so a later re-arm cannot replay the reopen.
    async with session_factory() as session:
        after = await RunRepository(session).get(run_id)
    assert after.pause_reason != GRAPH_OPERATOR_REOPEN_PAUSE_REASON
    assert project_run_state(await _events(session_factory, run_id)) != "failed"
    assert "worker" in dispatch_order


@pytest.mark.asyncio
async def test_recover_run_then_resume_reopens_failed_graph_run(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """recover_run parks a FAILED graph run PAUSED; the resume must still reopen.

    recover_run() transitions a FAILED graph run to PAUSED (pause_reason
    "recovered") without touching the durable kernel run_state, which stays
    "failed". The operator resume then takes the ordinary PAUSED -> ACTIVE
    branch. The reopen marker must still be stamped on that resume (it carries
    operator intent to reopen the failed kernel) so the re-armed driver issues
    the kernel resume — otherwise the ACTIVE/failed-kernel row would self-heal
    straight back to FAILED and the operator recover+resume would silently do
    nothing.
    """
    _, session_factory = file_db
    repo = tmp_path / "repo-recover-resume"
    _init_repo(repo)
    run_id = "graph-recover-resume"
    routine = _routine()
    await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)

    clock = FixedClock()
    ids = SequentialIds()
    await _seed_and_force_failed_graph(
        session_factory, routine, run_id=run_id, clock=clock, ids=ids
    )

    # Drive the row to FAILED (operator-visible terminal state).
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.apply_start_run(run_id)
        await service.apply_fail_run(run_id, reason="forced_for_test")
    assert await _run_status(session_factory, run_id) == RunStatus.FAILED

    # Operator recover: FAILED -> PAUSED (pause_reason "recovered"), kernel
    # untouched so run_state is still "failed".
    async with session_factory() as session:
        target_task_id = (await RunRepository(session).get(run_id)).steps[0].tasks[0].id
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.recover_run(run_id, target_task_id=target_task_id, reset_branch=False)
    async with session_factory() as session:
        recovered = await RunRepository(session).get(run_id)
    assert recovered.status == RunStatus.PAUSED
    assert recovered.pause_reason == "recovered"
    assert project_run_state(await _events(session_factory, run_id)) == "failed"

    # Operator resume takes the ordinary PAUSED -> ACTIVE branch, but the reopen
    # marker must still be stamped because this is a graph run.
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.apply_resume_run(run_id, resume_strategy="continue")
    async with session_factory() as session:
        resumed = await RunRepository(session).get(run_id)
    assert resumed.status == RunStatus.ACTIVE
    assert resumed.pause_reason == GRAPH_OPERATOR_REOPEN_PAUSE_REASON
    assert project_run_state(await _events(session_factory, run_id)) == "failed"

    # Re-arming the driver issues the kernel resume: the graph reopens instead of
    # self-healing back to FAILED, and the worker node becomes schedulable again.
    dispatch_order: list[str] = []
    driver = _shared_driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=dispatch_order,
        clock=clock,
        ids=ids,
    )
    await driver.run(run_id)

    assert project_run_state(await _events(session_factory, run_id)) != "failed"
    assert "worker" in dispatch_order
    async with session_factory() as session:
        after = await RunRepository(session).get(run_id)
    assert after.pause_reason != GRAPH_OPERATOR_REOPEN_PAUSE_REASON


@pytest.mark.asyncio
async def test_clarification_resume_does_not_reopen_recovered_failed_graph(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """A clarification response must NOT reopen a graph run parked for recovery.

    The clarification-response endpoint only auto-resumes a PAUSED run when it
    was paused *for* a clarification / user action. A graph run parked PAUSED
    with pause_reason "recovered" while its durable kernel is still "failed" is
    NOT such a run: resuming it here would drive apply_resume_run to stamp the
    operator-reopen marker and reopen the failed kernel under a fabricated
    operator role. The clarifications router guard
    (_is_clarification_pause_reason) blocks that, so the run stays PAUSED and the
    kernel stays failed with no reopen marker.
    """
    from orchestrator.api import is_clarification_pause_reason

    _, session_factory = file_db
    repo = tmp_path / "repo-clarif-no-reopen"
    _init_repo(repo)
    run_id = "graph-clarif-no-reopen"
    routine = _routine()
    await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)

    clock = FixedClock()
    ids = SequentialIds()
    await _seed_and_force_failed_graph(
        session_factory, routine, run_id=run_id, clock=clock, ids=ids
    )

    # Drive the row to FAILED, then operator-recover it: FAILED -> PAUSED
    # (pause_reason "recovered"), kernel untouched so run_state stays "failed".
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.apply_start_run(run_id)
        await service.apply_fail_run(run_id, reason="forced_for_test")
    async with session_factory() as session:
        target_task_id = (await RunRepository(session).get(run_id)).steps[0].tasks[0].id
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.recover_run(run_id, target_task_id=target_task_id, reset_branch=False)
    async with session_factory() as session:
        recovered = await RunRepository(session).get(run_id)
    assert recovered.status == RunStatus.PAUSED
    assert recovered.pause_reason == "recovered"
    assert project_run_state(await _events(session_factory, run_id)) == "failed"

    # The clarification-response endpoint gates its auto-resume on this guard.
    # "recovered" is not a clarification/user-action pause reason, so the resume
    # branch is skipped entirely.
    assert is_clarification_pause_reason(recovered.pause_reason) is False

    # Reproduce the exact router branch: because the guard is False, the resume
    # is not issued. The run must remain PAUSED/"recovered" and the kernel must
    # remain "failed" — no operator-reopen marker is stamped.
    if recovered.status == RunStatus.PAUSED and is_clarification_pause_reason(
        recovered.pause_reason
    ):  # pragma: no cover - guard is False in this scenario
        async with session_factory() as session:
            await WorkflowService(session).apply_resume_run(run_id, resume_strategy="continue")

    async with session_factory() as session:
        after = await RunRepository(session).get(run_id)
    assert after.status == RunStatus.PAUSED
    assert after.pause_reason == "recovered"
    assert after.pause_reason != GRAPH_OPERATOR_REOPEN_PAUSE_REASON
    assert project_run_state(await _events(session_factory, run_id)) == "failed"


def test_is_clarification_pause_reason_classification() -> None:
    """The clarification-resume guard admits only user-action pause reasons."""
    from orchestrator.api import is_clarification_pause_reason

    assert is_clarification_pause_reason("awaiting_user_input") is True
    assert is_clarification_pause_reason("awaiting_clarification") is True
    # Fan-out children carry a parent_ prefix over the underlying reason.
    assert is_clarification_pause_reason("parent_awaiting_user_input") is True
    # Unrelated pause reasons must not trigger an auto-resume.
    assert is_clarification_pause_reason("recovered") is False
    assert is_clarification_pause_reason("manual_gate") is False
    assert is_clarification_pause_reason("agent_execution_error") is False
    assert is_clarification_pause_reason(None) is False


class NoOpDispatcher:
    """Suppresses ALL outbox delivery (decision D8, chunk 6).

    In this harness a *non-managed* dispatch always concludes with
    ``agent_died`` (``dispatch.py:972-974``, ``:1011-1012``) and a *managed*
    one always routes to ``request_runner_recovery`` (the boundary path) —
    neither can produce a genuinely orphaned lease. The one production shape
    the orphan-lease sweep exists for, per its own docstring
    (``graph_driver.py:1153-1159``), is an outbox item delivered by an
    executor this driver instance does not own. The faithful way to model
    that here is to never deliver the item at all: the controller, the real
    ``GraphRunDriver``, the real ``GraphDispatchExecutor`` and the real
    projection read path all run unmodified — only this one seam (outbox
    delivery) is stubbed, so the granted lease is never acknowledged and the
    driver's own orphan-lease recovery sweep is the only thing that can ever
    conclude it.
    """

    async def dispatch_pending(
        self,
        *,
        run_id: str | None = None,
        allowed_kinds: frozenset[str] | None = None,
    ) -> None:
        del run_id, allowed_kinds

    async def earliest_pending_retry_at(self, *, run_id: str | None = None) -> datetime | None:
        del run_id
        return None


def _routine_with_retry_budget(max_attempts: int) -> RoutineConfig:
    """Same single-worker/verifier shape as ``_routine()``, but with an
    explicit compiled retry budget well above ``MAX_NODE_RECOVERIES_PER_DRIVE``
    (decision D9's sanctioned fallback). Without this, the kernel's own
    default ``RetryConfig.max_attempts`` (3, ``config/models.py:187``) equals
    the driver's recovery budget (also 3), and — per branch precedence
    (D5, ``_commands.py:4240`` before ``:4283``) — the run would terminate via
    ``max_attempts_exhausted`` before the driver's ``recovery_exhausted``
    branch (chunk 3) ever fires. Bounding this node's compiled budget at 10
    guarantees the driver's smaller budget is what concludes it.
    """
    return RoutineConfig.model_validate(
        {
            "id": "graph-driver-missing-callback",
            "name": "Graph Driver Missing Callback",
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
                            "retry": {"max_attempts": max_attempts},
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


async def _drive_missing_callback_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    repo: Path,
    run_id: str,
) -> tuple[Any, list[EventEnvelope]]:
    """Drive one real graph run, end to end, through the real
    ``GraphController``, ``GraphRunDriver``, ``GraphDispatchExecutor`` and
    projection read path, with outbox delivery suppressed (``NoOpDispatcher``,
    D8). The single compiled worker node's lease is granted and then never
    acknowledged by anyone, so it is genuinely orphaned; only the driver's
    own orphan-lease recovery sweep can conclude it. Shared by both chunk-6
    tests so the setup is not duplicated.
    """
    await _create_graph_run(
        session_factory,
        _routine_with_retry_budget(10),
        run_id=run_id,
        repo=repo,
    )
    dispatch_order: list[str] = []
    driver = _driver(
        session_factory,
        repo=repo,
        agents={},
        dispatch_order=dispatch_order,
        dispatcher_factory=lambda *_args: NoOpDispatcher(),
    )
    outcome = await driver.run(run_id)
    events = await _events(session_factory, run_id)
    # Nothing was ever executed: the lease really was orphaned rather than
    # concluded by a runner that ran and then failed to call back.
    assert dispatch_order == []
    return outcome, events


@pytest.mark.asyncio
async def test_missing_callback_blocks_with_a_conclusively_revoked_lease(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """Scenario #9, closed end to end (facts X/Y, chunk 6).

    A missing callback that only the driver's own orphan-lease sweep can
    observe must stop at a conclusively revoked lease with a classified,
    retryable failure and paused recovery plan. It must never repeat an
    indistinguishable attempt or leave an active lease unaccounted for. This
    drives the REAL controller, kernel, driver and
    projection read path with real event-log reads on every call; no
    ``GraphProjectionSnapshot`` is constructed by hand anywhere in this test.
    """
    _, session_factory = file_db
    repo = tmp_path / "repo-missing-callback"
    _init_repo(repo)
    run_id = "graph-missing-callback"

    outcome, events = await _drive_missing_callback_scenario(session_factory, repo, run_id)

    projection = project_graph_projection_snapshot(events)
    assert projection.active_leases == {}  # criterion 3, end to end

    node_id = "worker-step-1-task-1"
    assert projection.node_states[node_id] == "blocked"

    node_failure_records = [
        event.payload["value"]
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "failure_record"
        and event.payload.get("producer_node_id") == node_id
    ]
    error_classes_seen = {value["error_class"] for value in node_failure_records}
    # Neither the compiled nor driver recovery budget authorizes an identical
    # retry. A differentiating recovery fact is required first.
    assert "max_attempts_exhausted" not in error_classes_seen
    assert "recovery_budget_exhausted" not in error_classes_seen
    recovery_required_records = [
        value
        for value in node_failure_records
        if value["error_class"] == "runtime_death_recovery_required"
    ]
    assert len(recovery_required_records) == 1
    (failure_value,) = recovery_required_records
    assert failure_value["failure_class"] == "infrastructure_failure"
    assert failure_value["retryable"] is True

    agent_died_indices = [i for i, event in enumerate(events) if event.event_type == "agent_died"]
    assert len(agent_died_indices) == 1
    died = events[agent_died_indices[0]]
    revoked_lease_id = died.payload.get("lease_id")
    trailing = events[agent_died_indices[0] + 1 : agent_died_indices[0] + 5]
    assert any(
        event.event_type == "lease_revoked" and event.payload.get("lease_id") == revoked_lease_id
        for event in trailing
    )
    assert any(
        event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "recovery_plan"
        and event.payload.get("value", {}).get("action") == "pause"
        for event in trailing
    )
    assert not any(event.event_type == "runtime_retry_scheduled" for event in events)
    assert len([event for event in events if event.event_type == "lease_granted"]) == 1

    assert outcome.completed is False
    assert outcome.blocked_reason is not None
    assert "worker-step-1-task-1=blocked" in outcome.blocked_reason
    assert "missing_required_input:candidate_under_test" in outcome.blocked_reason
    assert "active lease(s) without callback" not in (outcome.blocked_reason or "")


@pytest.mark.asyncio
async def test_missing_callback_never_pauses_with_an_active_lease(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """The negative pin (R7). Whatever the driver's exact command sequence,
    it must never leave the run row paused while the projection still shows
    an active lease, and no lease that was ever granted may be left
    unrevoked. This is the property that must survive even if a future
    change alters *how* the driver concludes.
    """
    _, session_factory = file_db
    repo = tmp_path / "repo-missing-callback-pin"
    _init_repo(repo)
    run_id = "graph-missing-callback-pin"

    _outcome, events = await _drive_missing_callback_scenario(session_factory, repo, run_id)

    granted_lease_ids = {
        event.payload["lease_id"] for event in events if event.event_type == "lease_granted"
    }
    revoked_lease_ids = {
        event.payload["lease_id"] for event in events if event.event_type == "lease_revoked"
    }
    assert granted_lease_ids  # sanity: leases really were granted along the way
    assert granted_lease_ids <= revoked_lease_ids  # none left dangling

    projection = project_graph_projection_snapshot(events)
    assert projection.active_leases == {}

    async with session_factory() as session:
        run_row = await RunRepository(session).get(run_id)
    assert run_row.status == RunStatus.PAUSED
    assert run_row.pause_reason == "graph_blocked"
