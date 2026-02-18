# Feature: Wire Step-Level Human Approval to the UI

## Summary

The backend endpoint for step-level human approval exists and is tested, but no API client
function, mutation hook, or UI component calls it. Runs that use an `approval` gate between
steps block indefinitely with no way to approve from the frontend.

## Current State

**Backend — complete:**
- `POST /api/runs/{id}/steps/{step_id}/approve` (`api/routers/runs.py:603`)
- `HumanApprovalRequest` / `HumanApprovalResponse` schemas (`api/schemas/steps.py`)
- `StepSummary` already carries `has_approval_gate: boolean` and
  `approval_status: 'pending' | 'approved' | null` (`ui/src/types/runs.ts`)

**Frontend — missing everything:**
- No `approveStep(runId, stepId, { approved_by, comment })` in `ui/src/api/client.ts`
- No `useApproveStep` mutation hook in `ui/src/hooks/useApi.ts`
- No UI component checks `has_approval_gate && approval_status === 'pending'`
- Step-level approvals do not appear in `usePendingActions` results

## Work Required

1. **`ui/src/api/client.ts`** — add:
   ```ts
   approveStep(runId: string, stepId: string, data: { approved_by: string; comment?: string }): Promise<StepResponse>
   ```
   calling `POST /api/runs/{runId}/steps/{stepId}/approve`.

2. **`ui/src/hooks/useApi.ts`** — add `useApproveStep` mutation that invalidates
   `['run', runId]` on success.

3. **`ui/src/pages/RunDetail.tsx`** or a new `StepApprovalBanner` component — when a step
   has `has_approval_gate && approval_status === 'pending'`, render an approve prompt (button
   or inline modal) similar to the existing task-level `ApprovalModal` pattern.

4. **`ui/src/hooks/usePendingActions.ts`** (or wherever pending actions are aggregated) —
   ensure step-level gates surface as `PendingAction` entries so the `PendingActionsBadge`
   badge count includes them.

## Severity

**High** — any routine that uses a step `gate: type: human_approval` is unactionable from
the UI today.

## Related

- `docs/ui-gaps2/README.md §1`
- `src/orchestrator/api/routers/runs.py:603` — backend endpoint
- `src/orchestrator/api/schemas/steps.py` — `HumanApprovalRequest` schema
- `ui/src/types/runs.ts` — `StepSummary.has_approval_gate`, `StepSummary.approval_status`
- `AGENT-DEATH-HUMAN-GATE.md` — related: agent confusion when entering an approval-gated step
