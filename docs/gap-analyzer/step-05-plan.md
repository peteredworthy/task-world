# Step Plan: Frontend Display

## Purpose

Render step verification state and gap reports in the UI. Users should be able to see when a step is being verified, how many iterations have run, what the verifier assessed, and what actions were taken — including fix-up tasks spawned by the verifier.

## Prerequisites

- Step 4 complete: API returns `verifying`, `verifier_iterations`, `gap_reports` on `StepSummary`.

## Functional Contract

### Inputs

**Type additions (`ui/src/types/runs.ts`):**
- `GapAction` and `GapReport` interfaces matching `GapActionSchema` / `GapReportSchema`
- `StepSummary` extended with `verifying: boolean`, `verifier_iterations: number`, `gap_reports: GapReport[]`
- `TaskSummary` extended with `spawned_by_gap_report: boolean` (for fix-up task display)

**Step timeline (`ui/src/lib/stepTimelineUtils.ts`):**
- `getStepState()` returns `'verifying'` when `step.verifying === true`
- `stepBadgeClasses` entry for `'verifying'`: pulsing purple badge (similar to task verifying badge)

**Step timeline component (`ui/src/components/dashboard/StepTimeline.tsx`):**
- Steps in verifying state show pulsing purple badge with iteration counter: `"Verifying 2/3"`

**Gap report display (new component or inline in `RunDetail.tsx`):**
- Assessment text
- Verdict badge: green=pass, amber=retry/fix, red=fail
- Action list: type, target task ID (linked to task), feedback/context text
- Iteration counter: `"Iteration 2 of 3"`
- Historical gap reports collapsible (show all past iterations)

**Fix-up tasks:**
- Tasks with `spawned_by_gap_report=true`: dashed border, "Fix-up" badge in step task list

**Activity feed (`ui/src/components/detail/ActivityFeed.tsx`):**
- `StepVerificationStarted` event: appropriate icon (e.g., magnifying glass), iteration info
- `GapReportGenerated` event: verdict badge inline, assessment snippet
- `StepVerificationCompleted` event: final verdict summary

### Outputs

- Pulsing purple "Verifying N/M" badge on verifying steps in `StepTimeline`
- Gap report card(s) visible on step detail view with full assessment, verdict, and actions
- Fix-up tasks visually distinct from normal tasks
- Activity feed shows step verification lifecycle events

### Error Cases

- `gap_reports: []` — no gap report cards rendered (graceful empty state)
- `verifying=false` with `gap_reports` present — historical reports shown, no pulsing badge
- Missing `spawned_by_gap_report` field from older API — treat as `false` (optional field with default)

## Tasks

1. Update `ui/src/types/runs.ts`: add `GapAction`, `GapReport` interfaces; extend `StepSummary` and `TaskSummary`
2. Update `ui/src/lib/stepTimelineUtils.ts`: add `'verifying'` state to `getStepState()` and badge classes
3. Update `ui/src/components/dashboard/StepTimeline.tsx`: render pulsing purple badge with iteration counter for verifying steps
4. Create gap report display (component file or inline): assessment, verdict badge, action list, iteration counter, collapsible history
5. Update step task list: dashed border and "Fix-up" badge for tasks where `spawned_by_gap_report=true`
6. Update `ui/src/components/detail/ActivityFeed.tsx`: handle `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` event types
7. Write frontend tests:
   - `StepTimeline` renders pulsing purple badge with iteration counter for `verifying=true` steps
   - Gap report card renders assessment text, verdict badge, action list
   - Fix-up task renders with "Fix-up" badge and dashed border

## Verification Approach

### Auto-Verify

- `npx vitest run` — all frontend tests pass (including new ones)
- `npx tsc --noEmit` — no TypeScript errors
- `npx eslint ui/src/` — no lint errors

### Manual Verification

- Visual inspection: create a routine with `step_verifier` configured; confirm verifying badge pulses during verification
- Confirm gap report card appears after verifier completes; shows correct verdict color
- Confirm historical gap reports (from earlier iterations) are accessible via collapsible
- Confirm fix-up tasks have dashed border and "Fix-up" badge in task list
- Confirm activity feed shows all three new event types with appropriate icons

## Context & References

- Plan: `docs/gap-analyzer/plan.md` — M4 specification
- Architecture: `docs/gap-analyzer/architecture.md` — frontend components section
- Step 4 plan: `docs/gap-analyzer/step-04-plan.md` — API shape this step consumes
