from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from orchestrator.api import create_app
from orchestrator.config import RoutineConfig, RoutineSource
from orchestrator.db import (
    GraphEventSummaryModel,
    GraphNodeDetailSummaryCheckpointModel,
    GraphNodeDetailSummaryModel,
    GraphProjectionSnapshotModel,
    init_db,
    save_run,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.state import create_run_from_routine

RAW_SENTINEL = "S3_RAW_SENTINEL_DO_NOT_RENDER"


@pytest.fixture
async def client_and_app() -> AsyncGenerator[tuple[AsyncClient, Any], None]:
    app = create_app(db_path=":memory:", routine_dirs=[("routines", RoutineSource.LOCAL)])
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app
    await app.state.engine.dispose()


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "s3-hidden-oracle",
            "name": "S3 Hidden Oracle Routine",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Build diagnostics",
                            "task_context": "Exercise S3 graph diagnostics.",
                            "verifier": {"rubric": [{"id": "req-1", "text": "Correct."}]},
                        }
                    ],
                }
            ],
        }
    )


def _event(run_id: str, event_id: str, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        causation_id="s3-hidden-oracle",
        correlation_id=None,
        timestamp=datetime(2026, 6, 21, 12, 0, tzinfo=UTC),
        payload=payload,
    )


def _graph_events(run_id: str) -> list[EventEnvelope]:
    return [
        _event(run_id, "evt-active", "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            run_id,
            "evt-worker-created",
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "task_region_id": "step-1/task-1",
                "prompt": f"raw prompt {RAW_SENTINEL}",
            },
        ),
        _event(
            run_id,
            "evt-verifier-pass-created",
            "node_created",
            {
                "node_id": "verifier-pass",
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "task_region_id": "step-1/task-1",
            },
        ),
        _event(
            run_id,
            "evt-verifier-expired-created",
            "node_created",
            {
                "node_id": "verifier-expired",
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "task_region_id": "step-1/task-1",
            },
        ),
        _event(
            run_id,
            "evt-gate-created",
            "node_created",
            {
                "node_id": "gate-human",
                "kind": "gate",
                "role": "approval",
                "state": "blocked",
                "gate_type": "human_approval",
                "prompt": "Review diagnostics evidence",
            },
        ),
        _event(
            run_id,
            "evt-review-created",
            "node_created",
            {
                "node_id": "review-final",
                "kind": "review",
                "role": "invariant",
                "state": "blocked",
                "blocker": "final invariant missing verification_evidence",
            },
        ),
        _event(
            run_id,
            "evt-patch-accepted",
            "graph_patch_accepted",
            {
                "patch_id": "patch-health-summary",
                "actor_role": "planner",
                "proposed_by_node_id": "planner-1",
                "successor_planner_node_ids": ["planner-gap"],
                "ops": [{"op": "create_node"}, {"op": "create_edge"}],
            },
        ),
        _event(
            run_id,
            "evt-patch-rejected",
            "graph_patch_rejected",
            {
                "patch_id": "patch-too-broad",
                "actor_role": "planner",
                "proposed_by_node_id": "planner-1",
                "reason": "read_set_changed",
            },
        ),
        _event(
            run_id,
            "evt-edge",
            "edge_created",
            {
                "edge_id": "edge-worker-verifier",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "verifier-pass",
                "to_port": "candidate_under_test",
            },
        ),
        _event(
            run_id,
            "evt-worker-lease",
            "lease_granted",
            {
                "lease_id": "lease-worker",
                "node_id": "worker-1",
                "generation": 1,
                "execution_id": "exec-worker",
                "expires_at": "2026-06-21T12:10:00+00:00",
                "base_snapshot_id": "S0",
            },
        ),
        _event(
            run_id,
            "evt-worker-running",
            "node_state_changed",
            {
                "node_id": "worker-1",
                "new_state": "running",
                "trigger": "runtime_start_acknowledged",
            },
        ),
        _event(
            run_id,
            "evt-output",
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "candidate summary", "body": RAW_SENTINEL * 256},
            },
        ),
        _event(
            run_id,
            "evt-file-state",
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "producer_node_id": "worker-1",
                "snapshot_id": "snapshot-1",
                "verdict": "captured",
                "tracked": [
                    {
                        "path": "src/orchestrator/api/routers/graph.py",
                        "status": "modified",
                        "classification": "source",
                        "needs_gatekeeper": False,
                    }
                ],
                "residue": [
                    {
                        "path": "reports/graph-health.json",
                        "classification": "test_artifact",
                        "needs_gatekeeper": False,
                    }
                ],
                "rejected_paths": [
                    {
                        "path": ".cache/noise.bin",
                        "classification": "tool_cache",
                        "reason": "ignored cache outside manifest",
                    }
                ],
                "diff_summary": {"files_changed": 2, "additions": 30, "deletions": 4},
            },
        ),
        _event(
            run_id,
            "evt-worker-callback",
            "callback_accepted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-worker",
                "lease_generation": 1,
                "execution_id": "exec-worker",
            },
        ),
        _event(run_id, "evt-worker-release", "lease_released", {"lease_id": "lease-worker"}),
        _event(
            run_id,
            "evt-input-bound",
            "input_bound",
            {
                "edge_id": "edge-worker-verifier",
                "to_node_id": "verifier-pass",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
            },
        ),
        _event(
            run_id,
            "evt-worker-completed",
            "node_state_changed",
            {"node_id": "worker-1", "new_state": "completed"},
        ),
        _event(
            run_id,
            "evt-verification-passed",
            "verification_passed",
            {
                "verifier_node_id": "verifier-pass",
                "candidate_id": "candidate-1",
                "task_region_id": "step-1/task-1",
                "record_id": "verification-pass",
                "value": {"grades": [{"requirement_id": "req-1", "grade": "A"}]},
            },
        ),
        _event(
            run_id,
            "evt-expired-lease",
            "lease_granted",
            {
                "lease_id": "lease-expired",
                "node_id": "verifier-expired",
                "generation": 1,
                "execution_id": "exec-expired",
                "expires_at": "2026-06-21T12:05:00+00:00",
                "base_snapshot_id": "S0",
            },
        ),
        _event(
            run_id,
            "evt-lease-expired",
            "lease_expired",
            {"lease_id": "lease-expired", "node_id": "verifier-expired"},
        ),
        _event(
            run_id,
            "evt-verifier-failed",
            "node_state_changed",
            {
                "node_id": "verifier-expired",
                "new_state": "failed",
                "trigger": "lease_expired_without_callback",
                "reason": "lease_expired_without_callback",
            },
        ),
        _event(
            run_id,
            "evt-verification-failed",
            "verification_failed",
            {
                "verifier_node_id": "verifier-expired",
                "candidate_id": "candidate-1",
                "task_region_id": "step-1/task-1",
                "record_id": "verification-failed",
                "evidence": f"raw verifier evidence {RAW_SENTINEL}",
                "value": {"grades": [{"requirement_id": "req-2", "grade": "C"}]},
            },
        ),
        _event(
            run_id,
            "evt-review-deferred",
            "node_deferred",
            {"node_id": "review-final", "reason": "missing_required_input:verification_evidence"},
        ),
        _event(
            run_id,
            "evt-complete-rejected",
            "command_rejected",
            {
                "command_type": "complete",
                "reason": "final invariant blockers remain",
                "blockers": [{"node_id": "review-final", "kind": "final_invariant"}],
            },
        ),
    ]


async def _save_synthetic_run(app: Any, run_id: str, *, graph: bool) -> None:
    run = create_run_from_routine(
        _routine(),
        repo_name=f"s3-hidden-{run_id}",
        source_branch="main",
    )
    run.id = run_id
    run.execution_mode = "graph" if graph else "legacy"
    async with app.state.session_factory() as session:
        await save_run(session, run)
        await session.commit()


async def _seed_graph(app: Any, run_id: str) -> None:
    await _save_synthetic_run(app, run_id, graph=True)
    async with app.state.session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, _graph_events(run_id))
        await session.commit()


async def _delete_disposable_read_models(app: Any, run_id: str) -> None:
    async with app.state.session_factory() as session:
        for model in (
            GraphEventSummaryModel,
            GraphProjectionSnapshotModel,
            GraphNodeDetailSummaryModel,
            GraphNodeDetailSummaryCheckpointModel,
        ):
            await session.execute(delete(model).where(model.run_id == run_id))
        await session.commit()


def _json_blob(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _count(health: dict[str, Any], key: str) -> int:
    value = health.get("counts", {}).get(key)
    assert isinstance(value, int), f"missing integer counts.{key}: {health}"
    return value


async def _health(client: AsyncClient, run_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/runs/{run_id}/graph/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


async def test_graph_health_snapshot_surfaces_blockers_without_raw_payloads(
    client_and_app: tuple[AsyncClient, Any],
) -> None:
    client, app = client_and_app
    run_id = "s3-hidden-graph"
    await _seed_graph(app, run_id)

    health = await _health(client, run_id)

    assert health["run_id"] == run_id
    assert health["run_state"] == "active"
    assert _count(health, "expired_leases") == 1
    assert _count(health, "failed_nodes") == 1
    assert _count(health, "final_blockers") == 1
    assert _count(health, "patches_accepted") == 1
    assert _count(health, "patches_rejected") == 1
    assert _count(health, "verifier_passed") == 1
    assert _count(health, "verifier_failed") == 1
    assert _count(health, "pending_gates") == 1

    assert any(
        row.get("node_id") == "verifier-expired"
        and row.get("reason") == "lease_expired_without_callback"
        for row in health["failed_nodes"]
    )
    assert any(
        row.get("node_id") == "verifier-expired"
        and row.get("reason") == "lease_expired_without_callback"
        for row in health["expired_leases"]
    )
    assert any(
        row.get("node_id") == "review-final"
        and "verification_evidence" in str(row.get("reason"))
        for row in health["blockers"]
    )
    assert any(row.get("patch_id") == "patch-health-summary" for row in health["recent_patch_decisions"])
    assert any(row.get("node_id") == "gate-human" for row in health["pending_gates"])
    assert RAW_SENTINEL not in _json_blob(health)

    await _delete_disposable_read_models(app, run_id)
    rebuilt = await _health(client, run_id)
    assert rebuilt["event_count"] == health["event_count"]
    assert rebuilt["counts"] == health["counts"]
    assert RAW_SENTINEL not in _json_blob(rebuilt)


async def test_default_graph_readbacks_are_summary_only_and_rebuildable(
    client_and_app: tuple[AsyncClient, Any],
) -> None:
    client, app = client_and_app
    run_id = "s3-hidden-readback"
    await _seed_graph(app, run_id)

    events_response = await client.get(f"/api/runs/{run_id}/graph/events")
    assert events_response.status_code == 200
    events = events_response.json()
    assert RAW_SENTINEL not in _json_blob(events)

    detail_response = await client.get(f"/api/runs/{run_id}/graph/nodes/worker-1")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["node_id"] == "worker-1"
    assert detail["output_records"][0]["record_id"] == "candidate-1"
    assert "value" not in detail["output_records"][0]
    assert detail["file_state_records"][0]["classification_summary"]["total_paths"] == 3
    assert RAW_SENTINEL not in _json_blob(detail)

    full_detail_response = await client.get(
        f"/api/runs/{run_id}/graph/nodes/worker-1?payload_mode=full"
    )
    assert full_detail_response.status_code == 200
    assert RAW_SENTINEL in _json_blob(full_detail_response.json())

    await _delete_disposable_read_models(app, run_id)
    rebuilt_detail_response = await client.get(f"/api/runs/{run_id}/graph/nodes/worker-1")
    assert rebuilt_detail_response.status_code == 200
    rebuilt_detail = rebuilt_detail_response.json()
    assert rebuilt_detail["output_records"][0]["record_id"] == "candidate-1"
    assert RAW_SENTINEL not in _json_blob(rebuilt_detail)


async def test_legacy_runs_are_not_reported_as_graph_health(
    client_and_app: tuple[AsyncClient, Any],
) -> None:
    client, app = client_and_app
    run_id = "s3-hidden-legacy"
    await _save_synthetic_run(app, run_id, graph=False)

    run_response = await client.get(f"/api/runs/{run_id}")
    assert run_response.status_code == 200
    assert run_response.json()["is_graph_backed"] is False

    health = await _health(client, run_id)
    assert health["run_id"] == run_id
    assert health["event_count"] == 0
    assert health["run_state"] is None
    assert all(value == 0 for value in health["counts"].values())
