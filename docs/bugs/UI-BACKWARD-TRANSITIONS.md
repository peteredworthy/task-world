# Feature: Wire Backward Step Transitions to the UI

## Summary

The backend supports transitioning a run back to an earlier step (e.g., to redo work after a
regression), but the frontend has no way to trigger this. The `StepTimeline` component
visualises step history but provides no control to move backwards.

## Current State

**Backend — complete:**
- `POST /api/runs/{id}/transition-back` — accepts `{ target_step_index: number, reason?: string }`,
  resets tasks in skipped steps to PENDING, returns updated `RunResponse`
  (`src/orchestrator/api/routers/runs.py:837`)
- `WorkflowService.transition_backward()` is tested

**Frontend — missing everything:**
- No `transitionBack(runId, { target_step_index, reason })` in `ui/src/api/client.ts`
- No `useTransitionBack` mutation hook in `ui/src/hooks/useApi.ts`
- No UI to select a target step and confirm the transition

## Work Required

1. **`ui/src/api/client.ts`** — add:
   ```ts
   transitionBack(runId: string, data: { target_step_index: number; reason?: string }): Promise<RunResponse>
   ```

2. **`ui/src/hooks/useApi.ts`** — add `useTransitionBack` mutation; invalidate `['run', runId]`
   on success.

3. **UI — step selector + confirmation dialog:**
   - In `StepTimeline` (or `RunDetail`), add a "Revert to this step" action on each
     completed step that precedes the current one.
   - Show a confirmation dialog: "This will reset all tasks from step N onward to PENDING.
     Are you sure?" with an optional reason field.
   - Call `useTransitionBack` on confirm.

## Severity

**Medium** — without this, recovering from a mid-run mistake requires direct DB manipulation
or cancelling the entire run and starting over.

## Related

- `docs/ui-gaps2/README.md §5`
- `src/orchestrator/api/routers/runs.py:837` — backend endpoint
- `src/orchestrator/workflow/service.py` — `transition_backward()`
- `ui/src/components/StepTimeline.tsx` — natural home for the UI trigger
