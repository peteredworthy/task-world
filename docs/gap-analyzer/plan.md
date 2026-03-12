# Plan: Gap Analyzer + Targeted Retry

## Overview

Implement the gap analyzer in four milestones: (1) data models and enums, (2) engine lifecycle and action dispatch, (3) executor integration and API surface, (4) frontend display. Each milestone delivers independently testable functionality.

## Milestones

### M1: Data Models + Schema

**Goal:** Define all new types so the rest of the system can reference them, without touching the engine or executor yet.

**Deliverables:**
- `StepVerdict` enum (`PASS`, `RETRY`, `FIX`, `FAIL`) in `src/orchestrator/config/enums.py`
- `StepVerifierConfig` Pydantic model in `src/orchestrator/config/models.py` (`prompt: str`, `max_iterations: int = 3`, `auto_verify: AutoVerifyConfig | None = None`)
- `step_verifier: StepVerifierConfig | None = None` field on `StepConfig` (optional, backward compatible)
- `GapReport` Pydantic model in `src/orchestrator/state/models.py` (`id`, `iteration`, `assessment`, `verdict`, `actions: list[GapAction]`, `timestamp`)
- `GapAction` model (`type`: `retry_task` | `spawn_fix` | `pass` | `fail`, `task_id: str | None`, `title: str | None`, `feedback: str | None`, `context: str | None`, `requirements: list[RequirementConfig] | None`)
- `StepState` gains `verifying: bool = False`, `verifier_iterations: int = 0`, `gap_reports: list[GapReport] = []`
- `StepModel` gains `verifying` (Integer/bool, default 0) and `gap_reports` (JSON, default list) columns via Alembic migration
- `StepVerificationStarted`, `StepVerificationCompleted`, `GapReportGenerated` event types in `src/orchestrator/workflow/events.py`
- Unit tests: `GapReport` schema validation, `StepVerifierConfig` validation, event type construction

**Verification:** `uv run pytest tests/unit/ -v` passes, `uv run pyright` clean, existing tests unaffected.

### M2: Engine Lifecycle + Action Dispatch

**Goal:** Wire step verification into the workflow engine so the loop runs and actions are dispatched correctly.

**Deliverables:**
- `start_step_verification(run_id, step_id)` on `WorkflowEngine`:
  - Sets `step.verifying = True`, increments `verifier_iterations`
  - Emits `StepVerificationStarted`
  - Persists via `WorkflowService`
- `complete_step_verification(run_id, step_id, gap_report)` on `WorkflowEngine`:
  - Appends `gap_report` to `step.gap_reports`, emits `GapReportGenerated`
  - Dispatches actions:
    - `pass` → clear `verifying`, emit `StepVerificationCompleted`, call existing step completion path
    - `fail` → pause the run with reason `step_verifier_failed`
    - `retry_task` → reset target task to PENDING with feedback prepended; only allowed if task is COMPLETED; respects `max_attempts`
    - `spawn_fix` → create new `TaskState` in step with `spawned_by_gap_report=True`, `title`, and `requirements` from gap action; set to PENDING
  - If `verifier_iterations >= max_iterations`: treat as `fail` regardless of verdict
  - Emits `StepVerificationCompleted`
  - Persists state
- `check_step_progression()` in `transitions.py`: after all top-level tasks are terminal, if `step_verifier` configured and `verifying == False`, signal engine to call `start_step_verification()` instead of completing the step
- `WorkflowService` methods: persist/load `verifying`, `verifier_iterations`, `gap_reports` from `StepModel`
- Unit tests:
  - `start_step_verification` sets correct state
  - `complete_step_verification` with all four verdicts
  - `retry_task` on COMPLETED task → task reset to PENDING
  - `retry_task` on non-COMPLETED task → raises error / is rejected
  - `spawn_fix` → new task appears in step
  - max_iterations guard → auto-fail when limit reached
  - Iteration loop: two passes (retry → pass) completes step

**Verification:** `uv run pytest tests/unit/ tests/integration/ -v` passes.

### M3: Executor Integration + API Surface

**Goal:** Connect executor to the engine lifecycle so verifier agents are actually spawned, and expose verification data through the API.

**Deliverables:**
- Step verifier prompt in `src/orchestrator/workflow/prompts.py`:
  - Step context
  - Per-task summary: `config_id`, `title`, status, grades from last attempt, `auto_verify_results`
  - Auto-verify results from `StepVerifierConfig.auto_verify` (if any)
  - Required JSON output schema (`GapReport` shape) — agent must return this schema
- `src/orchestrator/runners/executor.py`:
  - After all tasks in a step reach terminal state, check if `step_verifier` is configured
  - Run `StepVerifierConfig.auto_verify` items first (reuse existing auto-verify runner)
  - Spawn the step verifier agent with the generated prompt
  - Parse JSON from agent output (use `json.loads`; fall back to `fail` verdict on parse error)
  - Call `service.complete_step_verification(run_id, step_id, gap_report)`
  - Loop: if actions include `retry_task` or `spawn_fix`, wait for those tasks to reach terminal state again, then re-enter verification
- `StepSummary` in `src/orchestrator/api/schemas/runs.py` gains:
  - `verifying: bool = False`
  - `verifier_iterations: int = 0`
  - `gap_reports: list[GapReportSchema] = []`
- `GapReportSchema` in API schemas: serialized form of `GapReport`
- Serialization in `_run_to_response()`: populate new fields from `StepModel`
- Integration tests:
  - Full lifecycle: all tasks complete → step verifier runs → `pass` → step completes
  - `retry_task`: task re-runs with feedback → step verifier re-runs → `pass`
  - `spawn_fix`: new task created, runs, completes → step verifier re-runs → `pass`
  - `fail` verdict → run paused
  - `max_iterations` guard → run paused after N iterations
  - Parse error in verifier output → run paused with error
  - GET run response includes `gap_reports` on step

**Verification:** `uv run pytest tests/integration/ -v` passes, API returns correct gap report data.

### M4: Frontend Display

**Goal:** Render step verification state and gap reports in the UI.

**Deliverables:**
- `ui/src/types/runs.ts`: add `GapReport`, `GapAction` types; add `verifying`, `verifier_iterations`, `gap_reports` to `StepSummary`
- `ui/src/lib/stepTimelineUtils.ts`: `getStepState()` returns `'verifying'` state; `stepBadgeClasses` entry for verifying (pulsing purple, similar to task verifying badge)
- `ui/src/components/dashboard/StepTimeline.tsx`: steps in verifying state get pulsing purple badge with iteration counter ("Verifying 2/3")
- Gap report card component (new or inline in `RunDetail.tsx`):
  - Assessment text
  - Verdict badge: green=pass, amber=retry/fix, red=fail
  - Action list: type, target task ID (linked), feedback/context
  - Iteration counter: "Iteration 2 of 3"
  - Collapsible: show all historical gap reports
- Fix-up tasks (`spawn_fix`): dashed border, "Fix-up" badge in step task list
- `ui/src/components/detail/ActivityFeed.tsx`: display `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` events with appropriate icons
- Frontend tests:
  - `StepTimeline` renders verifying badge for verifying steps
  - Gap report card renders assessment, verdict, action list
  - Fix-up task renders with "Fix-up" badge

**Verification:** `npx vitest run` passes, visual inspection of verifying state and gap reports.

## Implementation Order

### Step 1: Data Models (M1)
**Prerequisites:** None.
**Deliverables:** All new enums, Pydantic models, DB columns, event types, unit tests.

### Step 2: Engine Lifecycle (M2)
**Prerequisites:** Step 1 (models exist).
**Deliverables:** `start_step_verification`, `complete_step_verification`, `check_step_progression` changes, persistence, unit tests.

### Step 3: Executor + Prompts (M3 core)
**Prerequisites:** Steps 1-2 (engine lifecycle working).
**Deliverables:** Prompt generation, executor step verifier spawning and loop, JSON parsing.

### Step 4: API Surface + Integration Tests (M3 remaining)
**Prerequisites:** Step 3 (executor works end-to-end).
**Deliverables:** `StepSummary` schema changes, serialization, all integration tests.

### Step 5: Frontend (M4)
**Prerequisites:** Step 4 (API returns gap report data).
**Deliverables:** All frontend changes — types, timeline, gap report card, activity feed, tests.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Option D dependency | No (bespoke minimal spawning) | Option D is not implemented; `spawn_fix` creates `TaskState` directly with `max_iterations` as the only guard |
| JSON output from verifier | Required; `fail` on parse error | Structured output is essential for action dispatch; fail-safe on error prevents silent corruption |
| `retry_task` eligibility | COMPLETED tasks only | Aligns with idea spec; retrying failed tasks is outside the gap analyzer's purpose |
| Fan-out migration | Deferred | Architecture should permit it but it is not in scope now |
| Iteration limit reached | Auto-fail | Safest default; prevents infinite loops; user can adjust `max_iterations` in routine YAML |
| `spawn_fix` budget | None (max_iterations is guard) | No Option D; keep simple |
| Verifier agent type | Reuse existing agent runner for the step | Consistent with how task verifiers work; `step_verifier` uses same agent as tasks in the step |

## Risks and Unknowns

| Risk | Mitigation |
|------|------------|
| Verifier LLM produces invalid JSON | `json.loads` try/except → treat as `fail` verdict; log raw output for debugging |
| `retry_task` targeting a task that has exhausted `max_attempts` | Check before resetting; if exhausted, treat as `fail` (task can't be retried further) |
| `spawn_fix` tasks themselves failing | They count toward the iteration; if all tasks are terminal at the next check, verifier runs again |
| Step verifier loops without converging | `max_iterations` hard cap on the outer loop |
| DB migration on existing data | Default `verifying=False`, `gap_reports=[]` — safe additive migration |
| Fan-out parent verification path conflicts | `check_step_progression` must distinguish between normal steps (use new verifier path) and fan-out parent steps (leave existing path untouched) |
| Executor spawning step verifier concurrently with task agents | Verifier only spawns after ALL tasks are terminal; no concurrency concern |

## References

- [idea.md](idea.md) — Full feature specification
- `src/orchestrator/config/models.py` — `StepConfig`, `AutoVerifyConfig`
- `src/orchestrator/state/models.py` — `StepState`, `TaskState`, `Attempt`
- `src/orchestrator/db/models.py` — `StepModel`, `TaskModel`
- `src/orchestrator/workflow/transitions.py` — `check_step_progression()`
- `src/orchestrator/workflow/engine.py` — `WorkflowEngine`
- `src/orchestrator/workflow/service.py` — `WorkflowService`
- `src/orchestrator/workflow/events.py` — event types
- `src/orchestrator/workflow/prompts.py` — prompt generation
- `src/orchestrator/runners/executor.py` — agent spawning loop
- `src/orchestrator/api/schemas/runs.py` — `StepSummary`
