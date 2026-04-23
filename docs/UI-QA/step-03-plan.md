# Step Plan: Run Detail & Secondary Pages (M2b + M2e)

## Purpose

Add workflow coverage for the Run Detail page (step timeline, task list, attempt history, pause/resume/cancel) and secondary pages (Routines, Agents, History, Settings). Merged because secondary pages are thin and share page-object patterns with Run Detail.

## Prerequisites

- Step 01 complete: fixtures and infrastructure.
- Step 02 complete: dashboard page objects and shared steps established (navigation patterns reusable here).

## Functional Contract

### Inputs

- All fixtures from Step 01.
- Page objects and shared steps from Step 02 (navigation, API setup patterns).
- Factory functions for Run, Task, Attempt, Step, Routine, Agent.

### Outputs

- `ui/tests/bdd/features/run-detail.feature` — scenarios:
  - View run detail with step timeline
  - View task list within a step
  - Expand task detail card
  - View attempt history and timeline
  - View metrics bar
  - View activity feed
  - Pause active run
  - Resume paused run
  - Cancel active run
- `ui/tests/bdd/features/routines.feature` — scenarios:
  - Browse routine library
  - View routine detail
  - Validate routine
- `ui/tests/bdd/features/agents.feature` — scenarios:
  - View agents list
  - Configure agent runner
  - View agent quota
- `ui/tests/bdd/features/history.feature` — scenarios:
  - View completed runs
  - Filter/sort history
- `ui/tests/bdd/features/settings.feature` — scenarios:
  - Open settings modal
  - Toggle SSE/polling preference
- `ui/tests/bdd/steps/run-detail.steps.ts` — step definitions for run detail actions.
- `ui/tests/bdd/pages/run-detail.page.ts` — page object for RunDetail (step timeline, task cards, action buttons).
- `ui/tests/bdd/pages/routines.page.ts` — page object for Routines page.
- `ui/tests/bdd/pages/agents.page.ts` — page object for Agents page.

### Error Cases

- Run detail page requires valid run ID in URL — route handlers must serve run data for the ID in the URL path.
- Pause/resume/cancel actions require POST requests — route handlers must handle mutations and update state.
- Secondary pages may have minimal UI if no data — empty state scenarios needed.

## Tasks

1. Create page objects: `run-detail.page.ts`, `routines.page.ts`, `agents.page.ts`.
2. Write `run-detail.feature` with all run detail scenarios.
3. Write `routines.feature`, `agents.feature`, `history.feature`, `settings.feature`.
4. Create `run-detail.steps.ts` step definitions.
5. Extend `common.steps.ts` with shared patterns (e.g., "I am viewing run {string} in detail").
6. Extend `api-handlers.ts` if new endpoints need mocking (routines detail, agent config).
7. Run all BDD tests, verify green.

## Verification Approach

### Auto-Verify

- All feature files pass.
- Every page has at least one scenario.
- Every modal (settings) has open/close coverage.
- No regressions in Steps 01-02 features.

### Manual Verification

- Run detail page shows step timeline with correct task data.
- Pause/resume/cancel buttons trigger correct state changes.
- Secondary pages render with mocked data.

## Context & References

- Plan: `docs/UI-QA/plan.md` — M2b + M2e specification
- Architecture: `docs/UI-QA/architecture.md` — page object patterns
- Clarification Q6: RunDetail is third priority; secondary pages lowest (can be descoped if needed)
- Components covered: RunDetail, StepTimeline, TaskDetailCard, AttemptHistory, AttemptTimeline, MetricsBar, ActivityFeed, RoutineLibrary, AgentList, SettingsModal
- Intent traces: [I-04], [I-08], [I-11], [I-30], [I-32]
