# Step 9 Plan: Branch Status Panel and Back-Merge (UI-BRANCH-STATUS)

## Purpose

Add branch status visibility and back-merge capability to the `RunDetail` page for ACTIVE and PAUSED runs that have a worktree. Users currently cannot see branch divergence (ahead/behind counts, conflict status) or trigger a back-merge from the UI. The backend endpoints `GET /api/runs/{id}/branch-status` and `POST /api/runs/{id}/back-merge` exist and are implemented; this step adds the client function, hooks, types, and `BranchStatusPanel` component to make them accessible.

## Prerequisites

- None (independent of all other steps)

## Functional Contract

### Inputs

- `run_id` (string) from the `RunDetail` route params
- Run status — `BranchStatusPanel` is visible only when `run.status` is `ACTIVE` or `PAUSED` and the run has a `worktree_path`
- `GET /api/runs/{id}/branch-status` response (`BranchStatusResponse`): `{ behind_count, ahead_count, can_merge_cleanly, has_conflicts, source_branch, run_branch }`
- User clicking "Pull upstream changes" button — triggers `POST /api/runs/{id}/back-merge`

### Outputs

- `getBranchStatus(runId)` and `backMerge(runId)` functions added to `ui/src/api/client.ts`
- `BranchStatusResponse` type added to `ui/src/types/` (file: `types/branches.ts` or similar)
- `useBranchStatus(runId)` query hook added to `ui/src/hooks/useApi.ts` with a 30-second `refetchInterval` (branch drift is slow-changing)
- `useBackMerge()` mutation hook added to `ui/src/hooks/useApi.ts`; invalidates `['run', runId]` and refetches branch status on success
- `BranchStatusPanel` component (new file at `ui/src/components/detail/BranchStatusPanel.tsx`):
  - Shows source branch name, run branch name, ahead/behind counts, conflict warning
  - "Pull upstream changes" button calls `useBackMerge`; disabled when `has_conflicts === true`
  - Conflict warning renders when `has_conflicts` or when `!can_merge_cleanly`
- `RunDetail.tsx` mounts `BranchStatusPanel` for ACTIVE/PAUSED runs with a worktree

### Errors

- `branch-status` API 404 — run has no branch/worktree; hide `BranchStatusPanel` entirely (do not show error)
- `branch-status` API 500 — show inline error state with a retry button in the panel
- `back-merge` API 409 — show error "Merge conflicts detected, resolve manually"
- `back-merge` API 400 — show error "Back-merge not available in current run state"
- `back-merge` API 500 — show error toast; keep panel visible for retry
- TypeScript compile errors must be zero

## Tasks

1. Add `BranchStatusResponse` type to `ui/src/types/` (fields: `behind_count`, `ahead_count`, `can_merge_cleanly`, `has_conflicts`, `source_branch`, `run_branch`)
2. Add `getBranchStatus(runId)` and `backMerge(runId)` to `ui/src/api/client.ts`
3. Add `useBranchStatus(runId)` query hook (30s `refetchInterval`) and `useBackMerge()` mutation hook to `ui/src/hooks/useApi.ts`
4. Create `ui/src/components/detail/BranchStatusPanel.tsx` with ahead/behind display, conflict warning, and merge button
5. Update `ui/src/pages/RunDetail.tsx` to mount `BranchStatusPanel` for ACTIVE/PAUSED runs with a worktree
6. Write Vitest test: render `BranchStatusPanel` with mock branch status data; confirm ahead/behind counts display and conflict warning appears when `has_conflicts === true`

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `BranchStatusPanel.tsx` exists at `ui/src/components/detail/BranchStatusPanel.tsx`
- [ ] `getBranchStatus` and `backMerge` are exported from `ui/src/api/client.ts`
- [ ] `useBranchStatus` and `useBackMerge` are exported from `ui/src/hooks/useApi.ts`
- [ ] `BranchStatusResponse` type is defined and exported
- [ ] Vitest test for `BranchStatusPanel` passes

### Manual Verify

- [ ] `BranchStatusPanel` appears on `RunDetail` for ACTIVE/PAUSED runs with a worktree
- [ ] Panel correctly shows ahead/behind counts and conflict warning
- [ ] Panel auto-refreshes every 30 seconds
- [ ] Panel is hidden for COMPLETED or FAILED runs, or runs without a worktree
- [ ] "Pull upstream changes" button calls the back-merge endpoint and refreshes the panel on success

## Context & References

- Bug report: `docs/bugs/UI-BRANCH-STATUS.md`
- Architecture: `docs/bug-removal/architecture.md` — "New Components: BranchStatusPanel", polling strategy (30s `refetchInterval`)
- Backend endpoints: `GET /api/runs/{id}/branch-status`, `POST /api/runs/{id}/back-merge`
- Source files: `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, `ui/src/pages/RunDetail.tsx`
