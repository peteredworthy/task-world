"""Integration tests for graph file-state report API."""

from __future__ import annotations


import json
from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.models import RoutineConfig
from orchestrator.db import EventV2Model
from orchestrator.db.access.mutations import save_run
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock, MAX_EVENT_ENVELOPE_BYTES
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.state.factory import create_run_from_routine


def _legacy_usage_snapshot(value: object) -> object:
    return value


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
    from tests.unit.graph_test_utils import canonical_event_payload

    return EventEnvelope(
        event_id=f"{event_type}-{uuid4().hex}",
        run_id="placeholder",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=canonical_event_payload(event_type, payload),
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
                    _legacy_usage_snapshot(
                        {
                            "path": "reports/result.xml",
                            "classification": "test_artifact",
                            "confidence": 0.92,
                            "rationale": "metadata shape matches test output",
                            "model_id": "fake-small-model",
                            "gen_ai_usage_input_tokens": 7,
                            "gen_ai_usage_output_tokens": 2,
                            "cost_usd": 0.0001,
                            "wall_time_ms": 5,
                        }
                    )
                ],
                "resolved_count": 1,
            },
        ),
        # This is the cost event emitted by a successful
        # ``record_gatekeeper_verdicts`` command. It has its own canonical
        # position, so pagination must account for it without duplicating the
        # earlier file-state boundary.
        _event(
            "gatekeeper_cost_recorded",
            {
                "file_state_record_id": "file-state-1",
                "execution_id": "exec-1",
                "consult_id": "consult-1",
                "model_id": "fake-small-model",
                "gen_ai_usage_input_tokens": 17,
                "gen_ai_usage_output_tokens": 5,
                "gen_ai_usage_cache_read_input_tokens": 3,
                "gen_ai_usage_cache_creation_input_tokens": 2,
                "item_count": 1,
                "cost_usd": 0.0017,
                "wall_time_ms": 42,
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        # A malformed, very large irrelevant payload proves the report query
        # filters at SQL before JSON deserialization; a full read would fail.
        session.add(
            EventV2Model(
                aggregate_id=f"graph:{run_id}",
                version=99,
                event_type="node_created",
                payload=json.dumps({"not": ["a canonical event"] * 10_000}),
                timestamp="2026-01-01T00:00:00+00:00",
            )
        )
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
    assert body["event_count"] == 1
    assert body["from_position"] == 0
    assert body["has_more"] is False
    assert body["next_position"] is None
    assert body["gatekeeper_scope"] == "page"
    assert body["gatekeeper_metrics_truncated"] is False
    assert body["gatekeeper"]["gatekeeper_resolved"] == 1
    assert body["gatekeeper"] == {
        "run_id": run_id,
        "boundary_count": 1,
        "deterministic_classifications": 1,
        "gatekeeper_consults": 1,
        "gatekeeper_resolved": 1,
        "unresolved_residue": 0,
        "total_classified": 2,
        "hit_rate": 0.5,
        "pattern_library_size": 1,
        "pattern_library_size_over_time": [
            {"position": 3, "file_state_record_id": "file-state-1", "size": 0},
            {"position": 4, "file_state_record_id": "file-state-1", "size": 1},
        ],
        "gen_ai_usage_input_tokens": 17,
        "gen_ai_usage_output_tokens": 5,
        "gen_ai_usage_cache_read_input_tokens": 3,
        "gen_ai_usage_cache_creation_input_tokens": 2,
        "cost_usd": 0.0017,
        "wall_time_ms": 42,
        "models": {
            "fake-small-model": {
                "model_id": "fake-small-model",
                "consults": 1,
                "gen_ai_usage_input_tokens": 17,
                "gen_ai_usage_output_tokens": 5,
                "gen_ai_usage_cache_read_input_tokens": 3,
                "gen_ai_usage_cache_creation_input_tokens": 2,
                "cost_usd": 0.0017,
                "wall_time_ms": 42,
                "executions": ["exec-1"],
            }
        },
    }
    assert len(body["nodes"]) == 1
    node = body["nodes"][0]
    assert node["node_id"] == "worker-1"
    boundary = node["boundaries"][0]
    assert boundary["snapshot_id"] == "snapshot-1"
    assert boundary["snapshot_type"] == "git_commit"
    assert boundary["diff_summary"] == {"files_changed": 2, "additions": 7, "deletions": 1}
    assert boundary["diff_summary_available"] is True
    assert boundary["classification_counts"]["source"] == 1
    assert boundary["classification_counts"]["test_artifact"] == 1
    assert boundary["classification_counts"]["tool_cache"] == 1
    captured = {entry["path"]: entry for entry in boundary["captured_paths"]}
    assert boundary["captured_source_entries_total"] == 3
    assert boundary["captured_paths_truncated"] is False
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
    assert boundary["gatekeeper_verdicts_total"] == 1
    assert boundary["gatekeeper_verdicts_truncated"] is False
    assert boundary["gatekeeper_facts_total"] == 2
    assert boundary["gatekeeper_facts_truncated"] is False


async def test_file_state_report_limit_one_keeps_boundary_verdict_and_cost_atomic(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"file-state-cost-page-{uuid4().hex[:8]}"
    await _seed_file_state_report_run(app, run_id)

    verdict_page = await client.get(f"/api/runs/{run_id}/graph/file-state?limit=1")

    assert verdict_page.status_code == 200
    verdict_body = verdict_page.json()
    assert verdict_body["event_count"] == 1
    assert verdict_body["has_more"] is False
    assert len(verdict_body["nodes"][0]["boundaries"]) == 1
    assert verdict_body["gatekeeper"]["gatekeeper_consults"] == 1
    assert verdict_body["gatekeeper"]["gen_ai_usage_input_tokens"] == 17
    assert verdict_body["gatekeeper"]["cost_usd"] == 0.0017
    assert verdict_body["gatekeeper"]["models"]["fake-small-model"]["wall_time_ms"] == 42


async def test_file_state_report_verdict_exact_cap_and_over_cap_metadata(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"file-state-verdict-cap-{uuid4().hex[:8]}"
    await _seed_file_state_report_run(app, run_id)

    exact = await client.get(f"/api/runs/{run_id}/graph/file-state?path_limit=1")
    assert exact.status_code == 200
    exact_boundary = exact.json()["nodes"][0]["boundaries"][0]
    assert len(exact_boundary["gatekeeper_verdicts"]) == 1
    assert exact_boundary["gatekeeper_verdicts_total"] == 1
    assert exact_boundary["gatekeeper_verdicts_truncated"] is False

    extra_verdict = _event(
        "gatekeeper_verdict_recorded",
        {
            "file_state_record_id": "file-state-1",
            "execution_id": "exec-1",
            "producer_node_id": "worker-1",
            "verdicts": [
                {
                    "path": "duplicate.out",
                    "classification": "build_output",
                    "confidence": 0.9,
                    "rationale": "first duplicate",
                },
                {
                    "path": "duplicate.out",
                    "classification": "build_output",
                    "confidence": 0.8,
                    "rationale": "second duplicate",
                },
            ],
            "resolved_count": 2,
        },
    )
    extra_verdict = extra_verdict.model_copy(update={"run_id": run_id, "position": 100})
    async with app.state.session_factory() as session:
        session.add(
            EventV2Model(
                aggregate_id=f"graph:{run_id}",
                version=100,
                event_type=extra_verdict.event_type,
                payload=extra_verdict.model_dump_json(),
                timestamp=extra_verdict.timestamp.isoformat(),
            )
        )
        await session.commit()

    over = await client.get(f"/api/runs/{run_id}/graph/file-state?path_limit=2")
    assert over.status_code == 200
    over_boundary = over.json()["nodes"][0]["boundaries"][0]
    assert [item["path"] for item in over_boundary["gatekeeper_verdicts"]] == [
        "reports/result.xml",
        "duplicate.out",
    ]
    assert over_boundary["gatekeeper_verdicts_total"] == 3
    assert over_boundary["gatekeeper_verdicts_truncated"] is True


async def test_file_state_report_caps_associated_gatekeeper_facts_per_boundary(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"file-state-fact-cap-{uuid4().hex[:8]}"
    await _seed_file_state_report_run(app, run_id)
    extra_facts = []
    for index in range(100):
        event = _event(
            "gatekeeper_cost_recorded",
            {
                "file_state_record_id": "file-state-1",
                "execution_id": "exec-1",
                "consult_id": f"extra-consult-{index}",
                "model_id": "fake-small-model",
                "gen_ai_usage_input_tokens": 1,
                "gen_ai_usage_output_tokens": 0,
                "gen_ai_usage_cache_read_input_tokens": 0,
                "gen_ai_usage_cache_creation_input_tokens": 0,
                "item_count": 1,
                "cost_usd": 0.0,
                "wall_time_ms": 1,
            },
        )
        extra_facts.append(
            EventV2Model(
                aggregate_id=f"graph:{run_id}",
                version=100 + index,
                event_type=event.event_type,
                payload=event.model_dump_json(),
                timestamp=event.timestamp.isoformat(),
            )
        )
    async with app.state.session_factory() as session:
        session.add_all(extra_facts)
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph/file-state?limit=1")
    assert response.status_code == 200
    boundary = response.json()["nodes"][0]["boundaries"][0]
    assert boundary["gatekeeper_facts_total"] == 102
    assert boundary["gatekeeper_facts_truncated"] is True
    assert boundary["gatekeeper_verdicts_total"] is None
    assert boundary["gatekeeper_verdicts_truncated"] is True
    assert response.json()["gatekeeper_metrics_truncated"] is True


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
    assert body == {
        "run_id": run_id,
        "event_count": 0,
        "from_position": 0,
        "has_more": False,
        "next_position": None,
        "path_limit": 50,
        "nodes": [],
        "gatekeeper_scope": "page",
        "gatekeeper_metrics_truncated": False,
        "orphan_gatekeeper_fact_count": 0,
        "gatekeeper": None,
    }


async def test_file_state_report_pages_only_matching_events_and_caps_paths(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"paged-file-state-report-{uuid4().hex[:8]}"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id, execution_mode="graph")
    paths = [
        {
            "path": f"generated/{index}.txt",
            "source": "untracked",
            "classification": "build_output",
            "matched_rule": "test",
            "needs_gatekeeper": False,
        }
        for index in range(4)
    ]
    events = [
        _event("node_created", {"node_id": "worker", "kind": "worker", "state": "planned"}),
        _event(
            "file_state_accepted",
            {
                "record_id": "first",
                "record_kind": "file_state",
                "producer_node_id": "worker",
                "snapshot_id": "first-snapshot",
                "base_snapshot_id": "base",
                "verdict": "captured",
                "classifications": paths,
            },
        ),
        _event("node_created", {"node_id": "other", "kind": "worker", "state": "planned"}),
        _event(
            "file_state_accepted",
            {
                "record_id": "second",
                "record_kind": "file_state",
                "producer_node_id": "worker",
                "snapshot_id": "second-snapshot",
                "base_snapshot_id": "base",
                "verdict": "captured",
                "classifications": [],
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()

    first = await client.get(f"/api/runs/{run_id}/graph/file-state?limit=1&path_limit=2")

    assert first.status_code == 200
    first_body = first.json()
    assert first_body["event_count"] == 1
    assert first_body["has_more"] is True
    assert first_body["next_position"] == 3
    first_boundary = first_body["nodes"][0]["boundaries"][0]
    assert [entry["path"] for entry in first_boundary["captured_paths"]] == [
        "generated/0.txt",
        "generated/1.txt",
    ]
    assert first_boundary["captured_source_entries_total"] == 4
    assert first_boundary["captured_paths_truncated"] is True

    second = await client.get(
        f"/api/runs/{run_id}/graph/file-state?from_position={first_body['next_position']}&limit=1"
    )
    assert second.status_code == 200
    assert second.json()["nodes"][0]["boundaries"][0]["record_id"] == "second"
    assert second.json()["has_more"] is False


async def test_file_state_report_large_boundary_retains_only_capped_path_output(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"large-file-state-boundary-{uuid4().hex[:8]}"
    await _save_run(app.state.session_factory, run_id, execution_mode="graph")
    source_entries = [
        {
            "path": f"generated/{index}.txt",
            "source": "untracked",
            "classification": "build_output",
            "matched_rule": "test",
            "needs_gatekeeper": False,
        }
        for index in range(10_000)
    ]
    async with app.state.session_factory() as session:
        stored = await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _event("node_created", {"node_id": "worker", "kind": "worker", "state": "planned"}),
            ],
        )
        historical = _event(
            "file_state_accepted",
            {
                "record_id": "large-boundary",
                "record_kind": "file_state",
                "producer_node_id": "worker",
                "snapshot_id": "large-snapshot",
                "base_snapshot_id": "base",
                "verdict": "captured",
                "classifications": source_entries,
            },
        ).model_copy(update={"run_id": run_id, "position": 2})
        assert len(historical.model_dump_json().encode()) > MAX_EVENT_ENVELOPE_BYTES
        session.add(
            EventV2Model(
                aggregate_id=f"graph:{run_id}",
                version=2,
                event_type=historical.event_type,
                payload=historical.model_dump_json(),
                timestamp=historical.timestamp.isoformat(),
            )
        )
        assert stored[0].position == 1
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph/file-state?path_limit=3")
    assert response.status_code == 200
    boundary = response.json()["nodes"][0]["boundaries"][0]
    assert [item["path"] for item in boundary["captured_paths"]] == [
        "generated/0.txt",
        "generated/1.txt",
        "generated/2.txt",
    ]
    assert len(boundary["captured_paths"]) == 3
    assert boundary["captured_source_entries_total"] == 10_000
    assert boundary["captured_paths_truncated"] is True
    assert boundary["diff_summary"] is None
    assert boundary["diff_summary_available"] is False


async def test_file_state_report_associates_same_execution_facts_by_record_id(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"file-state-associated-pages-{uuid4().hex[:8]}"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id, execution_mode="graph")

    def boundary(record_id: str) -> EventEnvelope:
        return _event(
            "file_state_accepted",
            {
                "record_id": record_id,
                "record_kind": "file_state",
                "producer_node_id": "worker",
                "snapshot_id": f"{record_id}-snapshot",
                "base_snapshot_id": "base",
                "verdict": "captured",
                "classifications": [],
            },
        )

    def verdict(record_id: str, path: str) -> EventEnvelope:
        return _event(
            "gatekeeper_verdict_recorded",
            {
                "file_state_record_id": record_id,
                "execution_id": "shared-execution",
                "producer_node_id": "worker",
                "verdicts": [
                    {
                        "path": path,
                        "classification": "build_output",
                        "confidence": 0.9,
                        "rationale": "test association",
                    }
                ],
                "resolved_count": 1,
            },
        )

    def cost(record_id: str, tokens: int) -> EventEnvelope:
        return _event(
            "gatekeeper_cost_recorded",
            {
                "file_state_record_id": record_id,
                "execution_id": "shared-execution",
                "consult_id": f"consult-{record_id}",
                "model_id": "model-a",
                "gen_ai_usage_input_tokens": tokens,
                "gen_ai_usage_output_tokens": 0,
                "gen_ai_usage_cache_read_input_tokens": 0,
                "gen_ai_usage_cache_creation_input_tokens": 0,
                "item_count": 1,
                "cost_usd": 0.0,
                "wall_time_ms": 1,
            },
        )

    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _event("node_created", {"node_id": "worker", "kind": "worker", "state": "planned"}),
                boundary("first"),
                boundary("second"),
                verdict("first", "first.out"),
                cost("first", 11),
                verdict("second", "second.out"),
                cost("second", 22),
            ],
        )
        await session.commit()

    first_page = await client.get(f"/api/runs/{run_id}/graph/file-state?limit=1")
    assert first_page.status_code == 200
    first_boundary = first_page.json()["nodes"][0]["boundaries"][0]
    assert first_boundary["record_id"] == "first"
    assert [entry["path"] for entry in first_boundary["gatekeeper_verdicts"]] == ["first.out"]
    assert first_page.json()["gatekeeper"]["gen_ai_usage_input_tokens"] == 11

    second_page = await client.get(
        f"/api/runs/{run_id}/graph/file-state?from_position={first_page.json()['next_position']}&limit=1"
    )
    assert second_page.status_code == 200
    second_boundary = second_page.json()["nodes"][0]["boundaries"][0]
    assert second_boundary["record_id"] == "second"
    assert [entry["path"] for entry in second_boundary["gatekeeper_verdicts"]] == ["second.out"]
    assert second_page.json()["gatekeeper"]["gen_ai_usage_input_tokens"] == 22


async def test_file_state_report_counts_orphan_gatekeeper_facts(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"file-state-orphan-{uuid4().hex[:8]}"
    await _save_run(app.state.session_factory, run_id, execution_mode="graph")
    orphan = _event(
        "gatekeeper_cost_recorded",
        {
            "file_state_record_id": "missing-boundary",
            "execution_id": "orphan-execution",
            "consult_id": "orphan-consult",
            "model_id": "model-a",
            "gen_ai_usage_input_tokens": 1,
            "gen_ai_usage_output_tokens": 0,
            "gen_ai_usage_cache_read_input_tokens": 0,
            "gen_ai_usage_cache_creation_input_tokens": 0,
            "item_count": 1,
            "cost_usd": 0.0,
            "wall_time_ms": 1,
        },
    )
    async with app.state.session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, [orphan])
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph/file-state")
    assert response.status_code == 200
    assert response.json()["nodes"] == []
    assert response.json()["orphan_gatekeeper_fact_count"] == 1


async def test_file_state_report_rejects_invalid_bounds(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"file-state-bounds-{uuid4().hex[:8]}"
    await _save_run(app.state.session_factory, run_id, execution_mode="graph")

    for query in ("limit=0", "limit=101", "path_limit=0", "path_limit=201", "from_position=-1"):
        response = await client.get(f"/api/runs/{run_id}/graph/file-state?{query}")
        assert response.status_code == 422
