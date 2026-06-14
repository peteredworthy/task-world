"""Unit test for the carrier-comparison metric aggregation (slice 4.3).

Pure: exercises ``aggregate_bucket`` over a fixed fixture of run metrics, with no
network and no orchestrator. Guards the maths behind the committed carrier
comparison (docs/graph-approach/carrier-comparison.md).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compare_carriers.py"
_spec = importlib.util.spec_from_file_location("compare_carriers", _SCRIPT)
assert _spec and _spec.loader
compare_carriers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_carriers)


def _row(**kw: object) -> dict[str, object]:
    base = {
        "status": "completed",
        "grades": ["A"],
        "agent_dispatches": 0,
        "attempts": 0,
        "retries": 0,
        "tokens_read": 0,
        "tokens_write": 0,
        "tokens_cache": 0,
    }
    base.update(kw)
    return base


def test_aggregate_counts_completion_and_grades() -> None:
    rows = [
        _row(status="completed", grades=["A", "A"]),
        _row(status="completed", grades=["A", "B"]),  # not all-A
        _row(status="failed", grades=[]),
    ]
    agg = compare_carriers.aggregate_bucket(rows)
    assert agg["runs"] == 3
    assert agg["completed"] == 2
    assert agg["all_a"] == 1


def test_aggregate_sums_turns_retries_and_tokens() -> None:
    rows = [
        _row(agent_dispatches=1, attempts=2, retries=1, tokens_write=1000, tokens_read=50),
        _row(agent_dispatches=2, attempts=1, retries=0, tokens_write=1500, tokens_read=70),
    ]
    agg = compare_carriers.aggregate_bucket(rows)
    assert agg["agent_turns"] == 6  # (1+2) + (2+1)
    assert agg["retries"] == 1
    assert agg["tokens_write"] == 2500
    assert agg["tokens_read"] == 120


def test_aggregate_empty_bucket() -> None:
    agg = compare_carriers.aggregate_bucket([])
    assert agg == {
        "runs": 0,
        "completed": 0,
        "all_a": 0,
        "agent_turns": 0,
        "retries": 0,
        "tokens_read": 0,
        "tokens_write": 0,
        "tokens_cache": 0,
    }
