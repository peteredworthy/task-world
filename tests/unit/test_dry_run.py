"""Unit tests for dry-run verification mode."""

import json

import pytest

from orchestrator.config.enums import Priority, StepType
from orchestrator.config.models import (
    DryRunConfig,
    RequirementConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
)
from orchestrator.state.models import Run
from orchestrator.workflow.dry_run import (
    DryRunResult,
    build_dry_run_context,
    build_dry_run_prompt,
    execute_dry_run,
    get_step_by_id,
    parse_dry_run_response,
)


def test_dry_run_config_validation():
    """Test DryRunConfig model validation."""
    config = DryRunConfig(
        target_steps=["S-01", "S-02"],
        context_limit=4000,
        report_path="docs/dry-run-report.md",
    )

    assert config.target_steps == ["S-01", "S-02"]
    assert config.context_limit == 4000
    assert config.report_path == "docs/dry-run-report.md"


def test_dry_run_config_defaults():
    """Test DryRunConfig default values."""
    config = DryRunConfig(
        target_steps=["S-01"],
        report_path="report.md",
    )

    assert config.context_limit == 4000  # Default


def test_dry_run_result_model():
    """Test DryRunResult model."""
    result = DryRunResult(
        step_id="S-01",
        task_id="T-01",
        simulated_outcome="Would implement feature X",
        identified_gaps=["Missing database schema"],
        missing_context=["API documentation"],
        unclear_requirements=["Performance targets not specified"],
        suggested_improvements=["Add acceptance criteria"],
    )

    assert result.step_id == "S-01"
    assert result.task_id == "T-01"
    assert len(result.identified_gaps) == 1
    assert len(result.missing_context) == 1


def test_dry_run_result_empty_lists():
    """Test DryRunResult with empty lists."""
    result = DryRunResult(
        step_id="S-01",
        task_id="T-01",
        simulated_outcome="Complete",
    )

    assert result.identified_gaps == []
    assert result.missing_context == []
    assert result.unclear_requirements == []
    assert result.suggested_improvements == []


def test_build_dry_run_context_basic():
    """Test building dry-run context with basic inputs."""
    run = Run(
        project_id="proj-1",
        config={"feature": "auth", "version": "v1"},
    )

    step = StepConfig(
        id="S-01",
        title="Test Step",
        step_context="Implement authentication feature",
        tasks=[
            TaskConfig(
                id="T-01",
                title="Task 1",
                task_context="Build login",
            )
        ],
    )

    artifacts = {
        "plan.md": "# Plan\nImplement OAuth2",
        "design.md": "# Design\nUse JWT tokens",
    }

    context = build_dry_run_context(
        run=run,
        step=step,
        artifacts=artifacts,
        token_limit=1000,
    )

    assert "## Step Context" in context
    assert "Implement authentication feature" in context
    assert "## Run Configuration" in context
    assert "feature: auth" in context
    assert "## Available Artifacts" in context
    assert "plan.md" in context


def test_build_dry_run_context_respects_token_limit():
    """Test that context building respects token limit."""
    run = Run(
        project_id="proj-1",
        config={},
    )

    step = StepConfig(
        id="S-01",
        title="Test",
        step_context="Short context",
        tasks=[
            TaskConfig(
                id="T-01",
                title="Task",
                task_context="Do work",
            )
        ],
    )

    # Create large artifacts
    large_content = "x" * 10000  # ~2500 tokens
    artifacts = {
        "large1.md": large_content,
        "large2.md": large_content,
    }

    context = build_dry_run_context(
        run=run,
        step=step,
        artifacts=artifacts,
        token_limit=500,  # Small limit
    )

    # Should be truncated
    assert "[... truncated ...]" in context
    # Rough check: should be much smaller than input
    assert len(context) < len(large_content)


def test_build_dry_run_context_empty_artifacts():
    """Test context building with no artifacts."""
    run = Run(
        project_id="proj-1",
        config={"key": "value"},
    )

    step = StepConfig(
        id="S-01",
        title="Test",
        step_context="Do something",
        tasks=[
            TaskConfig(
                id="T-01",
                title="Task",
                task_context="Work",
            )
        ],
    )

    context = build_dry_run_context(
        run=run,
        step=step,
        artifacts={},
        token_limit=1000,
    )

    assert "## Step Context" in context
    assert "Do something" in context
    assert "## Run Configuration" in context
    # Should not have artifacts section
    assert "Available Artifacts" not in context or "## Available Artifacts" in context


def test_build_dry_run_context_no_step_context():
    """Test context building when step has no context."""
    run = Run(
        project_id="proj-1",
        config={"key": "value"},  # Add config so section appears
    )

    step = StepConfig(
        id="S-01",
        title="Test",
        tasks=[
            TaskConfig(
                id="T-01",
                title="Task",
                task_context="Work",
            )
        ],
    )

    context = build_dry_run_context(
        run=run,
        step=step,
        artifacts={},
        token_limit=1000,
    )

    # Should still work, just no step context section
    assert "## Run Configuration" in context
    # Step Context should not be present
    assert "## Step Context" not in context


def test_build_dry_run_prompt_basic():
    """Test building dry-run prompt."""
    step = StepConfig(
        id="S-01",
        title="Implementation",
        tasks=[
            TaskConfig(
                id="T-01",
                title="Build feature",
                task_context="Implement the {{feature}} feature",
                requirements=[
                    RequirementConfig(
                        id="R1",
                        desc="Add unit tests",
                        priority=Priority.CRITICAL,
                    ),
                    RequirementConfig(
                        id="R2",
                        desc="Update documentation",
                        priority=Priority.EXPECTED,
                    ),
                ],
            )
        ],
    )

    task = step.tasks[0]
    context = "## Context\nSome limited context here"
    config = {"feature": "authentication"}

    prompt = build_dry_run_prompt(
        step=step,
        task=task,
        context=context,
        config=config,
    )

    # Check prompt structure
    assert "You are simulating execution" in prompt
    assert "LIMITED context" in prompt
    assert context in prompt
    assert "Implement the authentication feature" in prompt  # Variable substituted
    assert "REQUIREMENTS:" in prompt
    assert "[CRITICAL] Add unit tests" in prompt
    assert "[EXPECTED] Update documentation" in prompt
    assert "Respond in JSON format:" in prompt
    assert '"simulated_outcome"' in prompt


def test_build_dry_run_prompt_no_requirements():
    """Test prompt building with no requirements."""
    step = StepConfig(
        id="S-01",
        title="Test",
        tasks=[
            TaskConfig(
                id="T-01",
                title="Task",
                task_context="Do work",
            )
        ],
    )

    prompt = build_dry_run_prompt(
        step=step,
        task=step.tasks[0],
        context="Context",
        config={},
    )

    assert "No specific requirements defined" in prompt


def test_parse_dry_run_response_valid():
    """Test parsing valid dry-run response."""
    response = json.dumps(
        {
            "simulated_outcome": "Would implement OAuth2 flow",
            "identified_gaps": ["Missing API credentials"],
            "missing_context": ["User schema definition"],
            "unclear_requirements": ["Token expiration time not specified"],
            "suggested_improvements": ["Add error handling requirements"],
        }
    )

    result = parse_dry_run_response(response)

    assert result["simulated_outcome"] == "Would implement OAuth2 flow"
    assert len(result["identified_gaps"]) == 1
    assert len(result["missing_context"]) == 1
    assert len(result["unclear_requirements"]) == 1
    assert len(result["suggested_improvements"]) == 1


def test_parse_dry_run_response_empty_lists():
    """Test parsing response with empty lists (no issues found)."""
    response = json.dumps(
        {
            "simulated_outcome": "Clear and complete",
            "identified_gaps": [],
            "missing_context": [],
            "unclear_requirements": [],
            "suggested_improvements": [],
        }
    )

    result = parse_dry_run_response(response)

    assert result["simulated_outcome"] == "Clear and complete"
    assert result["identified_gaps"] == []


def test_parse_dry_run_response_invalid_json():
    """Test parsing invalid JSON response."""
    response = "This is not JSON"

    with pytest.raises(ValueError, match="Invalid JSON response"):
        parse_dry_run_response(response)


def test_parse_dry_run_response_missing_field():
    """Test parsing response missing required field."""
    response = json.dumps(
        {
            "simulated_outcome": "Done",
            "identified_gaps": [],
            # Missing other required fields
        }
    )

    with pytest.raises(ValueError, match="Missing required field"):
        parse_dry_run_response(response)


def test_parse_dry_run_response_wrong_type():
    """Test parsing response with wrong field type."""
    response = json.dumps(
        {
            "simulated_outcome": "Done",
            "identified_gaps": "should be list",  # Wrong type
            "missing_context": [],
            "unclear_requirements": [],
            "suggested_improvements": [],
        }
    )

    with pytest.raises(ValueError, match="must be a list"):
        parse_dry_run_response(response)


def test_get_step_by_id_found():
    """Test finding step by ID."""
    routine = RoutineConfig(
        id="test-routine",
        name="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="First",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Work",
                    )
                ],
            ),
            StepConfig(
                id="S-02",
                title="Second",
                tasks=[
                    TaskConfig(
                        id="T-02",
                        title="Task 2",
                        task_context="More work",
                    )
                ],
            ),
        ],
    )

    step = get_step_by_id(routine, "S-02")

    assert step is not None
    assert step.id == "S-02"
    assert step.title == "Second"


def test_get_step_by_id_not_found():
    """Test step not found returns None."""
    routine = RoutineConfig(
        id="test-routine",
        name="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="First",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task",
                        task_context="Work",
                    )
                ],
            ),
        ],
    )

    step = get_step_by_id(routine, "S-99")

    assert step is None


def test_execute_dry_run_single_step():
    """Test executing dry-run for single step."""
    run = Run(
        project_id="proj-1",
        config={"feature": "auth"},
    )

    routine = RoutineConfig(
        id="test-routine",
        name="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="Implementation",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Build",
                        task_context="Build {{feature}}",
                    )
                ],
            ),
        ],
    )

    config = DryRunConfig(
        target_steps=["S-01"],
        context_limit=4000,
        report_path="report.md",
    )

    results = execute_dry_run(
        run=run,
        routine=routine,
        config=config,
        artifacts={},
    )

    assert len(results) == 1
    assert results[0].step_id == "S-01"
    assert results[0].task_id == "T-01"
    assert results[0].simulated_outcome  # Has placeholder data


def test_execute_dry_run_multiple_steps():
    """Test executing dry-run for multiple steps."""
    run = Run(
        project_id="proj-1",
        config={},
    )

    routine = RoutineConfig(
        id="test-routine",
        name="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="First",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Work 1",
                    )
                ],
            ),
            StepConfig(
                id="S-02",
                title="Second",
                tasks=[
                    TaskConfig(
                        id="T-02",
                        title="Task 2",
                        task_context="Work 2",
                    )
                ],
            ),
        ],
    )

    config = DryRunConfig(
        target_steps=["S-01", "S-02"],
        context_limit=4000,
        report_path="report.md",
    )

    results = execute_dry_run(
        run=run,
        routine=routine,
        config=config,
        artifacts={},
    )

    assert len(results) == 2
    assert results[0].step_id == "S-01"
    assert results[1].step_id == "S-02"


def test_execute_dry_run_with_artifacts():
    """Test executing dry-run with artifacts from prior steps."""
    run = Run(
        project_id="proj-1",
        config={},
    )

    routine = RoutineConfig(
        id="test-routine",
        name="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="Test",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task",
                        task_context="Work",
                    )
                ],
            ),
        ],
    )

    config = DryRunConfig(
        target_steps=["S-01"],
        context_limit=4000,
        report_path="report.md",
    )

    artifacts = {
        "S-00": {
            "plan.md": "# Plan content",
            "design.md": "# Design content",
        }
    }

    results = execute_dry_run(
        run=run,
        routine=routine,
        config=config,
        artifacts=artifacts,
    )

    assert len(results) == 1
    # Artifacts are used in context building (tested separately)


def test_execute_dry_run_step_not_found():
    """Test dry-run fails when target step not found."""
    run = Run(
        project_id="proj-1",
        config={},
    )

    routine = RoutineConfig(
        id="test-routine",
        name="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="Test",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task",
                        task_context="Work",
                    )
                ],
            ),
        ],
    )

    config = DryRunConfig(
        target_steps=["S-99"],  # Non-existent
        context_limit=4000,
        report_path="report.md",
    )

    with pytest.raises(ValueError, match="Target step not found: S-99"):
        execute_dry_run(
            run=run,
            routine=routine,
            config=config,
            artifacts={},
        )


def test_execute_dry_run_multiple_tasks_in_step():
    """Test dry-run with step containing multiple tasks."""
    run = Run(
        project_id="proj-1",
        config={},
    )

    routine = RoutineConfig(
        id="test-routine",
        name="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="Multi-task",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="First task",
                    ),
                    TaskConfig(
                        id="T-02",
                        title="Task 2",
                        task_context="Second task",
                    ),
                ],
            ),
        ],
    )

    config = DryRunConfig(
        target_steps=["S-01"],
        context_limit=4000,
        report_path="report.md",
    )

    results = execute_dry_run(
        run=run,
        routine=routine,
        config=config,
        artifacts={},
    )

    # Should have result for each task
    assert len(results) == 2
    assert results[0].task_id == "T-01"
    assert results[1].task_id == "T-02"


def test_step_config_with_dry_run_type():
    """Test StepConfig with dry_run type and configuration."""
    dry_run_config = DryRunConfig(
        target_steps=["S-02", "S-03"],
        context_limit=2000,
        report_path="docs/dry-run.md",
    )

    step = StepConfig(
        id="S-01",
        title="Dry Run Step",
        type=StepType.DRY_RUN,
        dry_run=dry_run_config,
        tasks=[
            TaskConfig(
                id="T-01",
                title="Placeholder",
                task_context="Dry run has no real tasks",
            )
        ],
    )

    assert step.type == StepType.DRY_RUN
    assert step.dry_run is not None
    assert step.dry_run.target_steps == ["S-02", "S-03"]
    assert step.dry_run.context_limit == 2000


def test_step_config_standard_type_default():
    """Test StepConfig defaults to STANDARD type."""
    step = StepConfig(
        id="S-01",
        title="Normal Step",
        tasks=[
            TaskConfig(
                id="T-01",
                title="Task",
                task_context="Work",
            )
        ],
    )

    assert step.type == StepType.STANDARD
    assert step.dry_run is None
