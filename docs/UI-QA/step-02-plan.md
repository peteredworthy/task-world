# Step Plan: Dashboard & CreateRunModal Workflows (M2a)

## Purpose

Implement Gherkin feature files and step definitions for the highest-priority user workflows: Dashboard browsing (run list, filtering, search) and run creation (modal open, form fill, submit). This is the most valuable workflow coverage per clarification Q6.

## Prerequisites

- Step 01 complete: fixtures, factories, route handlers, FakeWebSocket, playwright-bdd pipeline proven via smoke test.
- Smoke feature runs green.

## Functional Contract

### Inputs

- Factory functions from `ui/tests/fixtures/factories.ts` (buildRun, buildRoutine, buildAgent)
- API handlers from `ui/tests/fixtures/api-handlers.ts`
- FakeWebSocket from `ui/tests/fixtures/fake-ws.ts`
- Shared step definitions from `ui/tests/bdd/steps/common.steps.ts`

### Outputs

- `ui/tests/bdd/features/dashboard.feature` — scenarios:
  - View runs list (multiple runs displayed as cards)
  - Filter runs by status (active, completed, failed, etc.)
  - Search runs by name
  - Click run card navigates to run detail
  - Empty state when no runs exist
- `ui/tests/bdd/features/create-run.feature` — scenarios:
  - Open CreateRunModal via "New Run" button
  - Select routine from RoutineSelector
  - Select branch from BranchSelector
  - Fill run name and submit
  - Created run appears in dashboard list
  - Close modal without creating (cancel/escape)
  - Validation errors shown for required fields
- `ui/tests/bdd/steps/dashboard.steps.ts` — step definitions for dashboard-specific actions and assertions.
- `ui/tests/bdd/pages/dashboard.page.ts` — page object for Dashboard (run cards, filters, search, create button).
- `ui/tests/bdd/pages/modals.page.ts` — page object for CreateRunModal (routine selector, branch selector, name input, submit/cancel buttons).

### Error Cases

- Run card selectors change if RunCard component markup changes — mitigated by page objects isolating selectors.
- CreateRunModal form validation not triggered — tests must verify both valid and invalid submissions.
- Route handler state not reset between scenarios — each scenario gets fresh page + fresh handlers.

## Tasks

1. Create `ui/tests/bdd/pages/dashboard.page.ts` with selectors for run cards, filters, search input, create button.
2. Create `ui/tests/bdd/pages/modals.page.ts` with selectors for CreateRunModal fields and buttons.
3. Write `ui/tests/bdd/features/dashboard.feature` with all dashboard scenarios.
4. Write `ui/tests/bdd/features/create-run.feature` with all modal scenarios.
5. Create `ui/tests/bdd/steps/dashboard.steps.ts` with step definitions.
6. Update `common.steps.ts` if new shared steps emerge (e.g., navigation, API state setup).
7. Run all BDD tests, verify green.

## Verification Approach

### Auto-Verify

- All scenarios in `dashboard.feature` and `create-run.feature` pass.
- No regressions in smoke feature.
- TypeScript compilation clean.

### Manual Verification

- Dashboard page renders run cards matching mocked data.
- CreateRunModal opens, accepts input, submits successfully.
- Navigation from dashboard to run detail works.

## Context & References

- Plan: `docs/UI-QA/plan.md` — M2a specification
- Architecture: `docs/UI-QA/architecture.md` — page objects, step reuse patterns
- Clarification Q6: Dashboard + CreateRunModal is highest priority
- Components covered: Dashboard.tsx, CreateRunModal (useCreateRunModal), RunCard, RunFilters, RoutineSelector, BranchSelector
- Intent traces: [I-01], [I-06], [I-07], [I-27], [I-29]
