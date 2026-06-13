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
