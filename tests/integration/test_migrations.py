from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from orchestrator.db import create_engine, init_db


def _alembic_config(database_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    return config


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


def test_migration_retires_historical_claude_sdk_relational_values(tmp_path: Path) -> None:
    database_path = tmp_path / "historical-runner.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "zf1g2h3i4j5k")

    event_payload = b'{"old_agent":"claude_sdk","note":"immutable"}'
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "INSERT INTO runs (id, repo_name, status, runner_type, runner_config, config, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-1", "repo", "draft", "claude_sdk", "{}", "{}", "2025-01-01", "2025-01-01"),
        )
        connection.execute(
            "INSERT INTO attempts (id, task_id, attempt_num, runner_type, agent_model, "
            "tokens_read, tokens_write, tokens_cache, duration_ms, num_actions) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("attempt-1", "task-1", 1, "claude_sdk", "legacy-model", 0, 0, 0, 0, 0),
        )
        connection.execute(
            "INSERT INTO cost_records (id, run_id, task_id, attempt_num, agent_runner_type, phase, "
            "mode_tag, model_name, input_tokens, output_tokens, cache_read_tokens, "
            "cache_write_tokens, wall_time_ms, cost_usd, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "cost-1",
                "run-1",
                "task-1",
                1,
                "claude_sdk",
                "builder",
                "default",
                "model",
                0,
                0,
                0,
                0,
                0,
                0,
                "2025-01-01",
            ),
        )
        connection.execute(
            "INSERT INTO interaction_log_artifacts (id, run_id, task_id, attempt_num, "
            "agent_runner_type, phase, artifact_kind, prompt_text, output_text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "artifact-1",
                "run-1",
                "task-1",
                1,
                "claude_sdk",
                "builder",
                "log",
                "prompt",
                "output",
                "2025-01-01",
            ),
        )
        connection.execute(
            "INSERT INTO agent_runner_model_profile_defaults (id, runner_type, profile, model) "
            "VALUES (?, ?, ?, ?)",
            ("default-sdk", "claude_sdk", "coder", "legacy-model"),
        )
        connection.execute(
            "INSERT INTO agent_runner_model_profile_defaults (id, runner_type, profile, model) "
            "VALUES (?, ?, ?, ?)",
            ("default-retired", "retired", "coder", "current-model"),
        )
        connection.execute(
            "INSERT INTO agent_runner_model_profile_defaults (id, runner_type, profile, model) "
            "VALUES (?, ?, ?, ?)",
            ("default-other", "cli_subprocess", "architect", "other-model"),
        )
        connection.execute(
            "INSERT INTO agent_runner_model_profile_defaults (id, runner_type, profile, model) "
            "VALUES (?, ?, ?, ?)",
            ("default-sdk-noncollision", "claude_sdk", "designer", "legacy-designer-model"),
        )
        connection.execute(
            "INSERT INTO events_v2 (aggregate_id, event_type, payload, timestamp, version) "
            "VALUES (?, ?, ?, ?, ?)",
            ("run-1", "agent_changed", event_payload, "2025-01-01T00:00:00Z", 1),
        )
        connection.commit()

        before_upgrade = {
            "run": connection.execute(
                "SELECT id, repo_name, status, runner_config, config, runner_type "
                "FROM runs WHERE id = 'run-1'"
            ).fetchone(),
            "attempt": connection.execute(
                "SELECT id, task_id, attempt_num, agent_model, runner_type "
                "FROM attempts WHERE id = 'attempt-1'"
            ).fetchone(),
            "cost": connection.execute(
                "SELECT id, run_id, task_id, attempt_num, phase, mode_tag, model_name, "
                "agent_runner_type FROM cost_records WHERE id = 'cost-1'"
            ).fetchone(),
            "artifact": connection.execute(
                "SELECT id, run_id, task_id, attempt_num, phase, artifact_kind, prompt_text, "
                "output_text, agent_runner_type FROM interaction_log_artifacts "
                "WHERE id = 'artifact-1'"
            ).fetchone(),
            "other_default": connection.execute(
                "SELECT id, runner_type, profile, model "
                "FROM agent_runner_model_profile_defaults WHERE id = 'default-other'"
            ).fetchone(),
            "noncolliding_historical_default": connection.execute(
                "SELECT id, runner_type, profile, model "
                "FROM agent_runner_model_profile_defaults WHERE id = 'default-sdk-noncollision'"
            ).fetchone(),
        }

    command.upgrade(config, "zg1h2i3j4k5l")

    with sqlite3.connect(database_path) as connection:
        run = connection.execute(
            "SELECT id, repo_name, status, runner_config, config, runner_type "
            "FROM runs WHERE id = 'run-1'"
        ).fetchone()
        attempt = connection.execute(
            "SELECT id, task_id, attempt_num, agent_model, runner_type "
            "FROM attempts WHERE id = 'attempt-1'"
        ).fetchone()
        cost = connection.execute(
            "SELECT id, run_id, task_id, attempt_num, phase, mode_tag, model_name, "
            "agent_runner_type FROM cost_records WHERE id = 'cost-1'"
        ).fetchone()
        artifact = connection.execute(
            "SELECT id, run_id, task_id, attempt_num, phase, artifact_kind, prompt_text, "
            "output_text, agent_runner_type FROM interaction_log_artifacts "
            "WHERE id = 'artifact-1'"
        ).fetchone()

        assert run is not None
        assert attempt is not None
        assert cost is not None
        assert artifact is not None
        assert run[:-1] == before_upgrade["run"][:-1]
        assert attempt[:-1] == before_upgrade["attempt"][:-1]
        assert cost[:-1] == before_upgrade["cost"][:-1]
        assert artifact[:-1] == before_upgrade["artifact"][:-1]
        assert run[-1] == attempt[-1] == cost[-1] == artifact[-1] == "retired"
        assert connection.execute(
            "SELECT id, runner_type, profile, model FROM agent_runner_model_profile_defaults "
            "ORDER BY id"
        ).fetchall() == [
            ("default-other", "cli_subprocess", "architect", "other-model"),
            ("default-retired", "retired", "coder", "current-model"),
            ("default-sdk-noncollision", "retired", "designer", "legacy-designer-model"),
        ]
        assert (
            connection.execute(
                "SELECT id, runner_type, profile, model FROM agent_runner_model_profile_defaults "
                "WHERE id = 'default-other'"
            ).fetchone()
            == before_upgrade["other_default"]
        )
        noncolliding_historical_default = connection.execute(
            "SELECT id, runner_type, profile, model FROM agent_runner_model_profile_defaults "
            "WHERE id = 'default-sdk-noncollision'"
        ).fetchone()
        assert noncolliding_historical_default is not None
        assert (
            noncolliding_historical_default[0]
            == before_upgrade["noncolliding_historical_default"][0]
        )
        assert noncolliding_historical_default[1] == "retired"
        assert (
            noncolliding_historical_default[2:]
            == before_upgrade["noncolliding_historical_default"][2:]
        )
        assert connection.execute("SELECT payload FROM events_v2").fetchone() == (event_payload,)
