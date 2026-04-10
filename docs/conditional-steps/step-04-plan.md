# Step Plan: Runtime Repeat-For Expansion

## Purpose

Implement runtime expansion of `repeat_for` steps. When the engine reaches a step with `condition.repeat_for`, it resolves the variable to a list, creates N step copies, and optionally evaluates `when` conditions per copy. This enables dynamic iteration over lists from run config or prior step outputs.

## Prerequisites

- **Step 1** (Safe Evaluator) -- `ConditionEvaluator` for per-copy `when` evaluation.
- **Step 2** (Data Model Extensions) -- `StepCondition.repeat_for` field exists on `StepConfig`.
- **Step 3** (Engine Wiring) -- Engine evaluates conditions and skips steps; chain-skip logic exists.

## Functional Contract

### Inputs

- A step with `condition.repeat_for` set to a variable name (e.g., `"{{bug_ids}}"`)
- Run config variables (may contain the list)
- Prior step outputs (may contain the list, resolved at runtime)
- Optionally, a `condition.when` expression to evaluate per expanded copy

### Outputs

- The single step is replaced with N `StepState` copies in the run's step list:
  - ID: `{original_id}-{index}` (e.g., `S-03-0`, `S-03-1`)
  - Title: `{original_title} [{index + 1}/{count}]`
  - Each copy has `item` (current list value) and `item_index` (0-based index) injected as variables
- Expanded steps are persisted to DB immediately
- If the list is empty, a single skipped step is created with `skip_reason="empty list"`
- If `when` is also present: expansion happens first, then `when` is evaluated per copy. Copies whose condition is `False` are skipped. No agent/LLM work starts until a copy's condition passes.

### Error Cases

- Variable name doesn't resolve to any value -- run paused with error ("variable not found")
- Variable resolves to a non-list value -- run paused with error ("expected list")
- Empty list -- step marked as skipped (not an error)
- `when` evaluation on a copy raises `ConditionEvalError` -- run paused with error details

## Tasks

1. Implement repeat-for expansion logic in `src/orchestrator/workflow/engine.py`:
   - Resolve variable from run config variables first, then prior step outputs
   - Validate resolved value is a list
   - Create N `StepState` copies with unique IDs, suffixed titles, and injected `item`/`item_index`
   - Replace the original step in the run's step list
2. Handle empty list case: create single skipped step
3. Handle `repeat_for` + `when` combo: expand first, then evaluate `when` per copy using `ConditionEvaluator`
4. Persist expanded steps to DB immediately after expansion (atomic update)
5. Ensure engine handles step list mutation mid-run (step count changes, index tracking)
6. Update `create_run_from_routine()` in `state/factory.py` to preserve `condition` as-is (no expansion at creation)
7. Unit tests in `tests/unit/test_engine.py`:
   - List from run config -> N step copies with correct `item` and `item_index`
   - List from prior step output -> N step copies (runtime resolution)
   - Empty list -> skipped step
   - Variable not found -> run paused with error
   - Non-list value -> run paused with error
   - `repeat_for` + `when` combo -> expand first, evaluate per copy
8. Integration test in `tests/integration/test_conditional_steps.py`:
   - `repeat_for` with run config list -> correct number of copies
   - `repeat_for` with prior step output list -> runtime expansion

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/test_engine.py -v` -- repeat-for tests pass
- `uv run pytest tests/integration/test_conditional_steps.py -v` -- repeat-for integration tests pass
- Existing tests unaffected (`uv run pytest tests/ -v` passes)
- Step IDs follow `{parent_id}-{index}` pattern in test assertions

### Manual Verification

- Create a run with a `repeat_for` step via API; verify expanded copies appear in GET response with correct IDs and titles
- Verify each copy has correct `item` and `item_index` in its variables

## Context & References

- Plan: `docs/conditional-steps/plan.md` -- Step 4 specification (M2)
- Architecture: `docs/conditional-steps/architecture.md` -- Runtime repeat-for expansion flow, interaction diagram
- Clarification Q2: Expand first, evaluate `when` per copy (no LLM work until condition passes)
- Clarification Q4: Allow prior step outputs (runtime expansion, not static)
- `src/orchestrator/workflow/engine.py` -- workflow engine
- `src/orchestrator/state/factory.py` -- run creation
