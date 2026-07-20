from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from orchestrator.db import (
    AttemptModel,
    ProjectionRegistry,
    RunModel,
    RunStateProjector,
    SqliteEventStore,
    TaskStateProjector,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.workflow import deserialize_event


def _alembic_config(database_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    return config


def _legacy_usage_snapshot(value: Any) -> Any:
    """Mark an intentional pre-cutover fixture value for the vocabulary guard."""
    return value


def _legacy_event_payload(value: Any) -> Any:
    """Mark intentional historical event payloads and SQL for the vocabulary guard."""
    return value


async def _replay_migrated_usage_events(
    database_path: Path,
    expected_usage: dict[str, Any],
) -> None:
    engine = create_engine(database_path)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            stored_events = await SqliteEventStore(session).get_stream("usage-run")
            workflow_events = [
                deserialize_event(event.event_type, event.payload) for event in stored_events
            ]
            await session.execute(text("DELETE FROM attempts"))
            await session.execute(text("DELETE FROM tasks"))
            await session.execute(text("DELETE FROM steps"))
            await session.execute(text("DELETE FROM runs"))
            registry = ProjectionRegistry()
            registry.register(RunStateProjector())
            registry.register(TaskStateProjector())
            await registry.rebuild_all(workflow_events, session)
            await session.commit()

            replayed_run = await session.get(RunModel, "usage-run")
            replayed_attempt = await session.get(AttemptModel, "usage-attempt")
            assert replayed_run is not None
            assert replayed_attempt is not None
            assert replayed_run.token_usage_by_model == [expected_usage, expected_usage]
            assert replayed_attempt.token_usage_by_model == [expected_usage, expected_usage]
    finally:
        await engine.dispose()


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


def test_otel_usage_cutover_migrates_persisted_usage_facts_and_event_snapshots(
    tmp_path: Path,
) -> None:
    """The cutover retains every legacy usage value while changing its vocabulary."""
    database_path = tmp_path / "otel-usage-cutover.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "zg1h2i3j4k5l")

    legacy_usage = _legacy_usage_snapshot(
        {
            "model": "legacy-model",
            "input_tokens": 11,
            "output_tokens": 13,
            "cache_read_tokens": 17,
            "cache_creation_tokens": 19,
            "tokens_reasoning": 23,
            "total_cost_usd": 2.5,
            "provider_raw_key": "leave-me-alone",
        }
    )
    event_payload = _legacy_event_payload(
        {
            "run_id": "usage-run",
            "event_type": "run_created",
            "repo_name": "repo",
            "status": "draft",
            "token_usage_by_model": [legacy_usage],
            "telemetry": {"token_usage_by_model": [legacy_usage]},
            "run_snapshot": {
                "token_usage_by_model": [legacy_usage],
                "steps": [
                    {
                        "id": "snapshot-step",
                        "tasks": [
                            {
                                "id": "usage-task",
                                "attempts": [
                                    {
                                        "id": "usage-attempt",
                                        "attempt_num": 1,
                                        "token_usage_by_model": [legacy_usage],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            "attempt_snapshot": {"token_usage_by_model": [legacy_usage]},
            "provider_wire": {"model": "wire-model", "input_tokens": 999, "output_tokens": 888},
        }
    )
    attempt_updated_payload = _legacy_event_payload(
        {
            "run_id": "usage-run",
            "event_type": "attempt_updated",
            "task_id": "usage-task",
            "attempt_id": "usage-attempt",
            "token_usage_by_model": [legacy_usage],
        }
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            _legacy_event_payload(
                "INSERT INTO runs (id, repo_name, status, runner_config, config, created_at, updated_at, "
                "total_tokens_read, total_tokens_write, total_tokens_cache, total_duration_ms, "
                "total_num_actions, token_usage_by_model) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                "usage-run",
                "repo",
                "draft",
                "{}",
                "{}",
                "2025-01-01",
                "2025-01-01",
                11,
                13,
                17,
                29,
                31,
                json.dumps([legacy_usage]),
            ),
        )
        connection.execute(
            _legacy_event_payload(
                "INSERT INTO attempts (id, task_id, attempt_num, tokens_read, tokens_write, tokens_cache, "
                "duration_ms, num_actions, token_usage_by_model) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            ("usage-attempt", "usage-task", 1, 11, 13, 17, 29, 31, json.dumps([legacy_usage])),
        )
        connection.execute(
            _legacy_event_payload(
                "INSERT INTO cost_records (id, run_id, task_id, attempt_num, agent_runner_type, phase, "
                "mode_tag, model_name, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
                "wall_time_ms, cost_usd, token_usage_by_model, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                "usage-cost",
                "usage-run",
                "usage-task",
                1,
                "cli_subprocess",
                "builder",
                "default",
                "legacy-model",
                11,
                13,
                17,
                19,
                29,
                2.5,
                json.dumps([legacy_usage]),
                "2025-01-01",
            ),
        )
        connection.execute(
            "INSERT INTO events_v2 (aggregate_id, event_type, payload, timestamp, version) "
            "VALUES (?, ?, ?, ?, ?)",
            ("usage-run", "run_created", json.dumps(event_payload), "2025-01-01T00:00:00Z", 1),
        )
        connection.execute(
            "INSERT INTO events_v2 (aggregate_id, event_type, payload, timestamp, version) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "usage-run",
                "attempt_updated",
                json.dumps(attempt_updated_payload),
                "2025-01-01T00:00:01Z",
                2,
            ),
        )
        connection.commit()

    command.upgrade(config, "r04a1b2c3d4e")

    expected_usage = {
        "model": "legacy-model",
        "gen_ai_usage_input_tokens": 47,
        "gen_ai_usage_output_tokens": 13,
        "gen_ai_usage_cache_read_input_tokens": 17,
        "gen_ai_usage_cache_creation_input_tokens": 19,
        "gen_ai_usage_reasoning_output_tokens": 23,
        "cost_usd": 2.5,
        "provider_raw_key": "leave-me-alone",
    }
    with sqlite3.connect(database_path) as connection:
        run_columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        attempt_columns = {row[1] for row in connection.execute("PRAGMA table_info(attempts)")}
        cost_columns = {row[1] for row in connection.execute("PRAGMA table_info(cost_records)")}
        assert {"total_tokens_read", "total_tokens_write", "total_tokens_cache"}.isdisjoint(
            run_columns
        )
        assert _legacy_event_payload({"tokens_read", "tokens_write", "tokens_cache"}).isdisjoint(
            attempt_columns
        )
        assert {
            "gen_ai_usage_input_tokens",
            "gen_ai_usage_output_tokens",
            "gen_ai_usage_cache_read_input_tokens",
            "gen_ai_usage_cache_creation_input_tokens",
        }.issubset(cost_columns)
        assert json.loads(
            connection.execute("SELECT token_usage_by_model FROM runs").fetchone()[0]
        ) == [expected_usage]
        assert json.loads(
            connection.execute("SELECT token_usage_by_model FROM attempts").fetchone()[0]
        ) == [expected_usage]
        assert json.loads(
            connection.execute("SELECT token_usage_by_model FROM cost_records").fetchone()[0]
        ) == [expected_usage]
        payload = json.loads(connection.execute("SELECT payload FROM events_v2").fetchone()[0])
        assert payload["token_usage_by_model"] == [expected_usage]
        assert payload["telemetry"]["token_usage_by_model"] == [expected_usage]
        assert payload["run_snapshot"]["token_usage_by_model"] == [expected_usage]
        assert payload["run_snapshot"]["steps"][0]["tasks"][0]["attempts"][0][
            "token_usage_by_model"
        ] == [expected_usage]
        assert payload["attempt_snapshot"]["token_usage_by_model"] == [expected_usage]
        assert payload["provider_wire"] == _legacy_event_payload(
            {
                "model": "wire-model",
                "input_tokens": 999,
                "output_tokens": 888,
            }
        )
        assert connection.execute(
            "SELECT gen_ai_usage_input_tokens, gen_ai_usage_output_tokens, "
            "gen_ai_usage_cache_read_input_tokens, gen_ai_usage_cache_creation_input_tokens "
            "FROM cost_records"
        ).fetchone() == (47, 13, 17, 19)
        attempt_updated = json.loads(
            connection.execute(
                "SELECT payload FROM events_v2 WHERE event_type = 'attempt_updated'"
            ).fetchone()[0]
        )
        assert attempt_updated["token_usage_by_model"] == [expected_usage]

    asyncio.run(_replay_migrated_usage_events(database_path, expected_usage))

    command.downgrade(config, "zg1h2i3j4k5l")
    with sqlite3.connect(database_path) as connection:
        run_columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        attempt_columns = {row[1] for row in connection.execute("PRAGMA table_info(attempts)")}
        cost_columns = {row[1] for row in connection.execute("PRAGMA table_info(cost_records)")}
        assert {"total_tokens_read", "total_tokens_write", "total_tokens_cache"}.issubset(
            run_columns
        )
        assert _legacy_event_payload({"tokens_read", "tokens_write", "tokens_cache"}).issubset(
            attempt_columns
        )
        assert _legacy_event_payload(
            {"input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"}
        ).issubset(cost_columns)
        assert {
            "gen_ai_usage_input_tokens",
            "gen_ai_usage_output_tokens",
            "gen_ai_usage_cache_read_input_tokens",
            "gen_ai_usage_cache_creation_input_tokens",
        }.isdisjoint(cost_columns)
        assert connection.execute(
            _legacy_event_payload(
                "SELECT total_tokens_read, total_tokens_write, total_tokens_cache, "
                "total_duration_ms, total_num_actions FROM runs"
            )
        ).fetchone() == (22, 26, 72, 0, 0)
        assert connection.execute(
            _legacy_event_payload(
                "SELECT tokens_read, tokens_write, tokens_cache, duration_ms, num_actions FROM attempts"
            )
        ).fetchone() == (22, 26, 72, 0, 0)
        assert json.loads(
            connection.execute("SELECT token_usage_by_model FROM runs").fetchone()[0]
        ) == [legacy_usage, legacy_usage]
        assert json.loads(
            connection.execute("SELECT token_usage_by_model FROM attempts").fetchone()[0]
        ) == [legacy_usage, legacy_usage]
        assert json.loads(
            connection.execute("SELECT token_usage_by_model FROM cost_records").fetchone()[0]
        ) == [legacy_usage]
        assert connection.execute(
            _legacy_event_payload(
                "SELECT input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
                "wall_time_ms, cost_usd FROM cost_records"
            )
        ).fetchone() == (11, 13, 17, 19, 29, 2.5)
        payloads = {
            event_type: json.loads(payload)
            for event_type, payload in connection.execute(
                "SELECT event_type, payload FROM events_v2 ORDER BY version"
            )
        }
        run_created = payloads["run_created"]
        assert run_created["token_usage_by_model"] == [legacy_usage]
        assert run_created["telemetry"]["token_usage_by_model"] == [legacy_usage]
        assert run_created["run_snapshot"]["token_usage_by_model"] == [legacy_usage]
        assert run_created["run_snapshot"]["steps"][0]["tasks"][0]["attempts"][0][
            "token_usage_by_model"
        ] == [legacy_usage]
        assert run_created["attempt_snapshot"]["token_usage_by_model"] == [legacy_usage]
        assert run_created["provider_wire"] == _legacy_event_payload(
            {
                "model": "wire-model",
                "input_tokens": 999,
                "output_tokens": 888,
            }
        )
        assert payloads["attempt_updated"]["token_usage_by_model"] == [legacy_usage]


def test_otel_usage_cutover_equal_collisions_collapse_and_differing_collisions_rollback(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "otel-usage-collision.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "zg1h2i3j4k5l")

    equal_collision = _legacy_usage_snapshot(
        {
            "model": "legacy-model",
            "input_tokens": 11,
            "gen_ai_usage_input_tokens": 11,
        }
    )
    differing_collision = _legacy_usage_snapshot(
        {
            "model": "conflicting-model",
            "input_tokens": 13,
            "gen_ai_usage_input_tokens": 17,
        }
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            _legacy_event_payload(
                "INSERT INTO runs (id, repo_name, status, runner_config, config, created_at, updated_at, "
                "token_usage_by_model) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                "equal-run",
                "repo",
                "draft",
                "{}",
                "{}",
                "2025-01-01",
                "2025-01-01",
                json.dumps([equal_collision]),
            ),
        )
        connection.commit()

    command.upgrade(config, "r04a1b2c3d4e")
    with sqlite3.connect(database_path) as connection:
        assert json.loads(
            connection.execute(
                "SELECT token_usage_by_model FROM runs WHERE id = 'equal-run'"
            ).fetchone()[0]
        ) == [{"model": "legacy-model", "gen_ai_usage_input_tokens": 11}]

    command.downgrade(config, "zg1h2i3j4k5l")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            _legacy_event_payload(
                "INSERT INTO runs (id, repo_name, status, runner_config, config, created_at, updated_at, "
                "token_usage_by_model) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                "conflict-run",
                "repo",
                "draft",
                "{}",
                "{}",
                "2025-01-01",
                "2025-01-01",
                json.dumps([differing_collision]),
            ),
        )
        connection.commit()

    with pytest.raises(ValueError, match="usage migration collision"):
        command.upgrade(config, "r04a1b2c3d4e")

    with sqlite3.connect(database_path) as connection:
        assert json.loads(
            connection.execute(
                "SELECT token_usage_by_model FROM runs WHERE id = 'equal-run'"
            ).fetchone()[0]
        ) == [_legacy_usage_snapshot({"model": "legacy-model", "input_tokens": 11})]
        assert json.loads(
            connection.execute(
                "SELECT token_usage_by_model FROM runs WHERE id = 'conflict-run'"
            ).fetchone()[0]
        ) == [differing_collision]


def test_otel_usage_cutover_rejects_equal_input_collision_when_cache_is_present(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "otel-usage-cache-collision.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "zg1h2i3j4k5l")
    ambiguous = _legacy_usage_snapshot(
        {
            "model": "ambiguous-model",
            "input_tokens": 11,
            "gen_ai_usage_input_tokens": 11,
            "cache_read_tokens": 2,
        }
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO runs (id, repo_name, status, runner_config, config, created_at, updated_at, "
            "token_usage_by_model) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ambiguous-run",
                "repo",
                "draft",
                "{}",
                "{}",
                "2025-01-01",
                "2025-01-01",
                json.dumps([ambiguous]),
            ),
        )
        connection.commit()

    with pytest.raises(ValueError, match="ambiguous"):
        command.upgrade(config, "r04a1b2c3d4e")

    with sqlite3.connect(database_path) as connection:
        assert json.loads(
            connection.execute(
                "SELECT token_usage_by_model FROM runs WHERE id = 'ambiguous-run'"
            ).fetchone()[0]
        ) == [ambiguous]
