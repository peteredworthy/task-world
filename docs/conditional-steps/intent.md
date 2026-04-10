# Intent: Conditional Step Execution

## Original Request

Add conditional step execution, optional step wiring, and step-level `repeat_for` to the orchestrator so routines can adapt their workflow based on input variables and prior step outcomes. [S-01/T-02/R1, S-02/T-01/R1, S-04/T-01/R4]

## Goal

Enable steps to be conditionally skipped or repeated so that a single routine template can serve multiple workflows (e.g., skip design for simple bugs, include it for complex ones; repeat a fix step per bug ID). [S-03/T-01/R1, S-04/T-01/R1] This is Option C from the orchestration architecture research. [NO-REQ — architectural context, not a requirement]

## Scope

### In Scope

- **Step conditions** — `condition.when` field on `StepConfig` controlling whether a step executes or is skipped. [S-02/T-01/R1, S-02/T-01/R2] Expression types: variable-based (`{{complexity}} == 'high'`), output-based (`steps.S-01.has_failures`), literal (`always`/`never`), and manual gate (`manual`). [S-01/T-02/R1, S-01/T-02/R3, S-01/T-02/R4]
- **Step repeat** — `condition.repeat_for` field that expands a step into N iterations over a list. [S-04/T-01/R1, S-04/T-01/R2] The list can come from run config variables or from prior step outputs. [S-04/T-01/R4] Expansion happens at runtime (when the engine reaches the step), not at run creation, so prior step outputs are available. [S-02/T-03/R2, S-04/T-01/R1] Each iteration gets `{{item}}` and `{{item_index}}` in scope. [S-04/T-01/R1] When a step has both `repeat_for` and `when`, expansion happens first, then `when` is evaluated per iteration copy — no LLM/agent work starts until a copy's condition passes. [S-04/T-02/R4]
- **Safe condition evaluator** — Restricted expression parser (no `eval()`) supporting `==`, `!=`, `in`, `not in`, `and`, `or`, `not`, variable access, and literals. [S-01/T-01/R1, S-01/T-02/R1, S-01/T-02/R2, S-01/T-02/R5, S-01/T-03/R4] Syntax errors in condition expressions pause the run with an error so the routine can be fixed. [S-03/T-01/R3]
- **Skip tracking** — `skipped` and `skip_reason` fields on `StepState`, persisted to DB, exposed in API, with `StepSkipped` activity events. [S-02/T-02/R1, S-02/T-02/R2, S-02/T-03/R1, S-03/T-03/R1, S-05/T-01/R1, S-05/T-01/R2]
- **Manual gate** — When `when: "manual"`, the run pauses. [S-03/T-01/R2] On resume, the user can choose to **execute** the gated step or **skip** it. [S-05/T-02/R1, S-06/T-03/R1] A dedicated skip-step action is provided alongside resume. [S-05/T-02/R1, S-05/T-02/R3]
- **Step outcome properties** — Queryable properties for output-based conditions: `has_failures`, `all_passed`, `any_completed`, `completed` (step finished regardless of pass/fail), and `skipped` (step was skipped). [S-01/T-01/R2, S-01/T-02/R3]
- **Frontend changes** — Skipped steps rendered with dashed border/dimmed opacity in `StepTimeline`. [S-06/T-01/R3, S-06/T-02/R1] Pending conditional steps show their condition text. [S-06/T-02/R3] Repeat-for iterations shown as sub-items. [S-06/T-02/R5] Skip events in activity feed. [S-06/T-02/R4]
- **Backward compatibility** — Steps without a `condition` block behave identically to today (`when: "always"` is the default). [S-02/T-01/R3, S-03/T-01/R4, S-05/T-01/R3]

### Out of Scope

- Phase pipelines (Option A) — separate effort, no dependency. [NO-REQ — explicitly out of scope]
- Gap analyzer (Option B) — separate effort. [NO-REQ — explicitly out of scope]
- Orchestrated expansion (Option D) — separate effort. [NO-REQ — explicitly out of scope]
- Dynamic step insertion at runtime (adding steps that weren't in the original routine). [NO-REQ — explicitly out of scope]
- Cross-run condition evaluation (conditions referencing other runs). [NO-REQ — explicitly out of scope]
- Nested repeat_for (repeat inside repeat) — single level only for now. [NO-REQ — explicitly out of scope]
- Altering task-level config based on conditions (conditions apply at step level only). [NO-REQ — explicitly out of scope]
- Lazy/streaming expansion (repeat_for expands all at once when the step is reached, not incrementally). [NO-REQ — explicitly out of scope]

## Definition of Complete

- [ ] `StepCondition` Pydantic model exists with `when: str | None` and `repeat_for: str | None` fields. [S-02/T-01/R1]
- [ ] `StepConfig.condition` field is optional and defaults to `None` (backward compatible). [S-02/T-01/R2, S-02/T-01/R3]
- [ ] `ConditionEvaluator` parses and evaluates all expression types (variable, output, literal, manual) without using `eval()`. [S-01/T-01/R1, S-01/T-02/R1, S-01/T-02/R3, S-01/T-02/R4]
- [ ] `ConditionEvalError` for syntax errors pauses the run with an error (not skip, not execute). [S-03/T-01/R3]
- [ ] `StepState` has `skipped: bool` and `skip_reason: str | None` fields. [S-02/T-02/R1]
- [ ] `StepModel` has `skipped` and `skip_reason` DB columns (via Alembic migration). [S-02/T-02/R2, S-02/T-02/R3]
- [ ] `check_step_progression()` evaluates conditions when advancing and marks steps as skipped when the condition is false. [S-03/T-01/R1]
- [ ] `repeat_for` expansion happens at runtime (when the engine reaches the step), not at run creation, so it can reference prior step outputs. [S-04/T-01/R1, S-04/T-01/R4, S-02/T-03/R2]
- [ ] When a step has both `repeat_for` and `when`, expansion happens first, then `when` is evaluated per copy. No agent work starts until a copy passes. [S-04/T-02/R4]
- [ ] `StepSkipped` event type exists and is emitted when a step is skipped. [S-02/T-03/R1, S-03/T-02/R3]
- [ ] Manual gate provides both execute and skip options on resume. [S-05/T-02/R1, S-06/T-03/R1, S-06/T-03/R2]
- [ ] `StepOutcome` includes `has_failures`, `all_passed`, `any_completed`, `completed`, and `skipped` properties. [S-01/T-01/R2]
- [ ] `StepSummary` API schema includes `skipped`, `skip_reason`, and `condition` fields. [S-05/T-01/R1]
- [ ] Frontend `StepTimeline` renders skipped steps with dashed border and dimmed opacity. [S-06/T-01/R3, S-06/T-02/R1]
- [ ] Frontend shows condition text for pending conditional steps. [S-06/T-02/R3]
- [ ] Frontend activity feed displays step skip events. [S-06/T-02/R4]
- [ ] Unit tests cover the condition evaluator (all expression types, edge cases, malicious input rejection). [S-01/T-04/R1, S-01/T-04/R2]
- [ ] Unit tests cover step skipping in `check_step_progression()`. [S-03/T-01/R1, S-03/T-02/R1]
- [ ] Integration tests cover conditional step runs via API. [S-03/T-03/R2, S-05/T-03/R1]
- [ ] Integration test covers `repeat_for` expansion. [S-04/T-03/R1, S-04/T-03/R2]
- [ ] Frontend tests cover skipped step display in `StepTimeline`. [S-06/T-04/R1]
- [ ] All existing tests continue to pass (no regressions). [S-01/T-04/R3, S-04/T-03/R3, S-05/T-03/R3]
- [ ] `uv run pre-commit run --all-files` passes. [NO-REQ — implicit quality gate, covered by auto_verify test commands in each step]
