#!/usr/bin/env python
"""Aggregate execution cost records by run and mode."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


METRIC_COLUMNS = [
    "executions",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "wall_time_ms",
    "cost_usd",
]


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_aggregates(conn: sqlite3.Connection, group_columns: list[str]) -> list[dict[str, Any]]:
    columns = ", ".join(group_columns)
    rows = conn.execute(
        f"""
        SELECT
            {columns},
            COUNT(*) AS executions,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
            COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
            COALESCE(SUM(wall_time_ms), 0) AS wall_time_ms,
            COALESCE(SUM(cost_usd), 0.0) AS cost_usd
        FROM cost_records
        GROUP BY {columns}
        ORDER BY {columns}
        """
    ).fetchall()
    return [dict(row) for row in rows]


def build_report(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    with _connect(db_path) as conn:
        return {
            "by_run": _fetch_aggregates(conn, ["run_id"]),
            "by_mode": _fetch_aggregates(conn, ["agent_runner_type", "mode_tag"]),
        }


def _format_table(title: str, rows: list[dict[str, Any]], group_columns: list[str]) -> str:
    headers = [*group_columns, *METRIC_COLUMNS]
    rendered_rows = [
        [
            *(str(row[column]) for column in group_columns),
            str(row["executions"]),
            str(row["input_tokens"]),
            str(row["output_tokens"]),
            str(row["cache_read_tokens"]),
            str(row["cache_write_tokens"]),
            str(row["wall_time_ms"]),
            f"{row['cost_usd']:.6f}",
        ]
        for row in rows
    ]
    widths = [
        max(len(header), *(len(row[idx]) for row in rendered_rows))
        if rendered_rows
        else len(header)
        for idx, header in enumerate(headers)
    ]
    lines = [title, " | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers))]
    lines.append("-+-".join("-" * width for width in widths))
    for row in rendered_rows:
        lines.append(" | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row)))
    if not rendered_rows:
        lines.append("(no cost records)")
    return "\n".join(lines)


def render_text(report: dict[str, list[dict[str, Any]]]) -> str:
    return "\n\n".join(
        [
            _format_table("Cost by run", report["by_run"], ["run_id"]),
            _format_table("Cost by mode", report["by_mode"], ["agent_runner_type", "mode_tag"]),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Path to the SQLite database")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of tables")
    args = parser.parse_args()

    report = build_report(args.db)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))


if __name__ == "__main__":
    main()
