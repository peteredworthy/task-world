# Step 11: Branch History + Task File Attribution

Implement the branch history timeline and task-level file attribution in the Review & Merge workbench. Users can view the full commit history of the run branch, select individual commits to view their diffs, and see which files each task touched.

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — Branch history timeline shows commits with per-commit diff viewing. Task cards show files modified per task with task-scoped diff viewing.

**Functionality to Produce**:
- `HistoryPanel` component showing commit timeline with badges (prune, agent, back-merge)
- Commit selection that updates the diff panel to show that commit's diff
- Radio toggle for "Overall branch changes" vs "Selected commit"
- `TaskFilesPanel` showing task cards with file counts and per-file diff links
- Files appear under every task that touched them (per clarification Q5)
- Task file links open DiffDialog with task scope

**Final Verification Criteria**:
- History panel shows commits in reverse chronological order
- Commit badges correctly identify prune, agent, and back-merge commits
- Selecting a commit switches diff panel scope
- Task cards show correct file counts per task
- Files modified by multiple tasks appear under each task
- Task file "View Diff" link opens DiffDialog with task scope

---

## Task 1: Create HistoryPanel Component

**Description**: Create the commit timeline component for the left rail showing commit history with selection and badges.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/HistoryPanel.tsx`:
  - Section header "Branch History"
  - List of commits from `useCommits()` hook (already created in Step 2)
  - Each commit shows: short SHA, message (truncated), timestamp, author
  - Badge rendering: detect commit types by message patterns
    - "prune:" prefix → prune badge
    - "agent:" prefix or agent-related patterns → agent badge
    - Merge commits → back-merge badge
  - Selected commit highlighted
  - Clicking a commit calls `onCommitSelect` handler

- [ ] Add radio toggle to `ReviewMergeTab` header or near history panel:
  - "Overall branch changes" — shows aggregate diff
  - "Selected commit" — shows selected commit's diff
  - Default: "Overall branch changes"

**References**
- `docs/git-ops/step-11-plan.md` — Tasks 1, 2, 3, 7
- `docs/git-ops/architecture.md` — HistoryPanel spec

**Functionality (Expected Outcomes)**
- [ ] Commits displayed in reverse chronological order
- [ ] Badges correctly identify commit types
- [ ] Selecting a commit updates diff scope
- [ ] Radio toggle switches between aggregate and commit-scoped diff

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 2: Create TaskFilesPanel Component

**Description**: Create the task-level file attribution panel showing task cards with file counts and diff links.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/TaskFilesPanel.tsx`:
  - Section header "Task Files"
  - Task cards showing: task name/ID, "Files touched (N)"
  - Per-file entries within each task card: file name with "View Diff" link
  - Files appear under every task that touched them (use task commit ranges to determine)
  - "View Diff" link opens DiffDialog with `scope=task&ref={start}..{end}`
  - Empty state: "No task data available" for single-task runs or runs without task commit ranges
  - Collapsed by default for tasks with many files (expandable)

- [ ] Implement task-scoped file attribution:
  - Use task commit ranges from run data
  - Fetch file lists per task via `GET /review/diff/files?scope=task&ref={start}..{end}`
  - Map files to their tasks (a file can appear under multiple tasks)

**References**
- `docs/git-ops/step-11-plan.md` — Tasks 4, 5, 6
- `docs/git-ops/clarifications.md` — Q5: files appear under every task that touched them

**Functionality (Expected Outcomes)**
- [ ] Task cards show correct file count
- [ ] Files modified by multiple tasks appear under each task
- [ ] "View Diff" opens DiffDialog with correct task scope

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 3: Wire History and Tasks into ReviewMergeTab

**Description**: Integrate HistoryPanel and TaskFilesPanel into the ReviewMergeTab layout and connect commit selection to diff scope.

**Implementation Plan (Do These Steps)**

- [ ] Add `HistoryPanel` to the left rail in `ReviewMergeTab.tsx` (below test panel)
- [ ] Add `TaskFilesPanel` to the left rail (below history panel)
- [ ] Connect commit selection state:
  - When a commit is selected, update DiffDialog to use `scope=commit&ref={sha}`
  - When "Overall branch changes" is selected, use `scope=aggregate`
- [ ] Wire task file "View Diff" links to open DiffDialog with task scope

**Dependencies**
- [ ] Tasks 1-2 must be complete

**References**
- `docs/git-ops/step-11-plan.md` — Tasks 2, 6

**Functionality (Expected Outcomes)**
- [ ] History and task panels appear in the left rail
- [ ] Commit selection updates the main diff view
- [ ] Task file links open correct task-scoped diffs

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors
- [ ] `cd ui && npm run build` — frontend builds without errors
