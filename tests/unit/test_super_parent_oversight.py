"""Unit tests for deterministic super-parent oversight reduction."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from orchestrator.api import EvidenceBundleSchema
from orchestrator.config import RunStatus
from orchestrator.state import Run
from orchestrator.workflow import reduce_parent_oversight, reduce_parent_oversight_state


def _run(
    run_id: str,
    *,
    status: RunStatus,
    parent_run_id: str | None = None,
    parent_slice_id: str | None = None,
    oversight_state: dict[str, Any] | None = None,
    offset_minutes: int = 0,
) -> Run:
    created_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=offset_minutes)
    return Run(
        id=run_id,
        repo_name="task-world",
        status=status,
        parent_run_id=parent_run_id,
        parent_slice_id=parent_slice_id,
        oversight_state=oversight_state or {},
        routine_id="slice-routine",
        created_at=created_at,
        updated_at=created_at,
    )


def _evidence(outcome: str, *, slice_id: str = "slice-1") -> dict[str, Any]:
    return {
        "path": f"docs/{slice_id}/{outcome}-evidence.json",
        "bundle": {
            "schema_version": "phase4.evidence.v1",
            "slice_id": slice_id,
            "routine_id": "slice-routine",
            "assumption_tested": "The child completed the slice.",
            "summary": f"Outcome: {outcome}",
            "commands_run": [],
            "test_results": [],
            "target_bug_reproduced": "not_targeted",
            "real_frontend_path_exercised": False,
            "real_execution_surface": "unit",
            "files_changed": [],
            "evidence_files": [],
            "open_uncertainties": [],
            "next_recommendation": "proceed",
            "outcome": outcome,
        },
    }


def test_reduce_parent_oversight_is_deterministic() -> None:
    parent = _run("parent", status=RunStatus.ACTIVE)
    child = _run(
        "child",
        status=RunStatus.COMPLETED,
        parent_run_id="parent",
        parent_slice_id="slice-1",
    )
    evidence = {"child": [_evidence("verified_fix")]}

    first = reduce_parent_oversight_state(parent, [child], evidence)
    second = reduce_parent_oversight_state(parent, [child], evidence)

    assert first == second
    assert first["merge_queue"] == ["child"]
    assert first["next_parent_action"] == "accept_child"


def test_active_parent_with_two_active_children_is_illegal() -> None:
    parent = _run("parent", status=RunStatus.ACTIVE)
    children = [
        _run(
            "child-a",
            status=RunStatus.ACTIVE,
            parent_run_id="parent",
            parent_slice_id="slice-1",
        ),
        _run(
            "child-b",
            status=RunStatus.ACTIVE,
            parent_run_id="parent",
            parent_slice_id="slice-2",
            offset_minutes=1,
        ),
    ]

    snapshot = reduce_parent_oversight(parent, children)

    assert snapshot.active_child_run_ids == ["child-a", "child-b"]
    assert "active_parent_has_multiple_active_children" in snapshot.illegal_state_reasons
    assert snapshot.next_parent_action == "ask_user"
    assert not snapshot.terminal_guard.can_complete


def test_completed_accepted_child_blocks_parent_until_merged() -> None:
    parent = _run("parent", status=RunStatus.ACTIVE)
    child = _run(
        "child",
        status=RunStatus.COMPLETED,
        parent_run_id="parent",
        parent_slice_id="slice-1",
    )

    snapshot = reduce_parent_oversight(parent, [child], {"child": [_evidence("verified_fix")]})

    assert snapshot.merge_queue == ["child"]
    assert snapshot.terminal_guard.blocking_child_run_ids == ["child"]
    assert "child: accepted_child_not_merged" in snapshot.terminal_guard.blocking_reasons


def test_bug_not_reproduced_requires_parent_decision() -> None:
    parent = _run("parent", status=RunStatus.ACTIVE)
    child = _run(
        "child",
        status=RunStatus.COMPLETED,
        parent_run_id="parent",
        parent_slice_id="slice-1",
    )

    snapshot = reduce_parent_oversight(
        parent,
        [child],
        {"child": [_evidence("bug_not_reproduced")]},
    )

    assert snapshot.next_parent_action == "review_child_evidence"
    assert snapshot.attention_items[0].reason == "bug_not_reproduced_requires_parent_decision"
    assert not snapshot.terminal_guard.can_complete


def test_three_failed_or_revision_attempts_stall_slice() -> None:
    parent = _run("parent", status=RunStatus.ACTIVE)
    children = [
        _run(
            "child-a",
            status=RunStatus.FAILED,
            parent_run_id="parent",
            parent_slice_id="slice-1",
        ),
        _run(
            "child-b",
            status=RunStatus.COMPLETED,
            parent_run_id="parent",
            parent_slice_id="slice-1",
            offset_minutes=1,
        ),
        _run(
            "child-c",
            status=RunStatus.COMPLETED,
            parent_run_id="parent",
            parent_slice_id="slice-1",
            offset_minutes=2,
        ),
    ]
    evidence = {
        "child-b": [_evidence("needs_revision")],
        "child-c": [_evidence("partial_progress")],
    }

    snapshot = reduce_parent_oversight(parent, children, evidence)

    assert snapshot.next_parent_action == "ask_user"
    assert snapshot.stalled_slices == [
        {
            "slice_id": "slice-1",
            "attempt_count": 3,
            "reason": "3 failed/revision attempts for slice slice-1",
        }
    ]


def test_phase4_evidence_schema_accepts_expanded_outcomes() -> None:
    for outcome in (
        "verified_fix",
        "bug_not_reproduced",
        "behavior_already_correct",
        "environment_blocked",
        "needs_revision",
        "partial_progress",
        "unrelated_failure",
    ):
        assert EvidenceBundleSchema.model_validate(_evidence(outcome)["bundle"]).outcome == outcome

    invalid = _evidence("not_a_real_outcome")["bundle"]
    with pytest.raises(ValueError):
        EvidenceBundleSchema.model_validate(invalid)
