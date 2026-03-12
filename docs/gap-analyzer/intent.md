# Intent: Gap Analyzer + Targeted Retry

## Original Request

Add a step-level verification agent (Option B) that runs after all tasks in a step reach terminal state, examines their combined output, and takes targeted recovery actions — retrying specific tasks with feedback or spawning fix-up tasks for integration gaps between tasks. [S-03/T-02/R1, S-03/T-02/R3]

## Goal

Enable a step to self-heal integration failures that slip past per-task verification. Currently, tasks are verified in isolation; tasks that each pass individually can still leave integration gaps (mismatched API contracts, inconsistent interfaces). The gap analyzer closes this blind spot by checking the combined output as a unit and acting on what it finds. [S-03/T-02/R1, S-04/T-03/R1]

## Scope

### In Scope

- **`StepVerifierConfig`** — new optional block on `StepConfig` with `prompt: str`, `max_iterations: int = 3`, `auto_verify: AutoVerifyConfig | None = None`. Steps without this block are unaffected. [S-01/T-01/R2, S-01/T-01/R3]
- **Step verification state** — `StepState` gains `verifying: bool`, `verifier_iterations: int`, and `gap_reports: list[GapReport]` fields. `StepModel` gains `gap_reports` (JSON) and `verifying` (boolean) columns via Alembic migration. [S-01/T-02/R3, S-01/T-03/R1, S-01/T-03/R3]
- **`GapReport` model** — structured result of one verification pass: `iteration`, `assessment` (text), `verdict` (`pass` | `retry` | `fix` | `fail`), `actions` list, `timestamp`. [S-01/T-02/R2]
- **`StepVerdict` enum** — `PASS`, `RETRY`, `FIX`, `FAIL` in `config/enums.py`. [S-01/T-01/R1]
- **Verification loop** — engine method `start_step_verification()` / `complete_step_verification(gap_report)`. Loop: all tasks terminal → run step verifier → apply actions → wait for re-triggered tasks → repeat. Capped at `max_iterations`. [S-02/T-01/R1, S-02/T-02/R1, S-02/T-02/R4, S-03/T-02/R3]
- **`retry_task` action** — re-run a specific completed task with the gap report's feedback prepended to its prompt. Respects the task's own `max_attempts`. [S-02/T-03/R1, S-02/T-03/R2, S-02/T-03/R3, S-03/T-02/R4]
- **`spawn_fix` action** — create a new `TaskState` directly in the step's task list (minimal bespoke spawning since Option D is not yet implemented). No budget system; `max_iterations` acts as the guard. Provenance tracked via `spawned_by_gap_report` flag on the task. [S-02/T-03/R4, S-01/T-02/R4]
- **`pass` / `fail` actions** — pass advances the step to completion; fail pauses the run. [S-02/T-02/R2, S-02/T-02/R3]
- **Events** — `StepVerificationStarted`, `StepVerificationCompleted`, `GapReportGenerated` event types. [S-01/T-04/R1, S-01/T-04/R2, S-02/T-01/R3]
- **Prompts** — step verifier prompt generation in `workflow/prompts.py`: step context, per-task outcome summaries (status, grades, artifacts), auto-verify results, required output schema. [S-03/T-01/R1, S-03/T-01/R2]
- **Executor integration** — after all tasks in a step complete, if `step_verifier` is configured, executor spawns the step verifier agent, parses structured JSON from output, dispatches actions. [S-03/T-02/R1, S-03/T-02/R2, S-03/T-02/R5]
- **API surface** — `StepSummary` gains `verifying`, `verifier_iterations`, `gap_reports` fields. [S-04/T-01/R2, S-04/T-02/R1]
- **Frontend** — `StepTimeline` visual indicator for `STEP_VERIFYING` state (pulsing purple badge), gap report card in run detail (assessment, verdict, actions, iteration counter), fix-up tasks shown with "Fix-up" badge, activity feed events for verification. [S-05/T-02/R1, S-05/T-02/R2, S-05/T-03/R1, S-05/T-04/R1, S-05/T-04/R2]
- **Tests** — unit tests for gap report schema validation, lifecycle, action dispatch; integration tests for full verification flow, retry_task, spawn_fix, iteration loop, max_iterations guard; frontend tests. [S-01/T-04/R3, S-02/T-04/R3, S-04/T-03/R1, S-04/T-03/R2, S-05/T-04/R3]

### Out of Scope

- Option D (orchestrated expansion / `add_peer_task`) — `spawn_fix` uses bespoke minimal spawning; budget enforcement and full provenance tracking from Option D are deferred. [NO-REQ: explicitly excluded from scope; spawn_fix's bespoke approach is covered by S-02/T-03/R4]
- Migrating fan-out parent verification to use the step verifier infrastructure — architecture should allow it eventually but it is not required now. [NO-REQ: explicitly excluded; fan-out path protection is covered by S-03/T-02/R5]
- Phase pipelines (Option A) — independent effort. [NO-REQ: out of scope]
- Conditional steps (Option C) — already implemented; no changes needed. [NO-REQ: already done]
- Step verifier access to prior-step outputs across multiple steps — step verifier only sees its own step's tasks. [NO-REQ: scope limitation, not a feature to implement]
- Manual trigger of step re-verification via API — not needed for MVP; re-verification is automatic per the loop. [NO-REQ: explicitly deferred]

## Definition of Complete

- [ ] `StepVerifierConfig` Pydantic model exists with `prompt`, `max_iterations`, `auto_verify` fields. [S-01/T-01/R2]
- [ ] `step_verifier` field added to `StepConfig` (optional, backward compatible; steps without it behave identically to today). [S-01/T-01/R3]
- [ ] `GapReport` Pydantic model exists with `iteration`, `assessment`, `verdict`, `actions`, `timestamp` fields. [S-01/T-02/R2]
- [ ] `StepVerdict` enum exists with `PASS`, `RETRY`, `FIX`, `FAIL` values. [S-01/T-01/R1]
- [ ] `StepState` has `verifying: bool = False`, `verifier_iterations: int = 0`, `gap_reports: list[GapReport] = []` fields. [S-01/T-02/R3]
- [ ] `StepModel` has `verifying` (boolean) and `gap_reports` (JSON) columns via Alembic migration. [S-01/T-03/R1, S-01/T-03/R3]
- [ ] `start_step_verification()` and `complete_step_verification(gap_report)` exist on the engine. [S-02/T-01/R1, S-02/T-02/R1]
- [ ] `retry_task` action re-runs the target task with feedback prepended; task must be in COMPLETED state. [S-02/T-03/R1, S-02/T-03/R2]
- [ ] `spawn_fix` action creates a new `TaskState` in the step; marked with provenance. [S-02/T-03/R4]
- [ ] `pass` action advances the step to completion. [S-02/T-02/R2]
- [ ] `fail` action pauses the run. [S-02/T-02/R3]
- [ ] `max_iterations` guard prevents infinite loops. [S-02/T-02/R4, S-01/T-01/R4]
- [ ] `StepVerificationStarted`, `StepVerificationCompleted`, `GapReportGenerated` event types exist and are emitted. [S-01/T-04/R1, S-01/T-04/R2, S-02/T-01/R3]
- [ ] Step verifier prompt includes per-task outcome summaries and required JSON schema. [S-03/T-01/R2]
- [ ] Executor spawns step verifier agent after all tasks are terminal (if configured) and parses JSON output. [S-03/T-02/R1, S-03/T-02/R2]
- [ ] `StepSummary` API schema includes `verifying`, `verifier_iterations`, `gap_reports`. [S-04/T-01/R2, S-04/T-02/R1]
- [ ] Frontend `StepTimeline` shows pulsing purple badge for verifying steps. [S-05/T-02/R2]
- [ ] Frontend gap report card shows assessment, verdict, actions, iteration counter. [S-05/T-03/R1]
- [ ] Fix-up tasks (`spawn_fix`) display with "Fix-up" badge in step task list. [S-05/T-04/R1]
- [ ] Activity feed displays `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` events. [S-05/T-04/R2]
- [ ] Unit tests for gap report validation, lifecycle methods, action dispatch (all four verdicts). [S-01/T-04/R3, S-02/T-04/R3]
- [ ] Integration tests for full flow: verify → retry → re-verify → pass; max_iterations guard; spawn_fix creates runnable task. [S-04/T-03/R1, S-04/T-03/R2]
- [ ] Frontend tests for verifying state in timeline and gap report display. [S-05/T-04/R3]
- [ ] All existing tests continue to pass (no regressions). [S-01/T-04/R3, S-02/T-04/R3, S-04/T-03/R3]
- [ ] `uv run pre-commit run --all-files` passes. [NO-REQ: this is a meta-constraint, not a feature; all per-task auto_verify checks cover the underlying code quality requirements]
