# Step 11 Plan: Branch History + Task File Attribution

## Purpose

Implement the branch history timeline and task-level file attribution in the Review & Merge workbench. Users can view the full commit history of the run branch, select individual commits to view their diffs, and see which files each task touched (with each task showing its own diff for shared files).

## Prerequisites

- **Step 2** — Review & Merge tab skeleton must exist with placeholder sections for history and tasks.
- **Step 3** — Diff dialog must exist so selecting a commit or task file link can open the diff dialog with the correct scope.

## Functional Contract

### Inputs

- `GET /api/runs/{id}/review/commits` → commit history (already implemented in Step 1)
- `GET /api/runs/{id}/review/diff?scope=commit&ref={sha}` → per-commit diff (already implemented in Step 1)
- `GET /api/runs/{id}/review/diff?scope=task&ref={start}..{end}` → per-task diff (already implemented in Step 1)
- `GET /api/runs/{id}/review/diff/files?scope=task&ref={start}..{end}` → task-scoped file list (already implemented in Step 1)
- Run task data from existing run hooks (provides task commit ranges)

### Outputs

- `HistoryPanel` component in left rail: commit timeline showing SHA, message, timestamp, and badges (prune, agent, back-merge, manual)
- Commit selection: clicking a commit updates the main diff panel to show that commit's diff
- Radio toggle: "Overall branch changes" vs "Selected commit" to switch diff scope
- `TaskFilesPanel` component: task cards showing "Files touched (N)" with per-file "View Diff" links
- Files appear under every task that touched them (each showing that task's own diff for the file — per clarification Q5)
- Task file links open DiffDialog with task scope

### Errors

- No commits → "No commits on this branch" empty state
- Commit not found → error displayed in diff panel
- Task has no commit range → task card shows "No changes recorded" message
- Single-task runs → task attribution section simplified (all files under one task)

## Tasks

1. Create `ui/src/components/review/HistoryPanel.tsx` — commit timeline with badges and selection
2. Implement commit selection → diff panel scope switching via DiffDialog scope parameter
3. Add radio toggle for "Overall branch changes" vs "Selected commit" in the workbench header
4. Create `ui/src/components/review/TaskFilesPanel.tsx` — task cards with file counts and diff links
5. Implement task-scoped file attribution: compute which files each task touched using task commit ranges
6. Wire task file links to open DiffDialog with `scope=task` and correct ref range
7. Add commit badge rendering (detect prune commits, agent commits, back-merge commits by message patterns)
8. Write Playwright tests: history panel renders, commit selection updates diff, task file links work

## Verification

### Auto-Verify

- [ ] Playwright test `test_branch_history` — commit timeline renders, selecting commit updates diff
- [ ] Playwright test `test_task_file_attribution` — task cards show files, clicking opens task-scoped diff
- [ ] `npx tsc --noEmit` — no TypeScript errors
- [ ] `npm run build` — frontend builds

### Manual Verify

- [ ] History panel shows commits in reverse chronological order with SHA, message, and timestamp
- [ ] Commit badges correctly identify prune, agent, and back-merge commits
- [ ] Selecting a commit switches the diff panel to show that commit's changes
- [ ] Radio toggle switches between overall branch view and selected commit view
- [ ] Task cards show correct file count per task
- [ ] Files that were modified by multiple tasks appear under each task with that task's own diff
- [ ] Task file "View Diff" link opens DiffDialog with correct task scope
- [ ] Empty states handled for no commits and tasks with no changes

## Context & References

- `ui/src/components/review/ReviewMergeTab.tsx` — parent component for history and task panels
- `ui/src/components/review/DiffDialog.tsx` — scope switching for commit/task diffs
- `docs/git-ops/clarifications.md` — Q5: files appear under every task that touched them
- `docs/git-ops/architecture.md` — HistoryPanel, TaskFilesPanel specs
