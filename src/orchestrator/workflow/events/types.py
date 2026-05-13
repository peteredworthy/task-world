"""Workflow event types for observability."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from orchestrator.config.enums import AgentRunnerType, RunStatus, TaskStatus


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
    start_commit: str | None = None  # Git commit SHA at attempt start (BUILDING transition)
    end_commit: str | None = None  # Git commit SHA at attempt end (VERIFYING transition)


@dataclass
class RunStatusChanged(WorkflowEvent):
    """Emitted when a run changes status."""

    old_status: RunStatus = RunStatus.DRAFT
    new_status: RunStatus = RunStatus.DRAFT
    pause_reason: str | None = None
    last_error: str | None = None  # Human-readable error detail when paused due to error


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
class StepSkipped(WorkflowEvent):
    """Emitted when a step is skipped due to a condition."""

    event_type: str = "step_skipped"
    step_index: int = 0
    step_id: str = ""
    condition: str | None = None
    skip_reason: str | None = None  # Why the step was skipped


@dataclass
class RunStepBackward(WorkflowEvent):
    """Emitted when a run transitions backward to an earlier step."""

    from_step_index: int = 0
    to_step_index: int = 0
    reason: str | None = None


@dataclass
class AgentChangedEvent(WorkflowEvent):
    """Emitted when agent is switched on resume."""

    old_agent: AgentRunnerType = AgentRunnerType.CLI_SUBPROCESS
    new_agent: AgentRunnerType = AgentRunnerType.CLI_SUBPROCESS
    old_agent_runner_config: dict[str, Any] = field(default_factory=lambda: {})
    new_agent_runner_config: dict[str, Any] = field(default_factory=lambda: {})
    reason: str = "user_changed_on_resume"


@dataclass
class AgentDiedEvent(WorkflowEvent):
    """Emitted when a managed agent process dies."""

    agent_runner_type: AgentRunnerType = AgentRunnerType.CLI_SUBPROCESS
    exit_code: int | None = None
    reason: str = "agent_process_died"
    task_id: str | None = None


@dataclass
class TaskReverted(WorkflowEvent):
    """Emitted when a task is reverted to phase start during resume."""

    task_id: str = ""
    reverted_from_status: TaskStatus = TaskStatus.BUILDING


@dataclass
class HealthCheckEvent(WorkflowEvent):
    """Emitted when the pre-run health check starts or finishes."""

    phase: str = ""  # "started" or "completed" or "failed"
    message: str = ""


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
    questions: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())

    def __init__(
        self,
        run_id: str,
        task_id: str = "",
        request_id: str = "",
        question_count: int = 0,
        questions: list[dict[str, Any]] | None = None,
        timestamp: datetime | None = None,
        event_type: str = "clarification_requested",
    ) -> None:
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.run_id = run_id
        self.event_type = event_type
        self.task_id = task_id
        self.request_id = request_id
        self.question_count = question_count
        self.questions = questions if questions is not None else list[dict[str, Any]]()


@dataclass(init=False)
class ClarificationResponded(WorkflowEvent):
    """Emitted when human answers clarification questions."""

    task_id: str = ""
    request_id: str = ""

    def __init__(
        self,
        run_id: str,
        task_id: str = "",
        request_id: str = "",
        timestamp: datetime | None = None,
        event_type: str = "clarification_responded",
    ) -> None:
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.run_id = run_id
        self.event_type = event_type
        self.task_id = task_id
        self.request_id = request_id


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


@dataclass
class PruneApplied(WorkflowEvent):
    """Emitted when a prune operation is applied to the run branch."""

    commit_sha: str = ""
    files_affected: int = 0
    hunks_removed: int = 0
    lines_removed: int = 0


@dataclass
class TestRunStarted(WorkflowEvent):
    """Emitted when a test run is started from the review workbench."""

    test_run_id: str = ""


@dataclass
class TestRunCompleted(WorkflowEvent):
    """Emitted when a test run completes from the review workbench."""

    test_run_id: str = ""
    status: str = ""  # "passed" | "failed" | "error"
    duration_ms: int | None = None


@dataclass
class ConflictResolved(WorkflowEvent):
    """Emitted when a conflict file is resolved."""

    file_path: str = ""
    remaining_conflicts: int = 0


@dataclass
class BackMergeCompleted(WorkflowEvent):
    """Emitted when a back merge operation completes."""

    status: str = ""  # "clean" | "conflicts"
    merge_commit_sha: str | None = None
    conflict_count: int = 0


@dataclass
class BackMergeReverted(WorkflowEvent):
    """Emitted when a back merge commit is reverted."""

    reverted_commit: str = ""
    new_head: str = ""


@dataclass
class AgentFixStarted(WorkflowEvent):
    """Emitted when an agent is dispatched to fix conflicts or tests."""

    job_id: str = ""
    agent_runner_type: str = ""


@dataclass
class AgentFixCompleted(WorkflowEvent):
    """Emitted when an agent-dispatched fix completes."""

    job_id: str = ""
    status: str = ""  # "completed" | "failed"


@dataclass
class FanOutSpawned(WorkflowEvent):
    """Emitted once when the parent fan-out task spawns all children (parent aggregation event)."""

    parent_task_id: str = ""
    child_count: int = 0


@dataclass
class ChildSpawned(WorkflowEvent):
    """Emitted when a fan-out child task is spawned from a parent task."""

    parent_task_id: str = ""
    child_task_id: str = ""
    child_id: str = ""  # Stable UUID for this fan-out child (durable across restarts)
    fan_out_index: int = 0
    fan_out_input: str | None = None


@dataclass
class ChildCompleted(WorkflowEvent):
    """Emitted when a fan-out child task completes successfully."""

    parent_task_id: str = ""
    child_task_id: str = ""
    child_id: str = ""  # Stable UUID for this fan-out child
    fan_out_index: int = 0
    attempt_num: int = 0
    fan_out_output: str | None = None


@dataclass
class ChildFailed(WorkflowEvent):
    """Emitted when a fan-out child task fails."""

    parent_task_id: str = ""
    child_task_id: str = ""
    child_id: str = ""  # Stable UUID for this fan-out child
    fan_out_index: int = 0
    attempt_num: int = 0
    error: str | None = None


@dataclass
class FanOutCompleted(WorkflowEvent):
    """Emitted once when all fan-out children reach terminal state (parent aggregation event)."""

    parent_task_id: str = ""
    all_passed: bool = True
    completed_count: int = 0
    failed_count: int = 0


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
