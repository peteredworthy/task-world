# Step Plan: Engine Wiring

## Purpose

Wire condition evaluation into the workflow engine so steps are actually skipped or paused (manual gate) based on their conditions. This is the core integration that makes conditional steps functional at runtime.

## Prerequisites

- **Step 1** (Safe Evaluator) -- `ConditionEvaluator`, `StepOutcome`, `ConditionEvalError` exist.
- **Step 2** (Data Model Extensions) -- `StepCondition` on `StepConfig`, `skipped`/`skip_reason` on `StepState`/`StepModel`, `StepSkipped` event exist.

## Functional Contract

### Inputs

- A `Run` with steps that have `condition.when` expressions
- Run config variables (provided at creation)
- Step outcomes from previously completed/skipped steps

### Outputs

- When advancing to a step whose `when` evaluates to `False`: step is marked `skipped=True` with `skip_reason` set to the expression, `StepSkipped` event emitted, engine advances to next step
- When advancing to a step whose `when` evaluates to `None` (manual): run is paused with `pause_reason="manual_gate"`
- When advancing to a step whose `when` raises `ConditionEvalError`: run is paused with the error details
- Chain-skipping: if multiple consecutive steps evaluate to `False`, all are skipped and the engine lands on the first non-skipped step or completes the run
- Steps without conditions: unchanged behavior (execute normally)

### Error Cases

- `ConditionEvalError` raised during evaluation -- engine pauses the run with error details (does not crash)
- All steps skipped (every condition is `False`) -- run completes with no work done; warning event emitted
- Output-based condition references a step that hasn't executed yet -- step outcome property returns falsy default

## Tasks

1. Modify `check_step_progression()` in `src/orchestrator/workflow/transitions.py`:
   - After advancing `current_step_index`, evaluate the next step's `condition.when`
   - Build `StepOutcome` objects from completed/skipped steps
   - Gather run config variables for the evaluator
   - Handle `True` (proceed), `False` (skip + advance), `None` (pause), `ConditionEvalError` (pause with error)
2. Implement chain-skip loop: continue evaluating/skipping until a non-skipped step is found or end of steps
3. Handle edge case: all steps skipped (complete the run)
4. Update `WorkflowService` persistence to save/load `skipped` and `skip_reason` from `StepModel`
5. Emit `StepSkipped` events when steps are skipped
6. Integration tests in `tests/integration/test_conditional_steps.py`:
   - Condition true -- step executes normally
   - Condition false -- step skipped, next step starts
   - Manual gate -- run pauses with `manual_gate` reason
   - Output-based condition referencing step 1 failure state
   - Condition syntax error -- run paused with error
   - Chain-skip across multiple false conditions

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/ -v` -- all tests pass (including new transition tests)
- `uv run pytest tests/integration/test_conditional_steps.py -v` -- all conditional step tests pass
- Existing tests unaffected (`uv run pytest tests/ -v` passes)

### Manual Verification

- Create a run with conditional steps via API; verify skipped steps appear correctly in GET response
- Verify `StepSkipped` events appear in activity feed API

## Context & References

- Plan: `docs/conditional-steps/plan.md` -- Step 3 specification (M2 core)
- Architecture: `docs/conditional-steps/architecture.md` -- `check_step_progression()` flow, interaction diagram
- Clarification Q1: Manual gate provides both execute and skip options
- Clarification Q3: Syntax errors pause the run
- `src/orchestrator/workflow/transitions.py` -- step progression logic
- `src/orchestrator/workflow/engine.py` -- workflow state machine
