"""Journal segment replay integration coverage using real SQLite and files."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import load_routine_from_path
from orchestrator.db import (
    ProjectionRegistry,
    bootstrap_from_jsonl,
    commit_with_event_outbox,
    create_backup,
    create_engine,
    create_session_factory,
    init_db,
    scan_max_sequence,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock, SequentialIdGenerator
from orchestrator.graph_runtime import GraphController, GraphEventStore, seed_run


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


async def test_backup_scans_archives_when_the_active_journal_is_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    db_path.write_text("sqlite placeholder")
    journal = tmp_path / "history.jsonl"
    (tmp_path / "history.40-42.jsonl").write_text(json.dumps({"position": 42}) + "\n")

    metadata = await create_backup(db_path, tmp_path / "backups", journal)

    assert metadata.journal_sequence_marker == 42


async def test_bootstrap_skips_structurally_malformed_json_records(
    session: AsyncSession, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    active = tmp_path / "history.jsonl"
    active.write_text(
        "\n".join(
            [
                json.dumps(["not", "a record"]),
                json.dumps(
                    {"position": "bad", "aggregate_id": 2, "event_type": [], "timestamp": 3}
                ),
                json.dumps(_record(4)),
            ]
        )
        + "\n"
    )

    await bootstrap_from_jsonl(session, active, ProjectionRegistry())

    assert (await session.execute(text("SELECT position FROM events_v2"))).scalars().all() == [4]
    assert "skipping malformed journal record" in caplog.text


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


async def test_graph_controller_rotates_at_its_injected_journal_limit(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "orchestrator.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    try:
        await seed_run(
            session_factory,
            load_routine_from_path(Path("routines/demo-task.yaml")),
            run_id="journal-limit-run",
            clock=clock,
            id_gen=ids,
            journal_max_bytes=1,
        )
        controller = GraphController(
            session_factory,
            clock,
            ids,
            auto_dispatch=False,
            journal_max_bytes=1,
        )
        position = await controller.current_position("journal-limit-run")

        await controller.handle_command("journal-limit-run", position, "accept_run")

        journal_dir = tmp_path / ".orchestrator" / "state"
        assert list(journal_dir.glob("history.*-*.jsonl"))
    finally:
        await engine.dispose()
