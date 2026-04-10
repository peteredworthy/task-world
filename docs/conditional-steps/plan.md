# Plan: Conditional Step Execution

## Overview

Implement conditional step execution in three milestones: (1) safe expression evaluator and backend models, (2) engine integration and API surface, (3) frontend display. Each milestone delivers testable, independently useful functionality.

## Milestones

### M1: Foundation — Condition Evaluator + Data Models

**Goal:** Build the safe expression evaluator and extend all data models so the system can represent conditional steps, even before the engine acts on them.

**Deliverables:**
- `StepCondition` Pydantic model (`when`, `repeat_for` fields) in `src/orchestrator/config/models.py`
- `condition` field on `StepConfig` (optional, backward compatible)
- `skipped` and `skip_reason` fields on `StepState` in `src/orchestrator/state/models.py`
- `skipped` and `skip_reason` columns on `StepModel` via Alembic migration
- `StepSkipped` event type in `src/orchestrator/workflow/events.py`
- `ConditionEvaluator` class in new file `src/orchestrator/workflow/condition_evaluator.py`
  - Recursive descent parser for: `==`, `!=`, `in`, `not in`, `and`, `or`, `not`
  - Variable resolution: `{{var}}` from run config, `steps.S-XX.has_failures`/`all_passed`/`any_completed`/`completed`/`skipped` from step outcomes
  - Literal support: strings, numbers, booleans, lists
  - Explicit rejection of unsafe patterns (no attribute access beyond allowed, no function calls)
  - `always`/`never`/`manual` as special keywords
  - Syntax errors raise `ConditionEvalError` (engine will pause the run)
- `StepOutcome` with five properties: `has_failures`, `all_passed`, `any_completed`, `completed`, `skipped`
- Unit tests for evaluator: all expression types, operator precedence, nested boolean logic, unknown variables, malicious input

**Verification:** `uv run pytest tests/unit/ -v` passes, `uv run pyright` clean, existing tests unaffected.

### M2: Engine Integration + API Surface

**Goal:** Wire condition evaluation into the workflow engine so steps are actually skipped or paused (manual gate), repeat-for steps are expanded at runtime, and expose skip state through the API.

**Deliverables:**
- `check_step_progression()` in `transitions.py` calls `ConditionEvaluator` when advancing to a new step
  - If condition is false → set `skipped=True`, `skip_reason=<expression>`, emit `StepSkipped`, advance to next
  - If condition is `manual` → pause the run with reason `manual_gate` (reuse existing pause mechanism)
  - If condition evaluation raises `ConditionEvalError` → pause the run with the error details so the routine can be fixed
  - Chain evaluation: if multiple consecutive steps are skipped, advance past all of them
- **Manual gate resume with skip option:** When a run is paused at a manual gate, the user can choose to execute the step (resume) or skip it (new skip-step API endpoint). This provides both options so users aren't forced to execute gated steps.
- **Runtime repeat-for expansion** in the workflow engine (not at creation time):
  - When the engine reaches a step with `repeat_for`, it resolves the variable name to a list from the run context (run config variables OR prior step outputs)
  - For each item, creates a `StepState` copy with unique ID (`{original_id}-{index}`), title suffix, and `item`/`item_index` variables
  - If the step also has a `when` condition, expansion happens first, then `when` is evaluated per iteration copy — no agent/LLM work starts until a copy's `when` condition passes
  - If the list is empty, the step is marked as skipped with reason "empty list"
  - Replaces the single step with N copies in the run's step list and persists the change
- `StepSummary` in `src/orchestrator/api/schemas/runs.py` gains `skipped`, `skip_reason`, `condition` fields
- `RunResponse` serialization includes skip data from `StepModel`
- State persistence: `WorkflowService` saves/loads `skipped` and `skip_reason` from DB
- Integration tests: full lifecycle with conditional steps (skip, execute, manual gate with execute and skip options)
- Integration test: `repeat_for` creates correct number of step copies with correct variables (both from run config and from prior step outputs)

**Verification:** `uv run pytest tests/integration/ -v` passes, API returns correct skip data.

### M3: Frontend Display

**Goal:** Render conditional step state in the UI so users can see which steps were skipped, why, and what conditions pending steps have.

**Deliverables:**
- `StepTimeline.tsx`: skipped steps get dashed border, dimmed opacity, "Skipped" badge
- `stepTimelineUtils.ts`: `getStepState()` returns `'skipped'` state; `stepBadgeClasses` entry for skipped
- Tooltip on skipped steps shows `skip_reason`
- Pending conditional steps show condition expression text (e.g., "Runs if complexity = high")
- `repeat_for` iterations render as sub-items under the parent step badge (similar to fan-out children)
- `runs.ts` types: `StepSummary` gets `skipped`, `skip_reason`, `condition` fields
- `ActivityFeed.tsx`: `StepSkipped` events display with skip icon and reason
- Manual gate UI: when paused at a manual gate, show both "Execute Step" and "Skip Step" buttons
- Frontend tests for skipped step rendering in StepTimeline

**Verification:** `npx vitest run` passes, visual inspection of skipped/conditional steps.

## Implementation Order

### Step 1: Safe Evaluator (M1 core)
**Prerequisites:** None — pure function, no dependencies.
**Deliverables:** `ConditionEvaluator` class + unit tests. This is the highest-risk component (expression parsing) so it's built and tested first in isolation.

### Step 2: Data Model Extensions (M1 remaining)
**Prerequisites:** Step 1 (evaluator exists to reference in type annotations).
**Deliverables:** `StepCondition` model, `StepConfig.condition` field, `StepState` skip fields, `StepModel` migration, `StepSkipped` event, `StepOutcome` with 5 properties. All model changes in one step to avoid multiple migrations.

### Step 3: Engine Wiring (M2 core)
**Prerequisites:** Steps 1-2 (evaluator + models).
**Deliverables:** `check_step_progression()` changes, chain-skip logic, manual gate pause, condition syntax error → pause, `WorkflowService` persistence, integration tests for conditional execution.

### Step 4: Runtime Repeat-For Expansion (M2)
**Prerequisites:** Steps 1-3 (models + engine).
**Deliverables:** Runtime expansion logic in the engine when reaching a repeat-for step. Variable resolution from run config AND prior step outputs. Per-copy `when` evaluation. Integration test for repeat-for.

### Step 5: Manual Gate Skip Option + API Surface (M2 remaining)
**Prerequisites:** Steps 2-3 (models + engine).
**Deliverables:** Skip-step API endpoint for manual gates, `StepSummary` schema changes, serialization, API integration test.

### Step 6: Frontend (M3)
**Prerequisites:** Step 5 (API returns skip data).
**Deliverables:** All frontend changes — timeline, tooltips, activity feed, manual gate execute/skip buttons, types, tests.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Expression parser approach | Custom recursive descent | No external dependencies; full control over allowed operations; straightforward to audit for safety |
| repeat_for expansion timing | At runtime (when engine reaches the step) | Enables referencing prior step outputs (e.g., list of files found by step 1); more powerful than static expansion; user explicitly chose this over simpler static approach |
| repeat_for + when combo | Expand first, evaluate `when` per copy | No agent/LLM work starts until a copy's condition passes; programmatic evaluation only |
| repeat_for step IDs | `{parent_id}-{index}` | Preserves traceability to source step config; avoids collisions |
| Manual gate implementation | Reuse existing pause mechanism + skip option | `pause_run(reason="manual_gate")` avoids new state machine transitions; user can choose to execute or skip the gated step on resume |
| Condition evaluation timing | On step advancement in `check_step_progression()` | Evaluated lazily (not at run creation) so output-based conditions can reference completed steps |
| Condition syntax error handling | Pause the run with error | Safest option — lets user fix the routine; no silent skip or forced execution of potentially wrong step |
| Skipped step persistence | Dedicated DB columns | Simpler than encoding in a JSON state blob; queryable for reporting |
| Step outcome properties | 5 properties: `has_failures`, `all_passed`, `any_completed`, `completed`, `skipped` | `completed` and `skipped` added per user request; enables richer output-based conditions |

## Risks and Unknowns

| Risk | Mitigation |
|------|------------|
| Expression parser edge cases (injection, infinite loops) | Extensive unit tests with adversarial input; hard token limit on expression length; no recursion beyond fixed depth |
| Chain-skipping all steps (every step's condition is false) | Handle gracefully: complete the run with no work done; emit warning event |
| repeat_for with empty list | Treat as skip (no iterations, step marked skipped with reason "empty list") |
| Output-based conditions for not-yet-executed steps | Return `None`/falsy for missing step outcomes; document that output conditions only work for prior steps |
| DB migration on existing data | Default `skipped=False`, `skip_reason=None` for all existing rows; safe additive migration |
| Runtime repeat-for mutates step list mid-run | Must persist expanded steps to DB immediately; engine must handle step count changing; step index tracking must account for inserted steps |
| Prior step outputs may not be structured as expected | Validate that `repeat_for` resolves to a list; if not, pause the run with an error (consistent with syntax error handling) |

## References

- [idea.md](idea.md) — Full feature specification
- [Option C presentation](../presentations/orchestration-directions.html) — Architecture research context
- `src/orchestrator/workflow/transitions.py` — Step progression logic
- `src/orchestrator/workflow/engine.py` — Workflow state machine
- `src/orchestrator/config/models.py` — Step/task configuration models
- `src/orchestrator/state/factory.py` — Run creation from routine
