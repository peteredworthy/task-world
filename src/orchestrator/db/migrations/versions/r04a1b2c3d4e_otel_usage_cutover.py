"""Migrate persisted token usage facts to canonical OTel vocabulary.

Revision ID: r04a1b2c3d4e
Revises: zg1h2i3j4k5l
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Sequence, Union, cast

import sqlalchemy as sa
from alembic import op

revision: str = "r04a1b2c3d4e"
down_revision: Union[str, Sequence[str], None] = "zg1h2i3j4k5l"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_TO_CANONICAL = {
    "input_tokens": "gen_ai_usage_input_tokens",
    "output_tokens": "gen_ai_usage_output_tokens",
    "cache_read_tokens": "gen_ai_usage_cache_read_input_tokens",
    "cache_creation_tokens": "gen_ai_usage_cache_creation_input_tokens",
    "tokens_reasoning": "gen_ai_usage_reasoning_output_tokens",
    "total_cost_usd": "cost_usd",
}
_CANONICAL_TO_LEGACY = {value: key for key, value in _LEGACY_TO_CANONICAL.items()}


def _rewrite_usage_entries(value: Any, key_map: Mapping[str, str]) -> Any:
    if not isinstance(value, list):
        return value
    rewritten_entries: list[Any] = []
    for entry in cast(list[Any], value):
        if not isinstance(entry, dict):
            rewritten_entries.append(entry)
            continue
        rewritten = dict(cast(dict[str, Any], entry))
        if "model" not in rewritten:
            rewritten_entries.append(rewritten)
            continue
        for source, target in key_map.items():
            if (
                source in rewritten
                and target in rewritten
                and rewritten[source] != rewritten[target]
            ):
                raise ValueError(f"usage migration collision for {source} and {target}")
            if target not in rewritten and source in rewritten:
                rewritten[target] = rewritten[source]
            rewritten.pop(source, None)
        rewritten_entries.append(rewritten)
    return rewritten_entries


def _rewrite_json_column(table: str, column: str, key_map: Mapping[str, str]) -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL")
    )
    for rowid, raw_value in rows:
        value = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
        rewritten = _rewrite_usage_entries(value, key_map)
        connection.execute(
            sa.text(f"UPDATE {table} SET {column} = :value WHERE rowid = :rowid"),
            {"value": json.dumps(rewritten), "rowid": rowid},
        )


def _rewrite_usage_structure(value: Any, key_map: Mapping[str, str]) -> Any:
    """Rewrite every usage list inside a recognized event telemetry structure."""
    if isinstance(value, list):
        return [_rewrite_usage_structure(item, key_map) for item in cast(list[Any], value)]
    if not isinstance(value, dict):
        return value

    rewritten = dict(cast(dict[str, Any], value))
    if "token_usage_by_model" in rewritten:
        rewritten["token_usage_by_model"] = _rewrite_usage_entries(
            rewritten["token_usage_by_model"], key_map
        )
    for key, nested_value in rewritten.items():
        if key != "token_usage_by_model":
            rewritten[key] = _rewrite_usage_structure(nested_value, key_map)
    return rewritten


def _rewrite_event_payloads(key_map: Mapping[str, str]) -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT rowid, payload FROM events_v2"))
    for rowid, raw_payload in rows:
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
        if not isinstance(payload, dict):
            continue
        rewritten = dict(cast(dict[str, Any], payload))
        if "token_usage_by_model" in rewritten:
            rewritten["token_usage_by_model"] = _rewrite_usage_entries(
                rewritten["token_usage_by_model"], key_map
            )
        for key in ("telemetry", "run_snapshot", "attempt_snapshot"):
            container = rewritten.get(key)
            if isinstance(container, dict | list):
                rewritten[key] = _rewrite_usage_structure(container, key_map)
        connection.execute(
            sa.text("UPDATE events_v2 SET payload = :payload WHERE rowid = :rowid"),
            {"payload": json.dumps(rewritten), "rowid": rowid},
        )


def _usage_totals(raw_value: Any) -> tuple[int, int, int]:
    usage_entries = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
    if not isinstance(usage_entries, list):
        return 0, 0, 0
    entries = cast(list[Any], usage_entries)

    def total(key: str) -> int:
        return sum(
            int(cast(dict[str, Any], entry).get(key, 0))
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(cast(dict[str, Any], entry).get(key, 0), int | float)
        )

    return (
        total("gen_ai_usage_input_tokens"),
        total("gen_ai_usage_output_tokens"),
        total("gen_ai_usage_cache_read_input_tokens")
        + total("gen_ai_usage_cache_creation_input_tokens"),
    )


def _restore_flat_totals(table: str, columns: tuple[str, str, str]) -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"SELECT rowid, token_usage_by_model FROM {table} WHERE token_usage_by_model IS NOT NULL"
        )
    )
    for rowid, raw_value in rows:
        input_tokens, output_tokens, cache_tokens = _usage_totals(raw_value)
        connection.execute(
            sa.text(
                f"UPDATE {table} SET {columns[0]} = :input_tokens, {columns[1]} = :output_tokens, "
                f"{columns[2]} = :cache_tokens WHERE rowid = :rowid"
            ),
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_tokens": cache_tokens,
                "rowid": rowid,
            },
        )


def upgrade() -> None:
    for table in ("runs", "attempts", "cost_records"):
        _rewrite_json_column(table, "token_usage_by_model", _LEGACY_TO_CANONICAL)
    _rewrite_event_payloads(_LEGACY_TO_CANONICAL)

    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("total_tokens_read")
        batch_op.drop_column("total_tokens_write")
        batch_op.drop_column("total_tokens_cache")
    with op.batch_alter_table("attempts") as batch_op:
        batch_op.drop_column("tokens_read")
        batch_op.drop_column("tokens_write")
        batch_op.drop_column("tokens_cache")
    with op.batch_alter_table("cost_records") as batch_op:
        batch_op.alter_column("input_tokens", new_column_name="gen_ai_usage_input_tokens")
        batch_op.alter_column("output_tokens", new_column_name="gen_ai_usage_output_tokens")
        batch_op.alter_column(
            "cache_read_tokens", new_column_name="gen_ai_usage_cache_read_input_tokens"
        )
        batch_op.alter_column(
            "cache_write_tokens", new_column_name="gen_ai_usage_cache_creation_input_tokens"
        )


def downgrade() -> None:
    with op.batch_alter_table("cost_records") as batch_op:
        batch_op.alter_column("gen_ai_usage_input_tokens", new_column_name="input_tokens")
        batch_op.alter_column("gen_ai_usage_output_tokens", new_column_name="output_tokens")
        batch_op.alter_column(
            "gen_ai_usage_cache_read_input_tokens", new_column_name="cache_read_tokens"
        )
        batch_op.alter_column(
            "gen_ai_usage_cache_creation_input_tokens", new_column_name="cache_write_tokens"
        )
    with op.batch_alter_table("attempts") as batch_op:
        batch_op.add_column(
            sa.Column("tokens_read", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("tokens_write", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("tokens_cache", sa.Integer(), nullable=False, server_default="0")
        )
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(
            sa.Column("total_tokens_read", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("total_tokens_write", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("total_tokens_cache", sa.Integer(), nullable=False, server_default="0")
        )

    _restore_flat_totals("runs", ("total_tokens_read", "total_tokens_write", "total_tokens_cache"))
    _restore_flat_totals("attempts", ("tokens_read", "tokens_write", "tokens_cache"))
    for table in ("runs", "attempts", "cost_records"):
        _rewrite_json_column(table, "token_usage_by_model", _CANONICAL_TO_LEGACY)
    _rewrite_event_payloads(_CANONICAL_TO_LEGACY)
