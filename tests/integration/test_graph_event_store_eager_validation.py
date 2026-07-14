"""Eager catalog payload validation at GraphEventStore.append_events time."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import EventV2Model, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    StoredEventEnvelope,
    build_graph_catalog,
    event_payload_json,
)
from orchestrator.graph_runtime import (
    EventPayloadCorruptionError,
    GRAPH_PAYLOAD_SCHEMA_GENERATION,
    GraphEventStore,
)


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
                payload=payload,
            )
        )
    )


def _invalid_event(
    event_id: str, run_id: str, event_type: str, payload: dict[str, Any]
) -> StoredEventEnvelope:
    """Construct deliberate generation-2 corruption for store-boundary tests."""
    return StoredEventEnvelope(
        event_id=event_id,
        run_id=run_id,
        position=1,
        event_type=event_type,
        payload_schema_generation=2,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


def _insert_raw_event(session: AsyncSession, event: StoredEventEnvelope) -> None:
    session.add(
        EventV2Model(
            aggregate_id=f"graph:{event.run_id}",
            version=event.position,
            event_type=event.event_type,
            payload=event.model_dump_json(),
            payload_schema_generation=GRAPH_PAYLOAD_SCHEMA_GENERATION,
            timestamp=event.timestamp.isoformat(),
        )
    )


def _candidate_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_id": "candidate-1",
        "record_kind": "output",
        "producer_node_id": "worker-1",
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "record_type": "candidate",
        "candidate_id": "candidate-1",
        "value": {"summary": "done"},
    }
    record.update(overrides)
    return record


@pytest.mark.asyncio
async def test_invalid_output_record_accepted_seed_fails_at_append_with_clear_message(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-eager-invalid"
    corrupt = _invalid_event(
        "evt-corrupt",
        run_id,
        "output_record_accepted",
        {"record": _candidate_record(unexpected_field="boom")},
    )

    async with session_factory() as session:
        async with session.begin():
            _insert_raw_event(session, corrupt)

    async with session_factory() as session:
        store = GraphEventStore(session, build_graph_catalog())
        with pytest.raises(EventPayloadCorruptionError) as error:
            await store.read_run(run_id)

    message = str(error.value)
    assert "output_record_accepted" in message
    assert "position 1" in message
    assert "unexpected_field" in message


@pytest.mark.asyncio
async def test_valid_output_record_accepted_seed_appends_and_reads_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-eager-valid"
    valid = _event(
        "evt-valid",
        run_id,
        "output_record_accepted",
        {"record": _candidate_record()},
    )

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session, build_graph_catalog())
            stored = await store.append_events(run_id, 0, [valid])

    assert event_payload_json(stored[0])["record"]["record_id"] == "candidate-1"

    async with session_factory() as session:
        store = GraphEventStore(session, build_graph_catalog())
        read_back = await store.read_run(run_id)

    assert [event.event_id for event in read_back] == ["evt-valid"]
    assert event_payload_json(read_back[0])["record"]["candidate_id"] == "candidate-1"


@pytest.mark.asyncio
async def test_raw_corrupt_payload_does_not_bypass_strict_hydration(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-eager-escape"
    valid = _event(
        "evt-1",
        run_id,
        "node_created",
        {"node_id": "worker-1", "kind": "worker"},
    )
    corrupt = _invalid_event("evt-2", run_id, "node_created", {"node_id": 123}).model_copy(
        update={"position": 2}
    )

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session, build_graph_catalog())
            await store.append_events(run_id, 0, [valid])

    async with session_factory() as session:
        async with session.begin():
            _insert_raw_event(session, corrupt)

    async with session_factory() as session:
        store = GraphEventStore(session, build_graph_catalog())
        with pytest.raises(EventPayloadCorruptionError) as error:
            await store.read_run(run_id)

    message = str(error.value)
    assert "node_created" in message
    assert "position 2" in message
    assert "node_id" in message
