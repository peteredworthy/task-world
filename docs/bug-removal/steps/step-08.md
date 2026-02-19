# Step 8: Add Backward Step Transition UI (UI-BACKWARD-TRANSITIONS)

This step exposes the backend `POST /api/runs/{id}/transition-back` endpoint in the `StepTimeline`
component, allowing users to revert a run to an earlier step without direct database manipulation.
The backend is fully implemented and tested; this step adds the client function, mutation hook, and
"Revert to this step" UI to each completed step in the timeline, with a confirmation dialog and
optional reason field.

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "`transitionBack` wired in client and hooks; `StepTimeline` shows 'Revert to this step' on completed preceding steps with a confirmation dialog"
**Functionality to Produce**:
- `transitionBack(runId, data)` in `ui/src/api/client.ts`
- `useTransitionBack()` mutation hook in `ui/src/hooks/useApi.ts`
- `StepTimeline.tsx` updated: "Revert to this step" action on completed steps preceding current step
- Confirmation dialog with optional reason field; calls `useTransitionBack` on confirm

**Final Verification Criteria**:
- `npx tsc --noEmit` passes with no type errors
- `transitionBack` exported from `client.ts`
- `useTransitionBack` exported from `useApi.ts`
- Vitest test for `StepTimeline` revert action passes

---

## Task 1: Add transitionBack client function and useTransitionBack hook
**Description**:
Add the API client function for `POST /api/runs/{id}/transition-back` and the TanStack Query
mutation hook that invalidates the run query on success.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/api/client.ts`
- [ ] Add the client function:
```typescript
export async function transitionBack(
  runId: string,
  data: { target_step_index: number; reason?: string },
): Promise<void> {
  const response = await fetch(`/api/runs/${runId}/transition-back`, {
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
- [ ] Add the mutation hook:
```typescript
export function useTransitionBack(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { target_step_index: number; reason?: string }) =>
      transitionBack(runId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}
```

**References**
- `docs/bug-removal/step-08-plan.md` — Task 1 and Task 2 descriptions
- `docs/bugs/UI-BACKWARD-TRANSITIONS.md` — Current State and Work Required
- Backend endpoint: `src/orchestrator/api/routers/runs.py:837`

**Constraints**
- [ ] Only `client.ts` and `useApi.ts` should be changed in this task

**Functionality (Expected Outcomes)**
- [ ] `transitionBack` exported from `ui/src/api/client.ts`
- [ ] `useTransitionBack` exported from `ui/src/hooks/useApi.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `grep -n "transitionBack" ui/src/api/client.ts` shows the export
- [ ] `grep -n "useTransitionBack" ui/src/hooks/useApi.ts` shows the export

---

## Task 2: Update StepTimeline with revert action and confirmation dialog, write Vitest test
**Description**:
Update `StepTimeline.tsx` to show a "Revert to this step" action on each completed step that
precedes the current active step. Clicking opens a confirmation dialog with an optional reason
field. Confirming calls `useTransitionBack`. Write a Vitest test for the behavior.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/StepTimeline.tsx`
- [ ] Add local state for the dialog: `selectedStepIndex` and `reason`
- [ ] For each step that is completed AND precedes the current active step, add a "Revert to this step" button:
```typescript
{step.status === 'COMPLETED' && step.index < currentStepIndex && (
  <button
    onClick={() => setSelectedStepIndex(step.index)}
    className="text-sm text-amber-600 hover:underline"
  >
    Revert to this step
  </button>
)}
```
- [ ] Add a confirmation dialog (modal) that opens when `selectedStepIndex !== null`:
```typescript
{selectedStepIndex !== null && (
  <ConfirmationDialog
    title="Revert to this step?"
    description={`This will reset all tasks from step ${selectedStepIndex + 1} onward to PENDING. Are you sure?`}
    onConfirm={() => {
      transitionBackMutation.mutate({ target_step_index: selectedStepIndex, reason });
      setSelectedStepIndex(null);
    }}
    onCancel={() => setSelectedStepIndex(null)}
  >
    <textarea
      placeholder="Optional reason for reverting..."
      value={reason}
      onChange={(e) => setReason(e.target.value)}
    />
  </ConfirmationDialog>
)}
```
- [ ] Handle API errors: show error toast for 400 ("Invalid step"), 409 ("Run must be ACTIVE or PAUSED"), 500 (generic)
- [ ] Write a Vitest test in `ui/src/components/__tests__/StepTimeline.test.tsx` (or extend existing):
```typescript
const mockSteps = [
  { id: 'step-1', index: 0, status: 'COMPLETED', title: 'Step 1' },
  { id: 'step-2', index: 1, status: 'ACTIVE', title: 'Step 2' },
];

test('shows revert action on completed steps before current', () => {
  render(<StepTimeline steps={mockSteps} currentStepIndex={1} runId="run-1" />);
  expect(screen.getByText(/revert to this step/i)).toBeInTheDocument();
});

test('opens confirmation dialog on revert click', () => {
  render(<StepTimeline steps={mockSteps} currentStepIndex={1} runId="run-1" />);
  fireEvent.click(screen.getByText(/revert to this step/i));
  expect(screen.getByText(/reset all tasks from step/i)).toBeInTheDocument();
});
```
- [ ] Run `npx vitest run` and confirm all tests pass

**References**
- `docs/bug-removal/step-08-plan.md` — Task 3 and Task 4 descriptions
- `docs/bug-removal/architecture.md` — "Modified Components: StepTimeline.tsx"
- Source file: `ui/src/components/StepTimeline.tsx`

**Constraints**
- [ ] Only `StepTimeline.tsx` and the new/extended test file should be changed in this task
- [ ] "Revert to this step" must NOT appear on the current active step or steps after it

**Functionality (Expected Outcomes)**
- [ ] "Revert to this step" action appears on each completed step preceding the current step
- [ ] Confirmation dialog renders on click with the correct step warning message
- [ ] Optional reason textarea is present in the dialog
- [ ] `useTransitionBack` is called on confirm with the step index and reason

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `npx vitest run` exits 0 (all tests pass including the new StepTimeline revert tests)
