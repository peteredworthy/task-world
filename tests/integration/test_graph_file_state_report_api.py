"""Integration tests for graph file-state report API."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.models import RoutineConfig
from orchestrator.db.access.mutations import save_run
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.state.factory import create_run_from_routine


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-file-state-report-api-test",
            "name": "Graph File State Report API Test Routine",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Do one thing",
                            "task_context": "Exercise file-state report projections.",
                            "verifier": {"rubric": [{"id": "req-1", "text": "Correct."}]},
                        }
                    ],
                }
            ],
        }
    )


def _event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{uuid4().hex}",
        run_id="placeholder",
        position=-1,
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
) -> None:
    run = create_run_from_routine(
        _routine(),
        repo_name=f"graph-file-state-report-api-repo-{run_id}",
        source_branch="main",
    )
    run.id = run_id
    run.execution_mode = execution_mode
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()


async def _seed_file_state_report_run(app: Any, run_id: str) -> None:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id, execution_mode="graph")
    residue = {
        "path": "reports/result.xml",
        "source": "untracked",
        "classification": "unknown_ignored",
        "matched_rule": "unmatched_untracked",
        "needs_gatekeeper": True,
        "size_bytes": 42,
    }
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event("node_created", {"node_id": "worker-1", "kind": "worker", "state": "leased"}),
        _event(
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "producer_node_id": "worker-1",
                "snapshot_id": "snapshot-1",
                "base_snapshot_id": "base-1",
                "verdict": "captured",
                "git": {
                    "commit_sha": "commit-1",
                    "tree_sha": "tree-1",
                    "ref": "refs/orchestrator/snapshots/snapshot-1",
                    "diff_summary": {
                        "files_changed": 2,
                        "additions": 7,
                        "deletions": 1,
                    },
                },
                "classifications": [
                    {
                        "path": "src/app.py",
                        "source": "tracked",
                        "classification": "source",
                        "matched_rule": "tracked_source",
                        "needs_gatekeeper": False,
                    },
                    residue,
                ],
                "residue": [residue],
                "rejected_paths": [
                    {
                        "path": "tmp/cache.bin",
                        "source": "ignored",
                        "classification": "tool_cache",
                        "reason": "ignored cache outside manifest",
                        "needs_gatekeeper": False,
                    }
                ],
            },
        ),
        _event(
            "gatekeeper_verdict_recorded",
            {
                "file_state_record_id": "file-state-1",
                "execution_id": "exec-1",
                "producer_node_id": "worker-1",
                "verdicts": [
                    {
                        "path": "reports/result.xml",
                        "classification": "test_artifact",
                        "confidence": 0.92,
                        "rationale": "metadata shape matches test output",
                        "model_id": "fake-small-model",
                        "input_tokens": 7,
                        "output_tokens": 2,
                        "cost_usd": 0.0001,
                        "wall_time_ms": 5,
                    }
                ],
                "resolved_count": 1,
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()


async def test_file_state_report_lists_classifications_and_verdicts(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-file-state-report-{uuid4().hex[:8]}"
    await _seed_file_state_report_run(app, run_id)

    response = await client.get(f"/api/runs/{run_id}/graph/file-state")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["event_count"] == 4
    assert body["gatekeeper"]["gatekeeper_resolved"] == 1
    assert len(body["nodes"]) == 1
    node = body["nodes"][0]
    assert node["node_id"] == "worker-1"
    boundary = node["boundaries"][0]
    assert boundary["snapshot_id"] == "snapshot-1"
    assert boundary["snapshot_type"] == "git_commit"
    assert boundary["diff_summary"] == {"files_changed": 2, "additions": 7, "deletions": 1}
    assert boundary["classification_counts"]["source"] == 1
    assert boundary["classification_counts"]["test_artifact"] == 1
    assert boundary["classification_counts"]["tool_cache"] == 1
    captured = {entry["path"]: entry for entry in boundary["captured_paths"]}
    assert captured["reports/result.xml"]["classification"] == "test_artifact"
    assert captured["reports/result.xml"]["matched_rule"] == "gatekeeper:fake-small-model"
    assert boundary["rejected_paths"] == [
        {
            "path": "tmp/cache.bin",
            "classification": "tool_cache",
            "reason": "ignored cache outside manifest",
            "source": "ignored",
            "matched_rule": None,
            "needs_gatekeeper": False,
        }
    ]
    assert boundary["gatekeeper_verdicts"] == [
        {
            "path": "reports/result.xml",
            "verdict": "allow",
            "classification": "test_artifact",
            "rationale": "metadata shape matches test output",
            "confidence": 0.92,
            "model_id": "fake-small-model",
        }
    ]


async def test_file_state_report_empty_for_non_graph_run(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"legacy-file-state-report-{uuid4().hex[:8]}"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id)

    response = await client.get(f"/api/runs/{run_id}/graph/file-state")

    assert response.status_code == 200
    body = response.json()
    assert body == {"run_id": run_id, "event_count": 0, "nodes": [], "gatekeeper": None}
