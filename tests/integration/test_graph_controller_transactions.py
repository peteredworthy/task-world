from pathlib import Path

from sqlalchemy import event

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import FakeClock, SequentialIdGenerator
from orchestrator.graph_runtime import GraphController


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
