from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType
from orchestrator.config.models import RoutineConfig
from orchestrator.db import GraphOutboxModel, create_engine, create_session_factory, init_db
from orchestrator.graph import project_leases, project_residue_report, project_task_states
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    RecoveryReport,
    recover,
    reconcile_runtime,
    seed_run,
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


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class SequentialIds:
    def __init__(self, start: int = 1) -> None:
        self._next = start

    def next_id(self, prefix: str = "") -> str:
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value


class AgentFactory:
    def __init__(self, agents: dict[str, AgentRunner]) -> None:
        self._agents = agents

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
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


class ResidueSubmitAgent(SubmitAgent):
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
        Path(context.working_dir, "real-run-residue.txt").write_text("residue\n")
        await on_submit()
        return ExecutionResult(success=True)


class GradingAgent:
    def __init__(self, grade: str) -> None:
        self._grade = grade

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="grader")

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

    async def cancel(self) -> None:
        return None


class BlockingSubmitAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="blocking")

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
        self.started.set()
        await self.release.wait()
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        self.release.set()


class RaisingAgent:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="raising")

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
        raise RuntimeError("runner exploded")

    async def cancel(self) -> None:
        return None


class ReattachedSubmitProcess:
    def __init__(self, dispatch_payload: dict[str, object]) -> None:
        self._dispatch_payload = dispatch_payload

    def is_running(self, execution_id: str) -> bool:
        return execution_id == self._dispatch_payload["execution_id"]

    async def submit(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        controller: GraphController,
        run_id: str,
    ) -> None:
        node_id = str(self._dispatch_payload["node_id"])
        events = await _read_events(session_factory, run_id)
        node_payload = next(
            event.payload
            for event in events
            if event.event_type == "node_created" and event.payload.get("node_id") == node_id
        )
        candidate_id = str(node_payload["candidate_id"])
        task_region_id = str(node_payload["task_region_id"])
        attempt_number = int(node_payload["attempt_number"])
        output_records = [
            {
                "record_id": candidate_id,
                "record_kind": "output",
                "producer_node_id": node_id,
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": candidate_id,
                "task_region_id": task_region_id,
                "attempt_number": attempt_number,
                "value": {"summary": "submitted after process reattach"},
            },
            {
                "record_id": f"file-state-{node_id}",
                "record_kind": "file_state",
                "producer_node_id": node_id,
                "port": "file_state",
                "schema": "FileStateRecord",
                "snapshot_id": f"snapshot-{node_id}",
                "base_snapshot_id": str(self._dispatch_payload["base_snapshot_id"]),
                "task_region_id": task_region_id,
                "candidate_id": candidate_id,
                "verdict": "captured",
            },
        ]
        observed_position = await controller.current_position(run_id)
        await controller.handle_command(
            run_id,
            observed_position,
            "submit_callback",
            {
                "node_id": node_id,
                "execution_id": str(self._dispatch_payload["execution_id"]),
                "lease_id": str(self._dispatch_payload["lease_id"]),
                "lease_generation": int(self._dispatch_payload["generation"]),
                "base_snapshot_id": str(self._dispatch_payload["base_snapshot_id"]),
                "observed_graph_position": observed_position,
                "idempotency_key": f"{self._dispatch_payload['event_id']}:reattached-submit",
                "payload_hash": "reattached",
                "payload": {
                    "payload_hash": "reattached",
                    "output_records": output_records,
                },
            },
        )


@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph-runner.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-runner",
            "name": "Graph Runner",
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


async def _read_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
):
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _read_outbox_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[GraphOutboxModel]:
    async with session_factory() as session:
        result = await session.execute(
            select(GraphOutboxModel).order_by(GraphOutboxModel.outbox_id)
        )
        return list(result.scalars())


async def _seed_active_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    clock: FixedClock,
    ids: SequentialIds,
) -> GraphController:
    await seed_run(session_factory, _routine(), run_id=run_id, clock=clock, id_gen=ids)
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    position = await controller.current_position(run_id)
    accepted = await controller.handle_command(run_id, position, "accept_run")
    await controller.handle_command(run_id, accepted.projection_position, "start")
    return controller


async def _schedule_dispatch_and_wait(
    controller: GraphController,
    dispatcher: OutboxDispatcher,
    executor: GraphDispatchExecutor,
    run_id: str,
) -> None:
    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await executor.wait_for_all()


@pytest.mark.asyncio
async def test_graph_runner_builder_verifier_pass_accepts_task(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-pass"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-pass"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": ResidueSubmitAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)
    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events = await _read_events(session_factory, run_id)
    assert project_task_states(events) == {"step-1/task-1": "accepted"}
    residue_report = project_residue_report(events)
    assert residue_report["real-run-residue.txt"][0]["classification"] == "unknown_untracked"


@pytest.mark.asyncio
async def test_graph_runner_verifier_fail_needs_revision(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-fail"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-fail"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("C")}),
        worktree_path=repo,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)
    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events = await _read_events(session_factory, run_id)
    assert project_task_states(events) == {"step-1/task-1": "needs_revision"}


@pytest.mark.asyncio
async def test_graph_runner_restart_reattaches_running_builder(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    engine, session_factory = file_db
    db_path = tmp_path / "graph-runner.db"
    repo = tmp_path / "repo-reattach"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-reattach"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    builder = BlockingSubmitAgent()
    running: dict[str, asyncio.Task[None]] = {}
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": builder, "verifier": GradingAgent("A")}),
        worktree_path=repo,
        running_executions=running,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    scheduled = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await asyncio.wait_for(builder.started.wait(), timeout=2)
    dispatch_payload = dict(scheduled.outbox_items[0].payload)

    for task in running.values():
        task.cancel()
    await asyncio.gather(*running.values(), return_exceptions=True)
    running.clear()
    await engine.dispose()

    restarted_engine = create_engine(db_path)
    try:
        restarted_session_factory = create_session_factory(restarted_engine)
        restarted_clock = FixedClock()
        restarted_ids = SequentialIds(start=1000)
        live_process = ReattachedSubmitProcess(dispatch_payload)
        restarted_controller = GraphController(
            restarted_session_factory,
            restarted_clock,
            restarted_ids,
            auto_dispatch=False,
        )
        restarted_executor = GraphDispatchExecutor(
            restarted_session_factory,
            restarted_controller,
            AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
            worktree_path=repo,
            process_registry=live_process,
        )
        restarted_dispatcher = OutboxDispatcher(
            restarted_session_factory,
            restarted_executor,
            restarted_clock,
        )
        report = await recover(restarted_session_factory, restarted_dispatcher, run_id=run_id)
        await reconcile_runtime(restarted_controller, restarted_executor, report)

        await live_process.submit(restarted_session_factory, restarted_controller, run_id)
        await _schedule_dispatch_and_wait(
            restarted_controller,
            restarted_dispatcher,
            restarted_executor,
            run_id,
        )

        events = await _read_events(restarted_session_factory, run_id)
        assert project_task_states(events) == {"step-1/task-1": "accepted"}
        assert not any(event.event_type == "agent_died" for event in events)
    finally:
        await restarted_engine.dispose()


@pytest.mark.asyncio
async def test_graph_runner_restart_marks_missing_builder_dead_and_redispatches(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-dead"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-dead"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    builder = BlockingSubmitAgent()
    running: dict[str, asyncio.Task[None]] = {}
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": builder, "verifier": GradingAgent("A")}),
        worktree_path=repo,
        running_executions=running,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await asyncio.wait_for(builder.started.wait(), timeout=2)
    for task in running.values():
        task.cancel()
    running.clear()

    restarted_controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    restarted_executor = GraphDispatchExecutor(
        session_factory,
        restarted_controller,
        AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
    )
    restarted_dispatcher = OutboxDispatcher(session_factory, restarted_executor, clock)
    report = await recover(session_factory, restarted_dispatcher, run_id=run_id)
    await reconcile_runtime(restarted_controller, restarted_executor, report)

    await _schedule_dispatch_and_wait(
        restarted_controller,
        restarted_dispatcher,
        restarted_executor,
        run_id,
    )
    await _schedule_dispatch_and_wait(
        restarted_controller,
        restarted_dispatcher,
        restarted_executor,
        run_id,
    )

    events = await _read_events(session_factory, run_id)
    assert project_task_states(events) == {"step-1/task-1": "accepted"}
    assert any(event.event_type == "agent_died" for event in events)


@pytest.mark.asyncio
async def test_reconcile_runtime_skips_lease_already_recovered_by_another_driver(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-reconcile-stale"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-reconcile-stale"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
    )
    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    projection = await controller.read_projection(run_id)
    active_lease = next(
        lease for lease in projection["leases"].values() if lease.get("state") == "active"
    )
    stale_lease = {
        "run_id": run_id,
        "lease_id": str(active_lease["lease_id"]),
        "node_id": str(active_lease["node_id"]),
        "generation": int(active_lease["generation"]),
        "execution_id": str(active_lease["execution_id"]),
        "classification": "awaiting_start_ack",
    }

    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "agent_died",
        {
            "lease_id": str(stale_lease["lease_id"]),
            "execution_id": str(stale_lease["execution_id"]),
            "reason": "other_driver_already_reconciled",
        },
    )

    stale_report = RecoveryReport(
        redispatched=[],
        pending_cleanups=[],
        awaiting_start_ack=[stale_lease],
        awaiting_callback=[],
    )
    await reconcile_runtime(controller, executor, stale_report)

    events = await _read_events(session_factory, run_id)
    assert len([event for event in events if event.event_type == "agent_died"]) == 1
    assert not any(event.event_type == "command_rejected" for event in events)


@pytest.mark.asyncio
async def test_graph_runner_exception_appends_agent_died_and_releases_retry(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-raise"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-raise"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    failing_executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": RaisingAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
    )
    failing_dispatcher = OutboxDispatcher(session_factory, failing_executor, clock)

    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await failing_dispatcher.dispatch_pending()
    await failing_executor.wait_for_all()

    events_after_failure = await _read_events(session_factory, run_id)
    assert any(event.event_type == "agent_died" for event in events_after_failure)
    dead_lease = next(
        event.payload for event in events_after_failure if event.event_type == "agent_died"
    )
    leases_after_failure = project_leases(events_after_failure)
    assert not any(
        lease.get("execution_id") == dead_lease["execution_id"] and lease.get("state") == "active"
        for lease in leases_after_failure.values()
    )
    assert any(
        event.event_type == "node_state_changed"
        and event.payload.get("node_id") == dead_lease["node_id"]
        and event.payload.get("new_state") == "ready"
        for event in events_after_failure
    )

    healthy_executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
    )
    healthy_dispatcher = OutboxDispatcher(session_factory, healthy_executor, clock)
    await _schedule_dispatch_and_wait(controller, healthy_dispatcher, healthy_executor, run_id)
    await _schedule_dispatch_and_wait(controller, healthy_dispatcher, healthy_executor, run_id)

    events = await _read_events(session_factory, run_id)
    assert project_task_states(events) == {"step-1/task-1": "accepted"}


@pytest.mark.asyncio
async def test_graph_runner_rejects_stale_generation_callback_through_stack(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-stale"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-stale"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    builder = BlockingSubmitAgent()
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": builder, "verifier": GradingAgent("A")}),
        worktree_path=repo,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    scheduled = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await asyncio.wait_for(builder.started.wait(), timeout=2)

    dispatch_payload = scheduled.outbox_items[0].payload
    stale = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "submit_callback",
        {
            "node_id": str(dispatch_payload["node_id"]),
            "execution_id": str(dispatch_payload["execution_id"]),
            "lease_id": str(dispatch_payload["lease_id"]),
            "lease_generation": 0,
            "base_snapshot_id": str(dispatch_payload["base_snapshot_id"]),
            "observed_graph_position": await controller.current_position(run_id),
            "idempotency_key": "stale-generation",
            "payload_hash": "stale",
            "payload": {"payload_hash": "stale", "output_records": []},
        },
    )

    executor.cancel_all()

    assert [event.event_type for event in stale.events] == ["callback_rejected_stale"]


@pytest.mark.asyncio
async def test_graph_dispatch_requires_base_snapshot_id_without_inventing_identity(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-missing-snapshot"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-missing-snapshot"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock, max_attempts=1)

    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1, "base_snapshot_id": "snapshot-custom"},
    )
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(GraphOutboxModel).where(GraphOutboxModel.run_id == run_id)
            )
            row = result.scalar_one()
            payload = dict(row.payload)
            payload.pop("base_snapshot_id")
            row.payload = payload

    await dispatcher.dispatch_pending()

    rows = await _read_outbox_rows(session_factory)
    failed = next(row for row in rows if row.run_id == run_id)
    assert failed.status == "failed"
    assert failed.last_error == "agent dispatch payload missing base_snapshot_id"

    events = await _read_events(session_factory, run_id)
    assert not any(
        event.event_type in {"callback_accepted", "callback_rejected_stale", "agent_died"}
        for event in events
    )
    assert not executor.is_running(str(failed.payload["execution_id"]))


@pytest.mark.asyncio
async def test_graph_dispatch_carries_projection_base_snapshot_id_to_callback(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-custom-snapshot"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-custom-snapshot"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    scheduled = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await executor.wait_for_all()

    dispatch_payload = scheduled.outbox_items[0].payload
    events = await _read_events(session_factory, run_id)
    lease_granted = next(event for event in events if event.event_type == "lease_granted")
    assert lease_granted.payload["base_snapshot_id"] == "routine-snapshot-record"
    assert dispatch_payload["base_snapshot_id"] == "routine-snapshot-record"
    assert any(event.event_type == "callback_accepted" for event in events)
    assert not any(event.event_type == "callback_rejected_stale" for event in events)
