# Step 6 Plan: Wire Step-Level Human Approval UI (UI-STEP-APPROVAL)

## Purpose

Add a frontend approval flow for step-level human approval gates. The backend endpoint `POST /api/runs/{id}/steps/{step_id}/approve` exists and is tested, but the frontend has no API client function, mutation hook, or UI component to call it. Any routine that uses an `approval` gate between steps is currently unactionable from the UI — the user must use `curl` directly. This step closes that gap by adding a `StepApprovalBanner` that renders when a step has a pending approval gate, wired to a `useApproveStep` mutation hook.

## Prerequisites

- None (independent of all other steps)

## Functional Contract

### Inputs

- Run detail data from `GET /api/runs/{id}` — specifically `steps[].has_approval_gate` and `steps[].approval_status`
- `run_id` (string) from the `RunDetail` route params
- `step_id` (string) from the step with `has_approval_gate && approval_status === 'pending'`
- User-provided `approved_by` (string, required) and `comment` (string, optional) from the approval form

### Outputs

- `approveStep(runId, stepId, data: { approved_by: string; comment?: string })` function added to `ui/src/api/client.ts` calling `POST /api/runs/{runId}/steps/{stepId}/approve`
- `useApproveStep()` mutation hook added to `ui/src/hooks/useApi.ts`; invalidates `['run', runId]` on success
- `StepApprovalBanner` component (new file at `ui/src/components/detail/StepApprovalBanner.tsx`):
  - Renders per step where `has_approval_gate && approval_status === 'pending'`
  - Contains an approval form with `approved_by` input and optional `comment` field
  - Calls `useApproveStep` on submit
- `usePendingActions` updated to include pending step approval gates in its action list and badge count
- `RunDetail.tsx` mounts `StepApprovalBanner` for each step with a pending gate

### Errors

- 404 from approve API — show error toast "Step not found or already approved"
- 409 from approve API — show error toast "Step cannot be approved in its current state"
- 500 — show generic error toast; keep banner open for retry
- Network error — show "Connection error, please try again" toast
- TypeScript compile errors must be zero

## Tasks

1. Add `approveStep(runId, stepId, data)` to `ui/src/api/client.ts`
2. Add `useApproveStep()` mutation hook to `ui/src/hooks/useApi.ts` with run query invalidation on success
3. Create `ui/src/components/detail/StepApprovalBanner.tsx` with approval form and error handling
4. Update `ui/src/hooks/usePendingActions.ts` to include pending step approval gates in the returned action list and badge count
5. Update `ui/src/pages/RunDetail.tsx` to mount `StepApprovalBanner` per step with a pending gate
6. Write Vitest test: render `StepApprovalBanner` with a mock step having `has_approval_gate=true, approval_status='pending'`; confirm banner renders and submit button is present

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `StepApprovalBanner.tsx` exists at `ui/src/components/detail/StepApprovalBanner.tsx`
- [ ] `approveStep` is exported from `ui/src/api/client.ts`
- [ ] `useApproveStep` is exported from `ui/src/hooks/useApi.ts`
- [ ] Vitest test for `StepApprovalBanner` passes

### Manual Verify

- [ ] `RunDetail` page shows `StepApprovalBanner` when a step has `has_approval_gate && approval_status === 'pending'`
- [ ] Submitting the banner calls `POST /api/runs/{id}/steps/{step_id}/approve` with the correct payload
- [ ] Banner disappears and run detail refreshes after successful approval
- [ ] Pending approval gate appears in the `PendingActionsBadge` count

## Context & References

- Bug report: `docs/bugs/UI-STEP-APPROVAL.md` — Current State and Work Required
- Architecture: `docs/bug-removal/architecture.md` — "New Components: StepApprovalBanner", "Modified Components: RunDetail.tsx, usePendingActions.ts"
- Backend endpoint: `src/orchestrator/api/routers/runs.py:603` — `POST /api/runs/{id}/steps/{step_id}/approve`
- Existing pattern: `ui/src/components/detail/ApprovalModal.tsx` (task-level approval, for reference)
- `StepSummary` type: `ui/src/types/runs.ts` — already has `has_approval_gate` and `approval_status` fields
