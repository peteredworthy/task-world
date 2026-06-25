from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api import create_app
from orchestrator.config import AgentRunnerType
from orchestrator.config.models import RoutineConfig
from orchestrator.db import GraphOutboxModel, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    capture_file_state_boundary,
)
from orchestrator.graph_runtime.controller import rebuild_projection
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
from orchestrator.workflow import GraphRunDriver, WorkflowService


@pytest.fixture
async def fr15_app(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncClient, Any], None]:
    app = create_app(db_path=str(tmp_path / "fr15-app.db"), routine_dirs=[])
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


class UnusedAgentFactory:
    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        raise AssertionError(f"unexpected agent dispatch for {context.node_id}")


class AgentFactory:
    def __init__(self, agents: dict[str, AgentRunner]) -> None:
        self._agents = agents

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        return self._agents[context.node_kind]


class SecretThenCleanWorker:
    def __init__(self) -> None:
        self.submissions = 0

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CODEX_SERVER, name="fr15-worker")

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
        worktree = Path(context.working_dir)
        self.submissions += 1
        secret = worktree / "fake_key.pem"
        if self.submissions == 1:
            secret.write_bytes(bytes(range(128)))
        else:
            secret.unlink(missing_ok=True)
            artifact = worktree / "docs/fr15-clean-retry.txt"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("clean retry\n", encoding="utf-8")
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class PassingVerifier:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CODEX_SERVER, name="fr15-verifier")

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
        assert on_grade is not None
        await on_grade("req-1", "A", "clean retry accepted")
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


async def test_fr15_gatekeeper_cleanup_is_explicit_graph_work_and_readable(
    fr15_app: tuple[AsyncClient, Any],
    tmp_path: Path,
) -> None:
    client, app = fr15_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    repo = tmp_path / "fr15-cleanup"
    _init_repo(repo)
    run_id = _run_id("fr15-cleanup")
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)

    (repo / "residue.txt").write_text("needs gatekeeper\n", encoding="utf-8")
    boundary = capture_file_state_boundary(
        worktree_path=repo,
        run_id=run_id,
        node_id="worker-cleanup",
        execution_id="exec-cleanup",
        base_snapshot_id="base-snapshot",
    )
    assert boundary.output_record is not None
    record_id = str(boundary.output_record["record_id"])
    old_snapshot_id = str(boundary.output_record["snapshot_id"])
    old_ref = f"refs/orchestrator/snapshots/{old_snapshot_id}"

    await _append_manual_cleanup_seed(session_factory, run_id, boundary.output_record)
    controller = GraphController(
        session_factory,
        FixedClock(),
        SequentialIds(run_id),
        auto_dispatch=False,
    )
    verdict = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "record_gatekeeper_verdicts",
        {
            "file_state_record_id": record_id,
            "execution_id": "exec-cleanup",
            "consult_id": "consult-cleanup",
            "verdicts": [_secret_verdict("residue.txt")],
        },
    )
    assert [item.kind for item in verdict.outbox_items] == ["snapshot_cleanup"]

    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        UnusedAgentFactory(),
        worktree_path=repo,
    )
    await OutboxDispatcher(session_factory, executor, FixedClock()).dispatch_pending()

    raw_events = await _read_events(session_factory, run_id)
    projection = rebuild_projection(raw_events)
    original = projection["file_state_records"][record_id]
    superseding_id = str(original["superseded_by_record_id"])
    superseding = projection["file_state_records"][superseding_id]
    new_ref = f"refs/orchestrator/snapshots/{superseding['snapshot_id']}"
    public_events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    node = await _get_json(
        client, f"/api/runs/{run_id}/graph/nodes/worker-cleanup?payload_mode=full"
    )
    file_state = await _get_json(client, f"/api/runs/{run_id}/graph/file-state")
    scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")

    event_types = [event["event_type"] for event in public_events]
    assert event_types == [
        "run_lifecycle_changed",
        "node_created",
        "file_state_accepted",
        "gatekeeper_verdict_recorded",
        "cleanup_requested",
        "gatekeeper_cost_recorded",
        "cleanup_applied",
        "output_record_accepted",
        "file_state_accepted",
    ]
    assert original["compromised"] is True
    assert original["superseded_pending"] is False
    assert original["compromised_paths"] == ["residue.txt"]
    assert original["cleanup_applied_event_id"] is not None
    assert superseding["supersedes_record_id"] == record_id
    assert superseding["cleanup_id"] == f"{record_id}:gatekeeper-secret"
    assert "residue.txt" not in _tree_paths(repo, str(superseding["git"]["commit_sha"]))
    assert _ref_exists(repo, old_ref) is False
    assert _ref_exists(repo, new_ref) is True
    assert [record["record_id"] for record in node["file_state_records"]] == [
        record_id,
        superseding_id,
    ]
    assert node["file_state_records"][1]["supersedes_record_id"] == record_id
    assert scheduler["leases"] == {"active": [], "suspended": []}
    assert await _outbox_statuses(session_factory) == ["completed"]
    boundaries = file_state["nodes"][0]["boundaries"]
    assert boundaries[0]["record_id"] == record_id
    assert boundaries[0]["gatekeeper_verdicts"][0]["classification"] == "secret"
    assert boundaries[1]["record_id"] == superseding_id
    assert boundaries[1]["captured_paths"] == []


async def test_fr15_rejected_file_state_revokes_write_lease_and_retries_cleanly(
    fr15_app: tuple[AsyncClient, Any],
    tmp_path: Path,
) -> None:
    client, app = fr15_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    repo = tmp_path / "fr15-retry"
    _init_repo(repo)
    run_id = _run_id("fr15-retry")
    await _create_graph_run(session_factory, _routine(), run_id=run_id, repo=repo)

    outcome = await _driver(
        session_factory,
        repo=repo,
        run_id=run_id,
        agents={"worker": SecretThenCleanWorker(), "verifier": PassingVerifier()},
    ).run(run_id)

    run = await _get_json(client, f"/api/runs/{run_id}")
    graph = await _get_json(client, f"/api/runs/{run_id}/graph")
    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    node = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/worker-step-1-task-1?payload_mode=full",
    )
    scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")
    file_state = await _get_json(client, f"/api/runs/{run_id}/graph/file-state")
    blockers = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")

    event_types = [event["event_type"] for event in events]
    rejection = next(event for event in events if event["event_type"] == "file_state_rejected")
    rejected_lease_id = rejection["payload"]["lease_id"]
    revoked = [
        event
        for event in events
        if event["event_type"] == "lease_revoked"
        and event["payload"]["lease_id"] == rejected_lease_id
    ]
    worker_file_states = node["file_state_records"]
    all_captured_paths = [
        path["path"]
        for report_node in file_state["nodes"]
        for boundary in report_node["boundaries"]
        for path in boundary["captured_paths"]
    ]

    assert outcome.completed is True
    assert run["status"] == "completed"
    assert graph["run_state"] == "completed"
    assert graph["node_states"]["worker-step-1-task-1"] == "completed"
    assert event_types.index("file_state_rejected") < event_types.index("agent_died")
    assert event_types.index("agent_died") < event_types.index("runtime_retry_scheduled")
    assert revoked
    assert rejection["payload"]["rejected_paths"][0]["path"] == "fake_key.pem"
    assert rejection["payload"]["rejected_paths"][0]["classification"] == "secret"
    assert not any(
        event["event_type"] == "file_state_accepted"
        and any(
            entry.get("path") == "fake_key.pem"
            for entry in event["payload"].get("classifications", [])
        )
        for event in events
    )
    assert [record["producer_node_id"] for record in worker_file_states] == ["worker-step-1-task-1"]
    snapshot_paths = _tree_paths(repo, str(worker_file_states[0]["git"]["commit_sha"]))
    artifact_records = [
        record for record in node["output_records"] if record["record_type"] == "artifact_reference"
    ]
    assert "fake_key.pem" not in all_captured_paths
    assert "fake_key.pem" not in snapshot_paths
    assert "docs/fr15-clean-retry.txt" in snapshot_paths
    assert artifact_records[0]["value"]["uri"] == "docs/fr15-clean-retry.txt"
    assert scheduler["leases"] == {"active": [], "suspended": []}
    assert blockers["blockers"] == []


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "fr15-acceptance",
            "name": "FR-15 Acceptance",
            "execution_mode": "graph",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Produce clean artifact",
                            "task_context": "Write the FR-15 clean retry artifact.",
                            "artifacts": [{"path": "docs/fr15-clean-retry.txt"}],
                            "retry": {"max_attempts": 3},
                            "requirements": [{"id": "req-1", "desc": "Artifact is clean."}],
                            "verifier": {
                                "rubric": [{"id": "req-1", "text": "The artifact is clean."}]
                            },
                        }
                    ],
                }
            ],
        }
    )


async def _create_service(session: AsyncSession) -> WorkflowService:
    return WorkflowService(session)


async def _create_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    routine: RoutineConfig,
    *,
    run_id: str,
    repo: Path,
) -> None:
    run = create_run_from_routine(routine, repo_name=repo.name, source_branch="main")
    run.id = run_id
    run.execution_mode = "graph"
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.worktree_path = str(repo)
    run.agent_runner_type = AgentRunnerType.CODEX_SERVER
    async with session_factory() as session:
        await WorkflowService(session).create_run(run)


def _driver(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    repo: Path,
    run_id: str,
    agents: dict[str, AgentRunner],
) -> GraphRunDriver:
    fixed_clock = FixedClock()
    ids = SequentialIds(run_id)

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
            AgentFactory(agents),
            worktree_path=repo,
        )
        return controller, executor

    return GraphRunDriver(
        session_factory,
        _create_service,
        clock=fixed_clock,
        id_gen=ids,
        runtime_builder=runtime_builder,
    )


async def _append_manual_cleanup_seed(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    file_state_record: dict[str, object],
) -> None:
    events = [
        _event(run_id, "run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            run_id,
            "node_created",
            {
                "node_id": "worker-cleanup",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
                "resource_claims": [{"mode": "write", "scope": "paths", "paths": ["docs/"]}],
            },
        ),
        _event(run_id, "file_state_accepted", file_state_record),
    ]
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, events)


async def _read_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> list[EventEnvelope]:
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _outbox_statuses(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[str]:
    async with session_factory() as session:
        result = await session.execute(
            select(GraphOutboxModel.status).order_by(GraphOutboxModel.outbox_id)
        )
        return [str(status) for status in result.scalars()]


async def _get_json(client: AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200
    return response.json()


def _event(run_id: str, event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{uuid4().hex}",
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FixedClock().now(),
        payload=payload,
    )


def _secret_verdict(path: str) -> dict[str, object]:
    return {
        "path": path,
        "classification": "secret",
        "confidence": 0.99,
        "rationale": "secret fixture",
        "model_id": "test-gatekeeper",
        "input_tokens": 1,
        "output_tokens": 1,
        "cost_usd": 0.001,
        "wall_time_ms": 1,
    }


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# fr15 acceptance\n", encoding="utf-8")
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


def _run_git(path: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _ref_exists(path: Path, ref: str) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref],
        cwd=path,
        check=False,
        timeout=30,
    )
    return result.returncode == 0


def _tree_paths(path: Path, commit_sha: str) -> set[str]:
    output = _run_git(path, ["ls-tree", "-r", "--name-only", commit_sha])
    return set(output.splitlines()) if output else set()


def _run_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"
