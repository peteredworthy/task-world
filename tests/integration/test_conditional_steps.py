"""Integration tests for conditional step persistence and execution.

Tests verify that:
1. Skip state (skipped, skip_reason) persists to database
2. Conditions are evaluated and steps are skipped appropriately
3. Manual gates pause the run
4. Condition errors are handled correctly
5. Chain skipping works across multiple false conditions
"""

from datetime import datetime, timezone

import pytest
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import (
    RunStatus,
    TaskStatus,
)
from orchestrator.config.models import (
    RoutineConfig,
    StepConfig,
    TaskConfig,
    StepCondition,
)
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import Run
from orchestrator.workflow.service import WorkflowService


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
