"""Unit tests for task API request schema field validators."""

import pytest
from pydantic import ValidationError

from orchestrator.api.schemas.tasks import SetGradeRequest, UpdateChecklistRequest


# ---------------------------------------------------------------------------
# UpdateChecklistRequest.status validator
# ---------------------------------------------------------------------------


def test_invalid_checklist_status_rejected() -> None:
    """Invalid status raises ValidationError with helpful message."""
    with pytest.raises(ValidationError) as exc_info:
        UpdateChecklistRequest(status="invalid_status")
    assert "Invalid status" in str(exc_info.value)


def test_valid_checklist_statuses_accepted() -> None:
    """All known valid statuses are accepted and normalised to lowercase."""
    for status in ["done", "open", "blocked", "not_applicable"]:
        req = UpdateChecklistRequest(status=status)
        assert req.status == status


def test_checklist_status_case_insensitive() -> None:
    """Uppercase status is normalised to lowercase."""
    req = UpdateChecklistRequest(status="DONE")
    assert req.status == "done"


def test_checklist_status_mixed_case() -> None:
    """Mixed-case status is normalised to lowercase."""
    req = UpdateChecklistRequest(status="Done")
    assert req.status == "done"


# ---------------------------------------------------------------------------
# SetGradeRequest.grade validator
# ---------------------------------------------------------------------------


def test_invalid_grade_rejected() -> None:
    """Invalid grade raises ValidationError with helpful message."""
    with pytest.raises(ValidationError) as exc_info:
        SetGradeRequest(grade="Z")
    assert "Invalid grade" in str(exc_info.value)


def test_valid_grades_accepted() -> None:
    """All known valid grades are accepted."""
    for grade in ["A", "B", "C", "D", "F"]:
        req = SetGradeRequest(grade=grade)
        assert req.grade == grade


def test_grade_lowercase_normalised_to_uppercase() -> None:
    """Lowercase grade is normalised to uppercase."""
    req = SetGradeRequest(grade="a")
    assert req.grade == "A"


def test_grade_b_lowercase() -> None:
    """Lowercase 'b' is normalised to 'B'."""
    req = SetGradeRequest(grade="b")
    assert req.grade == "B"
