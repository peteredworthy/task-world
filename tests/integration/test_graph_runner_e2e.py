from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.artifacts import FilesystemArtifactStore, StoredArtifactRef
from orchestrator.config.enums import AgentRunnerType
from orchestrator.config.models import RoutineConfig
from orchestrator.db import GraphOutboxModel, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    EventEnvelope,
    accepted_output_records_by_node_port_view,
    leases_view,
    node_states_view,
    execution_attempts_view,
    projection_from_checkpoint,
    projection_to_checkpoint,
    project_residue_report,
    project_task_states,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    RecoveryReport,
    RunnerOwnedProcessRegistry,
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

pytestmark = pytest.mark.e2e


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


class CacheBudgetSubmitAgent(SubmitAgent):
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
        cache = Path(context.working_dir, "node_modules", "dependency")
        cache.mkdir(parents=True)
        (cache / "id_rsa").write_text("secret", encoding="utf-8")
        await on_submit()
        return ExecutionResult(success=True)


class OverflowCacheBudgetSubmitAgent(CacheBudgetSubmitAgent):
    def __init__(self, count: int) -> None:
        self._count = count

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
        for index in range(self._count):
            Path(context.working_dir, f"overflow-{index:05d}.txt").write_text("runner\n")
        return await super().execute(
            context,
            on_checklist_update,
            on_submit,
            on_output,
            on_grade,
            on_agent_metadata,
            on_escalation,
        )


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


class CancellationMutatingAgent:
    """Keeps ownership until the test permits cancellation to finish."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancellation_started = asyncio.Event()
        self.finish_cancellation = asyncio.Event()

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="cancel-mutating"
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
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            Path(context.working_dir, "README.md").write_text("mutation during cancellation\n")
            self.cancellation_started.set()
            await self.finish_cancellation.wait()
            raise

        raise AssertionError("cancellation-mutating runner unexpectedly completed")

    async def cancel(self) -> None:
        return None


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
        Path(context.working_dir, "README.md").write_text("changed by raising runner\n")
        raise RuntimeError("runner exploded")

    async def cancel(self) -> None:
        return None


class MutatingNoSubmitAgent:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="mutating")

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
        Path(context.working_dir, "README.md").write_text("changed by managed runner\n")
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class SubmitThenFailAgent(SubmitAgent):
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
        Path(context.working_dir, "README.md").write_text("changed before failed result\n")
        await on_submit()
        return ExecutionResult(success=False)


class SubmitThenMutateBoundaryAgent(SubmitAgent):
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
        Path(context.working_dir, "README.md").write_text("changed before submission\n")
        await on_submit()
        Path(context.working_dir, "README.md").write_text("changed after submission\n")
        return ExecutionResult(success=True)


class StagedThenUnsuccessfulAgent(SubmitAgent):
    """Stages output, then waits before its unsuccessful exit is observable."""

    def __init__(self) -> None:
        self.staged = asyncio.Event()
        self.return_unsuccessfully = asyncio.Event()

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
        Path(context.working_dir, "README.md").write_text("changed before failed result\n")
        await on_submit()
        self.staged.set()
        await self.return_unsuccessfully.wait()
        return ExecutionResult(success=False)


class StagedThenSuccessfulAgent(SubmitAgent):
    """Stages output, then waits so the durable callback artifact can be faulted."""

    def __init__(self) -> None:
        self.staged = asyncio.Event()
        self.finish = asyncio.Event()

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
        Path(context.working_dir, "README.md").write_text("changed before submission\n")
        await on_submit()
        self.staged.set()
        await self.finish.wait()
        return ExecutionResult(success=True)


class IgnoredToUntrackedStagedAgent(SubmitAgent):
    def __init__(self) -> None:
        self.staged = asyncio.Event()
        self.finish = asyncio.Event()

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
        Path(context.working_dir, ".gitignore").write_text("")
        await on_submit()
        self.staged.set()
        await self.finish.wait()
        return ExecutionResult(success=False)


class ReattachedSubmitProcess:
    """One live runner task whose callback/lock move to the restarted executor."""

    def __init__(self) -> None:
        self._execution_id: str | None = None
        self._task: asyncio.Task[object] | None = None
        self._submit_callback: Callable[[list[dict[str, object]]], Awaitable[None]] | None = None
        self._worktree_execution_lock: asyncio.Lock | None = None
        self.started = asyncio.Event()
        self.transferred = asyncio.Event()
        self.proceed_mutation = asyncio.Event()

    def is_running(self, execution_id: str) -> bool:
        return (
            execution_id == self._execution_id and self._task is not None and not self._task.done()
        )

    def own_execution(self, execution_id: str) -> None:
        assert self._task is not None
        self._execution_id = execution_id

    async def try_reattach(
        self,
        execution_id: str,
        callback: Callable[[list[dict[str, object]]], Awaitable[None]],
        worktree_execution_lock: asyncio.Lock,
    ) -> bool:
        if not self.is_running(execution_id):
            return False
        # No await separates replacing the live task's completion route from
        # replacing its worktree serialization owner.
        self._submit_callback = callback
        self._worktree_execution_lock = worktree_execution_lock
        self.transferred.set()
        return True

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="reattached")

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
        del on_checklist_update, on_submit, on_output, on_grade, on_agent_metadata, on_escalation
        self._task = asyncio.current_task()
        assert self._task is not None
        self.started.set()
        await self.transferred.wait()
        await self.proceed_mutation.wait()
        assert self._submit_callback is not None
        assert self._worktree_execution_lock is not None
        async with self._worktree_execution_lock:
            Path(context.working_dir, "README.md").write_text("mutated by reattached owner\n")
            output_records = [
                {
                    "record_id": f"candidate-{context.node_id}",
                    "record_kind": "output",
                    "producer_node_id": context.node_id,
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "value": {"summary": "submitted after process reattach"},
                },
            ]
        await self._submit_callback(output_records)
        await self._submit_callback(output_records)
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph-runner.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


def _routine(*, max_attempts: int = 3, scan_budget: dict[str, int] | None = None) -> RoutineConfig:
    payload: dict[str, object] = {
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
    if scan_budget is not None:
        payload["file_state_policy"] = {"scan_budget": scan_budget}
    return RoutineConfig.model_validate(payload)


def _cache_transition_routine(max_attempts: int) -> RoutineConfig:
    routine = _routine(max_attempts=max_attempts).model_dump(mode="json")
    routine["file_state_policy"] = {
        "declarations": [
            {
                "pattern": "custom-cache/**",
                "classification": "tool_cache",
                "source_kinds": ["ignored", "untracked"],
            }
        ]
    }
    return RoutineConfig.model_validate(routine)


def _parallel_artifact_routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-parallel-artifacts",
            "name": "Graph Parallel Artifacts",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "docs",
                            "title": "Docs artifact",
                            "task_context": "Write docs/out.txt only.",
                            "artifacts": [{"path": "docs/out.txt"}],
                        },
                        {
                            "id": "tests",
                            "title": "Tests artifact",
                            "task_context": "Write tests/out.txt only.",
                            "artifacts": [{"path": "tests/out.txt"}],
                        },
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


async def _read_staged_output_records(
    event: EventEnvelope,
    artifact_store: FilesystemArtifactStore,
) -> list[dict[str, object]]:
    """Resolve a new staged callback through its public content-addressed store."""
    assert "payload" not in event.payload
    ref = StoredArtifactRef.model_validate(event.payload["payload_ref"])
    content = await artifact_store.read(ref)
    payload = json.loads(content.decode("utf-8"))
    assert isinstance(payload, dict)
    records = payload.get("output_records")
    assert isinstance(records, list)
    assert all(isinstance(record, dict) for record in records)
    return [cast(dict[str, object], record) for record in records]


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
    routine: RoutineConfig | None = None,
) -> GraphController:
    await seed_run(session_factory, routine or _routine(), run_id=run_id, clock=clock, id_gen=ids)
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
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)
    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events = await _read_events(session_factory, run_id)
    assert project_task_states(events) == {"step-1/task-1": "accepted"}
    residue_report = project_residue_report(events)
    assert residue_report["real-run-residue.txt"][0]["classification"] == "unknown_untracked"


@pytest.mark.asyncio
async def test_parallel_worker_start_acknowledgements_retry_stale_positions(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-parallel-start"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-parallel-start"
    controller = await _seed_active_run(
        session_factory,
        run_id,
        clock,
        ids,
        routine=_parallel_artifact_routine(),
    )
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": SubmitAgent()}),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 2, "base_snapshot_id": "snapshot-parallel"},
    )
    await dispatcher.dispatch_pending()
    await executor.wait_for_all()

    events = await _read_events(session_factory, run_id)
    lease_grants = [event for event in events if event.event_type == "lease_granted"]
    assert [event.payload["node_id"] for event in lease_grants] == [
        "worker-step-1-docs",
        "worker-step-1-tests",
    ]
    assert not any(event.event_type == "agent_died" for event in events)
    assert len([event for event in events if event.event_type == "callback_accepted"]) == 2


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
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)
    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events = await _read_events(session_factory, run_id)
    assert project_task_states(events) == {
        "step-1/task-1": "needs_revision",
        "recovery-step-1-task-1": "pending",
    }


@pytest.mark.asyncio
async def test_graph_runner_restart_reattaches_running_builder(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    engine, session_factory = file_db
    repo = tmp_path / "repo-reattach"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-reattach"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    live_process = ReattachedSubmitProcess()
    running: dict[str, asyncio.Task[None]] = {}
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": live_process, "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        running_executions=running,
        process_registry=live_process,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    scheduled = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await asyncio.wait_for(live_process.started.wait(), timeout=2)
    dispatch_payload = dict(scheduled.outbox_items[0].payload)
    live_process.own_execution(str(dispatch_payload["execution_id"]))
    assert live_process.is_running(str(dispatch_payload["execution_id"]))
    owner_task = next(iter(running.values()))
    restarted_engine = engine
    try:
        restarted_session_factory = create_session_factory(restarted_engine)
        restarted_clock = FixedClock()
        restarted_ids = SequentialIds(start=1000)
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
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
            process_registry=live_process,
        )
        restarted_dispatcher = OutboxDispatcher(
            restarted_session_factory,
            restarted_executor,
            restarted_clock,
        )
        report = await recover(restarted_session_factory, restarted_dispatcher, run_id=run_id)
        reconciliation = asyncio.create_task(
            reconcile_runtime(restarted_controller, restarted_executor, report)
        )
        await asyncio.wait_for(live_process.transferred.wait(), timeout=2)
        await restarted_executor._worktree_execution_lock.acquire()
        try:
            live_process.proceed_mutation.set()
            await asyncio.sleep(0)
            assert (repo / "README.md").read_text() == "# tmp repo\n"
        finally:
            restarted_executor._worktree_execution_lock.release()
        await reconciliation
        await asyncio.wait_for(owner_task, timeout=2)
        await _schedule_dispatch_and_wait(
            restarted_controller,
            restarted_dispatcher,
            restarted_executor,
            run_id,
        )

        events = await _read_events(restarted_session_factory, run_id)
        assert project_task_states(events) == {"step-1/task-1": "accepted"}
        assert not any(event.event_type == "agent_died" for event in events)
        reattached_events = [
            event
            for event in events
            if event.payload.get("execution_id") == dispatch_payload["execution_id"]
        ]
        assert [event.event_type for event in reattached_events].count(
            "runner_submission_staged"
        ) == 1
        assert [event.event_type for event in reattached_events].count(
            "runner_execution_finalized"
        ) == 1
        assert (repo / "README.md").read_text() == "mutated by reattached owner\n"
        assert len(running) == 1
    finally:
        if not owner_task.done():
            owner_task.cancel()
        await asyncio.gather(owner_task, return_exceptions=True)


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
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
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
    abandoned_tasks = list(running.values())
    running.clear()
    try:
        restarted_controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
        restarted_executor = GraphDispatchExecutor(
            session_factory,
            restarted_controller,
            AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
        restarted_dispatcher = OutboxDispatcher(session_factory, restarted_executor, clock)
        report = await recover(session_factory, restarted_dispatcher, run_id=run_id)
        await reconcile_runtime(
            restarted_controller, restarted_executor, report, restarted_dispatcher
        )

        recovered_events = await _read_events(session_factory, run_id)
        assert any(
            event.event_type == "runner_recovery_requested"
            and event.payload.get("reason") == "runner_died"
            for event in recovered_events
        )
        assert any(event.event_type == "runner_recovery_completed" for event in recovered_events)

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
        assert not any(event.event_type == "agent_died" for event in events)
    finally:
        for task in abandoned_tasks:
            task.cancel()
        await asyncio.gather(*abandoned_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_runner_refusal_quiesces_mutating_owner_before_recovery(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """Recovery cannot restore while a refused live owner can still mutate."""
    _, session_factory = file_db
    repo = tmp_path / "repo-refusal-quiescence"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-refusal-quiescence"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    agent = CancellationMutatingAgent()
    registry = RunnerOwnedProcessRegistry()
    running: dict[str, asyncio.Task[None]] = {}
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        running_executions=running,
        process_registry=registry,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await asyncio.wait_for(agent.started.wait(), timeout=2)
    old_task = next(iter(running.values()))
    restarted_controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    restarted_executor = GraphDispatchExecutor(
        session_factory,
        restarted_controller,
        AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        process_registry=registry,
    )
    restarted_dispatcher = OutboxDispatcher(session_factory, restarted_executor, clock)
    try:
        report = await recover(session_factory, restarted_dispatcher, run_id=run_id)
        reconciliation = asyncio.create_task(
            reconcile_runtime(
                restarted_controller,
                restarted_executor,
                report,
                restarted_dispatcher,
            )
        )
        await asyncio.wait_for(agent.cancellation_started.wait(), timeout=2)
        assert not reconciliation.done()
        assert (repo / "README.md").read_text() == "mutation during cancellation\n"
        events_while_owner_live = await _read_events(session_factory, run_id)
        assert not any(
            event.event_type == "runner_recovery_requested" for event in events_while_owner_live
        )

        agent.finish_cancellation.set()
        await asyncio.wait_for(reconciliation, timeout=2)
        assert old_task.done()

        events = await _read_events(session_factory, run_id)
        assert any(
            event.event_type == "runner_recovery_requested"
            and event.payload.get("reason") == "runner_died"
            for event in events
        )
        assert any(event.event_type == "runner_recovery_completed" for event in events)
        assert (repo / "README.md").read_text() == "# tmp repo\n"
        await _schedule_dispatch_and_wait(
            restarted_controller, restarted_dispatcher, restarted_executor, run_id
        )
        await _schedule_dispatch_and_wait(
            restarted_controller, restarted_dispatcher, restarted_executor, run_id
        )
        assert project_task_states(await _read_events(session_factory, run_id)) == {
            "step-1/task-1": "accepted"
        }
    finally:
        agent.finish_cancellation.set()
        if not old_task.done():
            old_task.cancel()
        await asyncio.gather(old_task, return_exceptions=True)


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
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    projection = await controller.read_projection(run_id)
    active_lease = next(
        iter((lease for lease in leases_view(projection).values() if lease.state == "active"))
    )
    stale_lease = {
        "run_id": run_id,
        "lease_id": active_lease.lease_id,
        "node_id": active_lease.node_id,
        "generation": active_lease.generation,
        "execution_id": active_lease.execution_id,
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
async def test_graph_runner_exception_requests_recovery_before_retry(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-raise"
    _init_repo(repo)
    (repo / "unrelated-dirt.txt").write_text("preserve me\n")
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-raise"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    failing_executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": RaisingAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
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
    baselines = [
        event for event in events_after_failure if event.event_type == "runner_baseline_recorded"
    ]
    assert len(baselines) == 1
    execution_id = str(baselines[0].payload["execution_id"])
    recovery_requests = [
        event
        for event in events_after_failure
        if event.event_type == "runner_recovery_requested"
        and event.payload.get("execution_id") == execution_id
    ]
    assert len(recovery_requests) == 1
    recovery_request = recovery_requests[0]
    assert recovery_request.payload["reason"] == "runner_died"
    assert not any(
        event.payload.get("execution_id") == execution_id
        and event.event_type
        in {
            "runner_submission_staged",
            "runner_execution_finalized",
            "callback_accepted",
            "agent_died",
        }
        for event in events_after_failure
    )
    projection_after_failure = await controller.read_projection(run_id)
    node_id = str(recovery_request.payload["node_id"])
    assert (
        accepted_output_records_by_node_port_view(projection_after_failure)
        .get(node_id, {})
        .get("candidate", [])
        == []
    )
    assert node_states_view(projection_after_failure).get(node_id) != "ready"

    recovery_rows = [
        row
        for row in await _read_outbox_rows(session_factory)
        if row.kind == "runner_recovery" and row.payload["execution_id"] == execution_id
    ]
    assert len(recovery_rows) == 1
    assert recovery_rows[0].status == "pending"
    assert (repo / "README.md").read_text() == "changed by raising runner\n"
    assert (repo / "unrelated-dirt.txt").read_text() == "preserve me\n"

    completed = await failing_dispatcher.dispatch_pending(
        run_id=run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    assert [item.kind for item in completed] == ["runner_recovery"]

    events = await _read_events(session_factory, run_id)
    completions = [
        event
        for event in events
        if event.event_type == "runner_recovery_completed"
        and event.payload.get("execution_id") == execution_id
    ]
    assert len(completions) == 1
    lease_revoked = next(
        event
        for event in events
        if event.event_type == "lease_revoked" and event.payload.get("execution_id") == execution_id
    )
    retry_scheduled = next(
        event
        for event in events
        if event.event_type == "runtime_retry_scheduled" and event.payload.get("node_id") == node_id
    )
    retry_ready = next(
        event
        for event in events
        if event.event_type == "node_state_changed"
        and event.payload.get("node_id") == node_id
        and event.payload.get("new_state") == "ready"
        and event.payload.get("trigger") == "runner_recovery_completed_retry_scheduled"
    )
    assert (
        completions[0].position
        < lease_revoked.position
        < retry_scheduled.position
        < retry_ready.position
    )
    assert (repo / "README.md").read_text() == "# tmp repo\n"
    assert (repo / "unrelated-dirt.txt").read_text() == "preserve me\n"
    projection_after_recovery = await controller.read_projection(run_id)
    assert not any(
        lease.execution_id == execution_id
        for lease in (
            lease
            for lease in leases_view(projection_after_recovery).values()
            if lease.state == "active"
        )
    )
    assert node_states_view(projection_after_recovery).get(node_id) == "ready"


@pytest.mark.asyncio
async def test_cache_budget_exhaustion_rejects_submission_and_recovers_after_restart(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """A compiled byte budget survives replay and cannot strand a managed lease."""
    _, session_factory = file_db
    repo = tmp_path / "repo-cache-budget"
    _init_repo(repo)
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_text(f"{exclude.read_text(encoding='utf-8')}node_modules/\n", encoding="utf-8")
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-cache-budget"
    controller = await _seed_active_run(
        session_factory,
        run_id,
        clock,
        ids,
        _routine(scan_budget={"max_entries": 10, "max_bytes": 1}),
    )
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": CacheBudgetSubmitAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events_before_restart = await _read_events(session_factory, run_id)
    baseline = next(
        event for event in events_before_restart if event.event_type == "runner_baseline_recorded"
    )
    execution_id = str(baseline.payload["execution_id"])
    recovery = next(
        event
        for event in events_before_restart
        if event.event_type == "runner_recovery_requested"
        and event.payload.get("execution_id") == execution_id
    )
    assert recovery.payload["recovery_scope"] == "full_baseline"
    assert recovery.payload["final_boundary_entries"] == []
    assert recovery.payload["paths"] == []
    assert not any(
        event.event_type
        in {"runner_submission_staged", "runner_execution_finalized", "callback_accepted"}
        and event.payload.get("execution_id") == execution_id
        for event in events_before_restart
    )
    projection_before_restart = await controller.read_projection(run_id)
    assert (
        accepted_output_records_by_node_port_view(projection_before_restart)
        .get(str(recovery.payload["node_id"]), {})
        .get("candidate", [])
        == []
    )
    assert (repo / "node_modules" / "dependency" / "id_rsa").exists()

    # A fresh runtime reconstructs policy/attempt state from durable events;
    # recovery needs no process-local scan or baseline cache.
    restarted = GraphController(session_factory, clock, ids, auto_dispatch=False)
    restarted_executor = GraphDispatchExecutor(
        session_factory,
        restarted,
        AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts-restarted"),
    )
    restarted_dispatcher = OutboxDispatcher(session_factory, restarted_executor, clock)
    completed = await restarted_dispatcher.dispatch_pending(
        run_id=run_id, allowed_kinds=frozenset({"runner_recovery"})
    )

    assert [item.kind for item in completed] == ["runner_recovery"]
    assert not (repo / "node_modules").exists()
    events = await _read_events(session_factory, run_id)
    assert any(
        event.event_type == "runner_recovery_completed"
        and event.payload.get("execution_id") == execution_id
        for event in events
    )
    assert any(
        event.event_type == "lease_revoked" and event.payload.get("execution_id") == execution_id
        for event in events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path_count", [10_000, 10_001])
async def test_cache_budget_overflow_uses_durable_full_baseline_recovery_scope(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
    path_count: int,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-cache-budget-overflow"
    _init_repo(repo)
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_text(
        f"{exclude.read_text(encoding='utf-8')}node_modules/\n.venv/\npreexisting-ignored.log\n",
        encoding="utf-8",
    )
    (repo / "preexisting.txt").write_text("preserve untracked\n")
    (repo / "preexisting-ignored.log").write_text("preserve ignored\n")
    large_cache = repo / ".venv" / "lib" / "cache.bin"
    large_cache.parent.mkdir(parents=True)
    large_cache.write_bytes(b"x" * (2 * 1024 * 1024))
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-cache-budget-overflow"
    controller = await _seed_active_run(
        session_factory,
        run_id,
        clock,
        ids,
        _routine(scan_budget={"max_entries": 10, "max_bytes": 1}),
    )
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory(
            {"worker": OverflowCacheBudgetSubmitAgent(path_count), "verifier": GradingAgent("A")}
        ),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)
    events_before_restart = await _read_events(session_factory, run_id)
    recovery = next(
        event for event in events_before_restart if event.event_type == "runner_recovery_requested"
    )
    baseline = next(
        event for event in events_before_restart if event.event_type == "runner_baseline_recorded"
    )
    baseline_names = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", str(baseline.payload["baseline_commit_sha"])],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "preexisting.txt" in baseline_names
    assert "preexisting-ignored.log" in baseline_names
    assert not any(name.startswith((".venv/", "node_modules/")) for name in baseline_names)
    execution_id = str(recovery.payload["execution_id"])
    assert recovery.payload["recovery_scope"] == "full_baseline"
    assert recovery.payload["paths"] == []
    assert recovery.payload["final_boundary_entries"] == []
    assert not any(event.event_type == "command_rejected" for event in events_before_restart)
    assert not any(
        event.event_type
        in {"runner_submission_staged", "runner_execution_finalized", "callback_accepted"}
        for event in events_before_restart
    )

    restarted = GraphController(session_factory, clock, ids, auto_dispatch=False)
    restarted_executor = GraphDispatchExecutor(
        session_factory,
        restarted,
        AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts-restarted"),
    )
    completed = await OutboxDispatcher(session_factory, restarted_executor, clock).dispatch_pending(
        run_id=run_id, allowed_kinds=frozenset({"runner_recovery"})
    )

    assert [item.kind for item in completed] == ["runner_recovery"]
    assert (repo / "preexisting.txt").read_text() == "preserve untracked\n"
    assert (repo / "preexisting-ignored.log").read_text() == "preserve ignored\n"
    assert not (repo / "overflow-00000.txt").exists()
    assert not (repo / f"overflow-{path_count - 1:05d}.txt").exists()
    assert not (repo / "node_modules").exists()
    events = await _read_events(session_factory, run_id)
    completion = next(
        event
        for event in events
        if event.event_type == "runner_recovery_completed"
        and event.payload.get("execution_id") == execution_id
    )
    assert completion.payload["recovery_scope"] == "full_baseline"
    assert completion.payload["requested_paths"] == []
    projection = await restarted.read_projection(run_id)
    attempt = execution_attempts_view(projection)[execution_id]
    assert attempt.state == "recovered"
    assert attempt.recovery_scope == "full_baseline"
    assert attempt.recovery_paths == ()
    checkpoint_attempt = execution_attempts_view(
        projection_from_checkpoint(projection_to_checkpoint(projection))
    )[execution_id]
    assert checkpoint_attempt.recovery_scope == "full_baseline"


@pytest.mark.asyncio
async def test_graph_runner_unsuccessful_result_recovers_staged_submission_before_retry(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-unsuccessful-result"
    _init_repo(repo)
    (repo / "unrelated-dirt.txt").write_text("preserve me\n")
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-unsuccessful-result"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": SubmitThenFailAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=artifact_store,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await executor.wait_for_all()

    events_before_recovery = await _read_events(session_factory, run_id)
    baselines = [
        event for event in events_before_recovery if event.event_type == "runner_baseline_recorded"
    ]
    assert len(baselines) == 1
    execution_id = str(baselines[0].payload["execution_id"])
    staged = [
        event
        for event in events_before_recovery
        if event.event_type == "runner_submission_staged"
        and event.payload.get("execution_id") == execution_id
    ]
    assert len(staged) == 1
    staged_records = await _read_staged_output_records(staged[0], artifact_store)
    staged_record_ids = {str(record["record_id"]) for record in staged_records}
    assert staged_record_ids

    recovery_requests = [
        event
        for event in events_before_recovery
        if event.event_type == "runner_recovery_requested"
        and event.payload.get("execution_id") == execution_id
    ]
    assert len(recovery_requests) == 1
    recovery_request = recovery_requests[0]
    assert recovery_request.payload["reason"] == "runner_died"
    node_id = str(recovery_request.payload["node_id"])
    assert not any(
        event.event_type == "agent_died" and event.payload.get("execution_id") == execution_id
        for event in events_before_recovery
    )
    assert not any(
        event.event_type in {"output_record_accepted", "file_state_accepted"}
        and event.payload.get("record_id") in staged_record_ids
        for event in events_before_recovery
    )
    assert not any(
        event.event_type in {"callback_accepted", "runner_execution_finalized"}
        and event.payload.get("execution_id") == execution_id
        for event in events_before_recovery
    )
    assert not any(
        event.event_type == "runtime_retry_scheduled" and event.payload.get("node_id") == node_id
        for event in events_before_recovery
    )
    assert node_states_view(await controller.read_projection(run_id)).get(node_id) != "ready"
    assert (repo / "README.md").read_text() == "changed before failed result\n"
    assert (repo / "unrelated-dirt.txt").read_text() == "preserve me\n"

    recovery_rows = [
        row
        for row in await _read_outbox_rows(session_factory)
        if row.kind == "runner_recovery" and row.payload.get("execution_id") == execution_id
    ]
    assert len(recovery_rows) == 1
    assert recovery_rows[0].status == "pending"

    completed = await dispatcher.dispatch_pending(
        run_id=run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    assert [item.kind for item in completed] == ["runner_recovery"]

    events = await _read_events(session_factory, run_id)
    completions = [
        event
        for event in events
        if event.event_type == "runner_recovery_completed"
        and event.payload.get("execution_id") == execution_id
    ]
    assert len(completions) == 1
    assert not any(
        event.event_type in {"output_record_accepted", "file_state_accepted"}
        and event.payload.get("record_id") in staged_record_ids
        for event in events
    )
    assert not any(
        event.event_type in {"callback_accepted", "runner_execution_finalized"}
        and event.payload.get("execution_id") == execution_id
        for event in events
    )
    lease_revoked = next(
        event
        for event in events
        if event.event_type == "lease_revoked" and event.payload.get("execution_id") == execution_id
    )
    retry_scheduled = next(
        event
        for event in events
        if event.event_type == "runtime_retry_scheduled" and event.payload.get("node_id") == node_id
    )
    retry_ready = next(
        event
        for event in events
        if event.event_type == "node_state_changed"
        and event.payload.get("node_id") == node_id
        and event.payload.get("new_state") == "ready"
        and event.payload.get("trigger") == "runner_recovery_completed_retry_scheduled"
    )
    assert (
        completions[0].position
        < lease_revoked.position
        < retry_scheduled.position
        < retry_ready.position
    )
    assert (repo / "README.md").read_text() == "# tmp repo\n"
    assert (repo / "unrelated-dirt.txt").read_text() == "preserve me\n"
    projection_after_recovery = await controller.read_projection(run_id)
    assert not any(
        lease.execution_id == execution_id
        for lease in (
            lease
            for lease in leases_view(projection_after_recovery).values()
            if lease.state == "active"
        )
    )


@pytest.mark.asyncio
async def test_graph_runner_success_without_submit_requests_managed_recovery_before_retry(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-no-submit"
    _init_repo(repo)
    (repo / "unrelated-dirt.txt").write_text("preserve me\n")
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-no-submit"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": MutatingNoSubmitAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await executor.wait_for_all()

    events_before_recovery = await _read_events(session_factory, run_id)
    baselines = [
        event for event in events_before_recovery if event.event_type == "runner_baseline_recorded"
    ]
    assert len(baselines) == 1
    execution_id = str(baselines[0].payload["execution_id"])
    recovery_requests = [
        event
        for event in events_before_recovery
        if event.event_type == "runner_recovery_requested"
        and event.payload.get("execution_id") == execution_id
    ]
    assert len(recovery_requests) == 1
    recovery_request = recovery_requests[0]
    assert recovery_request.payload["reason"] == "runner_died"
    node_id = str(recovery_request.payload["node_id"])
    assert not any(
        event.payload.get("execution_id") == execution_id
        and event.event_type
        in {
            "runner_submission_staged",
            "runner_execution_finalized",
            "callback_accepted",
            "agent_died",
        }
        for event in events_before_recovery
    )
    projection_before_recovery = await controller.read_projection(run_id)
    assert (
        accepted_output_records_by_node_port_view(projection_before_recovery)
        .get(node_id, {})
        .get("candidate", [])
        == []
    )
    assert node_states_view(projection_before_recovery).get(node_id) != "ready"
    assert not any(
        event.event_type == "runtime_retry_scheduled" and event.payload.get("node_id") == node_id
        for event in events_before_recovery
    )
    assert (repo / "README.md").read_text() == "changed by managed runner\n"
    assert (repo / "unrelated-dirt.txt").read_text() == "preserve me\n"

    recovery_rows = [
        row
        for row in await _read_outbox_rows(session_factory)
        if row.kind == "runner_recovery" and row.payload["execution_id"] == execution_id
    ]
    assert len(recovery_rows) == 1
    assert recovery_rows[0].status == "pending"

    completed = await dispatcher.dispatch_pending(
        run_id=run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    assert [item.kind for item in completed] == ["runner_recovery"]

    events = await _read_events(session_factory, run_id)
    completions = [
        event
        for event in events
        if event.event_type == "runner_recovery_completed"
        and event.payload.get("execution_id") == execution_id
    ]
    assert len(completions) == 1
    assert not any(
        event.event_type == "output_record_accepted"
        and event.payload.get("producer_node_id") == node_id
        for event in events
    )
    assert (
        accepted_output_records_by_node_port_view(await controller.read_projection(run_id))
        .get(node_id, {})
        .get("candidate", [])
        == []
    )
    lease_revoked = next(
        event
        for event in events
        if event.event_type == "lease_revoked" and event.payload.get("execution_id") == execution_id
    )
    retry_scheduled = next(
        event
        for event in events
        if event.event_type == "runtime_retry_scheduled" and event.payload.get("node_id") == node_id
    )
    retry_ready = next(
        event
        for event in events
        if event.event_type == "node_state_changed"
        and event.payload.get("node_id") == node_id
        and event.payload.get("new_state") == "ready"
        and event.payload.get("trigger") == "runner_recovery_completed_retry_scheduled"
    )
    assert (
        completions[0].position
        < lease_revoked.position
        < retry_scheduled.position
        < retry_ready.position
    )
    assert (repo / "README.md").read_text() == "# tmp repo\n"
    assert (repo / "unrelated-dirt.txt").read_text() == "preserve me\n"
    projection_after_recovery = await controller.read_projection(run_id)
    assert not any(
        lease.execution_id == execution_id
        for lease in (
            lease
            for lease in leases_view(projection_after_recovery).values()
            if lease.state == "active"
        )
    )


@pytest.mark.asyncio
async def test_graph_runner_boundary_mismatch_recovers_without_publishing_staged_submission(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-boundary-mismatch"
    _init_repo(repo)
    (repo / "unrelated-dirt.txt").write_text("preserve me\n")
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-boundary-mismatch"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": SubmitThenMutateBoundaryAgent(), "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=artifact_store,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await executor.wait_for_all()

    events_before_recovery = await _read_events(session_factory, run_id)
    baseline = [
        event for event in events_before_recovery if event.event_type == "runner_baseline_recorded"
    ]
    assert len(baseline) == 1
    execution_id = str(baseline[0].payload["execution_id"])
    staged = [
        event
        for event in events_before_recovery
        if event.event_type == "runner_submission_staged"
        and event.payload.get("execution_id") == execution_id
    ]
    assert len(staged) == 1
    staged_records = await _read_staged_output_records(staged[0], artifact_store)
    assert {record["record_kind"] for record in staged_records} == {"output", "file_state"}
    staged_record_ids = {str(record["record_id"]) for record in staged_records}

    mismatch = next(
        event
        for event in events_before_recovery
        if event.event_type == "runner_boundary_mismatch"
        and event.payload.get("execution_id") == execution_id
    )
    recovery_request = next(
        event
        for event in events_before_recovery
        if event.event_type == "runner_recovery_requested"
        and event.payload.get("execution_id") == execution_id
    )
    assert mismatch.payload["reason"] == "boundary_mismatch"
    assert recovery_request.payload["reason"] == "boundary_mismatch"
    node_id = str(recovery_request.payload["node_id"])
    assert not any(
        event.event_type in {"runner_execution_finalized", "callback_accepted"}
        and event.payload.get("execution_id") == execution_id
        for event in events_before_recovery
    )
    assert not any(
        event.event_type in {"output_record_accepted", "file_state_accepted"}
        and event.payload.get("record_id") in staged_record_ids
        for event in events_before_recovery
    )
    assert not any(
        event.event_type == "runtime_retry_scheduled" and event.payload.get("node_id") == node_id
        for event in events_before_recovery
    )
    assert node_states_view(await controller.read_projection(run_id)).get(node_id) != "ready"
    recovery_rows = [
        row
        for row in await _read_outbox_rows(session_factory)
        if row.kind == "runner_recovery" and row.payload.get("execution_id") == execution_id
    ]
    assert len(recovery_rows) == 1
    assert recovery_rows[0].status == "pending"
    assert (repo / "README.md").read_text() == "changed after submission\n"

    completed = await dispatcher.dispatch_pending(
        run_id=run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    assert [item.kind for item in completed] == ["runner_recovery"]

    events = await _read_events(session_factory, run_id)
    recovery_completed = next(
        event
        for event in events
        if event.event_type == "runner_recovery_completed"
        and event.payload.get("execution_id") == execution_id
    )
    lease_revoked = next(
        event
        for event in events
        if event.event_type == "lease_revoked" and event.payload.get("execution_id") == execution_id
    )
    retry_scheduled = next(
        event
        for event in events
        if event.event_type == "runtime_retry_scheduled" and event.payload.get("node_id") == node_id
    )
    retry_ready = next(
        event
        for event in events
        if event.event_type == "node_state_changed"
        and event.payload.get("node_id") == node_id
        and event.payload.get("new_state") == "ready"
        and event.payload.get("trigger") == "runner_recovery_completed_retry_scheduled"
    )
    assert (
        recovery_completed.position
        < lease_revoked.position
        < retry_scheduled.position
        < retry_ready.position
    )
    assert recovery_request.payload["max_attempts"] == 3
    assert retry_ready.payload["attempt_number"] == 2
    assert (repo / "README.md").read_text() == "# tmp repo\n"
    assert (repo / "unrelated-dirt.txt").read_text() == "preserve me\n"
    projection = await controller.read_projection(run_id)
    assert (
        accepted_output_records_by_node_port_view(projection).get(node_id, {}).get("candidate", [])
        == []
    )
    assert not any(
        event.event_type in {"output_record_accepted", "file_state_accepted"}
        and event.payload.get("record_id") in staged_record_ids
        for event in events
    )
    assert not any(
        event.event_type == "callback_accepted"
        and event.payload.get("execution_id") == execution_id
        for event in events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_attempts", "expected_state", "expect_retry"),
    [(3, "ready", True), (1, "failed", False)],
)
async def test_restart_recovers_cache_root_whose_ignore_kind_changed(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
    max_attempts: int,
    expected_state: str,
    expect_retry: bool,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / f"repo-cache-transition-{max_attempts}"
    _init_repo(repo)
    (repo / ".gitignore").write_text("custom-cache/\n")
    subprocess.run(
        ["git", "add", ".gitignore"], cwd=repo, check=True, capture_output=True, text=True
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
            "ignore cache",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    cache_file = repo / "custom-cache" / "entry"
    cache_file.parent.mkdir()
    cache_file.write_text("ephemeral\n")

    clock = FixedClock()
    ids = SequentialIds()
    run_id = f"cache-kind-recovery-{max_attempts}"
    controller = await _seed_active_run(
        session_factory,
        run_id,
        clock,
        ids,
        routine=_cache_transition_routine(max_attempts),
    )
    agent = IgnoredToUntrackedStagedAgent()
    running: dict[str, asyncio.Task[None]] = {}
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
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
    await asyncio.wait_for(agent.staged.wait(), timeout=2)
    abandoned_tasks = list(running.values())
    running.clear()

    try:
        staged_events = await _read_events(session_factory, run_id)
        execution_id = str(
            next(
                event for event in staged_events if event.event_type == "runner_submission_staged"
            ).payload["execution_id"]
        )
        staged_projection = await controller.read_projection(run_id)
        staged_attempt = execution_attempts_view(staged_projection)[execution_id]
        assert [(root.path, root.kind) for root in staged_attempt.baseline_cache_roots] == [
            ("custom-cache", "ignored")
        ]
        assert [(root.path, root.kind) for root in staged_attempt.staged_cache_roots] == [
            ("custom-cache", "untracked")
        ]

        restarted_controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
        restarted_executor = GraphDispatchExecutor(
            session_factory,
            restarted_controller,
            AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
        restarted_dispatcher = OutboxDispatcher(session_factory, restarted_executor, clock)
        report = await recover(session_factory, restarted_dispatcher, run_id=run_id)
        await reconcile_runtime(
            restarted_controller, restarted_executor, report, restarted_dispatcher
        )

        events = await _read_events(session_factory, run_id)
        request = next(
            event
            for event in events
            if event.event_type == "runner_recovery_requested"
            and event.payload.get("execution_id") == execution_id
        )
        assert request.payload["recovery_scope"] == "selective"
        assert request.payload["observed_cache_roots"] == [
            {"path": "custom-cache", "kind": "untracked"}
        ]
        assert request.payload["authorized_cache_roots"] == [
            {"path": "custom-cache", "kind": "untracked"}
        ]
        assert request.payload["paths"] == [".gitignore", "custom-cache"]

        projection = await restarted_controller.read_projection(run_id)
        attempt = execution_attempts_view(projection)[execution_id]
        assert attempt.recovery_scope == "selective"
        assert attempt.recovery_paths == (".gitignore", "custom-cache")
        assert [(root.path, root.kind) for root in attempt.recovery_authorized_cache_roots] == [
            ("custom-cache", "untracked")
        ]
        assert projection_from_checkpoint(projection_to_checkpoint(projection)) == projection
        assert (repo / ".gitignore").read_text() == "custom-cache/\n"
        assert not cache_file.exists()

        completion = next(
            event
            for event in events
            if event.event_type == "runner_recovery_completed"
            and event.payload.get("execution_id") == execution_id
        )
        lease_revoked = next(
            event
            for event in events
            if event.event_type == "lease_revoked"
            and event.payload.get("execution_id") == execution_id
        )
        assert completion.position < lease_revoked.position
        retries = [
            event
            for event in events
            if event.event_type == "runtime_retry_scheduled"
            and event.payload.get("node_id") == attempt.node_id
        ]
        assert bool(retries) is expect_retry
        assert node_states_view(projection).get(attempt.node_id) == expected_state
    finally:
        agent.finish.set()
        for task in abandoned_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*abandoned_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_graph_runner_restart_recovers_orphaned_staged_submission_before_unobserved_failure(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-submit-failure"
    _init_repo(repo)
    (repo / "unrelated-dirt.txt").write_text("preserve me\n")
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-submit-failure"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    agent = StagedThenUnsuccessfulAgent()
    running: dict[str, asyncio.Task[None]] = {}
    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=artifact_store,
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
    await asyncio.wait_for(agent.staged.wait(), timeout=2)
    abandoned_tasks = list(running.values())
    running.clear()

    try:
        events_before_recovery = await _read_events(session_factory, run_id)
        baselines = [
            event
            for event in events_before_recovery
            if event.event_type == "runner_baseline_recorded"
        ]
        assert len(baselines) == 1
        execution_id = str(baselines[0].payload["execution_id"])
        staged = [
            event
            for event in events_before_recovery
            if event.event_type == "runner_submission_staged"
            and event.payload["execution_id"] == execution_id
        ]
        assert len(staged) == 1
        staged_records = await _read_staged_output_records(staged[0], artifact_store)
        assert staged_records
        assert {record["record_kind"] for record in staged_records} == {"output", "file_state"}
        staged_record_ids = {str(record["record_id"]) for record in staged_records}

        restarted_controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
        restarted_executor = GraphDispatchExecutor(
            session_factory,
            restarted_controller,
            AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
        restarted_dispatcher = OutboxDispatcher(session_factory, restarted_executor, clock)
        report = await recover(session_factory, restarted_dispatcher, run_id=run_id)
        await reconcile_runtime(
            restarted_controller, restarted_executor, report, restarted_dispatcher
        )

        events = await _read_events(session_factory, run_id)
        recovery_requests = [
            event
            for event in events
            if event.event_type == "runner_recovery_requested"
            and event.payload.get("execution_id") == execution_id
        ]
        assert len(recovery_requests) == 1
        node_id = str(recovery_requests[0].payload["node_id"])
        assert not any(
            event.event_type in {"callback_accepted", "runner_execution_finalized"}
            and event.payload.get("execution_id") == execution_id
            for event in events
        )
        assert not any(
            event.event_type == "output_record_accepted"
            and event.payload.get("record_id") in staged_record_ids
            for event in events
        )
        assert (
            accepted_output_records_by_node_port_view(
                await restarted_controller.read_projection(run_id)
            )
            .get(node_id, {})
            .get("candidate", [])
            == []
        )
        assert (repo / "README.md").read_text() == "# tmp repo\n"
        assert (repo / "unrelated-dirt.txt").read_text() == "preserve me\n"

        completions = [
            event
            for event in events
            if event.event_type == "runner_recovery_completed"
            and event.payload.get("execution_id") == execution_id
        ]
        assert len(completions) == 1
        lease_revoked = next(
            event
            for event in events
            if event.event_type == "lease_revoked"
            and event.payload.get("execution_id") == execution_id
        )
        retry_scheduled = next(
            event
            for event in events
            if event.event_type == "runtime_retry_scheduled"
            and event.payload.get("node_id") == node_id
        )
        assert completions[0].position < lease_revoked.position < retry_scheduled.position
        assert (
            node_states_view(await restarted_controller.read_projection(run_id)).get(node_id)
            == "ready"
        )

        await _schedule_dispatch_and_wait(
            restarted_controller, restarted_dispatcher, restarted_executor, run_id
        )
        await _schedule_dispatch_and_wait(
            restarted_controller, restarted_dispatcher, restarted_executor, run_id
        )
        assert project_task_states(await _read_events(session_factory, run_id)) == {
            "step-1/task-1": "accepted"
        }
    finally:
        agent.return_unsuccessfully.set()
        for task in abandoned_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*abandoned_tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("artifact_fault", ["missing", "corrupt"])
async def test_graph_runner_staged_callback_artifact_fault_requests_managed_recovery(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
    artifact_fault: Literal["missing", "corrupt"],
) -> None:
    _, session_factory = file_db
    repo = tmp_path / f"repo-staged-callback-{artifact_fault}"
    _init_repo(repo)
    (repo / "unrelated-dirt.txt").write_text("preserve me\n")
    clock = FixedClock()
    ids = SequentialIds()
    run_id = f"graph-runner-staged-callback-{artifact_fault}"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    agent = StagedThenSuccessfulAgent()
    artifact_root = tmp_path / "artifacts"
    artifact_store = FilesystemArtifactStore(artifact_root)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=artifact_store,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await asyncio.wait_for(agent.staged.wait(), timeout=2)

    staged_events = await _read_events(session_factory, run_id)
    staged = [event for event in staged_events if event.event_type == "runner_submission_staged"]
    assert len(staged) == 1
    assert "payload" not in staged[0].payload
    ref = StoredArtifactRef.model_validate(staged[0].payload["payload_ref"])
    execution_id = str(staged[0].payload["execution_id"])
    if artifact_fault == "missing":
        await artifact_store.delete(ref)
    else:
        digest = ref.content_hash.removeprefix("sha256:")
        blob_path = artifact_root / "sha256" / digest[:2] / digest[2:]
        blob_path.write_bytes(b"corrupt staged callback")

    agent.finish.set()
    await executor.wait_for_all()

    events_before_recovery = await _read_events(session_factory, run_id)
    recovery_requests = [
        event
        for event in events_before_recovery
        if event.event_type == "runner_recovery_requested"
        and event.payload.get("execution_id") == execution_id
    ]
    assert len(recovery_requests) == 1
    assert recovery_requests[0].payload["reason"] == "runner_died"
    assert not any(
        event.event_type in {"callback_accepted", "runner_execution_finalized"}
        and event.payload.get("execution_id") == execution_id
        for event in events_before_recovery
    )
    recovery_rows = [
        row
        for row in await _read_outbox_rows(session_factory)
        if row.kind == "runner_recovery" and row.payload.get("execution_id") == execution_id
    ]
    assert len(recovery_rows) == 1
    assert recovery_rows[0].status == "pending"
    assert (repo / "README.md").read_text() == "changed before submission\n"

    completed = await dispatcher.dispatch_pending(
        run_id=run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    assert [item.kind for item in completed] == ["runner_recovery"]

    events = await _read_events(session_factory, run_id)
    recovery_completions = [
        event
        for event in events
        if event.event_type == "runner_recovery_completed"
        and event.payload.get("execution_id") == execution_id
    ]
    assert len(recovery_completions) == 1
    assert (
        len(
            [
                event
                for event in events
                if event.event_type == "runner_recovery_requested"
                and event.payload.get("execution_id") == execution_id
            ]
        )
        == 1
    )
    assert not any(
        event.event_type in {"callback_accepted", "runner_execution_finalized"}
        and event.payload.get("execution_id") == execution_id
        for event in events
    )
    assert (repo / "README.md").read_text() == "# tmp repo\n"
    assert (repo / "unrelated-dirt.txt").read_text() == "preserve me\n"


@pytest.mark.asyncio
async def test_graph_runner_restart_orphaned_staged_submission_exhausts_original_retry_limit(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """Restart recovery retains the compiled retry limit, rather than defaulting unlimited."""
    _, session_factory = file_db
    repo = tmp_path / "repo-staged-exhausted"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "graph-runner-staged-exhausted"
    controller = await _seed_active_run(
        session_factory, run_id, clock, ids, routine=_routine(max_attempts=1)
    )
    agent = StagedThenUnsuccessfulAgent()
    running: dict[str, asyncio.Task[None]] = {}
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
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
    await asyncio.wait_for(agent.staged.wait(), timeout=2)
    abandoned_tasks = list(running.values())
    running.clear()

    try:
        restarted_controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
        restarted_executor = GraphDispatchExecutor(
            session_factory,
            restarted_controller,
            AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
        restarted_dispatcher = OutboxDispatcher(session_factory, restarted_executor, clock)
        report = await recover(session_factory, restarted_dispatcher, run_id=run_id)
        await reconcile_runtime(
            restarted_controller, restarted_executor, report, restarted_dispatcher
        )

        events = await _read_events(session_factory, run_id)
        execution_id = str(
            next(
                event for event in events if event.event_type == "runner_submission_staged"
            ).payload["execution_id"]
        )
        recovery_request = next(
            event
            for event in events
            if event.event_type == "runner_recovery_requested"
            and event.payload.get("execution_id") == execution_id
        )
        assert recovery_request.payload["max_attempts"] == 1
        recovery_completed = next(
            event
            for event in events
            if event.event_type == "runner_recovery_completed"
            and event.payload.get("execution_id") == execution_id
        )
        lease_revoked = next(
            event
            for event in events
            if event.event_type == "lease_revoked"
            and event.payload.get("execution_id") == execution_id
        )
        failed = next(
            event
            for event in events
            if event.event_type == "node_state_changed"
            and event.payload.get("new_state") == "failed"
            and event.payload.get("trigger") == "max_attempts_exhausted"
        )
        assert recovery_completed.position < lease_revoked.position < failed.position
        assert not any(event.event_type == "runtime_retry_scheduled" for event in events)
        assert (
            len([event for event in events if event.event_type == "agent_dispatch_requested"]) == 1
        )
        assert (repo / "README.md").read_text() == "# tmp repo\n"
    finally:
        agent.return_unsuccessfully.set()
        for task in abandoned_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*abandoned_tasks, return_exceptions=True)


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
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
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
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
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
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
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
    heartbeat_recorded = next(event for event in events if event.event_type == "heartbeat_recorded")
    assert heartbeat_recorded.payload["lease_id"] == dispatch_payload["lease_id"]
    assert heartbeat_recorded.payload["node_id"] == dispatch_payload["node_id"]
    assert heartbeat_recorded.payload["generation"] == dispatch_payload["generation"]
    assert heartbeat_recorded.payload["execution_id"] == dispatch_payload["execution_id"]
    lease_renewed = next(event for event in events if event.event_type == "lease_renewed")
    assert lease_renewed.payload["lease_id"] == dispatch_payload["lease_id"]
    assert any(event.event_type == "callback_accepted" for event in events)
    assert not any(event.event_type == "callback_rejected_stale" for event in events)
