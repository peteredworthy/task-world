# Intent: Run Review, Prune & Merge Workbench

## Original Request

Implement the features described in `docs/run-review-prune-merge/` (PRD and UI Mockups). The run review workbench adds a pre-merge review surface to the orchestrator UI, enabling users to inspect, prune, test, and merge run worktree changes with full confidence. Implementation must be iterative, with each iteration producing testable results verified end-to-end via Playwright. Runs should be created and modified to confirm the orchestrator works with the new functionality.

## Goal

Deliver a "Review & Merge" tab on the run detail page that provides a complete pre-merge workbench. Users can review all changes produced by a run, prune unwanted hunks/lines, run tests, request agent assistance for failing tests or merge conflicts, perform back-merges from the target branch, resolve conflicts in-UI, and execute a final gated merge-back — all without leaving the browser.

## Scope

### In Scope

- **Review & Merge tab** on run detail page with left rail (branch status, file lists, conflict files, history, task files) and main diff panel
- **Diff viewing** using `react-diff-view`: inline and side-by-side modes, branch-aggregate/per-commit/per-task scopes, near full-screen diff dialog
- **Prune mode**: file-level, hunk-level, and line-level selection with preview/apply modal, prune auditability via run events
- **Test execution** from the workbench (post-prune, post-conflict-resolution, pre-merge) with result display and log viewer
- **Agent assist**: "Use Agent to Fix Tests" and "Use Agent to Resolve Conflicts" actions that dispatch agent work against the run worktree
- **Back merge**: merge latest target branch into run branch, display conflicts, support manual and agent conflict resolution
- **Conflict resolver**: near full-screen dialog with keep-ours/keep-theirs/manual-selection per conflict block
- **Merge readiness gating**: persistent status bar with gates (clean merge prediction, no unresolved conflicts, required tests pass, no active jobs), final "Commit Merge Back" enabled only when all gates pass
- **Branch history**: commit timeline with per-commit and aggregate diff viewing
- **Task-level file attribution**: show files modified per task, open task-scoped diffs
- **Worktree path display** with copy-to-clipboard
- **Backend API endpoints** for diff generation, merge simulation, prune operations, conflict details/resolution, test execution, and agent actions
- **Playwright E2E tests** for every major workflow: review tab rendering, diff viewing, prune flow, test execution, back merge, conflict resolution, merge gating, and final merge
- **Playwright visual regression tests** to verify UI quality and catch layout/styling issues

### Key Design Decisions

- **Tab availability:** The "Review & Merge" tab is available on any run status as long as the worktree exists — maximum flexibility for reviewing in-progress, completed, or failed runs
- **Agent backend for review actions:** Agent assist modals (fix tests, resolve conflicts) default to the run's configured agent (same agent_type and agent_config), with an "Advanced" toggle allowing the user to override the agent at dispatch time
- **Test command source:** Test execution reuses the routine's `auto_verify` commands from the task/step configuration — no separate "review test command" config needed
- **Merge strategy:** The final "Commit Merge Back" modal lets the user choose between squash merge and merge commit (default: squash)
- **Back merge behavior:** Clean back merges auto-commit immediately; the UI shows a post-merge review banner with an undo option (revert the merge commit). Conflicted back merges enter a merge-in-progress state for resolution
- **Task-level file attribution:** Files appear under every task that touched them — each task card shows that task's own diff for the file (not just the latest task)
- **Prune commit strategy:** Each prune-apply creates a dedicated commit on the run branch for full auditability
- **Line-level prune scope:** Selection-only from existing diff lines (no arbitrary manual line composition in v1)

### Out of Scope

- Full code editing IDE in the browser (only selection-based prune, not free-form editing)
- Commit history rewriting (rebase/squash/amend) from the UI
- Multi-user collaborative editing of the same run branch
- Binary file conflict resolution beyond keep-ours/keep-theirs
- Configurable test profiles (use single default verification profile for v1)

## Definition of Complete

- [ ] Run detail page has a "Review & Merge" tab with branch status summary, file lists, conflict file group, and worktree path with copy action
- [ ] Diff viewer renders unified diffs using `react-diff-view` with inline/side-by-side toggle, supporting branch-aggregate, per-commit, and per-task scopes
- [ ] Near full-screen diff dialog opens from file list clicks with scope selector, search, and navigation
- [ ] Prune mode allows selecting files, hunks, and lines for removal with preview modal and apply confirmation
- [ ] Prune operations are recorded in run events and visible in activity timeline
- [ ] Test execution can be triggered from the workbench; results show pass/fail, summary counts, and collapsible log output
- [ ] "Use Agent to Fix Tests" dispatches agent work against the run worktree and updates diff/test status on completion
- [ ] Back merge action merges target branch into run branch with confirmation modal and impact summary
- [ ] Conflict resolver displays conflict blocks with keep-ours/keep-theirs/manual-selection actions per block
- [ ] "Use Agent to Resolve Conflicts" dispatches agent work scoped to unresolved conflicts
- [ ] Merge readiness bar shows all gate statuses and disables final merge when gates are not met
- [ ] "Commit Merge Back" is only enabled when all readiness gates pass; it merges the run branch back to the target
- [ ] Branch history timeline shows commits with per-commit diff viewing
- [ ] Task cards show files modified per task with task-scoped diff viewing
- [ ] All backend endpoints for diff, prune, merge-sim, conflict resolution, test execution, and agent actions exist and return correct data
- [ ] Playwright E2E tests cover: tab rendering, diff viewing, prune apply, test execution, back merge, conflict resolution, merge gating, and final merge
- [ ] Playwright visual tests confirm no major layout/styling regressions across the review workbench
- [ ] All existing tests continue to pass (`uv run pytest` and `npm run test`)
- [ ] `uv run pre-commit run --all-files` passes cleanly
