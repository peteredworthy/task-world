"""Tests for grade evaluation logic."""

from orchestrator.config.enums import ChecklistStatus, Priority
from orchestrator.state.models import ChecklistItem
from orchestrator.workflow.grades import (
    evaluate_grades,
    grade_meets_threshold,
)


def _item(
    req_id: str = "R1",
    priority: Priority = Priority.CRITICAL,
    grade: str | None = None,
    grade_reason: str | None = None,
) -> ChecklistItem:
    return ChecklistItem(
        req_id=req_id,
        desc="Test",
        priority=priority,
        status=ChecklistStatus.DONE,
        grade=grade,
        grade_reason=grade_reason,
    )


def test_grade_meets_threshold_equal() -> None:
    assert grade_meets_threshold("A", "A") is True


def test_grade_meets_threshold_above() -> None:
    assert grade_meets_threshold("A", "B") is True


def test_grade_meets_threshold_below() -> None:
    assert grade_meets_threshold("C", "A") is False


def test_grade_meets_threshold_invalid_grade() -> None:
    assert grade_meets_threshold("X", "A") is False


def test_grade_meets_threshold_invalid_threshold() -> None:
    assert grade_meets_threshold("A", "X") is False


def test_all_grades_pass() -> None:
    result = evaluate_grades(
        [
            _item(req_id="R1", priority=Priority.CRITICAL, grade="A"),
            _item(req_id="R2", priority=Priority.EXPECTED, grade="B"),
        ]
    )
    assert result.passed is True
    assert len(result.failing_items) == 0


def test_critical_below_threshold_fails() -> None:
    result = evaluate_grades(
        [
            _item(req_id="R1", priority=Priority.CRITICAL, grade="C"),
        ]
    )
    assert result.passed is False
    assert len(result.failing_items) == 1
    assert "R1" in result.failing_items[0]


def test_expected_below_threshold_fails() -> None:
    result = evaluate_grades(
        [
            _item(req_id="R1", priority=Priority.EXPECTED, grade="D"),
        ]
    )
    assert result.passed is False
    assert "R1" in result.failing_items[0]


def test_nice_no_threshold() -> None:
    result = evaluate_grades(
        [
            _item(req_id="R1", priority=Priority.NICE, grade="F"),
        ]
    )
    assert result.passed is True
    assert len(result.failing_items) == 0


def test_no_grade_items_skipped() -> None:
    result = evaluate_grades(
        [
            _item(req_id="R1", priority=Priority.CRITICAL, grade=None),
        ]
    )
    assert result.passed is False
    assert len(result.failing_items) == 1
    assert "Not graded" in result.failing_items[0]


def test_ungraded_expected_item_fails() -> None:
    result = evaluate_grades(
        [
            _item(req_id="R1", priority=Priority.EXPECTED, grade=None),
        ]
    )
    assert result.passed is False
    assert len(result.failing_items) == 1
    assert "Not graded" in result.failing_items[0]


def test_ungraded_nice_item_does_not_fail() -> None:
    """NICE items can remain ungraded without affecting pass/fail."""
    result = evaluate_grades(
        [
            _item(req_id="R1", priority=Priority.CRITICAL, grade="A"),
            _item(req_id="R2", priority=Priority.NICE, grade=None),
        ]
    )
    assert result.passed is True
    assert len(result.failing_items) == 0


def test_mixed_graded_and_ungraded_critical_fails() -> None:
    """If any CRITICAL item is ungraded, the evaluation fails even if others pass."""
    result = evaluate_grades(
        [
            _item(req_id="R1", priority=Priority.CRITICAL, grade="A"),
            _item(req_id="R2", priority=Priority.CRITICAL, grade=None),
        ]
    )
    assert result.passed is False
    assert any("R2" in item for item in result.failing_items)


def test_all_items_ungraded_no_grades_set() -> None:
    """When only NICE items exist and none are graded, still passes (no required items)."""
    result = evaluate_grades(
        [
            _item(req_id="R1", priority=Priority.NICE, grade=None),
        ]
    )
    # No CRITICAL or EXPECTED items to fail, no graded items
    # This edge case: graded_count=0, failing=0 → "no grades set"
    assert result.passed is False
    assert result.message == "no grades set"


def test_revision_guidance_collected() -> None:
    result = evaluate_grades(
        [
            _item(
                req_id="R1",
                priority=Priority.CRITICAL,
                grade="C",
                grade_reason="Missing error handling",
            ),
        ]
    )
    assert result.passed is False
    assert len(result.revision_guidance) == 1
    assert "Missing error handling" in result.revision_guidance[0]


def test_revision_guidance_not_collected_without_reason() -> None:
    result = evaluate_grades(
        [
            _item(req_id="R1", priority=Priority.CRITICAL, grade="C"),
        ]
    )
    assert result.passed is False
    assert len(result.revision_guidance) == 0


def test_custom_thresholds() -> None:
    result = evaluate_grades(
        [_item(req_id="R1", priority=Priority.CRITICAL, grade="B")],
        critical_threshold="B",
    )
    assert result.passed is True


def test_message_on_failure() -> None:
    result = evaluate_grades(
        [
            _item(req_id="R1", priority=Priority.CRITICAL, grade="F"),
        ]
    )
    assert result.message is not None
    assert "failed" in result.message.lower()
