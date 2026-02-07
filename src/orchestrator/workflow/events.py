"""Workflow event types for observability."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from orchestrator.config.enums import AgentType, RunStatus, TaskStatus


@dataclass
class WorkflowEvent:
    """Base workflow event."""

    timestamp: datetime
    run_id: str
    event_type: str


@dataclass
class TaskStatusChanged(WorkflowEvent):
    """Emitted when a task changes status."""

    task_id: str = ""
    old_status: TaskStatus = TaskStatus.PENDING
    new_status: TaskStatus = TaskStatus.PENDING


@dataclass
class RunStatusChanged(WorkflowEvent):
    """Emitted when a run changes status."""

    old_status: RunStatus = RunStatus.DRAFT
    new_status: RunStatus = RunStatus.DRAFT


@dataclass
class ChecklistGateEvaluated(WorkflowEvent):
    """Emitted when a checklist gate is evaluated."""

    task_id: str = ""
    passed: bool = False
    blocking_items: list[str] = field(default_factory=lambda: [])


@dataclass
class GradeDetail:
    """Grade snapshot for a single checklist item, embedded in events."""

    req_id: str = ""
    grade: str | None = None
    grade_reason: str | None = None


@dataclass
class GradesEvaluated(WorkflowEvent):
    """Emitted when grades are evaluated."""

    task_id: str = ""
    passed: bool = False
    failing_items: list[str] = field(default_factory=lambda: [])
    grade_details: list[GradeDetail] = field(default_factory=lambda: [])


@dataclass
class AutoVerifyCompleted(WorkflowEvent):
    """Emitted when auto-verify commands finish for a task."""

    task_id: str = ""
    passed: bool = False
    failing_must_items: list[str] = field(default_factory=lambda: [])
    results: list[dict[str, object]] = field(default_factory=lambda: [])


@dataclass
class StepCompleted(WorkflowEvent):
    """Emitted when all tasks in a step reach terminal status."""

    step_index: int = 0
    step_id: str = ""


@dataclass
class RunStepBackward(WorkflowEvent):
    """Emitted when a run transitions backward to an earlier step."""

    from_step_index: int = 0
    to_step_index: int = 0
    reason: str | None = None


@dataclass
class AgentChangedEvent(WorkflowEvent):
    """Emitted when agent is switched on resume."""

    old_agent: AgentType = AgentType.CLI_SUBPROCESS
    new_agent: AgentType = AgentType.CLI_SUBPROCESS
    old_agent_config: dict[str, Any] = field(default_factory=lambda: {})
    new_agent_config: dict[str, Any] = field(default_factory=lambda: {})
    reason: str = "user_changed_on_resume"


@dataclass
class AgentDiedEvent(WorkflowEvent):
    """Emitted when a managed agent process dies."""

    agent_type: AgentType = AgentType.CLI_SUBPROCESS
    exit_code: int | None = None
    reason: str = "agent_process_died"


@dataclass
class AgentOutputEvent(WorkflowEvent):
    """Emitted when agent produces output lines."""

    task_id: str = ""
    attempt_num: int = 0
    lines: list[str] = field(default_factory=lambda: [])
    line_offset: int = 0  # Starting line number of this batch


@dataclass
class AgentErrorEvent(WorkflowEvent):
    """Emitted when an agent encounters an error."""

    task_id: str = ""
    attempt_num: int = 0
    error_type: str = ""  # e.g., "AgentExecutionError"
    error_message: str = ""


@dataclass
class ClarificationRequested(WorkflowEvent):
    """Emitted when builder requests clarification."""

    task_id: str = ""
    request_id: str = ""
    question_count: int = 0


@dataclass
class ClarificationResponded(WorkflowEvent):
    """Emitted when human answers clarification questions."""

    task_id: str = ""
    request_id: str = ""


@dataclass
class ApprovalRequested(WorkflowEvent):
    """Emitted when task awaits human approval."""

    task_id: str = ""
    step_id: str = ""
    summary_artifact: str | None = None


@dataclass
class ApprovalDecision(WorkflowEvent):
    """Emitted when human approves or rejects."""

    task_id: str = ""
    step_id: str = ""
    approved: bool = False
    comment: str | None = None
    decided_by: str = ""


class BufferingEmitter:
    """Event emitter that buffers events in memory.

    Implements the same interface as the EventEmitter protocol used by WorkflowEngine.
    Events can be retrieved after engine calls for async persistence.
    """

    def __init__(self) -> None:
        self.events: list[WorkflowEvent] = []

    def emit(self, event: WorkflowEvent) -> None:
        self.events.append(event)

    def drain(self) -> list[WorkflowEvent]:
        """Return all buffered events and clear the buffer."""
        events = self.events
        self.events = []
        return events
