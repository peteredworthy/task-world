"""Workflow event types for observability."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from orchestrator.config.enums import AgentRunnerType, ChecklistStatus, RunStatus, TaskStatus


class WorkflowEvent(BaseModel):
    """Base workflow event."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: str
    event_type: str = ""


class TaskStatusChanged(WorkflowEvent):
    """Emitted when a task changes status."""

    task_id: str = ""
    old_status: TaskStatus | str = TaskStatus.PENDING
    new_status: TaskStatus | str = TaskStatus.PENDING
    start_commit: str | None = None  # Git commit SHA at attempt start (BUILDING transition)
    end_commit: str | None = None  # Git commit SHA at attempt end (VERIFYING transition)
    current_attempt: int | None = None
    attempt_snapshots: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


class RunStatusChanged(WorkflowEvent):
    """Emitted when a run changes status."""

    old_status: RunStatus | str = RunStatus.DRAFT
    new_status: RunStatus | str = RunStatus.DRAFT
    pause_reason: str | None = None
    last_error: str | None = None  # Human-readable error detail when paused due to error


class ChecklistGateEvaluated(WorkflowEvent):
    """Emitted when a checklist gate is evaluated."""

    task_id: str = ""
    passed: bool = False
    blocking_items: list[str] = Field(default_factory=list)


class ChecklistItemUpdated(WorkflowEvent):
    """Emitted when a checklist item status or note changes."""

    event_type: str = "checklist_item_updated"
    task_id: str = ""
    req_id: str = ""
    status: ChecklistStatus | str = ChecklistStatus.OPEN
    note: str | None = None


class ChecklistItemGraded(WorkflowEvent):
    """Emitted when a checklist item receives a verifier grade."""

    event_type: str = "checklist_item_graded"
    task_id: str = ""
    req_id: str = ""
    grade: str = ""
    grade_reason: str | None = None


class GradeDetail(BaseModel):
    """Grade snapshot for a single checklist item, embedded in events."""

    req_id: str = ""
    grade: str | None = None
    grade_reason: str | None = None


class GradesEvaluated(WorkflowEvent):
    """Emitted when grades are evaluated."""

    task_id: str = ""
    passed: bool = False
    failing_items: list[str] = Field(default_factory=list)
    grade_details: list[GradeDetail] = Field(default_factory=list[GradeDetail])


class AutoVerifyCompleted(WorkflowEvent):
    """Emitted when auto-verify commands finish for a task."""

    task_id: str = ""
    passed: bool = False
    failing_must_items: list[str] = Field(default_factory=list)
    results: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])
    checklist: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    current_attempt: int | None = None
    latest_attempt_snapshot: dict[str, Any] | None = None


class StepCompleted(WorkflowEvent):
    """Emitted when all tasks in a step reach terminal status."""

    step_index: int = 0
    step_id: str = ""


class StepSkipped(WorkflowEvent):
    """Emitted when a step is skipped due to a condition."""

    event_type: str = "step_skipped"
    step_index: int = 0
    step_id: str = ""
    condition: str | None = None
    skip_reason: str | None = None  # Why the step was skipped
    completed: bool = True
    current_step_index_after: int | None = None


class StepHumanApprovalRecorded(WorkflowEvent):
    """Emitted when a human approval is recorded for a step gate."""

    event_type: str = "step_human_approval_recorded"
    step_id: str = ""
    approved_by: str = ""
    approved_at: datetime
    comment: str | None = None


class RunStepBackward(WorkflowEvent):
    """Emitted when a run transitions backward to an earlier step."""

    from_step_index: int = 0
    to_step_index: int = 0
    reason: str | None = None
    transition_tracker_delta: dict[str, int] | None = None


class AgentChangedEvent(WorkflowEvent):
    """Emitted when agent is switched on resume."""

    event_type: str = "agent_changed"
    old_agent: AgentRunnerType = AgentRunnerType.CLI_SUBPROCESS
    new_agent: AgentRunnerType = AgentRunnerType.CLI_SUBPROCESS
    old_agent_runner_config: dict[str, Any] = Field(default_factory=dict)
    new_agent_runner_config: dict[str, Any] = Field(default_factory=dict)
    reason: str = "user_changed_on_resume"


class AgentDiedEvent(WorkflowEvent):
    """Emitted when a managed agent process dies."""

    agent_runner_type: AgentRunnerType = AgentRunnerType.CLI_SUBPROCESS
    exit_code: int | None = None
    reason: str = "agent_process_died"
    task_id: str | None = None


class TaskReverted(WorkflowEvent):
    """Emitted when a task is reverted to phase start during resume."""

    event_type: str = "task_reverted"
    task_id: str = ""
    reverted_from_status: TaskStatus | str = TaskStatus.BUILDING
    task_snapshot: dict[str, Any] = Field(default_factory=dict)


class HealthCheckEvent(WorkflowEvent):
    """Emitted when the pre-run health check starts or finishes."""

    event_type: str = "health_check"
    phase: str = ""  # "started" or "completed" or "failed"
    message: str = ""


class AgentOutputEvent(WorkflowEvent):
    """Emitted when agent produces output lines."""

    event_type: str = "agent_output"
    task_id: str = ""
    attempt_num: int = 0
    lines: list[str] = Field(default_factory=list)
    line_offset: int = 0  # Starting line number of this batch


class AgentErrorEvent(WorkflowEvent):
    """Emitted when an agent encounters an error."""

    event_type: str = "agent_error"
    task_id: str = ""
    attempt_num: int = 0
    error_type: str = ""  # e.g., "AgentExecutionError"
    error_message: str = ""


class ClarificationRequested(WorkflowEvent):
    """Emitted when builder requests clarification."""

    event_type: str = "clarification_requested"
    task_id: str = ""
    request_id: str = ""
    attempt_num: int = 0
    question_count: int = 0
    questions: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


class ClarificationResponded(WorkflowEvent):
    """Emitted when human answers clarification questions."""

    event_type: str = "clarification_responded"
    task_id: str = ""
    request_id: str = ""
    response_id: str | None = None
    answers: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    responded_by: str | None = None
    responded_at: datetime | None = None
    new_status: TaskStatus | str | None = None
    run_config_delta: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequested(WorkflowEvent):
    """Emitted when task awaits human approval."""

    task_id: str = ""
    step_id: str = ""
    summary_artifact: str | None = None


class ApprovalDecision(WorkflowEvent):
    """Emitted when human approves or rejects."""

    event_type: str = "approval_decision"
    task_id: str = ""
    step_id: str = ""
    approved: bool = False
    comment: str | None = None
    decided_by: str = ""
    new_status: TaskStatus | str | None = None
    current_attempt: int | None = None
    checklist: list[dict[str, Any]] | None = None
    attempt_snapshots: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


class PruneApplied(WorkflowEvent):
    """Emitted when a prune operation is applied to the run branch."""

    commit_sha: str = ""
    files_affected: int = 0
    hunks_removed: int = 0
    lines_removed: int = 0


class TestRunStarted(WorkflowEvent):
    """Emitted when a test run is started from the review workbench."""

    __test__ = False  # prevent pytest from collecting this class

    test_run_id: str = ""


class TestRunCompleted(WorkflowEvent):
    """Emitted when a test run completes from the review workbench."""

    __test__ = False  # prevent pytest from collecting this class

    test_run_id: str = ""
    status: str = ""  # "passed" | "failed" | "error"
    duration_ms: int | None = None


class ConflictResolved(WorkflowEvent):
    """Emitted when a conflict file is resolved."""

    file_path: str = ""
    remaining_conflicts: int = 0


class BackMergeCompleted(WorkflowEvent):
    """Emitted when a back merge operation completes."""

    status: str = ""  # "clean" | "conflicts"
    merge_commit_sha: str | None = None
    conflict_count: int = 0


class BackMergeReverted(WorkflowEvent):
    """Emitted when a back merge commit is reverted."""

    reverted_commit: str = ""
    new_head: str = ""


class AgentFixStarted(WorkflowEvent):
    """Emitted when an agent is dispatched to fix conflicts or tests."""

    job_id: str = ""
    agent_runner_type: str = ""


class AgentFixCompleted(WorkflowEvent):
    """Emitted when an agent-dispatched fix completes."""

    job_id: str = ""
    status: str = ""  # "completed" | "failed"


class FanOutSpawned(WorkflowEvent):
    """Emitted once when the parent fan-out task spawns all children (parent aggregation event)."""

    parent_task_id: str = ""
    child_count: int = 0


class ChildSpawned(WorkflowEvent):
    """Emitted when a fan-out child task is spawned from a parent task."""

    parent_task_id: str = ""
    child_task_id: str = ""
    child_id: str = ""  # Stable UUID for this fan-out child (durable across restarts)
    fan_out_index: int = 0
    fan_out_input: str | None = None


class ChildCompleted(WorkflowEvent):
    """Emitted when a fan-out child task completes successfully."""

    parent_task_id: str = ""
    child_task_id: str = ""
    child_id: str = ""  # Stable UUID for this fan-out child
    fan_out_index: int = 0
    attempt_num: int = 0
    fan_out_output: str | None = None


class ChildFailed(WorkflowEvent):
    """Emitted when a fan-out child task fails."""

    parent_task_id: str = ""
    child_task_id: str = ""
    child_id: str = ""  # Stable UUID for this fan-out child
    fan_out_index: int = 0
    attempt_num: int = 0
    error: str | None = None


class FanOutCompleted(WorkflowEvent):
    """Emitted once when all fan-out children reach terminal state (parent aggregation event)."""

    parent_task_id: str = ""
    all_passed: bool = True
    completed_count: int = 0
    failed_count: int = 0


class RunCreated(WorkflowEvent):
    """Created when a run is first persisted.

    Legacy events may include ``run_snapshot`` for backwards-compatible recovery.
    """

    event_type: str = "run_created"
    routine_id: str = ""
    project_path: str = ""
    repo_name: str = ""
    status: RunStatus = RunStatus.DRAFT
    pause_reason: str | None = None
    last_error: str | None = None
    execution_mode: str = "legacy"
    config: dict[str, Any] = Field(default_factory=dict)
    parent_run_id: str | None = None
    parent_task_id: str | None = None
    routine_sha: str | None = None
    routine_source: str | None = None
    routine_embedded: dict[str, Any] | None = None
    routine_path: str | None = None
    routine_commit: str | None = None
    parent_slice_id: str | None = None
    oversight_state: dict[str, Any] = Field(default_factory=dict)
    runner_type: str | None = None
    runner_config: dict[str, Any] = Field(default_factory=dict)
    verifier_model: str | None = None
    worktree_enabled: bool = True
    worktree_path: str | None = None
    delete_worktree_on_completion: bool = False
    source_branch: str | None = None
    source_branch_sha: str | None = None
    merge_strategy: str | None = None
    env_file_specs: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    env_source_dir: str | None = None
    current_step_index: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    agent_runner_started_at: str | None = None
    total_tokens_read: int = 0
    total_tokens_write: int = 0
    total_tokens_cache: int = 0
    total_duration_ms: int = 0
    total_num_actions: int = 0
    token_usage_by_model: list[dict[str, Any]] | None = None
    transition_tracker: dict[str, Any] | None = None
    run_snapshot: dict[str, Any] = Field(default_factory=dict)


class RunDeleted(WorkflowEvent):
    """Emitted when a user deletes a run."""

    event_type: str = "run_deleted"
    deleted_by: str | None = None
    reason: str | None = None


class StepCreated(WorkflowEvent):
    """Created when an initial step is materialized for a new run."""

    event_type: str = "step_created"
    step_id: str = ""
    config_id: str = ""
    title: str = ""
    order_index: int = 0
    condition: dict[str, Any] | None = None
    step_index: int | None = None
    completed: bool = False
    human_approval: dict[str, Any] | None = None
    skipped: bool = False
    skip_reason: str | None = None


class RunWorktreeUpdated(WorkflowEvent):
    """Worktree metadata assigned to a run after worktree creation."""

    event_type: str = "run_worktree_updated"
    worktree_path: str
    source_branch_sha: str | None = None


class RunWorktreeCreationRequested(WorkflowEvent):
    """Emitted before attempting to create or recover a run worktree."""

    event_type: str = "run_worktree_creation_requested"
    repo_name: str
    source_branch: str


class RunWorktreeCreationFailed(WorkflowEvent):
    """Emitted when required run worktree setup fails."""

    event_type: str = "run_worktree_creation_failed"
    error: str


class RunWorktreeResetRequested(WorkflowEvent):
    """Emitted before a destructive run worktree reset starts."""

    event_type: str = "run_worktree_reset_requested"
    worktree_path: str
    reset_type: str
    target_ref: str | None = None
    branch_name: str | None = None
    head_before: str | None = None
    reason: str | None = None


class RunWorktreeResetCompleted(WorkflowEvent):
    """Emitted after a destructive run worktree reset completes."""

    event_type: str = "run_worktree_reset_completed"
    worktree_path: str
    reset_type: str
    target_ref: str | None = None
    branch_name: str | None = None
    head_before: str | None = None
    head_after: str | None = None
    reason: str | None = None


class RunWorktreeResetFailed(WorkflowEvent):
    """Emitted when a destructive run worktree reset fails."""

    event_type: str = "run_worktree_reset_failed"
    worktree_path: str
    reset_type: str
    error: str
    target_ref: str | None = None
    branch_name: str | None = None
    head_before: str | None = None
    reason: str | None = None


class RunWorktreeCommitRequested(WorkflowEvent):
    """Emitted before orchestrator auto-commits run worktree changes."""

    event_type: str = "run_worktree_commit_requested"
    task_id: str
    attempt_id: str | None = None
    worktree_path: str
    commit_type: str
    message: str
    reason: str | None = None
    head_before: str | None = None


class RunWorktreeCommitCompleted(WorkflowEvent):
    """Emitted after orchestrator auto-commit completes or no-ops."""

    event_type: str = "run_worktree_commit_completed"
    task_id: str
    attempt_id: str | None = None
    worktree_path: str
    commit_type: str
    message: str
    created_commit: bool = False
    reason: str | None = None
    head_before: str | None = None
    head_after: str | None = None
    commit_sha: str | None = None


class RunWorktreeCommitFailed(WorkflowEvent):
    """Emitted when orchestrator auto-commit fails."""

    event_type: str = "run_worktree_commit_failed"
    task_id: str
    attempt_id: str | None = None
    worktree_path: str
    commit_type: str
    message: str
    error: str
    reason: str | None = None
    head_before: str | None = None


class RunMetadataUpdated(WorkflowEvent):
    """Partial run metadata update emitted by runner infrastructure."""

    event_type: str = "run_metadata_updated"
    runner_config_delta: dict[str, Any] = Field(default_factory=dict)


class TaskCreated(WorkflowEvent):
    """Full initial state of a new task (including fan-out children)."""

    event_type: str = "task_created"
    task_id: str = ""
    step_id: str = ""
    step_index: int = 0
    config_id: str = ""
    title: str = ""
    complexity: str | None = None
    order_index: int = 0
    max_attempts: int = 3
    checklist: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    parent_task_id: str | None = None
    fan_out_index: int | None = None
    fan_out_input: str | None = None
    fan_out_output: str | None = None
    child_id: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    current_attempt: int = 0
    has_verification: bool = True
    pending_action_type: str | None = None
    pending_clarification_id: str | None = None


class TaskAttemptCreated(WorkflowEvent):
    """New attempt appended to a task."""

    event_type: str = "task_attempt_created"
    task_id: str = ""
    attempt_id: str = ""
    attempt_num: int = 0
    runner_type: str | None = None
    agent_model: str | None = None
    started_at: str | None = None
    new_task_status: TaskStatus = TaskStatus.BUILDING


class AttemptUpdated(WorkflowEvent):
    """Partial update to the latest attempt (streaming output, metrics, outcome)."""

    event_type: str = "attempt_updated"
    task_id: str = ""
    attempt_id: str = ""
    output_lines: list[str] | None = None
    error: str | None = None
    outcome: str | None = None
    builder_prompt: str | None = None
    verifier_prompt: str | None = None
    verifier_comment: str | None = None
    grade_snapshot: list[dict[str, Any]] | None = None
    completed_at: str | None = None
    paused_at: str | None = None
    clear_paused_state: bool = False
    auto_verify_results: list[dict[str, Any]] | None = None
    action_log: Any | None = None
    token_usage_by_model: list[dict[str, Any]] | None = None
    tokens_read: int | None = None
    tokens_write: int | None = None
    tokens_cache: int | None = None
    duration_ms: int | None = None
    num_actions: int | None = None
    agent_runner_type: AgentRunnerType | str | None = None
    agent_model: str | None = None
    agent_settings: dict[str, Any] | None = None
    start_commit: str | None = None
    end_commit: str | None = None
    new_task_status: TaskStatus | None = None
    apply_to_run_totals: bool = True


class ParentOversightFactsUpdated(WorkflowEvent):
    """Merged oversight fact patch for a run."""

    event_type: str = "parent_oversight_facts_updated"
    patch: dict[str, Any] = Field(default_factory=dict)


class FanOutChildrenCreated(WorkflowEvent):
    """Fan-out children tasks created for a step."""

    event_type: str = "fan_out_children_created"
    step_id: str = ""
    parent_task_id: str = ""
    children: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    parent_new_status: TaskStatus | None = None


class FanOutChildrenReset(WorkflowEvent):
    """Non-completed fan-out children reset to PENDING; parent to FAN_OUT_RUNNING."""

    event_type: str = "fan_out_children_reset"
    parent_task_id: str = ""


class FanOutChildRetried(WorkflowEvent):
    """Single failed fan-out child reset to PENDING; parent set to FAN_OUT_RUNNING."""

    event_type: str = "fan_out_child_retried"
    child_task_id: str = ""
    step_order_index: int = 0


class StepIndexRewound(WorkflowEvent):
    """Run's current_step_index set back to target if it was higher."""

    event_type: str = "step_index_rewound"
    target_step_index: int = 0


class SignalEnqueued(WorkflowEvent):
    """Emitted when a signal is enqueued for a run."""

    event_type: str = "signal_enqueued"
    signal_type: str = ""
    payload: dict[str, Any] | None = None


class SignalProcessed(WorkflowEvent):
    """Emitted when a signal has been consumed, linking back to its origin event."""

    event_type: str = "signal_processed"
    enqueued_position: int = 0


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
