# Option B: Gap Analyzer + Targeted Retry

## Idea

Add a step-level verification agent that runs after all tasks in a step complete, examines the combined output, and can take targeted recovery actions — retrying specific tasks with feedback, or spawning new fix-up tasks for integration gaps between tasks. Currently, step completion is all-or-nothing: if any task fails, the step fails. There's no mechanism for a verifier to identify which specific task caused the problem and selectively retry just that task, or to notice that two individually-passing tasks don't integrate correctly.

This is the same pattern as fan-out parent verification (check all children, decide composite pass/fail) but generalized to any step.

## What to Build

### 1. Step Verifier Configuration

Steps gain an optional `step_verifier` block:

```yaml
steps:
  - id: S-02
    title: "Implement feature"
    tasks: [T-01, T-02, T-03]
    step_verifier:
      prompt: |
        Review all task outputs as a combined unit. Check for:
        - Integration gaps between components
        - Inconsistent interfaces or contracts
        - Missing cross-cutting concerns
      max_iterations: 3
      auto_verify:
        items:
          - id: "integration_tests"
            cmd: "uv run pytest tests/integration/ -q"
            must: true
```

### 2. Step Verification Flow

After all top-level tasks in a step reach terminal state (completed or failed):
1. If `step_verifier` is configured, the step transitions to a new state: `STEP_VERIFYING`
2. Auto-verify commands run first (if any)
3. The step verifier LLM agent is spawned with a prompt that includes:
   - The step context
   - A summary of each task's outcome (what was built, grades received)
   - Artifacts produced by each task
   - Auto-verify results
4. The verifier produces a structured **gap report** (JSON)
5. Based on the gap report, the engine takes action

### 3. Gap Report Schema

The step verifier LLM must return structured JSON:

```json
{
  "assessment": "Human-readable summary of the combined output quality",
  "verdict": "pass" | "retry" | "fix" | "fail",
  "actions": [
    {
      "type": "retry_task",
      "task_id": "T-02",
      "feedback": "The API paths don't match what T-01 exports. Update to use /api/v2/..."
    },
    {
      "type": "spawn_fix",
      "title": "Align API contract between auth and UI",
      "context": "Detailed description of the fix needed...",
      "requirements": [
        {"desc": "API paths consistent between modules", "priority": "critical"}
      ]
    }
  ]
}
```

### 4. Action Types

- **pass**: Combined output is acceptable. Step proceeds to completion.
- **retry_task**: Re-run a specific task with targeted feedback. The task gets a new attempt with the step verifier's feedback prepended to its prompt. Only tasks that are COMPLETED (not failed) can be retried this way. This respects the task's own max_attempts.
- **spawn_fix**: Create a new task in the step to address an integration gap. This uses the **Option D expansion API** (specifically `add_peer_task`). The fix-up task goes through the full build/verify pipeline.
- **fail**: The combined output is unrecoverable. Step fails, run pauses.

### 5. Iteration Loop

The step verifier runs in a loop:
1. All tasks complete → step verifier runs → produces gap report
2. If actions include retry/fix → those tasks execute → all tasks complete again
3. Step verifier runs again (iteration 2) → produces new gap report
4. Repeat until: verdict is "pass", verdict is "fail", or max_iterations reached

Track iterations to prevent infinite loops. Display iteration count in UI.

### 6. Unifying with Fan-Out Parent Verification

Currently, fan-out parent verification is a separate code path in the executor. With the step verifier, fan-out parent verification becomes a special case:
- The fan-out parent's verifier rubric is essentially a step-level check on the children's combined output
- The retry/spawn actions map to resetting fan-out children or adding new ones

This doesn't need to be a hard requirement of this option, but the architecture should be designed so that fan-out parent verification can eventually be migrated to use the step verifier infrastructure.

## Codebase Context

Key files:

- **Config models** (`src/orchestrator/config/models.py`): Add `StepVerifierConfig` model with `prompt: str`, `max_iterations: int = 3`, `auto_verify: AutoVerifyConfig | None = None`. Add `step_verifier` field to `StepConfig`.
- **State models** (`src/orchestrator/state/models.py`): Add to `StepState`: `verifier_iterations: int = 0`, `gap_reports: list[GapReport] = []`, `verifying: bool = False`. Create `GapReport` model with `iteration`, `assessment`, `verdict`, `actions`, `timestamp`.
- **DB models** (`src/orchestrator/db/models.py`): Add `gap_reports` JSON column to `StepModel`. Add `verifying` boolean column.
- **Enums** (`src/orchestrator/config/enums.py`): May want a `StepVerdict` enum: `PASS`, `RETRY`, `FIX`, `FAIL`.
- **Workflow transitions** (`src/orchestrator/workflow/transitions.py`): `check_step_progression()` currently checks if all tasks are terminal and advances. With step verifier: if step has `step_verifier` and hasn't been verified yet, transition step to `STEP_VERIFYING` instead of completing.
- **Workflow engine** (`src/orchestrator/workflow/engine.py`): Add step verifier lifecycle methods: `start_step_verification()`, `complete_step_verification(gap_report)`. Handle the retry/fix/pass/fail actions. For `retry_task`: call existing `start_task()` with feedback. For `spawn_fix`: call the expansion API (Option D) or create task directly if D isn't implemented yet.
- **Workflow service** (`src/orchestrator/workflow/service.py`): Add step verifier service methods wrapping engine calls with persistence.
- **Executor** (`src/orchestrator/runners/executor.py`): Add step verifier agent spawning. After all tasks in a step complete, if step has verifier config, spawn the step verifier agent. Parse structured JSON from verifier output. Dispatch actions.
- **Prompts** (`src/orchestrator/workflow/prompts.py`): Add step verifier prompt generation. Include: step context, per-task summaries (outcome, artifacts, grades), auto-verify results, gap report schema for structured output.
- **Events** (`src/orchestrator/workflow/events.py`): Add `StepVerificationStarted`, `StepVerificationCompleted`, `GapReportGenerated` event types.
- **API schemas** (`src/orchestrator/api/schemas/runs.py`): Add gap report data to `StepSummary`. Add step verification status.
- **API routers**: May need an endpoint to manually trigger step re-verification or to view gap reports.

### Frontend Changes

- **Step timeline** (`ui/src/components/dashboard/StepTimeline.tsx`): Steps in `STEP_VERIFYING` state need a visual indicator — perhaps a pulsing purple badge (similar to task verifying state). The `getStepState()` function needs a `'verifying'` state.
- **Step detail area**: When a step is being verified or has been verified, show the gap report. This is a new section in the run detail page:
  - Gap report card with assessment text, verdict badge, and action list
  - Each action shows: type (retry/fix/spawn), target task, feedback/context
  - Iteration counter: "Iteration 2 of 3"
  - Color-coded verdict: green=pass, amber=retry/fix, red=fail
- **Fix-up tasks**: Tasks spawned via `spawn_fix` should be visually distinct in the step — dashed border, "Fix-up" badge, linked to the gap report that spawned them. If Option D is implemented, these use the expansion display. If not, they need their own visual treatment.
- **Activity feed** (`ui/src/components/detail/ActivityFeed.tsx`): Step verification events should be prominent — show when verification started, gap report details, actions taken.
- **Types** (`ui/src/types/runs.ts`): `StepSummary` needs `verifying: boolean`, `gap_reports: GapReport[]`, `verifier_iterations: number`. Create `GapReport` type with `iteration`, `assessment`, `verdict`, `actions[]`.
- **Run detail** (`ui/src/pages/RunDetail.tsx`): After a step completes, if it has gap reports, show them in a collapsible section. Show the progression: iteration 1 → found gaps → retry → iteration 2 → passed.

### Integration with Option D (Expansion)

If Option D is implemented before this (recommended), then:
- `spawn_fix` action calls the expansion API (`add_peer_task`)
- Budget limits from D apply
- Provenance tracking from D applies
- UI from D (expansion badges) is reused

If Option D is NOT implemented, the step verifier needs a minimal version of task spawning:
- Create new TaskState directly in the step's task list
- No budget system (just max_iterations as guard)
- Simpler provenance tracking

The plan should account for both paths but prefer the Option D integration.

## Relationship to Other Options

- **Requires Option D** (ideally): spawn_fix uses expansion API. Can work without D but needs bespoke spawning.
- **Independent of Option C** (conditional steps)
- **Independent of Option A** (phase pipelines)

## Tests

- Unit tests for gap report schema validation
- Unit tests for step verifier lifecycle in engine (start, complete, iterate)
- Unit tests for action dispatch (retry_task, spawn_fix, pass, fail)
- Integration tests for step verification via API
- Integration test for retry_task action (specific task gets new attempt with feedback)
- Integration test for spawn_fix action (new task created and verified)
- Integration test for iteration loop (verify → fix → re-verify → pass)
- Integration test for max_iterations guard
- Frontend tests for gap report display
- Frontend tests for step verifying state in timeline
