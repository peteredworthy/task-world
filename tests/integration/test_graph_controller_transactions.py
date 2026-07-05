from pathlib import Path

import pytest
from sqlalchemy import event

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock, SequentialIdGenerator
from orchestrator.graph_runtime import GraphController, StaleProjectionError
from orchestrator.graph_runtime.store import GraphEventStore


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
    )

    await controller.handle_command("run-begin-immediate", 0, "accept_run")
    await engine.dispose()

    assert "BEGIN IMMEDIATE" in [statement.upper() for statement in statements]


async def test_graph_controller_reads_run_before_taking_write_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    read_run_called_at: list[int] = []
    real_read_run = GraphEventStore.read_run

    async def _tracking_read_run(
        self: GraphEventStore,
        run_id: str,
        from_position: int = 0,
    ) -> list[EventEnvelope]:
        read_run_called_at.append(
            sum(1 for statement in statements if "BEGIN IMMEDIATE" in statement)
        )
        return await real_read_run(self, run_id, from_position)

    monkeypatch.setattr(GraphEventStore, "read_run", _tracking_read_run)

    controller = GraphController(
        session_factory,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    await controller.handle_command("run-read-before-lock", 0, "accept_run")
    await engine.dispose()

    assert read_run_called_at == [0]
    assert "BEGIN IMMEDIATE" in statements


async def test_handle_command_raises_stale_projection_error_when_position_moves_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent writer landing between the pre-read and the write txn must
    surface as StaleProjectionError, not silently overwrite/duplicate events.

    Simulates the race by appending a durable event via a second store/session
    right after this controller's pre-read returns, but before its own write
    transaction opens. The controller's cheap position re-check inside
    BEGIN IMMEDIATE must catch that the head moved.
    """
    engine = create_engine(tmp_path / "graph-controller-race.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    clock = FakeClock()
    id_gen = SequentialIdGenerator()
    run_id = "run-race"

    controller = GraphController(session_factory, clock, id_gen, auto_dispatch=False)
    seeded = await controller.handle_command(run_id, 0, "accept_run")
    position = seeded.projection_position

    real_read_run = GraphEventStore.read_run
    injected = {"done": False}

    async def _read_run_then_race(
        self: GraphEventStore,
        target_run_id: str,
        from_position: int = 0,
    ) -> list[EventEnvelope]:
        events = await real_read_run(self, target_run_id, from_position)
        if not injected["done"] and target_run_id == run_id:
            injected["done"] = True
            async with session_factory() as racer_session:
                racer_store = GraphEventStore(racer_session)
                await racer_store.append_events(
                    run_id,
                    position,
                    [
                        EventEnvelope(
                            event_id="racer-event",
                            run_id=run_id,
                            position=-1,
                            event_type="lease_renewed",
                            schema_version=1,
                            actor=Actor(kind=ActorKind.CONTROLLER),
                            timestamp=clock.now(),
                            payload={},
                        )
                    ],
                )
                await racer_session.commit()
        return events

    monkeypatch.setattr(GraphEventStore, "read_run", _read_run_then_race)

    with pytest.raises(StaleProjectionError):
        await controller.handle_command(run_id, position, "start")

    await engine.dispose()
