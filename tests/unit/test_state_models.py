"""Tests for runtime state models."""

from orchestrator.config.enums import (
    AgentType,
    ChecklistStatus,
    Priority,
    RunStatus,
)
from orchestrator.state.models import (
    Attempt,
    AttemptMetrics,
    ChecklistItem,
    Run,
    TaskState,
)


def test_run_default_values() -> None:
    run = Run(repo_name="test-project")
    assert run.status == RunStatus.DRAFT
    assert run.id is not None
    assert len(run.id) == 36  # UUID format
    assert run.worktree_enabled is True


def test_run_with_values() -> None:
    run = Run(
        repo_name="test-project",
        source_branch="main",
        routine_id="planning",
        agent_type=AgentType.OPENHANDS_LOCAL,
        config={"feature": "auth"},
    )
    assert run.routine_id == "planning"
    assert run.agent_type == AgentType.OPENHANDS_LOCAL
    assert run.config["feature"] == "auth"


def test_task_state_checklist() -> None:
    task = TaskState(
        config_id="T-01",
        checklist=[
            ChecklistItem(
                req_id="R1",
                desc="Requirement 1",
                priority=Priority.CRITICAL,
            ),
            ChecklistItem(
                req_id="R2",
                desc="Requirement 2",
                priority=Priority.EXPECTED,
                status=ChecklistStatus.DONE,
            ),
        ],
    )
    assert len(task.checklist) == 2
    assert task.checklist[0].status == ChecklistStatus.OPEN
    assert task.checklist[1].status == ChecklistStatus.DONE


def test_attempt_metrics() -> None:
    attempt = Attempt(
        attempt_num=1,
        metrics=AttemptMetrics(
            tokens_read=1000,
            tokens_write=500,
            duration_ms=5000,
        ),
    )
    assert attempt.metrics.tokens_read == 1000
    assert attempt.metrics.duration_ms == 5000


def test_checklist_item_with_grade() -> None:
    item = ChecklistItem(
        req_id="R1",
        desc="Test",
        priority=Priority.CRITICAL,
        status=ChecklistStatus.DONE,
        grade="A",
        grade_reason="Well implemented",
    )
    assert item.grade == "A"
    assert item.grade_reason == "Well implemented"
