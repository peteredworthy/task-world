# Step 4: Add Recovery UI (FAILED-RUN-RECOVERY — Frontend)

This step surfaces the `POST /api/runs/{id}/recover` endpoint (added in Step 3) in the frontend
by adding a `RecoveryPanel` component to the `RunDetail` page. When a run is in `FAILED` status,
the user will see a step/task timeline with clickable rollback points and a confirmation dialog
that includes a `preserve_checklist` toggle. This makes failed-run recovery accessible without
requiring direct API calls or database manipulation.

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "Recovery UI is accessible from the run detail page when run is in FAILED status"
**Functionality to Produce**:
- `RecoverRequest` and `RecoverResponse` TypeScript types
- `recoverRun(runId, data)` API client function
- `useRecoverRun()` mutation hook with run query invalidation
- `RecoveryPanel` component: step/task timeline with rollback selection, confirmation dialog, preserve_checklist toggle
- `RunDetail` mounts `RecoveryPanel` when `run.status === "FAILED"`

**Final Verification Criteria**:
- `npx tsc --noEmit` passes with no type errors
- `RecoveryPanel.tsx` exists at `ui/src/components/detail/RecoveryPanel.tsx`
- `recoverRun` exported from `ui/src/api/client.ts`
- `useRecoverRun` exported from `ui/src/hooks/useApi.ts`

---

## Task 1: Add RecoverRequest and RecoverResponse TypeScript types
**Description**:
Add the TypeScript types for the recovery API request and response to the frontend types directory.

**Implementation Plan (Do These Steps)**
- [ ] Open or create `ui/src/types/recovery.ts` (or add to an existing `runs.ts` types file)
- [ ] Add the following types:
```typescript
export interface RecoverRequest {
  target_task_id: string;
  additional_attempts?: number;
  agent_type?: string;
  agent_config?: Record<string, unknown>;
  preserve_checklist?: boolean;
}

export interface RecoverResponse {
  run_id: string;
  status: string;
  pause_reason: string | null;
  current_step_index: number | null;
}
```
- [ ] Export these types from the types index if one exists

**References**
- `docs/bug-removal/step-04-plan.md` — Task 1 description
- `docs/bug-removal/architecture.md` — "Modified Components: ui/src/types/"

**Constraints**
- [ ] Do not modify existing type definitions; add only new types

**Functionality (Expected Outcomes)**
- [ ] `RecoverRequest` and `RecoverResponse` are importable from `ui/src/types/`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0 after adding the types

---

## Task 2: Add recoverRun client function and useRecoverRun hook
**Description**:
Add the API client function and TanStack Query mutation hook for the recovery endpoint.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/api/client.ts`
- [ ] Add the client function:
```typescript
export async function recoverRun(runId: string, data: RecoverRequest): Promise<RecoverResponse> {
  const response = await fetch(`/api/runs/${runId}/recover`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }
  return response.json();
}
```
- [ ] Open `ui/src/hooks/useApi.ts`
- [ ] Add the mutation hook:
```typescript
export function useRecoverRun(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: RecoverRequest) => recoverRun(runId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}
```

**References**
- `docs/bug-removal/step-04-plan.md` — Task 2 and Task 3 descriptions
- `docs/bug-removal/architecture.md` — "Modified Components: client.ts, useApi.ts"

**Constraints**
- [ ] Only `client.ts` and `useApi.ts` should be changed in this task
- [ ] Handle 404 (task not found) and 409 (not FAILED) error status codes distinctly

**Functionality (Expected Outcomes)**
- [ ] `recoverRun` is exported from `ui/src/api/client.ts`
- [ ] `useRecoverRun` is exported from `ui/src/hooks/useApi.ts`
- [ ] Hook invalidates `['run', runId]` query on success

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `grep -n "recoverRun" ui/src/api/client.ts` shows the export
- [ ] `grep -n "useRecoverRun" ui/src/hooks/useApi.ts` shows the export

---

## Task 3: Create RecoveryPanel component
**Description**:
Create the `RecoveryPanel` component that renders a step/task timeline with rollback target
selection and a confirmation dialog with `preserve_checklist` toggle.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/RecoveryPanel.tsx`
- [ ] The component receives the `run` object (including steps/tasks) as a prop
- [ ] Render a timeline of steps and tasks, each showing last status and `end_commit` (truncated)
- [ ] Clicking a task sets it as the `selectedTaskId` in local state and opens a confirmation dialog
- [ ] Confirmation dialog shows:
  - Which task was selected
  - A warning: "This will reset all downstream tasks to PENDING"
  - A checkbox for `preserve_checklist` (default unchecked)
  - Confirm and Cancel buttons
- [ ] On confirm, call `useRecoverRun` with `{ target_task_id: selectedTaskId, preserve_checklist }`
- [ ] On success, show a success toast; the run query invalidation will update the UI
- [ ] On API error, display the error message and keep the dialog open for retry
```typescript
interface RecoveryPanelProps {
  run: RunDetail; // the full run object including steps and tasks
}

export function RecoveryPanel({ run }: RecoveryPanelProps) {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [preserveChecklist, setPreserveChecklist] = useState(false);
  const recoverMutation = useRecoverRun(run.id);

  // render timeline + dialog
}
```

**References**
- `docs/bug-removal/step-04-plan.md` — Task 4 description
- `docs/bug-removal/architecture.md` — "New Components: RecoveryPanel.tsx"
- `docs/bugs/FAILED-RUN-RECOVERY.md` — UI section

**Constraints**
- [ ] `RecoveryPanel` must only render when `run.status === "FAILED"` (enforced by the parent or internally)
- [ ] Only one new file should be created in this task: `RecoveryPanel.tsx`

**Functionality (Expected Outcomes)**
- [ ] `RecoveryPanel.tsx` exists at `ui/src/components/detail/RecoveryPanel.tsx`
- [ ] Timeline renders steps and tasks with their last status
- [ ] Clicking a task opens a confirmation dialog
- [ ] Confirmation dialog includes a `preserve_checklist` toggle
- [ ] Confirmed recovery calls `useRecoverRun`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] File exists: `ui/src/components/detail/RecoveryPanel.tsx`

---

## Task 4: Mount RecoveryPanel in RunDetail and write Vitest test
**Description**:
Update `RunDetail.tsx` to conditionally mount `RecoveryPanel` for FAILED runs, and write a Vitest
test that renders the panel with a mock FAILED run and confirms the timeline and dialog behavior.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/pages/RunDetail.tsx`
- [ ] Import `RecoveryPanel` from `../components/detail/RecoveryPanel`
- [ ] Inside the RunDetail render, add:
```typescript
{run.status === 'FAILED' && <RecoveryPanel run={run} />}
```
- [ ] Write a Vitest test in `ui/src/components/detail/__tests__/RecoveryPanel.test.tsx` (or equivalent):
```typescript
import { render, screen, fireEvent } from '@testing-library/react';
import { RecoveryPanel } from '../RecoveryPanel';

const mockFailedRun = {
  id: 'run-1',
  status: 'FAILED',
  steps: [
    { id: 'step-1', title: 'Step 1', tasks: [{ id: 'task-1', status: 'FAILED', end_commit: 'abc1234' }] },
  ],
};

test('renders task timeline for FAILED run', () => {
  render(<RecoveryPanel run={mockFailedRun as any} />);
  expect(screen.getByText(/abc1234/i)).toBeInTheDocument();
});

test('opens confirmation dialog on task click', () => {
  render(<RecoveryPanel run={mockFailedRun as any} />);
  fireEvent.click(screen.getByText(/task-1/i));
  expect(screen.getByText(/reset all downstream/i)).toBeInTheDocument();
});
```
- [ ] Run `npx vitest run` and confirm all tests pass

**References**
- `docs/bug-removal/step-04-plan.md` — Task 5 and Task 6 descriptions

**Constraints**
- [ ] Only `RunDetail.tsx` is modified (besides the new test file)
- [ ] Panel must be hidden for non-FAILED runs

**Functionality (Expected Outcomes)**
- [ ] `RunDetail` renders `RecoveryPanel` when run status is FAILED
- [ ] `RunDetail` does NOT render `RecoveryPanel` for ACTIVE, PAUSED, or COMPLETED runs
- [ ] Vitest test for `RecoveryPanel` passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `npx vitest run` exits 0 (all tests pass, including the new RecoveryPanel test)
