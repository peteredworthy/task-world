"""Real graph dispatch proof for operator-authorized crash barriers."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph_runtime import (
    CRASH_BARRIER_AUTHORIZATION,
    CrashBarrierConfig,
    CrashBarrierPlanConfig,
    CrashBarrierPlanState,
    CrashBarrierPoint,
    CrashBarrierTarget,
    FileCrashBarrier,
    GraphController,
    GraphDispatchExecutor,
    OutboxDispatcher,
    recover,
    reconcile_runtime,
)
from orchestrator.graph import compile_routine, execution_attempts_view, leases_view
from tests.integration.test_graph_runner_e2e import (
    AgentFactory,
    FixedClock,
    GradingAgent,
    SequentialIds,
    SubmitAgent,
    _init_repo,
    _read_events,
    _seed_active_run,
    _routine,
)


@pytest.mark.parametrize(
    "point",
    ["after_staging_pre_witness", "after_witness_pre_finalization"],
)
async def test_dispatch_barrier_reaches_exact_durable_boundary_and_releases(
    tmp_path: Path,
    point: CrashBarrierPoint,
) -> None:
    engine = create_engine(tmp_path / f"{point}.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / f"repo-{point}"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = f"barrier-{point}"

    try:
        controller = await _seed_active_run(session_factory, run_id, clock, ids)
        scheduled = await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 60, "max_grants": 1},
        )
        lease = next(
            event.payload for event in scheduled.events if event.event_type == "lease_granted"
        )
        barrier = FileCrashBarrier(
            CrashBarrierConfig(
                authorization=CRASH_BARRIER_AUTHORIZATION,
                run_id=run_id,
                execution_id=str(lease["execution_id"]),
                point=point,
            ),
            state_dir=tmp_path / f"state-{point}",
        )
        executor = GraphDispatchExecutor(
            session_factory,
            controller,
            AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / f"artifacts-{point}"),
            crash_barrier=barrier,
        )
        dispatcher = OutboxDispatcher(session_factory, executor, clock)
        await dispatcher.dispatch_pending()

        # The final boundary intentionally performs real Git/file-state work.
        # Wait on the durable barrier state with enough test-only headroom for
        # loaded CI; this does not alter any supervisor health threshold.
        for _ in range(1_500):
            reached = barrier.read_status()
            if reached is not None:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("dispatch never reached configured crash barrier")

        assert reached.status == "reached"
        events_at_barrier = await _read_events(session_factory, run_id)
        event_types = [event.event_type for event in events_at_barrier]
        assert event_types.count("runner_submission_staged") == 1
        assert "runner_execution_finalized" not in event_types
        if point == "after_staging_pre_witness":
            assert "runner_completion_witnessed" not in event_types
        else:
            assert event_types.count("runner_completion_witnessed") == 1

        barrier.release()
        await executor.wait_for_all()

        final_events = await _read_events(session_factory, run_id)
        final_types = [event.event_type for event in final_events]
        assert final_types.count("runner_submission_staged") == 1
        assert final_types.count("runner_completion_witnessed") == 1
        assert final_types.count("runner_execution_finalized") == 1
        assert (
            final_types.index("runner_submission_staged")
            < final_types.index("runner_completion_witnessed")
            < final_types.index("runner_execution_finalized")
        )
        released = barrier.read_status()
        assert released is not None
        assert released.status == "released"
    finally:
        await engine.dispose()


async def test_schema_two_survives_checkpointed_two_process_dispatch_recovery(
    tmp_path: Path,
) -> None:
    database = tmp_path / "schema-two.db"
    artifacts = tmp_path / "artifacts-schema-two"
    barrier_dir = tmp_path / "barriers-schema-two"
    repo = tmp_path / "repo-schema-two"
    _init_repo(repo)
    engine = create_engine(database)
    await init_db(engine)
    sessions = create_session_factory(engine)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "schema-two-dispatch-recovery"
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    compiled = compile_routine(_routine(), clock, ids, run_id=run_id)
    effectful_events = [
        event.model_copy(update={"payload": {**event.payload, "semantic_stage": "effectful_batch"}})
        if event.event_type == "node_created" and event.payload.get("kind") == "worker"
        else event
        for event in compiled
    ]
    seeded = await controller.handle_command(
        run_id, 0, "seed_compiled_events", {"events": effectful_events}
    )
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    config = CrashBarrierPlanConfig(
        schema_version=2,
        authorization=CRASH_BARRIER_AUTHORIZATION,
        run_id=run_id,
        nonce="schema_two_dispatch_nonce",
        target=CrashBarrierTarget(kind="worker", semantic_stage="effectful_batch"),
        slots=("after_staging_pre_witness", "after_witness_pre_finalization"),
    )
    child_script = """
import asyncio, os
from pathlib import Path
from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.db import create_engine, create_session_factory
from orchestrator.graph_runtime import GraphController, GraphDispatchExecutor, OutboxDispatcher, crash_barrier_from_environment
from tests.integration.test_graph_runner_e2e import AgentFactory, FixedClock, GradingAgent, SequentialIds, SubmitAgent
async def main():
    engine = create_engine(Path(os.environ['DATABASE']))
    sessions = create_session_factory(engine)
    clock = FixedClock()
    controller = GraphController(sessions, clock, SequentialIds(int(os.environ['ID_START'])), auto_dispatch=False)
    barrier = crash_barrier_from_environment(os.environ, state_dir=Path(os.environ['BARRIER_DIR']), reconcile_process_loss=True)
    class ObservedBarrier:
        def read_status(self):
            return barrier.read_status()
        async def wait_if_armed(self, **kwargs):
            observation = kwargs.get('observation')
            if kwargs.get('point') == 'after_witness_pre_finalization':
                assert observation is not None and observation.recovered_attempts, observation
            await barrier.wait_if_armed(**kwargs)
    executor = GraphDispatchExecutor(sessions, controller, AgentFactory({'worker': SubmitAgent(), 'verifier': GradingAgent('A')}), worktree_path=Path(os.environ['REPO']), artifact_store=FilesystemArtifactStore(Path(os.environ['ARTIFACTS'])), crash_barrier=ObservedBarrier())
    dispatcher = OutboxDispatcher(sessions, executor, clock)
    await dispatcher.dispatch_pending(run_id=os.environ['RUN_ID'])
    await executor.wait_for_all()
    await engine.dispose()
asyncio.run(main())
"""
    environment = {
        **os.environ,
        "ORCHESTRATOR_GRAPH_CRASH_BARRIER": config.model_dump_json(),
        "DATABASE": str(database),
        "ARTIFACTS": str(artifacts),
        "BARRIER_DIR": str(barrier_dir),
        "REPO": str(repo),
        "RUN_ID": run_id,
    }

    def spawn_dispatch(id_start: int) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [sys.executable, "-c", child_script],
            cwd=Path(__file__).resolve().parents[2],
            env={**environment, "ID_START": str(id_start)},
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def wait_for_slot(slot: int, process: subprocess.Popen[bytes]) -> CrashBarrierPlanState:
        barrier = FileCrashBarrier(config, state_dir=barrier_dir)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read().decode() if process.stdout is not None else ""
                raise AssertionError(f"dispatch process exited {process.returncode}: {output}")
            state = barrier.read_status()
            assert isinstance(state, CrashBarrierPlanState)
            if state.slots[slot - 1].status == "reached":
                return state
            time.sleep(0.02)
        raise AssertionError(f"schema-2 slot {slot} was not reached")

    def kill_dispatch(process: subprocess.Popen[bytes]) -> None:
        os.killpg(process.pid, signal.SIGKILL)
        assert process.wait(timeout=5) == -signal.SIGKILL

    async def reconcile(id_start: int) -> tuple[GraphController, GraphDispatchExecutor]:
        restarted_controller = GraphController(
            sessions, clock, SequentialIds(id_start), auto_dispatch=False
        )
        restarted_executor = GraphDispatchExecutor(
            sessions,
            restarted_controller,
            AgentFactory({"worker": SubmitAgent(), "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(artifacts),
            crash_barrier=FileCrashBarrier(config, state_dir=barrier_dir),
        )
        dispatcher = OutboxDispatcher(sessions, restarted_executor, clock)
        report = await recover(sessions, dispatcher, run_id=run_id)
        await reconcile_runtime(restarted_controller, restarted_executor, report, dispatcher)
        return restarted_controller, restarted_executor

    first_process = spawn_dispatch(10_000)
    second_process: subprocess.Popen[bytes] | None = None
    try:
        first_state = await asyncio.to_thread(wait_for_slot, 1, first_process)
        first = first_state.slots[0]
        events_at_first = await _read_events(sessions, run_id)
        first_types = [event.event_type for event in events_at_first]
        assert first_types.count("runner_submission_staged") == 1
        assert "runner_completion_witnessed" not in first_types
        assert "runner_execution_finalized" not in first_types
        kill_dispatch(first_process)
        barrier = FileCrashBarrier(config, state_dir=barrier_dir)
        barrier.reconcile_process_loss()

        recovered_controller, _ = await reconcile(20_000)
        recovered_projection = await recovered_controller.read_projection(run_id)
        assert first.execution_id is not None
        recovered_attempt = execution_attempts_view(recovered_projection)[first.execution_id]
        assert recovered_attempt.completion_disposition == "restored_unwitnessed"
        assert recovered_attempt.retry_scheduled is True
        assert all(lease.state != "active" for lease in leases_view(recovered_projection).values())

        await recovered_controller.handle_command(
            run_id,
            await recovered_controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 60, "max_grants": 1},
        )
        # Reading after the latest append ensures production assembles the next
        # dispatch from a current checkpoint rather than a historical tail.
        await recovered_controller.read_projection(run_id)
        second_process = spawn_dispatch(30_000)
        second_state = await asyncio.to_thread(wait_for_slot, 2, second_process)
        second = second_state.slots[1]
        assert second.node_id == first.node_id
        assert second.execution_id != first.execution_id
        assert second.lease_generation is not None
        assert first.lease_generation is not None
        assert second.lease_generation > first.lease_generation
        events_at_second = await _read_events(sessions, run_id)
        second_types = [event.event_type for event in events_at_second]
        assert second_types.count("runner_completion_witnessed") == 1
        assert "runner_execution_finalized" not in second_types
        kill_dispatch(second_process)
        barrier.reconcile_process_loss()

        finalized_controller, _ = await reconcile(40_000)
        final_projection = await finalized_controller.read_projection(run_id)
        final_events = await _read_events(sessions, run_id)
        assert [event.event_type for event in final_events].count("runner_execution_finalized") == 1
        assert [event.event_type for event in final_events].count("callback_accepted") == 1
        assert all(lease.state != "active" for lease in leases_view(final_projection).values())
    finally:
        for process in (first_process, second_process):
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        await engine.dispose()
