"""Regression coverage for bounded graph outbox side-effect delivery."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.graph_runtime.store import (
    GRAPH_EVENT_PAYLOAD_BYTES,
    GRAPH_RUNTIME_TAIL_EVENTS,
    GraphReadModelUnavailable,
)
from tests.integration.test_graph_managed_snapshot_cleanup import (
    _dispatcher,
    _events,
    _managed_fixture,
    _rows,
)

pytestmark = pytest.mark.slow


@pytest.fixture
async def outbox_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph-outbox-durability.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_event_reader_accepts_exact_cap_and_rejects_one_byte_over(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, sessions = outbox_db
    run_id = "exact-runtime-cap"
    event = _callback_event(run_id, 1, 0)
    empty_size = len(event.model_dump_json().encode())
    exact_body_size = GRAPH_EVENT_PAYLOAD_BYTES - empty_size
    exact = _callback_event(run_id, 1, exact_body_size)
    assert len(exact.model_dump_json().encode()) == GRAPH_EVENT_PAYLOAD_BYTES
    await _append(sessions, run_id, [exact])

    async with sessions() as session:
        bounded = await GraphEventStore(session).read_bounded_runtime_events(
            run_id, from_position=1
        )
    assert [item.position for item in bounded] == [1]

    oversized = _callback_event(run_id, 2, exact_body_size + 1)
    assert len(oversized.model_dump_json().encode()) == GRAPH_EVENT_PAYLOAD_BYTES + 1
    await _append(sessions, run_id, [oversized])
    async with sessions() as session:
        with pytest.raises(GraphReadModelUnavailable, match="event_payload_exceeds_byte_cap"):
            await GraphEventStore(session).read_bounded_runtime_events(run_id, from_position=2)


@pytest.mark.asyncio
async def test_runner_recovery_uses_checkpoint_after_oversized_historical_event(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = outbox_db
    fixture = await _managed_fixture(
        sessions, tmp_path, "recovery-oversized-history", mismatch=True
    )
    position = await fixture.controller.current_position(fixture.run_id)
    await _append(
        sessions,
        fixture.run_id,
        [_callback_event(fixture.run_id, position + 1, GRAPH_EVENT_PAYLOAD_BYTES)],
    )

    dispatcher = _dispatcher(sessions, fixture, tmp_path)
    await dispatcher.dispatch_pending(
        run_id=fixture.run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    recovery_rows = await _rows(sessions, fixture.run_id, "runner_recovery")
    assert len(recovery_rows) == 1
    assert recovery_rows[0].status == "completed"
    assert (await _event_types(sessions, fixture.run_id)).count("runner_recovery_completed") == 1


@pytest.mark.asyncio
async def test_snapshot_cleanup_uses_checkpoint_after_oversized_historical_event(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = outbox_db
    fixture = await _managed_fixture(
        sessions, tmp_path, "cleanup-oversized-history", mismatch=False
    )
    position = await fixture.controller.current_position(fixture.run_id)
    await _append(
        sessions,
        fixture.run_id,
        [_callback_event(fixture.run_id, position + 1, GRAPH_EVENT_PAYLOAD_BYTES)],
    )

    await _dispatcher(sessions, fixture, tmp_path).dispatch_pending(run_id=fixture.run_id)
    cleanup_rows = await _rows(sessions, fixture.run_id, "snapshot_cleanup")
    assert cleanup_rows and all(row.status == "completed" for row in cleanup_rows)
    assert (await _event_types(sessions, fixture.run_id)).count("cleanup_applied") == 3


@pytest.mark.asyncio
async def test_runner_recovery_does_not_scan_beyond_tail_cap_or_duplicate_completion(
    outbox_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]], tmp_path: Path
) -> None:
    _, sessions = outbox_db
    fixture = await _managed_fixture(sessions, tmp_path, "recovery-long-history", mismatch=True)
    position = await fixture.controller.current_position(fixture.run_id)
    await _append(
        sessions,
        fixture.run_id,
        [
            _callback_event(fixture.run_id, position + offset, 0)
            for offset in range(1, GRAPH_RUNTIME_TAIL_EVENTS + 2)
        ],
    )

    async with sessions() as session:
        with pytest.raises(GraphReadModelUnavailable, match="recovery_tail_exceeds_bounded_cap"):
            await GraphEventStore(session).read_bounded_runtime_events(fixture.run_id)

    dispatcher = _dispatcher(sessions, fixture, tmp_path)
    await dispatcher.dispatch_pending(
        run_id=fixture.run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    await dispatcher.dispatch_pending(
        run_id=fixture.run_id, allowed_kinds=frozenset({"runner_recovery"})
    )
    assert (await _event_types(sessions, fixture.run_id)).count("runner_recovery_completed") == 1


def _callback_event(run_id: str, position: int, body_size: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"oversized-callback-{position}",
        run_id=run_id,
        position=position,
        event_type="callback_rejected_conflict",
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload={
            "node_id": "node-1",
            "lease_id": "lease-1",
            "lease_generation": 1,
            "execution_id": "execution-1",
            "idempotency_key": f"callback-{position}",
            "payload": {"body": "x" * body_size},
            "reason": "fixture",
        },
    )


async def _append(
    sessions: async_sessionmaker[AsyncSession], run_id: str, events: list[EventEnvelope]
) -> None:
    async with sessions() as session:
        async with session.begin():
            position = await GraphEventStore(session).current_position(run_id)
            await GraphEventStore(session).append_events(run_id, position, events)


async def _event_types(sessions: async_sessionmaker[AsyncSession], run_id: str) -> list[str]:
    return [event.event_type for event in await _events(sessions, run_id)]
