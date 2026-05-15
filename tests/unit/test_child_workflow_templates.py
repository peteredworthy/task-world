"""Unit tests for compiled child workflow templates."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from orchestrator.config import RoutineConfig
from orchestrator.workflow import ChildSliceSpec, compile_child_routine_from_spec


def test_compile_child_routine_from_spec_validates_generated_routine() -> None:
    spec = ChildSliceSpec(
        template_id="bug_fix_with_regression_test",
        slice_id="INV-001",
        goal="Fix the target regression and prove it with a focused test.",
        target_inventory_ids=["INV-001"],
        allowed_paths=["src/orchestrator/workflow"],
        expected_files_changed=["src/orchestrator/workflow/example.py"],
        verification_commands=["uv run pytest tests/unit/test_example.py -q"],
        evidence_expectations=["Evidence distinguishes verified_fix from needs_revision."],
        stop_conditions=["Stop if the regression cannot be reproduced."],
        real_execution_surface="unit test",
    )

    routine = compile_child_routine_from_spec(spec)
    validated = RoutineConfig.model_validate(routine)

    assert validated.id == "child-INV-001"
    task = validated.steps[0].tasks[0]
    assert task.artifacts[0].path == "docs/run-evidence/INV-001-evidence.json"
    assert task.auto_verify.items[0].id == "evidence_bundle_schema"
    assert "schema_version" in task.auto_verify.items[0].cmd
    assert task.auto_verify.items[1].cmd == "uv run pytest tests/unit/test_example.py -q"
    assert "scripts/run_child_evidence.py" in task.task_context
    assert "--command 'verification_1::uv run pytest tests/unit/test_example.py -q'" in (
        task.task_context
    )
    assert "target_bug_reproduced values are reproduced" in task.task_context
    assert "submit the child task" in task.task_context


def test_compile_child_routine_strips_optional_command_labels_for_auto_verify() -> None:
    routine = compile_child_routine_from_spec(
        ChildSliceSpec(
            template_id="investigation_only",
            slice_id="INV-002",
            goal="Run a named smoke command.",
            verification_commands=["python_version::python -V"],
            real_execution_surface="python version command",
        )
    )
    validated = RoutineConfig.model_validate(routine)
    task = validated.steps[0].tasks[0]

    assert task.auto_verify.items[1].cmd == "python -V"
    assert "--command 'python_version::python -V'" in task.task_context
    assert "verification_1::python_version::python -V" not in task.task_context


def test_compile_child_routine_rejects_unsafe_slice_path() -> None:
    with pytest.raises(ValidationError, match="path must not traverse"):
        ChildSliceSpec(
            template_id="investigation_only",
            slice_id="INV-002",
            goal="Investigate the target behavior.",
            allowed_paths=["../outside"],
        )


def test_compile_child_routine_preserves_explicit_routine_id() -> None:
    routine = compile_child_routine_from_spec(
        {
            "template_id": "test_coverage_gap",
            "slice_id": "coverage-1",
            "routine_id": "child-coverage-custom",
            "goal": "Add missing coverage for the parser.",
        }
    )

    assert routine["id"] == "child-coverage-custom"
    steps = cast(list[dict[str, Any]], routine["steps"])
    task = cast(dict[str, Any], steps[0]["tasks"][0])
    auto_verify = cast(dict[str, Any], task["auto_verify"])
    items = cast(list[dict[str, str]], auto_verify["items"])
    assert "assert b['routine_id']=='child-coverage-custom'" in items[0]["cmd"]


def test_planning_template_creates_cut_down_idea_to_plan_workflow() -> None:
    routine = compile_child_routine_from_spec(
        ChildSliceSpec(
            template_id="planning_to_implementation_brief",
            slice_id="INV-009-plan",
            goal="Split the broad runner-defaults item into one implementation child.",
            target_inventory_ids=["INV-009"],
            allowed_paths=["src/orchestrator/runners", "tests/unit"],
            verification_commands=["uv run pytest tests/unit/test_child_workflow_templates.py -q"],
            real_execution_surface="runner defaults unit tests",
        )
    )
    validated = RoutineConfig.model_validate(routine)

    assert [step.id for step in validated.steps] == ["CH-01", "CH-02"]
    brief_task = validated.steps[0].tasks[0]
    evidence_task = validated.steps[1].tasks[0]
    assert brief_task.artifacts[0].path == (
        "docs/run-evidence/INV-009-plan-implementation-brief.md"
    )
    assert "Suggested Child Template" in brief_task.task_context
    assert "Do not edit production code" in brief_task.task_context
    assert "behavior_already_correct" in evidence_task.task_context
    assert evidence_task.auto_verify.items[0].id == "implementation_brief_exists"
    assert evidence_task.auto_verify.items[1].id == "evidence_bundle_schema"


def test_partial_progress_recovery_template_packages_dirty_turn_limited_work() -> None:
    routine = compile_child_routine_from_spec(
        ChildSliceSpec(
            template_id="partial_progress_recovery",
            slice_id="INV-009-recovery",
            goal="Package turn-limited child work for parent review.",
            expected_files_changed=["src/orchestrator/runners/agent_detector.py"],
            verification_commands=["uv run pytest tests/unit/test_cli_agent.py -q"],
        )
    )
    validated = RoutineConfig.model_validate(routine)

    assert [step.id for step in validated.steps] == ["CH-01", "CH-02"]
    summary_task = validated.steps[0].tasks[0]
    evidence_task = validated.steps[1].tasks[0]
    assert summary_task.artifacts[0].path == (
        "docs/run-evidence/INV-009-recovery-recovery-summary.md"
    )
    assert "Observed Run State" in summary_task.task_context
    assert "Do not continue broad implementation" in summary_task.task_context
    assert "`outcome` to `partial_progress`" in evidence_task.task_context
    assert evidence_task.auto_verify.items[0].id == "recovery_summary_exists"
    assert evidence_task.auto_verify.items[1].id == "evidence_bundle_schema"
