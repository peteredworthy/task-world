# Step 03 Plan: Diff Dialog with react-diff-view

## Purpose

Implement the core diff viewing experience: a near full-screen overlay dialog that renders unified diffs using `react-diff-view`. This component is the primary surface for reviewing code changes and is reused across multiple features (aggregate branch diff, per-commit diff, per-task diff, prune mode, conflict resolution).

## Prerequisites

- **Step 2** — Review & Merge tab skeleton must exist with `FileListSection` so clicking a file can open the diff dialog.
- **Step 1** — Backend `GET /review/diff` endpoint must exist to fetch diff content by scope.

## Functional Contract

### Inputs

- File path selected from `FileListSection` (triggers dialog open)
- `GET /api/runs/{id}/review/diff?scope=aggregate` → full branch diff text
- `GET /api/runs/{id}/review/diff?scope=commit&ref={sha}` → single commit diff
- `GET /api/runs/{id}/review/diff?scope=task&ref={start_sha}..{end_sha}` → task-scoped diff
- Scope selector state (aggregate, commit, task)
- View mode state (inline vs. side-by-side)

### Outputs

- `DiffDialog` component: near full-screen overlay with file header, scope selector dropdown, inline/side-by-side toggle
- `DiffViewer` component: core `react-diff-view` wrapper that parses unified diff text and renders hunks with syntax highlighting
- Diff parsed and rendered via `react-diff-view` with `gitdiff-parser` (or equivalent) for parsing unified diff text into structured format
- Scope switching re-fetches diff with new parameters and re-renders
- View mode toggle switches between inline and split rendering

### Errors

- Diff fetch failure → error message displayed in dialog body
- Unparseable diff text → fallback to raw text display with warning
- Empty diff for selected scope → "No changes in this scope" message
- File not found in diff → dialog shows file header with "File not in diff" message

## Tasks

1. Install `react-diff-view` and `unidiff` (or `gitdiff-parser`) npm packages
2. Create `ui/src/components/review/DiffViewer.tsx` — core `react-diff-view` integration (parse diff, render hunks, inline/split modes)
3. Create `ui/src/components/review/DiffDialog.tsx` — near full-screen overlay with file header, scope selector, view mode toggle
4. Wire `FileListSection` file clicks to open `DiffDialog` with correct file and scope
5. Implement scope switching (aggregate/commit/task) in dialog header
6. Add `useDiff()` hook to `useReview.ts` for fetching diff content by scope
7. Write Playwright tests: dialog opens, diff renders, view mode toggles, scope switching

## Verification

### Auto-Verify

- [ ] Playwright test `test_diff_dialog_opens` — clicking a file opens the diff dialog with rendered diff content
- [ ] Playwright test `test_diff_view_modes` — inline/side-by-side toggle switches rendering mode
- [ ] Playwright test `test_diff_scope_switch` — scope selector changes diff content
- [ ] `npx tsc --noEmit` — no TypeScript errors
- [ ] `npm run build` — frontend builds without errors

### Manual Verify

- [ ] Diff dialog is near full-screen with file name in header
- [ ] Unified diff renders with correct syntax highlighting and line numbers
- [ ] Side-by-side mode shows old/new content in parallel columns
- [ ] Scope selector shows aggregate/commit/task options
- [ ] Large diffs scroll correctly within the dialog
- [ ] Dialog closes cleanly with Escape key or close button

## Context & References

- `react-diff-view` documentation — hunk rendering, custom gutters, view modes
- `ui/src/components/review/FileListSection.tsx` — file click triggers dialog
- `ui/src/hooks/useReview.ts` — `useDiff()` hook for data fetching
- `docs/git-ops/architecture.md` — DiffDialog and DiffViewer component specs
