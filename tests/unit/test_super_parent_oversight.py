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
            "schema_version": "run.evidence.v1",
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


def _final_validation(
    *,
    passed: bool = True,
    service_verified: bool = True,
) -> dict[str, Any]:
    return {
        "schema_version": "super_parent.final_validation.v1",
        "passed": passed,
        "integrated_commit_sha": "abc1234",
        "report_path": "docs/super-parent/final-report.md",
        "commands_run": [
            {
                "command": "uv run pytest tests/unit/test_super_parent_oversight.py",
                "exit_code": 0 if passed else 1,
                "stdout_excerpt": "",
                "stderr_excerpt": "",
            }
        ],
        "evidence_files": ["docs/super-parent/final-report.md"],
        "service_verified": service_verified,
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


def test_malformed_acceptance_evidence_is_invalid_and_not_mergeable() -> None:
    parent = _run("parent", status=RunStatus.ACTIVE)
    child = _run(
        "child",
        status=RunStatus.COMPLETED,
        parent_run_id="parent",
        parent_slice_id="slice-1",
    )
    malformed_evidence = {
        "path": "docs/slice-1/evidence.json",
        "bundle": {
            "schema_version": "run.evidence.v1",
            "outcome": "verified_fix",
        },
    }

    snapshot = reduce_parent_oversight(parent, [child], {"child": [malformed_evidence]})

    assert snapshot.merge_queue == []
    assert snapshot.child_summaries[0].invalid_evidence_paths == ["docs/slice-1/evidence.json"]
    assert snapshot.child_summaries[0].invalid_evidence[0].errors[0].field == "slice_id"
    assert snapshot.child_summaries[0].blocking_reasons == [
        "completed_child_missing_evidence",
        "invalid_evidence_bundle",
    ]
    assert "child: invalid_evidence_bundle" in snapshot.terminal_guard.blocking_reasons


def test_mismatched_child_evidence_is_invalid_and_not_mergeable() -> None:
    parent = _run("parent", status=RunStatus.ACTIVE)
    child = _run(
        "child",
        status=RunStatus.COMPLETED,
        parent_run_id="parent",
        parent_slice_id="slice-expected",
    )
    child.routine_id = "expected-routine"
    mismatched = _evidence("verified_fix", slice_id="wrong-slice")
    mismatched["bundle"]["routine_id"] = "wrong-routine"

    snapshot = reduce_parent_oversight(parent, [child], {"child": [mismatched]})

    invalid = snapshot.child_summaries[0].invalid_evidence[0]
    assert snapshot.merge_queue == []
    assert invalid.path == "docs/wrong-slice/verified_fix-evidence.json"
    assert [(error.field, error.message) for error in invalid.errors] == [
        ("slice_id", "expected 'slice-expected', got 'wrong-slice'"),
        ("routine_id", "expected 'expected-routine', got 'wrong-routine'"),
    ]


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


def test_parent_cannot_complete_without_target_inventory() -> None:
    parent = _run(
        "parent",
        status=RunStatus.ACTIVE,
        oversight_state={"accepted_child_run_ids": ["child"]},
    )
    child = _run(
        "child",
        status=RunStatus.COMPLETED,
        parent_run_id="parent",
        parent_slice_id="slice-1",
    )

    snapshot = reduce_parent_oversight(
        parent,
        [child],
        {"child": [_evidence("verified_fix")]},
    )

    assert not snapshot.terminal_guard.can_complete
    assert "target_inventory_missing" in snapshot.terminal_guard.blocking_reasons
    assert snapshot.final_validation is None


def test_parent_cannot_complete_with_unresolved_in_scope_inventory_or_failed_validation() -> None:
    parent = _run(
        "parent",
        status=RunStatus.ACTIVE,
        oversight_state={
            "accepted_child_run_ids": ["child"],
            "target_inventory": [{"id": "bug-1", "in_scope": True, "resolved": False}],
            "final_validation": _final_validation(passed=False),
        },
    )
    child = _run(
        "child",
        status=RunStatus.COMPLETED,
        parent_run_id="parent",
        parent_slice_id="slice-1",
    )

    snapshot = reduce_parent_oversight(
        parent,
        [child],
        {"child": [_evidence("verified_fix")]},
    )

    assert not snapshot.terminal_guard.can_complete
    assert "unresolved_target_inventory:bug-1" in snapshot.terminal_guard.blocking_reasons
    assert "final_validation_not_passed" in snapshot.terminal_guard.blocking_reasons


def test_parent_can_complete_only_with_resolved_inventory_and_passed_validation() -> None:
    parent = _run(
        "parent",
        status=RunStatus.ACTIVE,
        oversight_state={
            "accepted_child_run_ids": ["child"],
            "target_inventory": [{"id": "bug-1", "in_scope": True, "resolved": True}],
            "final_validation": _final_validation(passed=True),
        },
    )
    child = _run(
        "child",
        status=RunStatus.COMPLETED,
        parent_run_id="parent",
        parent_slice_id="slice-1",
    )

    snapshot = reduce_parent_oversight(
        parent,
        [child],
        {"child": [_evidence("verified_fix")]},
    )

    assert snapshot.terminal_guard.can_complete
    assert snapshot.next_parent_action == "complete_parent"
    assert snapshot.final_validation is not None
    assert snapshot.final_validation.passed is True


def test_parent_cannot_complete_with_unverified_final_validation() -> None:
    parent = _run(
        "parent",
        status=RunStatus.ACTIVE,
        oversight_state={
            "accepted_child_run_ids": ["child"],
            "target_inventory": [{"id": "bug-1", "in_scope": True, "resolved": True}],
            "final_validation": _final_validation(passed=True, service_verified=False),
        },
    )
    child = _run(
        "child",
        status=RunStatus.COMPLETED,
        parent_run_id="parent",
        parent_slice_id="slice-1",
    )

    snapshot = reduce_parent_oversight(
        parent,
        [child],
        {"child": [_evidence("verified_fix")]},
    )

    assert not snapshot.terminal_guard.can_complete
    assert "final_validation_not_service_verified" in snapshot.terminal_guard.blocking_reasons


def test_run_evidence_schema_accepts_expanded_outcomes() -> None:
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
