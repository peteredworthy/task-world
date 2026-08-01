"""Slice 2.8 — graph run resume/recovery via the re-enterable driver.

The driver's run() recovers in-flight side effects (recover() +
reconcile_runtime()) before driving, so re-arming a graph run after a "restart"
resumes it. A restart is simulated by discarding the driver/runtime objects and
building fresh ones over the same tmp-file DB — the established pattern in
test_graph_runner_e2e / test_graph_outbox_crash_points. No mocks; hand-written
agents injected via constructor.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.config.enums import RunStatus
from orchestrator.graph import project_run_state, project_task_states
from orchestrator.graph_runtime import GraphController, GraphDispatchExecutor, seed_run
from orchestrator.runners import AgentRunner

# Reuse the driver-test harness (real SQLite tmp-file DB, real git repo,
# hand-written agents, real build via GraphController/GraphDispatchExecutor).
from tests.integration.test_graph_run_driver import (
    AgentFactory,
    FixedClock,
    GradingAgent,
    SequentialIds,
    SubmitAgent,
    _create_graph_run,
    _create_service,
    _events,
    _init_repo,
    _routine,
    _run_status,
    file_db,  # noqa: F401  (pytest fixture)
)
from orchestrator.workflow.graph_driver import GraphRunDriver
from orchestrator.graph_runtime.store import GraphEventStore

pytestmark = pytest.mark.slow


def _build_driver(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    repo: Path,
    agents: dict[str, AgentRunner],
    dispatch_order: list[str],
) -> GraphRunDriver:
    clock = FixedClock()
    ids = SequentialIds()

    def runtime_builder(
        sf,
        clock_arg,
        id_gen_arg,
        *,
        worktree_path,
        runner_type,
        runner_config=None,
        artifact_store,
    ):  # type: ignore[no-untyped-def]
        controller = GraphController(sf, clock_arg, id_gen_arg, auto_dispatch=False)
        executor = GraphDispatchExecutor(
            sf,
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
    )


async def _seed_active_worker_lease(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_id: str,
) -> None:
    clock = FixedClock()
    ids = SequentialIds()
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    await seed_run(
        session_factory,
        _routine(),
        run_id=run_id,
        clock=clock,
        id_gen=ids,
    )
    await controller.handle_command(run_id, await controller.current_position(run_id), "accept_run")
    await controller.handle_command(run_id, await controller.current_position(run_id), "start")
    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {
            "lease_seconds": 3600,
            "max_grants": 10,
            "base_snapshot_id": "routine-snapshot",
        },
    )


@pytest.mark.asyncio
async def test_resume_reschedules_dead_lease_to_completed(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],  # noqa: F811
    tmp_path: Path,
) -> None:
    """First drive leaves the worker lease active (execution 'died' after start
    ack). A second drive over the same DB with a fresh runtime recovers: the
    dead lease becomes agent_died, the node reschedules, a clean worker submits,
    the verifier grades A, the task is accepted and the run completes."""
    _, session_factory = file_db
    repo = tmp_path / "repo-dead-lease"
    _init_repo(repo)
    run_id = "graph-recover-dead-lease"
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)

    # Simulate a process restart after the scheduler granted a worker lease but
    # before any in-process executor is alive to acknowledge or submit it.
    await _seed_active_worker_lease(session_factory, run_id=run_id)
    events_after_first = await _events(session_factory, run_id)
    assert project_run_state(events_after_first) != "completed"

    # "Restart": fresh driver/runtime over the same DB. recover()+reconcile in
    # run() must agent_died the dead lease, reschedule, and drive to completion.
    order2: list[str] = []
    driver2 = _build_driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=order2,
    )
    outcome2 = await driver2.run(run_id)

    events = await _events(session_factory, run_id)
    assert project_task_states(events) == {"step-1/task-1": "accepted"}
    assert project_run_state(events) == "completed"
    assert outcome2.completed is True
    assert await _run_status(session_factory, run_id) == RunStatus.COMPLETED
    # The recovered worker and the verifier both ran on the second drive.
    assert "worker" in order2 and "verifier" in order2


@pytest.mark.asyncio
async def test_resume_after_clean_completion_is_idempotent_noop(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],  # noqa: F811
    tmp_path: Path,
) -> None:
    """Re-arming an already-completed graph run does not re-seed or regress it."""
    _, session_factory = file_db
    repo = tmp_path / "repo-rearm-complete"
    _init_repo(repo)
    run_id = "graph-recover-complete"
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)

    driver = _build_driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=[],
    )
    assert (await driver.run(run_id)).completed is True
    async with session_factory() as session:
        position_after_first = await GraphEventStore(session).current_position(run_id)

    # Re-arm: a second run() over a completed graph adds no new graph mutation
    # events (no re-seed, nothing to dispatch) and the run stays completed.
    driver2 = _build_driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=[],
    )
    await driver2.run(run_id)
    async with session_factory() as session:
        position_after_second = await GraphEventStore(session).current_position(run_id)

    events = await _events(session_factory, run_id)
    assert project_run_state(events) == "completed"
    assert position_after_second == position_after_first
    assert await _run_status(session_factory, run_id) == RunStatus.COMPLETED
