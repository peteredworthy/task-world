"""Round-trip tests for all Pydantic WorkflowEvent subclasses.

Verifies construct → serialize → deserialize round-trips for every concrete
event type, checks enum field serialization to .value strings, and asserts
datetime fields produce ISO 8601 strings in model_dump(mode="json").
"""

from datetime import datetime, timezone

import pytest

from orchestrator.config.enums import AgentRunnerType, ChecklistStatus, RunStatus, TaskStatus
from orchestrator.workflow import (
    AgentChangedEvent,
    AgentDiedEvent,
    AgentErrorEvent,
    AgentFixCompleted,
    AgentFixStarted,
    AgentOutputEvent,
    ApprovalDecision,
    ApprovalRequested,
    AttemptUpdated,
    AutoVerifyCompleted,
    BackMergeCompleted,
    BackMergeReverted,
    ChildCompleted,
    ChildFailed,
    ChildSpawned,
    ChecklistGateEvaluated,
    ChecklistItemGraded,
    ChecklistItemUpdated,
    ClarificationRequested,
    ClarificationResponded,
    ConflictResolved,
    FanOutChildrenCreated,
    FanOutChildrenReset,
    FanOutChildRetried,
    FanOutCompleted,
    FanOutSpawned,
    GradeDetail,
    GradesEvaluated,
    HealthCheckEvent,
    ParentOversightFactsUpdated,
    PruneApplied,
    RunCreated,
    RunDeleted,
    RunStatusChanged,
    RunStepBackward,
    RunWorktreeCommitCompleted,
    RunWorktreeCommitFailed,
    RunWorktreeCommitRequested,
    RunWorktreeCreationFailed,
    RunWorktreeCreationRequested,
    RunWorktreeResetCompleted,
    RunWorktreeResetFailed,
    RunWorktreeResetRequested,
    RunWorktreeUpdated,
    SignalEnqueued,
    SignalProcessed,
    StepCompleted,
    StepCreated,
    StepHumanApprovalRecorded,
    StepIndexRewound,
    StepSkipped,
    TaskAttemptCreated,
    TaskCreated,
    TaskReverted,
    TaskStatusChanged,
    TestRunCompleted,
    TestRunStarted,
    WorkflowEvent,
)

NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
NOW_ISO = "2025-01-15T10:30:00Z"


def _round_trip(event: WorkflowEvent, cls: type) -> WorkflowEvent:
    """Serialize to JSON and deserialize back."""
    json_str = event.model_dump_json()
    return cls.model_validate_json(json_str)


def _assert_no_datetime_objects(d: dict) -> None:
    """Assert no raw datetime objects anywhere in a dict (recursively)."""
    for v in d.values():
        assert not isinstance(v, datetime), f"Expected str, got datetime: {v!r}"
        if isinstance(v, dict):
            _assert_no_datetime_objects(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _assert_no_datetime_objects(item)
                assert not isinstance(item, datetime)


# ---------------------------------------------------------------------------
# TaskStatusChanged
# ---------------------------------------------------------------------------


def test_task_status_changed_round_trip() -> None:
    event = TaskStatusChanged(
        run_id="run-1",
        event_type="task_status_changed",
        timestamp=NOW,
        task_id="task-1",
        old_status=TaskStatus.PENDING,
        new_status=TaskStatus.BUILDING,
        start_commit="abc123",
    )
    rt = _round_trip(event, TaskStatusChanged)
    assert rt == event
    assert rt.task_id == "task-1"
    assert rt.old_status == TaskStatus.PENDING
    assert rt.new_status == TaskStatus.BUILDING
    assert rt.start_commit == "abc123"
    assert rt.end_commit is None


def test_task_status_changed_enum_serialization() -> None:
    event = TaskStatusChanged(
        run_id="run-1",
        event_type="task_status_changed",
        timestamp=NOW,
        task_id="t1",
        old_status=TaskStatus.BUILDING,
        new_status=TaskStatus.VERIFYING,
    )
    d = event.model_dump(mode="json")
    assert d["old_status"] == "building"
    assert d["new_status"] == "verifying"
    assert d["event_type"] == "task_status_changed"
    _assert_no_datetime_objects(d)
    assert isinstance(d["timestamp"], str)
    assert d["timestamp"] == NOW_ISO


# ---------------------------------------------------------------------------
# RunStatusChanged
# ---------------------------------------------------------------------------


def test_run_status_changed_round_trip() -> None:
    event = RunStatusChanged(
        run_id="run-1",
        event_type="run_status_changed",
        timestamp=NOW,
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
        pause_reason=None,
        last_error=None,
    )
    rt = _round_trip(event, RunStatusChanged)
    assert rt == event
    assert rt.old_status == RunStatus.DRAFT
    assert rt.new_status == RunStatus.ACTIVE


def test_run_status_changed_enum_serialization() -> None:
    event = RunStatusChanged(
        run_id="run-1",
        event_type="run_status_changed",
        timestamp=NOW,
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
    )
    d = event.model_dump(mode="json")
    assert d["old_status"] == "draft"
    assert d["new_status"] == "active"
    _assert_no_datetime_objects(d)


# ---------------------------------------------------------------------------
# ChecklistGateEvaluated
# ---------------------------------------------------------------------------


def test_checklist_gate_evaluated_round_trip() -> None:
    event = ChecklistGateEvaluated(
        run_id="run-1",
        event_type="checklist_gate_evaluated",
        timestamp=NOW,
        task_id="task-1",
        passed=False,
        blocking_items=["R1", "R2"],
    )
    rt = _round_trip(event, ChecklistGateEvaluated)
    assert rt == event
    assert rt.blocking_items == ["R1", "R2"]
    assert rt.passed is False


def test_checklist_gate_evaluated_empty_list() -> None:
    event = ChecklistGateEvaluated(
        run_id="run-1",
        event_type="checklist_gate_evaluated",
        timestamp=NOW,
        task_id="t1",
        passed=True,
    )
    rt = _round_trip(event, ChecklistGateEvaluated)
    assert rt.blocking_items == []
    assert rt.passed is True


def test_checklist_item_updated_round_trip() -> None:
    event = ChecklistItemUpdated(
        run_id="run-1",
        event_type="checklist_item_updated",
        timestamp=NOW,
        task_id="task-1",
        req_id="R1",
        status=ChecklistStatus.DONE,
        note="verified",
    )
    rt = _round_trip(event, ChecklistItemUpdated)
    assert rt == event
    assert rt.task_id == "task-1"
    assert rt.req_id == "R1"
    assert rt.status == ChecklistStatus.DONE
    assert rt.note == "verified"


def test_checklist_item_graded_round_trip() -> None:
    event = ChecklistItemGraded(
        run_id="run-1",
        event_type="checklist_item_graded",
        timestamp=NOW,
        task_id="task-1",
        req_id="R1",
        grade="A",
        grade_reason="complete",
    )
    rt = _round_trip(event, ChecklistItemGraded)
    assert rt == event
    assert rt.task_id == "task-1"
    assert rt.req_id == "R1"
    assert rt.grade == "A"
    assert rt.grade_reason == "complete"


# ---------------------------------------------------------------------------
# GradeDetail + GradesEvaluated
# ---------------------------------------------------------------------------


def test_grade_detail_round_trip() -> None:
    detail = GradeDetail(req_id="R1", grade="A", grade_reason="Excellent work")
    json_str = detail.model_dump_json()
    rt = GradeDetail.model_validate_json(json_str)
    assert rt == detail
    assert rt.req_id == "R1"
    assert rt.grade == "A"
    assert rt.grade_reason == "Excellent work"


def test_grades_evaluated_round_trip() -> None:
    event = GradesEvaluated(
        run_id="run-1",
        event_type="grades_evaluated",
        timestamp=NOW,
        task_id="task-1",
        passed=True,
        failing_items=[],
        grade_details=[
            GradeDetail(req_id="R1", grade="A", grade_reason="Correct"),
            GradeDetail(req_id="R2", grade="B", grade_reason="Close enough"),
        ],
    )
    rt = _round_trip(event, GradesEvaluated)
    assert rt == event
    assert len(rt.grade_details) == 2
    assert rt.grade_details[0].req_id == "R1"
    assert rt.grade_details[0].grade == "A"
    assert rt.grade_details[1].req_id == "R2"


def test_grades_evaluated_failing_items() -> None:
    event = GradesEvaluated(
        run_id="run-1",
        event_type="grades_evaluated",
        timestamp=NOW,
        task_id="t1",
        passed=False,
        failing_items=["R1: Grade D below A"],
    )
    d = event.model_dump(mode="json")
    assert d["failing_items"] == ["R1: Grade D below A"]
    assert d["event_type"] == "grades_evaluated"


# ---------------------------------------------------------------------------
# AutoVerifyCompleted
# ---------------------------------------------------------------------------


def test_auto_verify_completed_round_trip() -> None:
    event = AutoVerifyCompleted(
        run_id="run-1",
        event_type="auto_verify_completed",
        timestamp=NOW,
        task_id="t1",
        passed=False,
        failing_must_items=["test A"],
        results=[{"cmd": "pytest", "exit_code": 1}],
    )
    rt = _round_trip(event, AutoVerifyCompleted)
    assert rt == event
    assert rt.failing_must_items == ["test A"]
    assert rt.results[0]["cmd"] == "pytest"


# ---------------------------------------------------------------------------
# StepCompleted
# ---------------------------------------------------------------------------


def test_step_completed_round_trip() -> None:
    event = StepCompleted(
        run_id="run-1",
        event_type="step_completed",
        timestamp=NOW,
        step_index=2,
        step_id="step-2",
    )
    rt = _round_trip(event, StepCompleted)
    assert rt == event
    assert rt.step_index == 2
    assert rt.step_id == "step-2"


# ---------------------------------------------------------------------------
# StepSkipped (has default event_type)
# ---------------------------------------------------------------------------


def test_step_skipped_round_trip() -> None:
    event = StepSkipped(
        run_id="run-1",
        event_type="step_skipped",
        timestamp=NOW,
        step_index=1,
        step_id="step-1",
        condition="when: false",
        skip_reason="Condition evaluated to false",
        completed=True,
        current_step_index_after=2,
    )
    rt = _round_trip(event, StepSkipped)
    assert rt == event
    assert rt.event_type == "step_skipped"
    assert rt.skip_reason == "Condition evaluated to false"
    assert rt.completed is True
    assert rt.current_step_index_after == 2


def test_step_skipped_default_event_type() -> None:
    event = StepSkipped(run_id="run-1", event_type="step_skipped", timestamp=NOW)
    assert event.event_type == "step_skipped"
    assert event.completed is True
    assert event.current_step_index_after is None
    d = event.model_dump(mode="json")
    assert d["event_type"] == "step_skipped"


# ---------------------------------------------------------------------------
# StepHumanApprovalRecorded (has default event_type)
# ---------------------------------------------------------------------------


def test_step_human_approval_recorded_round_trip() -> None:
    event = StepHumanApprovalRecorded(
        run_id="run-1",
        timestamp=NOW,
        step_id="step-1",
        approved_by="reviewer@example.com",
        approved_at=NOW,
        comment="Approved",
    )
    rt = _round_trip(event, StepHumanApprovalRecorded)
    assert rt == event
    assert rt.event_type == "step_human_approval_recorded"
    assert rt.step_id == "step-1"
    assert rt.approved_by == "reviewer@example.com"
    assert rt.approved_at == NOW
    assert rt.comment == "Approved"
    d = event.model_dump(mode="json")
    assert d["approved_at"] == NOW_ISO
    _assert_no_datetime_objects(d)


# ---------------------------------------------------------------------------
# RunStepBackward
# ---------------------------------------------------------------------------


def test_run_step_backward_round_trip() -> None:
    event = RunStepBackward(
        run_id="run-1",
        event_type="run_step_backward",
        timestamp=NOW,
        from_step_index=3,
        to_step_index=1,
        reason="Failed verification",
        transition_tracker_delta={"S-02->S-01": 1},
    )
    rt = _round_trip(event, RunStepBackward)
    assert rt == event
    assert rt.from_step_index == 3
    assert rt.to_step_index == 1
    assert rt.transition_tracker_delta == {"S-02->S-01": 1}


def test_run_step_backward_default_delta_none() -> None:
    event = RunStepBackward(
        run_id="run-1",
        event_type="run_step_backward",
        timestamp=NOW,
    )
    rt = _round_trip(event, RunStepBackward)
    assert rt.transition_tracker_delta is None


# ---------------------------------------------------------------------------
# AgentChangedEvent
# ---------------------------------------------------------------------------


def test_agent_changed_event_round_trip() -> None:
    event = AgentChangedEvent(
        run_id="run-1",
        event_type="agent_changed",
        timestamp=NOW,
        old_agent=AgentRunnerType.CLI_SUBPROCESS,
        new_agent=AgentRunnerType.CLAUDE_SDK,
        old_agent_runner_config={"model": "gpt-4"},
        new_agent_runner_config={"model": "claude-3"},
        reason="user_changed_on_resume",
    )
    rt = _round_trip(event, AgentChangedEvent)
    assert rt == event
    assert rt.old_agent == AgentRunnerType.CLI_SUBPROCESS
    assert rt.new_agent == AgentRunnerType.CLAUDE_SDK


def test_agent_changed_event_enum_serialization() -> None:
    event = AgentChangedEvent(
        run_id="run-1",
        timestamp=NOW,
        old_agent=AgentRunnerType.CLI_SUBPROCESS,
        new_agent=AgentRunnerType.CLAUDE_SDK,
    )
    assert event.event_type == "agent_changed"
    d = event.model_dump(mode="json")
    assert d["event_type"] == "agent_changed"
    assert d["old_agent"] == AgentRunnerType.CLI_SUBPROCESS.value
    assert d["new_agent"] == AgentRunnerType.CLAUDE_SDK.value


# ---------------------------------------------------------------------------
# AgentDiedEvent
# ---------------------------------------------------------------------------


def test_agent_died_event_round_trip() -> None:
    event = AgentDiedEvent(
        run_id="run-1",
        event_type="agent_died",
        timestamp=NOW,
        agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
        exit_code=1,
        reason="agent_process_died",
        task_id="task-1",
    )
    rt = _round_trip(event, AgentDiedEvent)
    assert rt == event
    assert rt.exit_code == 1
    assert rt.agent_runner_type == AgentRunnerType.CLI_SUBPROCESS


# ---------------------------------------------------------------------------
# TaskReverted
# ---------------------------------------------------------------------------


def test_run_worktree_reset_events_round_trip() -> None:
    requested = RunWorktreeResetRequested(
        run_id="run-1",
        timestamp=NOW,
        worktree_path="/tmp/worktree",
        reset_type="checkout_ref",
        target_ref="abc123",
        branch_name="orchestrator/run-run-1",
        reason="recovery_reset_branch",
    )
    completed = RunWorktreeResetCompleted(
        run_id="run-1",
        timestamp=NOW,
        worktree_path="/tmp/worktree",
        reset_type="checkout_ref",
        target_ref="abc123",
        branch_name="orchestrator/run-run-1",
        reason="recovery_reset_branch",
    )
    failed = RunWorktreeResetFailed(
        run_id="run-1",
        timestamp=NOW,
        worktree_path="/tmp/worktree",
        reset_type="discard_changes",
        error="git reset failed",
        reason="resume_reset_worktree",
    )

    assert _round_trip(requested, RunWorktreeResetRequested) == requested
    assert _round_trip(completed, RunWorktreeResetCompleted) == completed
    assert _round_trip(failed, RunWorktreeResetFailed) == failed
    assert requested.event_type == "run_worktree_reset_requested"
    assert completed.event_type == "run_worktree_reset_completed"
    assert failed.event_type == "run_worktree_reset_failed"


def test_task_reverted_round_trip() -> None:
    event = TaskReverted(
        run_id="run-1",
        event_type="task_reverted",
        timestamp=NOW,
        task_id="task-1",
        reverted_from_status=TaskStatus.BUILDING,
        task_snapshot={
            "id": "task-1",
            "status": "building",
            "current_attempt": 2,
            "attempts": [{"id": "attempt-2", "attempt_num": 2}],
        },
    )
    rt = _round_trip(event, TaskReverted)
    assert rt == event
    assert rt.task_snapshot["current_attempt"] == 2
    d = event.model_dump(mode="json")
    assert d["reverted_from_status"] == "building"
    assert d["task_snapshot"]["attempts"][0]["id"] == "attempt-2"


# ---------------------------------------------------------------------------
# HealthCheckEvent
# ---------------------------------------------------------------------------


def test_health_check_event_round_trip() -> None:
    event = HealthCheckEvent(
        run_id="run-1",
        event_type="health_check",
        timestamp=NOW,
        phase="completed",
        message="All checks passed",
    )
    rt = _round_trip(event, HealthCheckEvent)
    assert rt == event
    assert rt.phase == "completed"


def test_health_check_event_default_event_type() -> None:
    event = HealthCheckEvent(run_id="run-1", timestamp=NOW)
    assert event.event_type == "health_check"


# ---------------------------------------------------------------------------
# AgentOutputEvent
# ---------------------------------------------------------------------------


def test_agent_output_event_round_trip() -> None:
    event = AgentOutputEvent(
        run_id="run-1",
        event_type="agent_output",
        timestamp=NOW,
        task_id="task-1",
        attempt_num=2,
        lines=["line 1", "line 2", "line 3"],
        line_offset=10,
    )
    rt = _round_trip(event, AgentOutputEvent)
    assert rt == event
    assert rt.lines == ["line 1", "line 2", "line 3"]
    assert rt.line_offset == 10


def test_agent_output_event_default_event_type() -> None:
    event = AgentOutputEvent(run_id="run-1", timestamp=NOW)
    assert event.event_type == "agent_output"


# ---------------------------------------------------------------------------
# AgentErrorEvent
# ---------------------------------------------------------------------------


def test_agent_error_event_round_trip() -> None:
    event = AgentErrorEvent(
        run_id="run-1",
        event_type="agent_error",
        timestamp=NOW,
        task_id="task-1",
        attempt_num=1,
        error_type="AgentExecutionError",
        error_message="Process exited with code 1",
    )
    rt = _round_trip(event, AgentErrorEvent)
    assert rt == event
    assert rt.error_type == "AgentExecutionError"


def test_agent_error_event_default_event_type() -> None:
    event = AgentErrorEvent(run_id="run-1", timestamp=NOW)
    assert event.event_type == "agent_error"


# ---------------------------------------------------------------------------
# ClarificationRequested (has default event_type)
# ---------------------------------------------------------------------------


def test_clarification_requested_round_trip() -> None:
    event = ClarificationRequested(
        run_id="run-1",
        event_type="clarification_requested",
        timestamp=NOW,
        task_id="task-1",
        request_id="req-123",
        attempt_num=2,
        question_count=2,
        questions=[{"id": "q1", "question": "What?"}],
    )
    rt = _round_trip(event, ClarificationRequested)
    assert rt == event
    assert rt.event_type == "clarification_requested"
    assert rt.attempt_num == 2
    assert rt.question_count == 2
    assert rt.questions[0]["id"] == "q1"


def test_clarification_requested_default_event_type() -> None:
    event = ClarificationRequested(
        run_id="run-1", event_type="clarification_requested", timestamp=NOW
    )
    assert event.event_type == "clarification_requested"


# ---------------------------------------------------------------------------
# ClarificationResponded (has default event_type)
# ---------------------------------------------------------------------------


def test_clarification_responded_round_trip() -> None:
    event = ClarificationResponded(
        run_id="run-1",
        event_type="clarification_responded",
        timestamp=NOW,
        task_id="task-1",
        request_id="req-123",
        response_id="resp-123",
        answers=[{"question_id": "q1", "selected_option": "A"}],
        responded_by="user@example.com",
        responded_at=NOW,
        new_status=TaskStatus.BUILDING,
        run_config_delta={"_compressed_decisions_request_id": "req-123"},
    )
    rt = _round_trip(event, ClarificationResponded)
    assert rt == event
    assert rt.event_type == "clarification_responded"
    assert rt.request_id == "req-123"
    assert rt.response_id == "resp-123"
    assert rt.new_status == TaskStatus.BUILDING
    assert rt.run_config_delta == {"_compressed_decisions_request_id": "req-123"}


def test_clarification_responded_accepts_legacy_payload() -> None:
    event = ClarificationResponded(
        run_id="run-1",
        event_type="clarification_responded",
        timestamp=NOW,
        task_id="task-1",
        request_id="req-123",
    )
    assert event.response_id is None
    assert event.answers == []
    assert event.responded_at is None
    assert event.new_status is None
    assert event.run_config_delta == {}


# ---------------------------------------------------------------------------
# ApprovalRequested
# ---------------------------------------------------------------------------


def test_approval_requested_round_trip() -> None:
    event = ApprovalRequested(
        run_id="run-1",
        event_type="approval_requested",
        timestamp=NOW,
        task_id="task-1",
        step_id="step-1",
        summary_artifact="path/to/summary.md",
    )
    rt = _round_trip(event, ApprovalRequested)
    assert rt == event
    assert rt.summary_artifact == "path/to/summary.md"


# ---------------------------------------------------------------------------
# ApprovalDecision
# ---------------------------------------------------------------------------


def test_approval_decision_round_trip() -> None:
    event = ApprovalDecision(
        run_id="run-1",
        event_type="approval_decision",
        timestamp=NOW,
        task_id="task-1",
        step_id="step-1",
        approved=True,
        comment="Looks good",
        decided_by="user@example.com",
        new_status=TaskStatus.COMPLETED,
        current_attempt=1,
        checklist=[{"req_id": "R1", "note": None}],
        attempt_snapshots=[{"id": "attempt-1", "attempt_num": 1, "outcome": "passed"}],
    )
    rt = _round_trip(event, ApprovalDecision)
    assert rt == event
    assert rt.approved is True
    assert rt.decided_by == "user@example.com"
    assert rt.new_status == TaskStatus.COMPLETED
    assert rt.current_attempt == 1
    assert rt.attempt_snapshots[0]["outcome"] == "passed"


def test_approval_decision_accepts_legacy_payload() -> None:
    event = ApprovalDecision(
        run_id="run-1",
        event_type="approval_decision",
        timestamp=NOW,
        task_id="task-1",
        step_id="step-1",
        approved=False,
        decided_by="user@example.com",
    )
    assert event.new_status is None
    assert event.current_attempt is None
    assert event.checklist is None
    assert event.attempt_snapshots == []


# ---------------------------------------------------------------------------
# PruneApplied
# ---------------------------------------------------------------------------


def test_prune_applied_round_trip() -> None:
    event = PruneApplied(
        run_id="run-1",
        event_type="prune_applied",
        timestamp=NOW,
        commit_sha="abc123",
        files_affected=5,
        hunks_removed=10,
        lines_removed=200,
    )
    rt = _round_trip(event, PruneApplied)
    assert rt == event
    assert rt.files_affected == 5
    assert rt.lines_removed == 200


# ---------------------------------------------------------------------------
# TestRunStarted
# ---------------------------------------------------------------------------


def test_test_run_started_round_trip() -> None:
    event = TestRunStarted(
        run_id="run-1",
        event_type="test_run_started",
        timestamp=NOW,
        test_run_id="tr-456",
    )
    rt = _round_trip(event, TestRunStarted)
    assert rt == event
    assert rt.test_run_id == "tr-456"


# ---------------------------------------------------------------------------
# TestRunCompleted
# ---------------------------------------------------------------------------


def test_test_run_completed_round_trip() -> None:
    event = TestRunCompleted(
        run_id="run-1",
        event_type="test_run_completed",
        timestamp=NOW,
        test_run_id="tr-456",
        status="passed",
        duration_ms=1500,
    )
    rt = _round_trip(event, TestRunCompleted)
    assert rt == event
    assert rt.status == "passed"
    assert rt.duration_ms == 1500


# ---------------------------------------------------------------------------
# ConflictResolved
# ---------------------------------------------------------------------------


def test_conflict_resolved_round_trip() -> None:
    event = ConflictResolved(
        run_id="run-1",
        event_type="conflict_resolved",
        timestamp=NOW,
        file_path="src/foo.py",
        remaining_conflicts=3,
    )
    rt = _round_trip(event, ConflictResolved)
    assert rt == event
    assert rt.file_path == "src/foo.py"
    assert rt.remaining_conflicts == 3


# ---------------------------------------------------------------------------
# BackMergeCompleted
# ---------------------------------------------------------------------------


def test_back_merge_completed_round_trip() -> None:
    event = BackMergeCompleted(
        run_id="run-1",
        event_type="back_merge_completed",
        timestamp=NOW,
        status="clean",
        merge_commit_sha="def456",
        conflict_count=0,
    )
    rt = _round_trip(event, BackMergeCompleted)
    assert rt == event
    assert rt.status == "clean"
    assert rt.merge_commit_sha == "def456"


# ---------------------------------------------------------------------------
# BackMergeReverted
# ---------------------------------------------------------------------------


def test_back_merge_reverted_round_trip() -> None:
    event = BackMergeReverted(
        run_id="run-1",
        event_type="back_merge_reverted",
        timestamp=NOW,
        reverted_commit="abc123",
        new_head="def456",
    )
    rt = _round_trip(event, BackMergeReverted)
    assert rt == event
    assert rt.reverted_commit == "abc123"
    assert rt.new_head == "def456"


# ---------------------------------------------------------------------------
# AgentFixStarted
# ---------------------------------------------------------------------------


def test_agent_fix_started_round_trip() -> None:
    event = AgentFixStarted(
        run_id="run-1",
        event_type="agent_fix_started",
        timestamp=NOW,
        job_id="job-789",
        agent_runner_type="cli_subprocess",
    )
    rt = _round_trip(event, AgentFixStarted)
    assert rt == event
    assert rt.job_id == "job-789"
    assert rt.agent_runner_type == "cli_subprocess"


# ---------------------------------------------------------------------------
# AgentFixCompleted
# ---------------------------------------------------------------------------


def test_agent_fix_completed_round_trip() -> None:
    event = AgentFixCompleted(
        run_id="run-1",
        event_type="agent_fix_completed",
        timestamp=NOW,
        job_id="job-789",
        status="completed",
    )
    rt = _round_trip(event, AgentFixCompleted)
    assert rt == event
    assert rt.status == "completed"


# ---------------------------------------------------------------------------
# FanOutSpawned
# ---------------------------------------------------------------------------


def test_fan_out_spawned_round_trip() -> None:
    event = FanOutSpawned(
        run_id="run-1",
        event_type="fan_out_spawned",
        timestamp=NOW,
        parent_task_id="task-parent",
        child_count=4,
    )
    rt = _round_trip(event, FanOutSpawned)
    assert rt == event
    assert rt.child_count == 4


# ---------------------------------------------------------------------------
# ChildSpawned
# ---------------------------------------------------------------------------


def test_child_spawned_round_trip() -> None:
    event = ChildSpawned(
        run_id="run-1",
        event_type="child_spawned",
        timestamp=NOW,
        parent_task_id="task-parent",
        child_task_id="task-child-1",
        child_id="uuid-child-1",
        fan_out_index=0,
        fan_out_input="input data",
    )
    rt = _round_trip(event, ChildSpawned)
    assert rt == event
    assert rt.child_id == "uuid-child-1"
    assert rt.fan_out_index == 0


# ---------------------------------------------------------------------------
# ChildCompleted
# ---------------------------------------------------------------------------


def test_child_completed_round_trip() -> None:
    event = ChildCompleted(
        run_id="run-1",
        event_type="child_completed",
        timestamp=NOW,
        parent_task_id="task-parent",
        child_task_id="task-child-1",
        child_id="uuid-child-1",
        fan_out_index=0,
        attempt_num=1,
        fan_out_output="output data",
    )
    rt = _round_trip(event, ChildCompleted)
    assert rt == event
    assert rt.fan_out_output == "output data"


# ---------------------------------------------------------------------------
# ChildFailed
# ---------------------------------------------------------------------------


def test_child_failed_round_trip() -> None:
    event = ChildFailed(
        run_id="run-1",
        event_type="child_failed",
        timestamp=NOW,
        parent_task_id="task-parent",
        child_task_id="task-child-2",
        child_id="uuid-child-2",
        fan_out_index=1,
        attempt_num=3,
        error="Max attempts exceeded",
    )
    rt = _round_trip(event, ChildFailed)
    assert rt == event
    assert rt.error == "Max attempts exceeded"


# ---------------------------------------------------------------------------
# FanOutCompleted
# ---------------------------------------------------------------------------


def test_fan_out_completed_round_trip() -> None:
    event = FanOutCompleted(
        run_id="run-1",
        event_type="fan_out_completed",
        timestamp=NOW,
        parent_task_id="task-parent",
        all_passed=False,
        completed_count=3,
        failed_count=1,
    )
    rt = _round_trip(event, FanOutCompleted)
    assert rt == event
    assert rt.all_passed is False
    assert rt.completed_count == 3
    assert rt.failed_count == 1


# ---------------------------------------------------------------------------
# Cross-cutting: timestamp default factory
# ---------------------------------------------------------------------------


def test_timestamp_default_factory() -> None:
    """WorkflowEvent timestamp is auto-set when not provided."""
    event = RunStatusChanged(
        run_id="run-1",
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=RunStatus.ACTIVE,
    )
    assert event.timestamp is not None
    assert event.timestamp.tzinfo is not None


# ---------------------------------------------------------------------------
# Cross-cutting: mutable list defaults are independent instances
# ---------------------------------------------------------------------------


def test_mutable_list_defaults_are_independent() -> None:
    """Each event instance gets its own default list — no shared state."""
    e1 = ChecklistGateEvaluated(run_id="r1", event_type="e", timestamp=NOW)
    e2 = ChecklistGateEvaluated(run_id="r2", event_type="e", timestamp=NOW)
    e1.blocking_items.append("R1")
    assert e2.blocking_items == []


# ---------------------------------------------------------------------------
# Cross-cutting: event_type string values preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event,expected_type",
    [
        (
            RunStatusChanged(
                run_id="r",
                event_type="run_status_changed",
                timestamp=NOW,
                old_status=RunStatus.DRAFT,
                new_status=RunStatus.ACTIVE,
            ),
            "run_status_changed",
        ),
        (
            TaskStatusChanged(
                run_id="r",
                event_type="task_status_changed",
                timestamp=NOW,
            ),
            "task_status_changed",
        ),
        (
            AgentOutputEvent(
                run_id="r",
                timestamp=NOW,
            ),
            "agent_output",
        ),
        (
            AgentErrorEvent(
                run_id="r",
                timestamp=NOW,
            ),
            "agent_error",
        ),
        (
            HealthCheckEvent(
                run_id="r",
                timestamp=NOW,
            ),
            "health_check",
        ),
        (
            ClarificationRequested(run_id="r", event_type="clarification_requested", timestamp=NOW),
            "clarification_requested",
        ),
        (
            ClarificationResponded(run_id="r", event_type="clarification_responded", timestamp=NOW),
            "clarification_responded",
        ),
        (
            RunDeleted(run_id="r", event_type="run_deleted", timestamp=NOW),
            "run_deleted",
        ),
        (
            StepSkipped(run_id="r", event_type="step_skipped", timestamp=NOW),
            "step_skipped",
        ),
    ],
)
def test_event_type_string_value(event: WorkflowEvent, expected_type: str) -> None:
    d = event.model_dump(mode="json")
    assert d["event_type"] == expected_type
    rt_json = event.model_dump_json()
    # event_type appears in the JSON string
    assert f'"event_type":"{expected_type}"' in rt_json


# ---------------------------------------------------------------------------
# RunCreated
# ---------------------------------------------------------------------------


def test_run_created_round_trip() -> None:
    event = RunCreated(
        run_id="run-1",
        event_type="run_created",
        timestamp=NOW,
        routine_id="routine-abc",
        project_path="/home/user/project",
        repo_name="my-repo",
        status=RunStatus.DRAFT,
        config={"key": "value"},
        parent_run_id=None,
        parent_task_id=None,
        created_at="2025-01-15T10:00:00Z",
        updated_at="2025-01-15T10:01:00Z",
        started_at="2025-01-15T10:02:00Z",
        completed_at="2025-01-15T10:03:00Z",
        agent_runner_started_at="2025-01-15T10:02:30Z",
        total_tokens_read=100,
        total_tokens_write=50,
        total_tokens_cache=10,
        total_duration_ms=1500,
        total_num_actions=5,
        token_usage_by_model=[{"model": "gpt-test", "input_tokens": 3}],
        transition_tracker={"counts": {"S-02->S-01": 2}},
        run_snapshot={
            "id": "run-1",
            "repo_name": "my-repo",
            "steps": [{"id": "step-1", "tasks": [{"id": "task-1"}]}],
        },
    )
    rt = _round_trip(event, RunCreated)
    assert rt == event
    assert rt.routine_id == "routine-abc"
    assert rt.repo_name == "my-repo"
    assert rt.status == RunStatus.DRAFT
    assert rt.config == {"key": "value"}
    assert rt.parent_run_id is None
    assert rt.created_at == "2025-01-15T10:00:00Z"
    assert rt.updated_at == "2025-01-15T10:01:00Z"
    assert rt.started_at == "2025-01-15T10:02:00Z"
    assert rt.completed_at == "2025-01-15T10:03:00Z"
    assert rt.agent_runner_started_at == "2025-01-15T10:02:30Z"
    assert rt.total_tokens_read == 100
    assert rt.total_tokens_write == 50
    assert rt.total_tokens_cache == 10
    assert rt.total_duration_ms == 1500
    assert rt.total_num_actions == 5
    assert rt.token_usage_by_model == [{"model": "gpt-test", "input_tokens": 3}]
    assert rt.transition_tracker == {"counts": {"S-02->S-01": 2}}
    assert rt.run_snapshot["steps"][0]["tasks"][0]["id"] == "task-1"


def test_run_created_enum_serialization() -> None:
    event = RunCreated(
        run_id="run-1",
        event_type="run_created",
        timestamp=NOW,
        status=RunStatus.ACTIVE,
        repo_name="repo",
    )
    d = event.model_dump(mode="json")
    assert d["status"] == "active"
    assert d["transition_tracker"] is None
    _assert_no_datetime_objects(d)


def test_run_created_with_parent() -> None:
    event = RunCreated(
        run_id="run-child",
        event_type="run_created",
        timestamp=NOW,
        repo_name="repo",
        parent_run_id="run-parent",
        parent_task_id="task-parent",
    )
    rt = _round_trip(event, RunCreated)
    assert rt.parent_run_id == "run-parent"
    assert rt.parent_task_id == "task-parent"


def test_run_deleted_round_trip() -> None:
    event = RunDeleted(
        run_id="run-1",
        event_type="run_deleted",
        timestamp=NOW,
        deleted_by="user@example.com",
        reason="cleanup",
    )
    rt = _round_trip(event, RunDeleted)
    assert rt == event
    assert rt.event_type == "run_deleted"
    assert rt.deleted_by == "user@example.com"
    assert rt.reason == "cleanup"


def test_run_deleted_accepts_minimal_payload() -> None:
    event = RunDeleted(run_id="run-1", event_type="run_deleted", timestamp=NOW)
    assert event.deleted_by is None
    assert event.reason is None


def test_run_worktree_updated_round_trip() -> None:
    event = RunWorktreeUpdated(
        run_id="run-1",
        event_type="run_worktree_updated",
        timestamp=NOW,
        worktree_path="/tmp/worktrees/run-1",
        source_branch_sha="abc123",
    )
    rt = _round_trip(event, RunWorktreeUpdated)
    assert rt == event
    assert rt.worktree_path == "/tmp/worktrees/run-1"
    assert rt.source_branch_sha == "abc123"


def test_run_worktree_creation_requested_round_trip() -> None:
    event = RunWorktreeCreationRequested(
        run_id="run-1",
        event_type="run_worktree_creation_requested",
        timestamp=NOW,
        repo_name="repo",
        source_branch="main",
    )
    rt = _round_trip(event, RunWorktreeCreationRequested)
    assert rt == event
    assert rt.repo_name == "repo"
    assert rt.source_branch == "main"


def test_run_worktree_creation_failed_round_trip() -> None:
    event = RunWorktreeCreationFailed(
        run_id="run-1",
        event_type="run_worktree_creation_failed",
        timestamp=NOW,
        error="repo missing",
    )
    rt = _round_trip(event, RunWorktreeCreationFailed)
    assert rt == event
    assert rt.error == "repo missing"


def test_run_worktree_reset_requested_round_trip() -> None:
    event = RunWorktreeResetRequested(
        run_id="run-1",
        event_type="run_worktree_reset_requested",
        timestamp=NOW,
        worktree_path="/tmp/worktrees/run-1",
        reset_type="resume_uncommitted",
        head_before="abc123",
        reason="resume_strategy=reset_worktree",
    )
    rt = _round_trip(event, RunWorktreeResetRequested)
    assert rt == event
    assert rt.reset_type == "resume_uncommitted"
    assert rt.head_before == "abc123"


def test_run_worktree_reset_completed_round_trip() -> None:
    event = RunWorktreeResetCompleted(
        run_id="run-1",
        event_type="run_worktree_reset_completed",
        timestamp=NOW,
        worktree_path="/tmp/worktrees/run-1",
        reset_type="checkout_ref",
        target_ref="def456",
        branch_name="orchestrator/run-run-1",
        head_before="abc123",
        head_after="def456",
        reason="recovery_reset_branch",
    )
    rt = _round_trip(event, RunWorktreeResetCompleted)
    assert rt == event
    assert rt.target_ref == "def456"
    assert rt.head_after == "def456"


def test_run_worktree_reset_failed_round_trip() -> None:
    event = RunWorktreeResetFailed(
        run_id="run-1",
        event_type="run_worktree_reset_failed",
        timestamp=NOW,
        worktree_path="/tmp/worktrees/run-1",
        reset_type="resume_uncommitted",
        error="git reset failed",
        head_before="abc123",
    )
    rt = _round_trip(event, RunWorktreeResetFailed)
    assert rt == event
    assert rt.error == "git reset failed"


def test_run_worktree_commit_requested_round_trip() -> None:
    event = RunWorktreeCommitRequested(
        run_id="run-1",
        event_type="run_worktree_commit_requested",
        timestamp=NOW,
        task_id="task-1",
        attempt_id="attempt-1",
        worktree_path="/tmp/worktrees/run-1",
        commit_type="builder_submit",
        message="Auto-commit builder changes for task task-1",
        head_before="abc123",
        reason="apply_submission",
    )
    rt = _round_trip(event, RunWorktreeCommitRequested)
    assert rt == event
    assert rt.commit_type == "builder_submit"
    assert rt.message.startswith("Auto-commit")


def test_run_worktree_commit_completed_round_trip() -> None:
    event = RunWorktreeCommitCompleted(
        run_id="run-1",
        event_type="run_worktree_commit_completed",
        timestamp=NOW,
        task_id="task-1",
        attempt_id="attempt-1",
        worktree_path="/tmp/worktrees/run-1",
        commit_type="builder_submit",
        message="Auto-commit builder changes for task task-1",
        created_commit=True,
        head_before="abc123",
        head_after="def456",
        commit_sha="def456",
        reason="apply_submission",
    )
    rt = _round_trip(event, RunWorktreeCommitCompleted)
    assert rt == event
    assert rt.created_commit is True
    assert rt.commit_sha == "def456"


def test_run_worktree_commit_failed_round_trip() -> None:
    event = RunWorktreeCommitFailed(
        run_id="run-1",
        event_type="run_worktree_commit_failed",
        timestamp=NOW,
        task_id="task-1",
        attempt_id="attempt-1",
        worktree_path="/tmp/worktrees/run-1",
        commit_type="builder_submit",
        message="Auto-commit builder changes for task task-1",
        error="git commit failed",
        head_before="abc123",
        reason="apply_submission",
    )
    rt = _round_trip(event, RunWorktreeCommitFailed)
    assert rt == event
    assert rt.error == "git commit failed"


# ---------------------------------------------------------------------------
# StepCreated
# ---------------------------------------------------------------------------


def test_step_created_round_trip() -> None:
    event = StepCreated(
        run_id="run-1",
        event_type="step_created",
        timestamp=NOW,
        step_id="step-1",
        config_id="S-01",
        title="Plan",
        order_index=1,
        condition={"when": "needed"},
        step_index=1,
    )
    rt = _round_trip(event, StepCreated)
    assert rt == event
    assert rt.step_id == "step-1"
    assert rt.config_id == "S-01"
    assert rt.condition == {"when": "needed"}


# ---------------------------------------------------------------------------
# TaskCreated
# ---------------------------------------------------------------------------


def test_task_created_round_trip() -> None:
    event = TaskCreated(
        run_id="run-1",
        event_type="task_created",
        timestamp=NOW,
        task_id="task-1",
        step_id="step-1",
        step_index=0,
        config_id="T-01",
        title="Build it",
        complexity="standard",
        order_index=0,
        max_attempts=3,
        checklist=[{"id": "R1", "description": "Must pass"}],
        parent_task_id=None,
        fan_out_index=2,
        fan_out_input="input",
        fan_out_output="output",
        child_id="child-1",
        has_verification=False,
    )
    rt = _round_trip(event, TaskCreated)
    assert rt == event
    assert rt.task_id == "task-1"
    assert rt.step_id == "step-1"
    assert rt.config_id == "T-01"
    assert rt.checklist == [{"id": "R1", "description": "Must pass"}]
    assert rt.parent_task_id is None
    assert rt.fan_out_index == 2
    assert rt.fan_out_input == "input"
    assert rt.fan_out_output == "output"
    assert rt.child_id == "child-1"
    assert rt.has_verification is False
    assert event.model_dump(mode="json")["has_verification"] is False


def test_task_created_defaults() -> None:
    event = TaskCreated(run_id="r1", event_type="task_created", timestamp=NOW)
    d = event.model_dump(mode="json")
    assert d["checklist"] == []
    assert d["max_attempts"] == 3
    assert d["order_index"] == 0
    assert d["has_verification"] is True
    legacy_payload = d.copy()
    legacy_payload.pop("has_verification")
    legacy_rt = TaskCreated.model_validate(legacy_payload)
    assert legacy_rt.has_verification is True
    _assert_no_datetime_objects(d)


# ---------------------------------------------------------------------------
# TaskAttemptCreated
# ---------------------------------------------------------------------------


def test_task_attempt_created_round_trip() -> None:
    event = TaskAttemptCreated(
        run_id="run-1",
        event_type="task_attempt_created",
        timestamp=NOW,
        task_id="task-1",
        attempt_id="attempt-uuid-1",
        attempt_num=1,
        runner_type="cli_subprocess",
        agent_model="claude-3",
        new_task_status=TaskStatus.COMPLETED,
    )
    rt = _round_trip(event, TaskAttemptCreated)
    assert rt == event
    assert rt.attempt_id == "attempt-uuid-1"
    assert rt.attempt_num == 1
    assert rt.runner_type == "cli_subprocess"
    assert rt.agent_model == "claude-3"
    assert rt.new_task_status == TaskStatus.COMPLETED


def test_task_attempt_created_optional_fields() -> None:
    event = TaskAttemptCreated(
        run_id="r1",
        event_type="task_attempt_created",
        timestamp=NOW,
        task_id="t1",
        attempt_id="a1",
        attempt_num=0,
    )
    rt = _round_trip(event, TaskAttemptCreated)
    assert rt.runner_type is None
    assert rt.agent_model is None
    assert rt.new_task_status == TaskStatus.BUILDING
    legacy_payload = event.model_dump(mode="json")
    legacy_payload.pop("new_task_status")
    legacy_rt = TaskAttemptCreated.model_validate(legacy_payload)
    assert legacy_rt.new_task_status == TaskStatus.BUILDING


# ---------------------------------------------------------------------------
# AttemptUpdated
# ---------------------------------------------------------------------------


def test_attempt_updated_round_trip() -> None:
    event = AttemptUpdated(
        run_id="run-1",
        event_type="attempt_updated",
        timestamp=NOW,
        task_id="task-1",
        attempt_id="attempt-1",
        output_lines=["line 1", "line 2"],
        error=None,
        outcome="passed",
        builder_prompt="build it",
        verifier_prompt="verify it",
        completed_at="2025-01-15T10:30:00Z",
        paused_at="2025-01-15T10:31:00Z",
        clear_paused_state=True,
        auto_verify_results=[{"id": "output_exists", "passed": True, "output": "ok"}],
        action_log={"session_id": "session-1"},
        token_usage_by_model=[{"model": "gpt-test", "input_tokens": 3}],
        tokens_read=100,
        tokens_write=50,
        tokens_cache=10,
        duration_ms=1500,
        num_actions=5,
        new_task_status=TaskStatus.COMPLETED,
        apply_to_run_totals=False,
    )
    rt = _round_trip(event, AttemptUpdated)
    assert rt == event
    assert rt.output_lines == ["line 1", "line 2"]
    assert rt.outcome == "passed"
    assert rt.builder_prompt == "build it"
    assert rt.verifier_prompt == "verify it"
    assert rt.paused_at == "2025-01-15T10:31:00Z"
    assert rt.clear_paused_state is True
    assert rt.auto_verify_results == [{"id": "output_exists", "passed": True, "output": "ok"}]
    assert rt.action_log == {"session_id": "session-1"}
    assert rt.token_usage_by_model == [{"model": "gpt-test", "input_tokens": 3}]
    assert rt.tokens_read == 100
    assert rt.new_task_status == TaskStatus.COMPLETED
    assert rt.apply_to_run_totals is False


def test_attempt_updated_all_none() -> None:
    event = AttemptUpdated(
        run_id="r1",
        event_type="attempt_updated",
        timestamp=NOW,
        task_id="t1",
        attempt_id="a1",
    )
    rt = _round_trip(event, AttemptUpdated)
    assert rt.output_lines is None
    assert rt.error is None
    assert rt.outcome is None
    assert rt.paused_at is None
    assert rt.clear_paused_state is False
    assert rt.new_task_status is None
    assert rt.apply_to_run_totals is True


def test_attempt_updated_enum_serialization() -> None:
    event = AttemptUpdated(
        run_id="r1",
        event_type="attempt_updated",
        timestamp=NOW,
        task_id="t1",
        attempt_id="a1",
        new_task_status=TaskStatus.BUILDING,
    )
    d = event.model_dump(mode="json")
    assert d["new_task_status"] == "building"


# ---------------------------------------------------------------------------
# ParentOversightFactsUpdated
# ---------------------------------------------------------------------------


def test_parent_oversight_facts_updated_round_trip() -> None:
    event = ParentOversightFactsUpdated(
        run_id="run-1",
        event_type="parent_oversight_facts_updated",
        timestamp=NOW,
        patch={"key1": "value1", "key2": [1, 2, 3]},
    )
    rt = _round_trip(event, ParentOversightFactsUpdated)
    assert rt == event
    assert rt.patch == {"key1": "value1", "key2": [1, 2, 3]}


def test_parent_oversight_facts_updated_empty_patch() -> None:
    event = ParentOversightFactsUpdated(
        run_id="r1",
        event_type="parent_oversight_facts_updated",
        timestamp=NOW,
    )
    rt = _round_trip(event, ParentOversightFactsUpdated)
    assert rt.patch == {}


# ---------------------------------------------------------------------------
# FanOutChildrenCreated
# ---------------------------------------------------------------------------


def test_fan_out_children_created_round_trip() -> None:
    event = FanOutChildrenCreated(
        run_id="run-1",
        event_type="fan_out_children_created",
        timestamp=NOW,
        step_id="step-1",
        parent_task_id="task-parent",
        children=[{"task_id": "child-1", "has_verification": False}, {"task_id": "child-2"}],
        parent_new_status=TaskStatus.FAN_OUT_RUNNING,
    )
    rt = _round_trip(event, FanOutChildrenCreated)
    assert rt == event
    assert len(rt.children) == 2
    assert rt.children[0]["task_id"] == "child-1"
    assert rt.children[0]["has_verification"] is False
    assert rt.parent_new_status == TaskStatus.FAN_OUT_RUNNING


def test_fan_out_children_created_defaults() -> None:
    event = FanOutChildrenCreated(
        run_id="r1",
        event_type="fan_out_children_created",
        timestamp=NOW,
    )
    rt = _round_trip(event, FanOutChildrenCreated)
    assert rt.children == []
    assert rt.parent_new_status is None


def test_fan_out_children_created_enum_serialization() -> None:
    event = FanOutChildrenCreated(
        run_id="r1",
        event_type="fan_out_children_created",
        timestamp=NOW,
        parent_new_status=TaskStatus.FAN_OUT_RUNNING,
    )
    d = event.model_dump(mode="json")
    assert d["parent_new_status"] == "fan_out_running"


# ---------------------------------------------------------------------------
# FanOutChildrenReset
# ---------------------------------------------------------------------------


def test_fan_out_children_reset_round_trip() -> None:
    event = FanOutChildrenReset(
        run_id="run-1",
        event_type="fan_out_children_reset",
        timestamp=NOW,
        parent_task_id="task-parent",
    )
    rt = _round_trip(event, FanOutChildrenReset)
    assert rt == event
    assert rt.parent_task_id == "task-parent"


def test_fan_out_children_reset_default() -> None:
    event = FanOutChildrenReset(run_id="r1", event_type="fan_out_children_reset", timestamp=NOW)
    d = event.model_dump(mode="json")
    assert d["parent_task_id"] == ""
    _assert_no_datetime_objects(d)


# ---------------------------------------------------------------------------
# FanOutChildRetried
# ---------------------------------------------------------------------------


def test_fan_out_child_retried_round_trip() -> None:
    event = FanOutChildRetried(
        run_id="run-1",
        event_type="fan_out_child_retried",
        timestamp=NOW,
        child_task_id="task-child-3",
        step_order_index=2,
    )
    rt = _round_trip(event, FanOutChildRetried)
    assert rt == event
    assert rt.child_task_id == "task-child-3"
    assert rt.step_order_index == 2


def test_fan_out_child_retried_default() -> None:
    event = FanOutChildRetried(run_id="r1", event_type="fan_out_child_retried", timestamp=NOW)
    rt = _round_trip(event, FanOutChildRetried)
    assert rt.child_task_id == ""
    assert rt.step_order_index == 0


# ---------------------------------------------------------------------------
# StepIndexRewound
# ---------------------------------------------------------------------------


def test_step_index_rewound_round_trip() -> None:
    event = StepIndexRewound(
        run_id="run-1",
        event_type="step_index_rewound",
        timestamp=NOW,
        target_step_index=3,
    )
    rt = _round_trip(event, StepIndexRewound)
    assert rt == event
    assert rt.target_step_index == 3


def test_step_index_rewound_zero() -> None:
    event = StepIndexRewound(run_id="r1", event_type="step_index_rewound", timestamp=NOW)
    rt = _round_trip(event, StepIndexRewound)
    assert rt.target_step_index == 0
    d = event.model_dump(mode="json")
    _assert_no_datetime_objects(d)


# ---------------------------------------------------------------------------
# SignalEnqueued
# ---------------------------------------------------------------------------


def test_signal_enqueued_round_trip() -> None:
    event = SignalEnqueued(
        run_id="run-1",
        event_type="signal_enqueued",
        timestamp=NOW,
        signal_type="pause",
        payload={"reason": "user_requested"},
    )
    rt = _round_trip(event, SignalEnqueued)
    assert rt == event
    assert rt.signal_type == "pause"
    assert rt.payload == {"reason": "user_requested"}


def test_signal_enqueued_no_payload() -> None:
    event = SignalEnqueued(
        run_id="run-1",
        event_type="signal_enqueued",
        timestamp=NOW,
        signal_type="cancel",
    )
    rt = _round_trip(event, SignalEnqueued)
    assert rt.payload is None
    assert rt.signal_type == "cancel"


def test_signal_enqueued_serialization() -> None:
    event = SignalEnqueued(
        run_id="run-1",
        event_type="signal_enqueued",
        timestamp=NOW,
        signal_type="resume",
        payload={"extra": 42},
    )
    d = event.model_dump(mode="json")
    assert d["signal_type"] == "resume"
    assert d["payload"] == {"extra": 42}
    assert d["event_type"] == "signal_enqueued"
    _assert_no_datetime_objects(d)


# ---------------------------------------------------------------------------
# SignalProcessed
# ---------------------------------------------------------------------------


def test_signal_processed_round_trip() -> None:
    event = SignalProcessed(
        run_id="run-1",
        event_type="signal_processed",
        timestamp=NOW,
        enqueued_position=42,
    )
    rt = _round_trip(event, SignalProcessed)
    assert rt == event
    assert rt.enqueued_position == 42


def test_signal_processed_default_position() -> None:
    event = SignalProcessed(
        run_id="run-1",
        event_type="signal_processed",
        timestamp=NOW,
    )
    rt = _round_trip(event, SignalProcessed)
    assert rt.enqueued_position == 0


def test_signal_processed_serialization() -> None:
    event = SignalProcessed(
        run_id="run-1",
        event_type="signal_processed",
        timestamp=NOW,
        enqueued_position=99,
    )
    d = event.model_dump(mode="json")
    assert d["enqueued_position"] == 99
    assert d["event_type"] == "signal_processed"
    _assert_no_datetime_objects(d)
