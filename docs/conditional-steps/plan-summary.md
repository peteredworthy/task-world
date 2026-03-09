# Execution Summary: Conditional Step Execution

## Intent Satisfaction

The plan fully addresses the original intent: enabling steps to be conditionally skipped or repeated so a single routine template can serve multiple workflows. Every element from the intent document is covered:

- **Step conditions** (`when` field) — Covered by Steps 1-3. The `ConditionEvaluator` (Step 1) parses expressions safely; data models (Step 2) store condition config and skip state; the engine (Step 3) evaluates conditions during step advancement.
- **Step repeat** (`repeat_for` field) — Covered by Step 4. Runtime expansion when the engine reaches the step, supporting both run config variables and prior step outputs. Per-copy `when` evaluation ensures no agent work starts until a copy's condition passes.
- **Safe condition evaluator** — Step 1. Custom recursive descent parser with no `eval()`, 500-char limit, 10-level depth cap, allowlisted attribute access only.
- **Skip tracking** — Step 2 (models + DB columns + events) and Step 3 (engine sets skip state).
- **Manual gate** — Steps 3 and 5. Pause on `when: "manual"`, with both execute (resume) and skip (new endpoint) options.
- **Step outcome properties** — Step 1. Five properties: `has_failures`, `all_passed`, `any_completed`, `completed`, `skipped`.
- **Frontend changes** — Step 6. Dashed border/dimmed opacity for skipped steps, condition text on pending steps, repeat-for sub-items, skip events in activity feed, manual gate execute/skip buttons.
- **Backward compatibility** — All steps. Steps without a `condition` block default to `when: "always"`.

All five user clarifications (Q1-Q5) are integrated across intent, plan, architecture, and step files.

## Ordered Step List

| Step | Title | Tasks | Milestone | Risk |
|------|-------|-------|-----------|------|
| 1 | Safe Condition Evaluator | 4 | M1 | Low-Medium |
| 2 | Data Model Extensions | 3 | M1 | Medium |
| 3 | Engine Wiring | 3 | M2 | High |
| 4 | Runtime Repeat-For Expansion | 3 | M2 | High |
| 5 | Manual Gate Skip Option + API Surface | 3 | M2 | Medium |
| 6 | Frontend Display | 4 | M3 | Medium |

**Total: 6 steps, 20 tasks across 3 milestones.**

### Dependencies
- Step 1 has no prerequisites (greenfield module).
- Step 2 depends on Step 1 (references `StepOutcome`, `ConditionEvalError`).
- Step 3 depends on Steps 1-2 (evaluator + models).
- Step 4 depends on Steps 1-3 (models + engine wiring).
- Step 5 depends on Steps 2-3 (models + manual gate pause mechanism).
- Step 6 depends on Step 5 (API returns skip data).

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Expression parser | Custom recursive descent | No external dependencies; full control over allowed operations; auditable security surface |
| `repeat_for` expansion timing | Runtime (when engine reaches the step) | Enables referencing prior step outputs; user explicitly chose power over simplicity (Q4) |
| `repeat_for` + `when` combo | Expand first, evaluate `when` per copy | No agent/LLM work starts until a copy's condition passes; programmatic only (Q2) |
| Manual gate behavior | Execute or skip on resume | User can choose to execute the gated step or skip it (Q1) |
| Condition syntax errors | Pause the run with error | Safest option — lets user fix the routine; no silent skip or forced execution (Q3) |
| Step outcome properties | 5 properties (+ `completed`, `skipped`) | Enables richer output-based conditions (Q5) |
| Skipped step persistence | Dedicated DB columns | Simpler than JSON blob; queryable; type-safe |
| Condition evaluation timing | On step advancement (lazy) | Output-based conditions can reference completed steps |
| repeat_for step IDs | `{parent_id}-{index}` | Preserves traceability; avoids collisions |

## Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Modifying `check_step_progression()` breaks existing run progression | All runs affected | High | Agent must read all callers and understand return-value contract before modifying; integration tests verify existing behavior |
| Step list mutation (repeat-for) breaks index tracking | Runs with repeat-for get stuck or skip wrong steps | High | Assert `current_step_index` correctness after expansion; persist expanded steps atomically; integration tests verify indices |
| "Prior step output" concept may not exist in codebase | repeat-for can't reference prior step outputs | High | Fallback: add `outputs: dict[str, Any]` to `StepState` if missing |
| Expression parser edge cases (injection, `not in` ambiguity) | Malformed conditions cause errors or security issues | Medium | Extensive unit tests with adversarial input; `not in` handled as single token via lookahead; hard limits on length and depth |
| Alembic migration environment misconfigured | DB schema changes blocked | Medium | Pre-check with `alembic heads`; fallback to manual migration with `op.add_column()` |
| Confusion between existing `evaluate_transition_conditions()` and new `ConditionEvaluator` | Wrong system wired, incorrect behavior | Medium | Different names and purposes documented: existing handles backward transitions (loops), new handles forward skip/execute decisions |
| Chain-skipping all steps | Run completes with no work | Low | Handle gracefully: complete the run, emit warning event |
| `repeat_for` with empty list | Unexpected skip | Low | Treat as skip with reason "empty list" |
| Runtime expansion + server restart mid-expansion | Inconsistent step list | Low | Persist expanded steps in a single DB transaction |

## Caveats for Execution

1. **Step 3 is the highest-risk step.** It modifies the core step progression logic that affects ALL runs. The implementing agent must deeply understand the existing call chain (engine -> transitions -> service) before making changes.

2. **Step 4 may require defining a new concept.** If `StepState` doesn't have an `outputs` field for prior step outputs, the agent must add one. This expands the scope but is well-defined in the dry-run notes.

3. **Steps 3 and 4 are the most likely to need revision cycles.** Both involve engine-level changes with subtle index management and state mutation. Budget for at least one revision per step.

4. **Alembic vs `create_all`**: The codebase uses `create_all` for dev (deleting and recreating the DB). The Alembic migration should still be created for production use, but dev testing may require `rm orchestrator.db && seed_db.py`.

5. **No nested `repeat_for`**: Only single-level iteration is supported. Nested repeat (repeat inside repeat) is explicitly out of scope.

6. **No dynamic step insertion**: Conditions can skip or repeat existing steps but cannot add new steps that weren't in the original routine.

7. **Output-based conditions are order-dependent**: `steps.S-XX.has_failures` only works for steps that have already executed. Referencing a future step's outcome returns falsy (undefined behavior is documented but could surprise routine authors).

8. **Frontend grouping for repeat-for**: Expanded steps are flat in the API response (each copy is a separate step with ID `{parent_id}-{N}`). The frontend must detect and group these by ID pattern — this grouping algorithm is specified in the architecture doc but not trivial to implement.

9. **Pre-commit and test baselines**: All existing tests (565 backend + 221 frontend = 786 total) must continue to pass. Each step should verify no regressions before proceeding.
