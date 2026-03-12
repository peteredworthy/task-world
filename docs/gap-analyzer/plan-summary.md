# Plan Summary: Gap Analyzer + Targeted Retry

**Date**: 2026-03-12
**Status**: Ready to Implement

---

## Intent Satisfaction Summary

The implementation plan fully satisfies the original intent: add a step-level verification agent (Option B) that runs after all tasks in a step reach terminal state, examines their combined output, and takes targeted recovery actions.

All 21 items in the "Definition of Complete" checklist from `intent.md` are addressed across the five steps. The plan closes the integration-gap blind spot that previously allowed individually-passing tasks to leave mismatched API contracts and inconsistent interfaces undetected.

Scope boundaries are respected:
- Option D (orchestrated expansion) remains deferred; `spawn_fix` uses bespoke minimal spawning
- Fan-out parent step path is untouched
- Manual re-verification API is out of scope for MVP
- Phase pipelines (Option A) and conditional steps (Option C) are unaffected

---

## Ordered Step List

| Step | Name | Tasks | Key Outputs |
|------|------|-------|-------------|
| 1 | Data Models + Schema | 4 | `StepVerdict` enum, `StepVerifierConfig`, `GapReport`, `GapAction`, `StepState` fields, DB migration (5 new columns), 3 event types, unit tests |
| 2 | Engine Lifecycle + Action Dispatch | 4 | `start_step_verification()`, `complete_step_verification()`, `retry_task` and `spawn_fix` dispatch, `repositories.py` persistence, engine unit tests |
| 3 | Executor + Prompts | 2 | `build_step_verifier_prompt()`, executor loop wiring (`_run_step_verification()`), JSON parse fallback |
| 4 | API Surface + Integration Tests | 3 | `GapReportSchema`, `StepSummary` + `TaskSummary` extensions, `_run_to_response()` serialization, 8 integration test scenarios |
| 5 | Frontend Display | 4 | TypeScript types, verifying badge in `StepTimeline`, `GapReportCard` component, fix-up task display, activity feed event handlers, frontend tests |

**Total tasks: 17 across 5 steps**

Each step has hard dependencies on the previous (the order is strictly sequential). Steps cannot be parallelized.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Option D dependency | No — bespoke minimal spawning | Option D not implemented; `spawn_fix` creates `TaskState` directly; `max_iterations` is the only guard |
| JSON output from verifier | Required; `fail` verdict on parse error | Structured output essential for action dispatch; fail-safe prevents silent corruption |
| `retry_task` eligibility | COMPLETED tasks only (not FAILED) | Aligns with intent spec; retrying failed tasks is outside the gap analyzer's purpose |
| `retry_task` current_attempt reset | Do NOT reset | Keeps `max_attempts` semantics correct; next `start_task` call increments and checks the limit |
| Fan-out migration | Deferred | Architecture should permit it eventually; not in scope now |
| Iteration limit reached | Auto-fail | Safest default; prevents infinite loops; user can adjust `max_iterations` in routine YAML |
| `spawn_fix` budget | None (`max_iterations` is guard) | No Option D; keep simple |
| Verifier agent type | Reuse same agent runner as step tasks | Consistent with how task verifiers work |
| Executor loop ownership | Executor manages step verification loop end-to-end | `check_step_progression()` is NOT modified; executor directly calls `start_step_verification()` when step_verifier configured and all tasks terminal |
| DB boolean columns | `Integer` (0/1) | Matches existing pattern (`StepModel.completed`); coerce to `bool` on read |

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation Applied |
|------|-----------|-------------------|
| Verifier LLM produces invalid JSON | HIGH | `json.loads` try/except → `fail`-verdict `GapReport` with `assessment = "Parse error: {e}"`; raw output logged at WARNING |
| `retry_task` targeting exhausted task (`current_attempt >= max_attempts`) | MEDIUM | Check before reset; treat as `fail` verdict; run paused with `step_verifier_failed` |
| `spawn_fix` tasks themselves failing | MEDIUM | They count toward the iteration; verifier re-runs when they reach terminal state |
| Step verifier loops without converging | HIGH | `max_iterations` hard cap on outer loop; exceeded → auto-fail with `step_verifier_max_iterations` |
| DB migration on existing data | LOW | Additive migration only; defaults: `verifying=0`, `verifier_iterations=0`, `gap_reports=[]`, `spawned_by_gap_report=0`, `gap_report_feedback=NULL` |
| Fan-out parent step conflicts | MEDIUM | Inline check `any(t.status == FAN_OUT_RUNNING for t in step.tasks)`; skip verification if fan-out parent |
| Executor spawning verifier concurrently with task agents | LOW | Verifier only spawns after ALL tasks are terminal; no concurrency concern |
| `routine_embedded` None at verification time | MEDIUM | Step 3 guard: only enter verification if `run.routine_embedded is not None` |
| Event type string mismatch frontend/backend | MEDIUM | Step 1 specifies exact snake_case values; Step 5 references them explicitly |

---

## Caveats for Execution

### Persistence Stack Must Be Complete Before Engine Tests

All five new DB columns (`verifying`, `verifier_iterations`, `gap_reports`, `spawned_by_gap_report`, `gap_report_feedback`) must be in place before Step 2 tests run. These are defined in Step 1 Task 3 and wired in Step 2 Task 4 (`repositories.py`). Do not skip the Alembic migration.

### Never Run `rm orchestrator.db`

If pre-commit tests fail due to missing DB columns, the correct fix is to run `uv run alembic upgrade head`, not to delete the database. The main `orchestrator.db` contains live run data.

### Git Operations Must Stay in Worktree

All `git` commands (including `alembic revision --autogenerate`) must be run from within the worktree directory (`worktrees/r23/`), never from the main project root (`/Users/peter/code/task-world`).

### `check_step_progression()` Must Not Be Modified

This function handles step advancement for normal (non-verifier) steps. The verification path is added exclusively in the executor. Any diff to `transitions.py` is a regression. Step 2 Task 4 explicitly checks for this.

### Integration Tests Use In-Memory DB

Test fixtures use `create_all` (not Alembic migrations). New columns must be added to the ORM models in `db/models.py` for the in-memory test DB to include them. If a test fails with "no such column", confirm the ORM model attribute exists (not just the migration).

### `gap_report_feedback` Must Be Cleared After Use

After the builder phase uses `task.gap_report_feedback` (injecting it into the prompt), the field must be reset to `None`. This prevents stale feedback from appearing in subsequent retries. Step 3 Task 2 covers the clearing mechanism.

### React Fast Refresh Constraint

`GapReportCard` (Step 5 Task 3) must export only the component — no utility functions mixed in the same file. This is a project-wide constraint documented in MEMORY.md.

### Routine YAML for Testing

The existing `routines/demo-task.yaml` does not include a `step_verifier` block. Integration tests construct routine configs programmatically (in-memory). Any manual end-to-end test will need a new or modified routine YAML with a `step_verifier` block.

---

## Dry-Run Gap Summary

A pre-implementation dry-run identified 14 gaps in the original step files. All 14 were applied to the step files before this plan was finalized:

- **Gap 1**: `verifier_iterations` DB column missing → added to Step 1 Task 3
- **Gap 2**: `spawned_by_gap_report` missing from persistence stack → added across Steps 1–4
- **Gap 3**: `gap_report_feedback` missing from persistence stack → added across Steps 1–3
- **Gap 4**: Step completion path underspecified → exact function call pattern added to Step 2 Task 2
- **Gap 5**: Executor insertion point underspecified → exact location added to Step 3 Task 2
- **Gap 6**: "spawn verifier agent" mechanism underspecified → full `_run_step_verification()` pattern added
- **Gap 7**: Integration test mock strategy missing → two-track approach specified in Step 4 Task 3
- **Gap 8**: Integration test assertions missing → concrete `assert` statements added to all 8 scenarios
- **Gap 9**: `max_iterations` validator instruction missing → `@field_validator` example added to Step 1 Task 1
- **Gap 10**: `spawned_by_gap_report` missing from `TaskSummary` API schema → added to Step 4 Task 1
- **Additional**: `spawn_fix` requirements → checklist conversion unspecified → explicit `ChecklistItem` loop added
- **Additional**: `event_type` string values not specified → snake_case values documented in Step 1 Task 4
- **Additional**: Fan-out parent check function doesn't exist → inline `any(...)` check specified
- **Additional**: `retry_task` `current_attempt` behavior unclear → explicit "do NOT reset" guidance added

The verification report confirms all 14 gaps are applied. No unresolved conflicts remain. The step files are execution-ready.
