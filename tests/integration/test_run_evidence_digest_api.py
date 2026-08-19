"""Integration tests for GET /api/runs/{run_id}/evidence-digest."""

from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import TaskStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.api import build_run_evidence_digest_response
from orchestrator.db import EventV2Model, GraphNodeDetailSummaryModel, GraphProjectionSnapshotModel
from orchestrator.db.access.mutations import save_run
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    project_lease_view,
)
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.graph_runtime.store import GRAPH_EVENT_PAYLOAD_BYTES, graph_aggregate_id
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
                gen_ai_usage_input_tokens=11,
                gen_ai_usage_output_tokens=22,
                gen_ai_usage_cache_read_input_tokens=3,
                gen_ai_usage_cache_creation_input_tokens=4,
                cost_usd=0.000067,
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
                "record_type": "fan_out_inputs",
                "producer_node_id": "node-a",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "output summary"},
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


async def test_evidence_digest_uses_current_snapshot_and_bounded_node_windows(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    """Irrelevant corrupt history must not cause a full stream read or parse."""
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"bounded-digest-{uuid4().hex[:8]}"
    await _seed_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory

    async with session_factory() as session:
        store = GraphEventStore(session)
        position = await store.current_position(run_id)
        output_events = [
            _event(
                "output_record_accepted",
                {
                    "record_id": f"bounded-output-{index}",
                    "record_kind": "output",
                    "record_type": "fan_out_inputs",
                    "producer_node_id": "node-a",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "value": {"summary": "small"},
                },
                position + index,
            )
            for index in range(1, 24)
        ]
        await store.append_events(run_id, position, output_events)
        position = await store.current_position(run_id)
        # This row represents old, corrupt, irrelevant history.  It is a real
        # DB row rather than a mock; the snapshot remains current because the
        # unknown event has no graph facts.
        session.add_all(
            [
                EventV2Model(
                    aggregate_id=graph_aggregate_id(run_id),
                    version=position + offset,
                    event_type="irrelevant_corrupt_event",
                    payload="{not json",
                    timestamp=FakeClock().now().isoformat(),
                )
                for offset in range(1, 251)
            ]
        )
        snapshot = await session.get(GraphProjectionSnapshotModel, run_id)
        assert snapshot is not None
        snapshot.position = position + 250
        await session.commit()

    statements: list[str] = []
    all_statements: list[str] = []

    def capture_payload_reads(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: Any,
    ) -> None:
        normalized = statement.lower()
        all_statements.append(normalized)
        if "select" in normalized and "events_v2" in normalized and "payload" in normalized:
            statements.append(normalized)

    engine = app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture_payload_reads)
    try:
        response = await client.get(f"/api/runs/{run_id}/evidence-digest?max_nodes=2")
    finally:
        event.remove(engine, "before_cursor_execute", capture_payload_reads)

    assert response.status_code == 200
    body = response.json()
    assert [node["node_id"] for node in body["representative_nodes"]] == ["node-a", "node-b"]
    node_a = body["representative_nodes"][0]
    assert node_a["title"] == "Task Alpha worker"
    assert node_a["evidence_status"] == "partial"
    assert "outputs=19" in node_a["evidence_summary"]
    assert body["graph_facts_status"] == "partial"
    # The endpoint made only limited payload reads for selected node IDs.  In
    # particular, it did not issue GraphEventStore.read_run's unbounded query.
    assert statements
    assert all("limit" in statement for statement in statements)
    assert not any("graph_projection_snapshots" in statement for statement in all_statements)


async def test_evidence_digest_skips_utf8_over_cap_evidence_body(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    """A selected non-ASCII body stays in SQL and makes evidence partial."""
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"utf8-bounded-digest-{uuid4().hex[:8]}"
    await _seed_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory

    async with session_factory() as session:
        store = GraphEventStore(session)
        position = await store.current_position(run_id)
        legacy_event = _event(
            "output_record_accepted",
            {
                "record_id": "utf8-over-cap-output",
                "record_kind": "output",
                "record_type": "fan_out_inputs",
                "producer_node_id": "node-a",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                # This historical body is above the byte cap even though it
                # contains fewer Unicode code points than the cap value.
                "value": {"summary": "é" * (GRAPH_EVENT_PAYLOAD_BYTES // 2 + 1)},
            },
            position + 1,
        ).model_copy(update={"run_id": run_id})
        # Seed a pre-contract canonical row directly. Production append must
        # reject this body; this test owns only bounded historical readback.
        session.add(
            EventV2Model(
                aggregate_id=graph_aggregate_id(run_id),
                version=position + 1,
                event_type=legacy_event.event_type,
                payload=legacy_event.model_dump_json(),
                timestamp=legacy_event.timestamp.isoformat(),
            )
        )
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/evidence-digest?max_nodes=1")

    assert response.status_code == 200
    node = response.json()["representative_nodes"][0]
    assert node["node_id"] == "node-a"
    assert node["evidence_status"] == "partial"
    assert "é" * 50 not in response.text


async def test_evidence_digest_graph_history_without_snapshot_uses_bounded_read_models(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"missing-snapshot-{uuid4().hex[:8]}"
    await _seed_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        snapshot = await session.get(GraphProjectionSnapshotModel, run_id)
        assert snapshot is not None
        await session.delete(snapshot)
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/evidence-digest")

    assert response.status_code == 200
    body = response.json()
    assert body["is_graph_backed"] is True
    assert body["graph_facts_status"] == "partial"
    assert [node["node_id"] for node in body["representative_nodes"]] == [
        "node-a",
        "node-b",
        "node-c",
    ]


async def test_digest_lease_counts_match_projection_lifecycle_semantics(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    """Terminal lease facts must supersede grants in the compact SQL window."""
    _client, _drain, _, _, app = _shared_app_fixture
    run_id = f"digest-leases-{uuid4().hex[:8]}"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    lifecycle = [
        ("lease_granted", {"lease_id": "active", "node_id": "node-active"}),
        ("lease_granted", {"lease_id": "renewed", "node_id": "node-renewed"}),
        ("lease_renewed", {"lease_id": "renewed", "node_id": "node-renewed"}),
        ("lease_granted", {"lease_id": "released", "node_id": "node-released"}),
        ("lease_released", {"lease_id": "released", "node_id": "node-released"}),
        ("lease_granted", {"lease_id": "revoked", "node_id": "node-revoked"}),
        ("lease_revoked", {"lease_id": "revoked", "node_id": "node-revoked"}),
        ("lease_granted", {"lease_id": "expired", "node_id": "node-expired"}),
        ("lease_expired", {"lease_id": "expired", "node_id": "node-expired"}),
        ("lease_granted", {"lease_id": "suspended", "node_id": "node-suspended"}),
        ("lease_suspended", {"lease_id": "suspended", "node_id": "node-suspended"}),
        ("lease_granted", {"lease_id": "old", "node_id": "node-reused"}),
        ("lease_released", {"lease_id": "old", "node_id": "node-reused"}),
        ("lease_granted", {"lease_id": "new", "node_id": "node-reused"}),
    ]
    events = [
        _event(event_type, payload, index)
        for index, (event_type, payload) in enumerate(lifecycle, 1)
    ]
    async with session_factory() as session:
        stored = await GraphEventStore(session).append_events(run_id, 0, events)
        digest = await GraphEventStore(session).read_evidence_digest_read_model(run_id, max_nodes=3)
        await session.commit()

    lease_view = project_lease_view(stored)
    assert digest.active_lease_count == len(lease_view["active"])
    assert digest.suspended_lease_count == len(lease_view["suspended"])
    assert digest.active_lease_count == 3  # active, renewed, and distinct new identity
    assert digest.suspended_lease_count == 1


async def test_digest_fallback_deduplicates_node_created_enrichments_before_limit(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    """A repeated enrichment must not consume another representative slot."""
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"fallback-digest-{uuid4().hex[:8]}"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    await _save_run(session_factory, run_id, execution_mode="graph")
    events = [
        _event(
            "node_created",
            {"node_id": "node-a", "kind": "worker", "state": "planned", "title": "First"},
            1,
        ),
        _event("node_state_changed", {"node_id": "node-a", "new_state": "running"}, 2),
        _event(
            "node_created",
            {
                "node_id": "node-a",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "title": "Current",
            },
            3,
        ),
        _event(
            "node_created",
            {
                "node_id": "node-b",
                "kind": "worker",
                "role": "coder",
                "state": "ready",
                "title": "Beta",
            },
            4,
        ),
        _event(
            "node_created",
            {
                "node_id": "node-c",
                "kind": "worker",
                "role": "coder",
                "state": "planned",
                "title": "Gamma",
            },
            5,
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.execute(
            delete(GraphNodeDetailSummaryModel).where(GraphNodeDetailSummaryModel.run_id == run_id)
        )
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/evidence-digest?max_nodes=3")

    assert response.status_code == 200
    nodes = response.json()["representative_nodes"]
    assert [node["node_id"] for node in nodes] == ["node-a", "node-b", "node-c"]
    assert nodes[0]["role"] == "builder"
    assert nodes[0]["state"] == "running"
    assert nodes[0]["title"] == "Current"


async def test_digest_blockers_dedupe_node_created_enrichments_before_cap(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    """More than the blocker cap of one node's enrichments cannot hide another node."""
    _client, _drain, _, _, app = _shared_app_fixture
    run_id = f"blocker-digest-{uuid4().hex[:8]}"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    events = [
        _event(
            "node_created",
            {
                "node_id": "node-a",
                "kind": "worker",
                "state": "blocked",
                "title": f"enrichment-{index}",
            },
            index,
        )
        for index in range(1, 102)
    ]
    events.append(
        _event(
            "node_created",
            {"node_id": "node-b", "kind": "worker", "state": "blocked", "title": "Beta"},
            102,
        )
    )
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        digest = await GraphEventStore(session).read_evidence_digest_read_model(run_id, max_nodes=3)
        await session.commit()

    assert digest.blockers == (
        "scheduler:blocked:node-a:blocked",
        "scheduler:blocked:node-b:blocked",
    )


async def test_bounded_store_evidence_keeps_latest_lease_lifecycle_for_presenter(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    """Newest-first SQL evidence must not be overwritten by the old grant."""
    _client, _drain, _, _, app = _shared_app_fixture
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    terminal_cases = ("lease_released", "lease_revoked", "lease_expired")
    for terminal_type in terminal_cases:
        run_id = f"digest-evidence-{terminal_type}-{uuid4().hex[:8]}"
        run = create_run_from_routine(_routine(), repo_name="repo", source_branch="main")
        run.id = run_id
        run.execution_mode = "graph"
        events = [
            _event(
                "node_created",
                {"node_id": "node-a", "kind": "worker", "state": "running", "title": "A"},
                1,
            ),
            _event("lease_granted", {"lease_id": "lease-a", "node_id": "node-a"}, 2),
            _event(terminal_type, {"lease_id": "lease-a"}, 3),
        ]
        async with session_factory() as session:
            stored = await GraphEventStore(session).append_events(run_id, 0, events)
            bounded = await GraphEventStore(session).read_bounded_node_evidence(run_id, ("node-a",))
            await session.commit()
        evidence = bounded.events_by_node["node-a"]
        assert [event.event_type for event in evidence[:3]] == [
            "node_created",
            terminal_type,
            "lease_granted",
        ]
        digest = build_run_evidence_digest_response(
            run,
            stored,
            evidence_by_node=bounded.events_by_node,
            associated_lease_ids_by_node=bounded.lease_ids_by_node,
        )
        assert project_lease_view(stored)["active"] == []
        assert "lease=terminal" in (digest.representative_nodes[0].evidence_summary or "")

    run_id = f"digest-evidence-suspended-{uuid4().hex[:8]}"
    run = create_run_from_routine(_routine(), repo_name="repo", source_branch="main")
    run.id = run_id
    run.execution_mode = "graph"
    events = [
        _event("node_created", {"node_id": "node-a", "kind": "worker", "state": "running"}, 1),
        _event("lease_granted", {"lease_id": "lease-a", "node_id": "node-a"}, 2),
        _event("lease_renewed", {"lease_id": "lease-a", "node_id": "node-a"}, 3),
        _event("lease_suspended", {"lease_id": "lease-a", "node_id": "node-a"}, 4),
    ]
    async with session_factory() as session:
        stored = await GraphEventStore(session).append_events(run_id, 0, events)
        bounded = await GraphEventStore(session).read_bounded_node_evidence(run_id, ("node-a",))
        await session.commit()
    digest = build_run_evidence_digest_response(
        run, stored, evidence_by_node=bounded.events_by_node
    )
    assert len(project_lease_view(stored)["suspended"]) == 1
    assert "lease=suspended" in (digest.representative_nodes[0].evidence_summary or "")


async def test_bounded_evidence_lease_identity_cap_marks_lease_unavailable(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    _client, _drain, _, _, app = _shared_app_fixture
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    run_id = f"digest-lease-cap-{uuid4().hex[:8]}"
    run = create_run_from_routine(_routine(), repo_name="repo", source_branch="main")
    run.id = run_id
    run.execution_mode = "graph"
    events = [
        _event("node_created", {"node_id": "node-a", "kind": "worker", "state": "running"}, 1),
        *[
            _event(
                "lease_granted",
                {"lease_id": f"lease-{index}", "node_id": "node-a"},
                index + 2,
            )
            for index in range(21)
        ],
        _event("lease_released", {"lease_id": "lease-0"}, 23),
    ]
    async with session_factory() as session:
        stored = await GraphEventStore(session).append_events(run_id, 0, events)
        bounded = await GraphEventStore(session).read_bounded_node_evidence(run_id, ("node-a",))
        await session.commit()

    assert "node-a" in bounded.truncated_node_ids
    # The authoritative projection can see the old terminal fact, but the
    # bounded identity set deliberately cannot claim that its selected window
    # covers every lease identity.
    assert all(entry["lease_id"] != "lease-0" for entry in project_lease_view(stored)["active"])
    digest = build_run_evidence_digest_response(
        run,
        stored,
        evidence_by_node=bounded.events_by_node,
        associated_lease_ids_by_node=bounded.lease_ids_by_node,
        partial_evidence_node_ids=bounded.truncated_node_ids,
    )
    assert digest.representative_nodes[0].evidence_status == "partial"
    assert "lease=unavailable" in (digest.representative_nodes[0].evidence_summary or "")
