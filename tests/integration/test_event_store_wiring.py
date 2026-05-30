"""Integration test: SqliteEventStore + JsonlOutboxObserver + PersistentEventEmitter."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import RunStatus
from orchestrator.api.deps import get_event_emitter, get_event_store_v2
from orchestrator.db import RunModel, create_engine, create_session_factory, init_db
from orchestrator.db import SqliteEventStore
from orchestrator.db import JsonlOutboxObserver
from orchestrator.db import commit_with_event_outbox
from orchestrator.workflow import PersistentEventEmitter
from orchestrator.workflow import RunStatusChanged

NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def jsonl_path(tmp_path: Path) -> Path:
    return tmp_path / "events_v2.jsonl"


def _event(run_id: str = "run-wiring-1") -> RunStatusChanged:
    return RunStatusChanged(
        timestamp=NOW,
        run_id=run_id,
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
    )


class _FakeConnectionManager:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def broadcast_event(self, event: object) -> None:
        self.events.append(event)


async def _insert_run(session: AsyncSession, run_id: str) -> None:
    session.add(
        RunModel(
            id=run_id,
            repo_name="proj-1",
            source_branch="main",
            status="draft",
            runner_config={},
            config={},
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()


async def test_emit_writes_events_v2_row(
    session: AsyncSession,
    jsonl_path: Path,
) -> None:
    store = SqliteEventStore(session)
    store.add_listener(JsonlOutboxObserver(jsonl_path))
    emitter = PersistentEventEmitter(store)

    await emitter.emit(_event("run-1"))

    rows = await store.get_stream("run-1")
    assert len(rows) == 1
    assert rows[0].event_type == "run_status_changed"
    assert rows[0].aggregate_id == "run-1"


async def test_get_event_emitter_writes_events_v2(
    session: AsyncSession,
) -> None:
    await _insert_run(session, "run-dep")
    store_v2 = await get_event_store_v2(session)
    manager = _FakeConnectionManager()
    emitter = await get_event_emitter(
        store_v2,
        manager,  # type: ignore[arg-type]
    )

    event = _event("run-dep")
    await emitter.emit(event)

    rows = await store_v2.get_stream("run-dep")
    assert len(rows) == 1
    assert rows[0].event_type == "run_status_changed"
    assert manager.events == [event]


async def test_notify_persisted_broadcasts_without_duplicate_append(
    session: AsyncSession,
) -> None:
    store = SqliteEventStore(session)
    emitter = PersistentEventEmitter(store)
    observed: list[object] = []
    emitter.add_listener(observed.append)

    event = _event("run-notify")
    await store.append([event])
    emitter.notify_persisted(event)

    rows = await store.get_stream("run-notify")
    assert len(rows) == 1
    assert observed == [event]


async def test_emit_writes_jsonl_line(
    session: AsyncSession,
    jsonl_path: Path,
) -> None:
    store = SqliteEventStore(session)
    store.add_listener(JsonlOutboxObserver(jsonl_path))
    emitter = PersistentEventEmitter(store)

    await emitter.emit(_event("run-2"))
    await commit_with_event_outbox(session)

    assert jsonl_path.exists()
    lines = jsonl_path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["aggregate_id"] == "run-2"
    assert record["event_type"] == "run_status_changed"
    assert "position" in record
    assert "payload" in record
    assert isinstance(record["payload"], dict)


async def test_emit_writes_both_events_v2_and_jsonl(
    session: AsyncSession,
    jsonl_path: Path,
) -> None:
    store = SqliteEventStore(session)
    observer = JsonlOutboxObserver(jsonl_path)
    store.add_listener(observer)
    emitter = PersistentEventEmitter(store)

    event = _event("run-dual")
    await emitter.emit(event)
    await commit_with_event_outbox(session)

    # events_v2 row
    rows = await store.get_stream("run-dual")
    assert len(rows) == 1
    db_position = rows[0].position

    # JSONL line
    lines = jsonl_path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["position"] == db_position
    assert record["aggregate_id"] == "run-dual"


async def test_emit_batch_writes_multiple_rows_and_jsonl_lines(
    session: AsyncSession,
    jsonl_path: Path,
) -> None:
    store = SqliteEventStore(session)
    store.add_listener(JsonlOutboxObserver(jsonl_path))
    emitter = PersistentEventEmitter(store)

    events = [_event("run-batch"), _event("run-batch"), _event("run-batch")]
    await emitter.emit_batch(events)
    await commit_with_event_outbox(session)

    rows = await store.get_stream("run-batch")
    assert len(rows) == 3

    lines = jsonl_path.read_text().splitlines()
    assert len(lines) == 3


async def test_jsonl_observer_restart_and_duplicate_post_commit_calls_are_idempotent(
    session: AsyncSession,
    jsonl_path: Path,
) -> None:
    store = SqliteEventStore(session)
    observer_a = JsonlOutboxObserver(jsonl_path)
    store.add_listener(observer_a)

    first_batch = await store.append([_event("run-restart"), _event("run-restart")])
    await commit_with_event_outbox(session)

    observer_b = JsonlOutboxObserver(jsonl_path)
    await observer_b(first_batch)

    store.add_listener(observer_b)
    second_batch = await store.append([_event("run-restart")])
    await commit_with_event_outbox(session)

    rows = await store.get_stream("run-restart")
    assert len(rows) == 3
    positions = [json.loads(line)["position"] for line in jsonl_path.read_text().splitlines()]
    assert positions == [event.position for event in first_batch + second_batch]
