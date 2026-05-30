"""Unit tests for SqliteEventStore and StoredEvent using real in-memory SQLite."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.db import (
    ConcurrencyConflictError,
    RetryWithBackoff,
    SqliteEventStore,
    StoredEvent,
    commit_with_event_outbox,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.workflow import RunStatusChanged, TaskStatusChanged

NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


def _run_event(run_id: str = "run-1") -> RunStatusChanged:
    return RunStatusChanged(
        timestamp=NOW,
        run_id=run_id,
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
    )


def _task_event(run_id: str = "run-1", task_id: str = "task-1") -> TaskStatusChanged:
    return TaskStatusChanged(
        timestamp=NOW,
        run_id=run_id,
        event_type="task_status_changed",
        task_id=task_id,
        old_status=TaskStatus.PENDING,
        new_status=TaskStatus.BUILDING,
    )


@pytest.fixture
async def async_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_append_and_get_stream(async_session: AsyncSession) -> None:
    store = SqliteEventStore(async_session)
    event1 = _run_event("run-1")
    event2 = _task_event("run-1", "task-1")

    await store.append([event1, event2])

    results = await store.get_stream("run-1")
    assert len(results) == 2
    assert results[0].event_type == "run_status_changed"
    assert results[1].event_type == "task_status_changed"
    # positions are ascending
    assert results[0].position < results[1].position


async def test_get_all_after_position(async_session: AsyncSession) -> None:
    store = SqliteEventStore(async_session)
    # Append 3 events for run-1 and 2 for run-2
    await store.append([_run_event("run-1")])
    await store.append([_run_event("run-2")])
    await store.append([_task_event("run-1")])
    await store.append([_run_event("run-1")])
    await store.append([_run_event("run-2")])

    all_events = await store.get_all(after_position=0)
    assert len(all_events) == 5

    # after_position=3 → only events 4 and 5
    later = await store.get_all(after_position=3)
    assert len(later) == 2
    for e in later:
        assert e.position > 3


async def test_version_auto_increments(async_session: AsyncSession) -> None:
    store = SqliteEventStore(async_session)

    await store.append([_run_event("agg-1")])
    await store.append([_run_event("agg-1")])
    await store.append([_run_event("agg-1")])

    events = await store.get_stream("agg-1")
    assert len(events) == 3
    assert events[0].version == 1
    assert events[1].version == 2
    assert events[2].version == 3


async def test_version_conflict_raises_concurrency_error(async_session: AsyncSession) -> None:
    """Injecting a strategy that always conflicts causes ConcurrencyConflictError."""

    class AlwaysConflictStrategy(RetryWithBackoff):
        """Raises a UNIQUE constraint error on every execute_with_retry call."""

        async def execute_with_retry(self, operation: Any) -> Any:
            raise ConcurrencyConflictError(
                "UNIQUE constraint failed: events_v2.aggregate_id, uq_events_v2"
            )

    store = SqliteEventStore(async_session, concurrency=AlwaysConflictStrategy(max_attempts=1))

    with pytest.raises(ConcurrencyConflictError):
        await store.append([_run_event("agg-conflict")])


async def test_listener_called_after_commit(async_session: AsyncSession) -> None:
    store = SqliteEventStore(async_session)
    received: list[list[StoredEvent]] = []

    async def on_append(events: list[StoredEvent]) -> None:
        received.append(events)

    store.add_listener(on_append)

    await store.append([_run_event("run-1")])
    assert received == []
    await commit_with_event_outbox(async_session)

    assert len(received) == 1
    assert len(received[0]) == 1
    assert received[0][0].aggregate_id == "run-1"
    assert isinstance(received[0][0], StoredEvent)


async def test_get_stream_returns_empty_for_unknown_aggregate(async_session: AsyncSession) -> None:
    store = SqliteEventStore(async_session)
    results = await store.get_stream("nonexistent-aggregate")
    assert results == []


async def test_get_all_returns_all_events_in_order(async_session: AsyncSession) -> None:
    store = SqliteEventStore(async_session)

    await store.append([_run_event("run-a")])
    await store.append([_run_event("run-b")])
    await store.append([_run_event("run-a")])

    all_events = await store.get_all()
    assert len(all_events) == 3
    positions = [e.position for e in all_events]
    assert positions == sorted(positions)


async def test_get_events_paginated_uses_position_cursor_and_parses_payload(
    async_session: AsyncSession,
) -> None:
    store = SqliteEventStore(async_session)
    await store.append([_run_event("run-1")])
    await store.append([_run_event("run-2")])
    await store.append([_task_event("run-1", "task-1")])

    page = await store.get_events_paginated("run-1", limit=1)

    assert len(page) == 1
    assert page[0]["id"] == 1
    assert page[0]["event_type"] == "run_status_changed"
    assert page[0]["payload"]["run_id"] == "run-1"
    assert page[0]["payload"]["old_status"] == "draft"

    next_page = await store.get_events_paginated("run-1", after=page[0]["id"], limit=10)
    assert [row["id"] for row in next_page] == [3]
    assert next_page[0]["payload"]["task_id"] == "task-1"


async def test_get_events_paginated_filters_by_event_type(
    async_session: AsyncSession,
) -> None:
    store = SqliteEventStore(async_session)
    await store.append([_run_event("run-1"), _task_event("run-1", "task-1")])

    rows = await store.get_events_paginated("run-1", event_type="task_status_changed")

    assert len(rows) == 1
    assert rows[0]["event_type"] == "task_status_changed"
    assert rows[0]["payload"]["task_id"] == "task-1"


async def test_versions_are_independent_per_aggregate(async_session: AsyncSession) -> None:
    """Different aggregates track their own versions independently."""
    store = SqliteEventStore(async_session)

    await store.append([_run_event("agg-x")])
    await store.append([_run_event("agg-y")])
    await store.append([_run_event("agg-x")])

    x_events = await store.get_stream("agg-x")
    y_events = await store.get_stream("agg-y")

    assert x_events[0].version == 1
    assert x_events[1].version == 2
    assert y_events[0].version == 1


async def test_stored_event_is_frozen(async_session: AsyncSession) -> None:
    """StoredEvent is immutable (frozen dataclass)."""
    store = SqliteEventStore(async_session)
    stored = await store.append([_run_event("run-1")])

    event = stored[0]
    with pytest.raises((AttributeError, TypeError)):
        event.position = 999  # type: ignore[misc]
