# Feature: Branch Status Panel and Back-Merge UI

## Summary

The backend exposes branch ahead/behind counts, merge-ability, and a back-merge trigger, but
the frontend only has `mergeBack` wired (for COMPLETED runs). There is no UI to show branch
drift for ACTIVE/PAUSED runs or to trigger a back-merge to pull upstream changes into the run
branch.

## Current State

**Backend — complete:**
- `GET /api/runs/{id}/branch-status` — returns `{ behind_count, ahead_count, can_merge_cleanly, has_conflicts, source_branch, run_branch }`
- `POST /api/runs/{id}/back-merge` — pulls source branch into run branch (ACTIVE/PAUSED only)
- `POST /api/runs/{id}/merge-back` — merges run branch into source (COMPLETED only)

**Frontend — partial:**
- `mergeBack()` client function and `useMergeBack()` hook exist and are wired ✅
- No `getBranchStatus(runId)` in `ui/src/api/client.ts`
- No `useBackMerge` mutation (distinct from `useMergeBack`)
- No `useBranchStatus(runId)` query hook
- No `BranchStatusResponse` type in `ui/src/types/`
- No component renders behind/ahead counts or a "Pull upstream changes" button

## Work Required

1. **`ui/src/types/`** — add `BranchStatusResponse`:
   ```ts
   interface BranchStatusResponse {
     behind_count: number;
     ahead_count: number;
     can_merge_cleanly: boolean;
     has_conflicts: boolean;
     source_branch: string;
     run_branch: string;
   }
   ```

2. **`ui/src/api/client.ts`** — add:
   ```ts
   getBranchStatus(runId: string): Promise<BranchStatusResponse>
   backMerge(runId: string): Promise<{ merge_commit: string; message: string }>
   ```

3. **`ui/src/hooks/useApi.ts`** — add `useBranchStatus(runId)` query and `useBackMerge`
   mutation (invalidates `['run', runId]`).

4. **UI — branch status panel:** For ACTIVE/PAUSED runs with a worktree, show a small panel
   (e.g., alongside the run header or in a details sidebar) with:
   - `{behind_count} behind / {ahead_count} ahead` of `source_branch`
   - "Pull upstream changes" button (calls `useBackMerge`) when `behind_count > 0`
   - Conflict warning when `has_conflicts` is true
   - The existing merge-back button (for COMPLETED runs) is already present

## Severity

**Medium** — without branch status visibility, runs silently drift from the source branch.
The back-merge endpoint exists but can't be triggered from the UI.

## Related

- `docs/ui-gaps2/README.md §6`
- `src/orchestrator/api/routers/runs.py:851` — branch-status endpoint
- `src/orchestrator/api/routers/runs.py:885` — back-merge endpoint
- `src/orchestrator/git/branch_ops.py` — `get_branch_status()`, `back_merge()`
- `ui/src/hooks/useApi.ts:useMergeBack` — exists; `useBackMerge` is the complement for ACTIVE runs
