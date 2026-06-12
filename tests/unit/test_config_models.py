"""Tests for configuration models."""

import pydantic
import pytest
import yaml

from orchestrator.config import Complexity
from orchestrator.config import Priority
from orchestrator.config.models import (
    GateConfig,
    RequirementConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
)


def test_requirement_defaults() -> None:
    req = RequirementConfig(id="R1", desc="Test requirement")
    assert req.must is True
    assert req.priority == Priority.CRITICAL


def test_task_with_requirements() -> None:
    task = TaskConfig(
        id="T1",
        title="Test Task",
        task_context="Do something",
        requirements=[
            RequirementConfig(id="R1", desc="Req 1"),
            RequirementConfig(id="R2", desc="Req 2", priority=Priority.NICE),
        ],
    )
    assert len(task.requirements) == 2
    assert task.requirements[1].priority == Priority.NICE


def test_routine_complete() -> None:
    routine = RoutineConfig(
        id="test-routine",
        name="Test Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Context",
                    ),
                ],
            )
        ],
    )
    assert routine.id == "test-routine"
    assert len(routine.steps) == 1


def test_model_overrides() -> None:
    task = TaskConfig(
        id="T1",
        title="Task",
        task_context="Default context",
        model_overrides={
            "claude-sonnet": {"task_context": "Claude-specific context"},
        },
    )
    assert task.model_overrides is not None
    assert task.model_overrides["claude-sonnet"]["task_context"] == "Claude-specific context"


def test_reject_ref_in_steps() -> None:
    """CRITICAL: ref/use inheritance must be rejected."""
    with pytest.raises(ValueError, match="ref.*not supported|not supported.*ref"):
        RoutineConfig(
            id="test",
            name="Test",
            steps=[{"ref": "some-step"}],  # type: ignore[list-item]
        )


def test_reject_use_in_task() -> None:
    """CRITICAL: ref/use inheritance must be rejected."""
    with pytest.raises(ValueError, match="use.*not supported|not supported.*use"):
        StepConfig(
            id="S1",
            title="Step",
            tasks=[{"use": "some-task"}],  # type: ignore[list-item]
        )


def test_step_with_multiple_tasks() -> None:
    step = StepConfig(
        id="S1",
        title="Step 1",
        tasks=[
            TaskConfig(id="T1", title="Task 1", task_context="Context 1"),
            TaskConfig(id="T2", title="Task 2", task_context="Context 2"),
        ],
    )
    assert len(step.tasks) == 2


def test_step_requires_at_least_one_task() -> None:
    with pytest.raises(ValueError):
        StepConfig(
            id="S1",
            title="Step",
            tasks=[],
        )


# --- Singular task: key normalization (Gap A3) ---


def test_singular_task_dict_parsed_to_tasks_list() -> None:
    """Singular 'task:' (dict value) is normalized to 'tasks: [TaskConfig]'."""
    step = StepConfig(
        id="S1",
        title="Step 1",
        task=TaskConfig(  # type: ignore[call-arg]
            id="T1",
            title="Task 1",
            task_context="Do something",
        ),
    )
    assert len(step.tasks) == 1
    assert step.tasks[0].id == "T1"
    assert step.tasks[0].title == "Task 1"


def test_singular_task_raw_dict_parsed_to_tasks_list() -> None:
    """Singular 'task:' as a raw dict (pre-validation) is normalized."""
    step = StepConfig.model_validate(
        {
            "id": "S1",
            "title": "Step 1",
            "task": {
                "id": "T1",
                "title": "Task 1",
                "task_context": "Do something",
            },
        }
    )
    assert len(step.tasks) == 1
    assert step.tasks[0].id == "T1"


def test_plural_tasks_still_works() -> None:
    """Plural 'tasks:' list continues to work as before."""
    step = StepConfig(
        id="S1",
        title="Step 1",
        tasks=[
            TaskConfig(id="T1", title="Task 1", task_context="Context 1"),
            TaskConfig(id="T2", title="Task 2", task_context="Context 2"),
        ],
    )
    assert len(step.tasks) == 2
    assert step.tasks[0].id == "T1"
    assert step.tasks[1].id == "T2"


def test_both_task_and_tasks_raises_error() -> None:
    """Specifying both 'task:' and 'tasks:' raises a validation error."""
    with pytest.raises(ValueError, match="Cannot specify both 'task' and 'tasks'"):
        StepConfig.model_validate(
            {
                "id": "S1",
                "title": "Step 1",
                "task": {
                    "id": "T1",
                    "title": "Task 1",
                    "task_context": "Context",
                },
                "tasks": [
                    {
                        "id": "T2",
                        "title": "Task 2",
                        "task_context": "Context",
                    }
                ],
            }
        )


def test_singular_task_via_yaml_loading() -> None:
    """Singular 'task:' works end-to-end through YAML parsing."""
    yaml_content = """
id: test-routine
name: Test Routine
steps:
  - id: S-01
    title: Step 1
    task:
      id: T-01
      title: Task 1
      task_context: Do the thing
"""
    data = yaml.safe_load(yaml_content)
    routine = RoutineConfig.model_validate(data)
    assert len(routine.steps) == 1
    assert len(routine.steps[0].tasks) == 1
    assert routine.steps[0].tasks[0].id == "T-01"
    assert routine.steps[0].tasks[0].title == "Task 1"
    assert routine.steps[0].tasks[0].task_context == "Do the thing"


def test_plural_tasks_via_yaml_loading() -> None:
    """Plural 'tasks:' works end-to-end through YAML parsing."""
    yaml_content = """
id: test-routine
name: Test Routine
steps:
  - id: S-01
    title: Step 1
    tasks:
      - id: T-01
        title: Task 1
        task_context: First thing
      - id: T-02
        title: Task 2
        task_context: Second thing
"""
    data = yaml.safe_load(yaml_content)
    routine = RoutineConfig.model_validate(data)
    assert len(routine.steps[0].tasks) == 2
    assert routine.steps[0].tasks[0].id == "T-01"
    assert routine.steps[0].tasks[1].id == "T-02"


def test_both_task_and_tasks_via_yaml_raises_error() -> None:
    """Both 'task:' and 'tasks:' in YAML raises validation error."""
    yaml_content = """
id: test-routine
name: Test Routine
steps:
  - id: S-01
    title: Step 1
    task:
      id: T-01
      title: Task 1
      task_context: Context
    tasks:
      - id: T-02
        title: Task 2
        task_context: Context
"""
    data = yaml.safe_load(yaml_content)
    with pytest.raises(ValueError, match="Cannot specify both 'task' and 'tasks'"):
        RoutineConfig.model_validate(data)


# --- Gap coverage: GateConfig.summary_artifact ---


def test_gate_config_with_summary_artifact() -> None:
    """Test GateConfig with summary_artifact field set."""
    from orchestrator.config import GateType

    gate = GateConfig(
        type=GateType.HUMAN_APPROVAL,
        approval_prompt="Please review the changes",
        summary_artifact="docs/summary.md",
    )
    assert gate.type == GateType.HUMAN_APPROVAL
    assert gate.summary_artifact == "docs/summary.md"
    assert gate.approval_prompt == "Please review the changes"


def test_gate_config_without_summary_artifact() -> None:
    """Test GateConfig with summary_artifact as None (default)."""
    from orchestrator.config import GateType

    gate = GateConfig(
        type=GateType.HUMAN_APPROVAL,
        approval_prompt="Please review",
    )
    assert gate.summary_artifact is None


def test_gate_config_in_step_with_summary_artifact() -> None:
    """Test StepConfig with gate containing summary_artifact."""
    from orchestrator.config import GateType

    step = StepConfig(
        id="S1",
        title="Step with gate",
        gate=GateConfig(
            type=GateType.HUMAN_APPROVAL,
            approval_prompt="Review required",
            summary_artifact="docs/step1-summary.md",
        ),
        tasks=[
            TaskConfig(id="T1", title="Task 1", task_context="Context"),
        ],
    )
    assert step.gate is not None
    assert step.gate.summary_artifact == "docs/step1-summary.md"


# --- Gap coverage: RoutineConfig.clarifications ---


def test_routine_config_with_clarifications() -> None:
    """Test RoutineConfig with clarifications field set."""
    from orchestrator.config.models import ClarificationsConfig

    routine = RoutineConfig(
        id="test-routine",
        name="Test Routine",
        clarifications=ClarificationsConfig(artifact_path="docs/my-clarifications.md"),
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Do something",
                    ),
                ],
            )
        ],
    )
    assert routine.clarifications is not None
    assert routine.clarifications.artifact_path == "docs/my-clarifications.md"


def test_routine_config_without_clarifications() -> None:
    """Test RoutineConfig with clarifications as None (default)."""
    routine = RoutineConfig(
        id="test-routine",
        name="Test Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Do something",
                    ),
                ],
            )
        ],
    )
    assert routine.clarifications is None


def test_routine_with_clarifications_via_yaml() -> None:
    """Test RoutineConfig with clarifications loaded from YAML."""
    yaml_content = """
id: test-routine
name: Test Routine
clarifications:
  artifact_path: docs/clarifications.md
steps:
  - id: S-01
    title: Step 1
    task:
      id: T-01
      title: Task 1
      task_context: Do something
"""
    data = yaml.safe_load(yaml_content)
    routine = RoutineConfig.model_validate(data)
    assert routine.clarifications is not None
    assert routine.clarifications.artifact_path == "docs/clarifications.md"


def test_clarifications_config_default_artifact_path() -> None:
    """Test ClarificationsConfig with default artifact path."""
    from orchestrator.config.models import ClarificationsConfig

    config = ClarificationsConfig()
    assert config.artifact_path == "docs/clarifications.md"


# --- Verification requirement tests ---


def _make_routine(
    *,
    strict_validation: bool = False,
    auto_verify_items: list[dict] | None = None,
    rubric_items: list[dict] | None = None,
) -> dict:
    """Build a minimal RoutineConfig dict for testing verification scenarios."""
    task: dict = {
        "id": "T-01",
        "title": "Task 1",
        "task_context": "Do something",
    }
    if auto_verify_items:
        task["auto_verify"] = {"items": auto_verify_items}
    if rubric_items:
        task["verifier"] = {"rubric": rubric_items}
    return {
        "id": "test-routine",
        "name": "Test Routine",
        "strict_validation": strict_validation,
        "steps": [
            {
                "id": "S-01",
                "title": "Step 1",
                "tasks": [task],
            }
        ],
    }


def test_task_no_verification_logs_debug_diagnostic(caplog: pytest.LogCaptureFixture) -> None:
    """TaskConfig with no auto_verify and no verifier logs a debug diagnostic."""
    import logging

    with caplog.at_level(logging.DEBUG, logger="orchestrator.config.models"):
        TaskConfig(id="T1", title="Task 1", task_context="ctx")

    assert any("no auto_verify" in record.message for record in caplog.records)


def test_routine_strict_no_verification_raises() -> None:
    """RoutineConfig with strict_validation=True and unverified task raises ValueError."""
    with pytest.raises(ValueError, match="strict_validation=True"):
        RoutineConfig.model_validate(_make_routine(strict_validation=True))


def test_routine_strict_with_auto_verify_passes() -> None:
    """RoutineConfig with strict_validation=True and auto_verify items passes."""
    routine = RoutineConfig.model_validate(
        _make_routine(
            strict_validation=True,
            auto_verify_items=[{"id": "AV1", "cmd": "echo ok"}],
        )
    )
    assert routine.strict_validation is True
    assert bool(routine.steps[0].tasks[0].auto_verify.items)


def test_routine_strict_with_rubric_passes() -> None:
    """RoutineConfig with strict_validation=True and rubric items passes."""
    routine = RoutineConfig.model_validate(
        _make_routine(
            strict_validation=True,
            rubric_items=[{"id": "RQ1", "text": "Does it work?"}],
        )
    )
    assert bool(routine.steps[0].tasks[0].verifier.rubric)


def test_existing_routines_without_strict_load() -> None:
    """Routines without strict_validation (default False) load even without verification."""
    data = yaml.safe_load("""
id: legacy-routine
name: Legacy Routine
steps:
  - id: S-01
    title: Step 1
    task:
      id: T-01
      title: Old Task
      task_context: Does not have verification
""")
    routine = RoutineConfig.model_validate(data)
    assert routine.strict_validation is False
    assert routine.id == "legacy-routine"


def test_auto_grade_blocked_when_no_verification() -> None:
    """transition_after_verification blocks auto-grade when task has no verification."""
    from datetime import datetime, timezone

    from orchestrator.config import ChecklistStatus, Priority, TaskStatus
    from orchestrator.state.models import ChecklistItem, TaskState
    from orchestrator.workflow import transition_after_verification

    task = TaskState(
        id="task-1",
        config_id="T-01",
        status=TaskStatus.VERIFYING,
        max_attempts=3,
        has_verification=False,
        checklist=[
            ChecklistItem(
                req_id="R1",
                desc="Req 1",
                priority=Priority.CRITICAL,
                status=ChecklistStatus.DONE,
            )
        ],
    )
    now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    result = transition_after_verification(task, now)
    assert result.success is False
    assert "no verification configured" in result.error


# --- Complexity field tests ---


def test_task_config_complexity_default() -> None:
    task = TaskConfig(id="T1", title="Test", task_context="ctx")
    assert task.complexity == Complexity.STANDARD
    assert task.complexity.value == "standard"


def test_task_config_complexity_simple() -> None:
    task = TaskConfig(id="T1", title="Test", task_context="ctx", complexity="simple")
    assert task.complexity == Complexity.SIMPLE
    assert task.complexity.value == "simple"


def test_task_config_complexity_standard_explicit() -> None:
    task = TaskConfig(id="T1", title="Test", task_context="ctx", complexity="standard")
    assert task.complexity == Complexity.STANDARD


def test_task_config_complexity_invalid() -> None:
    with pytest.raises(pydantic.ValidationError):
        TaskConfig(id="T1", title="Test", task_context="ctx", complexity="complex")


# --- A3: Per-requirement grading enforcement ---


def test_rubric_auto_generated_from_requirements() -> None:
    """Empty rubric + requirements -> rubric auto-populated with one item per requirement."""
    task = TaskConfig(
        id="T1",
        title="Task 1",
        task_context="ctx",
        requirements=[
            RequirementConfig(id="R1", desc="First requirement"),
            RequirementConfig(id="R2", desc="Second requirement"),
        ],
    )
    # Rubric should be auto-generated (one item per requirement).
    assert len(task.verifier.rubric) == 2
    assert task.verifier.rubric[0].id == "R1"
    assert task.verifier.rubric[0].text == "Does the implementation satisfy: First requirement?"
    assert task.verifier.rubric[1].id == "R2"
    assert task.verifier.rubric[1].text == "Does the implementation satisfy: Second requirement?"


def test_rubric_mismatch_logs_debug_diagnostic(caplog: pytest.LogCaptureFixture) -> None:
    """Rubric IDs that don't match any requirement ID produce a debug diagnostic."""
    import logging

    with caplog.at_level(logging.DEBUG, logger="orchestrator.config.models"):
        TaskConfig(
            id="T1",
            title="Task 1",
            task_context="ctx",
            requirements=[
                RequirementConfig(id="R1", desc="First requirement"),
                RequirementConfig(id="R2", desc="Second requirement"),
            ],
            verifier={  # type: ignore[arg-type]
                "rubric": [
                    {"id": "R1", "text": "Check R1"},
                    {"id": "R1-R3", "text": "Composite check covering R1 through R3"},
                ]
            },
        )

    debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("R1-R3" in msg for msg in debug_messages), (
        f"Expected debug diagnostic about 'R1-R3', got: {debug_messages}"
    )
