"""Read-model projection service for Super Parent oversight."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from orchestrator.state import Run
from orchestrator.workflow.oversight import reduce_parent_oversight_state


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


def extract_parent_oversight_facts(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return only durable parent-authored or coordinator-authored oversight facts."""
    return {key: value for key, value in state.items() if key in DURABLE_PARENT_OVERSIGHT_FACT_KEYS}


class OversightProjectionService:
    """Compute parent oversight projections from durable facts and live children."""

    def project_parent(
        self,
        parent: Run,
        children: Sequence[Run],
        evidence_by_run_id: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        *,
        max_child_runs: int,
    ) -> dict[str, Any]:
        """Return JSON-safe projected Super Parent oversight state."""
        parent_for_projection = parent.model_copy(
            deep=True,
            update={"oversight_state": extract_parent_oversight_facts(parent.oversight_state)},
        )
        return reduce_parent_oversight_state(
            parent_for_projection,
            children,
            evidence_by_run_id,
            max_child_runs=max_child_runs,
        )
