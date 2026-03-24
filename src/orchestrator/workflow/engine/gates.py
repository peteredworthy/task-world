"""Checklist gate evaluation logic (pure functions)."""

from dataclasses import dataclass, field
from typing import Any

from orchestrator.config.enums import ChecklistStatus, GateType, Priority
from orchestrator.config.models import GateConfig
from orchestrator.state.models import ChecklistItem, HumanApproval


@dataclass
class GateResult:
    """Result of gate evaluation."""

    passed: bool
    blocking_items: list[str] = field(default_factory=lambda: [])
    warnings: list[str] = field(default_factory=lambda: [])
    message: str | None = None
    gate_type: GateType | None = None


def evaluate_checklist_gate(checklist: list[ChecklistItem]) -> GateResult:
    """Evaluate whether checklist passes the gate to proceed.

    Rules:
    - CRITICAL items must be DONE, or (NOT_APPLICABLE/BLOCKED with note)
    - EXPECTED items should be DONE (warning if not)
    - NICE items are informational
    """
    blocking: list[str] = []
    warnings: list[str] = []

    for item in checklist:
        if item.priority == Priority.CRITICAL:
            if item.status == ChecklistStatus.OPEN:
                blocking.append(f"{item.req_id}: {item.desc} (not completed)")
            elif item.status in (ChecklistStatus.NOT_APPLICABLE, ChecklistStatus.BLOCKED):
                if not item.note:
                    blocking.append(
                        f"{item.req_id}: {item.desc} "
                        f"(marked {item.status.value} without justification)"
                    )
        elif item.priority == Priority.EXPECTED:
            if item.status == ChecklistStatus.OPEN:
                warnings.append(f"{item.req_id}: {item.desc} (not completed)")
            elif item.status in (ChecklistStatus.NOT_APPLICABLE, ChecklistStatus.BLOCKED):
                if not item.note:
                    warnings.append(
                        f"{item.req_id}: {item.desc} "
                        f"(marked {item.status.value} without justification)"
                    )

    passed = len(blocking) == 0
    message: str | None = None
    if not passed:
        message = f"Checklist gate failed: {len(blocking)} blocking item(s)"
    elif warnings:
        message = f"Checklist gate passed with {len(warnings)} warning(s)"

    return GateResult(
        passed=passed,
        blocking_items=blocking,
        warnings=warnings,
        message=message,
        gate_type=GateType.CHECKLIST,
    )


def evaluate_gate(
    gate_config: GateConfig,
    checklist: list[ChecklistItem],
    grades: dict[str, str],
    human_approval: HumanApproval | None,
    auto_verify_results: list[dict[str, Any]],
) -> GateResult:
    """Evaluate gate based on type.

    Args:
        gate_config: Gate configuration
        checklist: Current task checklist items
        grades: Dict mapping req_id -> grade
        human_approval: Human approval record if present
        auto_verify_results: Auto-verify results if present

    Returns:
        GateResult indicating pass/fail with details
    """
    if gate_config.type == GateType.HUMAN_APPROVAL:
        if human_approval is None:
            return GateResult(
                passed=False,
                blocking_items=["Human approval required"],
                message="Awaiting human approval",
                gate_type=GateType.HUMAN_APPROVAL,
            )
        if gate_config.require_comment and not human_approval.comment:
            return GateResult(
                passed=False,
                blocking_items=["Comment required for approval"],
                message="Human approval requires comment",
                gate_type=GateType.HUMAN_APPROVAL,
            )
        return GateResult(
            passed=True,
            message=f"Approved by {human_approval.approved_by}",
            gate_type=GateType.HUMAN_APPROVAL,
        )

    elif gate_config.type == GateType.GRADE_THRESHOLD:
        # Evaluate grade thresholds
        from orchestrator.workflow.grades import evaluate_grades

        grade_result = evaluate_grades(
            checklist,
            critical_threshold=gate_config.critical_threshold,
            expected_threshold=gate_config.expected_threshold,
        )
        return GateResult(
            passed=grade_result.passed,
            blocking_items=grade_result.failing_items,
            warnings=grade_result.revision_guidance,
            message=grade_result.message,
            gate_type=GateType.GRADE_THRESHOLD,
        )

    elif gate_config.type == GateType.AUTO_VERIFY:
        # Check auto-verify results
        blocking: list[str] = []
        for result in auto_verify_results:
            if result.get("must", False) and not result.get("passed", False):
                blocking.append(
                    f"{result.get('id', 'unknown')}: {result.get('error', 'verification failed')}"
                )

        passed = len(blocking) == 0
        message = (
            "Auto-verify passed"
            if passed
            else f"Auto-verify failed: {len(blocking)} check(s) failed"
        )
        return GateResult(
            passed=passed,
            blocking_items=blocking,
            message=message,
            gate_type=GateType.AUTO_VERIFY,
        )

    elif gate_config.type == GateType.CHECKLIST:
        # Use existing checklist gate logic
        result = evaluate_checklist_gate(checklist)
        result.gate_type = GateType.CHECKLIST
        return result

    # Unknown gate type
    return GateResult(
        passed=False,
        blocking_items=[f"Unknown gate type: {gate_config.type}"],
        message=f"Unknown gate type: {gate_config.type}",
        gate_type=gate_config.type,
    )
