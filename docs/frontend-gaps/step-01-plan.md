# Step 1 Plan: Step-Level Approval UI (Gap 1)

## Purpose

Add step-level human approval to RunDetail, enabling users to approve individual step gates via `POST /api/runs/{id}/steps/{step_id}/approve`. Currently only task-level approval exists; step gates cannot be approved through the UI, blocking the approval user story journey.

## Prerequisites

- None (this is a root step with no dependencies on other steps)

## Functional Contract

### Inputs

- `pendingActions` array from the run detail API response — filter for items where `action_type === "step_approval"`
- `run_id` (string) — from the current RunDetail page route params
- `step_id` (string) — from the pending action's `step_id` field
- User-provided `approved_by` (string) and optional `comment` (string) via the modal form

### Outputs

- `StepApprovalModal` component rendered in RunDetail when a step-approval pending action is detected
- `useApproveStep` hook wrapping `POST /api/runs/{id}/steps/{step_id}/approve` mutation
- `StepApprovalRequest` type added to `types/index.ts` (or `types/steps.ts`)
- On successful approval: TanStack Query cache invalidation for run detail and pending actions queries, modal closes, activity feed updates

### Errors

- API returns 404 — step not found or already approved → show error toast "Step not found or already approved"
- API returns 409 — step in wrong state for approval → show error toast "Step cannot be approved in its current state"
- API returns 500 — server error → show generic error toast, keep modal open for retry
- Network error → show "Connection error, please try again" toast

## Tasks

1. Add `StepApprovalRequest` type to `types/index.ts` with `approved_by: string` and `comment?: string` fields
2. Add `useApproveStep` mutation hook to `hooks/useApi.ts` calling `POST /api/runs/{id}/steps/{step_id}/approve`
3. Create `components/detail/StepApprovalModal.tsx` with form fields for approver name and optional comment, confirm/cancel buttons
4. Update `pages/RunDetail.tsx` to detect `step_approval` pending actions and render StepApprovalModal with appropriate props

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `StepApprovalModal.tsx` exists at `ui/src/components/detail/StepApprovalModal.tsx`
- [ ] `useApproveStep` is exported from `hooks/useApi.ts`
- [ ] `StepApprovalRequest` type is defined and exported

### Manual Verify

- [ ] RunDetail page shows step approval modal when a `step_approval` pending action exists
- [ ] Submitting the modal calls the correct API endpoint with the right payload
- [ ] Error states display appropriate messages
- [ ] Successful approval refreshes the run detail view

## Context & References

- Gap analysis: `docs/stories/GAP-ANALYSIS-FRONTEND.md` — Gap 1 (HIGH severity)
- Design decision Q1: Separate StepApprovalModal (not reusing ApprovalModal)
- Backend endpoint: `POST /api/runs/{id}/steps/{step_id}/approve`
- Existing pattern: `components/detail/ApprovalModal.tsx` (task-level, for reference)
