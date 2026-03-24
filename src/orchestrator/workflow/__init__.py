"""Workflow engine and gate logic."""

from orchestrator.workflow.artifacts import Artifact, ArtifactRegistry
from orchestrator.workflow.engine import (
    Clock,
    DefaultClock,
    EventEmitter,
    NoOpEmitter,
    WorkflowEngine,
)
from orchestrator.workflow.errors import GateBlockedError, InvalidTransitionError, WorkflowError
from orchestrator.workflow.locks import (
    InMemoryLockManager,
    LockManager,
    LockTimeoutError,
    TaskLockedError,
)
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
from orchestrator.workflow.dry_run import (
    DryRunResult,
    build_dry_run_context,
    build_dry_run_prompt,
    execute_dry_run,
    get_step_by_id,
    parse_dry_run_response,
)
from orchestrator.workflow.condition_evaluator import (
    ConditionEvalError,
    ConditionEvaluator,
    StepOutcome,
)

__all__ = [
    "Artifact",
    "ArtifactRegistry",
    "BuilderPrompt",
    "ChecklistGateEvaluated",
    "Clock",
    "ConditionEvalError",
    "ConditionEvaluator",
    "DEFAULT_GRADE_ORDER",
    "DefaultClock",
    "DryRunResult",
    "EventEmitter",
    "GateBlockedError",
    "GateResult",
    "GradeResult",
    "GradesEvaluated",
    "InMemoryLockManager",
    "InvalidTransitionError",
    "LockManager",
    "LockTimeoutError",
    "NoOpEmitter",
    "StepOutcome",
    "TaskLockedError",
    "RunStatusChanged",
    "TaskStatusChanged",
    "TransitionResult",
    "VALID_TRANSITIONS",
    "VerifierPrompt",
    "WorkflowEngine",
    "WorkflowError",
    "WorkflowEvent",
    "build_dry_run_context",
    "build_dry_run_prompt",
    "evaluate_checklist_gate",
    "evaluate_grades",
    "execute_dry_run",
    "generate_builder_prompt",
    "generate_verifier_prompt",
    "get_step_by_id",
    "get_task_context",
    "parse_dry_run_response",
]
