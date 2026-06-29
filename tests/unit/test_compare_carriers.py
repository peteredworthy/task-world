"""Unit test for the carrier-comparison metric aggregation (slice 4.3).

Pure: exercises ``aggregate_bucket`` and ``run_metrics`` over fixed fixtures,
with no network and no orchestrator.
"""

from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compare_carriers.py"
_SPEC = importlib.util.spec_from_file_location("compare_carriers", _SCRIPT)
assert _SPEC and _SPEC.loader
compare_carriers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(compare_carriers)


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
        "tool_calls": 0,
        "cost_usd": 0.0,
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
        "expired_leases": 0,
        "failed_nodes": 0,
        "final_blockers": 0,
        "stale_evidence_count": 0,
        "graph_verifier_grades": {},
        "tokens_by_node_kind": {},
    }
    base.update(kw)
    return base


def _run_metrics_with_fake_get(run_id: str, fake_get) -> dict[str, object]:
    return compare_carriers.run_metrics(run_id, fetcher=fake_get)


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


def test_aggregate_averages_tokens_tools_cost_and_dynamic_counts() -> None:
    rows = [
        _row(
            agent_dispatches=1,
            attempts=2,
            retries=1,
            tokens_write=1000,
            tokens_read=50,
            tokens_cache=400,
            tool_calls=10,
            cost_usd=0.10,
            planner_patches=1,
            accepted_patches=3,
            patch_rejection_reasons={"timeout": 1},
            tokens_by_node_kind={"planner": 4},
        ),
        _row(
            agent_dispatches=2,
            attempts=1,
            retries=0,
            tokens_write=1500,
            tokens_read=70,
            tokens_cache=600,
            tool_calls=20,
            cost_usd=0.30,
            planner_patches=2,
            accepted_patches=1,
            patch_rejection_reasons={"conflict": 2},
            tokens_by_node_kind={"planner": 1, "executor": 3},
        ),
    ]
    agg = compare_carriers.aggregate_bucket(rows)
    assert agg["agent_turns"] == 6  # (1+2) + (2+1) — total, not averaged
    assert agg["retries"] == 1
    assert agg["planner_patches"] == 3
    assert agg["accepted_patches"] == 4
    assert agg["patch_rejection_reasons"] == {"timeout": 1, "conflict": 2}
    assert agg["tokens_by_node_kind"] == {"planner": 5, "executor": 3}
    assert agg["avg_tokens_write"] == 1250  # (1000+1500)/2
    assert agg["avg_tokens_read"] == 60
    assert agg["avg_tokens_cache"] == 500
    assert agg["avg_tool_calls"] == 15
    assert abs(agg["avg_cost_usd"] - 0.20) < 1e-9


def test_aggregate_dynamic_dict_merge_only_by_key() -> None:
    rows = [
        _row(
            graph_verifier_grades={"A": 1, "B": 2},
            patch_rejection_reasons={"timeout": 2},
        ),
        _row(
            graph_verifier_grades={"A": 3},
            patch_rejection_reasons={"timeout": 1, "conflict": 1},
        ),
    ]
    agg = compare_carriers.aggregate_bucket(rows)
    assert agg["graph_verifier_grades"] == {"A": 4, "B": 2}
    assert agg["patch_rejection_reasons"] == {"timeout": 3, "conflict": 1}


def test_run_metrics_extracts_dynamic_graph_metrics_from_graph_events() -> None:
    def fake_get(path: str):
        if path == "/api/runs/test-run":
            return {
                "status": "completed",
                "execution_mode": "graph",
                "agent_runner_type": "cli_subprocess",
                "total_tokens_read": 20,
                "total_tokens_write": 30,
                "total_tokens_cache": 10,
                "total_num_actions": 4,
                "estimated_cost_usd": 0.42,
            }
        if path == "/api/runs/test-run/activity?limit=200&payload_mode=summary":
            return []
        if path == "/api/runs/test-run/graph/events?payload_mode=summary":
            return [
                {
                    "event_type": "graph_patch_accepted",
                    "payload": {
                        "patch_id": "patch-1",
                        "actor_role": "planner",
                        "proposed_by_node_id": "planner-1",
                        "ops": [{"op": "create_node"}, {"op": "create_edge"}],
                        "tokens_by_node_kind": {"planner": 5},
                    },
                },
                {
                    "event_type": "graph_patch_rejected",
                    "payload": {
                        "patch_id": "patch-2",
                        "actor_role": "planner",
                        "proposed_by_node_id": "planner-1",
                        "reason": "read_set_changed",
                    },
                },
                {
                    "event_type": "graph_patch_rejected",
                    "payload": {
                        "patch_id": "patch-3",
                        "actor_role": "planner",
                        "patch_rejection_reasons": ["read_set_changed", "budget_exhausted"],
                    },
                },
                {
                    "event_type": "node_created",
                    "payload": {"node_id": "worker-1", "kind": "worker", "state": "planned"},
                },
                {
                    "event_type": "node_created",
                    "payload": {
                        "node_id": "review-final",
                        "kind": "review",
                        "state": "blocked",
                        "blocker": "unresolved gap evidence",
                    },
                },
                {
                    "event_type": "node_state_changed",
                    "payload": {
                        "node_id": "worker-old",
                        "new_state": "retired",
                        "trigger": "graph_patch_accepted",
                    },
                },
                {
                    "event_type": "node_deferred",
                    "payload": {
                        "node_id": "verifier-2",
                        "reason": "missing_required_input:candidate",
                    },
                },
                {
                    "event_type": "command_rejected",
                    "payload": {
                        "command_type": "complete",
                        "reason": "final invariant blockers remain",
                        "blockers": [{"kind": "task_not_accepted"}, {"kind": "gate_not_approved"}],
                    },
                },
                {
                    "event_type": "verification_failed",
                    "payload": {
                        "value": {
                            "grades": [
                                {"requirement_id": "R-1", "grade": "C"},
                                {"requirement_id": "R-2", "grade": "B"},
                            ]
                        },
                    },
                },
                {
                    "event_type": "verification_passed",
                    "payload": {"grades": [{"requirement_id": "R-3", "grade": "A"}]},
                },
                {
                    "event_type": "gatekeeper_cost_recorded",
                    "payload": {
                        "kind": "review",
                        "input_tokens": 3,
                        "output_tokens": 4,
                        "cache_read_tokens": 5,
                    },
                },
                {
                    "event_type": "unrelated",
                    "payload": {
                        "planner_patches": 99,
                        "reason": "unknown",
                        "grade": "F",
                        "tokens_by_node_kind": {"unknown": 99},
                    },
                },
            ]
        if path == "/api/runs/test-run/graph/health":
            return {
                "counts": {
                    "expired_leases": 1,
                    "failed_nodes": 2,
                    "final_blockers": 3,
                    "stale_evidence": 4,
                }
            }
        raise AssertionError(f"unexpected path: {path}")

    metrics = _run_metrics_with_fake_get("test-run", fake_get)

    assert metrics["planner_patches"] == 3
    assert metrics["accepted_patches"] == 1
    assert metrics["rejected_patches"] == 2
    assert metrics["patch_ops"] == 2
    assert metrics["appended_regions"] == 2
    assert metrics["suspect_regions"] == 2
    assert metrics["superseded_regions"] == 1
    assert metrics["gap_findings"] == 4
    assert metrics["proposal_decisions"] == 3
    assert metrics["invariant_gate_failures"] == 1
    assert metrics["expired_leases"] == 1
    assert metrics["failed_nodes"] == 2
    assert metrics["final_blockers"] == 3
    assert metrics["stale_evidence_count"] == 4
    assert metrics["patch_rejection_reasons"] == {"read_set_changed": 2, "budget_exhausted": 1}
    assert metrics["graph_verifier_grades"] == {"C": 1, "B": 1, "A": 1}
    assert metrics["tokens_by_node_kind"] == {"planner": 5, "review": 12}


def test_run_metrics_defaults_on_missing_or_malformed_graph_payload() -> None:
    def missing_graph_get(path: str):
        if path == "/api/runs/missing-run":
            return {
                "status": "failed",
                "execution_mode": "graph",
                "agent_runner_type": "cli_subprocess",
            }
        if path == "/api/runs/missing-run/activity?limit=200&payload_mode=summary":
            return {"activities": []}
        if path == "/api/runs/missing-run/graph/events?payload_mode=summary":
            raise urllib.error.URLError("missing")
        if path == "/api/runs/missing-run/graph/health":
            raise urllib.error.URLError("missing")
        raise AssertionError(f"unexpected path: {path}")

    missing = _run_metrics_with_fake_get("missing-run", missing_graph_get)
    assert missing["planner_patches"] == 0
    assert missing["expired_leases"] == 0
    assert missing["patch_rejection_reasons"] == {}
    assert missing["graph_verifier_grades"] == {}

    def malformed_graph_get(path: str):
        if path == "/api/runs/malformed-run":
            return {"status": "completed"}
        if path == "/api/runs/malformed-run/activity?limit=200&payload_mode=summary":
            return []
        if path == "/api/runs/malformed-run/graph/events?payload_mode=summary":
            return {"unexpected": True}
        if path == "/api/runs/malformed-run/graph/health":
            return {"unexpected": True}
        raise AssertionError(f"unexpected path: {path}")

    malformed = _run_metrics_with_fake_get("malformed-run", malformed_graph_get)
    assert malformed["planner_patches"] == 0
    assert malformed["tokens_by_node_kind"] == {}


def test_aggregate_empty_bucket_preserves_existing_and_dynamic_defaults() -> None:
    agg = compare_carriers.aggregate_bucket([])
    assert agg == {
        "runs": 0,
        "completed": 0,
        "all_a": 0,
        "agent_turns": 0,
        "retries": 0,
        "planner_patches": 0,
        "accepted_patches": 0,
        "rejected_patches": 0,
        "patch_ops": 0,
        "appended_regions": 0,
        "suspect_regions": 0,
        "superseded_regions": 0,
        "gap_findings": 0,
        "proposal_decisions": 0,
        "invariant_gate_failures": 0,
        "expired_leases": 0,
        "failed_nodes": 0,
        "final_blockers": 0,
        "stale_evidence_count": 0,
        "patch_rejection_reasons": {},
        "graph_verifier_grades": {},
        "tokens_by_node_kind": {},
        "avg_tokens_read": 0,
        "avg_tokens_write": 0,
        "avg_tokens_cache": 0,
        "avg_tool_calls": 0,
        "avg_cost_usd": 0,
    }
