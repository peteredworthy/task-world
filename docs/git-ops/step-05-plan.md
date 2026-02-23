# Step 05 Plan: Frontend Prune Mode

## Purpose

Implement the interactive prune experience in the Review & Merge workbench. Users can enter a "Prune Mode" that enables selection of unwanted changes at file, hunk, or line granularity directly in the diff viewer. Selected changes can be previewed in a summary modal and applied with confirmation, creating a prune commit on the run branch.

## Prerequisites

- **Step 3** — Diff dialog with `react-diff-view` must exist, as prune mode extends the diff viewer with custom gutter cells for selection.
- **Step 4** — Backend prune endpoints must exist (`POST /prune/preview`, `POST /prune/apply`, `POST /revert-file`) for the frontend to call.

## Functional Contract

### Inputs

- User interactions: toggle prune mode on/off, select/deselect hunks and lines in diff gutter, select "Prune File" from file context menu
- `POST /api/runs/{id}/prune/preview` with `PruneSelection` → preview of resulting state
- `POST /api/runs/{id}/prune/apply` with `PruneSelection` → apply prune and get commit SHA
- `POST /api/runs/{id}/revert-file` with `{ file_path }` → revert entire file

### Outputs

- `PruneModeProvider` context: manages selection state (which files/hunks/lines are selected for pruning)
- `PruneToolbar` banner: indicates prune mode is active, shows selection count, preview and cancel buttons
- `PruneGutter` cells: hunk-level and line-level checkboxes in `react-diff-view` gutter
- File-level "Prune File" action in `⋯` context menu on file list items
- `PrunePreviewModal`: summary of what will be pruned (files affected, hunks/lines removed, resulting diff preview)
- Apply confirmation modal with post-apply toast notification
- After prune-apply: diff files list and diff viewer auto-refresh via TanStack Query invalidation
- Activity feed entry for the prune operation

### Errors

- Prune preview fails → error message in preview modal
- Prune apply fails (e.g., patch conflict) → error toast with failure reason
- Empty selection → "No changes selected" warning, preview button disabled
- File revert fails → error toast

## Tasks

1. Create `ui/src/components/review/PruneModeProvider.tsx` — context provider for prune selection state
2. Create `ui/src/components/review/PruneGutter.tsx` — custom gutter cells for `react-diff-view` with hunk/line checkboxes
3. Create `ui/src/components/review/PruneToolbar.tsx` — prune mode banner with selection count, preview, cancel
4. Create `ui/src/components/review/PrunePreviewModal.tsx` — preview modal with summary and apply confirmation
5. Add "Prune File" action to file list `⋯` context menu in `FileListSection.tsx`
6. Add TanStack Query mutations to `useReview.ts`: `usePrunePreview()`, `usePruneApply()`, `useRevertFile()` with appropriate cache invalidation
7. Wire prune mode toggle into `ReviewMergeTab` header
8. Write Playwright tests: enter prune mode, select hunks, preview, apply, verify changes reflected

## Verification

### Auto-Verify

- [ ] Playwright test `test_prune_mode_enter_exit` — prune mode toggle, banner, gutter controls appear/disappear
- [ ] Playwright test `test_prune_select_and_preview` — select hunks, open preview modal, verify summary
- [ ] Playwright test `test_prune_apply` — apply prune, verify diff updates, activity entry appears
- [ ] `npx tsc --noEmit` — no TypeScript errors
- [ ] `npm run build` — frontend builds

### Manual Verify

- [ ] Prune mode banner is clearly visible and distinguishable from normal view
- [ ] Hunk checkboxes appear in diff gutter when prune mode is active
- [ ] Line-level selection works within a hunk
- [ ] File-level prune via context menu works correctly
- [ ] Preview modal accurately reflects what will be removed
- [ ] Post-prune: file list updates, diff viewer refreshes with changes removed
- [ ] Activity feed shows prune event with details

## Context & References

- `ui/src/components/review/DiffViewer.tsx` — extend with custom gutter for prune selection
- `ui/src/components/review/DiffDialog.tsx` — prune mode integration in diff display
- `ui/src/components/review/FileListSection.tsx` — add context menu actions
- `react-diff-view` documentation — custom gutter cells, hunk/line rendering
- `docs/git-ops/architecture.md` — PruneModeProvider, PruneGutter, PruneToolbar specs
