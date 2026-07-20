"""Journal segment replay integration coverage using real SQLite and files."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import (
    ProjectionRegistry,
    bootstrap_from_jsonl,
    commit_with_event_outbox,
    create_engine,
    create_session_factory,
    init_db,
    scan_max_sequence,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as active_session:
        yield active_session
    await engine.dispose()


def _record(position: int) -> dict[str, object]:
    return {
        "position": position,
        "aggregate_id": f"run-{position}",
        "event_type": "unknown_replay_event",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "payload": {"run_id": f"run-{position}", "event_type": "unknown_replay_event"},
    }


async def test_bootstrap_replays_archives_and_active_in_global_position_order(
    session: AsyncSession, tmp_path: Path
) -> None:
    active = tmp_path / "history.jsonl"
    (tmp_path / "history.1-2.jsonl").write_text(
        "\n".join(json.dumps(_record(position)) for position in [2, 1]) + "\n"
    )
    (tmp_path / "history.3-3.jsonl").write_text(json.dumps(_record(3)) + "\n")
    active.write_text(json.dumps(_record(3)) + "\n" + json.dumps(_record(4)) + "\n{broken")

    await bootstrap_from_jsonl(session, active, ProjectionRegistry())

    positions = (
        (await session.execute(text("SELECT position FROM events_v2 ORDER BY position")))
        .scalars()
        .all()
    )
    assert positions == [1, 2, 3, 4]


def test_backup_scans_all_archives_and_active_for_maximum_position(tmp_path: Path) -> None:
    active = tmp_path / "history.jsonl"
    (tmp_path / "history.8-9.jsonl").write_text(json.dumps({"sequence_number": 9}) + "\n")
    (tmp_path / "history.10-12.jsonl").write_text(json.dumps({"position": 12}) + "\n")
    active.write_text(json.dumps({"sequence_number": 10}) + "\n")

    assert scan_max_sequence(active) == 12


async def test_graph_events_reach_the_committed_jsonl_journal(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)
    event = EventEnvelope(
        event_id="graph-journal-event",
        run_id="graph-journal-run",
        position=-1,
        event_type="run_lifecycle_changed",
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        causation_id="test",
        timestamp="2025-01-01T00:00:00+00:00",
        payload={
            "command_type": "start_run",
            "from_state": "draft",
            "to_state": "active",
            "trigger": "test",
        },
    )
    async with factory() as active_session:
        await GraphEventStore(active_session).append_events(event.run_id, 0, [event])
        await commit_with_event_outbox(active_session)

    journal = tmp_path / ".orchestrator" / "state" / "history.jsonl"
    assert [json.loads(line)["event_type"] for line in journal.read_text().splitlines()] == [
        "run_lifecycle_changed"
    ]
    await engine.dispose()
