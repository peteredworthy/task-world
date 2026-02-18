# Step 2 Plan: Branch Status + Back-Merge (Gaps 2, 3)

## Purpose

Add branch status visibility and back-merge capability to RunDetail. Users currently cannot see branch divergence (ahead/behind counts, conflicts) or trigger a back-merge from the UI. This step closes two HIGH-severity gaps that block the branch management user story.

## Prerequisites

- None (can run in parallel with Step 1)

## Functional Contract

### Inputs

- `run_id` (string) — from RunDetail route params
- WebSocket `run_status_changed` events — trigger branch status refetch
- Run status — back-merge button only visible when run is `ACTIVE` or `PAUSED`
- User confirmation via BackMergeDialog before triggering merge
- Optional merge strategy selection (default: merge) — this is basic in Step 2, enhanced in Step 3

### Outputs

- `BranchStatusPanel` component showing: source branch name, run branch name, ahead/behind counts, conflict warning indicator
- `BackMergeDialog` component with confirmation prompt and merge trigger
- `useBranchStatus(runId)` hook wrapping `GET /api/runs/{id}/branch-status` with WebSocket-driven refetch
- `useBackMerge()` mutation hook wrapping `POST /api/runs/{id}/back-merge`
- `BranchStatus` type in `types/branches.ts`
- RunDetail updated to render BranchStatusPanel and BackMergeDialog

### Errors

- Branch status API returns 404 — run has no branch → hide BranchStatusPanel entirely
- Branch status API returns 500 — show inline error with retry button in panel
- Back-merge API returns 409 — merge conflicts → show error "Merge conflicts detected, resolve manually"
- Back-merge API returns 400 — invalid run state → show error "Back-merge not available in current run state"
- Back-merge API returns 500 — server error → show error toast, keep dialog open for retry

## Tasks

1. Create `types/branches.ts` with `BranchStatus` interface (`behind_count`, `ahead_count`, `can_merge_cleanly`, `has_conflicts`, `source_branch`, `run_branch`)
2. Add `useBranchStatus(runId)` query hook to `hooks/useApi.ts` — fetch on load, refetch on WebSocket `run_status_changed` events
3. Add `useBackMerge()` mutation hook to `hooks/useApi.ts` calling `POST /api/runs/{id}/back-merge`
4. Create `components/detail/BranchStatusPanel.tsx` displaying branch info with conflict warning
5. Create `components/detail/BackMergeDialog.tsx` with confirmation UI and merge trigger
6. Update `pages/RunDetail.tsx` to mount BranchStatusPanel and BackMergeDialog

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `BranchStatusPanel.tsx` exists at `ui/src/components/detail/BranchStatusPanel.tsx`
- [ ] `BackMergeDialog.tsx` exists at `ui/src/components/detail/BackMergeDialog.tsx`
- [ ] `useBranchStatus` and `useBackMerge` are exported from `hooks/useApi.ts`
- [ ] `BranchStatus` type is defined and exported from `types/branches.ts`

### Manual Verify

- [ ] BranchStatusPanel appears on RunDetail for runs with branches
- [ ] Panel shows correct ahead/behind counts and conflict status
- [ ] Panel updates when WebSocket `run_status_changed` fires (no polling)
- [ ] Back-merge button only visible when run is ACTIVE or PAUSED
- [ ] BackMergeDialog shows confirmation before triggering merge
- [ ] Successful back-merge refreshes branch status panel

## Context & References

- Gap analysis: `docs/stories/GAP-ANALYSIS-FRONTEND.md` — Gaps 2, 3 (HIGH severity)
- Design decision Q2: On-demand fetch + WebSocket event-driven (not polling)
- Backend endpoints: `GET /api/runs/{id}/branch-status`, `POST /api/runs/{id}/back-merge`
- Architecture: `docs/frontend-gaps/architecture.md` — BranchStatusPanel, BackMergeDialog sections
