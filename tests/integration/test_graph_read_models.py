from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import (
    EventV2Model,
    GraphEventSummaryModel,
    GraphProjectionSnapshotModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.graph_runtime.store import graph_aggregate_id


@pytest.fixture(scope="module")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


def _event(event_id: str, run_id: str, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        causation_id="test",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


def _sample_events(run_id: str) -> list[EventEnvelope]:
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
            },
        ),
        _event(
            "evt-ready",
            run_id,
            "node_state_changed",
            {
                "node_id": "worker-1",
                "new_state": "ready",
                "blockers": ["waiting-for-input"],
                "graph_verifier_grades": {"req-1": "pass"},
                "tokens_by_node": {"worker-1": 30},
                "tokens_by_node_kind": {"worker": 30},
                "operations": [{"op": "replace"}, {"op": "add"}],
            },
        ),
        _event(
            "evt-output",
            run_id,
            "output_record_accepted",
            {
                "record_id": "record-1",
                "record_kind": "output",
                "producer_node_id": "worker-1",
                "port": "result",
                "value": {"large": "x" * 1024},
            },
        ),
    ]


async def _count_model(session: AsyncSession, model: type[Any], run_id: str) -> int:
    result = await session.scalar(
        select(func.count()).select_from(model).where(model.run_id == run_id)
    )
    return int(result or 0)


@pytest.mark.asyncio
async def test_append_keeps_graph_read_models_synchronized(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "read-model-sync"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, _sample_events(run_id))

    async with session_factory() as session:
        store = GraphEventStore(session)
        summaries = await store.read_run_summaries(run_id)
        snapshot = await store.read_projection_snapshot(run_id)

    assert [summary.position for summary in summaries] == [1, 2, 3, 4]
    assert summaries[2].payload == {
        "node_id": "worker-1",
        "new_state": "ready",
        "blockers": ["waiting-for-input"],
        "graph_verifier_grades": {"req-1": "pass"},
        "tokens_by_node": {"worker-1": 30},
        "tokens_by_node_kind": {"worker": 30},
        "patch_ops": 2,
    }
    assert summaries[-1].payload == {
        "producer_node_id": "worker-1",
        "record_id": "record-1",
        "record_kind": "output",
        "port": "result",
    }
    assert snapshot is not None
    assert snapshot.position == 4
    assert snapshot.run_state == "active"
    assert snapshot.node_states == {"worker-1": "ready"}
    assert snapshot.ready_nodes == ["worker-1"]


@pytest.mark.asyncio
async def test_graph_read_models_roll_back_with_event_append(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "read-model-rollback"
    async with session_factory() as session:
        transaction = await session.begin()
        await GraphEventStore(session).append_events(run_id, 0, _sample_events(run_id))
        await transaction.rollback()

    async with session_factory() as session:
        event_count = await session.scalar(
            select(func.count())
            .select_from(EventV2Model)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
        )
        summary_count = await _count_model(session, GraphEventSummaryModel, run_id)
        snapshot_count = await _count_model(session, GraphProjectionSnapshotModel, run_id)

    assert event_count == 0
    assert summary_count == 0
    assert snapshot_count == 0


@pytest.mark.asyncio
async def test_graph_read_models_are_rebuildable_and_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "read-model-rebuild"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, _sample_events(run_id))

    async with session_factory() as session:
        store = GraphEventStore(session)
        before_summaries = await store.read_run_summaries(run_id)
        before_snapshot = await store.read_projection_snapshot(run_id)
        await store.delete_read_models(run_id)
        await session.commit()

    async with session_factory() as session:
        event_count = await session.scalar(
            select(func.count())
            .select_from(EventV2Model)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
        )
        assert event_count == 4
        assert await _count_model(session, GraphEventSummaryModel, run_id) == 0
        assert await _count_model(session, GraphProjectionSnapshotModel, run_id) == 0

    async with session_factory() as session:
        store = GraphEventStore(session)
        rebuilt_snapshot = await store.rebuild_read_models(run_id)
        first_rebuild_summaries = await store.read_run_summaries(run_id)
        await store.rebuild_read_models(run_id)
        second_rebuild_summaries = await store.read_run_summaries(run_id)
        await session.commit()

    assert before_snapshot is not None
    assert rebuilt_snapshot is not None
    assert rebuilt_snapshot.position == before_snapshot.position
    assert rebuilt_snapshot.node_states == before_snapshot.node_states
    assert [summary.payload for summary in first_rebuild_summaries] == [
        summary.payload for summary in before_summaries
    ]
    assert [summary.payload for summary in second_rebuild_summaries] == [
        summary.payload for summary in before_summaries
    ]


@pytest.mark.asyncio
async def test_graph_event_summaries_are_paged_from_read_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "read-model-paging"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, _sample_events(run_id))

    async with session_factory() as session:
        store = GraphEventStore(session)
        first_page = await store.read_run_summaries(run_id, from_position=1, limit=2)
        second_page = await store.read_run_summaries(run_id, from_position=3, limit=2)

    assert [summary.position for summary in first_page] == [1, 2]
    assert [summary.position for summary in second_page] == [3, 4]
