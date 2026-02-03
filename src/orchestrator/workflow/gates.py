"""Checklist gate evaluation logic (pure functions)."""

from dataclasses import dataclass, field

from orchestrator.config.enums import ChecklistStatus, Priority
from orchestrator.state.models import ChecklistItem


@dataclass
class GateResult:
    """Result of gate evaluation."""

    passed: bool
    blocking_items: list[str] = field(default_factory=lambda: [])
    warnings: list[str] = field(default_factory=lambda: [])
    message: str | None = None


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

    return GateResult(passed=passed, blocking_items=blocking, warnings=warnings, message=message)
