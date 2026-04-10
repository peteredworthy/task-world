# Step 4: Runtime Repeat-For Expansion

Implement runtime expansion of `repeat_for` steps. When the engine reaches a step with `condition.repeat_for`, it resolves the variable to a list, creates N step copies, and optionally evaluates `when` conditions per copy.

## Intent Verification
**Original Intent**: Enable dynamic iteration over lists from run config or prior step outputs by expanding `repeat_for` steps at runtime (not at creation time), supporting both static lists and outputs from earlier steps (see `docs/conditional-steps/intent.md`).
**Functionality to Produce**:
- Runtime expansion logic in `engine.py` when reaching a repeat-for step
- Variable resolution from run config AND prior step outputs
- N `StepState` copies with unique IDs (`{parent_id}-{index}`), suffixed titles, and injected `item`/`item_index`
- Empty list -> skipped step
- `repeat_for` + `when` combo: expand first, evaluate per copy
- Immediate persistence of expanded steps to DB

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_engine.py -v` -- repeat-for tests pass
- `uv run pytest tests/integration/test_conditional_steps.py -v` -- repeat-for integration tests pass
- Existing tests unaffected
- Step IDs follow `{parent_id}-{index}` pattern

---

## Task 1: Implement Repeat-For Expansion Logic

**Description**: Add repeat-for expansion to the workflow engine. When reaching a step with `condition.repeat_for`, resolve the variable to a list and create N step copies.

**Implementation Plan (Do These Steps)**
- [ ] Add expansion logic in `src/orchestrator/workflow/engine.py`:
  - Detect `condition.repeat_for` on the current step
  - Resolve variable from run config variables first, then prior step outputs
  - Validate resolved value is a list (pause run with error if not)
  - Create N `StepState` copies with: ID `{original_id}-{index}`, title `{original_title} [{index + 1}/{count}]`, injected `item` and `item_index` variables
  - Replace the original step in the run's step list
- [ ] Persist expanded steps to DB immediately after expansion

**Dependencies**
- [ ] Steps 1-3 complete (evaluator, models, engine wiring)

**References**
- `docs/conditional-steps/architecture.md` -- runtime repeat-for expansion flow
- `docs/conditional-steps/step-04-plan.md` -- tasks 1, 4-5
- Clarification Q4: Allow prior step outputs (runtime expansion)
- `src/orchestrator/workflow/engine.py` -- workflow engine

**Constraints**
- `create_run_from_routine()` must NOT expand repeat-for (deferred to runtime)
- Engine must handle step list mutation mid-run (step count changes, index tracking)

**Functionality (Expected Outcomes)**
- [ ] Step with `repeat_for: "{{items}}"` and `items: ["a", "b", "c"]` produces 3 step copies
- [ ] Each copy has correct `item` value and `item_index`
- [ ] Step IDs follow `{parent_id}-{index}` pattern
- [ ] Expanded steps are persisted to DB

**Final Verification (Proof of Completion)**
- [ ] Expansion logic handles lists from run config correctly
- [ ] `uv run pyright src/orchestrator/workflow/engine.py` -- no errors

---

## Task 2: Handle Edge Cases and Repeat-For + When Combo

**Description**: Handle empty list, variable-not-found, non-list value, and the combination of `repeat_for` with `when` conditions.

**Implementation Plan (Do These Steps)**
- [ ] Handle empty list: create single skipped step with `skip_reason="empty list"`
- [ ] Handle variable not found: pause run with error ("variable not found")
- [ ] Handle non-list value: pause run with error ("expected list")
- [ ] Handle `repeat_for` + `when` combo: expand first, then evaluate `when` per copy using `ConditionEvaluator`. Copies whose condition is False are skipped. No agent/LLM work starts until a copy's condition passes.
- [ ] Handle `when` evaluation error on a copy: pause run with error details

**Dependencies**
- [ ] Task 1 must be complete (basic expansion works)

**References**
- `docs/conditional-steps/step-04-plan.md` -- tasks 2-3, 6
- Clarification Q2: Expand first, evaluate `when` per copy (no LLM work until condition passes)

**Constraints**
- Empty list is not an error -- just mark step as skipped
- `when` evaluation happens per copy, not on the original step

**Functionality (Expected Outcomes)**
- [ ] Empty list -> single skipped step
- [ ] Missing variable -> run paused with descriptive error
- [ ] Non-list value -> run paused with descriptive error
- [ ] `repeat_for` + `when`: copies with false condition are skipped, others execute

**Final Verification (Proof of Completion)**
- [ ] All error cases produce meaningful error messages

---

## Task 3: Write Unit and Integration Tests

**Description**: Write comprehensive tests for repeat-for expansion covering all scenarios.

**Implementation Plan (Do These Steps)**
- [ ] Add unit tests in `tests/unit/test_engine.py` (or new file):
  - List from run config -> N step copies with correct `item` and `item_index`
  - List from prior step output -> N step copies (runtime resolution)
  - Empty list -> skipped step
  - Variable not found -> run paused with error
  - Non-list value -> run paused with error
  - `repeat_for` + `when` combo -> expand first, evaluate per copy
- [ ] Add integration tests in `tests/integration/test_conditional_steps.py`:
  - `repeat_for` with run config list -> correct number of copies
  - `repeat_for` with prior step output list -> runtime expansion

**Dependencies**
- [ ] Tasks 1-2 must be complete (expansion fully implemented)

**References**
- `docs/conditional-steps/architecture.md` -- testing strategy
- `docs/conditional-steps/step-04-plan.md` -- tasks 7-8

**Constraints**
- No mocking (per AGENTS.md)
- Test step ID pattern: `{parent_id}-{index}`

**Functionality (Expected Outcomes)**
- [ ] All expansion scenarios have test coverage
- [ ] Integration tests verify end-to-end behavior through the API

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_engine.py -v` -- repeat-for tests pass
- [ ] `uv run pytest tests/integration/test_conditional_steps.py -v` -- repeat-for integration tests pass
- [ ] `uv run pytest tests/ -v` -- existing tests unaffected
