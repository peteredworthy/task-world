# Step 6: Wire Step-Level Human Approval UI (UI-STEP-APPROVAL)

This step adds a frontend approval flow for step-level human approval gates. The backend endpoint
`POST /api/runs/{id}/steps/{step_id}/approve` exists and is tested, but the frontend has no API
client function, mutation hook, or UI component to call it. Any routine that uses an `approval`
gate between steps is currently unactionable from the UI. This step closes the gap by adding a
`StepApprovalBanner` component, wiring it to a `useApproveStep` mutation hook, and surfacing
pending approval gates in `usePendingActions`.

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "`approveStep` in API client, `useApproveStep` hook, and step approval UI exist; pending approval gates appear in `usePendingActions`"
**Functionality to Produce**:
- `approveStep(runId, stepId, data)` in `ui/src/api/client.ts`
- `useApproveStep()` mutation hook in `ui/src/hooks/useApi.ts`
- `StepApprovalBanner` component at `ui/src/components/detail/StepApprovalBanner.tsx`
- `usePendingActions` updated to count pending step approval gates
- `RunDetail` mounts `StepApprovalBanner` per step with `has_approval_gate && approval_status === 'pending'`

**Final Verification Criteria**:
- `npx tsc --noEmit` passes with no type errors
- `StepApprovalBanner.tsx` exists at the expected path
- `approveStep` exported from `client.ts`, `useApproveStep` exported from `useApi.ts`
- Vitest test for `StepApprovalBanner` passes

---

## Task 1: Add approveStep client function and useApproveStep hook
**Description**:
Add the API client function and TanStack Query mutation hook for the step approval endpoint.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/api/client.ts`
- [ ] Add the `approveStep` client function:
```typescript
export async function approveStep(
  runId: string,
  stepId: string,
  data: { approved_by: string; comment?: string },
): Promise<void> {
  const response = await fetch(`/api/runs/${runId}/steps/${stepId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }
}
```
- [ ] Open `ui/src/hooks/useApi.ts`
- [ ] Add the `useApproveStep` mutation hook:
```typescript
export function useApproveStep(runId: string, stepId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { approved_by: string; comment?: string }) =>
      approveStep(runId, stepId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}
```

**References**
- `docs/bug-removal/step-06-plan.md` — Task 1 and Task 2 descriptions
- `docs/bugs/UI-STEP-APPROVAL.md` — Current State and Work Required
- Backend endpoint: `src/orchestrator/api/routers/runs.py:603`

**Constraints**
- [ ] Only `client.ts` and `useApi.ts` should be changed in this task

**Functionality (Expected Outcomes)**
- [ ] `approveStep` exported from `ui/src/api/client.ts`
- [ ] `useApproveStep` exported from `ui/src/hooks/useApi.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `grep -n "approveStep" ui/src/api/client.ts` shows the export
- [ ] `grep -n "useApproveStep" ui/src/hooks/useApi.ts` shows the export

---

## Task 2: Create StepApprovalBanner component
**Description**:
Create the `StepApprovalBanner` component that renders when a step has `has_approval_gate &&
approval_status === 'pending'`. It provides an approval form with `approved_by` and optional
`comment` fields, and calls `useApproveStep` on submit.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/StepApprovalBanner.tsx`
- [ ] Reference the existing `ui/src/components/detail/ApprovalModal.tsx` for patterns (task-level approval)
- [ ] The component receives `runId` and `step` (a `StepSummary` type with `id`, `has_approval_gate`, `approval_status`) as props
- [ ] Render the banner only when `step.has_approval_gate && step.approval_status === 'pending'`
- [ ] Include:
  - An `approved_by` text input (required)
  - An optional `comment` textarea
  - A Submit button that calls `useApproveStep`
  - Error toast on API error (404 → "Step not found or already approved", 409 → "Step cannot be approved in its current state")
```typescript
interface StepApprovalBannerProps {
  runId: string;
  step: StepSummary;
}

export function StepApprovalBanner({ runId, step }: StepApprovalBannerProps) {
  if (!step.has_approval_gate || step.approval_status !== 'pending') return null;
  const approve = useApproveStep(runId, step.id);
  // ... render form
}
```

**References**
- `docs/bug-removal/step-06-plan.md` — Task 3 description
- `docs/bug-removal/architecture.md` — "New Components: StepApprovalBanner"
- Existing pattern: `ui/src/components/detail/ApprovalModal.tsx`
- `StepSummary` type: `ui/src/types/runs.ts` — `has_approval_gate` and `approval_status` fields

**Constraints**
- [ ] Only one new file: `StepApprovalBanner.tsx`
- [ ] The banner must be a no-op (render nothing) when the step does not have a pending gate

**Functionality (Expected Outcomes)**
- [ ] `StepApprovalBanner.tsx` exists at `ui/src/components/detail/StepApprovalBanner.tsx`
- [ ] Banner renders for steps with `has_approval_gate=true, approval_status='pending'`
- [ ] Banner renders nothing for steps without a pending gate
- [ ] Submit calls `useApproveStep` with the form data

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] File exists: `ui/src/components/detail/StepApprovalBanner.tsx`

---

## Task 3: Update usePendingActions and RunDetail, write Vitest test
**Description**:
Update `usePendingActions` to include pending step approval gates in its count and action list,
mount `StepApprovalBanner` in `RunDetail`, and write a Vitest test for the banner component.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/hooks/usePendingActions.ts`
- [ ] Add logic to count steps with `has_approval_gate && approval_status === 'pending'`:
```typescript
const pendingApprovalGates = run?.steps?.filter(
  (step) => step.has_approval_gate && step.approval_status === 'pending'
) ?? [];
// Include pendingApprovalGates.length in the badge count
// Include these actions in the returned action list
```
- [ ] Open `ui/src/pages/RunDetail.tsx`
- [ ] Import `StepApprovalBanner`
- [ ] In the step list render, mount the banner for each step:
```typescript
{run.steps.map((step) => (
  <div key={step.id}>
    {/* ... existing step rendering ... */}
    <StepApprovalBanner runId={run.id} step={step} />
  </div>
))}
```
- [ ] Write a Vitest test in `ui/src/components/detail/__tests__/StepApprovalBanner.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react';
import { StepApprovalBanner } from '../StepApprovalBanner';

const pendingStep = {
  id: 'step-1',
  has_approval_gate: true,
  approval_status: 'pending',
};

test('renders banner for pending approval gate', () => {
  render(<StepApprovalBanner runId="run-1" step={pendingStep as any} />);
  expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument();
});

test('renders nothing when no pending gate', () => {
  const { container } = render(
    <StepApprovalBanner runId="run-1" step={{ ...pendingStep, approval_status: 'approved' } as any} />
  );
  expect(container).toBeEmptyDOMElement();
});
```
- [ ] Run `npx vitest run` and confirm all tests pass

**References**
- `docs/bug-removal/step-06-plan.md` — Task 4, Task 5, Task 6 descriptions

**Constraints**
- [ ] Changes limited to `usePendingActions.ts`, `RunDetail.tsx`, and the new test file

**Functionality (Expected Outcomes)**
- [ ] `usePendingActions` badge count includes pending step approval gates
- [ ] `RunDetail` renders `StepApprovalBanner` per step with a pending gate
- [ ] Vitest test for `StepApprovalBanner` passes (both render and no-render cases)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `npx vitest run` exits 0 (all tests pass including the new banner tests)
