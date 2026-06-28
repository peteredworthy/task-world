"""Integration tests for GET /api/runs/{run_id}/evidence-digest."""

from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import TaskStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db.access.mutations import save_run
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.state import Attempt, ModelTokenUsage
from orchestrator.state.factory import create_run_from_routine


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "run-evidence-digest-api",
            "name": "Run Evidence Digest API",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Task Alpha",
                            "task_context": "Do not leak this prompt text.",
                            "verifier": {"rubric": [{"id": "req-1", "text": "Pass."}]},
                        },
                        {
                            "id": "task-2",
                            "title": "Task Beta",
                            "verifier": {"rubric": [{"id": "req-2", "text": "Pass."}]},
                        },
                    ],
                }
            ],
        }
    )


def _event(event_type: str, payload: dict[str, Any], position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{uuid4().hex}",
        run_id="placeholder",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


async def _save_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    *,
    execution_mode: str = "legacy",
    with_metrics: bool = False,
) -> tuple[str, str]:
    run = create_run_from_routine(_routine(), repo_name=f"repo-{run_id}", source_branch="main")
    run.id = run_id
    run.execution_mode = execution_mode
    if with_metrics:
        step = run.steps[0]
        step.tasks[0].status = TaskStatus.PENDING_USER_ACTION
        step.tasks[0].pending_action_type = "clarification"
        step.tasks[1].status = TaskStatus.COMPLETED
        attempt = Attempt(attempt_num=1)
        attempt.metrics.duration_ms = 777
        attempt.metrics.num_actions = 5
        attempt.token_usage_by_model = [
            ModelTokenUsage(
                model="gpt-4o",
                input_tokens=11,
                output_tokens=22,
                cache_read_tokens=3,
                cache_creation_tokens=4,
                cost_per_m_input=1.0,
                cost_per_m_output=2.0,
                cost_per_m_cache_read=3.0,
                cost_per_m_cache_creation=4.0,
            )
        ]
        step.tasks[0].attempts = [attempt]
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()
    return run.steps[0].id, run.steps[0].tasks[0].id


async def _seed_graph_run(app: Any, run_id: str) -> tuple[str, str]:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    step_id, task_id = await _save_run(
        session_factory, run_id, execution_mode="graph", with_metrics=True
    )

    events = [
        _event(
            "node_created",
            {
                "node_id": "node-a",
                "kind": "worker",
                "role": "builder",
                "state": "running",
                "title": "Task Alpha worker",
                "task_id": task_id,
                "task_region_id": f"{step_id}/{task_id}",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "output-1",
                "record_kind": "output",
                "port": "output",
                "producer_node_id": "node-a",
            },
            2,
        ),
        _event(
            "node_created",
            {
                "node_id": "node-b",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "title": "Task Beta worker",
            },
            3,
        ),
        _event(
            "node_deferred",
            {"node_id": "node-b", "reason": "resource_conflict:write:write"},
            4,
        ),
        _event(
            "node_created",
            {
                "node_id": "node-c",
                "kind": "gate",
                "role": "approval",
                "state": "planned",
                "title": "Gate node",
            },
            5,
        ),
        _event(
            "node_deferred",
            {"node_id": "node-c", "reason": "gate_not_approved:gate-c"},
            6,
        ),
        _event(
            "node_created",
            {
                "node_id": "node-review",
                "kind": "review",
                "state": "blocked",
                "title": "Review node",
                "reason": "final invariant blocked",
            },
            7,
        ),
    ]

    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()

    return step_id, task_id


async def test_evidence_digest_legacy_run_is_empty_for_graph_fields(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"legacy-digest-{uuid4().hex[:8]}"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id)

    response = await client.get(f"/api/runs/{run_id}/evidence-digest")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["is_graph_backed"] is False
    assert body["scheduler"] == {
        "graph_event_count": 0,
        "ready_count": 0,
        "blocked_count": 0,
        "waiting_resource_count": 0,
        "waiting_gate_count": 0,
        "active_lease_count": 0,
        "suspended_lease_count": 0,
    }
    assert body["representative_nodes"] == []
    assert body["blockers"] == []


async def test_evidence_digest_graph_run_limits_nodes_and_hides_evidence(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-digest-{uuid4().hex[:8]}"
    await _seed_graph_run(app, run_id)

    response = await client.get(
        f"/api/runs/{run_id}/evidence-digest?max_nodes=2&include_node_evidence=false",
    )

    assert response.status_code == 200
    body = response.json()
    run_resp = (await client.get(f"/api/runs/{run_id}")).json()
    assert body["is_graph_backed"] is True
    assert body["scheduler"]["graph_event_count"] == 7
    assert len(body["representative_nodes"]) <= 2
    assert body["representative_nodes"][0]["node_id"] == "node-a"
    assert body["representative_nodes"][0]["evidence_summary"] is None
    assert body["representative_nodes"][0]["blockers"] == []
    assert body["representative_nodes"][1]["node_id"] == "node-b"
    assert body["representative_nodes"][1]["evidence_summary"] is None
    assert "scheduler:waiting_resources:node-b:resource_conflict:write:write" in body["blockers"]
    assert "scheduler:blocked:node-review:blocked" in body["blockers"]
    assert "graph_review:node-review: final invariant blocked" in body["blockers"]
    assert body["metrics"]["total_tokens_read"] == run_resp["total_tokens_read"]
    assert body["metrics"]["total_tokens_write"] == run_resp["total_tokens_write"]
    assert body["metrics"]["total_tokens_cache"] == run_resp["total_tokens_cache"]
    assert body["metrics"]["total_duration_ms"] == run_resp["total_duration_ms"]
    assert body["metrics"]["total_num_actions"] == run_resp["total_num_actions"]
    assert body["metrics"]["estimated_cost_usd"] == run_resp["estimated_cost_usd"]


async def test_evidence_digest_validates_query_params(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"params-digest-{uuid4().hex[:8]}"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id)

    low = await client.get(f"/api/runs/{run_id}/evidence-digest?max_nodes=0")
    high = await client.get(f"/api/runs/{run_id}/evidence-digest?max_nodes=11")

    assert low.status_code == 422
    assert high.status_code == 422
