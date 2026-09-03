from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType, RunStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db import EventV2Model, create_engine, create_session_factory, init_db
from orchestrator.db.access.mutations import save_run
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.graph import project_graph_projection_snapshot
from orchestrator.state import Run
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import SignalConsumer, WorkflowService


def _routine_payload() -> dict[str, Any]:
    return {
        "id": "graph-routing",
        "name": "Graph Routing",
        "steps": [
            {
                "id": "step-1",
                "title": "Step 1",
                "tasks": [{"id": "task-1", "title": "Task"}],
            }
        ],
    }


async def test_create_run_records_execution_mode(
    _shared_app_fixture: tuple[AsyncClient, Any, Path, Path, Any],
    git_repo: Path,
) -> None:
    client, _drain, _, _, _ = _shared_app_fixture

    response = await client.post(
        "/api/runs",
        json={
            "repo_name": git_repo.name,
            "branch": "main",
            "routine_embedded": _routine_payload(),
            "execution_mode": "graph",
            "agent_runner_type": "cli_subprocess",
        },
    )

    assert response.status_code == 201
    created = response.json()
    fetched = await client.get(f"/api/runs/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["execution_mode"] == "graph"


async def test_explicit_legacy_run_records_execution_mode_legacy(
    _shared_app_fixture: tuple[AsyncClient, Any, Path, Path, Any],
    git_repo: Path,
) -> None:
    client, _drain, _, _, _ = _shared_app_fixture

    response = await client.post(
        "/api/runs",
        json={
            "repo_name": git_repo.name,
            "branch": "main",
            "routine_embedded": _routine_payload(),
            "execution_mode": "legacy",
            "agent_runner_type": "cli_subprocess",
        },
    )

    assert response.status_code == 201
    assert response.json()["execution_mode"] == "legacy"


@pytest.mark.asyncio
async def test_run_start_routes_graph_mode_to_driver(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "routing.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    graph_called = asyncio.Event()
    workflow_called = False
    called_run_ids: list[str] = []

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def graph_runner(run_id: str) -> None:
        called_run_ids.append(run_id)
        graph_called.set()

    async def workflow_runner(workflow: Any) -> None:
        nonlocal workflow_called
        workflow_called = True

    try:
        run_id = "graph-routing-run"
        await _create_run(session_factory, run_id, execution_mode="graph")
        consumer = SignalConsumer(
            session_factory,
            create_service,
            workflow_runner=workflow_runner,
            graph_runner=graph_runner,
            poll_interval=100.0,
        )
        async with session_factory() as session:
            service = await create_service(session)
            await consumer._handle_run_start(run_id, None, session, service)

        await asyncio.wait_for(graph_called.wait(), timeout=2)
        assert called_run_ids == [run_id]
        assert workflow_called is False
        assert run_id not in consumer._active_workflows
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_graph_runner_escape_durably_pauses_and_cleans_up_without_duplicate_transition(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "graph-runner-escape.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    fallback_run_id = "graph-seed-escape-run"
    stopping_run_id = "graph-stopping-escape-run"
    already_paused_run_id = "graph-drive-escape-run"
    cancelled_run_id = "graph-cancelled-before-escape-run"
    errors = {
        fallback_run_id: "seed failed: no such column: semantic_contract",
        stopping_run_id: "driver escaped while stop was in flight",
        already_paused_run_id: "drive loop failed after its own pause",
        cancelled_run_id: "driver escaped after cancellation won",
    }

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def graph_runner(run_id: str) -> None:
        if run_id == already_paused_run_id:
            async with session_factory() as session:
                await WorkflowService(session).apply_pause_run(
                    run_id,
                    reason="graph_driver_crashed",
                    error_detail=errors[run_id],
                )
        elif run_id == cancelled_run_id:
            async with session_factory() as session:
                await WorkflowService(session).apply_cancel_run(
                    run_id,
                    reason="runner_cancelled",
                )
        raise RuntimeError(errors[run_id])

    try:
        for run_id, status in (
            (fallback_run_id, RunStatus.ACTIVE),
            (stopping_run_id, RunStatus.ACTIVE),
            (already_paused_run_id, RunStatus.ACTIVE),
            (cancelled_run_id, RunStatus.ACTIVE),
        ):
            await _create_run(
                session_factory,
                run_id,
                execution_mode="graph",
                status=status,
                agent_runner_type=AgentRunnerType.CODEX_SERVER,
            )

        # Model a crash while an ordinary queued pause is already in flight.
        # The public lifecycle boundary makes STOPPING observable before the
        # consumer owns the STOPPING -> PAUSED transition.
        async with session_factory() as session:
            await WorkflowService(session).pause_run(
                stopping_run_id,
                reason="graph_driver_crashed",
                error_detail=errors[stopping_run_id],
            )

        consumer = SignalConsumer(session_factory, create_service, graph_runner=graph_runner)
        for run_id in errors:
            if run_id == stopping_run_id:
                assert await consumer.arm_graph_run(run_id) is False
            else:
                assert await consumer.arm_graph_run(run_id) is True
                task = consumer._graph_driver_tasks[run_id]
                await asyncio.wait_for(task, timeout=2)

            # Crash handling only enqueues lifecycle intent. Exercise the same
            # event-backed consumer path that production uses to apply it.
            await consumer._process_run(run_id)

            async with session_factory() as session:
                run = await WorkflowService(session).get_run(run_id)
                result = await session.execute(
                    select(EventV2Model.payload).where(
                        EventV2Model.aggregate_id == run_id,
                        EventV2Model.event_type == "run_status_changed",
                    )
                )
                transitions = [json.loads(payload) for payload in result.scalars()]

            if run_id == cancelled_run_id:
                assert run.status == RunStatus.CANCELLED
                assert run.pause_reason is None
                assert run.last_error is None
                assert [item["new_status"] for item in transitions] == ["cancelled"]
            else:
                assert run.status == RunStatus.PAUSED
                assert run.pause_reason == "graph_driver_crashed"
                assert run.last_error == errors[run_id]
                expected_states = (
                    ["paused"] if run_id == already_paused_run_id else ["stopping", "paused"]
                )
                assert [item["new_status"] for item in transitions] == expected_states
                assert transitions[-1]["pause_reason"] == "graph_driver_crashed"
                assert transitions[-1]["last_error"] == errors[run_id]
            assert run_id not in consumer._active_graph_runs
            assert run_id not in consumer._graph_driver_tasks
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["construction", "get", "pause"])
async def test_graph_crash_pause_retries_transient_service_failure_with_fresh_session(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    engine = create_engine(tmp_path / f"graph-crash-pause-{failure_stage}.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = f"graph-crash-pause-{failure_stage}-run"
    error_detail = f"original {failure_stage} escape detail"
    service_attempts = 0
    seen_sessions: list[AsyncSession] = []

    class FailFirstGetService(WorkflowService):
        async def get_run(self, received_run_id: str) -> Run:
            nonlocal service_attempts
            if service_attempts == 1:
                raise RuntimeError("transient get failure")
            return await super().get_run(received_run_id)

    class FailFirstPauseService(WorkflowService):
        async def pause_run(
            self,
            received_run_id: str,
            reason: str = "manual_pause",
            error_detail: str | None = None,
        ) -> Run:
            nonlocal service_attempts
            if service_attempts == 1:
                raise RuntimeError("transient pause enqueue failure")
            return await super().pause_run(
                received_run_id,
                reason=reason,
                error_detail=error_detail,
            )

    async def create_service(session: AsyncSession) -> WorkflowService:
        nonlocal service_attempts
        service_attempts += 1
        seen_sessions.append(session)
        if failure_stage == "construction" and service_attempts == 1:
            raise RuntimeError("transient construction failure")
        if failure_stage == "get":
            return FailFirstGetService(session)
        if failure_stage == "pause":
            return FailFirstPauseService(session)
        return WorkflowService(session)

    async def graph_runner(received_run_id: str) -> None:
        assert received_run_id == run_id
        raise RuntimeError(error_detail)

    try:
        await _create_run(
            session_factory,
            run_id,
            execution_mode="graph",
            status=RunStatus.ACTIVE,
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
        )
        consumer = SignalConsumer(session_factory, create_service, graph_runner=graph_runner)

        assert await consumer.arm_graph_run(run_id) is True
        task = consumer._graph_driver_tasks[run_id]
        await asyncio.wait_for(task, timeout=2)

        assert service_attempts == 2
        assert len(seen_sessions) == 2
        assert seen_sessions[0] is not seen_sessions[1]
        async with session_factory() as session:
            stopping_run = await WorkflowService(session).get_run(run_id)
        assert stopping_run.status == RunStatus.STOPPING

        # The successful retry durably enqueued PAUSE; only the signal consumer
        # may apply STOPPING -> PAUSED.
        await consumer._process_run(run_id)

        assert service_attempts == 3
        assert seen_sessions[1] is not seen_sessions[2]
        async with session_factory() as session:
            run = await WorkflowService(session).get_run(run_id)
            result = await session.execute(
                select(EventV2Model.payload).where(
                    EventV2Model.aggregate_id == run_id,
                    EventV2Model.event_type == "run_status_changed",
                )
            )
            transitions = [json.loads(payload) for payload in result.scalars()]

        assert run.status == RunStatus.PAUSED
        assert run.pause_reason == "graph_driver_crashed"
        assert run.last_error == error_detail
        assert [item["new_status"] for item in transitions] == ["stopping", "paused"]
        assert transitions[-1]["last_error"] == error_detail
        assert run_id not in consumer._active_graph_runs
        assert run_id not in consumer._graph_driver_tasks
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_graph_crash_pause_exhaustion_is_bounded_and_observed(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "graph-crash-pause-exhaustion.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = "graph-crash-pause-exhaustion-run"
    service_attempts = 0

    async def unavailable_service(_session: AsyncSession) -> WorkflowService:
        nonlocal service_attempts
        service_attempts += 1
        raise RuntimeError("persistence unavailable")

    async def graph_runner(_run_id: str) -> None:
        raise RuntimeError("original graph runner failure")

    try:
        await _create_run(
            session_factory,
            run_id,
            execution_mode="graph",
            status=RunStatus.ACTIVE,
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
        )
        consumer = SignalConsumer(
            session_factory,
            unavailable_service,
            graph_runner=graph_runner,
        )

        assert await consumer.arm_graph_run(run_id) is True
        task = consumer._graph_driver_tasks[run_id]
        await asyncio.wait_for(task, timeout=2)

        assert service_attempts == 3
        assert task.exception() is None
        async with session_factory() as session:
            run = await WorkflowService(session).get_run(run_id)
        assert run.status == RunStatus.ACTIVE
        assert run_id not in consumer._active_graph_runs
        assert run_id not in consumer._graph_driver_tasks
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_graph_crash_pause_preserves_cancellation(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "graph-crash-pause-cancelled.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = "graph-crash-pause-cancelled-run"
    service_attempts = 0

    async def cancelled_service(_session: AsyncSession) -> WorkflowService:
        nonlocal service_attempts
        service_attempts += 1
        raise asyncio.CancelledError

    async def graph_runner(_run_id: str) -> None:
        raise RuntimeError("graph runner failed before fallback cancellation")

    try:
        await _create_run(
            session_factory,
            run_id,
            execution_mode="graph",
            status=RunStatus.ACTIVE,
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
        )
        consumer = SignalConsumer(
            session_factory,
            cancelled_service,
            graph_runner=graph_runner,
        )

        assert await consumer.arm_graph_run(run_id) is True
        task = consumer._graph_driver_tasks[run_id]
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)

        assert service_attempts == 1
        async with session_factory() as session:
            run = await WorkflowService(session).get_run(run_id)
        assert run.status == RunStatus.ACTIVE
        assert run_id not in consumer._active_graph_runs
        assert run_id not in consumer._graph_driver_tasks
    finally:
        await engine.dispose()


async def test_graph_cancel_applies_graph_terminal_state_only_during_signal_drain(
    _shared_app_fixture: tuple[AsyncClient, Any, Path, Path, Any],
) -> None:
    client, drain, _, _, app = _shared_app_fixture
    run_id = "graph-cancel-api-run"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _create_run(
        session_factory,
        run_id,
        execution_mode="graph",
        status=RunStatus.ACTIVE,
        agent_runner_type=AgentRunnerType.CODEX_SERVER,
    )
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _graph_event("run_lifecycle_changed", {"to_state": "active"}),
                _graph_event(
                    "node_created",
                    {"node_id": "worker-1", "kind": "worker", "state": "running"},
                ),
                _graph_event(
                    "lease_granted",
                    {
                        "lease_id": "lease-worker-1",
                        "node_id": "worker-1",
                        "generation": 1,
                        "execution_id": "exec-worker-1",
                        "expires_at": "2026-06-22T12:05:00+00:00",
                    },
                ),
            ],
        )
        await session.commit()

    response = await client.post(f"/api/runs/{run_id}/cancel")

    assert response.status_code == 202
    assert response.json()["is_graph_backed"] is True
    assert response.json()["status"] == "stopping"
    async with session_factory() as session:
        before_drain = await GraphEventStore(session).read_run(run_id)
    assert "lease_revoked" not in [event.event_type for event in before_drain]

    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "cancelled"


@pytest.mark.asyncio
async def test_server_shutdown_cancellation_pauses_graph_run_and_revokes_lease(
    tmp_path: Path,
) -> None:
    """Consumer shutdown must not strand an ACTIVE graph row with a live lease."""
    engine = create_engine(tmp_path / "graph-shutdown.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = "graph-server-shutdown-run"
    started = asyncio.Event()
    never = asyncio.Event()

    async def create_service(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    async def graph_runner(received_run_id: str) -> None:
        assert received_run_id == run_id
        started.set()
        await never.wait()

    try:
        await _create_run(
            session_factory,
            run_id,
            execution_mode="graph",
            status=RunStatus.ACTIVE,
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
        )
        async with session_factory() as session:
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [
                    _graph_event("run_lifecycle_changed", {"to_state": "active"}),
                    _graph_event(
                        "node_created",
                        {"node_id": "worker-1", "kind": "worker", "state": "running"},
                    ),
                    _graph_event(
                        "lease_granted",
                        {
                            "lease_id": "lease-worker-1",
                            "node_id": "worker-1",
                            "generation": 1,
                            "execution_id": "exec-worker-1",
                            "expires_at": "2026-06-22T12:05:00+00:00",
                        },
                    ),
                ],
            )
            await session.commit()

        consumer = SignalConsumer(session_factory, create_service, graph_runner=graph_runner)
        assert await consumer.arm_graph_run(run_id) is True
        await asyncio.wait_for(started.wait(), timeout=2)
        await consumer.stop()

        async with session_factory() as session:
            run = await WorkflowService(session).get_run(run_id)
            store = GraphEventStore(session)
            events = await store.read_run(run_id)
            projection, _, _ = await store.load_projection_with_tail(run_id)
            facts = await store.read_bounded_runtime_projection_facts(run_id)
        snapshot = project_graph_projection_snapshot(facts or [], projection=projection)

        assert run.status == RunStatus.PAUSED
        assert run.pause_reason == "server_shutdown"
        assert "agent_died" in [event.event_type for event in events]
        assert snapshot.active_leases == {}
    finally:
        await engine.dispose()


async def _create_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    *,
    execution_mode: str,
    status: RunStatus = RunStatus.DRAFT,
    agent_runner_type: AgentRunnerType = AgentRunnerType.CLI_SUBPROCESS,
) -> None:
    routine = RoutineConfig.model_validate(_routine_payload())
    run = create_run_from_routine(routine, repo_name="routing-repo", source_branch="main")
    run.id = run_id
    run.execution_mode = execution_mode
    run.status = status
    run.agent_runner_type = agent_runner_type
    async with session_factory() as session:
        if status == RunStatus.DRAFT:
            await WorkflowService(session).create_run(run)
        else:
            await save_run(session, run)
            await session.commit()


def _graph_event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    from tests.unit.graph_test_utils import canonical_event_payload

    return EventEnvelope(
        event_id=f"{event_type}-{len(str(payload))}",
        run_id="placeholder",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=canonical_event_payload(event_type, payload),
    )
