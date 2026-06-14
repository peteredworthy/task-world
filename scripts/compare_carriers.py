#!/usr/bin/env python3
"""Carrier comparison data puller for the execution-graph convergence (slice 4.3).

Compares the three ways the orchestrator gets work done, on completeness/
correctness vs cost:

  - existing (legacy single-agent)    : one builder task, validated by scripts
  - 3-sub-agent (builder/auditor/fixer): legacy carrier, verifier agent + retry
  - execution graph                    : GraphRunDriver, structural worker+verifier

For each run it reports terminal status, agent dispatch/attempt count (a cost
proxy captured for every runner), verifier grades, retry count, and measured
token usage (read/write/cache) when the runner reports it.

Usage:
    uv run python scripts/compare_carriers.py <label=run_id> [<label=run_id> ...]
    # a label may repeat to aggregate several runs into one approach bucket.

Token note (June 2026): cli_subprocess (Claude CLI) persists token usage;
codex_server and graph-mode dispatch currently do NOT (token_usage stays 0) —
see docs/graph-approach/carrier-comparison.md. Use cli_subprocess runs for the
measured-token rows; agent-dispatch count is the runner-independent cost proxy.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from typing import Any


def _get(path: str) -> Any:
    raw = urllib.request.urlopen(f"http://localhost:8000{path}", timeout=30).read()
    text = "".join(c for c in raw.decode("utf-8", "replace") if c >= " " or c == "\t")
    return json.loads(text)


def _events(run_id: str) -> list[dict[str, Any]]:
    d = _get(f"/api/runs/{run_id}/activity?limit=1000")
    return d if isinstance(d, list) else d.get("activities", d.get("events", []))


def run_metrics(run_id: str) -> dict[str, Any]:
    """Pull one run's comparison facts from the live orchestrator API."""
    run = _get(f"/api/runs/{run_id}")
    evs = _events(run_id)

    def etype(e: dict[str, Any]) -> str:
        return (e.get("event_type") or e.get("type") or "").lower()

    grades = [
        (e.get("payload") or e).get("grade")
        for e in evs
        if "grad" in etype(e) and (e.get("payload") or e).get("grade")
    ]
    dispatches = sum(1 for e in evs if "dispatch" in etype(e))
    attempts = sum(1 for e in evs if "attempt_created" in etype(e) or "attempt_started" in etype(e))
    retries = sum(1 for e in evs if "retr" in etype(e))
    return {
        "status": run.get("status"),
        "mode": run.get("execution_mode"),
        "runner": run.get("agent_runner_type"),
        "grades": grades,
        "agent_dispatches": dispatches,
        "attempts": attempts,
        "retries": retries,
        "tokens_read": run.get("total_tokens_read") or 0,
        "tokens_write": run.get("total_tokens_write") or 0,
        "tokens_cache": run.get("total_tokens_cache") or 0,
    }


def aggregate_bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure aggregation of one approach bucket's run metrics (unit-tested)."""
    n = len(rows)
    return {
        "runs": n,
        "completed": sum(1 for r in rows if r["status"] == "completed"),
        "all_a": sum(1 for r in rows if r["grades"] and all(g == "A" for g in r["grades"])),
        "agent_turns": sum(r["agent_dispatches"] + r["attempts"] for r in rows),
        "retries": sum(r["retries"] for r in rows),
        "tokens_read": sum(r["tokens_read"] for r in rows),
        "tokens_write": sum(r["tokens_write"] for r in rows),
        "tokens_cache": sum(r["tokens_cache"] for r in rows),
    }


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    buckets: dict[str, list[str]] = defaultdict(list)
    for arg in argv:
        if "=" not in arg:
            print(f"skip (need label=run_id): {arg}")
            continue
        label, rid = arg.split("=", 1)
        buckets[label].append(rid)

    hdr = (
        f"{'approach':22} {'runs':4} {'compl':5} {'all-A':5} "
        f"{'turns':6} {'retries':7} {'tok_read':9} {'tok_write':10} {'tok_cache':10}"
    )
    print(hdr)
    print("-" * len(hdr))
    for label, rids in buckets.items():
        agg = aggregate_bucket([run_metrics(r) for r in rids])
        print(
            f"{label:22} {agg['runs']:<4} {agg['completed']:<5} {agg['all_a']:<5} "
            f"{agg['agent_turns']:<6} {agg['retries']:<7} {agg['tokens_read']:<9} "
            f"{agg['tokens_write']:<10} {agg['tokens_cache']:<10}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
