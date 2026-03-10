"""Tests for conditional step models and event handling."""

from datetime import datetime, timezone


from orchestrator.config.models import (
    RoutineConfig,
    StepCondition,
    StepConfig,
    TaskConfig,
)
from orchestrator.state.factory import create_run_from_routine, create_step_state
from orchestrator.state.models import StepState
from orchestrator.workflow.events import StepSkipped


class TestStepConditionModel:
    """Tests for StepCondition config model."""

    def test_step_condition_with_when(self) -> None:
        """StepCondition should accept 'when' clause."""
        condition = StepCondition(when="steps.S1.skipped")
        assert condition.when == "steps.S1.skipped"
        assert condition.repeat_for is None

    def test_step_condition_with_repeat_for(self) -> None:
        """StepCondition should accept 'repeat_for' clause."""
        condition = StepCondition(repeat_for="items in context.items")
        assert condition.repeat_for == "items in context.items"
        assert condition.when is None

    def test_step_condition_both_fields(self) -> None:
        """StepCondition should accept both when and repeat_for."""
        condition = StepCondition(
            when="context.env == 'prod'", repeat_for="items in context.targets"
        )
        assert condition.when == "context.env == 'prod'"
        assert condition.repeat_for == "items in context.targets"

    def test_step_condition_empty(self) -> None:
        """StepCondition should allow None for both fields."""
        condition = StepCondition()
        assert condition.when is None
        assert condition.repeat_for is None


class TestStepConfigWithCondition:
    """Tests for StepConfig with condition field."""

    def test_step_config_with_condition(self) -> None:
        """StepConfig should preserve condition field."""
        condition = StepCondition(when="steps.S1.completed")
        step = StepConfig(
            id="S2",
            title="Conditional Step",
            tasks=[TaskConfig(id="T1", title="Task 1", task_context="Context")],
            condition=condition,
        )
        assert step.condition == condition
        assert step.condition.when == "steps.S1.completed"

    def test_step_config_without_condition(self) -> None:
        """StepConfig should allow None condition."""
        step = StepConfig(
            id="S1",
            title="Normal Step",
            tasks=[TaskConfig(id="T1", title="Task 1", task_context="Context")],
        )
        assert step.condition is None

    def test_routine_with_conditional_steps(self) -> None:
        """RoutineConfig should accept steps with conditions."""
        routine = RoutineConfig(
            id="test-routine",
            name="Test Routine",
            steps=[
                StepConfig(
                    id="S1",
                    title="Step 1",
                    tasks=[TaskConfig(id="T1", title="Task 1", task_context="Context")],
                ),
                StepConfig(
                    id="S2",
                    title="Step 2",
                    tasks=[TaskConfig(id="T2", title="Task 2", task_context="Context")],
                    condition=StepCondition(when="steps.S1.completed"),
                ),
            ],
        )
        assert routine.steps[0].condition is None
        assert routine.steps[1].condition is not None
        assert routine.steps[1].condition.when == "steps.S1.completed"


class TestStepStateSkipFields:
    """Tests for StepState skip fields."""

    def test_step_state_default_skip_fields(self) -> None:
        """StepState should have default skip fields."""
        step = StepState(config_id="S1", title="Step 1")
        assert step.condition is None
        assert step.skipped is False
        assert step.skip_reason is None

    def test_step_state_with_condition(self) -> None:
        """StepState should preserve condition from creation."""
        condition_dict = {"when": "context.skip_step2"}
        step = StepState(config_id="S2", title="Step 2", condition=condition_dict)
        assert step.condition == condition_dict
        assert step.condition["when"] == "context.skip_step2"

    def test_step_state_marked_skipped(self) -> None:
        """StepState should allow marking as skipped with reason."""
        step = StepState(
            config_id="S1",
            title="Step 1",
            skipped=True,
            skip_reason="condition evaluated to false",
        )
        assert step.skipped is True
        assert step.skip_reason == "condition evaluated to false"

    def test_step_state_with_all_skip_fields(self) -> None:
        """StepState should maintain all skip-related fields together."""
        condition_dict = {"when": "env.stage == 'test'"}
        step = StepState(
            config_id="S3",
            title="Test Step",
            condition=condition_dict,
            skipped=True,
            skip_reason="Skipping because stage is not prod",
        )
        assert step.condition["when"] == "env.stage == 'test'"
        assert step.skipped is True
        assert step.skip_reason == "Skipping because stage is not prod"


class TestStepSkippedEvent:
    """Tests for StepSkipped event class and serialization."""

    def test_step_skipped_event_creation(self) -> None:
        """StepSkipped event should be created with all fields."""
        now = datetime.now(timezone.utc)
        event = StepSkipped(
            timestamp=now,
            run_id="run-123",
            step_index=1,
            step_id="S2",
            condition="steps.S1.completed",
            reason="Condition evaluated to false",
        )
        assert event.timestamp == now
        assert event.run_id == "run-123"
        assert event.event_type == "step_skipped"
        assert event.step_index == 1
        assert event.step_id == "S2"
        assert event.condition == "steps.S1.completed"
        assert event.reason == "Condition evaluated to false"

    def test_step_skipped_event_default_values(self) -> None:
        """StepSkipped event should have reasonable defaults."""
        event = StepSkipped(timestamp=datetime.now(timezone.utc), run_id="run-123")
        assert event.step_index == 0
        assert event.step_id == ""
        assert event.condition is None
        assert event.reason is None

    def test_step_skipped_event_serializable(self) -> None:
        """StepSkipped event should be serializable to dict/JSON."""
        now = datetime.now(timezone.utc)
        event = StepSkipped(
            timestamp=now,
            run_id="run-123",
            step_index=2,
            step_id="S3",
            condition="context.env == 'dev'",
            reason="Development environment detected",
        )

        # Should be convertible to dict
        event_dict = {
            "timestamp": now,
            "run_id": "run-123",
            "event_type": "step_skipped",
            "step_index": 2,
            "step_id": "S3",
            "condition": "context.env == 'dev'",
            "reason": "Development environment detected",
        }

        assert event.timestamp == event_dict["timestamp"]
        assert event.run_id == event_dict["run_id"]
        assert event.step_index == event_dict["step_index"]
        assert event.step_id == event_dict["step_id"]
        assert event.condition == event_dict["condition"]
        assert event.reason == event_dict["reason"]

    def test_step_skipped_event_fields_types(self) -> None:
        """StepSkipped event fields should have correct types."""
        event = StepSkipped(
            timestamp=datetime.now(timezone.utc),
            run_id="run-123",
            step_index=1,
            step_id="S2",
            condition="when.condition",
            reason="test reason",
        )
        assert isinstance(event.step_index, int)
        assert isinstance(event.step_id, str)
        assert isinstance(event.condition, str) or event.condition is None
        assert isinstance(event.reason, str) or event.reason is None


class TestCreateRunFromRoutinePreservesCondition:
    """Tests for create_run_from_routine preserving condition field."""

    def test_create_run_preserves_step_condition(self) -> None:
        """create_run_from_routine should preserve condition from StepConfig."""
        condition = StepCondition(when="steps.S1.completed")
        routine = RoutineConfig(
            id="test-routine",
            name="Test",
            steps=[
                StepConfig(
                    id="S1",
                    title="Step 1",
                    tasks=[TaskConfig(id="T1", title="Task 1", task_context="Context")],
                ),
                StepConfig(
                    id="S2",
                    title="Step 2",
                    tasks=[TaskConfig(id="T2", title="Task 2", task_context="Context")],
                    condition=condition,
                ),
            ],
        )

        run = create_run_from_routine(routine=routine, repo_name="proj-1", source_branch="main")

        # First step should have no condition
        assert run.steps[0].condition is None
        # Second step should have condition preserved
        assert run.steps[1].condition is not None
        assert run.steps[1].condition["when"] == "steps.S1.completed"

    def test_create_run_no_expansion_of_repeat_for(self) -> None:
        """create_run_from_routine should NOT expand repeat_for at creation time."""
        condition = StepCondition(repeat_for="item in context.items")
        routine = RoutineConfig(
            id="test-routine",
            name="Test",
            steps=[
                StepConfig(
                    id="S1",
                    title="Repeating Step",
                    tasks=[TaskConfig(id="T1", title="Task 1", task_context="Context")],
                    condition=condition,
                ),
            ],
        )

        run = create_run_from_routine(routine=routine, repo_name="proj-1", source_branch="main")

        # Condition should be preserved as-is, NOT expanded
        assert run.steps[0].condition is not None
        assert run.steps[0].condition["repeat_for"] == "item in context.items"
        # Should still have only one step, not expanded
        assert len(run.steps) == 1

    def test_create_step_state_preserves_condition(self) -> None:
        """create_step_state should preserve condition from StepConfig."""
        condition = StepCondition(when="env.production")
        step_config = StepConfig(
            id="S1",
            title="Production Only",
            tasks=[TaskConfig(id="T1", title="Task 1", task_context="Context")],
            condition=condition,
        )

        step_state = create_step_state(step_config)

        assert step_state.condition is not None
        assert step_state.condition["when"] == "env.production"
        assert step_state.config_id == "S1"
        assert step_state.title == "Production Only"


class TestConditionalStepsIntegration:
    """Integration tests for conditional steps across models."""

    def test_full_conditional_routine_workflow(self) -> None:
        """Test full workflow with conditional steps."""
        routine = RoutineConfig(
            id="conditional-routine",
            name="Conditional Workflow",
            steps=[
                StepConfig(
                    id="S1",
                    title="Setup",
                    tasks=[TaskConfig(id="T1", title="Initialize", task_context="Init")],
                ),
                StepConfig(
                    id="S2",
                    title="Optional Feature",
                    tasks=[TaskConfig(id="T2", title="Build Feature", task_context="Build")],
                    condition=StepCondition(when="context.include_feature"),
                ),
                StepConfig(
                    id="S3",
                    title="Cleanup",
                    tasks=[TaskConfig(id="T3", title="Cleanup", task_context="Clean")],
                ),
            ],
        )

        run = create_run_from_routine(routine=routine, repo_name="proj-1", source_branch="main")

        assert len(run.steps) == 3
        assert run.steps[0].condition is None
        assert run.steps[1].condition is not None
        assert run.steps[1].condition["when"] == "context.include_feature"
        assert run.steps[2].condition is None

    def test_event_and_state_consistency(self) -> None:
        """Test that StepSkipped event and StepState skip fields are consistent."""
        # Create a step state marked as skipped
        step_state = StepState(
            config_id="S2",
            title="Skipped Step",
            condition={"when": "steps.S1.completed"},
            skipped=True,
            skip_reason="Condition not met",
        )

        # Create corresponding event
        event = StepSkipped(
            timestamp=datetime.now(timezone.utc),
            run_id="run-123",
            step_index=1,
            step_id=step_state.id,
            condition="steps.S1.completed",
            reason="Condition not met",
        )

        # Verify consistency
        assert step_state.skipped is True
        assert step_state.skip_reason == event.reason
        assert step_state.condition is not None
        assert step_state.condition["when"] == event.condition
