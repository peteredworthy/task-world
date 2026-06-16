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
import urllib.error
import urllib.request
from collections.abc import Callable
from collections import defaultdict
from typing import Any


GRAPH_DYNAMIC_FIELDS: tuple[str, ...] = (
    "planner_patches",
    "accepted_patches",
    "rejected_patches",
    "patch_ops",
    "patch_rejection_reasons",
    "appended_regions",
    "suspect_regions",
    "superseded_regions",
    "gap_findings",
    "proposal_decisions",
    "invariant_gate_failures",
    "graph_verifier_grades",
    "tokens_by_node_kind",
)
_DYNAMIC_DICT_FIELDS = frozenset(
    {"patch_rejection_reasons", "tokens_by_node_kind", "graph_verifier_grades"}
)
Fetcher = Callable[[str], Any]


def _get(path: str) -> Any:
    raw = urllib.request.urlopen(f"http://localhost:8000{path}", timeout=30).read()
    text = "".join(c for c in raw.decode("utf-8", "replace") if c >= " " or c == "\t")
    return json.loads(text)


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _coerce_non_negative_int(value: Any) -> int | None:
    count = _coerce_int(value)
    if count is None or count < 0:
        return None
    return count


def _coerce_count(value: Any) -> int:
    if isinstance(value, (list, tuple, set)):
        return len(value)
    count = _coerce_non_negative_int(value)
    return count if count is not None else 0


def _coerce_str(value: Any) -> str | None:
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    return None


def _events(run_id: str, fetcher: Fetcher = _get) -> list[dict[str, Any]]:
    d = fetcher(f"/api/runs/{run_id}/activity?limit=1000")
    return d if isinstance(d, list) else d.get("events", d.get("activities", []))


def _event_type(event: dict[str, Any]) -> str:
    return (event.get("event_type") or event.get("type") or "").lower()


def _coerce_graph_events(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [event for event in payload if isinstance(event, dict)]
    if isinstance(payload, dict):
        events = payload.get("events") or payload.get("graph_events") or payload.get("data")
        if isinstance(events, list):
            return [event for event in events if isinstance(event, dict)]
    return []


def _get_graph_events(run_id: str, fetcher: Fetcher = _get) -> list[dict[str, Any]]:
    try:
        payload = fetcher(f"/api/runs/{run_id}/graph/events?payload_mode=summary")
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return []
    return _coerce_graph_events(payload)


def _merge_dict_metrics(target: dict[str, int], additions: dict[str, int]) -> None:
    for key, count in additions.items():
        if not isinstance(key, str):
            continue
        current = target.get(key, 0)
        value = _coerce_non_negative_int(count)
        if value is None:
            continue
        target[key] = current + value


def _default_graph_metrics() -> dict[str, Any]:
    return {
        "planner_patches": 0,
        "accepted_patches": 0,
        "rejected_patches": 0,
        "patch_ops": 0,
        "patch_rejection_reasons": {},
        "appended_regions": 0,
        "suspect_regions": 0,
        "superseded_regions": 0,
        "gap_findings": 0,
        "proposal_decisions": 0,
        "invariant_gate_failures": 0,
        "graph_verifier_grades": {},
        "tokens_by_node_kind": {},
    }


def _metric_count(payload: dict[str, Any], field: str, default: int) -> int:
    if field in payload:
        return _coerce_count(payload[field])
    return default


def _merge_rejection_reasons(target: dict[str, int], payload: dict[str, Any]) -> None:
    reasons = payload.get("patch_rejection_reasons")
    if isinstance(reasons, dict):
        additions: dict[str, int] = {}
        for reason, count in reasons.items():
            reason_text = _coerce_str(reason)
            reason_count = _coerce_non_negative_int(count)
            if reason_text is not None and reason_count is not None:
                additions[reason_text] = reason_count
        _merge_dict_metrics(target, additions)
        return

    if isinstance(reasons, list):
        additions = {}
        for reason in reasons:
            reason_text = _coerce_str(reason)
            if reason_text is not None:
                additions[reason_text] = additions.get(reason_text, 0) + 1
        _merge_dict_metrics(target, additions)
        return

    reason = _coerce_str(payload.get("reason")) or _coerce_str(payload.get("rejection_reason"))
    if reason is not None:
        _merge_dict_metrics(target, {reason: 1})


def _count_patch_ops(payload: dict[str, Any]) -> int:
    for key in ("patch_ops", "ops", "operations"):
        if key in payload:
            return _coerce_count(payload[key])
    return 0


def _planner_proposed(payload: dict[str, Any]) -> bool:
    proposed_by = _coerce_str(payload.get("proposed_by_node_id"))
    return payload.get("actor_role") == "planner" or (
        proposed_by is not None and proposed_by.startswith("planner")
    )


def _node_kind(payload: dict[str, Any]) -> str | None:
    return _coerce_str(payload.get("kind") or payload.get("node_kind") or payload.get("role"))


def _is_region_node(payload: dict[str, Any]) -> bool:
    return _node_kind(payload) in {
        "appeal",
        "check",
        "gate",
        "oversight",
        "planner",
        "review",
        "verifier",
        "worker",
    }


def _merge_verifier_grades(target: dict[str, int], payload: dict[str, Any]) -> None:
    if isinstance(payload.get("graph_verifier_grades"), dict):
        _merge_dict_metrics(target, payload["graph_verifier_grades"])
        return

    grade_rows = payload.get("grades")
    value = payload.get("value")
    if isinstance(value, dict) and "grades" in value:
        grade_rows = value["grades"]

    if isinstance(grade_rows, dict):
        _merge_dict_metrics(target, grade_rows)
        return

    if isinstance(grade_rows, list):
        additions: dict[str, int] = {}
        for row in grade_rows:
            grade = _coerce_str(row.get("grade")) if isinstance(row, dict) else _coerce_str(row)
            if grade is not None:
                additions[grade] = additions.get(grade, 0) + 1
        _merge_dict_metrics(target, additions)
        return

    grade = _coerce_str(payload.get("grade"))
    if grade is not None:
        _merge_dict_metrics(target, {grade: 1})


def _merge_token_metrics(target: dict[str, int], payload: dict[str, Any]) -> None:
    if isinstance(payload.get("tokens_by_node_kind"), dict):
        _merge_dict_metrics(target, payload["tokens_by_node_kind"])
    if isinstance(payload.get("tokens_by_node"), dict):
        _merge_dict_metrics(target, payload["tokens_by_node"])

    node_kind = _node_kind(payload)
    if node_kind is None:
        return
    token_total = _coerce_non_negative_int(payload.get("tokens"))
    if token_total is None:
        token_total = sum(
            _coerce_non_negative_int(payload.get(name)) or 0
            for name in (
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
            )
        )
    if token_total:
        _merge_dict_metrics(target, {node_kind: token_total})


def _extract_graph_metrics(graph_events: list[dict[str, Any]]) -> dict[str, Any]:
    dynamic: dict[str, Any] = _default_graph_metrics()

    for event in graph_events:
        if not isinstance(event, dict):
            continue

        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        etype = _event_type(event)

        if etype == "graph_patch_accepted":
            dynamic["accepted_patches"] += _metric_count(payload, "accepted_patches", 1)
            dynamic["patch_ops"] += _count_patch_ops(payload)
            dynamic["proposal_decisions"] += 1
            if _planner_proposed(payload):
                dynamic["planner_patches"] += 1
        elif etype == "graph_patch_rejected":
            dynamic["rejected_patches"] += _metric_count(payload, "rejected_patches", 1)
            dynamic["patch_ops"] += _count_patch_ops(payload)
            dynamic["proposal_decisions"] += 1
            if _planner_proposed(payload):
                dynamic["planner_patches"] += 1
            _merge_rejection_reasons(dynamic["patch_rejection_reasons"], payload)
        elif etype == "command_rejected":
            if payload.get("command_type") == "complete" and (
                payload.get("reason") == "final invariant blockers remain"
                or isinstance(payload.get("blockers"), list)
            ):
                dynamic["invariant_gate_failures"] += 1
                dynamic["gap_findings"] += _coerce_count(payload.get("blockers"))
        elif etype in {"verification_passed", "verification_failed"}:
            _merge_verifier_grades(dynamic["graph_verifier_grades"], payload)
        elif etype == "node_created":
            if _is_region_node(payload):
                dynamic["appended_regions"] += 1
            if payload.get("state") == "blocked" or payload.get("blocker"):
                dynamic["suspect_regions"] += 1
                dynamic["gap_findings"] += 1
        elif etype == "node_state_changed":
            if payload.get("new_state") in {"retired", "cancelled"}:
                dynamic["superseded_regions"] += 1
            if payload.get("new_state") in {"blocked", "failed", "suspended"}:
                dynamic["suspect_regions"] += 1
        elif etype == "node_retired":
            dynamic["superseded_regions"] += 1
        elif etype == "node_deferred":
            dynamic["gap_findings"] += 1
            dynamic["suspect_regions"] += 1

        if etype in {
            "command_rejected",
            "cost_recorded",
            "gatekeeper_cost_recorded",
            "graph_patch_accepted",
            "graph_patch_rejected",
            "node_created",
            "node_deferred",
            "node_retired",
            "node_state_changed",
            "verification_failed",
            "verification_passed",
        }:
            _merge_token_metrics(dynamic["tokens_by_node_kind"], payload)

    return dynamic


def run_metrics(run_id: str, fetcher: Fetcher = _get) -> dict[str, Any]:
    """Pull one run's comparison facts from the live orchestrator API."""
    run = fetcher(f"/api/runs/{run_id}")
    evs = _events(run_id, fetcher)
    dynamic = _extract_graph_metrics(_get_graph_events(run_id, fetcher))

    def etype(e: dict[str, Any]) -> str:
        return _event_type(e)

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
        "tool_calls": run.get("total_num_actions") or 0,
        "cost_usd": run.get("estimated_cost_usd") or 0.0,
        **dynamic,
    }


def aggregate_bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure aggregation of one approach bucket's run metrics (unit-tested).

    Token/tool/cost figures are per-run AVERAGES (so buckets with different run
    counts stay comparable); completion/grade figures are totals.
    """
    n = len(rows)
    div = n or 1

    dynamic_numeric: dict[str, int] = {
        k: 0 for k in GRAPH_DYNAMIC_FIELDS if k not in _DYNAMIC_DICT_FIELDS
    }
    dynamic_dict: dict[str, dict[str, int]] = {k: {} for k in _DYNAMIC_DICT_FIELDS}

    for row in rows:
        for name in dynamic_numeric:
            dynamic_numeric[name] += _coerce_non_negative_int(row.get(name, 0)) or 0
        for name in _DYNAMIC_DICT_FIELDS:
            values = row.get(name, {})
            if not isinstance(values, dict):
                continue
            for key, count in values.items():
                if not isinstance(key, str):
                    continue
                current = dynamic_dict[name].get(key, 0)
                dynamic_dict[name][key] = current + (_coerce_non_negative_int(count) or 0)

    return {
        "runs": n,
        "completed": sum(1 for r in rows if r["status"] == "completed"),
        "all_a": sum(1 for r in rows if r["grades"] and all(g == "A" for g in r["grades"])),
        "agent_turns": sum(r["agent_dispatches"] + r["attempts"] for r in rows),
        "retries": sum(r["retries"] for r in rows),
        "planner_patches": dynamic_numeric["planner_patches"],
        "accepted_patches": dynamic_numeric["accepted_patches"],
        "rejected_patches": dynamic_numeric["rejected_patches"],
        "patch_ops": dynamic_numeric["patch_ops"],
        "appended_regions": dynamic_numeric["appended_regions"],
        "suspect_regions": dynamic_numeric["suspect_regions"],
        "superseded_regions": dynamic_numeric["superseded_regions"],
        "gap_findings": dynamic_numeric["gap_findings"],
        "proposal_decisions": dynamic_numeric["proposal_decisions"],
        "invariant_gate_failures": dynamic_numeric["invariant_gate_failures"],
        "patch_rejection_reasons": dynamic_dict["patch_rejection_reasons"],
        "graph_verifier_grades": dynamic_dict["graph_verifier_grades"],
        "tokens_by_node_kind": dynamic_dict["tokens_by_node_kind"],
        "avg_tokens_read": sum(r["tokens_read"] for r in rows) / div,
        "avg_tokens_write": sum(r["tokens_write"] for r in rows) / div,
        "avg_tokens_cache": sum(r["tokens_cache"] for r in rows) / div,
        "avg_tool_calls": sum(r["tool_calls"] for r in rows) / div,
        "avg_cost_usd": sum(r["cost_usd"] for r in rows) / div,
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
        f"{'approach':24} {'runs':4} {'compl':5} {'all-A':5} {'avg_in':7} {'avg_out':8} "
        f"{'avg_cache':10} {'avg_tools':10} {'avg_cost$':10}"
    )
    print(hdr)
    print("-" * len(hdr))
    for label, rids in buckets.items():
        agg = aggregate_bucket([run_metrics(r) for r in rids])
        print(
            f"{label:24} {agg['runs']:<4} {agg['completed']:<5} {agg['all_a']:<5} "
            f"{agg['avg_tokens_read']:<7.0f} {agg['avg_tokens_write']:<8.0f} "
            f"{agg['avg_tokens_cache']:<10.0f} {agg['avg_tool_calls']:<10.1f} "
            f"{agg['avg_cost_usd']:<10.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
