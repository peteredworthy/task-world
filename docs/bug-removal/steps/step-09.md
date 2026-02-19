# Step 9: Branch Status Panel and Back-Merge (UI-BRANCH-STATUS)

This step adds branch status visibility and back-merge capability to the `RunDetail` page for
ACTIVE and PAUSED runs that have a worktree. Users currently cannot see branch divergence
(ahead/behind counts, conflict status) or trigger a back-merge from the UI. The backend endpoints
`GET /api/runs/{id}/branch-status` and `POST /api/runs/{id}/back-merge` exist and are tested;
this step adds the client functions, hooks, types, and `BranchStatusPanel` component.

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "`useBranchStatus` and `useBackMerge` exist; `BranchStatusPanel` renders behind/ahead counts and 'Pull upstream changes' for active/paused runs"
**Functionality to Produce**:
- `BranchStatusResponse` type in `ui/src/types/`
- `getBranchStatus(runId)` and `backMerge(runId)` in `ui/src/api/client.ts`
- `useBranchStatus(runId)` query hook (30s `refetchInterval`) and `useBackMerge()` mutation hook
- `BranchStatusPanel` component at `ui/src/components/detail/BranchStatusPanel.tsx`
- `RunDetail` mounts `BranchStatusPanel` for ACTIVE/PAUSED runs with a worktree

**Final Verification Criteria**:
- `npx tsc --noEmit` passes with no type errors
- `BranchStatusPanel.tsx` exists at the expected path
- All exported symbols present in their respective files
- Vitest test for `BranchStatusPanel` passes

---

## Task 1: Add BranchStatusResponse type and client functions
**Description**:
Add the `BranchStatusResponse` TypeScript type and two client functions (`getBranchStatus`,
`backMerge`) to the frontend.

**Implementation Plan (Do These Steps)**
- [ ] Add `BranchStatusResponse` type to `ui/src/types/` (create `types/branches.ts` or extend existing):
```typescript
export interface BranchStatusResponse {
  behind_count: number;
  ahead_count: number;
  can_merge_cleanly: boolean;
  has_conflicts: boolean;
  source_branch: string;
  run_branch: string;
}
```
- [ ] Open `ui/src/api/client.ts` and add:
```typescript
export async function getBranchStatus(runId: string): Promise<BranchStatusResponse> {
  const response = await fetch(`/api/runs/${runId}/branch-status`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}

export async function backMerge(runId: string): Promise<void> {
  const response = await fetch(`/api/runs/${runId}/back-merge`, { method: 'POST' });
  if (!response.ok) throw new ApiError(response.status, await response.text());
}
```

**References**
- `docs/bug-removal/step-09-plan.md` — Task 1 and Task 2 descriptions
- `docs/bugs/UI-BRANCH-STATUS.md`
- Backend endpoints: `GET /api/runs/{id}/branch-status`, `POST /api/runs/{id}/back-merge`

**Constraints**
- [ ] Only `ui/src/types/` (new file) and `ui/src/api/client.ts` should be changed in this task

**Functionality (Expected Outcomes)**
- [ ] `BranchStatusResponse` type exported from `ui/src/types/`
- [ ] `getBranchStatus` and `backMerge` exported from `ui/src/api/client.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0

---

## Task 2: Add useBranchStatus and useBackMerge hooks
**Description**:
Add the TanStack Query hooks: `useBranchStatus` with a 30-second `refetchInterval` for background
polling, and `useBackMerge` mutation that invalidates run and branch status queries on success.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/hooks/useApi.ts`
- [ ] Add the `useBranchStatus` query hook:
```typescript
export function useBranchStatus(runId: string) {
  return useQuery({
    queryKey: ['branchStatus', runId],
    queryFn: () => getBranchStatus(runId),
    refetchInterval: 30_000, // 30 seconds — branch drift is slow-changing
  });
}
```
- [ ] Add the `useBackMerge` mutation hook:
```typescript
export function useBackMerge(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => backMerge(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
      queryClient.invalidateQueries({ queryKey: ['branchStatus', runId] });
    },
  });
}
```

**References**
- `docs/bug-removal/step-09-plan.md` — Task 3 description
- `docs/bug-removal/architecture.md` — "Performance Considerations: useBranchStatus uses 30s polling"

**Constraints**
- [ ] Only `ui/src/hooks/useApi.ts` should be changed in this task
- [ ] `refetchInterval` must be 30 seconds (30_000 ms)

**Functionality (Expected Outcomes)**
- [ ] `useBranchStatus` exported with 30s polling interval
- [ ] `useBackMerge` exported and invalidates both run and branchStatus queries on success

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `grep -n "useBranchStatus\|useBackMerge" ui/src/hooks/useApi.ts` shows both exports

---

## Task 3: Create BranchStatusPanel and mount in RunDetail, write Vitest test
**Description**:
Create the `BranchStatusPanel` component and mount it in `RunDetail` for ACTIVE/PAUSED runs
with a worktree. Write a Vitest test verifying the panel displays ahead/behind counts and the
conflict warning.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/BranchStatusPanel.tsx`:
```typescript
interface BranchStatusPanelProps {
  runId: string;
}

export function BranchStatusPanel({ runId }: BranchStatusPanelProps) {
  const { data, isLoading, isError, refetch } = useBranchStatus(runId);
  const backMergeMutation = useBackMerge(runId);

  if (isLoading) return <div>Loading branch status...</div>;
  if (isError) return (
    <div>
      Unable to load branch status.
      <button onClick={() => refetch()}>Retry</button>
    </div>
  );
  if (!data) return null;

  return (
    <div>
      <p>Source branch: {data.source_branch}</p>
      <p>Run branch: {data.run_branch}</p>
      <p>Behind: {data.behind_count} commits, Ahead: {data.ahead_count} commits</p>
      {(data.has_conflicts || !data.can_merge_cleanly) && (
        <p className="text-red-600">Warning: merge conflicts detected</p>
      )}
      <button
        disabled={data.has_conflicts || backMergeMutation.isPending}
        onClick={() => backMergeMutation.mutate()}
      >
        Pull upstream changes
      </button>
    </div>
  );
}
```
- [ ] Open `ui/src/pages/RunDetail.tsx`
- [ ] Import `BranchStatusPanel` and mount it for ACTIVE/PAUSED runs with a worktree:
```typescript
{['ACTIVE', 'PAUSED'].includes(run.status) && run.worktree_path && (
  <BranchStatusPanel runId={run.id} />
)}
```
- [ ] Write a Vitest test in `ui/src/components/detail/__tests__/BranchStatusPanel.test.tsx`:
```typescript
const mockBranchStatus = {
  behind_count: 3,
  ahead_count: 1,
  can_merge_cleanly: false,
  has_conflicts: true,
  source_branch: 'main',
  run_branch: 'run/abc123',
};

test('renders ahead/behind counts', () => {
  render(<BranchStatusPanel runId="run-1" />); // with mocked useBranchStatus
  expect(screen.getByText(/Behind: 3/i)).toBeInTheDocument();
  expect(screen.getByText(/Ahead: 1/i)).toBeInTheDocument();
});

test('shows conflict warning when has_conflicts is true', () => {
  render(<BranchStatusPanel runId="run-1" />);
  expect(screen.getByText(/merge conflicts detected/i)).toBeInTheDocument();
});
```
- [ ] Run `npx vitest run` and confirm all tests pass

**References**
- `docs/bug-removal/step-09-plan.md` — Task 4, Task 5, Task 6 descriptions
- `docs/bug-removal/architecture.md` — "New Components: BranchStatusPanel.tsx"

**Constraints**
- [ ] New file: `BranchStatusPanel.tsx`; modified file: `RunDetail.tsx`; new test file
- [ ] Panel must be hidden for COMPLETED/FAILED runs or runs without `worktree_path`
- [ ] "Pull upstream changes" button must be disabled when `has_conflicts === true`

**Functionality (Expected Outcomes)**
- [ ] `BranchStatusPanel.tsx` exists at `ui/src/components/detail/BranchStatusPanel.tsx`
- [ ] Panel shows ahead/behind counts and source/run branch names
- [ ] Conflict warning appears when `has_conflicts` or `!can_merge_cleanly`
- [ ] Panel auto-polls every 30 seconds via `useBranchStatus`
- [ ] Vitest test for `BranchStatusPanel` passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `npx vitest run` exits 0 (all tests pass including the new BranchStatusPanel tests)
- [ ] File exists: `ui/src/components/detail/BranchStatusPanel.tsx`
