from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.api import (
    build_node_detail_response,
    build_node_detail_response_from_summary,
)
from orchestrator.db import (
    EventV2Model,
    GraphNodeDetailSummaryCheckpointModel,
    GraphNodeDetailSummaryModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.graph_runtime.store import GraphNodeDetailSummary, graph_aggregate_id
from orchestrator.graph import build_graph_catalog
from orchestrator.graph import GraphCatalog
from orchestrator.graph import StoredEventEnvelope


@pytest.fixture(scope="module")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


def _event(
    event_id: str,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    schema_version: int = 2,
) -> EventEnvelope:
    return (
        build_graph_catalog()
        .resolve_event(event_type)
        .hydrate(
            StoredEventEnvelope(
                event_id=event_id,
                run_id=run_id,
                position=-1,
                event_type=event_type,
                payload_schema_generation=2,
                actor=Actor(kind=ActorKind.CONTROLLER),
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                payload={"record": payload}
                if event_type == "output_record_accepted"
                and not (isinstance(payload, dict) and "record" in payload)
                else payload,
            )
        )
    )


def _unsafe_event(
    event_id: str,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    schema_version: int,
) -> EventEnvelope:
    """Construct intentionally malformed persisted input for rejection coverage."""
    return EventEnvelope(
        event_id=event_id,
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=schema_version,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


def test_node_detail_rejects_unknown_generation_one_output_record(*, catalog: GraphCatalog) -> None:
    run_id = "legacy-output-record"
    with pytest.raises(TypeError, match="graph reduction requires HydratedEvent"):
        build_node_detail_response(
            run_id,
            "worker-1",
            [
                _unsafe_event(
                    "evt-legacy-output",
                    run_id,
                    "output_record_accepted",
                    {
                        "record": {
                            "record_type": "totally_unknown",
                            "record_id": "legacy-1",
                            "record_kind": "output",
                            "producer_node_id": "worker-1",
                        }
                    },
                    schema_version=1,
                )
            ],
            catalog=build_graph_catalog(),
        )


def test_node_detail_rejects_unknown_generation_two_output_record() -> None:
    run_id = "strict-output-record"
    summary = GraphNodeDetailSummary(
        run_id=run_id,
        node_id="worker-1",
        position=1,
        kind="worker",
        role=None,
        state=None,
        task_region_id=None,
        input_ports={},
        output_records=[],
        file_state_records=[],
        leases=[],
        active_lease=None,
        callback_history=[],
        events=[],
    )

    with pytest.raises(TypeError, match="node detail events require HydratedEvent"):
        build_node_detail_response_from_summary(
            summary,
            full_events=[
                _unsafe_event(
                    "evt-strict-output",
                    run_id,
                    "output_record_accepted",
                    {
                        "record": {
                            "record_type": "totally_unknown",
                            "record_id": "strict-1",
                            "record_kind": "output",
                            "producer_node_id": "worker-1",
                        }
                    },
                    schema_version=2,
                )
            ],
        )


def _representative_events(run_id: str) -> list[EventEnvelope]:
    heavy_body = {
        "summary": "candidate output",
        "body": "x" * 4096,
        "grades": {"req-1": "pass"},
    }
    return [
        _event("evt-active", run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "evt-worker",
            run_id,
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "task_region_id": "task-1",
                "command_definition": {
                    "id": "worker-command",
                    "cmd": "true",
                    "source": "test",
                },
            },
        ),
        _event(
            "evt-authority",
            run_id,
            "node_authority_changed",
            {
                "node_id": "worker-1",
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["."]}],
                "allowed_actions": ["submit"],
                "preconditions": ["candidate_bound"],
            },
        ),
        _event(
            "evt-verifier",
            run_id,
            "node_created",
            {
                "node_id": "verifier-1",
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "evt-edge",
            run_id,
            "edge_created",
            {
                "edge_id": "edge-1",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
            },
        ),
        _event(
            "evt-lease",
            run_id,
            "lease_granted",
            {
                "lease_id": "lease-1",
                "node_id": "worker-1",
                "generation": 1,
                "execution_id": "exec-1",
                "expires_at": "2026-01-01T00:01:00+00:00",
                "base_snapshot_id": "S0",
                "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["."]}],
            },
        ),
        _event(
            "evt-started",
            run_id,
            "node_state_changed",
            {
                "node_id": "worker-1",
                "new_state": "running",
                "trigger": "runtime_start_acknowledged",
            },
        ),
        _event(
            "evt-output",
            run_id,
            "output_record_accepted",
            {
                "record": {
                    "record_id": "candidate-1",
                    "record_kind": "output",
                    "producer_node_id": "worker-1",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "value": heavy_body,
                    "record_type": "candidate",
                    "candidate_id": "candidate-1",
                }
            },
        ),
        _event(
            "evt-file-state",
            run_id,
            "file_state_accepted",
            {
                "record_id": "fs-1",
                "record_kind": "file_state",
                "producer_node_id": "worker-1",
                "snapshot_id": "snapshot-1",
                "verdict": "captured",
                "tracked": [
                    {
                        "path": "src/app.py",
                        "classification": "source",
                        "needs_gatekeeper": False,
                    }
                ],
                "residue": [
                    {
                        "path": "tmp/output.log",
                        "classification": "test_artifact",
                        "needs_gatekeeper": False,
                    }
                ],
            },
        ),
        _event(
            "evt-callback",
            run_id,
            "callback_accepted",
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "idempotency_key": "node-detail-callback-1",
                "payload": {},
                "reason": "accepted",
            },
        ),
        _event(
            "evt-release",
            run_id,
            "lease_released",
            {"lease_id": "lease-1", "node_id": "worker-1", "generation": 1},
        ),
        _event(
            "evt-input",
            run_id,
            "input_bound",
            {
                "edge_id": "edge-1",
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
                "bound_at_position": 9,
            },
        ),
        _event(
            "evt-completed",
            run_id,
            "node_state_changed",
            {"node_id": "worker-1", "new_state": "completed"},
        ),
    ]


async def _count_model(session: AsyncSession, model: type[Any], run_id: str) -> int:
    result = await session.scalar(
        select(func.count()).select_from(model).where(model.run_id == run_id)
    )
    return int(result or 0)


async def _materialized_response(
    session: AsyncSession,
    run_id: str,
    node_id: str,
) -> dict[str, Any]:
    summary = await GraphEventStore(
        session,
        build_graph_catalog(),
    ).read_node_detail_summary(run_id, node_id)
    assert summary is not None
    return build_node_detail_response_from_summary(summary).model_dump(mode="json")


async def _stored_rows(session: AsyncSession, run_id: str) -> list[dict[str, Any]]:
    result = await session.execute(
        select(GraphNodeDetailSummaryModel)
        .where(GraphNodeDetailSummaryModel.run_id == run_id)
        .order_by(GraphNodeDetailSummaryModel.node_id)
    )
    return [
        {
            "run_id": row.run_id,
            "node_id": row.node_id,
            "position": row.position,
            "kind": row.kind,
            "role": row.role,
            "state": row.state,
            "task_region_id": row.task_region_id,
            "input_ports": row.input_ports,
            "output_records": row.output_records,
            "file_state_records": row.file_state_records,
            "leases": row.leases,
            "active_lease": row.active_lease,
            "callback_history": row.callback_history,
            "events": row.events,
            "prompt_summary": row.prompt_summary,
        }
        for row in result.scalars()
    ]


@pytest.mark.asyncio
async def test_append_creates_and_updates_node_detail_summaries(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "node-detail-sync"
    events = _representative_events(run_id)
    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(
                session,
                build_graph_catalog(),
            )
            await store.append_events(run_id, 0, events[:6])
            await store.append_events(run_id, 6, events[6:])

    async with session_factory() as session:
        worker = await _materialized_response(session, run_id, "worker-1")
        verifier = await _materialized_response(session, run_id, "verifier-1")
        checkpoint = await session.get(GraphNodeDetailSummaryCheckpointModel, run_id)

    assert checkpoint is not None
    assert checkpoint.position == len(events)
    assert worker["kind"] == "worker"
    assert worker["role"] == "builder"
    assert worker["state"] == "completed"
    assert worker["resource_claims"] == [{"mode": "write", "scope": "repo", "paths": ["."]}]
    assert worker["allowed_actions"] == ["submit"]
    assert worker["preconditions"] == ["candidate_bound"]
    assert worker["command_definition"] == {
        "id": "worker-command",
        "cmd": "true",
        "source": "test",
    }
    assert worker["active_lease"]["state"] == "released"
    assert worker["output_records"][0]["record_id"] == "candidate-1"
    assert "value" not in worker["output_records"][0]
    assert worker["file_state_records"][0]["classification_summary"]["total_paths"] == 0
    assert [event["event_type"] for event in worker["callback_history"]] == [
        "node_state_changed",
        "callback_accepted",
    ]
    assert verifier["input_ports"] == {"candidate_under_test": ["candidate-1"]}


@pytest.mark.asyncio
async def test_check_node_detail_summary_derives_command_precondition(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "node-detail-check-precondition"
    node_id = "check-1"
    events = [
        _event(
            "evt-check",
            run_id,
            "node_created",
            {
                "node_id": node_id,
                "kind": "check",
                "role": "auto_verify",
                "state": "planned",
                "task_region_id": "task-1",
                "command_definition": {
                    "id": "unit-check",
                    "cmd": "uv run python -c 'print(42)'",
                    "must": True,
                },
                "allowed_actions": ["submit_records"],
                "resource_claims": [{"mode": "read", "scope": "repo", "paths": ["."]}],
            },
        )
    ]
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(run_id, 0, events)

    async with session_factory() as session:
        check = await _materialized_response(session, run_id, node_id)

    assert check["allowed_actions"] == ["submit_records"]
    assert check["resource_claims"] == [{"mode": "read", "scope": "repo", "paths": ["."]}]
    assert check["command_definition"] == {
        "id": "unit-check",
        "cmd": "uv run python -c 'print(42)'",
        "must": True,
    }
    assert check["preconditions"] == ["has_command_definition"]


@pytest.mark.asyncio
async def test_node_detail_summary_accumulates_bind_all_input_ports(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "node-detail-bind-all"
    events = [
        _event(
            "evt-worker",
            run_id,
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "role": "builder", "state": "completed"},
        ),
        _event(
            "evt-summarizer",
            run_id,
            "node_created",
            {"node_id": "summarizer-1", "kind": "summarizer", "state": "planned"},
        ),
        _event(
            "evt-edge",
            run_id,
            "edge_created",
            {
                "edge_id": "edge-source-records",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
            },
        ),
        _event(
            "evt-bind-1",
            run_id,
            "input_bound",
            {
                "edge_id": "edge-source-records",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-1"],
                "binding_policy": "bind_all",
                "bound_at_position": 4,
            },
        ),
        _event(
            "evt-bind-2",
            run_id,
            "input_bound",
            {
                "edge_id": "edge-source-records",
                "to_node_id": "summarizer-1",
                "to_port": "source_records",
                "record_ids": ["candidate-2"],
                "binding_policy": "bind_all",
                "bound_at_position": 5,
            },
        ),
    ]

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(run_id, 0, events)

    async with session_factory() as session:
        summarizer = await _materialized_response(session, run_id, "summarizer-1")

    assert summarizer["input_ports"] == {"source_records": ["candidate-1", "candidate-2"]}


@pytest.mark.asyncio
async def test_node_detail_summaries_roll_back_with_append(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "node-detail-rollback"
    async with session_factory() as session:
        transaction = await session.begin()
        await GraphEventStore(
            session,
            build_graph_catalog(),
        ).append_events(run_id, 0, _representative_events(run_id))
        await transaction.rollback()

    async with session_factory() as session:
        event_count = await session.scalar(
            select(func.count())
            .select_from(EventV2Model)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
        )
        row_count = await _count_model(session, GraphNodeDetailSummaryModel, run_id)
        checkpoint_count = await _count_model(
            session,
            GraphNodeDetailSummaryCheckpointModel,
            run_id,
        )

    assert event_count == 0
    assert row_count == 0
    assert checkpoint_count == 0


@pytest.mark.asyncio
async def test_deleted_node_detail_rows_rebuild_on_summary_read(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "node-detail-rebuild-on-read"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(
                run_id,
                0,
                _representative_events(run_id),
            )
        await session.execute(
            delete(GraphNodeDetailSummaryModel).where(GraphNodeDetailSummaryModel.run_id == run_id)
        )
        await session.commit()

    async with session_factory() as session:
        response = await _materialized_response(session, run_id, "worker-1")
        await session.commit()

    async with session_factory() as session:
        row_count = await _count_model(session, GraphNodeDetailSummaryModel, run_id)

    assert response["node_id"] == "worker-1"
    assert row_count == 2


@pytest.mark.asyncio
async def test_deleted_node_detail_rows_do_not_partially_rebuild_on_append(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "node-detail-delete-then-append"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(
                run_id,
                0,
                _representative_events(run_id),
            )
        await session.execute(
            delete(GraphNodeDetailSummaryModel).where(GraphNodeDetailSummaryModel.run_id == run_id)
        )
        await session.commit()
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(
                run_id,
                len(_representative_events(run_id)),
                [
                    _event(
                        "evt-post-delete",
                        run_id,
                        "node_state_changed",
                        {"node_id": "worker-1", "new_state": "accepted"},
                    )
                ],
            )

    async with session_factory() as session:
        response = await _materialized_response(session, run_id, "worker-1")
        await session.commit()

    assert response["kind"] == "worker"
    assert response["role"] == "builder"
    assert response["state"] == "accepted"
    assert [event["event_id"] for event in response["events"]][0] == "evt-worker"
    assert [event["event_id"] for event in response["events"]][-1] == "evt-post-delete"


@pytest.mark.asyncio
async def test_node_detail_rebuild_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "node-detail-idempotent"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(
                run_id,
                0,
                _representative_events(run_id),
            )

    async with session_factory() as session:
        store = GraphEventStore(
            session,
            build_graph_catalog(),
        )
        await store.rebuild_node_detail_summaries(run_id)
        first_rows = await _stored_rows(session, run_id)
        first_response = await _materialized_response(session, run_id, "worker-1")
        await store.rebuild_node_detail_summaries(run_id)
        second_rows = await _stored_rows(session, run_id)
        second_response = await _materialized_response(session, run_id, "worker-1")

    assert second_rows == first_rows
    assert second_response == first_response


@pytest.mark.asyncio
async def test_node_detail_materializes_declared_appeal_and_recovery_node_references_on_append_and_rebuild(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Declared relation fields attach an event to every referenced node only."""
    run_id = "node-detail-declared-references"
    relation_event_ids = {
        "appeal-node": "evt-appeal-opened",
        "appealed-node": "evt-appeal-opened",
        "recovery-node": "evt-recovery-created",
        "guarded-planner-node": "evt-recovery-created",
        "predecessor-one": "evt-recovery-created",
        "predecessor-two": "evt-recovery-created",
    }
    node_ids = [*relation_event_ids, "unrelated-node"]
    seed_events = [
        _event(
            f"evt-{node_id}",
            run_id,
            "node_created",
            {"node_id": node_id, "kind": "worker", "state": "planned"},
        )
        for node_id in node_ids
    ]
    relation_events = [
        _event(
            "evt-recovery-created",
            run_id,
            "node_created",
            {
                "node_id": "recovery-node",
                "kind": "worker",
                "state": "planned",
                "recovery_of_node_id": "appeal-node",
                "guarded_planner_node_id": "guarded-planner-node",
                "predecessor_node_ids": ["predecessor-one", "predecessor-two"],
            },
        ),
        _event(
            "evt-appeal-opened",
            run_id,
            "appeal_opened",
            {
                "node_id": "appeal-node",
                "appealed_node_id": "appealed-node",
                "appeal_type": "invalid_test",
            },
        ),
    ]

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session, build_graph_catalog())
            await store.append_events(run_id, 0, seed_events)
            await store.append_events(run_id, len(seed_events), relation_events)

    async with session_factory() as session:
        incremental_events = {
            node_id: [
                event["event_id"]
                for event in (await _materialized_response(session, run_id, node_id))["events"]
            ]
            for node_id in node_ids
        }
        await session.execute(
            delete(GraphNodeDetailSummaryModel).where(GraphNodeDetailSummaryModel.run_id == run_id)
        )
        await GraphEventStore(session, build_graph_catalog()).rebuild_node_detail_summaries(run_id)
        rebuilt_events = {
            node_id: [
                event["event_id"]
                for event in (await _materialized_response(session, run_id, node_id))["events"]
            ]
            for node_id in node_ids
        }

    assert rebuilt_events == incremental_events
    for node_id, relation_event_id in relation_event_ids.items():
        assert relation_event_id in incremental_events[node_id]
    assert "evt-recovery-created" not in incremental_events["unrelated-node"]
    assert "evt-appeal-opened" not in incremental_events["unrelated-node"]


@pytest.mark.asyncio
async def test_node_detail_incrementally_materializes_forward_patch_successor_reference(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A patch may name its successor before the atomic batch creates it."""
    run_id = "node-detail-forward-patch-successor"
    seed_events = [
        _event(
            "evt-planner",
            run_id,
            "node_created",
            {"node_id": "planner-1", "kind": "planner", "state": "planned"},
        )
    ]
    patch_events = [
        _event(
            "evt-patch-accepted",
            run_id,
            "graph_patch_accepted",
            {
                "patch_id": "patch-successor",
                "base_graph_position": 1,
                "actor_role": "planner",
                "proposed_by_node_id": "planner-1",
                "successor_planner_node_ids": ["successor-planner-1"],
            },
        ),
        _event(
            "evt-successor-planner",
            run_id,
            "node_created",
            {
                "node_id": "successor-planner-1",
                "kind": "planner",
                "state": "planned",
            },
        ),
    ]

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session, build_graph_catalog())
            await store.append_events(run_id, 0, seed_events)
            await store.append_events(run_id, len(seed_events), patch_events)

    async with session_factory() as session:
        checkpoint = await session.get(GraphNodeDetailSummaryCheckpointModel, run_id)
        incremental_rows = await _stored_rows(session, run_id)
        successor = await _materialized_response(session, run_id, "successor-planner-1")
        await GraphEventStore(session, build_graph_catalog()).rebuild_node_detail_summaries(run_id)
        rebuilt_rows = await _stored_rows(session, run_id)

    assert checkpoint is not None
    assert checkpoint.position == len(seed_events) + len(patch_events)
    assert len(incremental_rows) == 2
    assert [event["event_id"] for event in successor["events"]] == [
        "evt-patch-accepted",
        "evt-successor-planner",
    ]
    assert incremental_rows == rebuilt_rows


@pytest.mark.asyncio
async def test_node_detail_invalidates_incremental_rows_for_absent_patch_successor_reference(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "node-detail-absent-patch-successor"
    seed_events = [
        _event(
            "evt-planner",
            run_id,
            "node_created",
            {"node_id": "planner-1", "kind": "planner", "state": "planned"},
        )
    ]
    absent_successor_patch = [
        _event(
            "evt-patch-accepted",
            run_id,
            "graph_patch_accepted",
            {
                "patch_id": "patch-absent-successor",
                "base_graph_position": 1,
                "actor_role": "planner",
                "proposed_by_node_id": "planner-1",
                "successor_planner_node_ids": ["absent-successor-planner"],
            },
        )
    ]

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session, build_graph_catalog())
            await store.append_events(run_id, 0, seed_events)
            await store.append_events(run_id, len(seed_events), absent_successor_patch)

    async with session_factory() as session:
        checkpoint = await session.get(GraphNodeDetailSummaryCheckpointModel, run_id)
        row_count = await _count_model(session, GraphNodeDetailSummaryModel, run_id)

    assert checkpoint is None
    assert row_count == 0


@pytest.mark.asyncio
async def test_node_detail_summary_matches_existing_light_builder(
    session_factory: async_sessionmaker[AsyncSession], *, catalog: GraphCatalog
) -> None:
    run_id = "node-detail-parity"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(
                run_id,
                0,
                _representative_events(run_id),
            )

    async with session_factory() as session:
        store = GraphEventStore(
            session,
            build_graph_catalog(),
        )
        light_events = await store.read_run_node_detail(run_id)
        old_response = build_node_detail_response(
            run_id, "worker-1", light_events, payload_mode="summary", catalog=build_graph_catalog()
        )
        new_response = await _materialized_response(session, run_id, "worker-1")

    assert old_response is not None
    old_dump = old_response.model_dump(mode="json")
    semantic_fields = set(new_response).difference({"events", "callback_history", "output_records"})
    assert len(semantic_fields) == 15
    assert semantic_fields == set(old_dump).difference(
        {"events", "callback_history", "output_records"}
    )
    assert {key: new_response[key] for key in semantic_fields} == {
        key: old_dump[key] for key in semantic_fields
    }
    assert [
        (event["event_id"], event["event_type"], event["position"])
        for event in new_response["events"]
    ] == [
        (event["event_id"], event["event_type"], event["position"]) for event in old_dump["events"]
    ]
    # Summary presentation remains an API concern after the named reader has
    # hydrated complete payloads; the persisted row retains the full body.
    assert [event["event_id"] for event in new_response["callback_history"]] == [
        event["event_id"] for event in old_dump["callback_history"]
    ]
    assert "value" not in new_response["output_records"][0]


@pytest.mark.asyncio
async def test_completed_sequential_leases_match_existing_summary_selection(
    session_factory: async_sessionmaker[AsyncSession], *, catalog: GraphCatalog
) -> None:
    run_id = "node-detail-lease-parity"
    events = [
        _event(
            "evt-worker",
            run_id,
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "evt-lease-1",
            run_id,
            "lease_granted",
            {
                "lease_id": "lease-1",
                "node_id": "worker-1",
                "generation": 1,
                "execution_id": "exec-1",
                "base_snapshot_id": "S0",
                "expires_at": "2026-01-01T00:05:00+00:00",
                "resource_claims": [],
            },
        ),
        _event(
            "evt-release-1",
            run_id,
            "lease_released",
            {"lease_id": "lease-1", "node_id": "worker-1", "generation": 1},
        ),
        _event(
            "evt-lease-2",
            run_id,
            "lease_granted",
            {
                "lease_id": "lease-2",
                "node_id": "worker-1",
                "generation": 2,
                "execution_id": "exec-2",
                "base_snapshot_id": "S0",
                "expires_at": "2026-01-01T00:05:00+00:00",
                "resource_claims": [],
            },
        ),
        _event(
            "evt-release-2",
            run_id,
            "lease_released",
            {"lease_id": "lease-2", "node_id": "worker-1", "generation": 2},
        ),
    ]
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(run_id, 0, events)

    async with session_factory() as session:
        store = GraphEventStore(
            session,
            build_graph_catalog(),
        )
        light_events = await store.read_run_node_detail(run_id)
        old_response = build_node_detail_response(
            run_id, "worker-1", light_events, payload_mode="summary", catalog=build_graph_catalog()
        )
        new_response = await _materialized_response(session, run_id, "worker-1")

    assert old_response is not None
    expected_lease = old_response.model_dump(mode="json")["active_lease"]
    expected_lease["resource_claims"] = []
    assert new_response["active_lease"] == expected_lease
    assert new_response["active_lease"]["lease_id"] == "lease-1"


@pytest.mark.asyncio
async def test_full_node_detail_path_keeps_heavy_output_and_file_state_detail(
    session_factory: async_sessionmaker[AsyncSession], *, catalog: GraphCatalog
) -> None:
    run_id = "node-detail-full"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(
                run_id,
                0,
                _representative_events(run_id),
            )

    async with session_factory() as session:
        events = await GraphEventStore(
            session,
            build_graph_catalog(),
        ).read_run(run_id)
        response = build_node_detail_response(
            run_id, "worker-1", events, payload_mode="full", catalog=build_graph_catalog()
        )

    assert response is not None
    full = response.model_dump(mode="json")
    assert full["output_records"][0]["value"]["body"].startswith("xxx")
    assert full["file_state_records"][0]["classification_summary"]["total_paths"] == 2
    assert full["file_state_records"][0]["tracked"][0]["path"] == "src/app.py"


@pytest.mark.asyncio
async def test_node_detail_rows_store_complete_hydrated_payloads(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "node-detail-compact"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(
                run_id,
                0,
                _representative_events(run_id),
            )

    async with session_factory() as session:
        full_events = await GraphEventStore(session, build_graph_catalog()).read_run(run_id)
        row = await session.get(
            GraphNodeDetailSummaryModel,
            {"run_id": run_id, "node_id": "worker-1"},
        )

    assert row is not None
    output_event = next(
        event for event in full_events if event.event_type == "output_record_accepted"
    )
    file_state_event = next(
        event for event in full_events if event.event_type == "file_state_accepted"
    )
    assert row.output_records == [output_event.payload.to_json()["record"]]
    assert row.file_state_records == [file_state_event.payload.to_json()]
