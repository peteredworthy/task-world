# Step Plan: Run & Task Lifecycle (M2c + M2d)

## Purpose

Implement Gherkin specs covering full run and task lifecycle workflows — state transitions driven by mocked API responses and WebSocket events. These scenarios verify the app correctly reflects backend state changes in the UI. Merged because run and task lifecycles share step definitions, fixtures, and the same lifecycle.steps.ts file.

## Prerequisites

- Step 01 complete: fixtures, FakeWebSocket, route handlers.
- Step 02 complete: dashboard page objects (run creation flows).
- Step 03 complete: run detail page objects (task display, action buttons).

## Functional Contract

### Inputs

- Factory functions for all lifecycle states (draft, active, paused, completed, failed, cancelled runs; queued, building, verifying, completed, failed tasks).
- FakeWebSocket for pushing `run_status_changed` and `task_status_changed` events.
- API route handlers (stateful — mutations update state for subsequent reads).
- Page objects from Steps 02-03.

### Outputs

- `ui/tests/bdd/features/run-lifecycle.feature` — scenarios:
  - Create run → start → active (tasks building) → verifying → grading → complete
  - Create → start → pause → resume → complete
  - Create → start → cancel
  - State transitions driven by WebSocket events update UI in real time
- `ui/tests/bdd/features/task-lifecycle.feature` — scenarios:
  - Task queued → building (prompt shown) → submit → verifying → grades set → complete
  - Verify → fail → revision → re-verify → pass
  - Checklist table updates as grades are submitted
  - Prompt copy box displayed during building phase
  - Grade badges reflect verification outcome
- `ui/tests/bdd/steps/lifecycle.steps.ts` — step definitions for lifecycle-specific When/Then (triggering transitions, verifying status badges, checking UI updates after WebSocket events).

### Error Cases

- WebSocket event arrives before API response — route handlers and FakeWS must be coordinated so test assertions wait for UI to settle.
- Task lifecycle depends on run being in correct state — scenario Background must set up run state correctly.
- Grade submission requires specific API payload — route handlers must validate and accept grade data.

## Tasks

1. Write `run-lifecycle.feature` covering all happy-path run state transitions.
2. Write `task-lifecycle.feature` covering all happy-path task state transitions.
3. Create `lifecycle.steps.ts` with step definitions for transitions, WebSocket event pushing, and status assertions.
4. Extend factories to produce objects in specific lifecycle states (e.g., `buildRun({ status: 'paused' })`).
5. Extend route handlers for task submission, verification completion, and grade endpoints.
6. Run all BDD tests, verify green.

## Verification Approach

### Auto-Verify

- All scenarios in `run-lifecycle.feature` and `task-lifecycle.feature` pass.
- WebSocket-driven UI updates verified (status badges change without page reload).
- No regressions in Steps 01-03 features.

### Manual Verification

- Full run lifecycle plays out correctly with mocked events.
- Task transitions from queued through completion show correct UI at each stage.
- Revision cycle (fail → retry) works end-to-end.

## Context & References

- Plan: `docs/UI-QA/plan.md` — M2c + M2d specification
- Architecture: `docs/UI-QA/architecture.md` — timing control patterns, WebSocket mock usage
- Components covered: ChecklistTable, GradeBadge, GradeRow, PromptCopyBox, status badges, action buttons
- Intent traces: [I-01], [I-04], [I-29], [I-30]
