# Step Plan: Frontend Display

## Purpose

Render conditional step state in the UI so users can see which steps were skipped, why, what conditions pending steps have, and interact with manual gates. This is the final step, making the feature visible to end users.

## Prerequisites

- **Step 5** (Manual Gate Skip + API Surface) -- API returns `skipped`, `skip_reason`, `condition` on `StepSummary`; skip-step endpoint exists.

## Functional Contract

### Inputs

- `StepSummary` objects from `GET /runs/{id}` containing `skipped`, `skip_reason`, and `condition` fields
- `StepSkipped` events from the activity feed
- Run pause state with `pause_reason="manual_gate"`

### Outputs

- **StepTimeline.tsx**: Skipped steps rendered with dashed border, dimmed opacity, and "Skipped" badge
- **stepTimelineUtils.ts**: `getStepState()` returns `'skipped'` state; `stepBadgeClasses` includes entry for skipped
- **Tooltip**: Skipped steps show `skip_reason` on hover
- **Condition text**: Pending conditional steps display their `condition.when` expression (e.g., "Runs if complexity = high")
- **Repeat-for sub-items**: `repeat_for` iterations render as sub-items under the parent step badge
- **Type updates**: `runs.ts` types gain `skipped`, `skip_reason`, `condition` fields on `StepSummary`
- **ActivityFeed.tsx**: `StepSkipped` events display with skip icon and reason text
- **Manual gate UI**: When run is paused at a manual gate, show both "Execute Step" and "Skip Step" buttons

### Error Cases

- Missing `condition` field (older runs or steps without conditions) -- render normally, no condition text shown
- Missing `skip_reason` -- show "Skipped" badge without tooltip detail
- API error on skip-step call -- show error toast, don't change UI state

## Tasks

1. Update `ui/src/types/runs.ts`: add `skipped`, `skip_reason`, `condition` to `StepSummary` type
2. Update `ui/src/lib/stepTimelineUtils.ts`:
   - `getStepState()` returns `'skipped'` when `step.skipped` is true
   - Add `stepBadgeClasses` entry for `'skipped'` state (dashed border, dimmed opacity)
3. Update `ui/src/components/dashboard/StepTimeline.tsx`:
   - Render skipped steps with skipped badge classes
   - Show "Skipped" badge text
   - Add tooltip with `skip_reason` on skipped steps
   - Show condition expression text on pending conditional steps
   - Render `repeat_for` iterations as sub-items under parent step
4. Update `ui/src/components/dashboard/ActivityFeed.tsx`:
   - Handle `StepSkipped` event type with skip icon and reason text
5. Add manual gate UI in `RunDetail.tsx` (or appropriate component):
   - When paused at manual gate, show "Execute Step" and "Skip Step" buttons
   - "Execute Step" calls existing resume endpoint
   - "Skip Step" calls `POST /runs/{id}/steps/{step_id}/skip`
6. Frontend tests:
   - Skipped step renders with dashed border class
   - Skipped step shows skip reason in tooltip
   - Pending conditional step shows condition text
   - `repeat_for` iterations render as sub-items
   - Manual gate shows execute and skip buttons

## Verification Approach

### Auto-Verify

- `cd ui && npx vitest run` -- all frontend tests pass (including new ones)
- `cd ui && npx tsc --noEmit` -- TypeScript type check clean
- `cd ui && npx eslint .` -- ESLint clean

### Manual Verification

- Visual inspection: create a run with conditional steps; verify skipped steps appear dimmed with dashed borders
- Visual inspection: verify pending conditional steps show condition text
- Visual inspection: pause at manual gate; verify both Execute and Skip buttons appear and work
- Visual inspection: verify `StepSkipped` events appear in activity feed

## Context & References

- Plan: `docs/conditional-steps/plan.md` -- Step 6 specification (M3)
- Architecture: `docs/conditional-steps/architecture.md` -- frontend testing strategy
- `ui/src/components/dashboard/StepTimeline.tsx` -- step timeline rendering
- `ui/src/lib/stepTimelineUtils.ts` -- step state classification
- `ui/src/components/dashboard/ActivityFeed.tsx` -- activity feed
- `ui/src/types/runs.ts` -- API response types
