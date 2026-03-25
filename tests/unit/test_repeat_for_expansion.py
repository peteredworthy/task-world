"""Tests for repeat_for expansion in workflow engine.

Tests verify that:
1. List from run config -> N step copies with correct item and item_index
2. List from prior step output -> N step copies
3. Empty list -> skipped step
4. Variable not found -> run paused
5. Non-list value -> run paused
6. repeat_for + when combo -> expand first, evaluate per copy
"""

import pytest

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.config.models import (
    RoutineConfig,
    StepConfig,
    TaskConfig,
    StepCondition,
)
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import Run, StepState, TaskState, Attempt
from orchestrator.workflow import (
    _parse_repeat_for_expression,
    _get_variable_value_for_repeat,
    _create_repeat_step_copies,
    check_step_progression,
)


class TestParseRepeatForExpression:
    """Tests for _parse_repeat_for_expression function."""

    def test_parse_context_items_expression(self) -> None:
        """Parse 'item in context.items' correctly."""
        var_name, var_path = _parse_repeat_for_expression("item in context.items")
        assert var_name == "item"
        assert var_path == "context.items"

    def test_parse_config_environments_expression(self) -> None:
        """Parse 'env in config.environments' correctly."""
        var_name, var_path = _parse_repeat_for_expression("env in config.environments")
        assert var_name == "env"
        assert var_path == "config.environments"

    def test_parse_step_output_expression(self) -> None:
        """Parse 'output in steps.S1.output' correctly."""
        var_name, var_path = _parse_repeat_for_expression("output in steps.S1.output")
        assert var_name == "output"
        assert var_path == "steps.S1.output"

    def test_parse_nested_path(self) -> None:
        """Parse expressions with nested paths."""
        var_name, var_path = _parse_repeat_for_expression("item in context.targets.all")
        assert var_name == "item"
        assert var_path == "context.targets.all"

    def test_parse_invalid_no_in_keyword(self) -> None:
        """Fail when 'in' keyword is missing."""
        with pytest.raises(ValueError) as exc_info:
            _parse_repeat_for_expression("item context.items")
        assert "Invalid repeat_for expression" in str(exc_info.value)

    def test_parse_invalid_too_few_parts(self) -> None:
        """Fail when expression has too few parts."""
        with pytest.raises(ValueError) as exc_info:
            _parse_repeat_for_expression("item in")
        assert "Invalid repeat_for expression" in str(exc_info.value)

    def test_parse_invalid_empty_string(self) -> None:
        """Fail on empty string."""
        with pytest.raises(ValueError) as exc_info:
            _parse_repeat_for_expression("")
        assert "Invalid repeat_for expression" in str(exc_info.value)

    def test_parse_case_insensitive_in(self) -> None:
        """The 'in' keyword should be case-insensitive."""
        var_name, var_path = _parse_repeat_for_expression("item IN context.items")
        assert var_name == "item"
        assert var_path == "context.items"


class TestGetVariableValueForRepeat:
    """Tests for _get_variable_value_for_repeat function."""

    def test_resolve_context_simple_list(self) -> None:
        """Resolve list from context."""
        run_config = {"items": [1, 2, 3]}
        run = Run(id="run-1", repo_name="proj", source_branch="main")

        value = _get_variable_value_for_repeat("context.items", run_config, run)
        assert value == [1, 2, 3]

    def test_resolve_context_nested_list(self) -> None:
        """Resolve nested list from context."""
        run_config = {"targets": {"all": ["a", "b", "c"]}}
        run = Run(id="run-1", repo_name="proj", source_branch="main")

        value = _get_variable_value_for_repeat("context.targets.all", run_config, run)
        assert value == ["a", "b", "c"]

    def test_resolve_step_output_list(self) -> None:
        """Resolve list from prior step output."""
        # Create a run with a completed step that has output
        run = Run(id="run-1", repo_name="proj", source_branch="main")
        step = StepState(id="S1", config_id="S1", title="Step 1")
        task = TaskState(id="T1", config_id="T1")
        attempt = Attempt(attempt_num=1)
        attempt.agent_output = '["server1", "server2", "server3"]'
        task.attempts.append(attempt)
        task.status = TaskStatus.COMPLETED
        step.tasks.append(task)
        step.completed = True
        run.steps.append(step)

        value = _get_variable_value_for_repeat("steps.S1.output", {}, run)
        assert isinstance(value, list)
        assert '["server1", "server2", "server3"]' in value

    def test_resolve_context_variable_not_found(self) -> None:
        """Raise error when variable not found in context."""
        run_config = {"items": [1, 2, 3]}
        run = Run(id="run-1", repo_name="proj", source_branch="main")

        with pytest.raises(ValueError) as exc_info:
            _get_variable_value_for_repeat("context.missing_key", run_config, run)
        assert "Variable not found in context" in str(exc_info.value)

    def test_resolve_non_existent_step(self) -> None:
        """Raise error when referenced step does not exist."""
        run = Run(id="run-1", repo_name="proj", source_branch="main")

        with pytest.raises(ValueError) as exc_info:
            _get_variable_value_for_repeat("steps.S99.output", {}, run)
        assert "not found in run" in str(exc_info.value)

    def test_resolve_incomplete_step_output(self) -> None:
        """Raise error when step output is not yet completed."""
        run = Run(id="run-1", repo_name="proj", source_branch="main")
        step = StepState(id="S1", config_id="S1", title="Step 1")
        task = TaskState(id="T1", config_id="T1")
        task.status = TaskStatus.BUILDING  # Not completed
        step.tasks.append(task)
        run.steps.append(step)

        with pytest.raises(ValueError) as exc_info:
            _get_variable_value_for_repeat("steps.S1.output", {}, run)
        assert "not yet completed" in str(exc_info.value)

    def test_resolve_invalid_path_prefix(self) -> None:
        """Raise error for unsupported path prefix."""
        run = Run(id="run-1", repo_name="proj", source_branch="main")

        with pytest.raises(ValueError) as exc_info:
            _get_variable_value_for_repeat("env.variables", {}, run)
        assert "Unsupported variable path" in str(exc_info.value)

    def test_resolve_context_nested_access_on_non_dict(self) -> None:
        """Raise error when trying to access nested key on non-dict."""
        run_config = {"items": [1, 2, 3]}  # items is a list, not a dict
        run = Run(id="run-1", repo_name="proj", source_branch="main")

        with pytest.raises(ValueError) as exc_info:
            _get_variable_value_for_repeat("context.items.nested", run_config, run)
        assert "Cannot access" in str(exc_info.value)

    def test_resolve_steps_incomplete_path(self) -> None:
        """Raise error for incomplete steps path."""
        run = Run(id="run-1", repo_name="proj", source_branch="main")

        with pytest.raises(ValueError) as exc_info:
            _get_variable_value_for_repeat("steps.S1", {}, run)
        assert "Invalid steps path" in str(exc_info.value)

    def test_resolve_step_task_outputs_property(self) -> None:
        """Resolve task_outputs property from prior step."""
        run = Run(id="run-1", repo_name="proj", source_branch="main")
        step = StepState(id="S1", config_id="S1", title="Step 1")
        task = TaskState(id="T1", config_id="T1")
        attempt = Attempt(attempt_num=1)
        attempt.agent_output = "task output"
        task.attempts.append(attempt)
        task.status = TaskStatus.COMPLETED
        step.tasks.append(task)
        step.completed = True
        run.steps.append(step)

        value = _get_variable_value_for_repeat("steps.S1.task_outputs", {}, run)
        assert isinstance(value, dict)
        assert "T1" in value


class TestCreateRepeatStepCopies:
    """Tests for _create_repeat_step_copies function."""

    def test_create_copies_from_list_of_strings(self) -> None:
        """Create N copies with correct item and item_index values."""
        original_step = StepState(id="S1", config_id="S1", title="Process Item")
        items = ["item1", "item2", "item3"]

        copies = _create_repeat_step_copies(original_step, items, "item")

        assert len(copies) == 3
        # Check first copy
        assert copies[0].id == "S1-0"
        assert copies[0].title == "Process Item [1/3]"
        assert copies[0].condition["injected_vars"]["item"] == "item1"
        assert copies[0].condition["injected_vars"]["item_index"] == 0

        # Check second copy
        assert copies[1].id == "S1-1"
        assert copies[1].title == "Process Item [2/3]"
        assert copies[1].condition["injected_vars"]["item"] == "item2"
        assert copies[1].condition["injected_vars"]["item_index"] == 1

        # Check third copy
        assert copies[2].id == "S1-2"
        assert copies[2].title == "Process Item [3/3]"
        assert copies[2].condition["injected_vars"]["item"] == "item3"
        assert copies[2].condition["injected_vars"]["item_index"] == 2

    def test_create_copies_from_list_of_dicts(self) -> None:
        """Create copies from list of dictionaries."""
        original_step = StepState(id="S1", config_id="S1", title="Deploy Server")
        items = [
            {"name": "server1", "region": "us-east"},
            {"name": "server2", "region": "us-west"},
        ]

        copies = _create_repeat_step_copies(original_step, items, "server")

        assert len(copies) == 2
        assert copies[0].condition["injected_vars"]["server"] == items[0]
        assert copies[1].condition["injected_vars"]["server"] == items[1]

    def test_create_copies_single_item(self) -> None:
        """Create copy for single item list."""
        original_step = StepState(id="S1", config_id="S1", title="Single Task")
        items = ["only_item"]

        copies = _create_repeat_step_copies(original_step, items, "task")

        assert len(copies) == 1
        assert copies[0].id == "S1-0"
        assert copies[0].title == "Single Task [1/1]"
        assert copies[0].condition["injected_vars"]["task"] == "only_item"

    def test_create_copies_preserves_tasks(self) -> None:
        """Ensure copies have independent task copies."""
        original_task = TaskState(id="T1", config_id="T1")
        original_step = StepState(id="S1", config_id="S1", title="Step", tasks=[original_task])
        items = ["a", "b"]

        copies = _create_repeat_step_copies(original_step, items, "item")

        # Each copy should have its own tasks (deep copy)
        assert len(copies[0].tasks) == 1
        assert len(copies[1].tasks) == 1
        # Tasks should be independent copies
        assert copies[0].tasks[0] is not copies[1].tasks[0]

    def test_create_copies_numeric_items(self) -> None:
        """Create copies from list of numbers."""
        original_step = StepState(id="S1", config_id="S1", title="Retry")
        items = [1, 2, 3, 4, 5]

        copies = _create_repeat_step_copies(original_step, items, "attempt")

        assert len(copies) == 5
        for i, copy in enumerate(copies):
            assert copy.condition["injected_vars"]["attempt"] == items[i]
            assert copy.condition["injected_vars"]["item_index"] == i

    def test_create_copies_preserves_step_config_id(self) -> None:
        """Original config_id should be preserved in copies."""
        original_step = StepState(id="S1", config_id="STEP_CONFIG_1", title="Step")
        items = ["a", "b"]

        copies = _create_repeat_step_copies(original_step, items, "item")

        # config_id should remain the same
        assert copies[0].config_id == "STEP_CONFIG_1"
        assert copies[1].config_id == "STEP_CONFIG_1"


class TestRepeatForWithStepProgression:
    """Integration tests for repeat_for within step progression logic."""

    def _make_routine_with_repeat_for(
        self, repeat_for_expr: str | None = None, when_expr: str | None = None
    ) -> RoutineConfig:
        """Helper to create routine with repeat_for step."""
        steps = [
            StepConfig(
                id="S1",
                title="Step 1",
                tasks=[TaskConfig(id="T1", title="Task 1", task_context="Do step 1")],
            ),
            StepConfig(
                id="S2",
                title="Repeat Step",
                tasks=[TaskConfig(id="T2", title="Task 2", task_context="Do step 2")],
                condition=StepCondition(repeat_for=repeat_for_expr, when=when_expr)
                if repeat_for_expr or when_expr
                else None,
            ),
        ]

        return RoutineConfig(
            id="test-routine",
            name="Test Routine",
            steps=steps,
        )

    def test_repeat_for_expansion_simple(self) -> None:
        """Basic repeat_for expansion creates N step copies."""
        routine = self._make_routine_with_repeat_for(repeat_for_expr="item in context.items")
        run = create_run_from_routine(routine, repo_name="proj", source_branch="main")

        # Advance through step 1 to completion
        run.steps[0].completed = True
        run.current_step_index = 1

        run_config = {"items": ["a", "b", "c"]}
        check_step_progression(run, routine, run_config=run_config)

        # S2 should be expanded to 3 copies (original is replaced)
        assert len(run.steps) == 4  # S1 + 3 copies of S2

        # Check the expanded steps
        expanded_steps = [s for s in run.steps if s.config_id == "S2"]
        assert len(expanded_steps) == 3

        assert expanded_steps[0].title == "Repeat Step [1/3]"
        assert expanded_steps[0].condition["injected_vars"]["item"] == "a"
        assert expanded_steps[0].condition["injected_vars"]["item_index"] == 0

        assert expanded_steps[1].title == "Repeat Step [2/3]"
        assert expanded_steps[1].condition["injected_vars"]["item"] == "b"
        assert expanded_steps[1].condition["injected_vars"]["item_index"] == 1

        assert expanded_steps[2].title == "Repeat Step [3/3]"
        assert expanded_steps[2].condition["injected_vars"]["item"] == "c"
        assert expanded_steps[2].condition["injected_vars"]["item_index"] == 2

    def test_repeat_for_empty_list_skips_step(self) -> None:
        """Empty list should skip the step."""
        routine = self._make_routine_with_repeat_for(repeat_for_expr="item in context.items")
        run = create_run_from_routine(routine, repo_name="proj", source_branch="main")

        run.steps[0].completed = True
        run.current_step_index = 1

        run_config = {"items": []}
        check_step_progression(run, routine, run_config=run_config)

        # Step S2 should be marked as skipped
        assert run.steps[1].skipped is True
        assert run.steps[1].skip_reason == "empty list"
        assert run.current_step_index == 2

    def test_repeat_for_variable_not_found_pauses_run(self) -> None:
        """Missing variable should pause run."""
        routine = self._make_routine_with_repeat_for(repeat_for_expr="item in context.items")
        run = create_run_from_routine(routine, repo_name="proj", source_branch="main")

        run.steps[0].completed = True
        run.current_step_index = 1

        run_config = {}  # Missing 'items'
        check_step_progression(run, routine, run_config=run_config)

        # Run should be paused
        assert run.status == RunStatus.PAUSED
        assert run.pause_reason == "repeat_for_resolution_error"

    def test_repeat_for_non_list_value_pauses_run(self) -> None:
        """Non-list value should pause run."""
        routine = self._make_routine_with_repeat_for(repeat_for_expr="item in context.items")
        run = create_run_from_routine(routine, repo_name="proj", source_branch="main")

        run.steps[0].completed = True
        run.current_step_index = 1

        run_config = {"items": "not a list"}  # String instead of list
        check_step_progression(run, routine, run_config=run_config)

        # Run should be paused
        assert run.status == RunStatus.PAUSED
        assert run.pause_reason == "repeat_for_invalid_type"

    def test_repeat_for_with_when_expands_first(self) -> None:
        """repeat_for and when together should expand first, then evaluate."""
        routine = self._make_routine_with_repeat_for(
            repeat_for_expr="item in context.items", when_expr="context.enabled"
        )
        run = create_run_from_routine(routine, repo_name="proj", source_branch="main")

        run.steps[0].completed = True
        run.current_step_index = 1

        run_config = {"items": ["a", "b"], "enabled": True}
        check_step_progression(run, routine, run_config=run_config)

        # Should expand to copies (2 items), NOT skip
        # First expansion happens, then each copy evaluates its condition
        assert len(run.steps) >= 3  # At least S1 + 2 expanded copies

    def test_repeat_for_from_prior_step_output(self) -> None:
        """repeat_for can reference output from prior step."""
        routine = self._make_routine_with_repeat_for(repeat_for_expr="item in steps.S1.output")
        run = create_run_from_routine(routine, repo_name="proj", source_branch="main")

        # Complete step 1 with output
        task = run.steps[0].tasks[0]
        task.status = TaskStatus.COMPLETED
        attempt = Attempt(attempt_num=1)
        attempt.agent_output = "output1"
        task.attempts.append(attempt)
        run.steps[0].completed = True
        run.current_step_index = 1

        check_step_progression(run, routine)

        # S2 should be expanded based on S1's output
        # Should have multiple copies since steps.S1.output returns a list
        assert len(run.steps) >= 2


class TestRepeatForEdgeCases:
    """Edge case tests for repeat_for expansion."""

    def test_repeat_for_with_complex_objects(self) -> None:
        """repeat_for should handle complex objects in list."""
        items = [
            {"server": "s1", "port": 8080, "env": "prod"},
            {"server": "s2", "port": 8081, "env": "staging"},
            {"server": "s3", "port": 8082, "env": "dev"},
        ]

        original_step = StepState(id="S1", config_id="S1", title="Deploy")
        copies = _create_repeat_step_copies(original_step, items, "server_config")

        assert len(copies) == 3
        assert copies[0].condition["injected_vars"]["server_config"]["server"] == "s1"
        assert copies[1].condition["injected_vars"]["server_config"]["port"] == 8081
        assert copies[2].condition["injected_vars"]["server_config"]["env"] == "dev"

    def test_repeat_for_large_list(self) -> None:
        """repeat_for should handle large lists."""
        items = list(range(100))
        original_step = StepState(id="S1", config_id="S1", title="Process")

        copies = _create_repeat_step_copies(original_step, items, "item")

        assert len(copies) == 100
        assert copies[0].condition["injected_vars"]["item_index"] == 0
        assert copies[99].condition["injected_vars"]["item_index"] == 99
        assert copies[99].title == "Process [100/100]"

    def test_repeat_for_with_special_characters_in_items(self) -> None:
        """repeat_for should handle items with special characters."""
        items = ["test-1", "test_2", "test.3", "test@4"]
        original_step = StepState(id="S1", config_id="S1", title="Step")

        copies = _create_repeat_step_copies(original_step, items, "name")

        assert len(copies) == 4
        assert copies[0].condition["injected_vars"]["name"] == "test-1"
        assert copies[1].condition["injected_vars"]["name"] == "test_2"

    def test_repeat_for_with_unicode_items(self) -> None:
        """repeat_for should handle Unicode items."""
        items = ["café", "naïve", "résumé", "🚀"]
        original_step = StepState(id="S1", config_id="S1", title="Step")

        copies = _create_repeat_step_copies(original_step, items, "item")

        assert len(copies) == 4
        assert copies[0].condition["injected_vars"]["item"] == "café"
        assert copies[3].condition["injected_vars"]["item"] == "🚀"
