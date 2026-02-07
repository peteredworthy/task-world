"""Tests for the idea_to_plan routine template."""

from pathlib import Path

from orchestrator.config.enums import GateType, Priority, StepType
from orchestrator.routines.loader import load_routine_from_path


def test_idea_to_plan_routine_loads():
    """Verify the idea_to_plan routine loads and has expected structure."""
    routine_path = (
        Path(__file__).parent.parent.parent / "examples" / "routines" / "idea_to_plan.yaml"
    )

    # Load the routine
    routine = load_routine_from_path(routine_path)

    # Basic metadata
    assert routine.id == "idea-to-plan"
    assert routine.name == "Idea to Implementation Plan"
    assert routine.description is not None

    # Inputs
    assert len(routine.inputs) == 3
    input_names = {inp.name for inp in routine.inputs}
    assert input_names == {"feature", "idea", "codebase_context"}

    # Required inputs
    feature_input = next(inp for inp in routine.inputs if inp.name == "feature")
    assert feature_input.required is True

    idea_input = next(inp for inp in routine.inputs if inp.name == "idea")
    assert idea_input.required is True

    codebase_input = next(inp for inp in routine.inputs if inp.name == "codebase_context")
    assert codebase_input.required is False

    # Steps
    assert len(routine.steps) == 9
    step_ids = [step.id for step in routine.steps]
    assert step_ids == ["S-01", "S-02", "S-03", "S-04", "S-05", "S-06", "S-07", "S-08", "S-09"]


def test_idea_to_plan_has_human_gates():
    """Verify human approval gates are configured correctly."""
    routine_path = (
        Path(__file__).parent.parent.parent / "examples" / "routines" / "idea_to_plan.yaml"
    )
    routine = load_routine_from_path(routine_path)

    # S-02: Human Review
    s02 = next(step for step in routine.steps if step.id == "S-02")
    assert s02.gate is not None
    assert s02.gate.type == GateType.HUMAN_APPROVAL
    assert s02.gate.require_comment is True
    assert s02.gate.approval_prompt is not None
    assert "Review the generated plan artifacts" in s02.gate.approval_prompt

    # S-08: Final Plan Review
    s08 = next(step for step in routine.steps if step.id == "S-08")
    assert s08.gate is not None
    assert s08.gate.type == GateType.HUMAN_APPROVAL
    assert s08.gate.require_comment is False
    assert s08.gate.approval_prompt is not None
    assert "plan is complete" in s08.gate.approval_prompt


def test_idea_to_plan_has_backward_transitions():
    """Verify backward transitions are configured with conditions."""
    routine_path = (
        Path(__file__).parent.parent.parent / "examples" / "routines" / "idea_to_plan.yaml"
    )
    routine = load_routine_from_path(routine_path)

    # S-03: Plan Refinement - should have backward transitions
    s03 = next(step for step in routine.steps if step.id == "S-03")
    assert s03.transitions is not None
    assert s03.transitions.on_complete == "S-04"
    assert len(s03.transitions.on_condition) == 2

    # Check conditions
    conditions = {cond.condition for cond in s03.transitions.on_condition}
    assert "has_unresolved_conflicts" in conditions
    assert "has_open_questions" in conditions

    # All backward transitions should target S-02 (Human Review)
    for cond in s03.transitions.on_condition:
        assert cond.target == "S-02"
        assert cond.max_iterations == 3

    # S-04: Step Planning - should also have backward transition
    s04 = next(step for step in routine.steps if step.id == "S-04")
    assert s04.transitions is not None
    assert len(s04.transitions.on_condition) == 1
    assert s04.transitions.on_condition[0].condition == "has_unresolved_conflicts"
    assert s04.transitions.on_condition[0].target == "S-02"


def test_idea_to_plan_has_artifact_tracking():
    """Verify artifact tracking is configured."""
    routine_path = (
        Path(__file__).parent.parent.parent / "examples" / "routines" / "idea_to_plan.yaml"
    )
    routine = load_routine_from_path(routine_path)

    # S-01: Initial Plan - should track artifacts
    s01 = next(step for step in routine.steps if step.id == "S-01")
    task = s01.tasks[0]
    assert len(task.artifacts) == 4

    # Check specific artifacts
    artifact_paths = {art.path for art in task.artifacts}
    assert "docs/{{feature}}/intent.md" in artifact_paths
    assert "docs/{{feature}}/plan.md" in artifact_paths
    assert "docs/{{feature}}/design-questions.md" in artifact_paths

    # design-questions.md should track resolution
    design_questions = next(art for art in task.artifacts if "design-questions" in art.path)
    assert design_questions.track_resolution is True

    # S-03: Plan Refinement - CONFLICTS.md tracking
    s03 = next(step for step in routine.steps if step.id == "S-03")
    conflicts_artifact = next(
        (art for art in s03.tasks[0].artifacts if "CONFLICTS" in art.path), None
    )
    assert conflicts_artifact is not None
    assert conflicts_artifact.track_resolution is True
    assert conflicts_artifact.required is False


def test_idea_to_plan_has_dry_run_step():
    """Verify dry-run step is configured correctly."""
    routine_path = (
        Path(__file__).parent.parent.parent / "examples" / "routines" / "idea_to_plan.yaml"
    )
    routine = load_routine_from_path(routine_path)

    # S-06: Dry Run
    s06 = next(step for step in routine.steps if step.id == "S-06")
    assert s06.type == StepType.DRY_RUN
    assert s06.dry_run is not None
    assert s06.dry_run.target_steps == ["S-09"]
    assert s06.dry_run.context_limit == 4000
    assert "dry-run-notes.md" in s06.dry_run.report_path


def test_idea_to_plan_has_context_injection():
    """Verify multi-artifact context injection is configured."""
    routine_path = (
        Path(__file__).parent.parent.parent / "examples" / "routines" / "idea_to_plan.yaml"
    )
    routine = load_routine_from_path(routine_path)

    # S-03: Plan Refinement - uses context_from
    s03 = next(step for step in routine.steps if step.id == "S-03")
    task = s03.tasks[0]
    assert len(task.context_from) == 3

    # Check context sources
    context_names = {ctx.as_name for ctx in task.context_from}
    assert context_names == {"plan", "questions", "architecture"}

    # plan and questions are required, architecture is optional
    plan_ctx = next(ctx for ctx in task.context_from if ctx.as_name == "plan")
    assert plan_ctx.required is True

    arch_ctx = next(ctx for ctx in task.context_from if ctx.as_name == "architecture")
    assert arch_ctx.required is False

    # S-07: Final Check - uses context from multiple artifacts including dry run
    s07 = next(step for step in routine.steps if step.id == "S-07")
    task = s07.tasks[0]
    assert len(task.context_from) == 3

    dry_run_ctx = next((ctx for ctx in task.context_from if ctx.as_name == "dry_run"), None)
    assert dry_run_ctx is not None
    assert dry_run_ctx.required is False


def test_idea_to_plan_has_auto_verify():
    """Verify auto-verification is configured for file existence checks."""
    routine_path = (
        Path(__file__).parent.parent.parent / "examples" / "routines" / "idea_to_plan.yaml"
    )
    routine = load_routine_from_path(routine_path)

    # S-01: Initial Plan - auto-verify files exist
    s01 = next(step for step in routine.steps if step.id == "S-01")
    task = s01.tasks[0]
    assert len(task.auto_verify.items) == 1
    assert task.auto_verify.items[0].id == "files_exist"
    assert "test -f" in task.auto_verify.items[0].cmd

    # S-04: Step Planning - auto-verify step plans exist
    s04 = next(step for step in routine.steps if step.id == "S-04")
    task = s04.tasks[0]
    assert len(task.auto_verify.items) == 1
    assert "step-*-plan.md" in task.auto_verify.items[0].cmd

    # S-09: Execution Ready - auto-verify summary exists
    s09 = next(step for step in routine.steps if step.id == "S-09")
    task = s09.tasks[0]
    assert len(task.auto_verify.items) == 1
    assert "plan-summary.md" in task.auto_verify.items[0].cmd


def test_idea_to_plan_has_llm_verification():
    """Verify LLM verification is configured where appropriate."""
    routine_path = (
        Path(__file__).parent.parent.parent / "examples" / "routines" / "idea_to_plan.yaml"
    )
    routine = load_routine_from_path(routine_path)

    # S-07: Final Check - should have verifier with rubric
    s07 = next(step for step in routine.steps if step.id == "S-07")
    task = s07.tasks[0]
    assert len(task.verifier.rubric) == 3

    rubric_ids = {item.id for item in task.verifier.rubric}
    assert rubric_ids == {"completeness", "consistency", "executability"}

    # Check submission template
    assert task.verifier.submission_template.grade_scale == ["A", "B", "C", "D", "F"]
    assert task.verifier.submission_template.require_reason_if_below == "A"
    assert task.verifier.submission_template.require_remediation_if_below == "B"


def test_idea_to_plan_requirements_have_priorities():
    """Verify requirements have appropriate priorities."""
    routine_path = (
        Path(__file__).parent.parent.parent / "examples" / "routines" / "idea_to_plan.yaml"
    )
    routine = load_routine_from_path(routine_path)

    # S-01: Initial Plan
    s01 = next(step for step in routine.steps if step.id == "S-01")
    task = s01.tasks[0]
    assert len(task.requirements) == 4

    # Most should be critical
    critical_reqs = [req for req in task.requirements if req.priority == Priority.CRITICAL]
    assert len(critical_reqs) == 3

    # Architecture is expected priority
    arch_req = next(req for req in task.requirements if "architecture" in req.desc.lower())
    assert arch_req.priority == Priority.EXPECTED


def test_idea_to_plan_retry_config():
    """Verify retry configuration is set appropriately."""
    routine_path = (
        Path(__file__).parent.parent.parent / "examples" / "routines" / "idea_to_plan.yaml"
    )
    routine = load_routine_from_path(routine_path)

    # Most tasks should have retry configured
    s01 = next(step for step in routine.steps if step.id == "S-01")
    assert s01.tasks[0].retry.max_attempts == 2

    s07 = next(step for step in routine.steps if step.id == "S-07")
    assert s07.tasks[0].retry.max_attempts == 2


def test_idea_to_plan_step_progression():
    """Verify the logical flow of steps."""
    routine_path = (
        Path(__file__).parent.parent.parent / "examples" / "routines" / "idea_to_plan.yaml"
    )
    routine = load_routine_from_path(routine_path)

    # Verify step titles follow expected progression
    step_titles = [step.title for step in routine.steps]
    expected_titles = [
        "Initial Plan",
        "Human Review",
        "Plan Refinement",
        "Step Planning",
        "Task Breakdown",
        "Dry Run",
        "Final Check",
        "Final Plan Review",
        "Execution Ready",
    ]
    assert step_titles == expected_titles

    # Verify each step has step_context (except gates which may not need it)
    for step in routine.steps:
        if step.gate is None or step.id not in ["S-02", "S-08"]:
            assert step.step_context is not None
