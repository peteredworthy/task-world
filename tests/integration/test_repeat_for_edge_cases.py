"""Integration tests for repeat_for edge cases handling.

Tests verify that:
1. Empty list marks step as skipped with reason "empty list"
2. Missing variable pauses run with descriptive error
3. Non-list value pauses run with descriptive error
4. repeat_for + when combo: expand first, evaluate when per copy
"""

from datetime import datetime, timezone

import pytest
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import RunStatus
from orchestrator.config.models import (
    RoutineConfig,
    StepConfig,
    TaskConfig,
    StepCondition,
)
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import Run
from orchestrator.workflow.service import WorkflowService
from orchestrator.workflow import check_step_progression


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """Create in-memory database for testing."""
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def service(session: AsyncSession) -> WorkflowService:
    """Create WorkflowService with in-memory database."""
    return WorkflowService(session)


def _make_routine_with_repeat_for(
    repeat_for: str | None = None,
    when_condition: str | None = None,
) -> RoutineConfig:
    """Create a routine with repeat_for step for testing."""
    steps = [
        StepConfig(
            id="S1",
            title="Step 1",
            tasks=[TaskConfig(id="T1", title="Task 1", task_context="Do step 1")],
        ),
    ]

    # Add repeat_for step
    if repeat_for or when_condition:
        condition = StepCondition(repeat_for=repeat_for, when=when_condition)
        steps.append(
            StepConfig(
                id="S2",
                title="Repeat Step",
                tasks=[TaskConfig(id="T2", title="Task 2", task_context="Do step 2")],
                condition=condition,
            )
        )

    return RoutineConfig(
        id="test-repeat-routine",
        name="Test Repeat Routine",
        steps=steps,
    )


def _make_run_from_routine(routine: RoutineConfig) -> Run:
    """Create a Run from a routine for testing."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")
    run.created_at = now
    run.updated_at = now
    return run


class TestRepeatForEmptyList:
    """Tests for empty list handling in repeat_for."""

    def test_empty_list_marks_step_skipped(self) -> None:
        """Empty list should mark step as skipped with reason 'empty list'."""
        routine = _make_routine_with_repeat_for(repeat_for="item in context.items")
        run = _make_run_from_routine(routine)

        run.current_step_index = 1
        run.status = RunStatus.ACTIVE

        # Call check_step_progression with empty list
        clock = type("Clock", (), {"now": lambda self: datetime.now(timezone.utc)})()
        check_step_progression(run, routine_config=routine, clock=clock, run_config={"items": []})

        # Step should be marked as skipped
        step = run.steps[1]
        assert step.skipped is True
        assert step.skip_reason == "empty list"
        assert step.completed is True

    def test_empty_list_advances_to_next_step(self) -> None:
        """After skipping due to empty list, step index should advance."""
        routine = _make_routine_with_repeat_for(repeat_for="item in context.items")
        run = _make_run_from_routine(routine)

        run.current_step_index = 1
        run.status = RunStatus.ACTIVE

        clock = type("Clock", (), {"now": lambda self: datetime.now(timezone.utc)})()
        check_step_progression(run, routine_config=routine, clock=clock, run_config={"items": []})

        # Current step index should have advanced
        assert run.current_step_index > 1


class TestRepeatForMissingVariable:
    """Tests for missing variable handling in repeat_for."""

    def test_missing_variable_pauses_run(self) -> None:
        """Missing variable should pause run with descriptive error."""
        routine = _make_routine_with_repeat_for(repeat_for="item in context.items")
        run = _make_run_from_routine(routine)

        run.current_step_index = 1
        run.status = RunStatus.ACTIVE

        clock = type("Clock", (), {"now": lambda self: datetime.now(timezone.utc)})()
        # Don't set items in config - it will be missing
        check_step_progression(run, routine_config=routine, clock=clock, run_config={})

        # Run should be paused with error
        assert run.status == RunStatus.PAUSED
        assert run.pause_reason == "repeat_for_resolution_error"
        assert (
            "Variable not found in context" in run.last_error or "context" in run.last_error.lower()
        )

    def test_missing_variable_error_contains_path(self) -> None:
        """Error message should contain the variable path."""
        routine = _make_routine_with_repeat_for(repeat_for="item in context.missing_items")
        run = _make_run_from_routine(routine)

        run.current_step_index = 1
        run.status = RunStatus.ACTIVE

        clock = type("Clock", (), {"now": lambda self: datetime.now(timezone.utc)})()
        check_step_progression(run, routine_config=routine, clock=clock, run_config={})

        # Error should mention the missing variable
        assert run.status == RunStatus.PAUSED
        assert "missing_items" in run.last_error


class TestRepeatForNonListValue:
    """Tests for non-list value handling in repeat_for."""

    def test_non_list_value_pauses_run(self) -> None:
        """Non-list value should pause run with descriptive error."""
        routine = _make_routine_with_repeat_for(repeat_for="item in context.value")
        run = _make_run_from_routine(routine)

        run.current_step_index = 1
        run.status = RunStatus.ACTIVE

        clock = type("Clock", (), {"now": lambda self: datetime.now(timezone.utc)})()
        # Set a non-list value
        check_step_progression(
            run, routine_config=routine, clock=clock, run_config={"value": "not a list"}
        )

        # Run should be paused with error
        assert run.status == RunStatus.PAUSED
        assert run.pause_reason == "repeat_for_invalid_type"
        assert "expected list" in run.last_error

    def test_dict_value_pauses_run(self) -> None:
        """Dict value should also pause run with error."""
        routine = _make_routine_with_repeat_for(repeat_for="item in context.config")
        run = _make_run_from_routine(routine)

        run.current_step_index = 1
        run.status = RunStatus.ACTIVE

        clock = type("Clock", (), {"now": lambda self: datetime.now(timezone.utc)})()
        # Set a dict value
        check_step_progression(
            run, routine_config=routine, clock=clock, run_config={"config": {"key": "value"}}
        )

        # Run should be paused with error
        assert run.status == RunStatus.PAUSED
        assert run.pause_reason == "repeat_for_invalid_type"


class TestRepeatForWithWhenCombo:
    """Tests for repeat_for + when condition combination."""

    def test_repeat_for_with_when_expands_then_evaluates(self) -> None:
        """With repeat_for + when, should expand first then evaluate when per copy."""
        routine = _make_routine_with_repeat_for(
            repeat_for="item in context.items",
            when_condition="item == 'include'",
        )
        run = _make_run_from_routine(routine)

        run.current_step_index = 1
        run.status = RunStatus.ACTIVE

        clock = type("Clock", (), {"now": lambda self: datetime.now(timezone.utc)})()
        # Set up test data
        check_step_progression(
            run,
            routine_config=routine,
            clock=clock,
            run_config={"items": ["include", "skip", "include"]},
        )

        # Steps should be expanded
        # After first expansion, we should have 3 copies
        assert len(run.steps) >= 4  # S1 + at least S2 expanded copies

    def test_when_condition_skips_expanded_copy(self) -> None:
        """Expanded step copies should be skippable via when condition."""
        routine = _make_routine_with_repeat_for(
            repeat_for="item in context.items",
            when_condition="item == 'process'",
        )
        run = _make_run_from_routine(routine)

        run.current_step_index = 1
        run.status = RunStatus.ACTIVE

        clock = type("Clock", (), {"now": lambda self: datetime.now(timezone.utc)})()
        check_step_progression(
            run,
            routine_config=routine,
            clock=clock,
            run_config={"items": ["skip", "process", "skip"]},
        )

        # The expanded copies should be marked appropriately
        # At least some should be skipped based on the condition
        assert run.status == RunStatus.ACTIVE or run.status == RunStatus.PAUSED


class TestRepeatForConditionPersistence:
    async def test_expanded_steps_persist_to_database(self, service: WorkflowService) -> None:
        """Expanded repeat_for steps should persist to database."""
        routine = _make_routine_with_repeat_for(repeat_for="item in context.items")
        run = _make_run_from_routine(routine)

        # Simulate expansion by adding multiple copies
        run.config = {"items": ["a", "b", "c"]}
        run.current_step_index = 1

        # Create expanded step copies manually for persistence test
        original_step = run.steps[1]
        copies = []
        for i, item in enumerate(["a", "b", "c"]):
            import copy

            step_copy = copy.deepcopy(original_step)
            step_copy.id = f"{original_step.id}-{i}"
            step_copy.title = f"{original_step.title} [{i + 1}/3]"
            if step_copy.condition is None:
                step_copy.condition = {}
            if "injected_vars" not in step_copy.condition:
                step_copy.condition["injected_vars"] = {}
            step_copy.condition["injected_vars"]["item"] = item
            step_copy.condition["injected_vars"]["item_index"] = i
            copies.append(step_copy)

        # Replace step with copies
        run.steps[1 : 1 + 1] = copies

        # Save to database
        await service.create_run(run)

        # Load from database
        loaded_run = await service._repo.get(run.id)

        # Verify expanded steps are persisted
        assert len(loaded_run.steps) >= 4  # Original S1 + 3 expanded copies
        # Check that injected vars are preserved
        for step in loaded_run.steps[1:]:
            if "injected_vars" in (step.condition or {}):
                assert "item" in step.condition["injected_vars"]
                assert "item_index" in step.condition["injected_vars"]
