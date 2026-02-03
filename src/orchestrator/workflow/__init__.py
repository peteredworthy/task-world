"""Workflow engine and gate logic."""

from orchestrator.workflow.engine import (
    Clock,
    DefaultClock,
    EventEmitter,
    NoOpEmitter,
    WorkflowEngine,
)
from orchestrator.workflow.errors import GateBlockedError, InvalidTransitionError, WorkflowError
from orchestrator.workflow.events import (
    ChecklistGateEvaluated,
    GradesEvaluated,
    RunStatusChanged,
    TaskStatusChanged,
    WorkflowEvent,
)
from orchestrator.workflow.gates import GateResult, evaluate_checklist_gate
from orchestrator.workflow.grades import DEFAULT_GRADE_ORDER, GradeResult, evaluate_grades
from orchestrator.workflow.prompts import (
    BuilderPrompt,
    VerifierPrompt,
    generate_builder_prompt,
    generate_verifier_prompt,
    get_task_context,
)
from orchestrator.workflow.transitions import VALID_TRANSITIONS, TransitionResult

__all__ = [
    "BuilderPrompt",
    "ChecklistGateEvaluated",
    "Clock",
    "DEFAULT_GRADE_ORDER",
    "DefaultClock",
    "EventEmitter",
    "GateBlockedError",
    "GateResult",
    "GradeResult",
    "GradesEvaluated",
    "InvalidTransitionError",
    "NoOpEmitter",
    "RunStatusChanged",
    "TaskStatusChanged",
    "TransitionResult",
    "VALID_TRANSITIONS",
    "VerifierPrompt",
    "WorkflowEngine",
    "WorkflowError",
    "WorkflowEvent",
    "evaluate_checklist_gate",
    "evaluate_grades",
    "generate_builder_prompt",
    "generate_verifier_prompt",
    "get_task_context",
]
