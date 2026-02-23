# Architecture: Run Review, Prune & Merge Workbench

## Current State

The orchestrator already supports:

- **Worktree management** (`src/orchestrator/git/worktree.py`): creating/removing git worktrees for run isolation
- **Branch operations** (`src/orchestrator/git/branch_ops.py`): `get_branch_status()` (ahead/behind, mergeability), `back_merge()` (target into run branch), `merge_back()` (run branch into target)
- **Run detail UI** (`ui/src/pages/RunDetail.tsx`): step progress, activity feed, metrics, approval modals
- **Branch status panel** (`ui/src/components/detail/BranchStatusPanel.tsx`): basic ahead/behind display, pull upstream button
- **API client + hooks** (`ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`): `backMerge()`, `mergeBack()`, `getBranchStatus()` with TanStack Query
- **Agent executor** (`src/orchestrator/agents/executor.py`): lifecycle management for dispatching agent work against worktrees
- **Event system** (`src/orchestrator/workflow/events.py`, `event_logger.py`): event sourcing for run state transitions
- **WebSocket** (`src/orchestrator/api/websocket.py`): real-time run update push to frontend

The feature builds on this foundation — it does not replace any existing component but extends the git layer, adds new API endpoints, and introduces a major new frontend surface.

### Resolved Design Decisions

These decisions were confirmed through human Q&A (see `docs/git-ops/clarifications.md`):

1. **Tab availability:** The "Review & Merge" tab is visible for any run status as long as the worktree exists (in-progress, completed, failed, cancelled).
2. **Agent backend for review actions:** Agent assist modals default to the run's configured agent (`agent_type` + `agent_config`). An "Advanced" toggle reveals an agent picker for override.
3. **Test command source:** Test execution reuses the routine's `auto_verify` commands from the task/step configuration.
4. **Merge strategy:** The final merge-back confirmation modal lets the user choose between squash merge (default) and merge commit.
5. **Back merge behavior:** Clean back merges auto-commit immediately with a post-merge review banner offering an undo option (revert merge commit). Conflicted back merges enter a merge-in-progress state for manual or agent resolution.
6. **Task-level file attribution:** Files appear under every task that touched them; each task card shows that task's own diff for the file.
7. **Prune commit strategy:** Each prune-apply creates a dedicated commit on the run branch for auditability.
8. **Line-level prune scope:** Selection-only from existing diff lines (no free-form editing in v1).

## Proposed Changes

### New Components

#### Backend: `src/orchestrator/git/diff_ops.py`

Diff generation module providing:
- `get_branch_diff(worktree_path, base_ref, head_ref)` — unified diff for the full branch
- `get_commit_diff(worktree_path, commit_sha)` — diff for a single commit
- `get_task_diff(worktree_path, start_commit, end_commit)` — diff scoped to a task's commit range
- `get_modified_files(worktree_path, base_ref, head_ref)` — list of changed files with stats (+/- lines, status)
- `get_commit_log(worktree_path, base_ref)` — commit history from base to HEAD

Uses `asyncio.create_subprocess_exec` to call `git diff` and `git log` — consistent with the existing `_run_git()` pattern in `branch_ops.py`.

#### Backend: `src/orchestrator/git/prune_ops.py`

Prune operations module:
- `preview_prune(worktree_path, selections)` — computes resulting diff after pruning selected hunks/lines (dry-run)
- `apply_prune(worktree_path, selections)` — applies reverse patches to the worktree, commits the result
- `revert_file(worktree_path, file_path, base_ref)` — restores a single file to its base-branch state

Prune works by constructing a reverse patch from the user's selection and applying it via `git apply --reverse`. File-level revert uses `git checkout <base_ref> -- <file>`.

#### Backend: `src/orchestrator/git/conflict_ops.py`

Conflict detection and resolution module:
- `get_conflict_files(worktree_path)` — lists files with unresolved merge conflicts
- `get_conflict_blocks(worktree_path, file_path)` — parses conflict markers into structured blocks (ours/theirs/base content)
- `resolve_conflict(worktree_path, file_path, resolutions)` — applies per-block resolution choices, stages the file
- `mark_all_resolved(worktree_path)` — verifies no remaining conflict markers, stages remaining files

#### Backend: `src/orchestrator/review/` (new package)

Review-specific service layer:
- `service.py` — `ReviewService` orchestrating diff retrieval, prune, test execution, conflict resolution, merge readiness computation
- `models.py` — Pydantic domain models: `DiffResult`, `ModifiedFile`, `CommitInfo`, `PruneSelection`, `PruneResult`, `ConflictFile`, `ConflictBlock`, `MergeReadiness`, `TestRunResult`
- `test_runner.py` — Executes the routine's `auto_verify` commands in worktree subprocess, captures output, computes summary

#### Backend: `src/orchestrator/api/routers/review.py`

New API router mounted at `/api/runs/{run_id}/review/`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/diff` | Branch diff (query: scope=aggregate\|commit\|task, ref=...) |
| GET | `/diff/files` | Modified file list with change stats |
| GET | `/commits` | Commit history for run branch |
| GET | `/conflicts` | List conflict files with block details |
| POST | `/conflicts/{file_path}/resolve` | Apply resolution for a file |
| POST | `/conflicts/agent-resolve` | Dispatch agent to resolve conflicts (defaults to run's agent; optional agent override) |
| POST | `/prune/preview` | Preview prune result |
| POST | `/prune/apply` | Apply prune selections (auto-commits on the run branch) |
| POST | `/revert-file` | Revert file to base state |
| POST | `/test` | Execute routine's `auto_verify` commands in worktree |
| GET | `/test/{test_run_id}` | Get test run results |
| POST | `/agent-fix-tests` | Dispatch agent to fix tests (defaults to run's agent; optional agent override) |
| POST | `/revert-back-merge` | Revert the last back merge commit (undo action) |
| GET | `/merge-readiness` | Compute merge readiness gates |

#### Backend: `src/orchestrator/api/schemas/review.py`

Pydantic request/response schemas for all review endpoints.

#### Frontend: `ui/src/components/review/` (new directory)

| Component | Purpose |
|-----------|---------|
| `ReviewMergeTab.tsx` | Top-level tab container with left rail + main panel layout |
| `BranchStatusSection.tsx` | Branch summary in left rail (extends existing BranchStatusPanel data) |
| `FileListSection.tsx` | Modified files list with `⋯` context menus |
| `ConflictFileList.tsx` | Conflict files group with status chips |
| `HistoryPanel.tsx` | Commit timeline with selection |
| `TaskFilesPanel.tsx` | Task-level file attribution mini-panel |
| `DiffDialog.tsx` | Near full-screen diff overlay using `react-diff-view` |
| `DiffViewer.tsx` | Core `react-diff-view` wrapper with custom gutter, scope handling |
| `PruneModeProvider.tsx` | Context provider for prune selection state |
| `PruneGutter.tsx` | Custom gutter cells for hunk/line selection |
| `PruneToolbar.tsx` | Prune mode banner with selection summary |
| `PrunePreviewModal.tsx` | Preview modal before prune apply |
| `TestPanel.tsx` | Test execution panel in left rail |
| `TestLogsDrawer.tsx` | Collapsible test output viewer |
| `AgentFixTestsModal.tsx` | Agent test fix dispatch modal (defaults to run's agent; Advanced toggle for agent override) |
| `ConflictResolverDialog.tsx` | Near full-screen conflict resolution overlay |
| `ConflictBlock.tsx` | Individual conflict block with ours/theirs actions |
| `AgentResolveConflictsModal.tsx` | Agent conflict resolution dispatch modal (defaults to run's agent; Advanced toggle for agent override) |
| `MergeReadinessBar.tsx` | Sticky bottom bar with gate indicators + merge CTA (merge strategy choice in confirmation modal: squash default, merge commit option) |
| `BackMergeModal.tsx` | Back merge confirmation modal |
| `BackMergeBanner.tsx` | Post-back-merge review banner with undo option (revert merge commit) |

#### Frontend: `ui/src/api/reviewClient.ts`

API client functions for all `/review/` endpoints. Keeps the review API surface separate from the main `client.ts` for maintainability.

#### Frontend: `ui/src/hooks/useReview.ts`

TanStack Query hooks for review operations:
- Queries: `useDiffFiles()`, `useDiff()`, `useCommits()`, `useConflicts()`, `useMergeReadiness()`, `useTestResult()`
- Mutations: `usePrunePreview()`, `usePruneApply()`, `useRevertFile()`, `useRunTests()`, `useResolveConflict()`, `useAgentFixTests()`, `useAgentResolveConflicts()`, `useRevertBackMerge()`
- Invalidation: mutations invalidate related queries (e.g., prune-apply invalidates diff files, merge readiness)

#### E2E Tests: `tests/e2e/test_review_workbench.py` (Playwright, Python)

Playwright test suite covering major workflows. Tests use the orchestrator API to create runs with known worktree state, then interact with the Review & Merge UI.

#### E2E Tests: `ui/tests/review/` (Playwright, TypeScript, if using frontend Playwright config)

Alternative or additional Playwright tests run from the frontend project for visual regression and UI interaction testing.

### Modified Components

| Component | Change |
|-----------|--------|
| `ui/src/pages/RunDetail.tsx` | Add "Review & Merge" tab to the tab bar (visible when worktree exists, regardless of run status); render `ReviewMergeTab` when selected |
| `ui/src/api/client.ts` | Add imports/re-exports from `reviewClient.ts` if needed for consistency |
| `ui/src/hooks/useApi.ts` | Re-export review hooks or keep them separate in `useReview.ts` |
| `ui/src/types/` | Add `review.ts` with TypeScript types matching backend schemas |
| `src/orchestrator/api/app.py` | Mount the new `review` router |
| `src/orchestrator/api/deps.py` | Add `ReviewService` dependency injection |
| `src/orchestrator/workflow/events.py` | Add event types: `PRUNE_APPLIED`, `TEST_RUN_STARTED`, `TEST_RUN_COMPLETED`, `AGENT_FIX_STARTED`, `AGENT_FIX_COMPLETED`, `CONFLICT_RESOLVED`, `BACK_MERGE_COMPLETED`, `BACK_MERGE_REVERTED` |
| `src/orchestrator/git/branch_ops.py` | Enhance `back_merge()` to auto-commit clean merges and return conflict file list on conflict; add conflict count to `get_branch_status()`; enhance `merge_back()` to accept merge strategy parameter (squash or merge commit) |
| `docs/ARCHITECTURE.md` | Update directory map, API routes table, and component descriptions |

### Interactions

```
User (browser)
  │
  ├─► ReviewMergeTab
  │     ├─► useDiffFiles() ──► GET /api/runs/{id}/review/diff/files ──► diff_ops.get_modified_files()
  │     ├─► useDiff() ──► GET /api/runs/{id}/review/diff ──► diff_ops.get_branch_diff/commit_diff/task_diff()
  │     ├─► useCommits() ──► GET /api/runs/{id}/review/commits ──► diff_ops.get_commit_log()
  │     ├─► useBranchStatus() ──► GET /api/runs/{id}/branch-status ──► branch_ops.get_branch_status()
  │     ├─► useMergeReadiness() ──► GET /api/runs/{id}/review/merge-readiness ──► ReviewService.compute_readiness()
  │     │
  │     ├─► Prune Mode
  │     │     ├─► usePrunePreview() ──► POST /review/prune/preview ──► prune_ops.preview_prune()
  │     │     └─► usePruneApply() ──► POST /review/prune/apply ──► prune_ops.apply_prune() ──► EventLogger
  │     │
  │     ├─► Test Panel
  │     │     ├─► useRunTests() ──► POST /review/test ──► test_runner.execute() (subprocess in worktree)
  │     │     └─► useAgentFixTests() ──► POST /review/agent-fix-tests ──► AgentExecutor (worktree)
  │     │
  │     ├─► Back Merge
  │     │     └─► useBackMerge() ──► POST /api/runs/{id}/back-merge ──► branch_ops.back_merge()
  │     │
  │     ├─► Conflict Resolver
  │     │     ├─► useConflicts() ──► GET /review/conflicts ──► conflict_ops.get_conflict_files()
  │     │     ├─► useResolveConflict() ──► POST /review/conflicts/{path}/resolve ──► conflict_ops.resolve_conflict()
  │     │     └─► useAgentResolveConflicts() ──► POST /review/conflicts/agent-resolve ──► AgentExecutor
  │     │
  │     └─► Final Merge
  │           └─► useMergeBack() ──► POST /api/runs/{id}/merge-back ──► branch_ops.merge_back()
  │
  └─► WebSocket /ws/runs/{id} ──► real-time event updates (prune, test, agent, merge events)
```

## Technology Choices

| Area | Choice | Rationale |
|------|--------|-----------|
| Diff rendering | `react-diff-view` (npm) | PRD-specified; supports unified/split, custom gutters, hunk rendering |
| Diff parsing (frontend) | `unidiff` or `gitdiff-parser` (npm) | Parse unified diff text into structured data for `react-diff-view` |
| Diff generation (backend) | `git diff` via subprocess | Consistent with existing `_run_git()` pattern; no new Python dependency needed |
| Conflict parsing (backend) | Custom parser for `<<<<<<<`/`=======`/`>>>>>>>` markers | Standard git conflict markers; small focused parser, no external dependency |
| Test execution | `asyncio.create_subprocess_exec` with routine's `auto_verify` commands | Same pattern as agent execution; reuses existing config; captures stdout/stderr streams |
| E2E testing | Playwright (Python + optional TypeScript) | Specified in requirements; supports visual regression, cross-browser |
| Prune mechanism | `git apply --reverse` | Safe, uses git's own patch machinery; file-level via `git checkout` |
| State invalidation | TanStack Query cache invalidation | Existing pattern in codebase; mutations invalidate related queries |
| Real-time updates | Existing WebSocket `/ws/runs/{id}` | Already established; add new event types for review operations |

## Testing Strategy

### Unit Tests

**Location:** `tests/unit/`

- **`test_diff_ops.py`** — Test diff generation functions with pre-constructed git repos (using `tmp_path` fixture). Verify correct unified diff output, file list generation, commit log parsing.
- **`test_prune_ops.py`** — Test prune preview and apply functions. Verify file-level revert, hunk-level removal, line-level removal against known diff states.
- **`test_conflict_ops.py`** — Test conflict block parsing and resolution. Verify correct identification of conflict markers, ours/theirs extraction, resolution application.
- **`test_review_models.py`** — Test Pydantic model validation for review domain models (MergeReadiness gates, PruneSelection, etc.).
- **`test_merge_readiness.py`** — Test merge readiness computation logic as a pure function given various input states.

**Patterns:**
- Real git repos via `tmp_path` fixture (no mocking per AGENTS.md)
- Helper functions to create repos with known diff states, merge conflicts
- Fast (<1s per test), no external dependencies

### Integration Tests

**Location:** `tests/integration/`

- **`test_review_api.py`** — Test all `/api/runs/{id}/review/` endpoints against a running FastAPI app with real SQLite database and real git repos.
  - Create run with worktree, make known changes, verify diff endpoints return correct data
  - Apply prune operations, verify worktree state changes
  - Create merge conflicts, verify conflict endpoints
  - Execute resolution, verify conflict markers removed
- **`test_review_test_runner.py`** — Test the test execution endpoint against a real worktree with a simple test file.
- **`test_review_merge_readiness.py`** — Test merge readiness endpoint across various states (clean, conflicted, tests failing).

**Patterns:**
- `AsyncClient` with real FastAPI app
- Real git repos with `tmp_path`
- Real SQLite via `:memory:`
- Existing branch ops test patterns from `tests/integration/test_branch_ops.py`

### E2E Tests (Playwright)

**Location:** `tests/e2e/review/` (Python Playwright) and/or `ui/tests/review/` (TypeScript Playwright)

**Setup:**
- Start backend (`uv run orchestrator serve`) and frontend (`npm run dev`) before test suite
- Create runs via API with known worktree states
- Make commits to worktrees to produce diff content

**Test scenarios:**

| Test | What it verifies |
|------|------------------|
| `test_review_tab_renders` | Tab appears on run detail, branch status displays correctly |
| `test_file_list_shows_changes` | Modified files list populates from API data |
| `test_diff_dialog_opens` | Clicking file opens diff dialog with correct content |
| `test_diff_view_modes` | Inline/side-by-side toggle works |
| `test_diff_scope_switch` | Aggregate/commit/task scope switching renders correct diff |
| `test_worktree_path_copy` | Copy-to-clipboard action works |
| `test_prune_mode_enter_exit` | Prune mode toggle, banner, gutter controls appear/disappear |
| `test_prune_select_and_preview` | Select hunks, open preview modal, verify summary |
| `test_prune_apply` | Apply prune, verify diff updates, activity entry appears |
| `test_run_tests` | Execute tests, verify results display, log viewer |
| `test_back_merge_clean` | Back merge with no conflicts, verify clean result |
| `test_back_merge_conflicts` | Back merge with conflicts, verify conflict file list |
| `test_conflict_resolver` | Open conflict dialog, choose ours/theirs, mark resolved |
| `test_merge_readiness_gating` | Verify merge button disabled when gates unmet, enabled when all pass |
| `test_final_merge` | All gates green, click merge, verify success |
| `test_agent_fix_tests` | Dispatch agent fix, verify post-agent state |
| `test_branch_history` | Commit timeline renders, selecting commit updates diff |
| `test_task_file_attribution` | Task cards show files, clicking opens task-scoped diff |

**Visual regression tests:**

| Test | Snapshot target |
|------|-----------------|
| `visual_review_tab_clean` | Review tab with no conflicts, tests passing |
| `visual_review_tab_conflicts` | Review tab with conflict indicators |
| `visual_diff_dialog_inline` | Diff dialog in inline mode |
| `visual_diff_dialog_split` | Diff dialog in side-by-side mode |
| `visual_prune_mode_active` | Prune mode with selections |
| `visual_conflict_resolver` | Conflict resolver with ours/theirs blocks |
| `visual_merge_readiness_ready` | Readiness bar with all gates green |
| `visual_merge_readiness_blocked` | Readiness bar with gates unmet |

**Agent guidance for E2E tests:**
- Use `/iterate` to write each test, run it against a real system, fix failures, and confirm it passes before writing the next
- Create and modify actual runs to verify the orchestrator works with the new functionality (not just static UI rendering)
- Use Playwright's `expect(page).toHaveScreenshot()` for visual regression with appropriate tolerance thresholds

## Security Considerations

- **Prune operations** only modify the run worktree branch, never the target branch or main checkout. The backend must validate that the worktree path belongs to the specified run.
- **Agent dispatch** for test fixing or conflict resolution reuses the existing agent executor with the same sandboxing and authorization as regular builder/verifier phases.
- **File path traversal**: the conflict resolution and revert-file endpoints must validate that requested file paths are within the worktree directory (no `../../` escapes).
- **Test command execution** runs only the routine's `auto_verify` commands from the task/step configuration (not user-supplied arbitrary commands) in the worktree directory.
- **Merge-back** requires all readiness gates to pass server-side before execution — the frontend gating is UX only, the backend enforces the invariant.

## Performance Considerations

- **Large diffs**: Backend returns unified diff text; frontend parses and renders with `react-diff-view`. For very large diffs (>10K lines), implement lazy rendering with collapsed file sections (Milestone 7).
- **Diff caching**: Branch aggregate diff can be cached server-side until the worktree HEAD changes. Per-commit diffs are immutable and safe to cache indefinitely.
- **File list pagination**: For runs with many modified files (>100), the file list endpoint should support pagination or virtual scrolling on the frontend.
- **Test execution**: Runs asynchronously; the frontend polls for completion rather than holding a connection open. Consider WebSocket push for real-time log streaming if needed.
- **Conflict parsing**: Performed on-demand per file, not precomputed for all files. Conflict blocks are typically small.
- **Merge readiness**: Lightweight check (git status + test result lookup + conflict file count). Cached briefly (5s) to avoid redundant computation during rapid polling.
