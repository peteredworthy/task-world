"""Super Parent policy expressed over generic delegated-work primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from orchestrator.config import RunStatus
from orchestrator.state import Run
from orchestrator.workflow.delegation.models import (
    DelegateResultEnvelope,
    DelegatedWork,
    DelegatedWorkStatus,
    DelegationDecision,
)
from orchestrator.workflow.oversight import ACTIVE_CHILD_STATUSES, ACCEPTANCE_OUTCOMES


class SuperParentFacts(BaseModel):
    """Durable facts needed by the Super Parent delegation policy."""

    parent_run_id: str
    parent_status: str
    max_child_runs: int
    resolved_child_run_ids: set[str] = Field(default_factory=set[str])
    child_count: int = 0


def work_from_child_run(child: Run, *, resolved: bool = False) -> DelegatedWork:
    """Represent an existing child run as generic delegated work."""
    status = _delegated_status_for_child(child, resolved=resolved)
    return DelegatedWork(
        id=child.id,
        owner_id=child.parent_run_id or "",
        owner_kind="run",
        delegate_kind="run",
        goal=child.parent_slice_id or "",
        generation=_generation_for_child_run(child),
        status=status,
        output_contract="run.evidence.v1",
        policy_metadata={
            "parent_slice_id": child.parent_slice_id,
            "run_status": child.status.value,
            "routine_id": child.routine_id,
        },
    )


def build_super_parent_facts(
    parent: Run,
    children: Sequence[Run],
    *,
    max_child_runs: int,
    resolved_child_run_ids: set[str],
) -> tuple[SuperParentFacts, list[DelegatedWork]]:
    """Build pure policy inputs from parent and child run state."""
    facts = SuperParentFacts(
        parent_run_id=parent.id,
        parent_status=parent.status.value,
        max_child_runs=max_child_runs,
        resolved_child_run_ids=resolved_child_run_ids,
        child_count=len(children),
    )
    works = [
        work_from_child_run(child, resolved=child.id in resolved_child_run_ids)
        for child in children
    ]
    return facts, works


class SuperParentDelegationPolicy:
    """Sequential Super Parent policy over delegated child runs."""

    def reduce(
        self,
        owner_facts: Mapping[str, Any],
        works: Sequence[DelegatedWork],
        results: Mapping[str, DelegateResultEnvelope],
    ) -> DelegationDecision:
        facts = SuperParentFacts.model_validate(owner_facts)
        unresolved = [work for work in works if work.id not in facts.resolved_child_run_ids]
        active = [work for work in unresolved if work.status in ("running", "waiting")]
        if len(active) > 1:
            return DelegationDecision(
                kind="ask_user",
                reason="multiple_active_delegates",
                stable_state="ReviewDelegateResult",
            )
        if active:
            return DelegationDecision(
                kind="wait",
                work_id=active[0].id,
                reason="delegate_still_running",
                stable_state="WaitingOnDelegate",
            )

        for work in unresolved:
            result = results.get(work.id)
            if work.status == "terminal" and result is not None and result.integration_ready:
                return DelegationDecision(kind="integrate", work_id=work.id)
            if work.status == "terminal":
                return DelegationDecision(
                    kind="review",
                    work_id=work.id,
                    reason="terminal_delegate_requires_review",
                    stable_state="ReviewDelegateResult",
                )

        if facts.child_count >= facts.max_child_runs:
            return DelegationDecision(
                kind="ask_user",
                reason="max_delegate_limit_reached",
                stable_state="ReviewDelegateResult",
            )

        return DelegationDecision(kind="launch", reason="ready_for_next_delegate")

    def decision_for_create_child(
        self,
        parent: Run,
        children: Sequence[Run],
        *,
        child_run_id: str,
        max_child_runs: int,
        resolved_child_run_ids: set[str],
    ) -> DelegationDecision:
        """Return the create-child decision without mutating state."""
        if parent.status != RunStatus.ACTIVE:
            return DelegationDecision(
                kind="review",
                work_id=child_run_id,
                reason="parent_not_active",
                stable_state="ReviewDelegateResult",
            )
        for child in children:
            if child.id == child_run_id:
                return DelegationDecision(
                    kind="stale_command_ignored",
                    work_id=child.id,
                    reason="duplicate_child_create",
                    stable_state="StaleCommandIgnored",
                )
        unresolved = [child for child in children if child.id not in resolved_child_run_ids]
        if unresolved:
            return DelegationDecision(
                kind="wait",
                work_id=unresolved[0].id,
                reason="unresolved_child_already_exists",
                stable_state="WaitingOnDelegate",
            )
        if len(children) >= max_child_runs:
            return DelegationDecision(
                kind="ask_user",
                work_id=child_run_id,
                reason="max_child_run_limit_reached",
                stable_state="ReviewDelegateResult",
            )
        return DelegationDecision(kind="launch", work_id=child_run_id)


def _delegated_status_for_child(child: Run, *, resolved: bool) -> DelegatedWorkStatus:
    if resolved:
        return "integrated"
    if child.status.value in ACTIVE_CHILD_STATUSES:
        return "running"
    if child.status == RunStatus.DRAFT:
        return "requested"
    if child.status == RunStatus.PAUSED:
        return "waiting"
    if child.status in (RunStatus.COMPLETED, RunStatus.FAILED):
        return "terminal"
    return "review"


def result_from_child_evidence(
    work_id: str,
    evidence_outcomes: set[str],
    *,
    generation: int = 0,
    invalid_reasons: list[str] | None = None,
) -> DelegateResultEnvelope:
    """Create a delegate result from validated Super Parent evidence outcomes."""
    invalid_reasons = invalid_reasons or []
    return DelegateResultEnvelope(
        work_id=work_id,
        generation=generation,
        terminal_status="completed",
        outcome=",".join(sorted(evidence_outcomes)),
        validation_status="invalid" if invalid_reasons else "valid",
        integration_ready=bool(evidence_outcomes & ACCEPTANCE_OUTCOMES) and not invalid_reasons,
        reasons=tuple(invalid_reasons),
    )


def _generation_for_child_run(child: Run) -> int:
    """Derive a stable command fence generation from durable child timestamps."""
    return max(0, int(child.updated_at.timestamp() * 1_000_000))
