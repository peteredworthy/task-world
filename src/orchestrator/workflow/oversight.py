"""Deterministic reducer for super-parent oversight state."""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, ValidationError

from orchestrator.config import RunStatus
from orchestrator.state import Run


EvidenceOutcome = Literal[
    "verified_fix",
    "bug_not_reproduced",
    "behavior_already_correct",
    "environment_blocked",
    "needs_revision",
    "partial_progress",
    "unrelated_failure",
]

ACCEPTANCE_OUTCOMES: frozenset[str] = frozenset(
    {
        "verified_fix",
        "behavior_already_correct",
    }
)
REVISION_OUTCOMES: frozenset[str] = frozenset(
    {
        "environment_blocked",
        "needs_revision",
        "partial_progress",
        "unrelated_failure",
    }
)
ACTIVE_CHILD_STATUSES: frozenset[str] = frozenset(
    {
        RunStatus.ACTIVE.value,
        RunStatus.STOPPING.value,
    }
)
UNRESOLVED_CHILD_STATUSES: frozenset[str] = frozenset(
    {
        RunStatus.DRAFT.value,
        RunStatus.ACTIVE.value,
        RunStatus.PAUSED.value,
        RunStatus.STOPPING.value,
    }
)
TERMINAL_PARENT_STATUSES: frozenset[str] = frozenset(
    {
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
    }
)


class OversightEvidenceSummary(BaseModel):
    """Evidence facts consumed by the parent reducer."""

    path: str
    slice_id: str = ""
    routine_id: str = ""
    outcome: EvidenceOutcome
    next_recommendation: str = ""
    target_bug_reproduced: str = ""
    summary: str = ""


class RunEvidenceCommand(BaseModel):
    """Command evidence inside a run evidence bundle."""

    command: str
    exit_code: int
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""


class RunEvidenceTestResult(BaseModel):
    """Test result evidence inside a run evidence bundle."""

    name: str
    status: Literal["passed", "failed", "skipped", "not_run"]
    details: str = ""


class RunEvidenceBundle(BaseModel):
    """Full run.evidence.v1 bundle used by parent oversight mechanics."""

    schema_version: Literal["run.evidence.v1"]
    slice_id: str
    routine_id: str
    assumption_tested: str
    summary: str
    commands_run: list[RunEvidenceCommand]
    test_results: list[RunEvidenceTestResult]
    target_bug_reproduced: Literal["reproduced", "not_reproduced", "not_targeted", "unknown"]
    real_frontend_path_exercised: bool
    real_execution_surface: str
    files_changed: list[str]
    evidence_files: list[str]
    open_uncertainties: list[str]
    next_recommendation: Literal["proceed", "replan", "stop", "environment_blocked"]
    outcome: EvidenceOutcome


class TargetInventoryItem(BaseModel):
    """Simplified target inventory entry used by terminal completion checks."""

    schema_version: Literal["super_parent.target_inventory.v1"] = "super_parent.target_inventory.v1"
    id: str
    in_scope: bool = True
    resolved: bool = False


class FinalValidationMarker(BaseModel):
    """Explicit integrated validation marker for terminal completion."""

    schema_version: Literal["super_parent.final_validation.v1"] = "super_parent.final_validation.v1"
    passed: bool
    integration_scope: Literal["integrated", "final"] = "integrated"
    integrated_commit_sha: str = Field(min_length=7)
    report_path: str = Field(min_length=1)
    commands_run: list[RunEvidenceCommand] = Field(min_length=1)
    evidence_files: list[str] = Field(min_length=1)
    service_verified: bool = False


class ChildOversightSummary(BaseModel):
    """Parent-facing summary for one child run."""

    run_id: str
    slice_id: str
    status: str
    routine_id: str | None = None
    created_at: str
    evidence: list[OversightEvidenceSummary] = Field(default_factory=list[OversightEvidenceSummary])
    invalid_evidence_paths: list[str] = Field(default_factory=list[str])
    blocking_reasons: list[str] = Field(default_factory=list[str])


class OversightAttentionItem(BaseModel):
    """A child or slice condition that requires parent/user attention."""

    kind: Literal["child", "slice", "parent"]
    run_id: str | None = None
    slice_id: str | None = None
    reason: str


class OversightTerminalGuard(BaseModel):
    """Whether a parent run may transition terminally."""

    can_complete: bool
    blocking_reasons: list[str] = Field(default_factory=list[str])
    blocking_child_run_ids: list[str] = Field(default_factory=list[str])


class ParentOversightSnapshot(BaseModel):
    """Computed durable oversight payload for a super-parent run."""

    schema_version: Literal["super_parent.oversight.v1"] = "super_parent.oversight.v1"
    parent_run_id: str
    parent_status: str
    current_understanding: Any = Field(default_factory=dict)
    target_inventory: list[TargetInventoryItem] = Field(default_factory=list[TargetInventoryItem])
    final_validation: FinalValidationMarker | None = None
    decisions: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    slices: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    last_child_run_id: str | None = None
    last_decision: str | None = None
    child_waits: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    accepted_child_run_ids: list[str] = Field(default_factory=list[str])
    accepted_children: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    rejected_child_run_ids: list[str] = Field(default_factory=list[str])
    abandoned_child_run_ids: list[str] = Field(default_factory=list[str])
    merge_conflicts: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    max_child_runs: int
    child_count: int
    child_counts: dict[str, int] = Field(default_factory=dict[str, int])
    child_summaries: list[ChildOversightSummary] = Field(
        default_factory=list[ChildOversightSummary]
    )
    attempt_counts_by_slice: dict[str, dict[str, int]] = Field(
        default_factory=dict[str, dict[str, int]]
    )
    active_child_run_ids: list[str] = Field(default_factory=list[str])
    merge_queue: list[str] = Field(default_factory=list[str])
    attention_items: list[OversightAttentionItem] = Field(
        default_factory=list[OversightAttentionItem]
    )
    stalled_slices: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    illegal_state_reasons: list[str] = Field(default_factory=list[str])
    terminal_guard: OversightTerminalGuard
    next_parent_action: Literal[
        "launch_child",
        "wait_for_child",
        "accept_child",
        "review_child_evidence",
        "ask_user",
        "complete_parent",
    ]


def reduce_parent_oversight_state(
    parent_run: Run,
    child_runs: Sequence[Run],
    evidence_by_run_id: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    *,
    max_child_runs: int = 20,
    stalled_attempt_threshold: int = 3,
) -> dict[str, Any]:
    """Compute JSON-safe oversight state for storage on the parent run."""
    snapshot = reduce_parent_oversight(
        parent_run,
        child_runs,
        evidence_by_run_id,
        max_child_runs=max_child_runs,
        stalled_attempt_threshold=stalled_attempt_threshold,
    )
    return snapshot.model_dump(mode="json")


def reduce_parent_oversight(
    parent_run: Run,
    child_runs: Sequence[Run],
    evidence_by_run_id: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    *,
    max_child_runs: int = 20,
    stalled_attempt_threshold: int = 3,
) -> ParentOversightSnapshot:
    """Reduce parent/child run facts into a deterministic oversight snapshot."""
    evidence_by_run_id = evidence_by_run_id or {}
    existing_state = parent_run.oversight_state or {}
    target_inventory, target_inventory_blocking_reasons = _parse_target_inventory(
        existing_state.get("target_inventory")
    )
    final_validation = _parse_final_validation(existing_state.get("final_validation"))
    accepted_children = _list_of_dicts(existing_state.get("accepted_children"))
    merge_conflicts = _list_of_dicts(existing_state.get("merge_conflicts"))
    accepted_child_run_ids = _extract_child_id_set(
        existing_state,
        "accepted_child_run_ids",
        "accepted_children",
    )
    rejected_child_run_ids = _extract_child_id_set(existing_state, "rejected_child_run_ids")
    abandoned_child_run_ids = _extract_child_id_set(existing_state, "abandoned_child_run_ids")
    resolved_child_run_ids = (
        accepted_child_run_ids
        | rejected_child_run_ids
        | abandoned_child_run_ids
        | _extract_child_id_set(existing_state, "closed_child_run_ids")
    )

    child_counts: Counter[str] = Counter()
    attempt_counts: dict[str, Counter[str]] = {}
    child_summaries: list[ChildOversightSummary] = []
    attention_items: list[OversightAttentionItem] = []
    active_child_run_ids: list[str] = []
    merge_queue: list[str] = []
    blocking_child_run_ids: set[str] = set()
    blocking_reasons: list[str] = []
    illegal_state_reasons: list[str] = []

    sorted_children = sorted(
        child_runs,
        key=lambda run: (
            run.created_at.isoformat(),
            run.id,
        ),
    )

    for child in sorted_children:
        status = _status_value(child.status)
        child_counts[status] += 1
        evidence, invalid_paths = _parse_evidence_items(evidence_by_run_id.get(child.id, ()))
        slice_id = _slice_id_for_child(child, evidence)
        counters = attempt_counts.setdefault(slice_id, Counter())
        counters["total"] += 1

        outcomes = {item.outcome for item in evidence}
        child_blocking_reasons = _child_blocking_reasons(
            parent_run=parent_run,
            child_run=child,
            status=status,
            outcomes=outcomes,
            has_evidence=bool(evidence),
            invalid_evidence_paths=invalid_paths,
            accepted_child_run_ids=accepted_child_run_ids,
            resolved_child_run_ids=resolved_child_run_ids,
        )

        if status in ACTIVE_CHILD_STATUSES:
            active_child_run_ids.append(child.id)
        if status == RunStatus.COMPLETED.value and outcomes & ACCEPTANCE_OUTCOMES:
            counters["accepted"] += 1
            if child.id not in accepted_child_run_ids:
                merge_queue.append(child.id)
        if status == RunStatus.FAILED.value or outcomes & REVISION_OUTCOMES:
            counters["failed_or_revision"] += 1
        if child_blocking_reasons:
            counters["needs_attention"] += 1
            blocking_child_run_ids.add(child.id)
            attention_items.append(
                OversightAttentionItem(
                    kind="child",
                    run_id=child.id,
                    slice_id=slice_id,
                    reason="; ".join(child_blocking_reasons),
                )
            )

        child_summaries.append(
            ChildOversightSummary(
                run_id=child.id,
                slice_id=slice_id,
                status=status,
                routine_id=child.routine_id,
                created_at=child.created_at.isoformat(),
                evidence=evidence,
                invalid_evidence_paths=invalid_paths,
                blocking_reasons=child_blocking_reasons,
            )
        )

    stalled_slices: list[dict[str, Any]] = []
    for slice_id in sorted(attempt_counts):
        counters = attempt_counts[slice_id]
        if (
            counters["failed_or_revision"] >= stalled_attempt_threshold
            and counters["accepted"] == 0
        ):
            reason = (
                f"{counters['failed_or_revision']} failed/revision attempts for slice {slice_id}"
            )
            stalled_slices.append(
                {
                    "slice_id": slice_id,
                    "attempt_count": counters["failed_or_revision"],
                    "reason": reason,
                }
            )
            attention_items.append(
                OversightAttentionItem(kind="slice", slice_id=slice_id, reason=reason)
            )

    parent_status = _status_value(parent_run.status)
    if parent_status == RunStatus.ACTIVE.value and len(active_child_run_ids) > 1:
        illegal_state_reasons.append("active_parent_has_multiple_active_children")
    if parent_status == RunStatus.PAUSED.value and active_child_run_ids:
        illegal_state_reasons.append("paused_parent_has_active_children")
    if parent_status in TERMINAL_PARENT_STATUSES and blocking_child_run_ids:
        illegal_state_reasons.append("terminal_parent_has_unresolved_children")
    if len(sorted_children) > max_child_runs:
        attention_items.append(
            OversightAttentionItem(
                kind="parent",
                reason=f"parent has {len(sorted_children)} child runs, exceeding {max_child_runs}",
            )
        )
        blocking_reasons.append("max_child_run_limit_exceeded")
    if not sorted_children:
        blocking_reasons.append("no_child_runs")
    for conflict in merge_conflicts:
        conflict_child_id = conflict.get("child_run_id")
        conflict_slice_id = conflict.get("parent_slice_id")
        attention_items.append(
            OversightAttentionItem(
                kind="parent",
                run_id=conflict_child_id if isinstance(conflict_child_id, str) else None,
                slice_id=conflict_slice_id if isinstance(conflict_slice_id, str) else None,
                reason="child_merge_conflict_requires_resolution",
            )
        )
        blocking_reasons.append("child_merge_conflict_requires_resolution")

    for child_summary in child_summaries:
        for reason in child_summary.blocking_reasons:
            blocking_reasons.append(f"{child_summary.run_id}: {reason}")
    for stalled_slice in stalled_slices:
        blocking_reasons.append(str(stalled_slice["reason"]))
    for reason in illegal_state_reasons:
        blocking_reasons.append(f"illegal_state: {reason}")
    for reason in target_inventory_blocking_reasons:
        blocking_reasons.append(reason)
    blocking_reasons.extend(_final_validation_blocking_reasons(final_validation))

    terminal_guard = OversightTerminalGuard(
        can_complete=not blocking_reasons,
        blocking_reasons=sorted(dict.fromkeys(blocking_reasons)),
        blocking_child_run_ids=sorted(blocking_child_run_ids),
    )
    next_parent_action = _next_parent_action(
        terminal_guard=terminal_guard,
        illegal_state_reasons=illegal_state_reasons,
        stalled_slices=stalled_slices,
        active_child_run_ids=active_child_run_ids,
        merge_queue=merge_queue,
        attention_items=attention_items,
        child_count=len(sorted_children),
    )

    return ParentOversightSnapshot(
        parent_run_id=parent_run.id,
        parent_status=parent_status,
        current_understanding=existing_state.get("current_understanding", {}),
        target_inventory=target_inventory,
        final_validation=final_validation,
        decisions=_list_of_dicts(existing_state.get("decisions")),
        slices=_list_of_dicts(existing_state.get("slices")),
        last_child_run_id=existing_state.get("last_child_run_id")
        if isinstance(existing_state.get("last_child_run_id"), str)
        else None,
        last_decision=existing_state.get("last_decision")
        if isinstance(existing_state.get("last_decision"), str)
        else None,
        child_waits=_list_of_dicts(existing_state.get("child_waits")),
        accepted_child_run_ids=sorted(accepted_child_run_ids),
        accepted_children=accepted_children,
        rejected_child_run_ids=sorted(rejected_child_run_ids),
        abandoned_child_run_ids=sorted(abandoned_child_run_ids),
        merge_conflicts=merge_conflicts,
        max_child_runs=max_child_runs,
        child_count=len(sorted_children),
        child_counts=dict(sorted(child_counts.items())),
        child_summaries=child_summaries,
        attempt_counts_by_slice={
            slice_id: dict(sorted(counters.items()))
            for slice_id, counters in sorted(attempt_counts.items())
        },
        active_child_run_ids=sorted(active_child_run_ids),
        merge_queue=sorted(dict.fromkeys(merge_queue)),
        attention_items=attention_items,
        stalled_slices=stalled_slices,
        illegal_state_reasons=illegal_state_reasons,
        terminal_guard=terminal_guard,
        next_parent_action=next_parent_action,
    )


def _child_blocking_reasons(
    *,
    parent_run: Run,
    child_run: Run,
    status: str,
    outcomes: set[str],
    has_evidence: bool,
    invalid_evidence_paths: list[str],
    accepted_child_run_ids: set[str],
    resolved_child_run_ids: set[str],
) -> list[str]:
    if child_run.id in resolved_child_run_ids:
        return []

    reasons: list[str] = []
    if child_run.id == parent_run.id:
        reasons.append("child_run_matches_parent_run")
    if child_run.parent_run_id not in (None, parent_run.id):
        reasons.append("child_linked_to_different_parent")
    if not child_run.parent_slice_id:
        reasons.append("child_missing_parent_slice_id")
    if invalid_evidence_paths:
        reasons.append("invalid_evidence_bundle")
    if status in UNRESOLVED_CHILD_STATUSES:
        reasons.append(f"child_not_terminal:{status}")
    elif status == RunStatus.COMPLETED.value:
        if not has_evidence:
            reasons.append("completed_child_missing_evidence")
        elif outcomes & ACCEPTANCE_OUTCOMES:
            if child_run.id not in accepted_child_run_ids:
                reasons.append("accepted_child_not_merged")
        elif "bug_not_reproduced" in outcomes:
            reasons.append("bug_not_reproduced_requires_parent_decision")
        elif outcomes & REVISION_OUTCOMES:
            reasons.append("child_evidence_requires_revision")
    elif status == RunStatus.FAILED.value:
        reasons.append("failed_child_unresolved")
    return sorted(dict.fromkeys(reasons))


def _next_parent_action(
    *,
    terminal_guard: OversightTerminalGuard,
    illegal_state_reasons: list[str],
    stalled_slices: list[dict[str, Any]],
    active_child_run_ids: list[str],
    merge_queue: list[str],
    attention_items: list[OversightAttentionItem],
    child_count: int,
) -> Literal[
    "launch_child",
    "wait_for_child",
    "accept_child",
    "review_child_evidence",
    "ask_user",
    "complete_parent",
]:
    if illegal_state_reasons or stalled_slices:
        return "ask_user"
    if active_child_run_ids:
        return "wait_for_child"
    if merge_queue:
        return "accept_child"
    if attention_items:
        return "review_child_evidence"
    if terminal_guard.can_complete and child_count > 0:
        return "complete_parent"
    return "launch_child"


def _parse_evidence_items(
    raw_items: Sequence[Mapping[str, Any]],
) -> tuple[list[OversightEvidenceSummary], list[str]]:
    evidence: list[OversightEvidenceSummary] = []
    invalid_paths: list[str] = []
    for raw_item in sorted(raw_items, key=lambda item: str(item.get("path", ""))):
        bundle_obj = raw_item.get("bundle")
        bundle: Mapping[str, Any] = (
            cast(Mapping[str, Any], bundle_obj) if isinstance(bundle_obj, Mapping) else raw_item
        )
        path = _string_or_empty(raw_item.get("path")) or "<unknown>"
        try:
            bundle_model = RunEvidenceBundle.model_validate(bundle)
            evidence.append(
                OversightEvidenceSummary.model_validate(
                    {
                        "path": path,
                        "slice_id": bundle_model.slice_id,
                        "routine_id": bundle_model.routine_id,
                        "outcome": bundle_model.outcome,
                        "next_recommendation": bundle_model.next_recommendation,
                        "target_bug_reproduced": bundle_model.target_bug_reproduced,
                        "summary": bundle_model.summary,
                    }
                )
            )
        except ValidationError:
            invalid_paths.append(path)
    return evidence, sorted(invalid_paths)


def _slice_id_for_child(child_run: Run, evidence: Sequence[OversightEvidenceSummary]) -> str:
    if child_run.parent_slice_id:
        return child_run.parent_slice_id
    for item in evidence:
        if item.slice_id:
            return item.slice_id
    return "unassigned"


def _extract_child_id_set(state: Mapping[str, Any], *keys: str) -> set[str]:
    child_ids: set[str] = set()
    for key in keys:
        value = state.get(key)
        if isinstance(value, str):
            child_ids.add(value)
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, str)):
            for item in cast(Sequence[Any], value):
                if isinstance(item, str):
                    child_ids.add(item)
                elif isinstance(item, Mapping):
                    mapping = cast(Mapping[str, Any], item)
                    child_id = mapping.get("child_run_id") or mapping.get("run_id")
                    if isinstance(child_id, str):
                        child_ids.add(child_id)
    return child_ids


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (bytes, str)):
        return []
    return [
        dict(cast(Mapping[str, Any], item))
        for item in cast(Sequence[Any], value)
        if isinstance(item, Mapping)
    ]


def _parse_target_inventory(
    value: Any,
) -> tuple[list[TargetInventoryItem], list[str]]:
    if not isinstance(value, Sequence) or isinstance(value, (bytes, str)):
        return [], ["target_inventory_missing"]

    parsed_items: list[TargetInventoryItem] = []
    blocking_reasons: list[str] = []
    raw_items = cast(Sequence[Any], value)
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, Mapping):
            blocking_reasons.append(f"target_inventory_item_invalid:{index}")
            continue
        item = cast(Mapping[str, Any], raw_item)
        try:
            parsed_items.append(TargetInventoryItem.model_validate(item))
        except ValidationError:
            item_id = item.get("id")
            if not isinstance(item_id, str):
                blocking_reasons.append(f"target_inventory_item_invalid:{index}")
            else:
                blocking_reasons.append(f"target_inventory_item_invalid:{item_id}")

    if not parsed_items and not blocking_reasons:
        blocking_reasons.append("target_inventory_missing")

    unresolved_items = [item.id for item in parsed_items if item.in_scope and not item.resolved]
    if unresolved_items:
        blocking_reasons.extend(
            [f"unresolved_target_inventory:{item}" for item in unresolved_items]
        )

    return parsed_items, sorted(dict.fromkeys(blocking_reasons))


def _parse_final_validation(value: Any) -> FinalValidationMarker | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return FinalValidationMarker.model_validate(value)
    except ValidationError:
        return None


def _final_validation_blocking_reasons(marker: FinalValidationMarker | None) -> list[str]:
    if marker is None:
        return ["final_validation_marker_missing"]
    reasons: list[str] = []
    if not marker.passed:
        reasons.append("final_validation_not_passed")
    if not marker.service_verified:
        reasons.append("final_validation_not_service_verified")
    if not marker.integrated_commit_sha.strip():
        reasons.append("final_validation_missing_integrated_commit")
    if not marker.report_path.strip():
        reasons.append("final_validation_missing_report_path")
    if not marker.commands_run:
        reasons.append("final_validation_missing_commands")
    if not marker.evidence_files:
        reasons.append("final_validation_missing_evidence_files")
    return reasons


def _status_value(status: RunStatus | str) -> str:
    return status.value if isinstance(status, RunStatus) else str(status)


def _string_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""
