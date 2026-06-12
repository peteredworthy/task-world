from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import EventV2Model, create_engine, create_session_factory, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore, StaleProjectionError


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


@pytest.mark.asyncio
async def test_append_read_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-round-trip"
    events = [
        _event("evt-1", run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event("evt-2", run_id, "node_created", {"node_id": "worker-1", "kind": "worker"}),
    ]

    async with session_factory() as session:
        async with session.begin():
            stored = await GraphEventStore(session).append_events(run_id, 0, events)

    async with session_factory() as session:
        read_back = await GraphEventStore(session).read_run(run_id)

    assert [event.position for event in stored] == [1, 2]
    assert read_back == stored


@pytest.mark.asyncio
async def test_per_run_isolation(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session)
            await store.append_events(
                "store-run-a",
                0,
                [_event("evt-a", "store-run-a", "node_created", {"node_id": "a"})],
            )
            await store.append_events(
                "store-run-b",
                0,
                [_event("evt-b", "store-run-b", "node_created", {"node_id": "b"})],
            )

    async with session_factory() as session:
        store = GraphEventStore(session)
        run_a = await store.read_run("store-run-a")
        run_b = await store.read_run("store-run-b")

    assert [event.run_id for event in run_a] == ["store-run-a"]
    assert [event.run_id for event in run_b] == ["store-run-b"]


@pytest.mark.asyncio
async def test_unique_version_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-conflict"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [_event("evt-conflict-1", run_id, "node_created", {"node_id": "n1"})],
            )

    with pytest.raises(StaleProjectionError):
        async with session_factory() as session:
            async with session.begin():
                await GraphEventStore(session).append_events(
                    run_id,
                    0,
                    [_event("evt-conflict-2", run_id, "node_created", {"node_id": "n2"})],
                )


@pytest.mark.asyncio
async def test_unique_constraint_race_surfaces_stale_projection_error(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "graph-race.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = "store-race"

    try:
        async with session_factory() as reader_one, session_factory() as reader_two:
            position_one = await GraphEventStore(reader_one).current_position(run_id)
            position_two = await GraphEventStore(reader_two).current_position(run_id)

        assert position_one == 0
        assert position_two == 0

        async with session_factory() as session:
            async with session.begin():
                await GraphEventStore(session).append_events(
                    run_id,
                    position_one,
                    [_event("evt-race-1", run_id, "node_created", {"node_id": "n1"})],
                )

        with pytest.raises(StaleProjectionError):
            async with session_factory() as session:
                async with session.begin():
                    await GraphEventStore(session).append_events(
                        run_id,
                        position_two,
                        [_event("evt-race-2", run_id, "node_created", {"node_id": "n2"})],
                    )

        async with session_factory() as session:
            rows = await session.execute(
                select(EventV2Model).where(EventV2Model.aggregate_id == run_id)
            )
            stored_rows = list(rows.scalars())
            events = await GraphEventStore(session).read_run(run_id)

        assert len(stored_rows) == 1
        assert [event.event_id for event in events] == ["evt-race-1"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_read_from_offset(session_factory: async_sessionmaker[AsyncSession]) -> None:
    run_id = "store-offset"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [
                    _event("evt-offset-1", run_id, "node_created", {"node_id": "n1"}),
                    _event("evt-offset-2", run_id, "node_created", {"node_id": "n2"}),
                    _event("evt-offset-3", run_id, "node_created", {"node_id": "n3"}),
                ],
            )

    async with session_factory() as session:
        events = await GraphEventStore(session).read_run(run_id, from_position=2)

    assert [event.event_id for event in events] == ["evt-offset-2", "evt-offset-3"]
