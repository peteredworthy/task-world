"""Runtime graph-driver liveness reconciliation through the signal queue."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import AgentRunnerType, RoutineConfig, RunStatus
from orchestrator.db import (
    EventV2Model,
    GraphRuntimeSupervisionRepository,
    create_engine,
    create_session_factory,
    init_db,
    save_run,
)
from orchestrator.state.factory import create_run_from_routine
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    OutboxDispatcher,
    RunnerOwnedProcessRegistry,
)
from orchestrator.graph import execution_attempts_view, leases_view
from orchestrator.runners import (
    AgentMetadataCallback,
    AgentRunnerInfo,
    ChecklistUpdateCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    RunnerRuntimeObservationCapability,
    SubmitCallback,
)
from orchestrator.workflow import GraphRunDriver, SignalConsumer, WorkflowService
from tests.integration.test_graph_run_driver import (
    GradingAgent,
    SubmitAgent,
    _create_graph_run,
    _events,
    _init_repo,
    _routine as _graph_routine,
)
from tests.integration.test_graph_startup_recovery import (
    _build_driver,
    _seed_active_worker_lease,
)
from tests.integration.test_graph_runner_e2e import (
    AgentFactory as GraphAgentFactory,
    BlockingSubmitAgent,
    FixedClock,
    SequentialIds,
    StagedThenSuccessfulAgent,
    _seed_active_run,
)


class LostSubprocessAgent:
    """Real child disappears while its runner coroutine remains wedged."""

    def __init__(self) -> None:
        self.child_exited = asyncio.Event()

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
            name="lost-subprocess",
            runtime_observation=RunnerRuntimeObservationCapability(
                mode="host_process",
                reason="test runner reports its real host subprocess identity",
            ),
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
        del context, on_checklist_update, on_submit, on_output, on_grade, on_escalation
        process = await asyncio.create_subprocess_exec("/bin/sh", "-c", "sleep 0.05")
        assert on_agent_metadata is not None
        await on_agent_metadata({"pid": process.pid})
        try:
            await process.wait()
            self.child_exited.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
        finally:
            await process.wait()
            self.child_exited.set()

    async def cancel(self) -> None:
        return None


class BlockingObservedAgent:
    """Own a real child until the replacement driver cancels this exact runner."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.cancel_count = 0
        self.process: asyncio.subprocess.Process | None = None

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
            name="blocking-observed",
            runtime_observation=RunnerRuntimeObservationCapability(
                mode="host_process",
                reason="integration runner reports its owned host subprocess",
            ),
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
        del context, on_checklist_update, on_submit, on_output, on_grade, on_escalation
        self.process = await asyncio.create_subprocess_exec("/bin/sleep", "60")
        assert on_agent_metadata is not None
        await on_agent_metadata({"pid": self.process.pid})
        self.started.set()
        try:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
        finally:
            if self.process.returncode is None:
                self.process.terminate()
            await self.process.wait()

    async def cancel(self) -> None:
        self.cancel_count += 1
        process = self.process
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()
        self.cancelled.set()


class PausableObservedAgent(BlockingObservedAgent):
    """Real child held at either baseline-captured or submission-staged."""

    def __init__(self, *, stage_submission: bool) -> None:
        super().__init__()
        self.stage_submission = stage_submission
        self.reached = asyncio.Event()
        self.start_count = 0
        self.processes: list[asyncio.subprocess.Process] = []

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
        del on_checklist_update, on_output, on_grade, on_escalation
        self.start_count += 1
        self.process = await asyncio.create_subprocess_exec("/bin/sleep", "60")
        self.processes.append(self.process)
        assert on_agent_metadata is not None
        await on_agent_metadata({"pid": self.process.pid})
        self.started.set()
        if self.stage_submission:
            Path(context.working_dir, "README.md").write_text(
                "staged mutation awaiting manual pause\n"
            )
            await on_submit()
        self.reached.set()
        try:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
        finally:
            if self.process.returncode is None:
                self.process.terminate()
            await self.process.wait()


class CountingAgentFactory:
    """Real injected factory recorder for pre-spawn admission proofs."""

    def __init__(self, agent: PausableObservedAgent) -> None:
        self.agent = agent
        self.create_count = 0

    def create_runner(self, context: GraphDispatchContext) -> PausableObservedAgent:
        del context
        self.create_count += 1
        return self.agent


class RecordingProcessRegistry(RunnerOwnedProcessRegistry):
    """Production registry with an observable reservation count."""

    def __init__(self) -> None:
        super().__init__()
        self.reserve_count = 0

    def reserve(self, run_id: str, execution_id: str, cancellation: Any) -> None:
        self.reserve_count += 1
        super().reserve(run_id, execution_id, cancellation)


class RecordingGraphRunner:
    """Injected graph-driver callable that records actual admission."""

    def __init__(self) -> None:
        self.call_count = 0

    async def __call__(self, run_id: str) -> None:
        del run_id
        self.call_count += 1


class AdmissionSequence:
    """Return explicit admission decisions and record every durable recheck."""

    def __init__(self, decisions: tuple[bool, ...]) -> None:
        self.decisions = decisions
        self.calls: list[str] = []

    async def __call__(self, run_id: str) -> bool:
        self.calls.append(run_id)
        index = min(len(self.calls) - 1, len(self.decisions) - 1)
        return self.decisions[index]


class BrokenMetadataAgent:
    """A process-owning runner that violates one declared metadata invariant."""

    def __init__(self, behavior: str) -> None:
        self.behavior = behavior

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
            name=f"broken-metadata-{self.behavior}",
            runtime_observation=RunnerRuntimeObservationCapability(
                mode="host_process",
                reason="adversarial runner promises exact process metadata",
            ),
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
        del context, on_checklist_update, on_submit, on_output, on_grade, on_escalation
        assert on_agent_metadata is not None
        if self.behavior == "invalid_metadata":
            await on_agent_metadata({"pid": "not-a-pid"})
            await asyncio.Event().wait()
        if self.behavior == "unreported":
            await asyncio.Event().wait()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-liveness",
            "name": "Graph liveness",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [{"id": "task-1", "title": "Task 1"}],
                }
            ],
        }
    )


async def _save_active_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    *,
    execution_mode: str,
) -> None:
    run = create_run_from_routine(_routine(), repo_name="liveness-repo", source_branch="main")
    run.id = run_id
    run.status = RunStatus.ACTIVE
    run.execution_mode = execution_mode
    run.agent_runner_type = AgentRunnerType.CODEX_SERVER
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()


async def _wait_until_unowned(consumer: SignalConsumer, run_id: str) -> None:
    while consumer.graph_driver_ownership(run_id).owned:
        await asyncio.sleep(0)


async def _wait_for_owner_count(
    registry: RunnerOwnedProcessRegistry,
    run_id: str,
    expected: int,
) -> None:
    while registry.run_owner_count(run_id) != expected:
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_missing_graph_driver_rearms_then_pauses_through_signal_queue(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "graph-liveness.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = "active-orphaned-graph"
    invocations: list[str] = []

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def silent_graph_runner(received_run_id: str) -> None:
        invocations.append(received_run_id)

    try:
        await _save_active_run(session_factory, run_id, execution_mode="graph")
        for expected_attempt in range(1, 4):
            # Recreate the consumer every cycle: retry budget is durable and
            # cannot reset when the supervising process restarts.
            consumer = SignalConsumer(
                session_factory,
                create_service,
                graph_runner=silent_graph_runner,
                graph_reconcile_max_attempts=3,
            )
            result = await consumer.reconcile_graph_liveness_once()
            assert result.rearmed_run_ids == (run_id,)
            await _wait_until_unowned(consumer, run_id)
            async with session_factory() as session:
                durable = await GraphRuntimeSupervisionRepository(session).get(run_id)
            assert durable is not None
            assert durable.no_progress_attempts == expected_attempt
            assert durable.last_action == "missing_driver_rearmed"

        consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=silent_graph_runner,
            graph_reconcile_max_attempts=3,
        )
        exhausted = await consumer.reconcile_graph_liveness_once()
        assert exhausted.pause_enqueued_run_ids == (run_id,)
        assert invocations == [run_id, run_id, run_id]

        async with session_factory() as session:
            stopping = await WorkflowService(session).get_run(run_id)
            rows = await session.execute(
                select(EventV2Model.event_type, EventV2Model.payload)
                .where(EventV2Model.aggregate_id == run_id)
                .order_by(EventV2Model.position)
            )
            events = [(event_type, json.loads(payload)) for event_type, payload in rows]
        assert stopping.status == RunStatus.STOPPING
        assert any(
            event_type == "signal_enqueued"
            and payload["signal_type"] == "pause"
            and payload["payload"]["reason"] == "graph_driver_liveness_exhausted"
            for event_type, payload in events
        )

        await consumer._process_run(run_id)
        async with session_factory() as session:
            paused = await WorkflowService(session).get_run(run_id)
        assert paused.status == RunStatus.PAUSED
        assert paused.pause_reason == "graph_driver_liveness_exhausted"
        assert paused.last_error is not None
        assert "3 bounded reconciliation attempts" in paused.last_error
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owned_task_liveness_does_not_reset_durable_no_progress_budget(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "graph-liveness-owned-budget.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = "active-owned-without-progress"
    release = asyncio.Event()

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def silent_runner(_run_id: str) -> None:
        return

    async def held_runner(_run_id: str) -> None:
        await release.wait()

    try:
        await _save_active_run(session_factory, run_id, execution_mode="graph")
        first_consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=silent_runner,
        )
        first = await first_consumer.reconcile_graph_liveness_once()
        assert first.rearmed_run_ids == (run_id,)
        await _wait_until_unowned(first_consumer, run_id)

        restarted_consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=held_runner,
        )
        assert await restarted_consumer.arm_graph_run(run_id) is True
        await asyncio.sleep(0)
        owned = await restarted_consumer.reconcile_graph_liveness_once()

        assert owned.already_owned == 1
        assert owned.rearmed_run_ids == ()
        async with session_factory() as session:
            durable = await GraphRuntimeSupervisionRepository(session).get(run_id)
        assert durable is not None
        assert durable.no_progress_attempts == 1
        assert durable.last_action == "observed"
    finally:
        release.set()
        if "restarted_consumer" in locals():
            await restarted_consumer._quiesce_graph_run(run_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_owned_driver_with_expired_baseline_execution_is_quiesced_and_rearmed(
    tmp_path: Path,
) -> None:
    """An owned outer task cannot hide an expired baseline-captured runner."""
    engine = create_engine(tmp_path / "graph-liveness-owned-expired.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / "repo-owned-expired"
    _init_repo(repo)
    run_id = "owned-expired-baseline"
    graph_clock = FixedClock()
    ids = SequentialIds()
    agent = BlockingSubmitAgent()
    held_driver_release = asyncio.Event()
    driver_starts: list[str] = []

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def held_driver(received_run_id: str) -> None:
        driver_starts.append(received_run_id)
        await held_driver_release.wait()

    try:
        await _create_graph_run(session_factory, _graph_routine(), run_id=run_id, repo=repo)
        controller = await _seed_active_run(
            session_factory, run_id, graph_clock, ids, routine=_graph_routine()
        )
        async with session_factory() as session:
            await WorkflowService(session).apply_start_run(run_id)
        executor = GraphDispatchExecutor(
            session_factory,
            controller,
            GraphAgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts-owned-expired"),
        )
        dispatcher = OutboxDispatcher(session_factory, executor, graph_clock)
        await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 60, "max_grants": 1},
        )
        await dispatcher.dispatch_pending()
        await agent.started.wait()
        projection = await controller.read_projection(run_id)
        assert {attempt.state for attempt in execution_attempts_view(projection).values()} == {
            "baseline_captured"
        }

        graph_clock.advance(4_000)
        consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=held_driver,
            liveness_clock=graph_clock,
        )
        assert await consumer.arm_graph_run(run_id) is True
        await asyncio.sleep(0)

        reconciled = await consumer.reconcile_graph_liveness_once()

        assert reconciled.already_owned == 0
        assert reconciled.rearmed_run_ids == (run_id,)
        assert driver_starts == [run_id, run_id]
        async with session_factory() as session:
            durable = await GraphRuntimeSupervisionRepository(session).get(run_id)
        assert durable is not None
        assert durable.last_action == "expired_runtime_lease_rearmed"
        assert durable.no_progress_attempts == 1
        assert durable.active_lease_count == 1
        assert durable.expired_lease_count == 1
        assert durable.stalled_execution_id is not None
        assert durable.root_error is not None
        assert "executor heartbeat" in durable.root_error
    finally:
        held_driver_release.set()
        if "consumer" in locals():
            await consumer._quiesce_graph_run(run_id)
        agent.release.set()
        if "executor" in locals():
            await executor.wait_for_all()
        await engine.dispose()


@pytest.mark.asyncio
async def test_consumer_replaces_owned_driver_and_quiesces_exact_runner(
    tmp_path: Path,
) -> None:
    """Exercise the complete owner-to-replacement recovery chain with a real child."""
    engine = create_engine(tmp_path / "graph-liveness-combined-chain.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / "repo-combined-chain"
    _init_repo(repo)
    run_id = "owned-driver-expired-exact-runner"
    graph_clock = FixedClock()
    ids = SequentialIds()
    agent = BlockingObservedAgent()
    process_registry = RunnerOwnedProcessRegistry()
    executors: list[GraphDispatchExecutor] = []

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    def runtime_builder(
        sf: async_sessionmaker[AsyncSession],
        clock: FixedClock,
        id_gen: SequentialIds,
        *,
        worktree_path: Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, object] | None = None,
        artifact_store: FilesystemArtifactStore,
        process_registry: RunnerOwnedProcessRegistry,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        del worktree_path, runner_type, runner_config
        controller = GraphController(sf, clock, id_gen, auto_dispatch=False)
        executor = GraphDispatchExecutor(
            sf,
            controller,
            GraphAgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=artifact_store,
            process_registry=process_registry,
            runner_health_interval=0.01,
            runner_metadata_start_deadline=0.1,
        )
        executors.append(executor)
        return controller, executor

    try:
        routine_data = _graph_routine().model_dump(mode="json", by_alias=True)
        routine_data["steps"][0]["tasks"][0]["retry"] = {"max_attempts": 1}
        routine = RoutineConfig.model_validate(routine_data)
        await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)
        async with session_factory() as session:
            await WorkflowService(session).apply_start_run(run_id)
        driver = GraphRunDriver(
            session_factory,
            create_service,
            clock=graph_clock,
            id_gen=ids,
            runtime_builder=runtime_builder,
            process_registry=process_registry,
        )

        async def graph_runner(received_run_id: str) -> None:
            await driver.run(received_run_id)

        consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=graph_runner,
            graph_execution_quiescence_preparer=process_registry.prepare_run_quiescence,
            graph_execution_quiescer=process_registry.quiesce_run,
            graph_safe_effect_drainer=driver.quiesce_run,
            graph_owner_checker=process_registry.has_run_owners,
            liveness_clock=graph_clock,
        )
        assert await consumer.arm_graph_run(run_id) is True
        await agent.started.wait()
        projection = await GraphController(
            session_factory, graph_clock, ids, auto_dispatch=False
        ).read_projection(run_id)
        active_before = [
            lease for lease in leases_view(projection).values() if lease.state == "active"
        ]
        assert len(active_before) == 1
        execution_id = active_before[0].execution_id
        assert isinstance(execution_id, str)
        assert process_registry.is_running(execution_id) is True

        graph_clock.advance(4_000)
        result = await consumer.reconcile_graph_liveness_once()

        assert result.rearmed_run_ids == (run_id,)
        await agent.cancelled.wait()
        while consumer.graph_driver_ownership(run_id).owned:
            await asyncio.sleep(0.01)

        assert agent.cancel_count == 1
        assert agent.process is not None and agent.process.returncode is not None
        assert process_registry.is_running(execution_id) is False
        assert all(not executor.is_running(execution_id) for executor in executors)

        projection = await GraphController(
            session_factory, graph_clock, ids, auto_dispatch=False
        ).read_projection(run_id)
        assert all(lease.state != "active" for lease in leases_view(projection).values())
        attempt = execution_attempts_view(projection)[execution_id]
        assert attempt.state == "recovered"
        assert attempt.recovery_reason == "runner_died"

        async with session_factory() as session:
            run = await WorkflowService(session).get_run(run_id)
            durable = await GraphRuntimeSupervisionRepository(session).get(run_id)
        assert run.status == RunStatus.PAUSED
        assert run.pause_reason == "graph_blocked"
        assert durable is not None
        assert durable.no_progress_attempts == 1
        assert durable.last_action == "expired_runtime_lease_rearmed"
        assert durable.stalled_execution_id == execution_id
        assert durable.root_error is not None and "heartbeat" in durable.root_error
        assert (await _events(session_factory, run_id))[-1].event_type != "lease_renewed"
        assert (
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            == ""
        )
    finally:
        if "consumer" in locals():
            await consumer._quiesce_graph_run(run_id)
        for executor in executors:
            executor.cancel_all()
            await executor.wait_for_all()
        if agent.process is not None and agent.process.returncode is None:
            agent.process.kill()
            await agent.process.wait()
        await engine.dispose()


async def _exercise_manual_pause_recovery(tmp_path: Path, *, stage_submission: bool) -> None:
    """STOPPING remains visible until child, task, owner, and lease are gone."""
    suffix = "staged" if stage_submission else "baseline"
    engine = create_engine(tmp_path / f"graph-manual-pause-{suffix}.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / f"repo-manual-pause-{suffix}"
    _init_repo(repo)
    run_id = f"manual-pause-{suffix}"
    graph_clock = FixedClock()
    ids = SequentialIds()
    agent = PausableObservedAgent(stage_submission=stage_submission)
    process_registry = RunnerOwnedProcessRegistry()
    executors: list[GraphDispatchExecutor] = []

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def active_admission(received_run_id: str) -> bool:
        async with session_factory() as session:
            run = await WorkflowService(session).get_run(received_run_id)
        return run.status == RunStatus.ACTIVE

    def runtime_builder(
        sf: async_sessionmaker[AsyncSession],
        clock: FixedClock,
        id_gen: SequentialIds,
        *,
        worktree_path: Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, object] | None = None,
        artifact_store: FilesystemArtifactStore,
        process_registry: RunnerOwnedProcessRegistry,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        del worktree_path, runner_type, runner_config
        controller = GraphController(sf, clock, id_gen, auto_dispatch=False)
        executor = GraphDispatchExecutor(
            sf,
            controller,
            GraphAgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=artifact_store,
            process_registry=process_registry,
            agent_dispatch_admission=active_admission,
            runner_health_interval=30.0,
            runner_metadata_start_deadline=0.1,
        )
        executors.append(executor)
        return controller, executor

    try:
        await _create_graph_run(session_factory, _graph_routine(), run_id=run_id, repo=repo)
        async with session_factory() as session:
            await WorkflowService(session).apply_start_run(run_id)
        driver = GraphRunDriver(
            session_factory,
            create_service,
            clock=graph_clock,
            id_gen=ids,
            runtime_builder=runtime_builder,
            process_registry=process_registry,
        )
        consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=driver.run,
            graph_execution_quiescence_preparer=process_registry.prepare_run_quiescence,
            graph_execution_quiescer=process_registry.quiesce_run,
            graph_safe_effect_drainer=driver.quiesce_run,
            graph_owner_checker=process_registry.has_run_owners,
            liveness_clock=graph_clock,
        )
        assert await consumer.arm_graph_run(run_id) is True
        await agent.reached.wait()
        projection = await GraphController(
            session_factory, graph_clock, ids, auto_dispatch=False
        ).read_projection(run_id)
        execution_id, attempt = next(iter(execution_attempts_view(projection).items()))
        assert attempt.state == ("submission_staged" if stage_submission else "baseline_captured")
        assert process_registry.has_run_owners(run_id) is True
        assert agent.process is not None and agent.process.returncode is None

        async with session_factory() as session:
            stopping = await WorkflowService(session).pause_run(
                run_id,
                reason="manual_pause",
            )
        assert stopping.status == RunStatus.STOPPING
        assert stopping.pause_reason == "graph_pause_requested"
        assert process_registry.has_run_owners(run_id) is True

        await consumer._process_run(run_id)

        async with session_factory() as session:
            paused = await WorkflowService(session).get_run(run_id)
        assert paused.status == RunStatus.PAUSED
        assert paused.pause_reason == "manual_pause"
        assert consumer.graph_driver_ownership(run_id).owned is False
        assert process_registry.has_run_owners(run_id) is False
        assert agent.process.returncode is not None

        projection = await GraphController(
            session_factory, graph_clock, ids, auto_dispatch=False
        ).read_projection(run_id)
        recovery_request = next(
            event
            for event in await _events(session_factory, run_id)
            if event.event_type == "runner_recovery_requested"
        )
        assert recovery_request.payload["retry_after_recovery"] is True
        assert all(lease.state != "active" for lease in leases_view(projection).values())
        recovered = execution_attempts_view(projection)[execution_id]
        assert recovered.state == "recovered"
        assert recovered.recovery_reason == "cancelled"
        assert recovered.retry_after_recovery is True

        for executor in executors:
            await OutboxDispatcher(session_factory, executor, graph_clock).dispatch_pending(
                run_id=run_id
            )
        restarted = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=driver.run,
            graph_execution_quiescence_preparer=process_registry.prepare_run_quiescence,
            graph_execution_quiescer=process_registry.quiesce_run,
            graph_safe_effect_drainer=driver.quiesce_run,
            graph_owner_checker=process_registry.has_run_owners,
            liveness_clock=graph_clock,
        )
        assert (await restarted.reconcile_graph_liveness_once()).graph_runs == 0
        assert process_registry.has_run_owners(run_id) is False
        assert agent.cancel_count == 1

        async with session_factory() as session:
            resume_source = await WorkflowService(session).resume_run(run_id)
        assert resume_source.status == RunStatus.PAUSED
        await restarted._process_run(run_id)
        await _wait_for_owner_count(process_registry, run_id, 1)
        while agent.start_count != 2:
            await asyncio.sleep(0.01)
        assert agent.start_count == 2
        assert process_registry.run_owner_count(run_id) == 1
        resumed_projection = await GraphController(
            session_factory, graph_clock, ids, auto_dispatch=False
        ).read_projection(run_id)
        assert (
            sum(lease.state == "active" for lease in leases_view(resumed_projection).values()) == 1
        )

        async with session_factory() as session:
            await WorkflowService(session).pause_run(run_id, reason="resume_proof_complete")
        await restarted._process_run(run_id)
        await _wait_for_owner_count(process_registry, run_id, 0)
        async with session_factory() as session:
            repaused = await WorkflowService(session).get_run(run_id)
        assert repaused.status == RunStatus.PAUSED
        assert restarted.graph_driver_ownership(run_id).owned is False
        assert all(process.returncode is not None for process in agent.processes)
    finally:
        for executor in executors:
            executor.cancel_all()
            await executor.wait_for_all()
        if agent.process is not None and agent.process.returncode is None:
            agent.process.kill()
            await agent.process.wait()
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_pause_waits_for_exact_runner_recovery_before_paused(
    tmp_path: Path,
) -> None:
    await _exercise_manual_pause_recovery(tmp_path, stage_submission=False)


@pytest.mark.asyncio
async def test_manual_pause_waits_for_staged_runner_recovery_before_paused(
    tmp_path: Path,
) -> None:
    await _exercise_manual_pause_recovery(tmp_path, stage_submission=True)


async def _exercise_manual_cancel_recovery(tmp_path: Path, *, stage_submission: bool) -> None:
    """A public cancel cannot become terminal while a real runner still owns work."""
    suffix = "staged" if stage_submission else "baseline"
    engine = create_engine(tmp_path / f"graph-manual-cancel-{suffix}.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / f"repo-manual-cancel-{suffix}"
    _init_repo(repo)
    run_id = f"manual-cancel-{suffix}"
    graph_clock = FixedClock()
    ids = SequentialIds()
    agent = PausableObservedAgent(stage_submission=stage_submission)
    process_registry = RunnerOwnedProcessRegistry()
    executors: list[GraphDispatchExecutor] = []

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def active_admission(received_run_id: str) -> bool:
        async with session_factory() as session:
            run = await WorkflowService(session).get_run(received_run_id)
        return run.status == RunStatus.ACTIVE

    def runtime_builder(
        sf: async_sessionmaker[AsyncSession],
        clock: FixedClock,
        id_gen: SequentialIds,
        *,
        worktree_path: Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, object] | None = None,
        artifact_store: FilesystemArtifactStore,
        process_registry: RunnerOwnedProcessRegistry,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        del worktree_path, runner_type, runner_config
        controller = GraphController(sf, clock, id_gen, auto_dispatch=False)
        executor = GraphDispatchExecutor(
            sf,
            controller,
            GraphAgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=artifact_store,
            process_registry=process_registry,
            agent_dispatch_admission=active_admission,
            runner_health_interval=30.0,
            runner_metadata_start_deadline=0.1,
        )
        executors.append(executor)
        return controller, executor

    try:
        await _create_graph_run(session_factory, _graph_routine(), run_id=run_id, repo=repo)
        async with session_factory() as session:
            await WorkflowService(session).apply_start_run(run_id)
        driver = GraphRunDriver(
            session_factory,
            create_service,
            clock=graph_clock,
            id_gen=ids,
            runtime_builder=runtime_builder,
            process_registry=process_registry,
        )
        consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=driver.run,
            graph_execution_quiescence_preparer=process_registry.prepare_run_quiescence,
            graph_execution_quiescer=process_registry.quiesce_run,
            graph_safe_effect_drainer=driver.quiesce_run,
            graph_owner_checker=process_registry.has_run_owners,
            liveness_clock=graph_clock,
        )
        assert await consumer.arm_graph_run(run_id) is True
        await agent.reached.wait()
        projection = await GraphController(
            session_factory, graph_clock, ids, auto_dispatch=False
        ).read_projection(run_id)
        execution_id, attempt = next(iter(execution_attempts_view(projection).items()))
        assert attempt.state == ("submission_staged" if stage_submission else "baseline_captured")
        assert process_registry.run_owner_count(run_id) == 1
        assert agent.process is not None and agent.process.returncode is None

        async with session_factory() as session:
            stopping = await WorkflowService(session).cancel_run(
                run_id,
                reason="manual_cancel",
            )
        assert stopping.status == RunStatus.STOPPING
        assert process_registry.run_owner_count(run_id) == 1

        await consumer._process_run(run_id)

        async with session_factory() as session:
            cancelled = await WorkflowService(session).get_run(run_id)
            rows = list(
                await session.scalars(
                    select(EventV2Model)
                    .where(EventV2Model.aggregate_id == run_id)
                    .order_by(EventV2Model.position)
                )
            )
        graph_events = await _events(session_factory, run_id)
        assert cancelled.status == RunStatus.CANCELLED
        assert consumer.graph_driver_ownership(run_id).owned is False
        assert process_registry.run_owner_count(run_id) == 0
        assert agent.process.returncode is not None

        projection = await GraphController(
            session_factory, graph_clock, ids, auto_dispatch=False
        ).read_projection(run_id)
        assert all(lease.state != "active" for lease in leases_view(projection).values())
        recovered = execution_attempts_view(projection)[execution_id]
        assert recovered.state == "recovered"
        assert recovered.recovery_reason == "cancelled"

        recovery_requested = next(
            event.position
            for event in graph_events
            if event.event_type == "runner_recovery_requested"
        )
        recovery_completed = next(
            event.position
            for event in graph_events
            if event.event_type == "runner_recovery_completed"
        )
        graph_cancelled = next(
            event.position
            for event in graph_events
            if event.event_type == "run_lifecycle_changed"
            and event.payload.get("to_state") == "cancelled"
        )
        workflow_cancelled = next(
            row.position
            for row in rows
            if row.event_type == "run_status_changed"
            and json.loads(row.payload).get("new_status") == "cancelled"
        )
        assert recovery_requested < recovery_completed < graph_cancelled < workflow_cancelled
        forbidden_between_recovery_and_cancel = [
            event
            for event in graph_events
            if recovery_completed < event.position < graph_cancelled
            and (
                event.event_type in {"runtime_retry_scheduled", "lease_granted"}
                or (
                    event.event_type == "node_state_changed"
                    and event.payload.get("new_state") == "ready"
                )
            )
        ]
        assert forbidden_between_recovery_and_cancel == []
        assert agent.cancel_count == 1
    finally:
        for executor in executors:
            executor.cancel_all()
            await executor.wait_for_all()
        for process in agent.processes:
            if process.returncode is None:
                process.kill()
                await process.wait()
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_cancel_orders_recovery_before_graph_and_workflow_terminal(
    tmp_path: Path,
) -> None:
    await _exercise_manual_cancel_recovery(tmp_path, stage_submission=False)


@pytest.mark.asyncio
async def test_manual_cancel_orders_staged_recovery_before_graph_and_workflow_terminal(
    tmp_path: Path,
) -> None:
    await _exercise_manual_cancel_recovery(tmp_path, stage_submission=True)


async def test_manual_pause_isolated_to_exact_run_owner_and_lease(tmp_path: Path) -> None:
    """Pausing one run cannot cancel or recover another run's real child."""
    engine = create_engine(tmp_path / "graph-pause-cross-run.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    graph_clock = FixedClock()
    ids = SequentialIds()
    process_registry = RunnerOwnedProcessRegistry()
    run_ids = ("pause-isolation-a", "pause-isolation-b")
    repos = {run_id: tmp_path / f"repo-{run_id}" for run_id in run_ids}
    agents = {run_id: PausableObservedAgent(stage_submission=False) for run_id in run_ids}
    executors: list[GraphDispatchExecutor] = []

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def active_admission(received_run_id: str) -> bool:
        async with session_factory() as session:
            run = await WorkflowService(session).get_run(received_run_id)
        return run.status == RunStatus.ACTIVE

    def runtime_builder(
        sf: async_sessionmaker[AsyncSession],
        clock: FixedClock,
        id_gen: SequentialIds,
        *,
        worktree_path: Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, object] | None = None,
        artifact_store: FilesystemArtifactStore,
        process_registry: RunnerOwnedProcessRegistry,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        del runner_type, runner_config
        run_id = next(candidate for candidate, repo in repos.items() if repo == worktree_path)
        controller = GraphController(sf, clock, id_gen, auto_dispatch=False)
        executor = GraphDispatchExecutor(
            sf,
            controller,
            GraphAgentFactory({"worker": agents[run_id], "verifier": GradingAgent("A")}),
            worktree_path=worktree_path,
            artifact_store=artifact_store,
            process_registry=process_registry,
            agent_dispatch_admission=active_admission,
            runner_health_interval=30.0,
            runner_metadata_start_deadline=0.1,
        )
        executors.append(executor)
        return controller, executor

    try:
        for run_id in run_ids:
            _init_repo(repos[run_id])
            await _create_graph_run(
                session_factory,
                _graph_routine(),
                run_id=run_id,
                repo=repos[run_id],
            )
            async with session_factory() as session:
                await WorkflowService(session).apply_start_run(run_id)
        driver = GraphRunDriver(
            session_factory,
            create_service,
            clock=graph_clock,
            id_gen=ids,
            runtime_builder=runtime_builder,
            process_registry=process_registry,
        )
        consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=driver.run,
            graph_execution_quiescence_preparer=process_registry.prepare_run_quiescence,
            graph_execution_quiescer=process_registry.quiesce_run,
            graph_safe_effect_drainer=driver.quiesce_run,
            graph_owner_checker=process_registry.has_run_owners,
            liveness_clock=graph_clock,
        )
        for run_id in run_ids:
            assert await consumer.arm_graph_run(run_id) is True
            await agents[run_id].reached.wait()
        assert all(process_registry.run_owner_count(run_id) == 1 for run_id in run_ids)

        paused_run, unaffected_run = run_ids
        unaffected_agent = agents[unaffected_run]
        async with session_factory() as session:
            await WorkflowService(session).pause_run(paused_run, reason="manual_pause")
        await consumer._process_run(paused_run)

        async with session_factory() as session:
            paused = await WorkflowService(session).get_run(paused_run)
            unaffected = await WorkflowService(session).get_run(unaffected_run)
        assert paused.status == RunStatus.PAUSED
        assert unaffected.status == RunStatus.ACTIVE
        assert process_registry.run_owner_count(paused_run) == 0
        assert process_registry.run_owner_count(unaffected_run) == 1
        assert consumer.graph_driver_ownership(paused_run).owned is False
        assert consumer.graph_driver_ownership(unaffected_run).owned is True
        assert unaffected_agent.cancel_count == 0
        assert unaffected_agent.process is not None
        assert unaffected_agent.process.returncode is None
        unaffected_projection = await GraphController(
            session_factory, graph_clock, ids, auto_dispatch=False
        ).read_projection(unaffected_run)
        assert (
            sum(lease.state == "active" for lease in leases_view(unaffected_projection).values())
            == 1
        )
        assert all(
            attempt.state == "baseline_captured"
            for attempt in execution_attempts_view(unaffected_projection).values()
        )

        async with session_factory() as session:
            await WorkflowService(session).pause_run(
                unaffected_run,
                reason="isolation_proof_complete",
            )
        await consumer._process_run(unaffected_run)
        assert process_registry.run_owner_count(unaffected_run) == 0
    finally:
        for executor in executors:
            executor.cancel_all()
            await executor.wait_for_all()
        for agent in agents.values():
            for process in agent.processes:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        await engine.dispose()


async def test_inactive_graph_run_is_rejected_before_consumer_arm(tmp_path: Path) -> None:
    """The consumer never creates a driver task for a durable inactive row."""
    engine = create_engine(tmp_path / "graph-inactive-arm.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = "inactive-before-arm"
    run = create_run_from_routine(
        _routine(),
        repo_name="inactive-arm-repo",
        source_branch="main",
    )
    run.id = run_id
    run.status = RunStatus.PAUSED
    run.execution_mode = "graph"
    runner = RecordingGraphRunner()

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    try:
        async with session_factory() as session:
            await save_run(session, run)
            await session.commit()
        consumer = SignalConsumer(session_factory, create_service, graph_runner=runner)
        assert await consumer.arm_graph_run(run_id) is False
        await asyncio.sleep(0)
        assert runner.call_count == 0
        assert consumer.graph_driver_ownership(run_id).owned is False
    finally:
        await engine.dispose()


async def _exercise_inactive_dispatch_rejection(
    tmp_path: Path,
    *,
    decisions: tuple[bool, ...],
    expected_reservations: int,
    expected_checks: int,
) -> None:
    """Admission is rechecked before reserve and after reserve, before spawn."""
    suffix = "before-reserve" if not decisions[0] else "after-reserve"
    engine = create_engine(tmp_path / f"graph-inactive-dispatch-{suffix}.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / f"repo-inactive-dispatch-{suffix}"
    _init_repo(repo)
    graph_clock = FixedClock()
    ids = SequentialIds()
    run_id = f"inactive-dispatch-{suffix}"
    agent = PausableObservedAgent(stage_submission=False)
    factory = CountingAgentFactory(agent)
    registry = RecordingProcessRegistry()
    admission = AdmissionSequence(decisions)

    try:
        controller = await _seed_active_run(session_factory, run_id, graph_clock, ids)
        await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 60, "max_grants": 1},
        )
        executor = GraphDispatchExecutor(
            session_factory,
            controller,
            factory,
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / f"artifacts-{suffix}"),
            process_registry=registry,
            agent_dispatch_admission=admission,
        )
        dispatcher = OutboxDispatcher(session_factory, executor, graph_clock)
        completed = await dispatcher.dispatch_pending(run_id=run_id)
        await executor.wait_for_all()

        assert [item.kind for item in completed] == ["agent_dispatch"]
        assert len(admission.calls) == expected_checks
        assert admission.calls == [run_id] * expected_checks
        assert registry.reserve_count == expected_reservations
        assert registry.run_owner_count(run_id) == 0
        assert factory.create_count == 0
        assert agent.start_count == 0
        assert agent.process is None
        graph_events = await _events(session_factory, run_id)
        assert not any(
            event.event_type
            in {
                "runner_baseline_captured",
                "runner_recovery_requested",
                "runtime_retry_scheduled",
            }
            for event in graph_events
        )
    finally:
        if agent.process is not None and agent.process.returncode is None:
            agent.process.kill()
            await agent.process.wait()
        await engine.dispose()


@pytest.mark.asyncio
async def test_inactive_dispatch_is_rejected_before_runner_spawn(tmp_path: Path) -> None:
    await _exercise_inactive_dispatch_rejection(
        tmp_path, decisions=(False,), expected_reservations=0, expected_checks=1
    )


@pytest.mark.asyncio
async def test_inactive_dispatch_is_rejected_after_reserve_before_runner_spawn(
    tmp_path: Path,
) -> None:
    await _exercise_inactive_dispatch_rejection(
        tmp_path, decisions=(True, True, False), expected_reservations=1, expected_checks=3
    )


async def test_quiescence_failure_keeps_stop_visible_and_signal_retryable(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "graph-quiescence-retry.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = "graph-quiescence-retry"
    driver_started = asyncio.Event()

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def graph_runner(_run_id: str) -> None:
        driver_started.set()
        await asyncio.Event().wait()

    async def exact_owner_quiescer(
        _run_id: str,
        _runner_loss: bool,
        _retry_after_recovery: bool,
    ) -> None:
        return None

    drain_attempts = 0

    async def fail_once_drainer(
        _run_id: str,
        _reason: str,
        _retry_after_recovery: bool,
    ) -> None:
        nonlocal drain_attempts
        drain_attempts += 1
        if drain_attempts == 1:
            raise RuntimeError("injected durable recovery drain failure")

    try:
        await _save_active_run(session_factory, run_id, execution_mode="graph")
        consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=graph_runner,
            graph_execution_quiescer=exact_owner_quiescer,
            graph_safe_effect_drainer=fail_once_drainer,
            graph_owner_checker=lambda _run_id: False,
        )
        assert await consumer.arm_graph_run(run_id) is True
        await driver_started.wait()
        async with session_factory() as session:
            stopping = await WorkflowService(session).pause_run(run_id, reason="manual_pause")
        assert stopping.status == RunStatus.STOPPING

        await consumer._process_run(run_id)
        async with session_factory() as session:
            failed_stop = await WorkflowService(session).get_run(run_id)
            processed_before_retry = list(
                await session.scalars(
                    select(EventV2Model).where(
                        EventV2Model.aggregate_id == run_id,
                        EventV2Model.event_type == "signal_processed",
                    )
                )
            )
        assert failed_stop.status == RunStatus.STOPPING
        assert failed_stop.pause_reason == "graph_quiescence_failed"
        assert "durable recovery drain failure" in (failed_stop.last_error or "")
        assert processed_before_retry == []

        await consumer._process_run(run_id)
        async with session_factory() as session:
            paused = await WorkflowService(session).get_run(run_id)
            processed_after_retry = list(
                await session.scalars(
                    select(EventV2Model).where(
                        EventV2Model.aggregate_id == run_id,
                        EventV2Model.event_type == "signal_processed",
                    )
                )
            )
        assert paused.status == RunStatus.PAUSED
        assert paused.pause_reason == "manual_pause"
        assert drain_attempts == 2
        assert len(processed_after_retry) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_runner_child_loss_is_durable_and_converges_through_recovery(
    tmp_path: Path,
) -> None:
    """A real reported child PID is supervised independently of the driver task."""
    engine = create_engine(tmp_path / "graph-runner-child-loss.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / "repo-runner-child-loss"
    _init_repo(repo)
    run_id = "runner-child-loss"
    graph_clock = FixedClock()
    ids = SequentialIds()
    agent = LostSubprocessAgent()

    try:
        await _create_graph_run(session_factory, _graph_routine(), run_id=run_id, repo=repo)
        controller = await _seed_active_run(
            session_factory, run_id, graph_clock, ids, routine=_graph_routine()
        )
        executor = GraphDispatchExecutor(
            session_factory,
            controller,
            GraphAgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts-child-loss"),
            runner_health_interval=0.01,
        )
        dispatcher = OutboxDispatcher(session_factory, executor, graph_clock)
        await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 60, "max_grants": 1},
        )
        await dispatcher.dispatch_pending()
        await agent.child_exited.wait()
        await executor.wait_for_all()
        await dispatcher.dispatch_pending(run_id=run_id)

        async with session_factory() as session:
            runtime_events = list(
                await session.scalars(
                    select(EventV2Model)
                    .where(
                        EventV2Model.aggregate_id == run_id,
                        EventV2Model.event_type == "graph_runner_runtime_observed",
                    )
                    .order_by(EventV2Model.position)
                )
            )
        runtime_states = [json.loads(event.payload)["state"] for event in runtime_events]
        assert runtime_states[:2] == ["not_yet_reported", "exact_identity_available"]
        assert runtime_states[-1] == "missing"
        missing_payload = json.loads(runtime_events[-1].payload)
        assert missing_payload["runner_type"] == "cli_subprocess"
        assert missing_payload["pid"] > 0
        assert len(missing_payload["command_sha256"]) == 64
        assert "disappeared or changed" in missing_payload["root_error"]
        projection = await controller.read_projection(run_id)
        attempts = execution_attempts_view(projection)
        assert {attempt.state for attempt in attempts.values()} == {"recovered"}
        assert {attempt.recovery_reason for attempt in attempts.values()} == {"runner_died"}
        assert all(lease.state != "active" for lease in leases_view(projection).values())
    finally:
        if "executor" in locals():
            executor.cancel_all()
            await executor.wait_for_all()
        await engine.dispose()


async def _exercise_process_runner_metadata_failure(
    tmp_path: Path,
    *,
    behavior: str,
    expected_state: str,
    reason_fragment: str,
) -> None:
    engine = create_engine(tmp_path / f"graph-runner-{behavior}.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / f"repo-{behavior}"
    _init_repo(repo)
    run_id = f"runner-{behavior}"
    graph_clock = FixedClock()
    ids = SequentialIds()
    agent = BrokenMetadataAgent(behavior)

    try:
        routine_data = _graph_routine().model_dump(mode="json", by_alias=True)
        routine_data["steps"][0]["tasks"][0]["retry"] = {"max_attempts": 1}
        routine = RoutineConfig.model_validate(routine_data)
        await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)
        controller = await _seed_active_run(
            session_factory, run_id, graph_clock, ids, routine=routine
        )
        executor = GraphDispatchExecutor(
            session_factory,
            controller,
            GraphAgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / f"artifacts-{behavior}"),
            runner_health_interval=0.01,
            runner_metadata_start_deadline=0.01,
        )
        dispatcher = OutboxDispatcher(session_factory, executor, graph_clock)
        await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 60, "max_grants": 1},
        )
        await dispatcher.dispatch_pending()
        await executor.wait_for_all()
        await dispatcher.dispatch_pending(run_id=run_id)

        async with session_factory() as session:
            runtime_events = list(
                await session.scalars(
                    select(EventV2Model)
                    .where(
                        EventV2Model.aggregate_id == run_id,
                        EventV2Model.event_type == "graph_runner_runtime_observed",
                    )
                    .order_by(EventV2Model.position)
                )
            )
        payloads = [json.loads(event.payload) for event in runtime_events]
        assert payloads[0]["state"] == "not_yet_reported"
        failed = next(payload for payload in payloads if payload["state"] == expected_state)
        assert failed["runner_type"] == "codex_server"
        assert reason_fragment in failed["reason"]
        assert failed["root_error"] == failed["reason"]
        projection = await controller.read_projection(run_id)
        assert {attempt.state for attempt in execution_attempts_view(projection).values()} == {
            "recovered"
        }
        assert all(lease.state != "active" for lease in leases_view(projection).values())
    finally:
        if "executor" in locals():
            executor.cancel_all()
            await executor.wait_for_all()
        await engine.dispose()


@pytest.mark.asyncio
async def test_process_runner_unreported_metadata_is_durable_and_fail_closed(tmp_path: Path) -> None:
    await _exercise_process_runner_metadata_failure(
        tmp_path,
        behavior="unreported",
        expected_state="unreported",
        reason_fragment="within 0.01 seconds",
    )


@pytest.mark.asyncio
async def test_liveness_reconciliation_is_bounded_keyset_and_ignores_legacy_runs(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "graph-liveness-bounded.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    invoked: list[str] = []
    release = asyncio.Event()

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def held_graph_runner(run_id: str) -> None:
        invoked.append(run_id)
        await release.wait()

    try:
        await _save_active_run(session_factory, "a-graph", execution_mode="graph")
        await _save_active_run(session_factory, "b-legacy", execution_mode="legacy")
        await _save_active_run(session_factory, "c-graph", execution_mode="graph")
        consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=held_graph_runner,
            graph_reconcile_batch_size=1,
        )

        first = await consumer.reconcile_graph_liveness_once()
        second = await consumer.reconcile_graph_liveness_once()
        third = await consumer.reconcile_graph_liveness_once()
        await asyncio.sleep(0)

        assert first.scanned == second.scanned == third.scanned == 1
        assert first.rearmed_run_ids == ("a-graph",)
        assert second.graph_runs == 0
        assert third.rearmed_run_ids == ("c-graph",)
        assert invoked == ["a-graph", "c-graph"]
        assert consumer.graph_driver_ownership("a-graph").owned is True
        assert consumer.graph_driver_ownership("b-legacy").task_state == "absent"
        assert consumer.graph_driver_ownership("c-graph").owned is True
    finally:
        release.set()
        await asyncio.sleep(0)
        await engine.dispose()


@pytest.mark.asyncio
async def test_started_consumer_periodically_converges_orphan_to_observable_pause(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "graph-liveness-periodic.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = "periodic-orphaned-graph"

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def silent_graph_runner(_run_id: str) -> None:
        return

    consumer = SignalConsumer(
        session_factory,
        create_service,
        poll_interval=0.001,
        graph_runner=silent_graph_runner,
        graph_reconcile_interval=0.001,
        graph_reconcile_max_attempts=2,
    )
    try:
        await _save_active_run(session_factory, run_id, execution_mode="graph")
        await consumer.start()
        while True:
            async with session_factory() as session:
                run = await WorkflowService(session).get_run(run_id)
            if run.status == RunStatus.PAUSED:
                break
            await asyncio.sleep(0.005)

        assert run.pause_reason == "graph_driver_liveness_exhausted"
        assert run.last_error is not None
        assert "2 bounded reconciliation attempts" in run.last_error
        assert consumer.graph_driver_ownership(run_id).owned is False
    finally:
        await consumer.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_rearms_real_driver_and_revokes_missing_execution_lease(
    tmp_path: Path,
) -> None:
    """The periodic primitive reaches the real driver recovery path, not a proxy."""
    engine = create_engine(tmp_path / "graph-liveness-real-driver.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / "repo-real-driver"
    _init_repo(repo)
    run_id = "runtime-orphaned-lease"
    dispatch_order: list[str] = []

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    try:
        await _create_graph_run(
            session_factory,
            _graph_routine(),
            run_id=run_id,
            repo=repo,
        )
        await _seed_active_worker_lease(session_factory, run_id=run_id)
        async with session_factory() as session:
            await WorkflowService(session).apply_start_run(run_id)
        driver = _build_driver(
            session_factory,
            repo=repo,
            agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
            dispatch_order=dispatch_order,
        )

        async def graph_runner(received_run_id: str) -> None:
            await driver.run(received_run_id)

        consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=graph_runner,
        )
        result = await consumer.reconcile_graph_liveness_once()
        assert result.rearmed_run_ids == (run_id,)
        await _wait_until_unowned(consumer, run_id)

        events = await _events(session_factory, run_id)
        async with session_factory() as session:
            run = await WorkflowService(session).get_run(run_id)
        assert run.status == RunStatus.PAUSED
        assert run.pause_reason == "graph_blocked"
        assert any(
            event.event_type == "lease_revoked"
            and event.payload.get("reason") == "runtime_process_missing_after_restart"
            for event in events
        )
        assert any(event.event_type == "agent_died" for event in events)
        assert dispatch_order == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owned_but_stalled_staged_submission_is_quiesced_and_rearmed(
    tmp_path: Path,
) -> None:
    """A task object cannot hide durable staged-without-witness stagnation."""
    engine = create_engine(tmp_path / "graph-liveness-staged.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / "repo-staged"
    _init_repo(repo)
    run_id = "owned-stalled-stage"
    graph_clock = FixedClock()
    ids = SequentialIds()
    stalled_agent = StagedThenSuccessfulAgent()
    held_driver_release = asyncio.Event()
    driver_starts: list[str] = []

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def held_driver(received_run_id: str) -> None:
        driver_starts.append(received_run_id)
        await held_driver_release.wait()

    try:
        await _create_graph_run(
            session_factory,
            _graph_routine(),
            run_id=run_id,
            repo=repo,
        )
        controller = await _seed_active_run(
            session_factory, run_id, graph_clock, ids, routine=_graph_routine()
        )
        async with session_factory() as session:
            await WorkflowService(session).apply_start_run(run_id)
        executor = GraphDispatchExecutor(
            session_factory,
            controller,
            GraphAgentFactory({"worker": stalled_agent, "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts-staged"),
        )
        dispatcher = OutboxDispatcher(session_factory, executor, graph_clock)
        await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 60, "max_grants": 1},
        )
        await dispatcher.dispatch_pending()
        await stalled_agent.staged.wait()

        graph_clock.advance(600)
        consumer = SignalConsumer(
            session_factory,
            create_service,
            graph_runner=held_driver,
            graph_staged_submission_deadline=30,
            liveness_clock=graph_clock,
        )
        assert await consumer.arm_graph_run(run_id) is True
        await asyncio.sleep(0)
        assert consumer.graph_driver_ownership(run_id).owned is True

        reconciled = await consumer.reconcile_graph_liveness_once()

        assert reconciled.already_owned == 0
        assert reconciled.rearmed_run_ids == (run_id,)
        assert driver_starts == [run_id, run_id]
        assert consumer.graph_driver_ownership(run_id).generation == 2
        async with session_factory() as session:
            durable = await GraphRuntimeSupervisionRepository(session).get(run_id)
            canonical_actions = list(
                await session.scalars(
                    select(EventV2Model).where(
                        EventV2Model.aggregate_id == run_id,
                        EventV2Model.event_type == "graph_runtime_reconciled",
                    )
                )
            )
        assert durable is not None
        assert durable.last_action == "stalled_submission_rearmed"
        assert durable.staged_count == 1
        assert durable.witnessed_count == 0
        assert durable.stalled_execution_id is not None
        assert durable.no_progress_attempts == 1
        assert len(canonical_actions) == 1
    finally:
        held_driver_release.set()
        if "consumer" in locals():
            await consumer._quiesce_graph_run(run_id)
        stalled_agent.finish.set()
        if "executor" in locals():
            await executor.wait_for_all()
        await engine.dispose()
