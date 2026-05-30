"""Unit tests for JsonlOutboxObserver."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import RunStatus
from orchestrator.db import (
    JsonlOutboxObserver,
    SqliteEventStore,
    StoredEvent,
    commit_with_event_outbox,
    create_engine,
    create_session_factory,
    init_db,
    rollback_with_event_outbox,
)
from orchestrator.workflow import RunStatusChanged

NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


def _stored(position: int, aggregate_id: str = "run-1") -> StoredEvent:
    return StoredEvent(
        position=position,
        aggregate_id=aggregate_id,
        event_type="run_status_changed",
        payload='{"run_id": "run-1", "event_type": "run_status_changed"}',
        timestamp="2025-01-15T10:30:00+00:00",
        version=1,
    )


def _event(run_id: str = "run-1") -> RunStatusChanged:
    return RunStatusChanged(
        timestamp=NOW,
        run_id=run_id,
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
    )


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_write_event_to_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    observer = JsonlOutboxObserver(path)
    event = _stored(position=1)

    await observer([event])

    lines = path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["position"] == 1
    assert record["aggregate_id"] == "run-1"
    assert record["event_type"] == "run_status_changed"
    assert "timestamp" in record
    assert "payload" in record


async def test_idempotent_same_position(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    observer = JsonlOutboxObserver(path)
    event = _stored(position=5)

    await observer([event])
    await observer([event])

    lines = path.read_text().splitlines()
    assert len(lines) == 1


async def test_idempotent_across_observer_restart(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    observer_a = JsonlOutboxObserver(path)
    await observer_a([_stored(1), _stored(2)])

    observer_b = JsonlOutboxObserver(path)
    await observer_b([_stored(1), _stored(2), _stored(3)])

    lines = path.read_text().splitlines()
    positions = [json.loads(line)["position"] for line in lines]
    assert positions == [1, 2, 3]


async def test_preexisting_malformed_lines_are_ignored_for_position_discovery(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "position": 1,
                        "aggregate_id": "run-1",
                        "event_type": "run_status_changed",
                        "timestamp": "2025-01-15T10:30:00+00:00",
                        "payload": {"run_id": "run-1"},
                    }
                ),
                "{malformed json",
                json.dumps(["not", "an", "object"]),
                json.dumps({"position": "2"}),
            ]
        )
        + "\n"
    )
    observer = JsonlOutboxObserver(path)

    await observer([_stored(1), _stored(2)])

    valid_records = [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.startswith("{") and "malformed" not in line
    ]
    positions = [record.get("position") for record in valid_records if record.get("position")]
    assert positions == [1, "2", 2]


async def test_boolean_positions_do_not_suppress_integer_positions(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"position": True}),
                json.dumps({"position": False}),
            ]
        )
        + "\n"
    )
    observer = JsonlOutboxObserver(path)

    await observer([_stored(0), _stored(1)])

    records = [json.loads(line) for line in path.read_text().splitlines()]
    positions = [record["position"] for record in records]
    assert positions == [True, False, 0, 1]


async def test_duplicate_events_within_same_call_are_written_once(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    observer = JsonlOutboxObserver(path)

    await observer([_stored(1), _stored(1), _stored(2), _stored(2)])

    lines = path.read_text().splitlines()
    positions = [json.loads(line)["position"] for line in lines]
    assert positions == [1, 2]


async def test_multiple_events_written(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    observer = JsonlOutboxObserver(path)
    events = [_stored(1), _stored(2), _stored(3)]

    await observer(events)

    lines = path.read_text().splitlines()
    assert len(lines) == 3
    positions = [json.loads(line)["position"] for line in lines]
    assert positions == [1, 2, 3]


async def test_write_failure_propagates(tmp_path: Path) -> None:
    # Place a regular file where the observer expects a directory, causing mkdir to fail.
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("i am a file, not a directory")
    path = blocker / "events.jsonl"
    observer = JsonlOutboxObserver(path)
    with pytest.raises(OSError):
        await observer([_stored(1)])
    assert not path.exists()


async def test_partial_idempotency_skips_already_written(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    observer = JsonlOutboxObserver(path)

    await observer([_stored(1), _stored(2)])
    # Re-submit position 1, add new position 3
    await observer([_stored(1), _stored(3)])

    lines = path.read_text().splitlines()
    assert len(lines) == 3
    positions = {json.loads(line)["position"] for line in lines}
    assert positions == {1, 2, 3}


async def test_payload_is_parsed_json(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    observer = JsonlOutboxObserver(path)
    event = _stored(1)

    await observer([event])

    record = json.loads(path.read_text().splitlines()[0])
    assert isinstance(record["payload"], dict)
    assert record["payload"]["event_type"] == "run_status_changed"


async def test_append_without_commit_does_not_write_jsonl(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    store = SqliteEventStore(session)
    store.add_listener(JsonlOutboxObserver(path))

    await store.append([_event("run-no-commit")])

    assert not path.exists()


async def test_append_then_rollback_does_not_write_jsonl(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    store = SqliteEventStore(session)
    store.add_listener(JsonlOutboxObserver(path))

    await store.append([_event("run-rollback")])
    await rollback_with_event_outbox(session)

    assert not path.exists()


async def test_projection_failure_does_not_write_jsonl(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    store = SqliteEventStore(session)
    store.add_listener(JsonlOutboxObserver(path))

    async def failing_projection(*_args: object) -> None:
        raise RuntimeError("projection failed")

    store.add_projection_listener(failing_projection)

    with pytest.raises(RuntimeError, match="projection failed"):
        await store.append([_event("run-projection-fail")])

    assert not path.exists()
    await rollback_with_event_outbox(session)


async def test_commit_helper_writes_exact_committed_positions(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    store = SqliteEventStore(session)
    store.add_listener(JsonlOutboxObserver(path))

    stored = await store.append([_event("run-commit"), _event("run-commit")])
    await commit_with_event_outbox(session)

    lines = path.read_text().splitlines()
    positions = [json.loads(line)["position"] for line in lines]
    assert positions == [event.position for event in stored]
