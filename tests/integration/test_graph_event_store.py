from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import (
    EventV2Model,
    EventV2PayloadModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore, StaleProjectionError
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
                select(EventV2Model).where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            )
            stored_rows = list(rows.scalars())
            events = await GraphEventStore(session).read_run(run_id)

        assert len(stored_rows) == 1
        assert [event.event_id for event in events] == ["evt-race-1"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_graph_stream_coexists_with_legacy_workflow_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Legacy workflow events live in events_v2 under aggregate_id == run_id.
    The graph stream is namespaced (graph:<run_id>) so the two never contend
    for (aggregate_id, version) and never leak into each other's reads."""
    run_id = "store-coexist"
    async with session_factory() as session:
        async with session.begin():
            # Legacy workflow event at version 1 for the same run.
            event = EventV2Model(
                aggregate_id=run_id,
                version=1,
                event_type="run_created",
                timestamp="2026-01-01T00:00:00+00:00",
            )
            session.add(event)
            await session.flush()
            session.add(
                EventV2PayloadModel(
                    position=event.position,
                    payload='{"run_id": "store-coexist"}',
                )
            )

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session)
            # Graph stream starts empty despite the legacy row.
            assert await store.current_position(run_id) == 0
            # Appending at expected_position=0 must not collide with the
            # legacy row's (aggregate_id, version=1).
            await store.append_events(
                run_id,
                0,
                [_event("evt-coexist-1", run_id, "node_created", {"node_id": "n1"})],
            )

    async with session_factory() as session:
        store = GraphEventStore(session)
        events = await store.read_run(run_id)
        assert [event.event_id for event in events] == ["evt-coexist-1"]
        assert await store.current_position(run_id) == 1


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


@pytest.mark.asyncio
async def test_read_run_summaries_avoids_heavy_payload_materialization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-summary"
    large_payload = [{"path": f".venv/file-{index}.py"} for index in range(1000)]

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [
                    _event(
                        "evt-summary-1",
                        run_id,
                        "callback_accepted",
                        {
                            "node_id": "worker-1",
                            "lease_id": "lease-1",
                            "payload": {
                                "output_records": [
                                    {
                                        "record_kind": "file_state",
                                        "ignored": large_payload,
                                    }
                                ]
                            },
                        },
                    ),
                    _event(
                        "evt-summary-2",
                        run_id,
                        "node_created",
                        {
                            "node_id": "worker-1",
                            "kind": "worker",
                            "state": "planned",
                            "large_irrelevant_field": large_payload,
                        },
                    ),
                ],
            )

    async with session_factory() as session:
        summaries = await GraphEventStore(session).read_run_summaries(run_id)

    assert [summary.event_id for summary in summaries] == ["evt-summary-1", "evt-summary-2"]
    assert summaries[0].payload == {"lease_id": "lease-1", "node_id": "worker-1"}
    assert summaries[1].payload == {
        "kind": "worker",
        "node_id": "worker-1",
        "state": "planned",
    }


@pytest.mark.asyncio
async def test_read_run_light_preserves_projection_fields_without_heavy_payloads(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-light"
    large_payload = [{"path": f".venv/file-{index}.py"} for index in range(1000)]

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [
                    _event(
                        "evt-light-1",
                        run_id,
                        "node_created",
                        {
                            "node_id": "worker-1",
                            "kind": "worker",
                            "state": "planned",
                            "task_region_id": "step/task",
                            "resource_claims": [{"mode": "write", "scope": "repo"}],
                            "value": {"body": large_payload},
                        },
                    ),
                    _event(
                        "evt-light-2",
                        run_id,
                        "output_record_accepted",
                        {
                            "record_id": "candidate-1",
                            "record_kind": "output",
                            "producer_node_id": "worker-1",
                            "port": "candidate",
                            "candidate_id": "candidate-1",
                            "task_region_id": "step/task",
                            "value": {"body": large_payload},
                        },
                    ),
                    _event(
                        "evt-light-3",
                        run_id,
                        "callback_accepted",
                        {
                            "node_id": "worker-1",
                            "lease_id": "lease-1",
                            "payload": {"output_records": large_payload},
                        },
                    ),
                ],
            )

    async with session_factory() as session:
        events = await GraphEventStore(session).read_run_light(run_id)

    assert [event.event_id for event in events] == ["evt-light-1", "evt-light-2", "evt-light-3"]
    assert events[0].payload == {
        "kind": "worker",
        "node_id": "worker-1",
        "resource_claims": [{"mode": "write", "scope": "repo"}],
        "state": "planned",
        "task_region_id": "step/task",
    }
    assert events[1].payload == {
        "candidate_id": "candidate-1",
        "port": "candidate",
        "producer_node_id": "worker-1",
        "record_id": "candidate-1",
        "record_kind": "output",
        "task_region_id": "step/task",
    }
    assert events[2].payload == {"lease_id": "lease-1", "node_id": "worker-1"}
    assert all("value" not in event.payload for event in events)
    assert all("payload" not in event.payload for event in events)
