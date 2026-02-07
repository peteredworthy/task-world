"""Grade evaluation logic (pure functions)."""

from dataclasses import dataclass, field

from orchestrator.config.enums import Priority
from orchestrator.state.models import ChecklistItem

DEFAULT_GRADE_ORDER: list[str] = ["A", "B", "C", "D", "F"]


@dataclass
class GradeResult:
    """Result of grade evaluation."""

    passed: bool
    failing_items: list[str] = field(default_factory=lambda: [])
    revision_guidance: list[str] = field(default_factory=lambda: [])
    message: str | None = None


def grade_meets_threshold(
    grade: str,
    threshold: str,
    grade_order: list[str] = DEFAULT_GRADE_ORDER,
) -> bool:
    """Check if a grade meets or exceeds a threshold."""
    try:
        return grade_order.index(grade) <= grade_order.index(threshold)
    except ValueError:
        return False


def evaluate_grades(
    checklist: list[ChecklistItem],
    critical_threshold: str = "A",
    expected_threshold: str = "B",
    grade_order: list[str] = DEFAULT_GRADE_ORDER,
) -> GradeResult:
    """Evaluate grades against thresholds by priority."""
    failing: list[str] = []
    guidance: list[str] = []
    graded_count = 0

    for item in checklist:
        if item.grade is None:
            # Ungraded CRITICAL and EXPECTED items are treated as failing.
            # Only NICE items may remain ungraded without affecting pass/fail.
            if item.priority == Priority.CRITICAL:
                failing.append(f"{item.req_id}: Not graded (CRITICAL requirement)")
            elif item.priority == Priority.EXPECTED:
                failing.append(f"{item.req_id}: Not graded (EXPECTED requirement)")
            continue

        graded_count += 1

        if item.priority == Priority.CRITICAL:
            if not grade_meets_threshold(item.grade, critical_threshold, grade_order):
                failing.append(f"{item.req_id}: Grade {item.grade} below {critical_threshold}")
                if item.grade_reason:
                    guidance.append(f"{item.req_id}: {item.grade_reason}")
        elif item.priority == Priority.EXPECTED:
            if not grade_meets_threshold(item.grade, expected_threshold, grade_order):
                failing.append(f"{item.req_id}: Grade {item.grade} below {expected_threshold}")
                if item.grade_reason:
                    guidance.append(f"{item.req_id}: {item.grade_reason}")

    if graded_count == 0 and len(failing) == 0:
        return GradeResult(
            passed=False, failing_items=[], revision_guidance=[], message="no grades set"
        )

    passed = len(failing) == 0
    message: str | None = None
    if not passed:
        message = f"Grade evaluation failed: {len(failing)} item(s) below threshold"
    return GradeResult(
        passed=passed, failing_items=failing, revision_guidance=guidance, message=message
    )
