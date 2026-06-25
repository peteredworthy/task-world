from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api import create_app
from orchestrator.config import AgentRunnerType, RunStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db import init_db
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchExecutor,
    GraphEventStore,
    RecoveryReport,
    reconcile_runtime,
    seed_run,
)
from orchestrator.runners import AgentRunner
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import WorkflowService


@pytest.fixture
async def fr12_app(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncClient, Any], None]:
    app = create_app(db_path=str(tmp_path / "fr12-app.db"), routine_dirs=[])
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app
    await app.state.engine.dispose()


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class SequentialIds:
    def __init__(self, namespace: str) -> None:
        self._namespace = namespace
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{self._namespace}-{prefix}-{self._next}"
        self._next += 1
        return value


class NoRunningAgentFactory:
    def create_runner(self, context: object) -> AgentRunner:
        raise AssertionError("FR-12 recovery re-entry harness must not dispatch agents")


class NeverRunningRegistry:
    def is_running(self, execution_id: str) -> bool:
        return False


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "fr12-acceptance",
            "name": "FR-12 Acceptance",
            "execution_mode": "graph",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Recover after restart",
                            "task_context": "Exercise durable recovery re-entry.",
                            "retry": {"max_attempts": 2},
                            "requirements": [{"id": "req-1", "desc": "Recovery is durable."}],
                            "verifier": {
                                "rubric": [{"id": "req-1", "text": "Recovery is durable."}]
                            },
                        }
                    ],
                }
            ],
        }
    )


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# fr12 acceptance\n")
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


async def _create_active_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    routine: RoutineConfig,
    *,
    run_id: str,
    repo: Path,
) -> None:
    run = create_run_from_routine(routine, repo_name=repo.name, source_branch="main")
    run.id = run_id
    run.status = RunStatus.ACTIVE
    run.execution_mode = "graph"
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.worktree_path = str(repo)
    run.agent_runner_type = AgentRunnerType.CODEX_SERVER
    async with session_factory() as session:
        await WorkflowService(session).create_run(run)


async def _read_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
):
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _delete_read_models(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    async with session_factory() as session:
        store = GraphEventStore(session)
        await store.delete_read_models(run_id)
        await session.commit()


async def _get_json(client: AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200
    return response.json()


def _run_id() -> str:
    return f"fr12-recovery-reentry-{uuid4().hex[:8]}"


async def test_fr12_recovery_reentry_skips_stale_report_and_rebuilds_readbacks(
    fr12_app: tuple[AsyncClient, Any],
    tmp_path: Path,
) -> None:
    client, app = fr12_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    repo = tmp_path / "fr12-recovery-reentry"
    _init_repo(repo)
    run_id = _run_id()
    routine = _routine()
    clock = FixedClock()
    ids = SequentialIds(run_id)
    await _create_active_graph_run(session_factory, routine, run_id=run_id, repo=repo)
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    await seed_run(session_factory, routine, run_id=run_id, clock=clock, id_gen=ids)
    accepted = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "accept_run",
    )
    await controller.handle_command(run_id, accepted.projection_position, "start")
    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1, "base_snapshot_id": "snapshot-fr12"},
    )

    before_recovery = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")
    active_leases = before_recovery["leases"]["active"]
    assert len(active_leases) == 1
    active_lease = active_leases[0]
    assert active_lease["node_id"] == "worker-step-1-task-1"
    stale_report = RecoveryReport(
        redispatched=[],
        pending_cleanups=[],
        awaiting_start_ack=[
            {
                "run_id": run_id,
                "lease_id": active_lease["lease_id"],
                "node_id": active_lease["node_id"],
                "generation": active_lease["generation"],
                "execution_id": active_lease["execution_id"],
                "classification": "awaiting_start_ack",
            }
        ],
        awaiting_callback=[],
    )
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        NoRunningAgentFactory(),
        worktree_path=repo,
        process_registry=NeverRunningRegistry(),
    )

    await reconcile_runtime(controller, executor, stale_report)
    first_recovery_position = await controller.current_position(run_id)
    await reconcile_runtime(controller, executor, stale_report)

    events = await _read_events(session_factory, run_id)
    event_types = [event.event_type for event in events]
    positions = [event.position for event in events]
    assert positions == list(range(1, len(events) + 1))
    assert await controller.current_position(run_id) == first_recovery_position
    assert event_types.count("agent_died") == 1
    assert event_types.count("lease_revoked") == 1
    assert event_types.count("runtime_retry_scheduled") == 1
    assert any(
        event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "recovery_plan"
        for event in events
    )
    assert not any(event.event_type == "command_rejected" for event in events)

    run = await _get_json(client, f"/api/runs/{run_id}")
    graph = await _get_json(client, f"/api/runs/{run_id}/graph")
    events_json = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    node = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/worker-step-1-task-1?payload_mode=full",
    )
    scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")
    blockers = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")

    assert run["status"] == "active"
    assert run["is_graph_backed"] is True
    assert graph["run_state"] == "active"
    assert graph["node_states"]["worker-step-1-task-1"] == "ready"
    assert scheduler["scheduler"]["ready"] == ["worker-step-1-task-1"]
    assert scheduler["leases"] == {"active": [], "suspended": []}
    assert blockers["blockers"]
    assert [event["position"] for event in events_json] == positions
    assert [event["event_type"] for event in events_json].count("agent_died") == 1
    assert any(record["record_type"] == "recovery_plan" for record in node["output_records"])
    assert any(callback["event_type"] == "agent_died" for callback in node["callback_history"])

    await _delete_read_models(session_factory, run_id)
    rebuilt_graph = await _get_json(client, f"/api/runs/{run_id}/graph")
    rebuilt_scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")
    rebuilt_blockers = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")
    assert rebuilt_graph["event_count"] == graph["event_count"]
    assert rebuilt_graph["node_states"] == graph["node_states"]
    assert rebuilt_scheduler["scheduler"]["ready"] == ["worker-step-1-task-1"]
    assert rebuilt_scheduler["leases"] == {"active": [], "suspended": []}
    assert rebuilt_blockers["blockers"] == blockers["blockers"]
