# Intent: Gap Analyzer + Targeted Retry

## Original Request

Add a step-level verification agent (Option B) that runs after all tasks in a step reach terminal state, examines their combined output, and takes targeted recovery actions — retrying specific tasks with feedback or spawning fix-up tasks for integration gaps between tasks.

## Goal

Enable a step to self-heal integration failures that slip past per-task verification. Currently, tasks are verified in isolation; tasks that each pass individually can still leave integration gaps (mismatched API contracts, inconsistent interfaces). The gap analyzer closes this blind spot by checking the combined output as a unit and acting on what it finds.

## Scope

### In Scope

- **`StepVerifierConfig`** — new optional block on `StepConfig` with `prompt: str`, `max_iterations: int = 3`, `auto_verify: AutoVerifyConfig | None = None`. Steps without this block are unaffected.
- **Step verification state** — `StepState` gains `verifying: bool`, `verifier_iterations: int`, and `gap_reports: list[GapReport]` fields. `StepModel` gains `gap_reports` (JSON) and `verifying` (boolean) columns via Alembic migration.
- **`GapReport` model** — structured result of one verification pass: `iteration`, `assessment` (text), `verdict` (`pass` | `retry` | `fix` | `fail`), `actions` list, `timestamp`.
- **`StepVerdict` enum** — `PASS`, `RETRY`, `FIX`, `FAIL` in `config/enums.py`.
- **Verification loop** — engine method `start_step_verification()` / `complete_step_verification(gap_report)`. Loop: all tasks terminal → run step verifier → apply actions → wait for re-triggered tasks → repeat. Capped at `max_iterations`.
- **`retry_task` action** — re-run a specific completed task with the gap report's feedback prepended to its prompt. Respects the task's own `max_attempts`.
- **`spawn_fix` action** — create a new `TaskState` directly in the step's task list (minimal bespoke spawning since Option D is not yet implemented). No budget system; `max_iterations` acts as the guard. Provenance tracked via `spawned_by_gap_report` flag on the task.
- **`pass` / `fail` actions** — pass advances the step to completion; fail pauses the run.
- **Events** — `StepVerificationStarted`, `StepVerificationCompleted`, `GapReportGenerated` event types.
- **Prompts** — step verifier prompt generation in `workflow/prompts.py`: step context, per-task outcome summaries (status, grades, artifacts), auto-verify results, required output schema.
- **Executor integration** — after all tasks in a step complete, if `step_verifier` is configured, executor spawns the step verifier agent, parses structured JSON from output, dispatches actions.
- **API surface** — `StepSummary` gains `verifying`, `verifier_iterations`, `gap_reports` fields.
- **Frontend** — `StepTimeline` visual indicator for `STEP_VERIFYING` state (pulsing purple badge), gap report card in run detail (assessment, verdict, actions, iteration counter), fix-up tasks shown with "Fix-up" badge, activity feed events for verification.
- **Tests** — unit tests for gap report schema validation, lifecycle, action dispatch; integration tests for full verification flow, retry_task, spawn_fix, iteration loop, max_iterations guard; frontend tests.

### Out of Scope

- Option D (orchestrated expansion / `add_peer_task`) — `spawn_fix` uses bespoke minimal spawning; budget enforcement and full provenance tracking from Option D are deferred.
- Migrating fan-out parent verification to use the step verifier infrastructure — architecture should allow it eventually but it is not required now.
- Phase pipelines (Option A) — independent effort.
- Conditional steps (Option C) — already implemented; no changes needed.
- Step verifier access to prior-step outputs across multiple steps — step verifier only sees its own step's tasks.
- Manual trigger of step re-verification via API — not needed for MVP; re-verification is automatic per the loop.

## Definition of Complete

- [ ] `StepVerifierConfig` Pydantic model exists with `prompt`, `max_iterations`, `auto_verify` fields.
- [ ] `step_verifier` field added to `StepConfig` (optional, backward compatible; steps without it behave identically to today).
- [ ] `GapReport` Pydantic model exists with `iteration`, `assessment`, `verdict`, `actions`, `timestamp` fields.
- [ ] `StepVerdict` enum exists with `PASS`, `RETRY`, `FIX`, `FAIL` values.
- [ ] `StepState` has `verifying: bool = False`, `verifier_iterations: int = 0`, `gap_reports: list[GapReport] = []` fields.
- [ ] `StepModel` has `verifying` (boolean) and `gap_reports` (JSON) columns via Alembic migration.
- [ ] `start_step_verification()` and `complete_step_verification(gap_report)` exist on the engine.
- [ ] `retry_task` action re-runs the target task with feedback prepended; task must be in COMPLETED state.
- [ ] `spawn_fix` action creates a new `TaskState` in the step; marked with provenance.
- [ ] `pass` action advances the step to completion.
- [ ] `fail` action pauses the run.
- [ ] `max_iterations` guard prevents infinite loops.
- [ ] `StepVerificationStarted`, `StepVerificationCompleted`, `GapReportGenerated` event types exist and are emitted.
- [ ] Step verifier prompt includes per-task outcome summaries and required JSON schema.
- [ ] Executor spawns step verifier agent after all tasks are terminal (if configured) and parses JSON output.
- [ ] `StepSummary` API schema includes `verifying`, `verifier_iterations`, `gap_reports`.
- [ ] Frontend `StepTimeline` shows pulsing purple badge for verifying steps.
- [ ] Frontend gap report card shows assessment, verdict, actions, iteration counter.
- [ ] Fix-up tasks (`spawn_fix`) display with "Fix-up" badge in step task list.
- [ ] Activity feed displays `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` events.
- [ ] Unit tests for gap report validation, lifecycle methods, action dispatch (all four verdicts).
- [ ] Integration tests for full flow: verify → retry → re-verify → pass; max_iterations guard; spawn_fix creates runnable task.
- [ ] Frontend tests for verifying state in timeline and gap report display.
- [ ] All existing tests continue to pass (no regressions).
- [ ] `uv run pre-commit run --all-files` passes.
