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
from orchestrator.db import GraphOutboxModel
from orchestrator.graph import (
    FailureRecord,
    RecoveryPlanRecord,
    leases_view,
    node_states_view,
    project_run_state,
    project_task_states,
)
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
    scheduled = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {
            "lease_seconds": 3600,
            "max_grants": 10,
            "base_snapshot_id": "routine-snapshot",
        },
    )
    lease = next(event.payload for event in scheduled.events if event.event_type == "lease_granted")
    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "acknowledge_start",
        {
            "node_id": lease["node_id"],
            "lease_id": lease["lease_id"],
            "lease_generation": lease["generation"],
            "execution_id": lease["execution_id"],
        },
    )
    dispatch = next(item for item in scheduled.outbox_items if item.kind == "agent_dispatch")
    async with session_factory() as session:
        async with session.begin():
            row = await session.get(GraphOutboxModel, dispatch.outbox_id)
            assert row is not None
            row.status = "completed"


@pytest.mark.asyncio
async def test_resume_blocks_dead_lease_until_recovery_is_differentiated(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],  # noqa: F811
    tmp_path: Path,
) -> None:
    """A restart revokes a dead lease without repeating an identical attempt.

    The durable failure and recovery-plan records keep the node recoverable,
    but a health fact or changed recovery action must differentiate the retry
    before another runner can be dispatched.
    """
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
    # run() must classify the missing runtime and revoke its lease, but must not
    # hand the same work straight back to an indistinguishable runner attempt.
    order2: list[str] = []
    driver2 = _build_driver(
        session_factory,
        repo=repo,
        agents={"worker": SubmitAgent(), "verifier": GradingAgent("A")},
        dispatch_order=order2,
    )
    outcome2 = await driver2.run(run_id)

    events = await _events(session_factory, run_id)
    event_types = [event.event_type for event in events]
    projection = await GraphController(
        session_factory, FixedClock(), SequentialIds(), auto_dispatch=False
    ).read_projection(run_id)
    recovery_required_failures = [
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "failure_record"
        and isinstance(event.payload.get("value"), dict)
        and event.payload["value"].get("error_class") == "runtime_death_recovery_required"
    ]
    assert len(recovery_required_failures) == 1, [
        (event.event_type, event.payload) for event in events
    ]
    failure = FailureRecord.model_validate(recovery_required_failures[0].payload)
    recovery = RecoveryPlanRecord.model_validate(
        next(
            event.payload
            for event in events
            if event.event_type == "output_record_accepted"
            and event.payload.get("record_type") == "recovery_plan"
        )
    )

    assert project_task_states(events) == {"step-1/task-1": "pending"}
    assert project_run_state(events) == "active"
    assert outcome2.completed is False
    assert await _run_status(session_factory, run_id) == RunStatus.PAUSED
    assert order2 == []
    assert "runtime_retry_scheduled" not in event_types
    assert any(
        event.event_type == "lease_revoked"
        and event.payload.get("reason") == "runtime_process_missing_after_restart"
        for event in events
    )
    assert all(lease.state == "revoked" for lease in leases_view(projection).values())
    assert node_states_view(projection)[failure.value.failed_node_id] == "blocked"
    assert failure.value.failure_class == "infrastructure_failure"
    assert failure.value.retryable is True
    assert failure.value.reason == "runtime_process_missing_after_restart"
    assert recovery.producer_node_id == failure.value.failed_node_id
    assert recovery.value.action == "pause"
    assert recovery.value.retry_basis == "no_differentiating_action"
    assert recovery.value.retry_base_snapshot_id == "routine-snapshot"


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
