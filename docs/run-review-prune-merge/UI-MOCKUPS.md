# Run Review & Merge Workbench UI Mockups

**Companion to:** `docs/run-review-prune-merge/PRD.md`  
**UI target:** Run detail page  
**Diff renderer:** `react-diff-view`

## 1. UX Direction (Keep It Powerful, Not Messy)

This feature adds a lot of capability. The UI should feel like a structured workbench, not a pile of controls.

Principles:

- One primary workspace (`Review & Merge`) with progressive disclosure
- Summary-first, details-on-click
- Heavy actions (prune apply, back merge, final merge) always via modals
- Diff work in near full-screen overlays
- Persistent merge readiness bar so users always know what remains

## 2. High-Level Layout (Run Detail -> Review & Merge Tab)

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Run #6daf...  Routine: idea_to_plan                    [Review & Merge]     │
├──────────────────────────────────────────────────────────────────────────────┤
│ Branch: orchestrator/run-1234   Target: main           Readiness: NOT READY │
│ Base: a1b2c3d  Head: e4f5g6h    Predicted merge: 3 conflicts                │
│ Worktree: /Users/peter/code/task-world/worktrees/run-1234   [Copy Path]     │
│                                                                              │
│ [Prune Mode] [Run Tests] [Back Merge main -> run branch] [Use Agent ▾]      │
├──────────────────────────────────────────────────────────────────────────────┤
│ Left Rail (320px)                 │ Main Panel                               │
│                                   │                                          │
│ Branch Status                     │ Branch Aggregate Diff                    │
│ - Modified Files (18)             │ [Inline | Side-by-side] [Whitespace ▾]   │
│ - Merge Conflicts (3)             │ [Overall Branch ▾] [Filter files ▾]      │
│ - Tests (last: failed)            │                                          │
│ - History (12 commits)            │   react-diff-view rendering area         │
│                                   │   with sticky per-file headers           │
│ Files                             │                                          │
│ > src/api/routes.py               │                                          │
│ > src/service/merge.py            │                                          │
│ > tests/test_merge_flow.py        │                                          │
│ ...                               │                                          │
│                                   │                                          │
│ Conflicts                         │                                          │
│ ! src/service/merge.py            │                                          │
│ ! src/ui/review_panel.tsx         │                                          │
│ ! tests/test_merge_flow.py        │                                          │
│                                   │                                          │
│ History                           │                                          │
│ • HEAD  e4f5g6h "prune changes"   │                                          │
│ • d4e5f6a "agent test fix"        │                                          │
│ • c3d4e5f "task 8 output"         │                                          │
└──────────────────────────────────────────────────────────────────────────────┘
│ Readiness Gates: ✗ Merge Clean  ✓ Conflicts Resolved  ✗ Tests Green         │
│ Final Merge Back disabled: Resolve merge conflicts and run tests             │
│                                              [Commit Merge Back (disabled)]  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 3. Left Rail Sections (Collapsible)

Keep left rail grouped, collapsible, and scannable.

### 3.1 Branch Status Section

```text
Branch Status
  Run branch      orchestrator/run-1234
  Target branch   main
  Ahead/behind    +9 / -2
  Mergeability    Conflicts predicted (3)
  Tests           Failed (2/184)
  Last check      2026-02-23 14:22
```

### 3.2 File Lists

- `Modified Files` list shows path + change summary (+/- count)
- `Merge Conflicts` list shows unresolved/resolved status chips
- Clicking opens near full-screen diff dialog
- `⋯` menu per row for actions (`Open Diff`, `Open Conflict Resolver`, `Prune File`, `Copy Path`)

### 3.3 History

- Commit timeline with SHA, message, timestamp, badges (`prune`, `agent`, `back-merge`)
- Toggle:
  - `Branch total`
  - `Selected commit`

### 3.4 Task Files

In `Tasks` tab and mirrored mini-panel in `Review & Merge`:

- Task cards show "Files touched (N)"
- Click file -> open diff scoped to task attempt

## 4. Near Full-Screen Diff Dialog (General Viewer)

Used for:

- Modified file inspection
- Task file diff
- Commit diff
- Branch aggregate file view

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ src/service/merge.py                                          [X Close]     │
│ Scope: Branch Aggregate ▾   Mode: [Inline | Side-by-side]   [Copy Path]     │
│ Status: Modified   Task(s): T-03, T-07   Conflict: No                        │
├──────────────────────────────────────────────────────────────────────────────┤
│ Toolbar: [Search in diff] [Prev Change] [Next Change] [Prune Mode Off ▾]    │
│          [Open in Conflict Resolver] (if conflicted)                         │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  react-diff-view component (scrollable)                                      │
│  - file header                                                               │
│  - hunks                                                                     │
│  - syntax-highlighted lines                                                  │
│  - custom gutter actions when prune mode enabled                             │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│ Footer: +84 / -21 lines                    [Prune Selected…] [Close]         │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 5. Prune Mode UX (Hunk and Line Level)

Prune mode should feel like review selection, not free-form editing.

### 5.1 Prune Mode Entry

- User clicks `Prune Mode`
- UI enters selection state:
  - left rail shows `Prune Basket`
  - diff gutters expose selection toggles
  - top banner indicates "Selection mode active"

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Prune Mode Active: Select hunks or lines to remove from the run branch       │
│ Selected: 3 hunks, 7 lines across 2 files     [Preview Prune] [Exit]         │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 `react-diff-view` Custom Gutter Actions (Mock)

```text
HUNK HEADER  @@ -120,8 +120,14 @@                         [Select Hunk] [Keep]

  [ ]  121   unchanged line
  [x]  122 + generated line to prune
  [x]  123 + generated line to prune
  [ ]  124 + useful line to keep
  [ ]  125   unchanged line
```

Behavior:

- Hunk checkbox selects all added/removed lines in hunk
- Line checkbox overrides hunk default
- Selection model is explicit and previewable before apply

### 5.3 Prune Preview Modal (Required before apply)

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Apply Prune Changes?                                                         │
├──────────────────────────────────────────────────────────────────────────────┤
│ You are about to remove:                                                     │
│ - 2 files from the run diff                                                  │
│ - 3 hunks                                                                    │
│ - 7 individual lines                                                         │
│                                                                              │
│ Resulting diff preview (collapsed summary + expandable files)                │
│                                                                              │
│ [Cancel]                                   [Apply Prune Changes]             │
└──────────────────────────────────────────────────────────────────────────────┘
```

Post-apply:

- toast + history entry
- merge readiness re-check
- optional prompt: `Run tests now?`

## 6. Test Runs and Agent Fix Flow (Workbench)

### 6.1 Test Panel (Left Rail or Drawer)

```text
Tests
  Profile: Default verification ▾
  Last run: Failed (2)
  Command: uv run pytest tests/unit -v
  Duration: 00:43
  Started: 14:28:10
  [Run Tests] [View Logs] [Use Agent to Fix Tests]
```

### 6.2 Test Logs Drawer

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Test Run #17 - Failed                                      [Copy Logs] [X]   │
├──────────────────────────────────────────────────────────────────────────────┤
│ Summary: 182 passed, 2 failed, 3 skipped                                     │
│ Failing files:                                                                │
│ - tests/test_merge_flow.py::test_back_merge_status_updates                    │
│ - tests/test_review_prune.py::test_line_prune_preview                         │
├──────────────────────────────────────────────────────────────────────────────┤
│ terminal output...                                                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Agent Fix Tests Modal

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Use Agent to Fix Failing Tests                                                │
├──────────────────────────────────────────────────────────────────────────────┤
│ Scope: Run worktree branch only                                               │
│ Failing tests in latest run: 2                                                │
│ Agent will be asked to fix test failures without changing merge target branch │
│                                                                              │
│ Prompt preview (collapsible)                                                  │
│ [Cancel]                                        [Start Agent Fix]            │
└──────────────────────────────────────────────────────────────────────────────┘
```

While running:

- action row shows live status
- diff updates after completion
- readiness gates re-evaluate

## 7. Back Merge Flow (Target -> Run Branch)

### 7.1 Back Merge Confirmation Modal

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Back Merge Latest Target Branch                                               │
├──────────────────────────────────────────────────────────────────────────────┤
│ Merge source: main (latest)                                                   │
│ Into branch: orchestrator/run-1234                                            │
│                                                                              │
│ This updates the run branch before final merge-back and may create conflicts. │
│                                                                              │
│ Precheck: 3 conflicts predicted                                               │
│ [Cancel]                                             [Start Back Merge]      │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 After Back Merge Result States

State A: clean

```text
Back Merge: Completed (clean)
New merge commit: ab12cd3
Next steps: Run tests, verify readiness
```

State B: conflicts

```text
Back Merge: Conflicts detected (3 files)
[Open Conflict Resolver] [Use Agent to Resolve Conflicts]
```

## 8. Conflict Resolver (Near Full-Screen)

This is the most important UX surface. Keep it focused.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Resolve Conflict: src/service/merge.py                         1 of 3 [X]    │
│ Mode: [Inline | Side-by-side]  View: [Conflict blocks only ▾]               │
│ File status: Unresolved                                                       │
├──────────────────────────────────────────────────────────────────────────────┤
│ Conflict Blocks                                                               │
│ [1] @@ conflict block                                                       ▼ │
│     Actions: [Keep Run (ours)] [Keep Target (theirs)] [Manual Selection]     │
│                                                                              │
│     react-diff-view rendering with conflict highlighting                      │
│     - ours section tinted warm                                                │
│     - theirs section tinted cool                                              │
│     - selected result preview below block                                     │
│                                                                              │
│ [2] @@ conflict block                                                       ▶ │
│ [3] @@ conflict block                                                       ▶ │
├──────────────────────────────────────────────────────────────────────────────┤
│ Resolved blocks: 1/3      File resolution: Partial                           │
│ [Prev File] [Next File]          [Mark File Resolved…] [Close]               │
└──────────────────────────────────────────────────────────────────────────────┘
```

Notes:

- `Mark File Resolved` opens confirmation modal if unresolved blocks remain
- Block-level quick actions must be single-click but reversible before save/apply
- Manual selection mode uses the same selection mechanics as prune mode where possible

## 9. Agent Conflict Resolution Flow

### 9.1 Modal

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Use Agent to Resolve Merge Conflicts                                          │
├──────────────────────────────────────────────────────────────────────────────┤
│ Unresolved files: 3                                                           │
│ Agent will work in run worktree branch only.                                  │
│ You will review the resulting diff before final merge is enabled.             │
│                                                                              │
│ [Cancel]                                  [Start Agent Conflict Fix]         │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 9.2 Post-Agent Review Banner

```text
Agent conflict resolution completed.
Changed files: 4   Remaining conflicts: 0
[Review Changes] [Run Tests]
```

## 10. Branch History + Commit/Task Diffs

### 10.1 Branch History Panel

```text
History
  ( ) Overall branch changes
  (•) Selected commit

  • e4f5g6h  prune: remove generated logging spam        2m ago
  • d4e5f6a  agent: fix failing tests after prune        6m ago
  • c3d4e5f  back-merge main into run branch             11m ago
  • b2c3d4e  task T-08 attempt 2 output                  18m ago
```

Selecting a commit updates main pane diff scope and file list.

### 10.2 Task Card File List (Tasks Tab)

```text
Task T-08: Implement merge readiness panel
Status: completed
Files touched (4)
  - src/ui/review_merge_panel.tsx     [View Diff]
  - src/api/review_routes.py          [View Diff]
  - tests/test_review_panel.py        [View Diff]
  - docs/ARCHITECTURE.md              [View Diff]
```

`View Diff` opens the same near full-screen diff dialog with task scope.

## 11. Final Merge Readiness Bar (Sticky)

Keep this visible at all times in `Review & Merge`.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Merge Readiness                                                               │
│ ✓ No unresolved conflicts   ✓ Final merge predicts clean   ✗ Required tests   │
│ Last checked: 14:31:07      Tests: Failed 2/184                             │
│ [Run Tests] [Use Agent to Fix Tests]                 [Commit Merge Back]     │
│                                        (disabled until required tests pass)  │
└──────────────────────────────────────────────────────────────────────────────┘
```

When fully ready:

```text
✓ No unresolved conflicts   ✓ Final merge predicts clean   ✓ Required tests pass
[Commit Merge Back]
```

## 12. Visual/Interaction Details (Implementation Notes)

### 12.1 `react-diff-view` Usage Pattern

- Parse backend-provided unified diff into files/hunks
- Render with custom:
  - file header
  - gutter cells (selection toggles)
  - hunk header toolbars
  - conflict block overlays
- Toggle `viewType` between unified/split for inline/side-by-side

### 12.2 Keyboard / Efficiency Features (Recommended)

- `j` / `k`: next/previous change (optional)
- `[` / `]`: previous/next conflict file
- `Shift+P`: enter prune mode
- `t`: run tests

### 12.3 Empty / Edge States

- No changes in run branch: show "Nothing to review"
- No conflicts: hide conflict section, show "Back merge clean"
- Binary file conflict: only `Keep ours` / `Keep theirs`
- Large diff: lazy render file sections; collapse by default

## 13. Suggested Iteration Order (UX-first)

1. `Review & Merge` tab skeleton + worktree path + branch status + file lists
2. Generic diff dialog with `react-diff-view` + inline/split toggle
3. Prune mode (file/hunk first), preview/apply modal
4. Tests panel + logs + agent-fix-tests action
5. Back merge + conflict list + conflict resolver UI
6. Agent conflict resolution + readiness gating polish
7. Branch history and task-scoped file diff UX improvements
