"""Read-only helpers for legacy run fact payloads.

These constants are retained for replaying historical ``ParentOversightFactsUpdated``
events. They are not a live oversight API.
"""

from collections.abc import Mapping
from typing import Any


DURABLE_PARENT_OVERSIGHT_FACT_KEYS: frozenset[str] = frozenset(
    {
        "current_understanding",
        "target_inventory",
        "final_validation",
        "decisions",
        "delegation_decisions",
        "delegation_results",
        "delegation_review_states",
        "child_waits",
        "delegated_work",
        "abandoned_child_run_ids",
        "rejected_child_run_ids",
        "accepted_child_run_ids",
    }
)

APPEND_ONLY_OVERSIGHT_LIST_KEYS: frozenset[str] = frozenset(
    {
        "decisions",
        "delegation_decisions",
        "delegation_results",
        "delegation_review_states",
        "child_waits",
    }
)

SET_UNION_OVERSIGHT_LIST_KEYS: frozenset[str] = frozenset(
    {
        "abandoned_child_run_ids",
        "rejected_child_run_ids",
        "accepted_child_run_ids",
    }
)


def durable_parent_oversight_patch(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return legacy durable fact keys for historical replay compatibility."""
    return {key: value for key, value in state.items() if key in DURABLE_PARENT_OVERSIGHT_FACT_KEYS}
