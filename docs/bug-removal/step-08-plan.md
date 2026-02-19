# Step 8 Plan: Add Backward Step Transition UI (UI-BACKWARD-TRANSITIONS)

## Purpose

Expose the backend `POST /api/runs/{id}/transition-back` endpoint in the `StepTimeline` component, allowing users to revert a run to an earlier step without direct database manipulation. Currently the backend transition logic is fully implemented and tested, but there is no frontend API client, hook, or UI trigger. Without this, recovering from a mid-run regression requires cancelling the entire run or direct SQL. After this step, each completed step in the timeline will show a "Revert to this step" action that opens a confirmation dialog.

## Prerequisites

- None (independent of all other steps)

## Functional Contract

### Inputs

- `run_id` (string) from the `RunDetail`/`StepTimeline` context
- `target_step_index` (integer) — the zero-based index of the step to revert to (selected by clicking a completed step in the timeline)
- `reason` (string, optional) — user-supplied justification from the confirmation dialog

### Outputs

- `transitionBack(runId, data: { target_step_index: number; reason?: string })` function added to `ui/src/api/client.ts` calling `POST /api/runs/{runId}/transition-back`
- `useTransitionBack()` mutation hook added to `ui/src/hooks/useApi.ts`; invalidates `['run', runId]` on success
- `StepTimeline.tsx` updated:
  - Each completed step that precedes the current active step shows a "Revert to this step" action (button or context menu item)
  - Clicking the action opens a confirmation dialog: "This will reset all tasks from step N onward to PENDING. Are you sure?"
  - Dialog includes an optional reason text field
  - On confirm, calls `useTransitionBack` with the selected step's index and optional reason
  - On success, run query is invalidated and the timeline reflects the new current step

### Errors

- 400 from transition-back API — show error toast "Invalid step or transition not allowed in current run state"
- 409 — show error toast "Run must be ACTIVE or PAUSED to revert steps"
- 500 — show generic error toast; keep dialog open for retry
- TypeScript compile errors must be zero

## Tasks

1. Add `transitionBack(runId, data)` to `ui/src/api/client.ts`
2. Add `useTransitionBack()` mutation hook to `ui/src/hooks/useApi.ts` with run query invalidation on success
3. Update `ui/src/components/StepTimeline.tsx`: add "Revert to this step" action on completed steps preceding the current one; implement confirmation dialog with optional reason field; wire to `useTransitionBack` on confirm
4. Write Vitest test: render `StepTimeline` with mock steps (some completed, one active); confirm "Revert to this step" action appears on completed steps and confirmation dialog renders on click

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `transitionBack` is exported from `ui/src/api/client.ts`
- [ ] `useTransitionBack` is exported from `ui/src/hooks/useApi.ts`
- [ ] Vitest test for `StepTimeline` revert action passes

### Manual Verify

- [ ] `StepTimeline` shows "Revert to this step" on each completed step preceding the current step
- [ ] Clicking the action opens a confirmation dialog describing which steps will be reset
- [ ] Confirming calls `POST /api/runs/{id}/transition-back` with the correct step index
- [ ] The timeline updates to reflect the new current step after a successful transition

## Context & References

- Bug report: `docs/bugs/UI-BACKWARD-TRANSITIONS.md` — Current State and Work Required
- Architecture: `docs/bug-removal/architecture.md` — "Modified Components: StepTimeline.tsx"
- Backend endpoint: `src/orchestrator/api/routers/runs.py:837` — `POST /api/runs/{id}/transition-back`
- Source file: `ui/src/components/StepTimeline.tsx`
