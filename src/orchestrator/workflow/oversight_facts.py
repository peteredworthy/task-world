"""Workflow-owned parent oversight fact keys and patch sanitizing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DURABLE_PARENT_OVERSIGHT_FACT_KEYS: frozenset[str] = frozenset(
    {
        "current_understanding",
        "target_inventory",
        "final_validation",
        "decisions",
        "delegated_work",
        "delegation_decisions",
        "delegation_results",
        "delegation_review_states",
        "slices",
        "last_child_run_id",
        "last_decision",
        "child_waits",
        "accepted_child_run_ids",
        "rejected_child_run_ids",
        "abandoned_child_run_ids",
        "closed_child_run_ids",
        "accepted_children",
        "merge_conflicts",
        "max_child_runs",
        "delegation_owner_token",
    }
)
APPEND_ONLY_OVERSIGHT_LIST_KEYS: frozenset[str] = frozenset(
    {
        "decisions",
        "delegation_decisions",
        "delegation_results",
        "child_waits",
        "accepted_children",
        "merge_conflicts",
        "slices",
    }
)
SET_UNION_OVERSIGHT_LIST_KEYS: frozenset[str] = frozenset(
    {
        "accepted_child_run_ids",
        "rejected_child_run_ids",
        "abandoned_child_run_ids",
        "closed_child_run_ids",
    }
)
COORDINATION_OVERSIGHT_FACT_KEYS: frozenset[str] = (
    (APPEND_ONLY_OVERSIGHT_LIST_KEYS - {"decisions"})
    | SET_UNION_OVERSIGHT_LIST_KEYS
    | frozenset(
        {
            "delegated_work",
            "delegation_review_states",
            "last_child_run_id",
            "last_decision",
            "delegation_owner_token",
        }
    )
)


def durable_parent_oversight_patch(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return only durable parent-authored or coordinator-authored oversight facts."""
    return {key: value for key, value in state.items() if key in DURABLE_PARENT_OVERSIGHT_FACT_KEYS}


def extract_parent_oversight_facts(state: Mapping[str, Any]) -> dict[str, Any]:
    """Backward-compatible name for durable parent oversight patch extraction."""
    return durable_parent_oversight_patch(state)
