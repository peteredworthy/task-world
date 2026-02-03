"""Tests for checklist gate evaluation."""

from orchestrator.config.enums import ChecklistStatus, Priority
from orchestrator.state.models import ChecklistItem
from orchestrator.workflow.gates import evaluate_checklist_gate


def _item(
    req_id: str = "R1",
    desc: str = "Test",
    priority: Priority = Priority.CRITICAL,
    status: ChecklistStatus = ChecklistStatus.OPEN,
    note: str | None = None,
) -> ChecklistItem:
    return ChecklistItem(req_id=req_id, desc=desc, priority=priority, status=status, note=note)


def test_empty_checklist_passes() -> None:
    result = evaluate_checklist_gate([])
    assert result.passed is True
    assert len(result.blocking_items) == 0
    assert len(result.warnings) == 0


def test_all_done_passes() -> None:
    result = evaluate_checklist_gate(
        [
            _item(req_id="R1", status=ChecklistStatus.DONE),
            _item(req_id="R2", status=ChecklistStatus.DONE),
        ]
    )
    assert result.passed is True


def test_critical_open_blocks() -> None:
    result = evaluate_checklist_gate(
        [
            _item(req_id="R1", priority=Priority.CRITICAL, status=ChecklistStatus.OPEN),
        ]
    )
    assert result.passed is False
    assert len(result.blocking_items) == 1
    assert "R1" in result.blocking_items[0]


def test_critical_na_without_note_blocks() -> None:
    result = evaluate_checklist_gate(
        [
            _item(
                req_id="R1",
                priority=Priority.CRITICAL,
                status=ChecklistStatus.NOT_APPLICABLE,
                note=None,
            ),
        ]
    )
    assert result.passed is False
    assert "without justification" in result.blocking_items[0]


def test_critical_na_with_note_passes() -> None:
    result = evaluate_checklist_gate(
        [
            _item(
                req_id="R1",
                priority=Priority.CRITICAL,
                status=ChecklistStatus.NOT_APPLICABLE,
                note="Not relevant for this task",
            ),
        ]
    )
    assert result.passed is True


def test_critical_blocked_without_note_blocks() -> None:
    result = evaluate_checklist_gate(
        [
            _item(
                req_id="R1",
                priority=Priority.CRITICAL,
                status=ChecklistStatus.BLOCKED,
                note=None,
            ),
        ]
    )
    assert result.passed is False


def test_critical_blocked_with_note_passes() -> None:
    result = evaluate_checklist_gate(
        [
            _item(
                req_id="R1",
                priority=Priority.CRITICAL,
                status=ChecklistStatus.BLOCKED,
                note="Blocked by external dependency",
            ),
        ]
    )
    assert result.passed is True


def test_expected_open_warns_but_passes() -> None:
    result = evaluate_checklist_gate(
        [
            _item(req_id="R1", priority=Priority.EXPECTED, status=ChecklistStatus.OPEN),
        ]
    )
    assert result.passed is True
    assert len(result.warnings) == 1
    assert "R1" in result.warnings[0]


def test_expected_blocked_with_note_warns_passes() -> None:
    result = evaluate_checklist_gate(
        [
            _item(
                req_id="R1",
                priority=Priority.EXPECTED,
                status=ChecklistStatus.BLOCKED,
                note="Blocked by external dependency",
            ),
        ]
    )
    assert result.passed is True
    assert len(result.warnings) == 0


def test_nice_open_does_not_warn() -> None:
    result = evaluate_checklist_gate(
        [
            _item(req_id="R1", priority=Priority.NICE, status=ChecklistStatus.OPEN),
        ]
    )
    assert result.passed is True
    assert len(result.warnings) == 0
    assert len(result.blocking_items) == 0


def test_mixed_priorities() -> None:
    result = evaluate_checklist_gate(
        [
            _item(req_id="R1", priority=Priority.CRITICAL, status=ChecklistStatus.DONE),
            _item(req_id="R2", priority=Priority.EXPECTED, status=ChecklistStatus.OPEN),
            _item(req_id="R3", priority=Priority.NICE, status=ChecklistStatus.OPEN),
        ]
    )
    assert result.passed is True
    assert len(result.warnings) == 1
    assert result.message is not None
    assert "warning" in result.message.lower()


def test_message_on_failure() -> None:
    result = evaluate_checklist_gate(
        [
            _item(req_id="R1", priority=Priority.CRITICAL, status=ChecklistStatus.OPEN),
        ]
    )
    assert result.message is not None
    assert "failed" in result.message.lower()
