from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import event

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock, SequentialIdGenerator
from orchestrator.graph_runtime import GraphController, StaleProjectionError
from orchestrator.graph_runtime.store import graph_aggregate_id
from orchestrator.graph import build_graph_catalog, future_command_effects


async def test_graph_controller_write_commands_begin_immediate(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "graph-controller.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _record_statement(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement)

    controller = GraphController(
        session_factory,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
        catalog=build_graph_catalog(),
        future_effects=future_command_effects(),
    )

    await controller.handle_command("run-begin-immediate", 0, "accept_run")
    await engine.dispose()

    assert "BEGIN IMMEDIATE" in [statement.upper() for statement in statements]


async def test_graph_controller_reads_run_before_taking_write_lock(tmp_path: Path) -> None:
    """The expensive read + projection rebuild must happen before BEGIN IMMEDIATE.

    Regression guard for the write-lock-hold-time incident: if ``read_run``
    (the full event-log read) is ever moved back inside the write
    transaction, this test fails because BEGIN IMMEDIATE will have already
    been issued by the time ``read_run`` runs.
    """
    engine = create_engine(tmp_path / "graph-controller-read-before-lock.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _record_statement(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement.upper())

    controller = GraphController(
        session_factory,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
        catalog=build_graph_catalog(),
        future_effects=future_command_effects(),
    )
    await controller.handle_command("run-read-before-lock", 0, "accept_run")
    await engine.dispose()

    begin_index = statements.index("BEGIN IMMEDIATE")
    pre_read_indexes = [
        index
        for index, statement in enumerate(statements)
        if statement.startswith("SELECT")
        and ("EVENTS_V2" in statement or "GRAPH_PROJECTION_SNAPSHOTS" in statement)
    ]
    assert pre_read_indexes
    assert min(pre_read_indexes) < begin_index


async def test_handle_command_raises_stale_projection_error_when_position_moves_before_write(
    tmp_path: Path,
) -> None:
    """A concurrent writer landing between the pre-read and the write txn must
    surface as StaleProjectionError, not silently overwrite/duplicate events.

    Simulates the race by appending a durable event via a second store/session
    right after this controller's pre-read returns, but before its own write
    transaction opens. The controller's cheap position re-check inside
    BEGIN IMMEDIATE must catch that the head moved.
    """
    db_path = tmp_path / "graph-controller-race.db"
    engine = create_engine(db_path)
    await init_db(engine)
    session_factory = create_session_factory(engine)
    clock = FakeClock()
    id_gen = SequentialIdGenerator()
    run_id = "run-race"

    controller = GraphController(
        session_factory,
        clock,
        id_gen,
        auto_dispatch=False,
        catalog=build_graph_catalog(),
        future_effects=future_command_effects(),
    )
    seeded = await controller.handle_command(run_id, 0, "accept_run")
    position = seeded.projection_position

    injected = {"done": False}

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _inject_race_before_write_lock(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if injected["done"] or statement.upper() != "BEGIN IMMEDIATE":
            return
        injected["done"] = True
        event = EventEnvelope(
            event_id="racer-event",
            run_id=run_id,
            position=position + 1,
            event_type="lease_renewed",
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=clock.now(),
            payload={},
        )
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                """
                INSERT INTO events_v2 (aggregate_id, version, event_type, payload, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    graph_aggregate_id(run_id),
                    position + 1,
                    event.event_type,
                    event.model_dump_json(),
                    event.timestamp.isoformat(),
                ),
            )
            connection.commit()

    with pytest.raises(StaleProjectionError):
        await controller.handle_command(run_id, position, "start")

    await engine.dispose()
