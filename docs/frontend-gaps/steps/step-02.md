# Step 2: Branch Status + Back-Merge (Gaps 2, 3)

Add branch status visibility and back-merge capability to RunDetail. Users currently cannot see branch divergence (ahead/behind counts, conflicts) or trigger a back-merge from the UI. This step closes two HIGH-severity gaps that block the branch management user story.

## Intent Verification
**Original Intent**: Close Gaps 2 and 3 (HIGH severity) from `docs/stories/GAP-ANALYSIS-FRONTEND.md` — branch status display and back-merge UI are missing, blocking the branch management journey.
**Functionality to Produce**:
- `BranchStatus` type in `types/branches.ts`
- `useBranchStatus(runId)` query hook with WebSocket-driven refetch
- `useBackMerge()` mutation hook for `POST /api/runs/{id}/back-merge`
- `BranchStatusPanel` component showing branch info and conflict warnings
- `BackMergeDialog` component with confirmation prompt
- RunDetail page renders both components
**Final Verification Criteria**:
- `npx tsc --noEmit` passes
- `BranchStatusPanel.tsx` and `BackMergeDialog.tsx` exist at the expected paths
- `useBranchStatus` and `useBackMerge` are exported from `hooks/useApi.ts`
- BranchStatusPanel appears on RunDetail for runs with branches
- Back-merge button only visible when run is ACTIVE or PAUSED

---

## Task 1: Create BranchStatus Type

**Description**: Define the `BranchStatus` interface so branch status data is typed throughout the frontend.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/types/branches.ts`
- [ ] Add the following type definition:
```typescript
export interface BranchStatus {
  behind_count: number;
  ahead_count: number;
  can_merge_cleanly: boolean;
  has_conflicts: boolean;
  source_branch: string;
  run_branch: string;
}
```

**References**
- `docs/frontend-gaps/architecture.md` — Type Additions (types/branches.ts)
- `docs/frontend-gaps/step-02-plan.md` — Task 1

**Functionality (Expected Outcomes)**
- [ ] `BranchStatus` is importable from `types/branches.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `types/branches.ts` exists and exports `BranchStatus`

---

## Task 2: Add useBranchStatus and useBackMerge Hooks

**Description**: Add query and mutation hooks for branch status fetching and back-merge triggering.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/hooks/useApi.ts`
- [ ] Import `BranchStatus` from `types/branches.ts`
- [ ] Add `useBranchStatus` hook following existing query patterns:
```typescript
export function useBranchStatus(runId: string) {
  return useQuery({
    queryKey: ['branchStatus', runId],
    queryFn: () => apiClient.get<BranchStatus>(`/api/runs/${runId}/branch-status`),
    retry: false, // 404 means no branch — don't retry
  });
}
```
- [ ] Add `useBackMerge` hook following existing mutation patterns:
```typescript
export function useBackMerge(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data?: { strategy?: string }) =>
      apiClient.post(`/api/runs/${runId}/back-merge`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['branchStatus', runId] });
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}
```
- [ ] Ensure `branchStatus` query key is invalidated on WebSocket `run_status_changed` events (check existing WebSocket handler in the codebase and add the query key there)

**Dependencies**
- [ ] Task 1 must be complete (BranchStatus type exists)

**References**
- `docs/frontend-gaps/architecture.md` — New Hooks section (useBranchStatus, useBackMerge)
- Design decision Q2: On-demand fetch + WebSocket event-driven (not polling)
- `docs/frontend-gaps/step-02-plan.md` — Tasks 2, 3

**Constraints**
- Use WebSocket event-driven refetch, not polling
- Follow existing hook patterns in `useApi.ts`

**Functionality (Expected Outcomes)**
- [ ] `useBranchStatus` and `useBackMerge` are exported from `hooks/useApi.ts`
- [ ] Branch status refetches on WebSocket `run_status_changed` events

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Both hooks are exported from `hooks/useApi.ts`

---

## Task 3: Create BranchStatusPanel Component

**Description**: Build the `BranchStatusPanel` component that displays branch info with conflict warnings.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/BranchStatusPanel.tsx`
- [ ] Import `useBranchStatus` from hooks
- [ ] Implement component with props: `runId: string`
- [ ] Render:
  - Source and run branch names
  - Ahead/behind counts (e.g., "3 ahead, 2 behind")
  - Conflict warning indicator when `has_conflicts` is true
  - Loading state while fetching
  - Hide panel entirely when API returns 404 (run has no branch)
  - Inline error with retry button on 500 errors
- [ ] Use TailwindCSS for styling consistent with other detail panels

**Dependencies**
- [ ] Task 2 must be complete (useBranchStatus hook exists)

**References**
- `docs/frontend-gaps/architecture.md` — BranchStatusPanel row
- `docs/frontend-gaps/step-02-plan.md` — Task 4

**Functionality (Expected Outcomes)**
- [ ] `BranchStatusPanel.tsx` exists at `ui/src/components/detail/BranchStatusPanel.tsx`
- [ ] Panel shows branch names, ahead/behind counts, and conflict status

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Component file exists and exports a React component

---

## Task 4: Create BackMergeDialog Component

**Description**: Build the `BackMergeDialog` component with confirmation UI and merge trigger.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/BackMergeDialog.tsx`
- [ ] Import `useBackMerge` from hooks
- [ ] Implement dialog with props: `runId: string`, `isOpen: boolean`, `onClose: () => void`
- [ ] Render:
  - Confirmation prompt explaining the back-merge action
  - Confirm button that calls `useBackMerge.mutate()`
  - Cancel button
  - Loading state during mutation
  - Error handling: 409 → "Merge conflicts detected, resolve manually", 400 → "Back-merge not available in current run state", 500 → generic error + keep dialog open

**Dependencies**
- [ ] Task 2 must be complete (useBackMerge hook exists)

**References**
- `docs/frontend-gaps/architecture.md` — BackMergeDialog row
- `docs/frontend-gaps/step-02-plan.md` — Task 5, Error handling section

**Functionality (Expected Outcomes)**
- [ ] `BackMergeDialog.tsx` exists at `ui/src/components/detail/BackMergeDialog.tsx`
- [ ] Dialog shows confirmation before triggering merge
- [ ] Error states display appropriate messages

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Component file exists and exports a React component

---

## Task 5: Wire BranchStatusPanel and BackMergeDialog into RunDetail

**Description**: Update `pages/RunDetail.tsx` to mount BranchStatusPanel and BackMergeDialog.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/pages/RunDetail.tsx`
- [ ] Import `BranchStatusPanel` and `BackMergeDialog`
- [ ] Add state for back-merge dialog: `showBackMerge` (boolean)
- [ ] Render `BranchStatusPanel` in the RunDetail layout (near the top, after run header)
- [ ] Add a "Back-merge" button in the BranchStatusPanel area, visible only when run status is `ACTIVE` or `PAUSED`
- [ ] Render `BackMergeDialog` controlled by `showBackMerge` state
- [ ] On successful back-merge, close dialog and let cache invalidation refresh the panel

**Dependencies**
- [ ] Tasks 3 and 4 must be complete

**References**
- `docs/frontend-gaps/architecture.md` — RunDetail modifications
- `docs/frontend-gaps/step-02-plan.md` — Task 6

**Constraints**
- Only add branch status and back-merge wiring. Do not modify other RunDetail functionality.

**Functionality (Expected Outcomes)**
- [ ] BranchStatusPanel appears on RunDetail for runs with branches
- [ ] Back-merge button only visible when run is ACTIVE or PAUSED
- [ ] BackMergeDialog shows confirmation before triggering merge
- [ ] Successful back-merge refreshes branch status panel

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `RunDetail.tsx` imports and renders both new components
- [ ] Panel updates when WebSocket `run_status_changed` fires
