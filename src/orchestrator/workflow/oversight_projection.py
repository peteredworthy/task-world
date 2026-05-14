"""Read-model projection service for Super Parent oversight."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from orchestrator.state import Run
from orchestrator.workflow.delegation.models import DelegationDecision
from orchestrator.workflow.oversight import reduce_parent_oversight_state
from orchestrator.workflow.oversight_facts import extract_parent_oversight_facts


def project_parent_oversight(
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


def delegation_decision_from_parent_snapshot(
    snapshot: Mapping[str, Any],
) -> DelegationDecision:
    """Map a projected parent oversight snapshot to the next delegation decision."""
    action = snapshot.get("next_parent_action")
    terminal_guard = _mapping(snapshot.get("terminal_guard"))
    blocking_reasons = _string_list(terminal_guard.get("blocking_reasons"))
    blocking_child_run_ids = _string_list(terminal_guard.get("blocking_child_run_ids"))
    active_child_run_ids = _string_list(snapshot.get("active_child_run_ids"))
    merge_queue = _string_list(snapshot.get("merge_queue"))
    attention_work_id = _first_attention_work_id(snapshot)
    child_count = _int_value(snapshot.get("child_count"))
    max_child_runs = _int_value(snapshot.get("max_child_runs"))
    illegal_state_reasons = _string_list(snapshot.get("illegal_state_reasons"))

    if (
        action == "ask_user"
        and len(active_child_run_ids) == 1
        and illegal_state_reasons == ["terminal_parent_has_unresolved_children"]
    ):
        return DelegationDecision(
            kind="wait",
            work_id=active_child_run_ids[0],
            reason="delegate_still_running",
            stable_state="WaitingOnDelegate",
        )
    if action == "wait_for_child":
        return DelegationDecision(
            kind="wait",
            work_id=_first(active_child_run_ids) or _first(blocking_child_run_ids),
            reason="delegate_still_running",
            stable_state="WaitingOnDelegate",
        )
    if action == "accept_child":
        return DelegationDecision(kind="integrate", work_id=_first(merge_queue))
    if action == "review_child_evidence":
        return DelegationDecision(
            kind="review",
            work_id=attention_work_id or _first(blocking_child_run_ids),
            reason="terminal_delegate_requires_review",
            stable_state="ReviewDelegateResult",
        )
    if action == "ask_user":
        reason = "parent_oversight_requires_user_decision"
        if max_child_runs is not None and child_count is not None and child_count >= max_child_runs:
            reason = "max_delegate_limit_reached"
        return DelegationDecision(
            kind="ask_user",
            work_id=attention_work_id or _first(blocking_child_run_ids),
            reason=reason,
            stable_state="ReviewDelegateResult",
        )
    if action == "complete_parent":
        return DelegationDecision(kind="complete")
    if action == "launch_child" and blocking_reasons:
        return DelegationDecision(
            kind="review",
            reason="terminal_guard_blocked",
            stable_state="AwaitingGate",
            payload={"blocking_reasons": blocking_reasons},
        )
    return DelegationDecision(kind="launch", reason="ready_for_next_delegate")


def _mapping(value: Any) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (bytes, str)):
        return []
    return [item for item in cast(Sequence[Any], value) if isinstance(item, str)]


def _first(values: Sequence[str]) -> str | None:
    return values[0] if values else None


def _int_value(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _first_attention_work_id(snapshot: Mapping[str, Any]) -> str | None:
    raw_items = snapshot.get("attention_items")
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (bytes, str)):
        return None
    for item in cast(Sequence[Any], raw_items):
        if isinstance(item, Mapping):
            run_id = cast(Mapping[str, Any], item).get("run_id")
            if isinstance(run_id, str):
                return run_id
    return None


__all__ = [
    "delegation_decision_from_parent_snapshot",
    "project_parent_oversight",
]
