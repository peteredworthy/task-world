"""Tests for the idea-to-plan-scoped production routine."""

from pathlib import Path

from orchestrator.config import GateType, Priority, StepType, load_routine_from_path

ROUTINE_PATH = (
    Path(__file__).parent.parent.parent / "routines" / "idea-to-plan-scoped" / "routine.yaml"
)


def test_idea_to_plan_routine_loads():
    """Verify the idea-to-plan-scoped routine loads and has expected structure."""
    routine = load_routine_from_path(ROUTINE_PATH)

    assert routine.id == "idea-to-plan-scoped"
    assert routine.name == "Idea to Implementation Plan (Scoped Context)"
    assert routine.description is not None

    # Inputs
    assert len(routine.inputs) == 3
    input_names = {inp.name for inp in routine.inputs}
    assert input_names == {"feature", "idea", "codebase_context"}

    feature_input = next(inp for inp in routine.inputs if inp.name == "feature")
    assert feature_input.required is True

    idea_input = next(inp for inp in routine.inputs if inp.name == "idea")
    assert idea_input.required is True

    codebase_input = next(inp for inp in routine.inputs if inp.name == "codebase_context")
    assert codebase_input.required is False

    # 8 steps
    assert len(routine.steps) == 8
    step_ids = [step.id for step in routine.steps]
    assert step_ids == ["S-01", "S-02", "S-03", "S-04", "S-05", "S-06", "S-07", "S-08"]


def test_idea_to_plan_has_human_gates():
    """Verify human approval gates are configured correctly."""
    routine = load_routine_from_path(ROUTINE_PATH)

    # S-07: Final Plan Review
    s07 = next(step for step in routine.steps if step.id == "S-07")
    assert s07.gate is not None
    assert s07.gate.type == GateType.HUMAN_APPROVAL
    assert s07.gate.require_comment is False
    assert s07.gate.approval_prompt is not None
    assert "plan is complete" in s07.gate.approval_prompt

    # S-06 also has a human approval gate (review before final verification)
    s06 = next(step for step in routine.steps if step.id == "S-06")
    assert s06.gate is not None
    assert s06.gate.type == GateType.HUMAN_APPROVAL


def test_idea_to_plan_has_backward_transitions():
    """Verify backward transitions are configured with conditions."""
    routine = load_routine_from_path(ROUTINE_PATH)

    # S-03: Step Planning - should have backward transition
    s03 = next(step for step in routine.steps if step.id == "S-03")
    assert s03.transitions is not None
    assert s03.transitions.on_complete == "S-04"
    assert len(s03.transitions.on_condition) == 1
    assert s03.transitions.on_condition[0].condition == "has_unresolved_conflicts"
    assert s03.transitions.on_condition[0].target == "S-02"

    # S-04: Task Breakdown - should also have backward transition
    s04 = next(step for step in routine.steps if step.id == "S-04")
    assert s04.transitions is not None
    assert len(s04.transitions.on_condition) == 1
    assert s04.transitions.on_condition[0].condition == "has_unresolved_conflicts"
    assert s04.transitions.on_condition[0].target == "S-02"

    # S-06: Final Check - backward transition on conflicts
    s06 = next(step for step in routine.steps if step.id == "S-06")
    assert s06.transitions is not None
    assert len(s06.transitions.on_condition) == 1
    assert s06.transitions.on_condition[0].target == "S-02"


def test_idea_to_plan_has_artifact_tracking():
    """Verify artifact tracking is configured."""
    routine = load_routine_from_path(ROUTINE_PATH)

    # S-01: Initial Plan - should track artifacts
    s01 = next(step for step in routine.steps if step.id == "S-01")
    task = s01.tasks[0]
    assert len(task.artifacts) == 3

    artifact_paths = {art.path for art in task.artifacts}
    assert "docs/{{feature}}/intent.md" in artifact_paths
    assert "docs/{{feature}}/plan.md" in artifact_paths
    assert "docs/{{feature}}/architecture.md" in artifact_paths


def test_idea_to_plan_has_fan_out_dry_run_step():
    """Verify S-05 dry run uses fan-out (not StepType.DRY_RUN)."""
    routine = load_routine_from_path(ROUTINE_PATH)

    # S-05: Dry Run & Failure Mode Analysis — uses fan-out tasks, not StepType.DRY_RUN
    s05 = next(step for step in routine.steps if step.id == "S-05")
    assert s05.type != StepType.DRY_RUN
    assert s05.title == "Dry Run & Failure Mode Analysis"

    # T-01 is a fan-out task that simulates execution per step
    t01 = next(t for t in s05.tasks if t.id == "T-01")
    assert t01.fan_out is not None
    assert "dry-run" in t01.fan_out.output_pattern

    # T-02 merges dry-run notes
    t02 = next(t for t in s05.tasks if t.id == "T-02")
    assert t02 is not None

    # T-03 applies gaps to step files
    t03 = next(t for t in s05.tasks if t.id == "T-03")
    assert t03 is not None


def test_idea_to_plan_has_context_injection():
    """Verify multi-artifact context injection is configured."""
    routine = load_routine_from_path(ROUTINE_PATH)

    # S-02: Requirements Gathering - uses context_from
    s02 = next(step for step in routine.steps if step.id == "S-02")
    task = s02.tasks[0]
    assert len(task.context_from) == 3
    context_names = {ctx.as_name for ctx in task.context_from}
    assert context_names == {"context.intent", "context.plan", "context.architecture"}

    # intent and plan are required, architecture is optional
    plan_ctx = next(ctx for ctx in task.context_from if ctx.as_name == "context.plan")
    assert plan_ctx.required is True
    arch_ctx = next(ctx for ctx in task.context_from if ctx.as_name == "context.architecture")
    assert arch_ctx.required is False

    # S-06: Final Check - uses context from 5 artifacts including dry run and clarifications
    s06 = next(step for step in routine.steps if step.id == "S-06")
    task = s06.tasks[0]
    assert len(task.context_from) == 5
    dry_run_ctx = next((ctx for ctx in task.context_from if ctx.as_name == "context.dry_run"), None)
    assert dry_run_ctx is not None
    assert dry_run_ctx.required is False


def test_idea_to_plan_has_auto_verify():
    """Verify auto-verification is configured for file existence checks."""
    routine = load_routine_from_path(ROUTINE_PATH)

    # S-01: Initial Plan - auto-verify files exist and intent items numbered
    s01 = next(step for step in routine.steps if step.id == "S-01")
    task = s01.tasks[0]
    av_ids = {item.id for item in task.auto_verify.items}
    assert "files_exist" in av_ids
    assert "intent_items_numbered" in av_ids

    # S-03: Step Planning T-01 - auto-verify step plans exist
    s03 = next(step for step in routine.steps if step.id == "S-03")
    task = s03.tasks[0]
    av_ids = {item.id for item in task.auto_verify.items}
    assert "step_plans_exist" in av_ids
    # context_from sources also get auto_verify items
    context_from_items = [i for i in task.auto_verify.items if i.id.startswith("context_from_")]
    assert len(context_from_items) == len([s for s in task.context_from if s.required])

    # S-08: Execution Ready - auto-verify summary exists
    s08 = next(step for step in routine.steps if step.id == "S-08")
    task = s08.tasks[0]
    av_ids = {item.id for item in task.auto_verify.items}
    assert "summary_exists" in av_ids

    # S-08/T-02: Routine YAML validation
    task2 = s08.tasks[1]
    av_ids = {item.id for item in task2.auto_verify.items}
    assert "routine_exists" in av_ids
    assert "routine_yaml_valid" in av_ids


def test_idea_to_plan_has_llm_verification():
    """Verify LLM verification is configured where appropriate."""
    routine = load_routine_from_path(ROUTINE_PATH)

    # S-06: Final Check - should have verifier with 6 rubric items (R1-R6)
    s06 = next(step for step in routine.steps if step.id == "S-06")
    task = s06.tasks[0]
    assert len(task.verifier.rubric) == 6

    rubric_ids = {item.id for item in task.verifier.rubric}
    assert rubric_ids == {"R1", "R2", "R3", "R4", "R5", "R6"}

    # Check submission template
    assert task.verifier.submission_template.grade_scale == ["A", "B", "C", "D", "F"]
    assert task.verifier.submission_template.require_reason_if_below == "A"
    assert task.verifier.submission_template.require_remediation_if_below == "B"


def test_idea_to_plan_requirements_have_priorities():
    """Verify requirements have appropriate priorities."""
    routine = load_routine_from_path(ROUTINE_PATH)

    # S-01: Initial Plan — 4 requirements: R1 (critical), R2 (critical), R3 (expected), R4 (critical)
    s01 = next(step for step in routine.steps if step.id == "S-01")
    task = s01.tasks[0]
    assert len(task.requirements) == 4

    critical_reqs = [req for req in task.requirements if req.priority == Priority.CRITICAL]
    assert len(critical_reqs) == 3

    # Architecture is expected priority
    arch_req = next(req for req in task.requirements if "architecture" in req.desc.lower())
    assert arch_req.priority == Priority.EXPECTED


def test_idea_to_plan_retry_config():
    """Verify retry configuration is set appropriately."""
    routine = load_routine_from_path(ROUTINE_PATH)

    s01 = next(step for step in routine.steps if step.id == "S-01")
    assert s01.tasks[0].retry.max_attempts == 2

    s06 = next(step for step in routine.steps if step.id == "S-06")
    assert s06.tasks[0].retry.max_attempts == 2


def test_idea_to_plan_step_progression():
    """Verify the logical flow of steps."""
    routine = load_routine_from_path(ROUTINE_PATH)

    step_titles = [step.title for step in routine.steps]
    expected_titles = [
        "Initial Plan",
        "Requirements Gathering",
        "Step Planning",
        "Task Breakdown",
        "Dry Run & Failure Mode Analysis",
        "Final Check",
        "Final Plan Review",
        "Execution Ready",
    ]
    assert step_titles == expected_titles

    # Verify each non-gate step has step_context
    for step in routine.steps:
        if step.gate is None:
            assert step.step_context is not None, f"Step {step.id} missing step_context"


def test_idea_to_plan_context_from_generates_auto_verify():
    """Verify that required context_from sources get auto_verify items."""
    routine = load_routine_from_path(ROUTINE_PATH)

    for step in routine.steps:
        for task in step.tasks:
            required_sources = [s for s in task.context_from if s.required]
            if not required_sources:
                continue
            av_ids = {item.id for item in task.auto_verify.items}
            for source in required_sources:
                expected_id = f"context_from_exists_{source.as_name or source.artifact}"
                assert expected_id in av_ids, (
                    f"{step.id}/{task.id}: missing auto_verify for required "
                    f"context_from source '{source.as_name or source.artifact}'"
                )
