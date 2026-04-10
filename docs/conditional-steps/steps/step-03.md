# Step 3: Engine Wiring

Wire condition evaluation into the workflow engine so steps are actually skipped or paused (manual gate) based on their conditions. This is the core integration that makes conditional steps functional at runtime.

## Intent Verification
**Original Intent**: Integrate the condition evaluator into the step progression logic so that steps with `when` conditions are evaluated at runtime, enabling skip, execute, or pause behavior (see `docs/conditional-steps/intent.md`).
**Functionality to Produce**:
- `check_step_progression()` evaluates `condition.when` when advancing to a new step
- False conditions skip the step with `StepSkipped` event
- `manual` keyword pauses the run with `pause_reason="manual_gate"`
- `ConditionEvalError` pauses the run with error details
- Chain-skip handles multiple consecutive false conditions
- `WorkflowService` persists `skipped` and `skip_reason` to DB

**Final Verification Criteria**:
- `uv run pytest tests/unit/ -v` -- all tests pass
- `uv run pytest tests/integration/test_conditional_steps.py -v` -- all conditional step tests pass
- Existing tests unaffected

---

## Task 1: Implement Condition Evaluation in Step Progression

**Description**: Modify `check_step_progression()` to evaluate `condition.when` when advancing to a new step. Build `StepOutcome` objects from completed/skipped steps and gather run config variables.

**Implementation Plan (Do These Steps)**
- [ ] Modify `check_step_progression()` in `src/orchestrator/workflow/transitions.py`:
  - After advancing `current_step_index`, evaluate the next step's `condition.when`
  - Build `StepOutcome` objects from completed/skipped steps
  - Gather run config variables for the evaluator
  - Handle results: `True` (proceed), `False` (skip + advance), `None` (pause signal), `ConditionEvalError` (pause with error signal)
- [ ] Return appropriate signals to the engine for pause/skip cases
- [ ] Emit `StepSkipped` events when steps are skipped

**Dependencies**
- [ ] Step 1 (evaluator) and Step 2 (data models) must be complete

**References**
- `docs/conditional-steps/architecture.md` -- `check_step_progression()` flow, interaction diagram
- `docs/conditional-steps/step-03-plan.md` -- task 1
- Clarification Q3: Syntax errors pause the run
- `src/orchestrator/workflow/transitions.py` -- current step progression logic

**Constraints**
- Steps without conditions behave exactly as before (no regression)
- Output-based conditions for not-yet-executed steps return falsy defaults

**Functionality (Expected Outcomes)**
- [ ] Step with `when: "never"` is skipped with skip_reason set
- [ ] Step with `when: "manual"` causes run to pause
- [ ] Step with syntax error in `when` causes run to pause with error
- [ ] Step with `when: "always"` or no condition executes normally

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/ -v` -- all pass (including new transition tests)
- [ ] `uv run pyright src/orchestrator/workflow/transitions.py` -- no errors

---

## Task 2: Implement Chain-Skip and Edge Cases

**Description**: Implement chain-skip logic for multiple consecutive false conditions and handle the edge case where all steps are skipped.

**Implementation Plan (Do These Steps)**
- [ ] Implement chain-skip loop in `check_step_progression()`: continue evaluating/skipping until a non-skipped step is found or end of steps
- [ ] Handle all-steps-skipped: complete the run with no work done, emit warning event
- [ ] Ensure step index tracking accounts for skipped steps correctly

**Dependencies**
- [ ] Task 1 must be complete (basic condition evaluation works)

**References**
- `docs/conditional-steps/step-03-plan.md` -- tasks 2-3
- `docs/conditional-steps/plan.md` -- risks: chain-skipping all steps

**Constraints**
- Chain-skip is bounded by the number of steps (no infinite loop risk)
- Run completes gracefully when all steps are skipped

**Functionality (Expected Outcomes)**
- [ ] Three consecutive false-condition steps are all skipped, engine lands on step 4
- [ ] If every step is false, run completes without errors
- [ ] Each skipped step gets its own `StepSkipped` event

**Final Verification (Proof of Completion)**
- [ ] Chain-skip logic has unit test coverage

---

## Task 3: Update WorkflowService Persistence and Write Integration Tests

**Description**: Ensure `WorkflowService` saves/loads `skipped` and `skip_reason` from the DB, and write integration tests for the full conditional step lifecycle.

**Implementation Plan (Do These Steps)**
- [ ] Update `WorkflowService` persistence to save `skipped` and `skip_reason` to `StepModel`
- [ ] Update `WorkflowService` to load `skipped` and `skip_reason` from `StepModel` when reconstructing state
- [ ] Create integration tests in `tests/integration/test_conditional_steps.py`:
  - Condition true -> step executes normally
  - Condition false -> step skipped, next step starts
  - Manual gate -> run pauses with `manual_gate` reason
  - Output-based condition referencing step 1 failure state
  - Condition syntax error -> run paused with error
  - Chain-skip across multiple false conditions

**Dependencies**
- [ ] Tasks 1-2 must be complete (engine wiring done)

**References**
- `docs/conditional-steps/architecture.md` -- testing strategy, integration tests section
- `docs/conditional-steps/step-03-plan.md` -- tasks 4-6

**Constraints**
- No mocking in tests (per AGENTS.md)
- Integration tests use real DB (in-memory SQLite)

**Functionality (Expected Outcomes)**
- [ ] Skipped steps survive server restart (persisted to DB)
- [ ] All conditional step scenarios are covered by integration tests

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/integration/test_conditional_steps.py -v` -- all tests pass
- [ ] `uv run pytest tests/ -v` -- existing tests unaffected
