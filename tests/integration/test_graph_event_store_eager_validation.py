"""Eager catalog payload validation at GraphEventStore.append_events time."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope, build_graph_catalog
from orchestrator.graph_runtime import GraphEventStore, InvalidGraphEventPayloadError


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
    corrupt = _event(
        "evt-corrupt",
        run_id,
        "output_record_accepted",
        {"record": _candidate_record(unexpected_field="boom")},
    )

    async with session_factory() as session:
        store = GraphEventStore(session, build_graph_catalog())
        with pytest.raises(InvalidGraphEventPayloadError) as error:
            await store.append_events(run_id, 0, [corrupt])

    message = str(error.value)
    assert "output_record_accepted" in message
    assert "position 1" in message
    assert "unexpected_field" in message

    async with session_factory() as session:
        store = GraphEventStore(session, build_graph_catalog())
        assert await store.current_position(run_id) == 0


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

    assert stored[0].payload["record"]["record_id"] == "candidate-1"

    async with session_factory() as session:
        store = GraphEventStore(session, build_graph_catalog())
        read_back = await store.read_run(run_id)

    assert [event.event_id for event in read_back] == ["evt-valid"]
    assert read_back[0].payload["record"]["candidate_id"] == "candidate-1"


@pytest.mark.asyncio
async def test_allow_invalid_payloads_escape_admits_intentional_corruption(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-eager-escape"
    valid = _event(
        "evt-1",
        run_id,
        "node_created",
        {"node_id": "worker-1", "kind": "worker"},
    )
    corrupt = _event("evt-2", run_id, "node_created", {"node_id": 123})

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session, build_graph_catalog())
            await store.append_events(run_id, 0, [valid])

    async with session_factory() as session:
        store = GraphEventStore(session, build_graph_catalog())
        with pytest.raises(InvalidGraphEventPayloadError):
            await store.append_events(run_id, 1, [corrupt])

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session, build_graph_catalog())
            # Intentional-corruption tests bypass disposable read models so the
            # corrupt row lands without being folded through strict hydration.
            await store.delete_read_models(run_id)
            await store.append_events(run_id, 1, [corrupt], allow_invalid_payloads=True)

    async with session_factory() as session:
        store = GraphEventStore(session, build_graph_catalog())
        read_back = await store.read_run(run_id)

    assert [event.event_id for event in read_back] == ["evt-1", "evt-2"]
    assert read_back[1].payload == {"node_id": 123}
