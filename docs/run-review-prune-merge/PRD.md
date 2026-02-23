# Run Review, Prune, and Pre-Merge Workbench PRD

**Status:** Draft  
**Audience:** Product, frontend, backend, agent orchestration implementers  
**Primary UI target:** Run detail view (new review/merge workbench)

## 1. Summary

Add a first-class workflow for reviewing and refining a run's worktree before final merge. Users must be able to:

- Inspect all changes produced by a run
- Prune unwanted changes at hunk/block and line level
- Run tests after pruning
- Ask an agent to fix failing tests
- Perform a back-merge from target branch into the run branch
- Inspect and resolve merge conflicts manually (or via agent)
- Run tests again after conflict resolution
- Only execute final merge-back when mergeability is clean and required tests pass

This feature is a "pre-merge workbench" for safe human-in-the-loop integration.

## 2. Problem

Runs generate changes in isolated worktrees, but the current UX does not provide a guided way to:

- Review exactly what changed across the branch and per task
- Remove unwanted generated edits safely
- Validate the result incrementally with tests
- Resolve merge conflicts before final merge
- Understand when a clean merge is possible

This creates risk (bad merges), friction (manual CLI work), and low confidence in agent output.

## 3. Goals

1. Make run output reviewable and editable (prune) in the UI before merge.
2. Support human-controlled merge conflict resolution in the UI.
3. Allow agent assistance for:
   - fixing tests
   - fixing merge conflicts
4. Make merge readiness explicit and trustworthy.
5. Preserve clear traceability: branch history, task-level file changes, test runs, and agent interventions.

## 4. Non-Goals (Initial Release)

1. Full arbitrary code editing IDE in the browser.
2. Rewriting commit history (rebase/squash/edit commit messages) from the UI.
3. Multi-user collaborative editing of the same run branch.
4. Conflict resolution for binary files beyond keep-ours/keep-theirs selection.

## 5. User Stories

1. As a user, I can open a run and see everything changed in its worktree branch.
2. As a user, I can prune generated changes by hunk or line before merging.
3. As a user, I can run tests after pruning and see pass/fail output.
4. As a user, I can ask an agent to fix failing tests without leaving the run review workflow.
5. As a user, I can back-merge the latest target branch into the run branch before final merge.
6. As a user, I can resolve merge conflicts in a near full-screen diff dialog and choose which version to keep.
7. As a user, I can ask an agent to resolve merge conflicts.
8. As a user, I can confirm final merge-back is only available when merge is clean and tests are green.
9. As a user, I can copy the run worktree directory path for local inspection.
10. As a user, I can inspect branch history and view per-commit and aggregate diffs.
11. As a user, I can inspect task-level modified files and the diffs produced by that task.

## 6. Key Concepts

### 6.1 Review Workbench

A new run-detail area focused on pre-merge operations:

- Branch status / readiness
- Changed files and conflicts
- Diff viewer (inline/side-by-side)
- Prune actions
- Test execution and results
- Agent assist actions
- Branch history

### 6.2 Prune Session

A user-driven change selection/edit flow that removes parts of the run branch diff (vs base or current target baseline), with:

- Hunk-level exclude/apply
- Line-level exclude/apply (when parseable text diff)
- File-level revert/remove from run branch

### 6.3 Merge Readiness

Computed status shown in UI with explicit gates:

- `merge_check.clean` (no merge conflicts predicted for final merge-back)
- `conflicts_resolved` (if back-merge introduced conflicts)
- `required_tests.green`
- `working_tree.clean_or_expected` (no unresolved merge markers / staged intermediate failure)

Final "Commit Merge Back" action is enabled only when all required gates pass.

## 7. Functional Requirements

## 7.1 Run Work Visibility

### FR-RW-1: Worktree Path Display + Copy

- Run detail merge/review view SHALL display the absolute worktree directory path.
- UI SHALL include a copy-to-clipboard action.
- Path SHALL be visible without opening developer tools/logs.

### FR-RW-2: Branch Status Summary

- UI SHALL show:
  - run branch name
  - target branch name
  - base commit and head commit (short SHA)
  - ahead/behind counts (if available)
  - merge readiness status
  - predicted merge conflict count (if any)
  - test status summary (latest run)

### FR-RW-3: Modified Files + Conflict Files List

- Branch status area SHALL list modified files in the run branch.
- Conflicted files (if any) SHALL be shown in a distinct group with stronger status styling.
- Clicking any file SHALL open a near full-screen modal/dialog for diff viewing and change management.

## 7.2 Diff Viewing and Interaction

### FR-DV-1: Diff Viewer Library

- The UI SHALL use `react-diff-view` as the primary diff rendering component for text files.

### FR-DV-2: View Modes

- Users SHALL be able to switch between:
  - inline view
  - side-by-side view

### FR-DV-3: Scope Modes

- Diff viewer SHALL support multiple scopes:
  - branch aggregate (overall changes in run branch)
  - per commit
  - per task
  - merge conflict resolution view

### FR-DV-4: Large/Binary File Handling

- For unsupported or binary files, UI SHALL show metadata and fallback actions (open path/copy path/keep ours/theirs where relevant).
- UI SHALL not attempt line-level prune for binary files.

## 7.3 Prune Mode

### FR-PR-1: Enter Prune Mode

- User SHALL be able to enter "Prune Mode" from the review workbench before final merge.
- Prune Mode SHALL make selectable:
  - file-level changes
  - hunk/block-level changes
  - line-level changes (text diffs)

### FR-PR-2: Prune Operations

- Supported actions:
  - remove file change from run branch (revert to base/target state)
  - remove selected hunk/block
  - remove selected line(s) within a hunk
  - restore previously pruned hunks/lines during current prune session before applying

### FR-PR-3: Safety + Preview

- Prune changes SHALL be previewed before apply.
- Destructive apply SHALL use a modal confirmation (per repo UI constraints).
- System SHALL show apply result and any partial failures.

### FR-PR-4: Prune Auditability

- System SHALL record prune operations in run history/events (who/when/what scope).
- UI SHOULD show a prune timeline entry (e.g., "Pruned 3 hunks across 2 files").

## 7.4 Tests After Prune / Conflict Resolution

### FR-TS-1: Test Execution in Workbench

- User SHALL be able to run configured tests from the review workbench:
  - after prune
  - after conflict resolution
  - before final merge

### FR-TS-2: Test Result Presentation

- UI SHALL show:
  - command/profile used
  - start/end time
  - pass/fail status
  - summary counts
  - log output (collapsible)

### FR-TS-3: Agent Fix for Failing Tests

- When tests fail, UI SHALL offer "Use Agent to Fix Tests".
- Agent fix runs against the run worktree branch (not main checkout).
- UI SHALL show agent progress and resulting diff/test status updates.

## 7.5 Back Merge + Conflict Resolution

### FR-MG-1: Back Merge Action

- UI SHALL provide a "Back Merge" action to merge latest target branch into the run branch before final merge.
- Action SHALL show source/target branches clearly to avoid reversal mistakes.
- Action SHALL open a modal with impact summary and confirmation.

### FR-MG-2: Conflict Detection and Display

- If back merge or final merge simulation detects conflicts, UI SHALL:
  - surface conflict count prominently
  - list conflict files
  - allow opening each conflict in conflict resolution modal

### FR-MG-3: Manual Conflict Resolution

- Conflict dialog SHALL support choosing resolution at appropriate granularity:
  - keep current/run branch version (ours)
  - keep target branch version (theirs)
  - mixed/manual selection by block/line for text conflicts
- Resolved status SHALL be visible per file.

### FR-MG-4: Agent Conflict Resolution

- UI SHALL offer "Use Agent to Resolve Conflicts".
- Agent action SHALL be scoped to current unresolved conflicts and run worktree.
- UI SHALL require user review of resulting changes before final merge-back enablement.

## 7.6 Final Merge Gating

### FR-FM-1: Readiness Indicator

- UI SHALL display a persistent merge readiness panel with explicit gates:
  - clean final merge prediction
  - no unresolved conflicts
  - required tests pass
  - no active agent/test job running

### FR-FM-2: Final Merge-Back Enablement

- "Commit Merge Back" action SHALL be disabled unless all required gates pass.
- Disabled state SHALL explain which conditions remain unmet.

### FR-FM-3: Recheck on State Changes

- Merge readiness SHALL be recomputed after:
  - prune apply
  - agent fix completion
  - test completion
  - back merge
  - conflict resolution apply

## 7.7 Branch History + Task History

### FR-HI-1: Branch Commit History

- UI SHALL show run branch commit history timeline.
- User SHALL be able to select a commit and view:
  - commit metadata
  - files changed in that commit
  - commit diff

### FR-HI-2: Branch Aggregate vs Commit Diff

- UI SHALL support switching between:
  - overall branch diff
  - selected commit diff

### FR-HI-3: Task-Level Modified Files

- Task details SHALL show files modified in that task.
- Clicking a file SHALL open diff viewer scoped to that task/attempt changes.

## 8. UX Requirements and Constraints

1. No inline confirm/cancel pairs in compact rows/cards.
2. Destructive operations (apply prune, back merge, final merge) must use full modal confirmations.
3. File actions in compact lists should be behind a `⋯` menu where space is tight.
4. Diff and conflict management should use near full-screen overlays to avoid cramped editing.
5. UI must clearly distinguish:
   - run branch changes
   - target branch incoming changes
   - unresolved conflict state
   - test health

## 9. Proposed Information Architecture (Run Detail)

Add a new top-level tab/section in run detail:

- `Overview`
- `Tasks`
- `Artifacts`
- `Review & Merge` (new)

Within `Review & Merge`:

- Header: branch summary + worktree path + readiness badge + primary actions
- Left pane: branch status (files, conflicts, tests, history, tasks)
- Main pane: diff viewer / history diff / conflict diff
- Footer bar (sticky): readiness gates + final merge CTA

## 10. Component / Technical Notes (Frontend)

### 10.1 `react-diff-view`

Use `react-diff-view` for:

- unified and split diff rendering
- hunk parsing/rendering
- custom gutter cells for line/hunk selection (prune mode)
- conflict block highlighting overlays

Expected custom UI additions around `react-diff-view`:

- line selection checkboxes/toggles for prune mode
- hunk action toolbar (`Prune hunk`, `Keep hunk`, `Restore`)
- conflict resolution action chips (`Keep ours`, `Keep theirs`, `Edit selection`)
- inline/side-by-side view toggle

### 10.2 Backend/API Capabilities Needed (PRD-level)

This PRD assumes new backend endpoints/services for:

- branch diff summaries (aggregate, commit, task-scoped)
- merge simulation / mergeability checks
- prune apply operations (file/hunk/line)
- back merge initiation
- conflict list/details and resolution apply
- test run execution and logs in review context
- agent actions for test fix / conflict fix

Exact route naming is implementation work, not fixed by this PRD.

## 11. Data Model Additions (Conceptual)

Likely new domain records/events:

- `RunReviewStatus`
- `MergeReadinessStatus`
- `PruneOperation`
- `PruneSession`
- `ReviewTestRun`
- `BackMergeAttempt`
- `ConflictResolution`
- `AgentAssistAction` (type: `fix_tests` | `resolve_conflicts`)

## 12. Success Metrics

1. Reduced manual CLI usage for merge preparation.
2. Higher successful first-time merge-back rate.
3. Lower frequency of merging unwanted generated changes.
4. Faster conflict resolution time for runs with back merges.
5. Increased user confidence (qualitative feedback).

## 13. Risks and Mitigations

### Risk: Line-level prune is complex and error-prone

- Mitigation: Start with file + hunk prune; add line-level behind feature flag if needed.
- Mitigation: Always show preview and validate patch apply.

### Risk: Diff UI becomes cluttered

- Mitigation: Near full-screen modal for detail work, strong left-nav grouping, sticky readiness bar.
- Mitigation: Progressive disclosure (summary first, details on click).

### Risk: Agent conflict resolution may produce unsafe changes

- Mitigation: Require user review; do not auto-enable merge without passing gates.
- Mitigation: Show explicit diff of agent-produced resolutions.

### Risk: Mergeability check drift vs real merge

- Mitigation: Recompute merge readiness immediately before final merge action.

## 14. Milestones (Suggested)

1. Diff visibility foundation (aggregate/per-task/per-commit) + worktree path copy
2. Prune mode (file/hunk) + tests + readiness panel
3. Back merge + conflict display + manual resolution
4. Agent assist (fix tests / resolve conflicts)
5. Final merge gating polish + UX iteration + telemetry

## 15. Open Questions

1. Which test profiles are "required" for merge gating (single default vs configurable set)?
2. Should prune actions create explicit commits on the run branch automatically, or remain uncommitted until user action?
3. For line-level prune, do we support arbitrary manual line composition or selection-only from existing diff lines in v1?
4. Should back merge create a dedicated merge commit immediately, or stage conflict resolution before commit creation?
5. How should task-to-file attribution behave when multiple tasks modify the same file/lines?
