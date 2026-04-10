"""Unit tests for human-only gate type."""

from datetime import datetime, timezone
from typing import Any

import pytest

from orchestrator.config import ChecklistStatus, GateType, Priority
from orchestrator.config.models import GateConfig
from orchestrator.state.models import ChecklistItem, HumanApproval
from orchestrator.workflow import evaluate_gate


@pytest.fixture
def sample_checklist() -> list[ChecklistItem]:
    """Sample checklist for testing."""
    return [
        ChecklistItem(
            req_id="R1",
            desc="Critical requirement",
            priority=Priority.CRITICAL,
            status=ChecklistStatus.DONE,
        ),
        ChecklistItem(
            req_id="R2",
            desc="Expected requirement",
            priority=Priority.EXPECTED,
            status=ChecklistStatus.DONE,
        ),
    ]


@pytest.fixture
def sample_grades() -> dict[str, str]:
    """Sample grades for testing."""
    return {"R1": "A", "R2": "B"}


@pytest.fixture
def sample_auto_verify_results() -> list[dict[str, Any]]:
    """Sample auto-verify results for testing."""
    return [
        {"id": "test1", "cmd": "test -f file.txt", "must": True, "passed": True},
        {"id": "test2", "cmd": "test -d dir", "must": False, "passed": True},
    ]


class TestHumanApprovalGate:
    """Tests for HUMAN_APPROVAL gate type."""

    def test_blocks_without_approval(
        self,
        sample_checklist: list[ChecklistItem],
        sample_grades: dict[str, str],
        sample_auto_verify_results: list[dict[str, Any]],
    ) -> None:
        """Human gate blocks when no approval provided."""
        gate_config = GateConfig(
            type=GateType.HUMAN_APPROVAL,
            approval_prompt="Please review",
        )

        result = evaluate_gate(
            gate_config=gate_config,
            checklist=sample_checklist,
            grades=sample_grades,
            human_approval=None,
            auto_verify_results=sample_auto_verify_results,
        )

        assert not result.passed
        assert result.gate_type == GateType.HUMAN_APPROVAL
        assert len(result.blocking_items) == 1
        assert "Human approval required" in result.blocking_items[0]
        assert result.message == "Awaiting human approval"

    def test_passes_with_approval(
        self,
        sample_checklist: list[ChecklistItem],
        sample_grades: dict[str, str],
        sample_auto_verify_results: list[dict[str, Any]],
    ) -> None:
        """Human gate passes with valid approval."""
        gate_config = GateConfig(
            type=GateType.HUMAN_APPROVAL,
            approval_prompt="Please review",
        )

        approval = HumanApproval(
            approved_by="user@example.com",
            approved_at=datetime.now(timezone.utc),
            comment="Looks good",
        )

        result = evaluate_gate(
            gate_config=gate_config,
            checklist=sample_checklist,
            grades=sample_grades,
            human_approval=approval,
            auto_verify_results=sample_auto_verify_results,
        )

        assert result.passed
        assert result.gate_type == GateType.HUMAN_APPROVAL
        assert len(result.blocking_items) == 0
        assert result.message is not None
        assert "user@example.com" in result.message

    def test_comment_required_when_configured(
        self,
        sample_checklist: list[ChecklistItem],
        sample_grades: dict[str, str],
        sample_auto_verify_results: list[dict[str, Any]],
    ) -> None:
        """Human gate blocks when comment required but not provided."""
        gate_config = GateConfig(
            type=GateType.HUMAN_APPROVAL,
            approval_prompt="Please review",
            require_comment=True,
        )

        approval = HumanApproval(
            approved_by="user@example.com",
            approved_at=datetime.now(timezone.utc),
            comment=None,  # No comment provided
        )

        result = evaluate_gate(
            gate_config=gate_config,
            checklist=sample_checklist,
            grades=sample_grades,
            human_approval=approval,
            auto_verify_results=sample_auto_verify_results,
        )

        assert not result.passed
        assert result.gate_type == GateType.HUMAN_APPROVAL
        assert len(result.blocking_items) == 1
        assert "Comment required" in result.blocking_items[0]
        assert result.message == "Human approval requires comment"

    def test_passes_with_comment_when_required(
        self,
        sample_checklist: list[ChecklistItem],
        sample_grades: dict[str, str],
        sample_auto_verify_results: list[dict[str, Any]],
    ) -> None:
        """Human gate passes when comment required and provided."""
        gate_config = GateConfig(
            type=GateType.HUMAN_APPROVAL,
            approval_prompt="Please review",
            require_comment=True,
        )

        approval = HumanApproval(
            approved_by="user@example.com",
            approved_at=datetime.now(timezone.utc),
            comment="All requirements met, looks good to proceed",
        )

        result = evaluate_gate(
            gate_config=gate_config,
            checklist=sample_checklist,
            grades=sample_grades,
            human_approval=approval,
            auto_verify_results=sample_auto_verify_results,
        )

        assert result.passed
        assert result.gate_type == GateType.HUMAN_APPROVAL
        assert len(result.blocking_items) == 0

    def test_audit_trail_recorded(self) -> None:
        """Human approval records audit trail."""
        now = datetime.now(timezone.utc)
        approval = HumanApproval(
            approved_by="user@example.com",
            approved_at=now,
            comment="Approved after review",
        )

        assert approval.approved_by == "user@example.com"
        assert approval.approved_at == now
        assert approval.comment == "Approved after review"

    def test_empty_comment_allowed_when_not_required(
        self,
        sample_checklist: list[ChecklistItem],
        sample_grades: dict[str, str],
        sample_auto_verify_results: list[dict[str, Any]],
    ) -> None:
        """Human gate passes without comment when not required."""
        gate_config = GateConfig(
            type=GateType.HUMAN_APPROVAL,
            approval_prompt="Please review",
            require_comment=False,
        )

        approval = HumanApproval(
            approved_by="user@example.com",
            approved_at=datetime.now(timezone.utc),
            comment=None,
        )

        result = evaluate_gate(
            gate_config=gate_config,
            checklist=sample_checklist,
            grades=sample_grades,
            human_approval=approval,
            auto_verify_results=sample_auto_verify_results,
        )

        assert result.passed
        assert result.gate_type == GateType.HUMAN_APPROVAL


class TestGateTypeIntegration:
    """Tests for evaluate_gate with different gate types."""

    def test_checklist_gate_type(
        self,
        sample_grades: dict[str, str],
        sample_auto_verify_results: list[dict[str, Any]],
    ) -> None:
        """evaluate_gate handles CHECKLIST gate type."""
        gate_config = GateConfig(type=GateType.CHECKLIST)

        checklist = [
            ChecklistItem(
                req_id="R1",
                desc="Critical",
                priority=Priority.CRITICAL,
                status=ChecklistStatus.DONE,
            )
        ]

        result = evaluate_gate(
            gate_config=gate_config,
            checklist=checklist,
            grades=sample_grades,
            human_approval=None,
            auto_verify_results=sample_auto_verify_results,
        )

        assert result.passed
        assert result.gate_type == GateType.CHECKLIST

    def test_grade_threshold_gate_type(
        self,
        sample_checklist: list[ChecklistItem],
        sample_auto_verify_results: list[dict[str, Any]],
    ) -> None:
        """evaluate_gate handles GRADE_THRESHOLD gate type."""
        gate_config = GateConfig(
            type=GateType.GRADE_THRESHOLD,
            critical_threshold="A",
            expected_threshold="B",
        )

        # Add grades to checklist
        checklist = [
            ChecklistItem(
                req_id="R1",
                desc="Critical",
                priority=Priority.CRITICAL,
                status=ChecklistStatus.DONE,
                grade="A",
            ),
            ChecklistItem(
                req_id="R2",
                desc="Expected",
                priority=Priority.EXPECTED,
                status=ChecklistStatus.DONE,
                grade="B",
            ),
        ]

        result = evaluate_gate(
            gate_config=gate_config,
            checklist=checklist,
            grades={},
            human_approval=None,
            auto_verify_results=sample_auto_verify_results,
        )

        assert result.passed
        assert result.gate_type == GateType.GRADE_THRESHOLD

    def test_auto_verify_gate_type_passes(
        self,
        sample_checklist: list[ChecklistItem],
        sample_grades: dict[str, str],
    ) -> None:
        """evaluate_gate handles AUTO_VERIFY gate type when passing."""
        gate_config = GateConfig(type=GateType.AUTO_VERIFY)

        auto_verify_results = [
            {"id": "test1", "cmd": "test -f file.txt", "must": True, "passed": True},
            {"id": "test2", "cmd": "test -d dir", "must": False, "passed": True},
        ]

        result = evaluate_gate(
            gate_config=gate_config,
            checklist=sample_checklist,
            grades=sample_grades,
            human_approval=None,
            auto_verify_results=auto_verify_results,
        )

        assert result.passed
        assert result.gate_type == GateType.AUTO_VERIFY
        assert result.message is not None
        assert "passed" in result.message.lower()

    def test_auto_verify_gate_type_fails(
        self,
        sample_checklist: list[ChecklistItem],
        sample_grades: dict[str, str],
    ) -> None:
        """evaluate_gate handles AUTO_VERIFY gate type when failing."""
        gate_config = GateConfig(type=GateType.AUTO_VERIFY)

        auto_verify_results = [
            {
                "id": "test1",
                "cmd": "test -f missing.txt",
                "must": True,
                "passed": False,
                "error": "File not found",
            },
            {"id": "test2", "cmd": "test -d dir", "must": False, "passed": True},
        ]

        result = evaluate_gate(
            gate_config=gate_config,
            checklist=sample_checklist,
            grades=sample_grades,
            human_approval=None,
            auto_verify_results=auto_verify_results,
        )

        assert not result.passed
        assert result.gate_type == GateType.AUTO_VERIFY
        assert len(result.blocking_items) == 1
        assert "test1" in result.blocking_items[0]
        assert "File not found" in result.blocking_items[0]

    def test_unknown_gate_type(
        self,
        sample_checklist: list[ChecklistItem],
        sample_grades: dict[str, str],
        sample_auto_verify_results: list[dict[str, Any]],
    ) -> None:
        """evaluate_gate handles unknown gate types gracefully."""
        # This shouldn't happen in practice due to enum validation,
        # but test defensive behavior
        gate_config = GateConfig(type=GateType.CHECKLIST)
        # Manually override type to test error handling
        gate_config.type = "unknown_type"  # type: ignore[assignment]

        result = evaluate_gate(
            gate_config=gate_config,
            checklist=sample_checklist,
            grades=sample_grades,
            human_approval=None,
            auto_verify_results=sample_auto_verify_results,
        )

        assert not result.passed
        assert result.message is not None
        assert "Unknown gate type" in result.message


class TestHumanApprovalModel:
    """Tests for HumanApproval model."""

    def test_create_with_comment(self) -> None:
        """Can create approval with comment."""
        now = datetime.now(timezone.utc)
        approval = HumanApproval(
            approved_by="user@example.com",
            approved_at=now,
            comment="Looks great",
        )

        assert approval.approved_by == "user@example.com"
        assert approval.approved_at == now
        assert approval.comment == "Looks great"

    def test_create_without_comment(self) -> None:
        """Can create approval without comment."""
        now = datetime.now(timezone.utc)
        approval = HumanApproval(
            approved_by="user@example.com",
            approved_at=now,
        )

        assert approval.approved_by == "user@example.com"
        assert approval.approved_at == now
        assert approval.comment is None

    def test_serialization(self) -> None:
        """HumanApproval can be serialized."""
        now = datetime.now(timezone.utc)
        approval = HumanApproval(
            approved_by="user@example.com",
            approved_at=now,
            comment="Approved",
        )

        data = approval.model_dump()
        assert data["approved_by"] == "user@example.com"
        assert data["approved_at"] == now
        assert data["comment"] == "Approved"

        # Round-trip
        approval2 = HumanApproval.model_validate(data)
        assert approval2.approved_by == approval.approved_by
        assert approval2.approved_at == approval.approved_at
        assert approval2.comment == approval.comment
