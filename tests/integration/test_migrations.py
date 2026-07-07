from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect

from orchestrator.db import create_engine, init_db


@pytest.mark.asyncio
async def test_init_db_adds_execution_mode_column(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "migrations.db")
    try:
        await init_db(engine)

        async with engine.connect() as conn:
            columns = await conn.run_sync(
                lambda sync_conn: {
                    column["name"] for column in inspect(sync_conn).get_columns("runs")
                }
            )

        assert "execution_mode" in columns
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_adds_graph_outbox_backoff_schema(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "outbox-backoff-migrations.db")
    try:
        await init_db(engine)

        async with engine.connect() as conn:
            columns = await conn.run_sync(
                lambda sync_conn: {
                    column["name"] for column in inspect(sync_conn).get_columns("graph_outbox")
                }
            )
            indexes = await conn.run_sync(
                lambda sync_conn: {
                    index["name"] for index in inspect(sync_conn).get_indexes("graph_outbox")
                }
            )

        assert "next_attempt_at" in columns
        assert "idx_graph_outbox_status_next_attempt_id" in indexes
    finally:
        await engine.dispose()
