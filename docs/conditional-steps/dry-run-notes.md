# Dry Run Simulation: Conditional Steps Feature

## Per-Step Simulation Results

### Step 1: Safe Condition Evaluator

#### Task 1: Create ConditionEvaluator Module with Core Types
- **Assumptions**: `src/orchestrator/workflow/` directory exists; Pydantic is available; no naming conflicts with existing modules
- **Expected outputs**: New file `condition_evaluator.py` with `ConditionEvalError`, `StepOutcome`, and `ConditionEvaluator` class skeleton
- **Blockers**: None — greenfield module, no dependencies
- **Mitigation**: N/A

#### Task 2: Implement Tokenizer and Recursive Descent Parser
- **Assumptions**: Task 1 skeleton is correct and complete; grammar from architecture doc is unambiguous; `{{var}}` syntax doesn't conflict with other templating in the codebase
- **Expected outputs**: Fully working tokenizer + parser handling all operator types, variable resolution, and keyword literals
- **Blockers**: None — self-contained code
- **Mitigation**: N/A
- **Risk note**: This is the largest single task in step 1 — a recursive descent parser with tokenizer is ~200-400 lines of code. An agent could get stuck on edge cases (e.g., `not in` as a two-word operator, distinguishing `not` prefix from `not in` infix). The grammar spec is clear but the implementation requires careful lookahead.

#### Task 3: Implement Safety Constraints
- **Assumptions**: Parser from task 2 tracks nesting depth; expression length is checked before parsing
- **Expected outputs**: Safety checks integrated into evaluate() flow
- **Blockers**: None
- **Mitigation**: N/A

#### Task 4: Write Comprehensive Unit Tests
- **Assumptions**: `tests/unit/` directory exists; pytest is configured; the evaluator from tasks 1-3 is complete and working
- **Expected outputs**: New test file with coverage for all expression types, operators, edge cases, and adversarial inputs
- **Blockers**: None
- **Mitigation**: N/A
- **Risk note**: If tasks 2-3 have subtle bugs, the agent may spend time debugging test failures. Tests should be written to match the spec, not the implementation, so bugs are caught rather than papered over.

#### Step 1 Overall Assessment
**Risk level**: LOW-MEDIUM. Self-contained greenfield code with no external dependencies. The parser is the most complex piece but the grammar is well-specified. Agent should succeed on first attempt.

---

### Step 2: Data Model Extensions

#### Task 1: Add StepCondition and StepConfig.condition
- **Assumptions**: `StepConfig` in `config/models.py` is a Pydantic BaseModel; adding an optional field is backward-compatible; no existing `condition` field on StepConfig
- **Expected outputs**: `StepCondition` and updated `StepConfig` with `condition: StepCondition | None = None`
- **Blockers**: None
- **Mitigation**: N/A
- **Risk note**: Must verify existing routines still parse — agent should load a real YAML file to confirm.

#### Task 2: Add Skip Fields to StepState and StepModel
- **Assumptions**: Alembic is configured and working; `StepModel` uses SQLAlchemy declarative base; existing migrations apply cleanly; `StepState` is a Pydantic model
- **Expected outputs**: New fields on `StepState`, new columns on `StepModel`, Alembic migration file
- **Blockers**: **Alembic migration generation depends on a working database connection and properly configured migration environment.** If alembic env is misconfigured (e.g., wrong import path, missing `env.py` setup), the migration generation command will fail.
- **Mitigation**: Task instructions should include a fallback: if `alembic revision --autogenerate` fails, create the migration manually. Also verify `alembic.ini` path before running.
- **Risk note**: The codebase uses `init_db()` with `create_all` for dev (per MEMORY.md), so the Alembic migration may not be the primary schema update mechanism. Agent needs to understand whether Alembic is actively used or if `create_all` is the real path. If `create_all` is the only mechanism, the migration file may be dead code. However, the task explicitly requires an Alembic migration, so it should be created regardless.

#### Task 3: Add StepSkipped Event and Update Factory
- **Assumptions**: Event types follow an existing pattern in `events.py`; `create_run_from_routine()` currently doesn't modify condition config (just passes through); there's a pattern for how events are defined
- **Expected outputs**: `StepSkipped` event class, verification that factory preserves conditions, unit tests
- **Blockers**: None
- **Mitigation**: N/A
- **Risk note**: The instruction says `repeat_for` expansion does NOT happen at creation time. Agent must resist the urge to add expansion logic here — that's step 4. The task is explicit about this constraint.

#### Step 2 Overall Assessment
**Risk level**: MEDIUM. The Alembic migration is the riskiest part. If the migration environment isn't properly configured (16 existing migrations suggest it is, but config could have drifted), the agent may get stuck. The data model changes themselves are straightforward.

---

### Step 3: Engine Wiring

#### Task 1: Implement Condition Evaluation in Step Progression
- **Assumptions**: `check_step_progression()` is the correct integration point; the function has access to the `Run` object (which contains steps and config); the function can be modified to return signals for pause/skip; `StepOutcome` can be built from existing step data
- **Expected outputs**: Modified `check_step_progression()` that evaluates conditions when advancing steps
- **Blockers**: **Critical dependency on existing code structure.** The current `check_step_progression()` returns specific values and is called from specific places in `engine.py`. The agent must understand the existing call chain to add condition evaluation without breaking the caller contract.
- **Mitigation**: Agent should read both `transitions.py` AND the calling code in `engine.py` before modifying. The task document should emphasize understanding the return type/signal contract.
- **Risk note**: The existing `evaluate_transition_conditions()` in transitions.py is DIFFERENT from the new `ConditionEvaluator`. The existing code handles backward transitions (loop conditions), while the new code handles forward skip/execute decisions. Agent must not confuse these two systems. They coexist but serve different purposes.

#### Task 2: Implement Chain-Skip and Edge Cases
- **Assumptions**: The loop in check_step_progression can safely skip multiple steps without side effects; step index tracking is consistent; skipping doesn't trigger task creation
- **Expected outputs**: Loop that continues evaluating/skipping until finding a non-skipped step
- **Blockers**: None beyond task 1 correctness
- **Mitigation**: N/A
- **Risk note**: All-steps-skipped case must complete the run gracefully. Agent needs to understand how run completion works (what events, what state changes) to replicate it in the all-skipped path.

#### Task 3: Update WorkflowService Persistence and Write Integration Tests
- **Assumptions**: `WorkflowService` has existing save/load patterns for step data; integration tests can use in-memory SQLite; the test infrastructure supports creating runs with conditional steps
- **Expected outputs**: Persistence for skip fields, integration test file
- **Blockers**: **Integration tests require the full stack (engine + DB + service) to be functional with the new code.** If step 2 migrations or model changes have issues, these tests will fail.
- **Mitigation**: Run unit tests from steps 1-2 first as a smoke test before attempting integration tests.
- **Risk note**: The task says "no mocking" — integration tests must use the real engine, real DB, and real evaluator. This makes the tests more valuable but also more fragile. Any issue in prior steps cascades here.

#### Step 3 Overall Assessment
**Risk level**: HIGH. This is the most architecturally sensitive step — it modifies the core step progression logic. The agent must deeply understand the existing call chain (engine → transitions → service) and the existing return value contracts. A mistake here could break ALL run progression, not just conditional steps.

---

### Step 4: Runtime Repeat-For Expansion

#### Task 1: Implement Repeat-For Expansion Logic
- **Assumptions**: The engine can mutate the step list mid-run; step indices are recalculated after mutation; DB persistence handles variable-length step lists; `StepState` copies can be created with modified IDs and titles
- **Expected outputs**: Expansion logic that detects repeat_for, resolves the variable, creates N copies, replaces the original step
- **Blockers**: **Step list mutation mid-run is architecturally complex.** The engine and transitions code assume step indices are stable. After expansion, `current_step_index` and all subsequent indices shift. If other code caches step references by index, it will break.
- **Mitigation**: Task instructions should mandate: (1) expansion happens BEFORE any other step logic runs on the expanded step, (2) indices are immediately recalculated, (3) the expansion is persisted atomically so a restart doesn't re-expand.
- **Risk note**: Resolving variables from "prior step outputs" (per clarification Q4) requires a mechanism to access step outputs. The current architecture may not have a clear "step output" concept — tasks have outcomes, but steps don't aggregate outputs. The agent needs to determine what "prior step output" actually means in the codebase (likely task artifacts or a designated output field). If this concept doesn't exist yet, the agent will need to define it, which significantly expands the scope.

#### Task 2: Handle Edge Cases and Repeat-For + When Combo
- **Assumptions**: Empty list detection works; variable-not-found detection works; non-list value detection works; per-copy when evaluation uses the same ConditionEvaluator
- **Expected outputs**: Error handling for all edge cases, per-copy condition evaluation
- **Blockers**: None beyond task 1 correctness
- **Mitigation**: N/A
- **Risk note**: The `repeat_for` + `when` combo is the most complex interaction in the feature. The agent must correctly inject `item` and `item_index` into the variables dict BEFORE evaluating `when` per copy. If the order is wrong, the `when` expression can't reference the current item.

#### Task 3: Write Unit and Integration Tests
- **Assumptions**: Prior step output resolution is testable without running actual agents; step list mutation is observable in tests
- **Expected outputs**: Unit and integration tests for all expansion scenarios
- **Blockers**: **Testing "list from prior step output" requires a way to set step outputs in test fixtures.** If the output mechanism isn't defined clearly, these tests can't be written.
- **Mitigation**: Define a minimal step output interface even if it's just a dict on StepState.
- **Risk note**: Integration tests for runtime expansion need to create a run, complete step 1 (to produce output), then advance to step 2 (which has repeat_for referencing step 1 output). This is a multi-step test that may be slow and brittle.

#### Step 4 Overall Assessment
**Risk level**: HIGH. Runtime step list mutation is inherently complex. The "prior step output" concept may not exist cleanly in the codebase, requiring the agent to define it. Index management after expansion is error-prone. This step has the highest probability of requiring a revision cycle.

---

### Step 5: API Surface

#### Task 1: Add API Schemas for Conditional Steps
- **Assumptions**: `StepSummary` in schemas/runs.py matches the Pydantic pattern; adding optional fields is backward-compatible; serialization from StepModel/StepState to StepSummary has a clear mapping point
- **Expected outputs**: `StepConditionSchema`, extended `StepSummary`, updated serialization
- **Blockers**: None — straightforward schema addition
- **Mitigation**: N/A

#### Task 2: Add Skip-Step API Endpoint
- **Assumptions**: `pause_reason` field reliably indicates "manual_gate" when paused at a gate; the current gated step can be identified from the run state; the engine has a method to advance past a skipped step; existing resume endpoint is not modified
- **Expected outputs**: New POST endpoint with proper validation and 409 error responses
- **Blockers**: **The endpoint must correctly identify which step is the gated step.** If `current_step_index` points to the gated step (which it should), the validation is straightforward. But if the engine advances past the step before pausing (off-by-one), the step_id won't match.
- **Mitigation**: Task instructions should clarify: when paused at a manual gate, `current_step_index` points to the gated step (not the next one).
- **Risk note**: The skip action must also evaluate the NEXT step's condition (in case it's also conditional). This means the skip endpoint essentially needs to trigger the same chain-skip logic from step 3. Code reuse is critical here.

#### Task 3: Write Integration Tests
- **Assumptions**: Integration test infrastructure supports creating runs that pause at manual gates; test can simulate the pause → skip → advance flow
- **Expected outputs**: Integration tests for API surface
- **Blockers**: None
- **Mitigation**: N/A

#### Step 5 Overall Assessment
**Risk level**: MEDIUM. The skip-step endpoint has subtle validation requirements and must reuse chain-skip logic. Schema changes are straightforward.

---

### Step 6: Frontend Display

#### Task 1: Update TypeScript Types and Step State Utils
- **Assumptions**: `StepSummary` TypeScript type matches the backend schema; `getStepState()` can be extended without breaking existing callers; the `'skipped'` state doesn't conflict with existing states
- **Expected outputs**: Updated types and utils
- **Blockers**: None
- **Mitigation**: N/A
- **Risk note**: The `stepBadgeClasses` map may need a new entry for `'skipped'`. If the existing code uses a strict union type for step states, adding `'skipped'` requires updating the type definition AND all switch/if-else blocks that handle step states.

#### Task 2: Update StepTimeline and ActivityFeed Components
- **Assumptions**: `StepTimeline.tsx` renders steps in a map/loop where we can add conditional rendering; `ActivityFeed.tsx` has a switch or map for event types; tooltip implementation exists or can use native `title` attribute
- **Expected outputs**: Visual indicators for skipped steps, condition text, repeat-for sub-items, StepSkipped events
- **Blockers**: **Repeat-for sub-items rendering depends on how expanded steps are represented in the API response.** If expanded steps are flat (each copy is a separate step in the steps array), rendering as sub-items requires grouping logic. If they're nested (parent step with children), the component structure is different.
- **Mitigation**: The architecture says expanded steps replace the original step as flat entries with IDs like `{parent_id}-{index}`. The frontend needs grouping logic to detect these by ID pattern and render as sub-items under a parent header.
- **Risk note**: The tooltip for skip_reason may not match existing tooltip patterns in the UI. Agent should check what tooltip library/pattern is used elsewhere.

#### Task 3: Add Manual Gate UI
- **Assumptions**: `RunDetail.tsx` (or similar) already handles pause states; `pause_reason` is available in the frontend run state; API client functions exist for resume and can be extended for skip
- **Expected outputs**: Two buttons (Execute/Skip) shown when paused at manual gate
- **Blockers**: None — straightforward UI addition
- **Mitigation**: N/A

#### Task 4: Write Frontend Tests
- **Assumptions**: Vitest + Testing Library is configured; component rendering tests can provide mock step data; no need for API mocking (just component rendering)
- **Expected outputs**: Tests for all new UI elements
- **Blockers**: None
- **Mitigation**: N/A
- **Risk note**: Frontend tests that render components with conditional props are usually straightforward, but the repeat-for sub-items test requires understanding the grouping logic from task 2.

#### Step 6 Overall Assessment
**Risk level**: MEDIUM. The repeat-for sub-items rendering requires grouping logic that isn't fully specified. The rest is standard React component work. TypeScript type changes should catch most issues at compile time.

---

## Failure Mode Analysis

| Step | Failure Mode | Likelihood | Impact | Hardening Action |
|------|-------------|------------|--------|-----------------|
| 1 | Parser can't handle `not in` as two-word operator (conflicts with `not` prefix) | MEDIUM | Blocks all `not in` expressions | Add explicit note in task 2: tokenizer must handle `not in` as a single token via lookahead; include a `not in` test case in task 4 |
| 1 | Agent uses `ast.literal_eval` or `eval` for "simplicity" | LOW | Security violation, fails verification | Safety constraint is already explicit in task 3; add to task 2 as well: "Do NOT use eval/exec/ast — build a recursive descent parser from scratch" |
| 2 | Alembic migration generation fails due to env misconfiguration | MEDIUM | Blocks DB schema changes | Add environment check: `uv run alembic -c alembic.ini heads` should succeed before attempting `revision`. Include fallback: "If autogenerate fails, create migration manually with `op.add_column()`" |
| 2 | Agent confuses `create_all` (dev) with Alembic (prod) schema management | LOW | Migration file created but never used, or wrong approach taken | Add note: "This project uses BOTH create_all (dev, deletes DB) and Alembic (prod). Create the migration file even though dev uses create_all." |
| 3 | Agent modifies `check_step_progression()` return type without updating all callers | HIGH | Breaks all run progression, not just conditional | Add pre-task instruction: "Before modifying check_step_progression(), read ALL callers (grep for the function name) and understand the return value contract. List the callers in a comment." |
| 3 | Agent confuses existing `evaluate_transition_conditions()` with new `ConditionEvaluator` | MEDIUM | Wires wrong system, causes incorrect behavior | Add explicit note: "The existing evaluate_transition_conditions() handles BACKWARD transitions (loops). Do NOT modify it. The new ConditionEvaluator handles FORWARD skip/execute decisions. These are separate systems." |
| 3 | Condition evaluation runs BEFORE step tasks are spawned but signal handling is wrong | MEDIUM | Steps marked as skipped but tasks still spawn, or vice versa | Add integration test: "Verify that a skipped step has zero tasks started (no agent execution)" |
| 4 | Step list mutation breaks `current_step_index` tracking | HIGH | Run gets stuck or skips wrong steps after expansion | Add invariant check: "After expansion, assert current_step_index still points to the first expanded copy. Add a test that verifies step indices after expansion." |
| 4 | "Prior step output" concept doesn't exist in codebase | HIGH | Agent can't implement variable resolution from prior steps | Add explicit fallback: "If step output storage doesn't exist, add an `outputs: dict[str, Any]` field to StepState. This is the minimal mechanism needed. Document what populates it (task results, auto_verify output, etc.)." |
| 4 | Expansion persisted but server restarts mid-expansion | LOW | Inconsistent step list in DB | Add instruction: "Persist expanded steps in a single DB transaction. Include a test that loads a run with expanded steps from DB." |
| 4 | `repeat_for` + `when` combo: `item`/`item_index` not injected before `when` evaluation | MEDIUM | `when` expressions can't reference the current item | Add explicit instruction: "Inject `item` and `item_index` into the variables dict BEFORE calling ConditionEvaluator.evaluate() for each copy" |
| 5 | Skip-step endpoint doesn't trigger chain-skip for next step | MEDIUM | After skipping a manual gate, the next step's condition isn't evaluated | Add explicit instruction: "After skipping, call the same advancement/condition logic from step 3 to evaluate the next step's condition. Reuse, don't duplicate, the chain-skip code." |
| 5 | `current_step_index` off-by-one: gate step vs next step | MEDIUM | 409 errors on valid skip requests | Add clarifying note: "When paused at manual_gate, current_step_index points TO the gated step (the one to be skipped/executed), not past it." |
| 6 | Repeat-for sub-items grouping logic not specified | MEDIUM | Expanded steps render as flat ungrouped items | Add UI specification: "Detect expanded steps by ID pattern `{parent_id}-{N}`. Group consecutive steps matching the same parent_id under a collapsible parent header showing the original step title." |
| 6 | `'skipped'` step state not handled in all switch/if-else blocks | MEDIUM | Runtime errors or missing styling for skipped steps | Add instruction: "After adding 'skipped' to StepState type, grep for all uses of StepState and update each switch/if-else to handle the new case" |
| 6 | Manual gate UI buttons call wrong endpoints | LOW | Skip doesn't work or calls resume instead | Add explicit endpoint paths in task instructions: "Execute = POST /api/runs/{id}/resume, Skip = POST /api/runs/{id}/steps/{step_id}/skip" |
| ALL | Agent gets stuck in retry loop on test failures from prior step bugs | MEDIUM | Wasted time, no progress | Add per-step gate: "Before starting implementation, run the verification commands from the previous step. If they fail, stop and report — do not attempt to fix prior step issues." |
| ALL | Circular dependency between steps 3 and 4 | LOW | Engine wiring (step 3) doesn't account for repeat-for expansion (step 4) | Steps are ordered correctly: step 3 wires basic condition evaluation, step 4 adds repeat-for on top. But step 3 task instructions should note: "The repeat_for handling will be added in step 4. For now, only handle `when` conditions." |

## Plan Changes Recommended

### High Priority (address before execution)

1. **Step 3, Task 1 — Add caller analysis pre-task**: Before modifying `check_step_progression()`, the agent MUST read all callers and document the existing return-value contract. Add this as an explicit first sub-task: "Read `engine.py` and any other files that call `check_step_progression()`. Document what the caller expects as return value. Design your changes to maintain backward compatibility or update all callers."

2. **Step 4, Task 1 — Define "step output" mechanism**: The task references "prior step outputs" but the codebase may not have this concept. Add an explicit sub-task: "If `StepState` does not have an `outputs` field, add `outputs: dict[str, Any] = {}` to `StepState` and `outputs = Column(JSON, nullable=True)` to `StepModel`. Document that this field is populated by: (a) auto_verify results, (b) task completion artifacts, or (c) explicit set-output API calls. For this step, only the field and basic get/set are needed."

3. **Step 3, Task 1 — Disambiguate from existing transitions**: Add a warning: "The existing `evaluate_transition_conditions()` function in this same file handles a DIFFERENT feature (backward transition loops). Do NOT modify or call it. Create new condition evaluation logic using `ConditionEvaluator` from step 1."

4. **Step 4, Task 1 — Add index invariant assertion**: After step list mutation, add an assertion that `current_step_index` is correct. This catches off-by-one errors immediately rather than letting them propagate.

### Medium Priority (improve reliability)

5. **Step 1, Task 2 — Add `not in` tokenizer guidance**: Explicitly note that `not in` must be tokenized as a single operator via lookahead (check if `not` is followed by `in`). Add a test case for `"a" not in ["b", "c"]` in task 4.

6. **Step 2, Task 2 — Add Alembic pre-check**: Before running `alembic revision`, run `uv run alembic -c alembic.ini heads` to verify the migration environment is functional. If it fails, document the error and try manual migration creation.

7. **Step 5, Task 2 — Mandate chain-skip reuse**: Explicitly state: "The skip-step endpoint must reuse the same advancement logic from step 3 (condition evaluation + chain-skip). Extract this into a helper function if it's not already reusable."

8. **Step 6, Task 2 — Specify grouping algorithm**: Add: "Expanded repeat-for steps have IDs matching `{parent_id}-{N}` pattern. Group consecutive steps with matching parent prefix under a visual parent header. The parent header shows the original step title; sub-items show `[1/N]`, `[2/N]` suffixes."

9. **All steps — Add prior-step verification gate**: Each step's first task should begin with: "Run the verification commands from the previous step to confirm prerequisites are met. If any fail, stop and report rather than proceeding with broken foundations."

### Low Priority (nice to have)

10. **Step 1, Task 2 — Add grammar test-first guidance**: Suggest writing a few parser tests BEFORE implementing the parser, using the grammar specification as the oracle. This TDD approach catches ambiguities early.

11. **Step 2, Task 3 — Add backward compatibility test**: Add an explicit test: "Load an existing routine YAML without any `condition` field. Verify it creates a valid `StepConfig` with `condition=None`."

12. **Step 6, Task 4 — Add accessibility note**: Skipped steps should have appropriate ARIA attributes (e.g., `aria-label="Step 3: Skipped - condition was false"`) for screen reader users.
