# Step 02 Plan: Frontend Review & Merge Tab Skeleton + Branch Status Panel

## Purpose

Create the foundational frontend surface for the Review & Merge workbench. This step adds a new tab to the RunDetail page that renders when the run has an active worktree (regardless of run status). The tab contains a left rail layout with branch status information, a modified files list, and placeholder sections for features built in later steps.

## Prerequisites

- **Step 1** — Backend diff endpoints must exist (`GET /review/diff/files`, `GET /review/commits`, enhanced `GET /branch-status`) so the frontend can fetch and display data.

## Functional Contract

### Inputs

- Run data from existing `useRun()` hook (provides worktree path, branch info, run status)
- `GET /api/runs/{id}/review/diff/files` → file list for left rail
- `GET /api/runs/{id}/review/commits` → commit history for later use
- `GET /api/runs/{id}/branch-status` → enhanced branch status with ahead/behind, predicted conflicts

### Outputs

- `ReviewMergeTab` component rendered as a new tab on `RunDetail.tsx`
- `BranchStatusSection` component showing: branch name, target branch, base/head SHAs, ahead/behind counts, worktree path with copy-to-clipboard button
- `FileListSection` component showing: list of modified files with change stats (additions/deletions), file status icons (added/modified/deleted)
- Tab only visible when the run has a worktree (any run status)
- API client functions in `ui/src/api/reviewClient.ts`: `getDiffFiles()`, `getCommits()`, `getDiff()`
- TanStack Query hooks in `ui/src/hooks/useReview.ts`: `useDiffFiles()`, `useCommits()`, enhanced `useBranchStatus()`

### Errors

- Network failure fetching data → TanStack Query error state displayed in panel
- Run has no worktree → tab is not rendered (handled by conditional rendering)
- Empty file list → "No changes to review" empty state message

## Tasks

1. Create `ui/src/api/reviewClient.ts` with API client functions for review endpoints
2. Create `ui/src/hooks/useReview.ts` with TanStack Query hooks for review data
3. Create `ui/src/types/review.ts` with TypeScript types matching backend schemas
4. Create `ui/src/components/review/ReviewMergeTab.tsx` — top-level tab with left rail + main panel layout
5. Create `ui/src/components/review/BranchStatusSection.tsx` — branch summary display with copy-to-clipboard
6. Create `ui/src/components/review/FileListSection.tsx` — modified files list with change stats
7. Modify `ui/src/pages/RunDetail.tsx` to add "Review & Merge" tab (visible when worktree exists)
8. Write Playwright test: tab renders, branch status displays, file list populates

## Verification

### Auto-Verify

- [ ] Playwright test `test_review_tab_renders` — tab appears on run detail page for a run with a worktree
- [ ] Playwright test `test_file_list_shows_changes` — file list populates with correct entries
- [ ] `npx tsc --noEmit` — no TypeScript errors in new components
- [ ] Frontend builds without errors: `npm run build`

### Manual Verify

- [ ] Tab does NOT appear for runs without a worktree
- [ ] Tab appears for runs in any status (active, completed, failed) as long as worktree exists
- [ ] Branch status section shows correct branch name, ahead/behind counts, worktree path
- [ ] Copy-to-clipboard button copies worktree path
- [ ] File list shows accurate file names, status icons, and +/- line counts
- [ ] Empty file list shows appropriate empty state

## Context & References

- `ui/src/pages/RunDetail.tsx` — existing run detail page to modify
- `ui/src/components/detail/BranchStatusPanel.tsx` — existing branch status component (pattern reference)
- `ui/src/api/client.ts` — existing API client patterns
- `ui/src/hooks/useApi.ts` — existing TanStack Query hook patterns
- `docs/git-ops/architecture.md` — frontend component specifications
