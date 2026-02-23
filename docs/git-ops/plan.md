# Plan: Run Review, Prune & Merge Workbench

## Overview

Implement the pre-merge review workbench in seven iterative milestones. Each milestone delivers a testable vertical slice — backend API, frontend UI, and Playwright E2E tests — so the system stays runnable and verifiable after every step. The implementation agent should use the `/iterate` skill within each step to drive iterative build-verify cycles and confirm correctness before moving on.

## Milestones

### Milestone 1: Review Tab Foundation + Diff Visibility

**Goal:** A new "Review & Merge" tab exists on the run detail page showing branch status, modified file list, worktree path (with copy), and a basic diff viewer.

**What works after this milestone:**
- User opens any run that has a worktree (regardless of run status) and sees a "Review & Merge" tab
- Tab shows branch name, target branch, base/head SHAs, ahead/behind counts, worktree path with copy button
- Modified files listed in left rail; clicking a file opens a near full-screen diff dialog
- Diff dialog renders unified diff via `react-diff-view` with inline/side-by-side toggle
- Diff scopes: branch aggregate, per-commit, per-task
- Playwright tests confirm tab renders, file list populates, diff dialog opens, and view modes toggle

### Milestone 2: Prune Mode + Test Execution

**Goal:** Users can select and remove unwanted changes (file/hunk/line), then run tests from the workbench to validate the result.

**What works after this milestone:**
- "Prune Mode" button enters selection state with hunk/line checkboxes in the diff gutter
- File-level revert available from the file list context menu
- Preview modal shows summary of what will be pruned; apply confirmation via modal
- Prune operations recorded in run events and visible in activity feed
- "Run Tests" button executes the routine's `auto_verify` commands against the run worktree
- Test panel shows pass/fail, summary counts, duration, and collapsible log output
- Playwright tests confirm prune selection, preview, apply, and test execution flow

### Milestone 3: Back Merge + Conflict Detection & Display

**Goal:** Users can pull the latest target branch into the run branch and see any resulting conflicts.

**What works after this milestone:**
- "Back Merge" button opens confirmation modal showing source/target branches and predicted conflict count
- After back merge, clean merges auto-commit with a post-merge review banner (with undo option); conflicts enter merge-in-progress state
- Conflict files shown in a distinct group in the left rail with unresolved/resolved status
- Merge readiness indicator shows whether merge is clean or conflicts exist
- Playwright tests confirm back merge flow, conflict detection, and conflict file display

### Milestone 4: Conflict Resolver UI

**Goal:** Users can manually resolve merge conflicts in a near full-screen dialog.

**What works after this milestone:**
- Clicking a conflict file opens the conflict resolver dialog
- Conflict blocks displayed with ours/theirs sections highlighted (warm/cool tinting)
- Per-block actions: "Keep Run (ours)", "Keep Target (theirs)", "Manual Selection"
- Resolution status tracked per file; "Mark File Resolved" with confirmation
- Navigation between conflict files (prev/next)
- Merge readiness updates as conflicts are resolved
- Playwright tests confirm conflict resolution flow and readiness gate updates

### Milestone 5: Agent Assist (Fix Tests + Resolve Conflicts)

**Goal:** Users can dispatch agent work to fix failing tests or resolve merge conflicts without leaving the workbench.

**What works after this milestone:**
- "Use Agent to Fix Tests" opens modal (defaults to run's agent; Advanced toggle reveals agent picker), dispatches agent against run worktree, shows progress
- On agent completion, diff and test status update automatically
- "Use Agent to Resolve Conflicts" opens modal (same agent default + Advanced override), dispatches agent scoped to unresolved conflicts
- Post-agent review banner shows changed files and remaining conflict count
- Readiness gates re-evaluate after agent completion
- Playwright tests confirm agent dispatch, progress display, and post-agent state updates

### Milestone 6: Final Merge Gating + Merge Execution

**Goal:** A persistent merge readiness bar gates the final merge-back action; merging only proceeds when all conditions are met.

**What works after this milestone:**
- Sticky readiness bar at bottom of Review & Merge tab showing all gate statuses
- Gates: clean merge prediction, no unresolved conflicts, required tests pass, no active jobs
- "Commit Merge Back" button disabled with explanation when gates are unmet
- When all gates pass, button is enabled; clicking opens confirmation modal with merge strategy choice (squash default, merge commit option)
- Merge execution uses the user-selected strategy
- Readiness recomputed after prune, test, back merge, conflict resolution, and agent actions
- Playwright tests confirm gating logic, disabled/enabled states, and successful merge execution

### Milestone 7: Branch History + Task File Attribution + Visual Polish

**Goal:** Full branch history viewing, task-scoped file diffs, keyboard shortcuts, and visual regression testing.

**What works after this milestone:**
- Branch history panel shows commit timeline with badges (prune, agent, back-merge)
- Selecting a commit updates the main diff panel to show that commit's diff
- Task cards show "Files touched (N)" with links to task-scoped diffs; files appear under every task that touched them (each showing that task's own diff)
- Keyboard shortcuts for navigation (j/k, [/], Shift+P, t)
- Empty/edge states handled (no changes, no conflicts, binary files, large diffs)
- Playwright visual regression tests for all major workbench states
- UX polish pass: loading states, error states, responsive behavior

## Implementation Order

1. **Step 1: Backend diff endpoints + branch status enhancements**
   - Prerequisites: None
   - Deliverables:
     - `GET /api/runs/{id}/diff` — returns unified diff (aggregate, per-commit, per-task scopes via query params)
     - `GET /api/runs/{id}/diff/files` — returns list of modified files with change stats
     - `GET /api/runs/{id}/commits` — returns commit history for the run branch
     - Enhance existing `GET /api/runs/{id}/branch-status` with predicted conflict count, merge readiness fields
     - Pydantic schemas: `DiffResponse`, `DiffFileEntry`, `CommitEntry`, enhanced `BranchStatusResponse`
     - Unit tests for diff generation logic; integration tests for API endpoints
   - Agent guidance: Use `/iterate` to build each endpoint, write its tests, and verify they pass before moving to the next endpoint.

2. **Step 2: Frontend Review & Merge tab skeleton + branch status panel**
   - Prerequisites: Step 1
   - Deliverables:
     - New `ReviewMergeTab` component added as a tab on `RunDetail.tsx`
     - Left rail with `BranchStatusSection`, `FileListSection` (modified files), placeholder sections for conflicts/history/tasks
     - Worktree path display with copy-to-clipboard
     - TanStack Query hooks: `useDiffFiles()`, `useCommits()`, enhanced `useBranchStatus()`
     - API client functions for new endpoints
     - Playwright test: tab renders, branch status displays, file list populates
   - Agent guidance: Use `/iterate` to scaffold the tab, wire up data fetching, and confirm via Playwright.

3. **Step 3: Diff dialog with `react-diff-view`**
   - Prerequisites: Step 2
   - Deliverables:
     - Install `react-diff-view` and `unidiff` (or equivalent diff parsing library)
     - `DiffDialog` component: near full-screen overlay, file header, scope selector (aggregate/commit/task), inline/side-by-side toggle
     - `react-diff-view` integration: parse unified diff, render hunks with syntax highlighting
     - File list clicks open `DiffDialog` with correct scope
     - Playwright tests: dialog opens, diff renders, view mode toggles work, scope switching works
   - Agent guidance: Use `/iterate` — first get the dialog shell rendering, then integrate diff parsing, then wire up scope switching, verifying each iteration.

4. **Step 4: Backend prune endpoints**
   - Prerequisites: Step 1
   - Deliverables:
     - `POST /api/runs/{id}/prune/preview` — accepts prune selections (file/hunk/line), returns preview of resulting state
     - `POST /api/runs/{id}/prune/apply` — applies prune selections to the run worktree, records event
     - `POST /api/runs/{id}/revert-file` — reverts a single file to base/target state
     - Prune logic in `src/orchestrator/git/` using `git apply --reverse` or `git checkout` for file-level
     - Pydantic schemas: `PruneSelection`, `PrunePreviewResponse`, `PruneApplyResponse`
     - New event types: `PRUNE_APPLIED` in workflow events
     - Integration tests for prune operations against real git repos
   - Agent guidance: Use `/iterate` — implement file-level prune first (simplest), then hunk-level, then line-level, testing each level.

5. **Step 5: Frontend prune mode**
   - Prerequisites: Steps 3, 4
   - Deliverables:
     - Prune mode toggle in workbench header; banner indicating selection mode active
     - Custom `react-diff-view` gutter cells: hunk selection checkbox, line selection checkboxes
     - Selection state management (which files/hunks/lines are selected for pruning)
     - File-level "Prune File" action in `⋯` context menu on file list items
     - Preview modal showing summary and resulting diff
     - Apply confirmation modal with post-apply toast and activity feed entry
     - TanStack Query mutations: `usePrunePreview()`, `usePruneApply()`, `useRevertFile()`
     - Playwright tests: enter prune mode, select hunks, preview, apply, verify changes reflected
   - Agent guidance: Use `/iterate` — first get prune mode toggle and gutter rendering, then selection logic, then preview/apply flow, testing each.

6. **Step 6: Backend test execution endpoint**
   - Prerequisites: Step 1
   - Deliverables:
     - `POST /api/runs/{id}/review/test` — executes the routine's `auto_verify` commands in the run worktree, streams or returns results
     - `GET /api/runs/{id}/review/test/{test_run_id}` — get test run result (status, summary, log output)
     - Test execution runs in the worktree directory using the routine's `auto_verify` commands from the task/step configuration
     - Pydantic schemas: `TestRunRequest`, `TestRunResponse`, `TestRunResult`
     - Integration tests for test execution against a real worktree
   - Agent guidance: Use `/iterate` — implement the execution endpoint, then the result retrieval endpoint, verifying with integration tests.

7. **Step 7: Frontend test panel + agent fix tests**
   - Prerequisites: Steps 5, 6
   - Deliverables:
     - Test panel in left rail: profile selector, last run status, "Run Tests" button, "View Logs" drawer
     - Test logs drawer: summary counts, failing tests list, terminal output (collapsible)
     - "Use Agent to Fix Tests" modal: scope description, confirmation, progress indicator; defaults to run's agent with Advanced toggle for agent override
     - Agent fix dispatches agent work against run worktree (reuses existing agent execution infrastructure with selected agent_type/config)
     - Post-agent: diff and test status auto-refresh
     - TanStack Query hooks: `useRunTests()`, `useTestResult()`, `useAgentFixTests()`
     - Playwright tests: run tests, view logs, trigger agent fix, verify post-agent state
   - Agent guidance: Use `/iterate` — first the test panel and execution, then the agent fix flow, verifying each with Playwright.

8. **Step 8: Backend conflict resolution endpoints**
   - Prerequisites: Step 1
   - Deliverables:
     - `GET /api/runs/{id}/conflicts` — returns list of conflict files with block details
     - `POST /api/runs/{id}/conflicts/{file_path}/resolve` — applies resolution for a file (keep-ours/keep-theirs/manual per block)
     - `POST /api/runs/{id}/conflicts/agent-resolve` — dispatches agent to resolve remaining conflicts
     - Enhance `POST /api/runs/{id}/back-merge` to auto-commit clean merges and return conflict details on conflict
     - `POST /api/runs/{id}/review/revert-back-merge` — reverts the last back merge commit (undo action)
     - Pydantic schemas: `ConflictFile`, `ConflictBlock`, `ConflictResolutionRequest`, `ConflictResolutionResponse`
     - Integration tests for conflict detection and resolution against real git repos with merge conflicts
   - Agent guidance: Use `/iterate` — set up a test fixture with merge conflicts first, then implement detection, then resolution, verifying each.

9. **Step 9: Frontend back merge + conflict resolver**
   - Prerequisites: Steps 3, 8
   - Deliverables:
     - "Back Merge" button with confirmation modal (source/target branches, predicted conflicts)
     - Post-back-merge state display: clean result with review banner (undo option to revert merge commit), or conflict list for conflicted merges
     - Conflict files group in left rail with unresolved/resolved status chips
     - Conflict resolver dialog: near full-screen, conflict block display with ours/theirs highlighting
     - Per-block actions: "Keep Run (ours)", "Keep Target (theirs)", "Manual Selection"
     - "Mark File Resolved" with confirmation modal
     - "Use Agent to Resolve Conflicts" modal (defaults to run's agent, Advanced toggle for override) and progress display
     - Prev/next file navigation in conflict resolver
     - TanStack Query hooks: `useConflicts()`, `useResolveConflict()`, `useAgentResolveConflicts()`
     - Playwright tests: back merge flow, conflict display, manual resolution, agent resolution
   - Agent guidance: Use `/iterate` — first the back merge UI and modal, then conflict display, then resolver dialog, then agent resolution, testing each phase.

10. **Step 10: Merge readiness gating + final merge**
    - Prerequisites: Steps 5, 7, 9
    - Deliverables:
      - `GET /api/runs/{id}/merge-readiness` — returns all gate statuses (clean merge, no conflicts, tests green, no active jobs)
      - Sticky readiness bar component at bottom of Review & Merge tab
      - Gate status indicators with explanations for unmet conditions
      - "Commit Merge Back" button: disabled when gates unmet, enabled when all pass; opens confirmation modal with merge strategy choice (squash default, merge commit option)
      - Merge execution reuses existing `POST /api/runs/{id}/merge-back` with pre-flight readiness check and user-selected merge strategy
      - Readiness auto-refresh after state-changing operations (prune, test, back merge, conflict resolution, agent actions)
      - TanStack Query hook: `useMergeReadiness()` with invalidation on related mutations
      - Playwright tests: verify gating logic (disabled when tests fail, enabled when all green), successful merge
    - Agent guidance: Use `/iterate` — first the readiness endpoint and UI bar, then gating logic, then merge execution, testing each.

11. **Step 11: Branch history + task file attribution**
    - Prerequisites: Steps 2, 3
    - Deliverables:
      - History panel in left rail: commit timeline with SHA, message, timestamp, badges
      - Commit selection updates main diff panel scope
      - Radio toggle: "Overall branch changes" vs "Selected commit"
      - Task cards enhanced with "Files touched (N)" and per-file "View Diff" links
      - Task-scoped diff dialog using per-task diff scope from Step 1 endpoints
      - Playwright tests: history panel renders, commit selection updates diff, task file links work
    - Agent guidance: Use `/iterate` to build history panel, then task file attribution, verifying each.

12. **Step 12: Visual polish + edge states + keyboard shortcuts + visual regression tests**
    - Prerequisites: Steps 1-11
    - Deliverables:
      - Empty states: "Nothing to review" (no changes), "Back merge clean" (no conflicts)
      - Binary file handling: metadata display, keep-ours/keep-theirs only
      - Large diff lazy rendering with collapsed-by-default file sections
      - Keyboard shortcuts: j/k (next/prev change), [/] (prev/next conflict file), Shift+P (prune mode), t (run tests)
      - Loading states, error states, responsive behavior
      - Playwright visual regression tests for all major workbench states
      - Documentation updates: `docs/ARCHITECTURE.md` route table, directory map
    - Agent guidance: Use `/iterate` — tackle each polish item, run visual regression after each, fix issues iteratively.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Diff rendering library | `react-diff-view` | Specified in PRD; supports unified/split, custom gutters, hunk-level rendering |
| E2E test framework | Playwright | Specified in requirements; supports visual regression, cross-browser, and interaction testing |
| Prune implementation | Git patch reverse-apply | Safe, auditable, works at file/hunk/line level using git's own diff machinery |
| Conflict resolution granularity | Block-level (ours/theirs/manual) | Matches PRD; avoids full editor complexity while enabling meaningful resolution |
| Test execution model | Subprocess in worktree directory | Consistent with existing agent execution pattern; captures stdout/stderr for display |
| Test command source | Routine's `auto_verify` commands | Reuses existing task/step configuration; no new config surface needed |
| Agent assist dispatch | Default to run's agent, Advanced toggle for override | Simplest UX by default (single confirmation modal); Advanced toggle reveals agent picker for flexibility |
| Merge readiness computation | Server-side with client polling | Authoritative gate evaluation on backend; frontend polls/invalidates after mutations |
| Prune commit strategy | Auto-commit on apply | Each prune-apply creates a dedicated commit on the run branch for auditability |
| Line-level prune | Selection-only from existing diff lines in v1 | PRD lists it; implementing after hunk-level is incremental with same selection model; no free-form editing |
| Test profile | Single default per run (routine's auto_verify) | v1 simplicity; configurable profiles deferred per Non-Goals |
| Tab availability | Any run status as long as worktree exists | Maximum flexibility — users can review in-progress, completed, or failed runs |
| Merge strategy for final merge-back | User choice: squash (default) or merge commit | Squash gives clean target history; merge preserves audit trail; user picks in confirmation modal |
| Back merge behavior | Auto-commit clean merges + post-merge undo banner | Standard git behavior for clean merges; undo option (revert commit) gives safety net; conflicts enter merge-in-progress state |
| Task-level file attribution | Show file under every task that touched it | Each task card shows its own diff for the file; preserves full attribution history |

## References

- `docs/run-review-prune-merge/PRD.md` — Full product requirements
- `docs/run-review-prune-merge/UI-MOCKUPS.md` — UI mockup reference
- `src/orchestrator/git/branch_ops.py` — Existing git operations (back_merge, merge_back, get_branch_status)
- `src/orchestrator/git/worktree.py` — Worktree management
- `src/orchestrator/api/routers/runs.py` — Existing run API endpoints
- `src/orchestrator/api/schemas/runs.py` — Existing API schemas (BranchStatusResponse, BackMergeResponse)
- `ui/src/pages/RunDetail.tsx` — Run detail page (add new tab here)
- `ui/src/components/detail/BranchStatusPanel.tsx` — Existing branch status component (extend or wrap)
- `ui/src/api/client.ts` — Frontend API client (add new functions)
- `ui/src/hooks/useApi.ts` — TanStack Query hooks (add new hooks)
- `tests/integration/test_branch_ops.py` — Existing branch operation tests (patterns to follow)
- `AGENTS.md` — Project constraints and testing standards
