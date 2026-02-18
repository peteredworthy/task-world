# Step 1: Step-Level Approval UI (Gap 1)

Add step-level human approval to the RunDetail page, enabling users to approve individual step gates via `POST /api/runs/{id}/steps/{step_id}/approve`. Currently only task-level approval exists; step gates cannot be approved through the UI, blocking the Human-in-the-Loop user story journey.

## Intent Verification
**Original Intent**: Close Gap 1 (HIGH severity) from `docs/stories/GAP-ANALYSIS-FRONTEND.md` — step-level approval UI is missing, blocking the approval user story journey.
**Functionality to Produce**:
- `StepApprovalRequest` type with `approved_by: string` and `comment?: string` fields
- `useApproveStep` mutation hook calling `POST /api/runs/{id}/steps/{step_id}/approve`
- `StepApprovalModal` component with form fields for approver name and optional comment
- RunDetail page detects `step_approval` pending actions and renders StepApprovalModal
- On successful approval: cache invalidation, modal closes, activity feed updates
**Final Verification Criteria**:
- `npx tsc --noEmit` passes with no type errors
- `StepApprovalModal.tsx` exists at `ui/src/components/detail/StepApprovalModal.tsx`
- `useApproveStep` is exported from `hooks/useApi.ts`
- `StepApprovalRequest` type is defined and exported
- RunDetail page shows step approval modal when a `step_approval` pending action exists

---

## Task 1: Add StepApprovalRequest Type

**Description**: Add the `StepApprovalRequest` type to the frontend type system so the approval mutation has a typed payload.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/types/index.ts` (or create `ui/src/types/steps.ts` if types are organized by domain)
- [ ] Add the following type definition:
```typescript
export interface StepApprovalRequest {
  approved_by: string;
  comment?: string;
}
```
- [ ] Verify the file saves without syntax errors

**Dependencies**
- [ ] `ui/src/types/` directory must exist (it does per current architecture)

**References**
- `docs/frontend-gaps/architecture.md` — Type Additions section
- `docs/frontend-gaps/step-01-plan.md` — Task 1

**Constraints**
- Only add the `StepApprovalRequest` type. Do not modify any existing types.

**Functionality (Expected Outcomes)**
- [ ] `StepApprovalRequest` is importable from the types directory
- [ ] Type has `approved_by: string` and optional `comment?: string` fields

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes with no errors related to the new type
- [ ] `StepApprovalRequest` is exported and importable

---

## Task 2: Add useApproveStep Mutation Hook

**Description**: Create a TanStack Query mutation hook wrapping `POST /api/runs/{id}/steps/{step_id}/approve` so the UI can submit step approvals.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/hooks/useApi.ts`
- [ ] Import `StepApprovalRequest` from the types directory
- [ ] Add the `useApproveStep` hook following existing mutation patterns (reference `useApproveTask` or similar):
```typescript
export function useApproveStep(runId: string, stepId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: StepApprovalRequest) =>
      apiClient.post(`/api/runs/${runId}/steps/${stepId}/approve`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
      queryClient.invalidateQueries({ queryKey: ['pendingActions', runId] });
    },
  });
}
```
- [ ] Adjust the exact pattern to match existing hooks in the file (API client usage, error handling)

**Dependencies**
- [ ] Task 1 must be complete (StepApprovalRequest type exists)
- [ ] `hooks/useApi.ts` must have existing TanStack Query setup

**References**
- `docs/frontend-gaps/architecture.md` — New Hooks section (useApproveStep)
- Existing pattern: `hooks/useApi.ts` existing mutation hooks
- `docs/frontend-gaps/step-01-plan.md` — Task 2

**Constraints**
- Follow the exact same API client and mutation pattern used by other hooks in `useApi.ts`
- Do not add new dependencies

**Functionality (Expected Outcomes)**
- [ ] `useApproveStep` is exported from `hooks/useApi.ts`
- [ ] It wraps `POST /api/runs/{id}/steps/{step_id}/approve` with the correct payload type
- [ ] On success, it invalidates run detail and pending actions queries

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `useApproveStep` is exported from `hooks/useApi.ts`

---

## Task 3: Create StepApprovalModal Component

**Description**: Build the `StepApprovalModal` component with form fields for approver name and optional comment, with confirm/cancel buttons. This is separate from the existing `ApprovalModal` (task-level) per design decision Q1.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/StepApprovalModal.tsx`
- [ ] Import `useApproveStep` from hooks and `StepApprovalRequest` from types
- [ ] Implement a modal component with:
  - Props: `runId: string`, `stepId: string`, `isOpen: boolean`, `onClose: () => void`
  - Form fields: text input for `approved_by` (required), textarea for `comment` (optional)
  - Confirm button that calls `useApproveStep.mutate()` with form data
  - Cancel button that calls `onClose`
  - Loading state on confirm button during mutation
  - Error display: toast messages for 404, 409, 500, and network errors per the functional contract
- [ ] Follow existing modal patterns in the codebase (reference `ApprovalModal.tsx` for structure, but keep as a separate component)
- [ ] Use TailwindCSS for styling consistent with other modals

**Dependencies**
- [ ] Task 2 must be complete (useApproveStep hook exists)
- [ ] Existing modal/dialog patterns in the codebase

**References**
- `docs/frontend-gaps/architecture.md` — StepApprovalModal row
- `docs/frontend-gaps/step-01-plan.md` — Task 3, Error handling section
- Existing pattern: `components/detail/ApprovalModal.tsx` (for reference, not reuse)

**Constraints**
- Must be a separate component from ApprovalModal (design decision Q1)
- Error handling: 404 → "Step not found or already approved", 409 → "Step cannot be approved in its current state", 500 → generic error + keep modal open, network → "Connection error, please try again"

**Functionality (Expected Outcomes)**
- [ ] `StepApprovalModal.tsx` exists at `ui/src/components/detail/StepApprovalModal.tsx`
- [ ] Modal renders form for approver name and optional comment
- [ ] Submit calls the correct API endpoint
- [ ] Error states display appropriate messages
- [ ] Modal closes on successful approval

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `StepApprovalModal.tsx` exists and exports a React component

---

## Task 4: Wire StepApprovalModal into RunDetail Page

**Description**: Update `pages/RunDetail.tsx` to detect `step_approval` pending actions and render StepApprovalModal with appropriate props.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/pages/RunDetail.tsx`
- [ ] Import `StepApprovalModal` from `components/detail/StepApprovalModal`
- [ ] Add state for step approval modal: `selectedStepApproval` (tracks which step action is being approved, or null)
- [ ] In the pending actions section, filter for items where `action_type === "step_approval"`
- [ ] For each step-approval pending action, render a button/link that opens the StepApprovalModal
- [ ] Render `StepApprovalModal` with:
  - `runId` from route params
  - `stepId` from the selected pending action
  - `isOpen` based on whether `selectedStepApproval` is set
  - `onClose` that clears `selectedStepApproval`

**Dependencies**
- [ ] Task 3 must be complete (StepApprovalModal component exists)

**References**
- `docs/frontend-gaps/architecture.md` — RunDetail modifications
- `docs/frontend-gaps/step-01-plan.md` — Task 4

**Constraints**
- Only add step approval wiring. Do not modify other RunDetail functionality.
- Do not alter existing task-level approval flow.

**Functionality (Expected Outcomes)**
- [ ] RunDetail page shows step approval triggers when `step_approval` pending actions exist
- [ ] Clicking a step approval action opens StepApprovalModal with the correct step ID
- [ ] Successful approval refreshes the run detail view

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `RunDetail.tsx` imports and renders `StepApprovalModal`
- [ ] Step approval actions in pending actions trigger the modal
