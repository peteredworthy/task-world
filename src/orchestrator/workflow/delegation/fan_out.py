"""Fan-out task policy over generic delegated-work primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from orchestrator.config import RunStatus, TaskStatus
from orchestrator.state import Run, TaskState
from orchestrator.workflow.delegation.models import (
    DelegateResultEnvelope,
    DelegatedWork,
    DelegatedWorkStatus,
    DelegationDecision,
)


class FanOutFacts(BaseModel):
    """Durable facts needed by the fan-out delegation policy."""

    parent_task_id: str
    parent_status: str
    child_count: int = 0
    completed_child_ids: set[str] = Field(default_factory=set[str])
    failed_child_ids: set[str] = Field(default_factory=set[str])


def work_from_fan_out_child(child: TaskState) -> DelegatedWork:
    """Represent a fan-out child task as generic delegated work."""
    return DelegatedWork(
        id=child.id,
        owner_id=child.parent_task_id or "",
        owner_kind="task",
        delegate_kind="task",
        goal=child.fan_out_input or child.title,
        generation=child.current_attempt,
        status=_delegated_status_for_task(child.status),
        output_contract="fan_out.output.v1",
        policy_metadata={
            "config_id": child.config_id,
            "child_id": child.child_id,
            "fan_out_index": child.fan_out_index,
            "fan_out_input": child.fan_out_input,
            "fan_out_output": child.fan_out_output,
            "task_status": child.status.value,
        },
    )


def build_fan_out_facts(
    parent_task: TaskState,
    children: Sequence[TaskState],
) -> tuple[FanOutFacts, list[DelegatedWork]]:
    """Build pure policy inputs from fan-out parent and child task state."""
    facts = FanOutFacts(
        parent_task_id=parent_task.id,
        parent_status=parent_task.status.value,
        child_count=len(children),
        completed_child_ids={
            child.id for child in children if child.status == TaskStatus.COMPLETED
        },
        failed_child_ids={child.id for child in children if child.status == TaskStatus.FAILED},
    )
    return facts, [work_from_fan_out_child(child) for child in children]


class FanOutDelegationPolicy:
    """Bounded-parallel fan-out policy over delegated child tasks."""

    def reduce(
        self,
        owner_facts: Mapping[str, Any],
        works: Sequence[DelegatedWork],
        results: Mapping[str, DelegateResultEnvelope],
    ) -> DelegationDecision:
        facts = FanOutFacts.model_validate(owner_facts)
        active = [work for work in works if work.status in ("requested", "running", "waiting")]
        if active:
            return DelegationDecision(
                kind="wait",
                work_id=active[0].id,
                reason="fan_out_children_still_running",
                stable_state="WaitingOnDelegate",
                payload={"active_child_count": len(active)},
            )
        failed = [work for work in works if work.id in facts.failed_child_ids]
        if failed:
            return DelegationDecision(
                kind="reject",
                work_id=failed[0].id,
                reason="fan_out_child_failed",
                stable_state="NeedsRevision",
                payload={"failed_child_count": len(failed)},
            )
        if facts.child_count == 0 or len(works) == len(facts.completed_child_ids):
            return DelegationDecision(
                kind="complete",
                reason="fan_out_children_complete",
                payload={"child_count": facts.child_count},
            )
        return DelegationDecision(
            kind="review",
            reason="fan_out_state_requires_review",
            stable_state="ReviewDelegateResult",
        )

    def decision_for_start_parent(self, run: Run, task: TaskState) -> DelegationDecision:
        """Return the start-parent decision without mutating state."""
        if run.status != RunStatus.ACTIVE:
            return DelegationDecision(
                kind="review",
                work_id=task.id,
                reason="run_not_active",
                stable_state="ReviewDelegateResult",
            )
        if task.parent_task_id is not None:
            return DelegationDecision(
                kind="review",
                work_id=task.id,
                reason="task_is_fan_out_child",
                stable_state="ReviewDelegateResult",
            )
        if task.status == TaskStatus.FAN_OUT_RUNNING:
            return DelegationDecision(
                kind="wait",
                work_id=task.id,
                reason="fan_out_parent_already_running",
                stable_state="WaitingOnDelegate",
            )
        if task.status in (TaskStatus.PENDING, TaskStatus.BUILDING):
            return DelegationDecision(kind="launch", work_id=task.id)
        return DelegationDecision(
            kind="review",
            work_id=task.id,
            reason="fan_out_parent_not_startable",
            stable_state="ReviewDelegateResult",
        )

    def decision_for_parent_completion(
        self,
        old_status_value: str,
        *,
        all_passed: bool,
        to_verifying: bool,
    ) -> DelegationDecision:
        """Return the fan-out parent completion decision without mutating state."""
        if old_status_value in (TaskStatus.COMPLETED.value, TaskStatus.VERIFYING.value):
            return DelegationDecision(
                kind="stale_command_ignored",
                reason="fan_out_parent_already_completed",
                stable_state="StaleCommandIgnored",
            )
        if old_status_value != TaskStatus.FAN_OUT_RUNNING.value:
            return DelegationDecision(
                kind="review",
                reason="fan_out_parent_not_running",
                stable_state="ReviewDelegateResult",
            )
        if not all_passed:
            return DelegationDecision(
                kind="reject",
                reason="fan_out_child_failed",
                stable_state="NeedsRevision",
                payload={"new_status": TaskStatus.FAILED.value},
            )
        if to_verifying:
            return DelegationDecision(
                kind="complete",
                reason="fan_out_parent_needs_verification",
                stable_state="AwaitingGate",
                payload={"new_status": TaskStatus.VERIFYING.value},
            )
        return DelegationDecision(
            kind="complete",
            reason="fan_out_children_complete",
            payload={"new_status": TaskStatus.COMPLETED.value},
        )


def _delegated_status_for_task(status: TaskStatus) -> DelegatedWorkStatus:
    if status == TaskStatus.PENDING:
        return "requested"
    if status in (
        TaskStatus.BUILDING,
        TaskStatus.PENDING_USER_ACTION,
        TaskStatus.VERIFYING,
        TaskStatus.RECOVERING,
        TaskStatus.FAN_OUT_RUNNING,
    ):
        return "running"
    if status == TaskStatus.COMPLETED:
        return "terminal"
    if status == TaskStatus.FAILED:
        return "terminal"
    return "review"
