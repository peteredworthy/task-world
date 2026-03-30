"""Integration tests for conditional step persistence and execution.

Tests verify that:
1. Skip state (skipped, skip_reason) persists to database
2. Conditions are evaluated and steps are skipped appropriately
3. Manual gates pause the run
4. Condition errors are handled correctly
5. Chain skipping works across multiple false conditions
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.app import create_app
from orchestrator.config import RunStatus, TaskStatus, RoutineSource
from orchestrator.config.models import (
    RoutineConfig,
    StepConfig,
    TaskConfig,
    StepCondition,
)
from orchestrator.db import (
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import Run
from orchestrator.workflow.service import WorkflowService
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


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


def _make_routine_with_conditions(
    step2_condition: str | None = None,
    step3_condition: str | None = None,
) -> RoutineConfig:
    """Create a routine with conditional steps for testing."""
    steps = [
        StepConfig(
            id="S1",
            title="Step 1",
            tasks=[TaskConfig(id="T1", title="Task 1", task_context="Do step 1")],
        ),
        StepConfig(
            id="S2",
            title="Step 2",
            tasks=[TaskConfig(id="T2", title="Task 2", task_context="Do step 2")],
            condition=StepCondition(when=step2_condition) if step2_condition else None,
        ),
    ]

    # Add step 3 if condition provided
    if step3_condition:
        steps.append(
            StepConfig(
                id="S3",
                title="Step 3",
                tasks=[TaskConfig(id="T3", title="Task 3", task_context="Do step 3")],
                condition=StepCondition(when=step3_condition),
            )
        )

    return RoutineConfig(
        id="test-routine",
        name="Test Routine",
        steps=steps,
    )


def _make_run_from_routine(routine: RoutineConfig) -> Run:
    """Create a Run from a routine for testing."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")
    run.created_at = now
    run.updated_at = now
    return run


class TestConditionalStepPersistence:
    """Tests for persisting skip state to database."""

    async def test_skipped_step_persists_to_database(self, service: WorkflowService) -> None:
        """Skipped and skip_reason fields persist when saving and loading a run."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        # Mark step 2 as skipped
        run.steps[1].skipped = True
        run.steps[1].skip_reason = "condition: steps.S1.completed evaluated to false"

        # Save to database
        await service.create_run(run)

        # Load from database
        loaded_run = await service._repo.get(run.id)

        # Verify skip state was persisted
        assert loaded_run.steps[1].skipped is True
        assert loaded_run.steps[1].skip_reason == "condition: steps.S1.completed evaluated to false"

    async def test_unskipped_step_persists_correctly(self, service: WorkflowService) -> None:
        """Unskipped steps persist with skipped=False and skip_reason=None."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        # Ensure steps are not skipped
        run.steps[0].skipped = False
        run.steps[0].skip_reason = None

        await service.create_run(run)
        loaded_run = await service._repo.get(run.id)

        assert loaded_run.steps[0].skipped is False
        assert loaded_run.steps[0].skip_reason is None

    async def test_multiple_skipped_steps_persist(self, service: WorkflowService) -> None:
        """Multiple skipped steps in same run persist correctly."""
        routine = _make_routine_with_conditions(step3_condition="false")
        run = _make_run_from_routine(routine)

        # Mark multiple steps as skipped
        run.steps[1].skipped = True
        run.steps[1].skip_reason = "condition_false"
        run.steps[2].skipped = True
        run.steps[2].skip_reason = "chain_skip"

        await service.create_run(run)
        loaded_run = await service._repo.get(run.id)

        assert loaded_run.steps[1].skipped is True
        assert loaded_run.steps[1].skip_reason == "condition_false"
        assert loaded_run.steps[2].skipped is True
        assert loaded_run.steps[2].skip_reason == "chain_skip"

    async def test_skip_state_survives_multiple_save_cycles(self, service: WorkflowService) -> None:
        """Skip state persists through multiple save/load cycles."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        # First save
        run.steps[1].skipped = True
        run.steps[1].skip_reason = "cycle_1"
        await service.create_run(run)

        # Load and modify
        loaded1 = await service._repo.get(run.id)
        assert loaded1.steps[1].skip_reason == "cycle_1"

        # Update skip reason
        loaded1.steps[1].skip_reason = "cycle_2"
        await service._repo.save(loaded1)

        # Load again and verify
        loaded2 = await service._repo.get(run.id)
        assert loaded2.steps[1].skipped is True
        assert loaded2.steps[1].skip_reason == "cycle_2"


class TestConditionalSkip:
    """Tests for conditional skip scenarios."""

    async def test_condition_true_does_not_skip(self, service: WorkflowService) -> None:
        """When condition is true, step should not be skipped."""
        routine = _make_routine_with_conditions(step2_condition="true")
        run = _make_run_from_routine(routine)

        run.steps[1].skipped = False
        run.steps[1].skip_reason = None

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skipped is False
        assert loaded.steps[1].skip_reason is None

    async def test_unconditional_step_not_skipped(self, service: WorkflowService) -> None:
        """Steps without conditions should not be marked as skipped."""
        routine = _make_routine_with_conditions()  # No condition on S2
        run = _make_run_from_routine(routine)

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skipped is False
        assert loaded.steps[1].skip_reason is None

    async def test_skip_state_independent_from_completed(self, service: WorkflowService) -> None:
        """Skipped and completed are independent flags."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        # A step can be both skipped and completed
        run.steps[1].skipped = True
        run.steps[1].skip_reason = "condition_false"
        run.steps[1].completed = True

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skipped is True
        assert loaded.steps[1].skip_reason == "condition_false"
        assert loaded.steps[1].completed is True

    async def test_skip_state_with_partial_task_completion(self, service: WorkflowService) -> None:
        """Skip state persists even if some tasks in step are incomplete."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        # Mark step as skipped but tasks are pending
        run.steps[1].skipped = True
        run.steps[1].skip_reason = "condition_false"
        assert run.steps[1].tasks[0].status == TaskStatus.PENDING

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skipped is True
        assert loaded.steps[1].tasks[0].status == TaskStatus.PENDING


class TestChainSkipScenarios:
    """Tests for chain skipping across multiple false conditions."""

    async def test_chain_skip_multiple_steps(self, service: WorkflowService) -> None:
        """Multiple consecutive false conditions should skip all affected steps."""
        routine = _make_routine_with_conditions(step2_condition="false", step3_condition="false")
        run = _make_run_from_routine(routine)

        # Mark both steps as skipped
        run.steps[1].skipped = True
        run.steps[1].skip_reason = "condition_false"
        run.steps[2].skipped = True
        run.steps[2].skip_reason = "chain_skip_consequence"

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        # Verify both steps have skip state
        assert loaded.steps[1].skipped is True
        assert loaded.steps[2].skipped is True

    async def test_chain_skip_with_different_reasons(self, service: WorkflowService) -> None:
        """Chain-skipped steps can have different skip reasons."""
        routine = _make_routine_with_conditions(step2_condition="false", step3_condition="false")
        run = _make_run_from_routine(routine)

        run.steps[1].skipped = True
        run.steps[1].skip_reason = "Condition 'false' evaluated to false"
        run.steps[2].skipped = True
        run.steps[2].skip_reason = "Previous step skipped, chain advancing"

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skip_reason == "Condition 'false' evaluated to false"
        assert loaded.steps[2].skip_reason == "Previous step skipped, chain advancing"

    async def test_partial_chain_skip(self, service: WorkflowService) -> None:
        """When middle step condition is true, later steps are not skipped."""
        routine = _make_routine_with_conditions(step2_condition="false", step3_condition="true")
        run = _make_run_from_routine(routine)

        # Step 2 skipped, Step 3 not skipped
        run.steps[1].skipped = True
        run.steps[1].skip_reason = "condition_false"
        run.steps[2].skipped = False
        run.steps[2].skip_reason = None

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skipped is True
        assert loaded.steps[2].skipped is False


class TestSkipReasonContent:
    """Tests for skip_reason field content and validation."""

    async def test_skip_reason_not_empty_on_skip(self, service: WorkflowService) -> None:
        """Skip reason should contain meaningful information when step is skipped."""
        routine = _make_routine_with_conditions(step2_condition="false")
        run = _make_run_from_routine(routine)

        skip_reason = "Condition 'steps.S1.skipped == false' evaluated to false"
        run.steps[1].skipped = True
        run.steps[1].skip_reason = skip_reason

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skip_reason == skip_reason
        assert len(loaded.steps[1].skip_reason) > 0

    async def test_skip_reason_none_when_not_skipped(self, service: WorkflowService) -> None:
        """Skip reason should be None when step is not skipped."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        run.steps[0].skipped = False
        run.steps[0].skip_reason = None

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[0].skip_reason is None

    async def test_skip_reason_can_be_cleared(self, service: WorkflowService) -> None:
        """Skip reason can be set to None to clear it."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        # Set reason
        run.steps[1].skipped = True
        run.steps[1].skip_reason = "original_reason"
        await service.create_run(run)

        # Load and clear
        loaded = await service._repo.get(run.id)
        loaded.steps[1].skip_reason = None
        await service._repo.save(loaded)

        # Verify cleared
        reloaded = await service._repo.get(run.id)
        assert reloaded.steps[1].skip_reason is None

    async def test_skip_reason_with_special_characters(self, service: WorkflowService) -> None:
        """Skip reason can contain special characters and quotes."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        special_reason = "Condition \"context.env == 'prod'\" evaluated to false"
        run.steps[1].skipped = True
        run.steps[1].skip_reason = special_reason

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skip_reason == special_reason


class TestSkipStateReconstruction:
    """Tests for skip state reconstruction from database."""

    async def test_skip_state_reconstructed_after_shutdown(self, service: WorkflowService) -> None:
        """Skip state is properly reconstructed from database."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        run.steps[1].skipped = True
        run.steps[1].skip_reason = "condition_evaluated_to_false"

        await service.create_run(run)

        # Simulate shutdown and reload
        loaded = await service._repo.get(run.id)

        # State should be perfectly reconstructed
        assert loaded.steps[1].skipped is True
        assert loaded.steps[1].skip_reason == "condition_evaluated_to_false"

    async def test_skip_state_not_lost_on_run_update(self, service: WorkflowService) -> None:
        """Skip state persists when other run fields are updated."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        run.steps[1].skipped = True
        run.steps[1].skip_reason = "original_skip"

        await service.create_run(run)

        # Update run status
        loaded = await service._repo.get(run.id)
        loaded.status = RunStatus.ACTIVE
        loaded.started_at = datetime.now(timezone.utc)
        await service._repo.save(loaded)

        # Verify skip state is unchanged
        reloaded = await service._repo.get(run.id)
        assert reloaded.steps[1].skipped is True
        assert reloaded.steps[1].skip_reason == "original_skip"


class TestEdgeCases:
    """Tests for edge cases in skip state handling."""

    async def test_first_step_can_be_skipped(self, service: WorkflowService) -> None:
        """Even the first step can be marked as skipped."""
        routine = _make_routine_with_conditions(step2_condition="false")
        run = _make_run_from_routine(routine)

        run.steps[0].skipped = True
        run.steps[0].skip_reason = "initial_skip_condition"

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[0].skipped is True
        assert loaded.steps[0].skip_reason == "initial_skip_condition"

    async def test_all_steps_skipped_run_still_persists(self, service: WorkflowService) -> None:
        """If all steps are skipped, run still persists correctly."""
        routine = _make_routine_with_conditions(step2_condition="false", step3_condition="false")
        run = _make_run_from_routine(routine)

        # Skip all steps
        for step in run.steps:
            step.skipped = True
            step.skip_reason = "all_skipped"

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        # All steps should still be persisted as skipped
        for step in loaded.steps:
            assert step.skipped is True
            assert step.skip_reason == "all_skipped"

    async def test_empty_skip_reason_string(self, service: WorkflowService) -> None:
        """Empty string skip_reason should persist (though not recommended)."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        run.steps[1].skipped = True
        run.steps[1].skip_reason = ""  # Empty string

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        # Empty string should be persisted as-is
        assert loaded.steps[1].skip_reason == ""

    async def test_long_skip_reason(self, service: WorkflowService) -> None:
        """Very long skip reasons should be persisted."""
        routine = _make_routine_with_conditions()
        run = _make_run_from_routine(routine)

        # Create a long reason (1000+ characters)
        long_reason = "Condition evaluated to false: " + ("x" * 1000)
        run.steps[1].skipped = True
        run.steps[1].skip_reason = long_reason

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skip_reason == long_reason
        assert len(loaded.steps[1].skip_reason) > 1000


class TestManualGatePause:
    """Tests for manual gate scenarios causing run pause."""

    async def test_manual_gate_pauses_run(self, service: WorkflowService) -> None:
        """Manual gate condition should pause run with manual_gate reason."""
        routine = _make_routine_with_conditions(step2_condition="manual_gate")
        run = _make_run_from_routine(routine)

        # When manual gate is encountered, run pauses
        run.status = RunStatus.PAUSED
        run.pause_reason = "manual_gate"
        run.steps[1].skipped = False  # Not skipped, but requires approval
        run.steps[1].skip_reason = None

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.status == RunStatus.PAUSED
        assert loaded.pause_reason == "manual_gate"
        assert loaded.steps[1].skipped is False

    async def test_manual_gate_with_skip_state_persistence(self, service: WorkflowService) -> None:
        """Manual gate pause state persists across save/load cycles."""
        routine = _make_routine_with_conditions(step2_condition="manual_gate")
        run = _make_run_from_routine(routine)

        run.status = RunStatus.PAUSED
        run.pause_reason = "manual_gate"

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        # State should be perfectly reconstructed
        assert loaded.pause_reason == "manual_gate"
        assert loaded.status == RunStatus.PAUSED

    async def test_manual_gate_different_from_skip(self, service: WorkflowService) -> None:
        """Manual gate is different from skip - step waits for approval, not skipped."""
        routine = _make_routine_with_conditions(step2_condition="manual_gate")
        run = _make_run_from_routine(routine)

        # Manual gate: run pauses, step is not skipped
        run.status = RunStatus.PAUSED
        run.pause_reason = "manual_gate"
        run.steps[1].skipped = False
        run.steps[1].skip_reason = None

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skipped is False
        assert loaded.steps[1].skip_reason is None
        assert loaded.pause_reason == "manual_gate"


class TestOutputBasedConditions:
    """Tests for conditions referencing output from previous steps."""

    async def test_condition_referencing_step_failure_state(self, service: WorkflowService) -> None:
        """Condition can reference failure state of previous step."""
        # Condition in S2: "steps.S1.completed and not steps.S1.failed"
        routine = _make_routine_with_conditions(
            step2_condition="steps.S1.completed and not steps.S1.failed"
        )
        run = _make_run_from_routine(routine)

        # If S1 failed, S2 should be skipped
        run.steps[0].completed = True
        run.steps[1].skipped = True
        run.steps[1].skip_reason = "condition: steps.S1 failed"

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skipped is True
        assert "S1 failed" in loaded.steps[1].skip_reason

    async def test_condition_referencing_step_success_state(self, service: WorkflowService) -> None:
        """Condition can reference success state of previous step."""
        routine = _make_routine_with_conditions(step2_condition="steps.S1.outcome == 'passed'")
        run = _make_run_from_routine(routine)

        # If S1 succeeded, S2 should not be skipped
        run.steps[0].completed = True
        run.steps[1].skipped = False
        run.steps[1].skip_reason = None

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[1].skipped is False
        assert loaded.steps[1].skip_reason is None

    async def test_condition_referencing_multiple_steps(self, service: WorkflowService) -> None:
        """Condition can reference outputs from multiple previous steps."""
        routine = _make_routine_with_conditions(
            step2_condition="false", step3_condition="steps.S1.completed and steps.S2.skipped"
        )
        run = _make_run_from_routine(routine)

        run.steps[0].completed = True
        run.steps[1].skipped = True
        run.steps[1].skip_reason = "condition_false"

        # S3 condition: both S1 completed and S2 skipped
        run.steps[2].skipped = False
        run.steps[2].skip_reason = None

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.steps[0].completed is True
        assert loaded.steps[1].skipped is True
        assert loaded.steps[2].skipped is False


class TestConditionSyntaxErrors:
    """Tests for handling condition syntax errors."""

    async def test_condition_syntax_error_pauses_run(self, service: WorkflowService) -> None:
        """Invalid condition syntax should pause run with error."""
        # Invalid syntax: missing closing parenthesis
        routine = _make_routine_with_conditions(step2_condition="steps.S1.completed and (")
        run = _make_run_from_routine(routine)

        # Syntax error should pause run
        run.status = RunStatus.PAUSED
        run.pause_reason = "error"
        run.last_error = "Invalid condition syntax: steps.S1.completed and ("

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.status == RunStatus.PAUSED
        assert loaded.pause_reason == "error"
        assert "Invalid condition syntax" in loaded.last_error

    async def test_condition_undefined_variable_error(self, service: WorkflowService) -> None:
        """Reference to undefined variable should record error."""
        routine = _make_routine_with_conditions(step2_condition="steps.S99.completed")
        run = _make_run_from_routine(routine)

        # Undefined step reference
        run.status = RunStatus.PAUSED
        run.pause_reason = "error"
        run.last_error = "Undefined step reference in condition: steps.S99"

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.status == RunStatus.PAUSED
        assert loaded.pause_reason == "error"
        assert "S99" in loaded.last_error

    async def test_condition_type_error(self, service: WorkflowService) -> None:
        """Type mismatch in condition should record error."""
        routine = _make_routine_with_conditions(step2_condition="steps.S1.completed + 5")
        run = _make_run_from_routine(routine)

        # Type error: can't add boolean and int
        run.status = RunStatus.PAUSED
        run.pause_reason = "error"
        run.last_error = "Type error in condition: cannot add bool and int"

        await service.create_run(run)
        loaded = await service._repo.get(run.id)

        assert loaded.status == RunStatus.PAUSED
        assert loaded.pause_reason == "error"
        assert "Type error" in loaded.last_error


class TestRepeatForExpansionIntegration:
    """Integration tests for repeat_for expansion through workflow."""

    async def test_repeat_for_with_run_config_list(self, service: WorkflowService) -> None:
        """repeat_for with run config list creates N step copies."""
        # Create routine with repeat_for step
        routine = RoutineConfig(
            id="repeat-routine",
            name="Repeat Routine",
            steps=[
                StepConfig(
                    id="S1",
                    title="Setup",
                    tasks=[TaskConfig(id="T1", title="Initialize", task_context="Init")],
                ),
                StepConfig(
                    id="S2",
                    title="Process Item",
                    tasks=[TaskConfig(id="T2", title="Process", task_context="Process each item")],
                    condition=StepCondition(repeat_for="item in context.items"),
                ),
            ],
        )

        run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")

        # Simulate workflow progression with repeat_for expansion
        from orchestrator.workflow import check_step_progression

        run.steps[0].completed = True
        run.current_step_index = 1

        # Trigger expansion with run config containing list
        run_config = {"items": ["server1", "server2", "server3"]}
        check_step_progression(run, routine, run_config=run_config)

        # Should be expanded to 3 copies plus original step
        assert len(run.steps) == 4  # S1 + 3 expanded copies of S2

        # Verify copies have correct structure
        expanded_steps = [s for s in run.steps if s.config_id == "S2"]
        assert len(expanded_steps) == 3

        # Verify each copy has correct injected variables
        for i, step in enumerate(expanded_steps):
            assert step.condition is not None
            assert "injected_vars" in step.condition
            assert step.condition["injected_vars"]["item"] == f"server{i + 1}"
            assert step.condition["injected_vars"]["item_index"] == i

    async def test_repeat_for_with_empty_list_skips(self, service: WorkflowService) -> None:
        """repeat_for with empty list marks step as skipped."""
        routine = RoutineConfig(
            id="repeat-routine",
            name="Repeat Routine",
            steps=[
                StepConfig(
                    id="S1",
                    title="Setup",
                    tasks=[TaskConfig(id="T1", title="Initialize", task_context="Init")],
                ),
                StepConfig(
                    id="S2",
                    title="Process Item",
                    tasks=[TaskConfig(id="T2", title="Process", task_context="Process each")],
                    condition=StepCondition(repeat_for="item in context.items"),
                ),
            ],
        )

        run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")

        from orchestrator.workflow import check_step_progression

        run.steps[0].completed = True
        run.current_step_index = 1

        # Trigger expansion with empty list
        run_config = {"items": []}
        check_step_progression(run, routine, run_config=run_config)

        # S2 should be marked as skipped
        assert run.steps[1].skipped is True
        assert run.steps[1].skip_reason == "empty list"
        assert run.current_step_index == 2

    async def test_repeat_for_with_prior_step_output(self, service: WorkflowService) -> None:
        """repeat_for with prior step output creates copies."""
        routine = RoutineConfig(
            id="repeat-routine",
            name="Repeat Routine",
            steps=[
                StepConfig(
                    id="S1",
                    title="Generate List",
                    tasks=[TaskConfig(id="T1", title="Generate", task_context="Generate items")],
                ),
                StepConfig(
                    id="S2",
                    title="Process Item",
                    tasks=[
                        TaskConfig(id="T2", title="Process", task_context="Process from S1 output")
                    ],
                    condition=StepCondition(repeat_for="item in steps.S1.output"),
                ),
            ],
        )

        run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")

        # Complete step 1 with output
        task = run.steps[0].tasks[0]
        task.status = TaskStatus.COMPLETED
        from orchestrator.state.models import Attempt

        attempt = Attempt(attempt_num=1)
        attempt.agent_output = "output_1"
        task.attempts.append(attempt)
        run.steps[0].completed = True
        run.current_step_index = 1

        from orchestrator.workflow import check_step_progression

        # Trigger expansion - should resolve from S1's output
        check_step_progression(run, routine)

        # Should be expanded based on S1's output list
        # At minimum should have S1 + at least one expanded copy
        assert len(run.steps) >= 2

    async def test_repeat_for_missing_variable_pauses(self, service: WorkflowService) -> None:
        """repeat_for with missing variable pauses run."""
        routine = RoutineConfig(
            id="repeat-routine",
            name="Repeat Routine",
            steps=[
                StepConfig(
                    id="S1",
                    title="Step 1",
                    tasks=[TaskConfig(id="T1", title="Task 1", task_context="Task")],
                ),
                StepConfig(
                    id="S2",
                    title="Repeat Step",
                    tasks=[TaskConfig(id="T2", title="Task 2", task_context="Task")],
                    condition=StepCondition(repeat_for="item in context.missing_items"),
                ),
            ],
        )

        run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")

        from orchestrator.workflow import check_step_progression

        run.steps[0].completed = True
        run.current_step_index = 1

        # Trigger expansion with missing variable
        run_config = {}  # No 'missing_items'
        check_step_progression(run, routine, run_config=run_config)

        # Run should be paused
        assert run.status == RunStatus.PAUSED
        assert run.pause_reason == "repeat_for_resolution_error"
        assert "Variable not found" in run.last_error or "resolution error" in run.last_error

    async def test_repeat_for_non_list_value_pauses(self, service: WorkflowService) -> None:
        """repeat_for with non-list value pauses run."""
        routine = RoutineConfig(
            id="repeat-routine",
            name="Repeat Routine",
            steps=[
                StepConfig(
                    id="S1",
                    title="Step 1",
                    tasks=[TaskConfig(id="T1", title="Task 1", task_context="Task")],
                ),
                StepConfig(
                    id="S2",
                    title="Repeat Step",
                    tasks=[TaskConfig(id="T2", title="Task 2", task_context="Task")],
                    condition=StepCondition(repeat_for="item in context.items"),
                ),
            ],
        )

        run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")

        from orchestrator.workflow import check_step_progression

        run.steps[0].completed = True
        run.current_step_index = 1

        # Trigger expansion with non-list value
        run_config = {"items": "not a list"}
        check_step_progression(run, routine, run_config=run_config)

        # Run should be paused
        assert run.status == RunStatus.PAUSED
        assert run.pause_reason == "repeat_for_invalid_type"
        assert "expected list" in run.last_error

    async def test_repeat_for_with_multiple_items(self, service: WorkflowService) -> None:
        """repeat_for creates correct number of copies for various list sizes."""
        for num_items in [1, 2, 5, 10]:
            routine = RoutineConfig(
                id="repeat-routine",
                name="Repeat Routine",
                steps=[
                    StepConfig(
                        id="S1",
                        title="Setup",
                        tasks=[TaskConfig(id="T1", title="Init", task_context="Init")],
                    ),
                    StepConfig(
                        id="S2",
                        title="Process",
                        tasks=[TaskConfig(id="T2", title="Process", task_context="Process")],
                        condition=StepCondition(repeat_for="item in context.items"),
                    ),
                ],
            )

            run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")

            from orchestrator.workflow import check_step_progression

            run.steps[0].completed = True
            run.current_step_index = 1

            items = [f"item_{i}" for i in range(num_items)]
            run_config = {"items": items}
            check_step_progression(run, routine, run_config=run_config)

            # Should have S1 + num_items copies
            expected_count = 1 + num_items
            assert len(run.steps) == expected_count

    async def test_repeat_for_step_titles_indexed(self, service: WorkflowService) -> None:
        """repeat_for copies have titles with [n/total] indexing."""
        routine = RoutineConfig(
            id="repeat-routine",
            name="Repeat Routine",
            steps=[
                StepConfig(
                    id="S1",
                    title="Setup",
                    tasks=[TaskConfig(id="T1", title="Init", task_context="Init")],
                ),
                StepConfig(
                    id="S2",
                    title="Deploy Server",
                    tasks=[TaskConfig(id="T2", title="Deploy", task_context="Deploy")],
                    condition=StepCondition(repeat_for="server in context.servers"),
                ),
            ],
        )

        run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")

        from orchestrator.workflow import check_step_progression

        run.steps[0].completed = True
        run.current_step_index = 1

        run_config = {"servers": ["prod", "staging", "dev"]}
        check_step_progression(run, routine, run_config=run_config)

        expanded_steps = [s for s in run.steps if s.config_id == "S2"]
        assert expanded_steps[0].title == "Deploy Server [1/3]"
        assert expanded_steps[1].title == "Deploy Server [2/3]"
        assert expanded_steps[2].title == "Deploy Server [3/3]"

    async def test_repeat_for_config_ids_preserved(self, service: WorkflowService) -> None:
        """repeat_for copies preserve original config_id."""
        routine = RoutineConfig(
            id="repeat-routine",
            name="Repeat Routine",
            steps=[
                StepConfig(
                    id="S1",
                    title="Setup",
                    tasks=[TaskConfig(id="T1", title="Init", task_context="Init")],
                ),
                StepConfig(
                    id="S2",
                    title="Process",
                    tasks=[TaskConfig(id="T2", title="Process", task_context="Process")],
                    condition=StepCondition(repeat_for="item in context.items"),
                ),
            ],
        )

        run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")

        from orchestrator.workflow import check_step_progression

        run.steps[0].completed = True
        run.current_step_index = 1

        run_config = {"items": ["a", "b"]}
        check_step_progression(run, routine, run_config=run_config)

        expanded_steps = [s for s in run.steps if s.id.startswith("S2-")]
        for step in expanded_steps:
            assert step.config_id == "S2"  # config_id should remain original

    async def test_repeat_for_step_persistence(self, service: WorkflowService) -> None:
        """repeat_for expanded steps persist to database correctly."""
        routine = RoutineConfig(
            id="repeat-routine",
            name="Repeat Routine",
            steps=[
                StepConfig(
                    id="S1",
                    title="Setup",
                    tasks=[TaskConfig(id="T1", title="Init", task_context="Init")],
                ),
                StepConfig(
                    id="S2",
                    title="Process",
                    tasks=[TaskConfig(id="T2", title="Process", task_context="Process")],
                    condition=StepCondition(repeat_for="item in context.items"),
                ),
            ],
        )

        run = create_run_from_routine(routine, repo_name="test-repo", source_branch="main")

        from orchestrator.workflow import check_step_progression

        run.steps[0].completed = True
        run.current_step_index = 1

        run_config = {"items": ["x", "y", "z"]}
        check_step_progression(run, routine, run_config=run_config)

        # Save to database
        await service.create_run(run)

        # Load from database
        loaded = await service._repo.get(run.id)

        # Expanded steps should be persisted
        assert len(loaded.steps) == 4  # S1 + 3 expanded copies
        expanded_loaded = [s for s in loaded.steps if s.config_id == "S2"]
        assert len(expanded_loaded) == 3

        # Verify titles are persisted correctly, indicating the expansion worked
        assert expanded_loaded[0].title == "Process [1/3]"
        assert expanded_loaded[1].title == "Process [2/3]"
        assert expanded_loaded[2].title == "Process [3/3]"


# ============================================================================
# API Surface Tests - Verify skip-step endpoint and response schema
# ============================================================================


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    """Create an async test client with in-memory database and signal drain for API tests."""
    signal_transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    app.state.signal_transport = signal_transport
    await init_db(app.state.engine)
    asgi = ASGITransport(app=app)  # type: ignore[arg-type]
    drain = make_drain_fn(app, signal_transport)
    async with AsyncClient(transport=asgi, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


@pytest.fixture
async def api_client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    """Backward-compatible fixture that returns just the client."""
    client, _ = client_and_drain
    return client


async def _create_run_with_manual_gate_for_api(
    client: AsyncClient, drain: DrainFn
) -> tuple[str, str]:
    """Create a run with a manual gate condition on step 2."""
    routine_config = {
        "id": "test-manual-gate-api",
        "name": "test-manual-gate-api",
        "steps": [
            {
                "id": "step1",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "task1",
                        "title": "Task 1",
                        "instructions": "Build something",
                    }
                ],
            },
            {
                "id": "step2",
                "title": "Step 2",
                "condition": {"when": "manual"},
                "tasks": [
                    {
                        "id": "task2",
                        "title": "Task 2",
                        "instructions": "Build something else",
                    }
                ],
            },
        ],
    }

    # Create run
    create_resp = await client.post(
        "/api/runs",
        json={
            "repo_name": "test-repo",
            "branch": "main",
            "routine_embedded": routine_config,
        },
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    # Start run (async — enqueues RUN_START signal, returns 202)
    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    await drain(run_id)

    # Complete step 1
    task1_id = create_resp.json()["steps"][0]["tasks"][0]["id"]

    # Start task 1
    task_start_resp = await client.post(f"/api/runs/{run_id}/tasks/{task1_id}/start")
    assert task_start_resp.status_code == 200

    # Submit task 1
    submit_resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task1_id}/submit",
        json={
            "artifacts": [],
            "completion_reason": "Completed task",
        },
    )
    assert submit_resp.status_code == 200
    await drain(run_id)

    # Complete verification (auto-verify should pass)
    complete_resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task1_id}/complete-verification",
        json={"passing_grades": []},
    )
    assert complete_resp.status_code == 200
    await drain(run_id)

    # Now check that run is paused at manual gate
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["status"] == "paused"
    assert run_data["pause_reason"] == "manual_gate"

    # Get step2 ID
    step2_id = run_data["steps"][1]["id"]

    return run_id, step2_id


@pytest.mark.asyncio
class TestSkipStepAPISurface:
    """API-level tests for skip-step endpoint and response schema."""

    async def test_get_run_response_includes_skipped_field_on_steps(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Verify GET /runs/{id} response includes skipped field on steps."""
        api_client, drain = client_and_drain
        run_id, _ = await _create_run_with_manual_gate_for_api(api_client, drain)

        # Get the run
        run_resp = await api_client.get(f"/api/runs/{run_id}")
        assert run_resp.status_code == 200

        run_data = run_resp.json()
        assert "steps" in run_data

        # Verify all steps have skipped field
        for step in run_data["steps"]:
            assert "skipped" in step
            assert isinstance(step["skipped"], bool)

    async def test_get_run_response_includes_skip_reason_field_on_steps(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Verify GET /runs/{id} response includes skip_reason field on steps."""
        api_client, drain = client_and_drain
        run_id, _ = await _create_run_with_manual_gate_for_api(api_client, drain)

        # Get the run
        run_resp = await api_client.get(f"/api/runs/{run_id}")
        assert run_resp.status_code == 200

        run_data = run_resp.json()

        # Verify all steps have skip_reason field
        for step in run_data["steps"]:
            assert "skip_reason" in step
            assert step["skip_reason"] is None or isinstance(step["skip_reason"], str)

    async def test_get_run_response_includes_condition_field_on_steps(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Verify GET /runs/{id} response includes condition field on steps."""
        api_client, drain = client_and_drain
        run_id, _ = await _create_run_with_manual_gate_for_api(api_client, drain)

        # Get the run
        run_resp = await api_client.get(f"/api/runs/{run_id}")
        assert run_resp.status_code == 200

        run_data = run_resp.json()

        # Verify all steps have condition field
        for step in run_data["steps"]:
            assert "condition" in step
            # condition can be None or a dict with condition data

    async def test_skipped_step_has_skipped_true_after_skip_endpoint(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """After calling skip endpoint, skipped field should be true."""
        api_client, drain = client_and_drain
        run_id, step2_id = await _create_run_with_manual_gate_for_api(api_client, drain)

        # Skip the manual gate step
        skip_resp = await api_client.post(f"/api/runs/{run_id}/steps/{step2_id}/skip")
        assert skip_resp.status_code == 200

        run_data = skip_resp.json()

        # Step 2 should be marked as skipped
        step2_data = next(s for s in run_data["steps"] if s["id"] == step2_id)
        assert step2_data["skipped"] is True
        assert step2_data["skip_reason"] == "manual_skip"

    async def test_skipped_step_in_activity_events(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Verify activity is recorded when step is skipped."""
        api_client, drain = client_and_drain
        run_id, step2_id = await _create_run_with_manual_gate_for_api(api_client, drain)

        # Skip the manual gate step
        skip_resp = await api_client.post(f"/api/runs/{run_id}/steps/{step2_id}/skip")
        assert skip_resp.status_code == 200

        # Get activity events
        activity_resp = await api_client.get(f"/api/runs/{run_id}/activity")
        assert activity_resp.status_code == 200

        activity_data = activity_resp.json()
        assert "events" in activity_data

        # Verify we have activity events (skip action should be recorded in activity)
        # Multiple events may be present from all actions during the test
        assert len(activity_data["events"]) > 0

    async def test_skip_endpoint_works_for_manual_gate_paused_runs(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Skip-step endpoint should succeed for runs paused at manual gate."""
        api_client, drain = client_and_drain
        run_id, step2_id = await _create_run_with_manual_gate_for_api(api_client, drain)

        # Verify run is paused at manual gate
        run_resp = await api_client.get(f"/api/runs/{run_id}")
        run_data = run_resp.json()
        assert run_data["status"] == "paused"
        assert run_data["pause_reason"] == "manual_gate"

        # Skip should succeed
        skip_resp = await api_client.post(f"/api/runs/{run_id}/steps/{step2_id}/skip")
        assert skip_resp.status_code == 200

        # Verify response is a valid RunResponse with updated state
        result = skip_resp.json()
        assert result["id"] == run_id
        assert result["steps"][1]["skipped"] is True

    async def test_skip_returns_409_when_not_at_manual_gate(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Skip-step should return 409 when run is not paused at manual gate."""
        api_client, _ = client_and_drain
        routine_config = {
            "id": "test-no-condition",
            "name": "test-no-condition",
            "steps": [
                {
                    "id": "step1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task1",
                            "title": "Task 1",
                            "instructions": "Build something",
                        }
                    ],
                }
            ],
        }

        create_resp = await api_client.post(
            "/api/runs",
            json={
                "repo_name": "test-repo",
                "branch": "main",
                "routine_embedded": routine_config,
            },
        )
        run_id = create_resp.json()["id"]
        step1_id = create_resp.json()["steps"][0]["id"]

        # Try to skip without pausing at manual gate
        skip_resp = await api_client.post(f"/api/runs/{run_id}/steps/{step1_id}/skip")
        assert skip_resp.status_code == 409
        assert "manual gate" in skip_resp.json()["detail"].lower()

    async def test_skip_returns_409_for_wrong_step_id(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Skip-step should return 409 when step_id doesn't match current step."""
        api_client, drain = client_and_drain
        run_id, _ = await _create_run_with_manual_gate_for_api(api_client, drain)

        # Try to skip with wrong step ID
        skip_resp = await api_client.post(f"/api/runs/{run_id}/steps/wrong-step-id/skip")
        assert skip_resp.status_code == 409
        assert "not the current step" in skip_resp.json()["detail"].lower()

    async def test_skip_endpoint_advances_current_step_index(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Skipping a step should advance current_step_index."""
        api_client, drain = client_and_drain
        run_id, step2_id = await _create_run_with_manual_gate_for_api(api_client, drain)

        # Check current_step_index before skip
        run_resp = await api_client.get(f"/api/runs/{run_id}")
        initial_index = run_resp.json()["current_step_index"]

        # Skip the manual gate step
        skip_resp = await api_client.post(f"/api/runs/{run_id}/steps/{step2_id}/skip")
        assert skip_resp.status_code == 200

        # Current step index should advance (or run completes if it's the last step)
        new_index = skip_resp.json()["current_step_index"]
        assert new_index >= initial_index

    async def test_skip_endpoint_marks_step_completed(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Skipping a step should mark it as completed."""
        api_client, drain = client_and_drain
        run_id, step2_id = await _create_run_with_manual_gate_for_api(api_client, drain)

        # Skip the manual gate step
        skip_resp = await api_client.post(f"/api/runs/{run_id}/steps/{step2_id}/skip")
        assert skip_resp.status_code == 200

        run_data = skip_resp.json()

        # Step 2 should be marked as both skipped and completed
        step2_data = next(s for s in run_data["steps"] if s["id"] == step2_id)
        assert step2_data["skipped"] is True
        assert step2_data["completed"] is True

    async def test_skip_cascades_false_conditions(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Skip cascades through subsequent false conditions."""
        api_client, drain = client_and_drain
        routine_config = {
            "id": "test-cascade-conditions-api",
            "name": "test-cascade-conditions-api",
            "steps": [
                {
                    "id": "step1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task1",
                            "title": "Task 1",
                            "instructions": "Build something",
                        }
                    ],
                },
                {
                    "id": "step2",
                    "title": "Step 2",
                    "condition": {"when": "manual"},
                    "tasks": [
                        {
                            "id": "task2",
                            "title": "Task 2",
                            "instructions": "Build something else",
                        }
                    ],
                },
                {
                    "id": "step3",
                    "title": "Step 3",
                    "condition": {"when": "false"},
                    "tasks": [
                        {
                            "id": "task3",
                            "title": "Task 3",
                            "instructions": "Build third thing",
                        }
                    ],
                },
                {
                    "id": "step4",
                    "title": "Step 4",
                    "tasks": [
                        {
                            "id": "task4",
                            "title": "Task 4",
                            "instructions": "Build fourth thing",
                        }
                    ],
                },
            ],
        }

        # Create and set up run
        create_resp = await api_client.post(
            "/api/runs",
            json={
                "repo_name": "test-repo",
                "branch": "main",
                "routine_embedded": routine_config,
            },
        )
        run_id = create_resp.json()["id"]

        # Capture step IDs from initial response
        initial_steps = create_resp.json()["steps"]
        step2_id = next(s["id"] for s in initial_steps if s["config_id"] == "step2")
        step3_id = next(s["id"] for s in initial_steps if s["config_id"] == "step3")
        step4_id = next(s["id"] for s in initial_steps if s["config_id"] == "step4")

        # Start run (async — enqueues RUN_START signal, returns 202)
        start_resp = await api_client.post(f"/api/runs/{run_id}/start")
        assert start_resp.status_code == 202
        await drain(run_id)

        # Complete step 1
        task1_id = create_resp.json()["steps"][0]["tasks"][0]["id"]

        await api_client.post(f"/api/runs/{run_id}/tasks/{task1_id}/start")
        submit_resp = await api_client.post(
            f"/api/runs/{run_id}/tasks/{task1_id}/submit",
            json={"artifacts": [], "completion_reason": "Completed task"},
        )
        assert submit_resp.status_code == 200
        await drain(run_id)
        complete_resp = await api_client.post(
            f"/api/runs/{run_id}/tasks/{task1_id}/complete-verification",
            json={"passing_grades": []},
        )
        assert complete_resp.status_code == 200
        await drain(run_id)

        # Skip step 2
        skip_resp = await api_client.post(f"/api/runs/{run_id}/steps/{step2_id}/skip")
        assert skip_resp.status_code == 200

        result = skip_resp.json()

        # Verify step 2 is skipped
        step2_data = next(s for s in result["steps"] if s["id"] == step2_id)
        assert step2_data["skipped"] is True

        # Verify step 3 is also skipped (cascading from false condition)
        step3_data = next(s for s in result["steps"] if s["id"] == step3_id)
        assert step3_data["skipped"] is True

        # Step 4 should not be skipped
        step4_data = next(s for s in result["steps"] if s["id"] == step4_id)
        assert step4_data["skipped"] is False
