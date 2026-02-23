# Dry-Run Simulation Notes: Review & Merge Workbench

This document captures the results of simulating execution across all 12 step task files. Each step was traced through its tasks, verifying assumptions against the actual codebase, identifying expected outputs, and flagging blockers with concrete remediation.

---

## Methodology

- Read all 12 step task files (`docs/git-ops/steps/step-01.md` through `step-12.md`)
- Read all 12 step plans (`docs/git-ops/step-01-plan.md` through `step-12-plan.md`)
- Read intent, plan, architecture, and clarifications documents
- Inspected the actual source files referenced by each step:
  - `src/orchestrator/git/branch_ops.py` — existing git operations
  - `src/orchestrator/git/worktree.py` — worktree management
  - `src/orchestrator/api/routers/runs.py` — run API router
  - `src/orchestrator/api/schemas/runs.py` — existing schemas
  - `src/orchestrator/api/app.py` — router mounting
  - `src/orchestrator/workflow/events.py` — event system
  - `src/orchestrator/agents/executor.py` — agent executor
  - `ui/src/pages/RunDetail.tsx` — run detail page
  - `ui/src/api/client.ts` — frontend API client
  - `ui/src/hooks/useApi.ts` — TanStack Query hooks
  - `ui/src/components/detail/BranchStatusPanel.tsx` — existing branch status
  - `tests/integration/test_branch_ops.py` — test patterns
- Verified which files exist and which must be created

---

## Step-by-Step Simulation

### Step 1: Backend Diff Endpoints + Branch Status Enhancements

**Assumptions Verified:**
- `_run_git()` exists in `branch_ops.py` — **Confirmed**, but it uses `subprocess.run()` (synchronous), not `asyncio.create_subprocess_exec` as the task description implies.
- `get_branch_status()` returns `BranchStatus` dataclass — **Confirmed**. Fields: `behind_count`, `ahead_count`, `can_merge_cleanly`, `has_conflicts`.
- `BranchStatusResponse` exists in schemas/runs.py — **Confirmed**. Fields: `behind_count`, `ahead_count`, `can_merge_cleanly`, `has_conflicts`, `source_branch`, `run_branch`.
- Router mounting follows `app.include_router()` — **Confirmed**.
- `src/orchestrator/review/` does not exist — **Confirmed**, must be created.
- `src/orchestrator/git/diff_ops.py` does not exist — **Confirmed**, must be created.

**Expected Outputs:**
- New files: `src/orchestrator/review/__init__.py`, `src/orchestrator/review/models.py`, `src/orchestrator/git/diff_ops.py`, `src/orchestrator/api/schemas/review.py`, `src/orchestrator/api/routers/review.py`
- Modified files: `src/orchestrator/api/app.py` (mount review router), `src/orchestrator/git/branch_ops.py` (enhance `get_branch_status`), `src/orchestrator/api/schemas/runs.py` (add fields to `BranchStatusResponse`)
- Test files: `tests/unit/test_diff_ops.py`, `tests/integration/test_review_api.py`

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-01 | `_run_git()` is synchronous (`subprocess.run`), not async. Tasks describe using `asyncio.create_subprocess_exec` "following the `_run_git()` pattern". The agent needs clear direction on which approach to use. | Medium | Task 2 should explicitly state: "Create a new async helper `_run_git_async()` using `asyncio.create_subprocess_exec` in `diff_ops.py`, since the existing `_run_git()` in `branch_ops.py` is synchronous. Follow the same error handling pattern (raise `GitCommandError` on non-zero exit) but with async subprocess." |
| G-02 | Adding `predicted_conflict_count` to `BranchStatusResponse` requires changes in two places: the `BranchStatus` dataclass (domain layer) and `BranchStatusResponse` (API schema), plus the mapping between them. Task 5 only mentions the schema changes, not the dataclass. | Medium | Task 5 should add: "Update the `BranchStatus` dataclass in `branch_ops.py` to include `predicted_conflict_count: int` field, and update the mapping from `BranchStatus` to `BranchStatusResponse` in the runs router." |
| G-03 | Existing branch status tests in `tests/integration/test_branch_ops.py` may break if `BranchStatus` gains new required fields. | Low | Task 5 already has a verification step to run existing tests. The agent should add default values to new fields to maintain backward compatibility. |

---

### Step 2: Frontend Review & Merge Tab Skeleton + Branch Status Panel

**Assumptions Verified:**
- `RunDetail.tsx` exists — **Confirmed**, but it is a flat single-column layout with NO tabs.
- `BranchStatusPanel.tsx` exists — **Confirmed**, can be used as pattern reference.
- `client.ts` uses `fetchApi<T>()` pattern — **Confirmed**.
- `useApi.ts` uses TanStack Query patterns — **Confirmed**.

**Expected Outputs:**
- New files: `ui/src/types/review.ts`, `ui/src/api/reviewClient.ts`, `ui/src/hooks/useReview.ts`, `ui/src/components/review/BranchStatusSection.tsx`, `ui/src/components/review/FileListSection.tsx`, `ui/src/components/review/ReviewMergeTab.tsx`
- Modified: `ui/src/pages/RunDetail.tsx`

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-04 | **RunDetail.tsx has no tab system.** Task 5 says "Add 'Review & Merge' tab to the tab bar" but there is no tab bar. The page is a single-column scroll layout. The agent must create a tab navigation system from scratch (e.g., a tab bar with "Overview" and "Review & Merge" tabs). | High | Task 5 needs explicit guidance: "RunDetail.tsx currently uses a flat single-column layout. Create a tab bar at the top of the page with two tabs: 'Overview' (wrapping the existing content) and 'Review & Merge' (rendering `ReviewMergeTab`). The 'Review & Merge' tab should only be visible when the run has a worktree. Use Tailwind for styling." |
| G-05 | The Playwright E2E test mentioned in Step 2 ("tab renders, branch status displays, file list populates") requires a running backend AND frontend, plus a run with a worktree and committed changes. The step tasks don't describe how to set up this test data. | Medium | Add a Playwright test setup task: "Create a Playwright test fixture that starts the backend/frontend, creates a run with a worktree, makes commits to produce diff data, then verifies the Review & Merge tab renders." Step 2 tasks omit the Playwright test entirely — it should be added as a Task 6 or deferred to a later step. |

---

### Step 3: Diff Dialog with react-diff-view

**Assumptions Verified:**
- `react-diff-view` is NOT installed — **Confirmed**, must be installed.
- `DiffDialog` will be a new component — **Confirmed**, nothing similar exists.

**Expected Outputs:**
- Package installation: `react-diff-view` (and diff parser)
- New files: `ui/src/components/review/DiffViewer.tsx`, `ui/src/components/review/DiffDialog.tsx`
- Modified: `ui/src/hooks/useReview.ts` (add `useDiff()` hook), `ui/src/components/review/FileListSection.tsx` (click handler), `ui/src/components/review/ReviewMergeTab.tsx` (dialog state)

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-06 | Task 1 installs `unidiff` as a diff parsing library. The `unidiff` npm package may not exist or may not be the right choice. `react-diff-view` ships with its own `parseDiff` utility function. | Medium | Task 1 should be: "Install `react-diff-view`. Verify if `react-diff-view`'s built-in `parseDiff` function is sufficient for parsing unified diff text. If it is, no additional diff parser is needed. If not, evaluate `gitdiff-parser` as an alternative." Also check TypeScript type availability — `react-diff-view` may not ship types and may need `@types/react-diff-view` or manual declarations. |
| G-07 | Task 2's `DiffViewer` component needs to import CSS from `react-diff-view`. The library requires its stylesheet to be imported (`react-diff-view/style/index.css`). This is not mentioned. | Low | Task 2 should add: "Import `react-diff-view` CSS stylesheet in the component or in the app's global styles." |

---

### Step 4: Backend Prune Endpoints

**Assumptions Verified:**
- `src/orchestrator/git/prune_ops.py` does not exist — **Confirmed**.
- Event system uses `@dataclass` extending `WorkflowEvent` — **Confirmed**.

**Expected Outputs:**
- New files: `src/orchestrator/git/prune_ops.py`, `tests/unit/test_prune_ops.py`
- Modified: `src/orchestrator/api/schemas/review.py` (add prune schemas), `src/orchestrator/api/routers/review.py` (add prune endpoints), `src/orchestrator/workflow/events.py` (add `PRUNE_APPLIED`), `tests/integration/test_review_api.py` (add prune tests)

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-08 | Hunk-level and line-level prune (Task 3) requires constructing reverse patches from parsed diff output. This is the most complex operation in the entire feature. The task description is vague about the exact algorithm for constructing selective reverse patches from arbitrary hunk/line selections. | High | Task 3 needs a concrete algorithm specification: "To prune specific hunks: (1) Generate the full unified diff for the file. (2) Extract the selected hunk headers and content. (3) Construct a valid patch file with only those hunks. (4) Apply it in reverse via `git apply --reverse --cached`. (5) Reset working tree from index. For line-level: filter individual diff lines within a hunk, adjusting hunk header line counts accordingly." Consider implementing file-level and hunk-level first as a separate task, and line-level as a follow-on, to reduce per-task complexity. |
| G-09 | `preview_prune()` is described as using `git stash` or a temporary work area to avoid modifying the worktree. Using `git stash` in the actual worktree is risky if concurrent operations happen. | Medium | Remediation: `preview_prune()` should compute the resulting diff purely by parsing — apply the reverse patch logic in-memory (construct what the file would look like after prune) without touching the worktree. Alternatively, use `git apply --check --reverse` to validate without applying, then compute the resulting diff from the original diff minus the pruned portions. |
| G-10 | The `PRUNE_APPLIED` event type needs to follow the existing `@dataclass` extending `WorkflowEvent` pattern. Task 4 mentions adding the event type but doesn't specify the dataclass fields. | Low | Task 4 should specify: "Add `PruneApplied(WorkflowEvent)` dataclass with fields: `event_type = 'PRUNE_APPLIED'`, `files_affected: int`, `hunks_removed: int`, `lines_removed: int`, `commit_sha: str`." |

---

### Step 5: Frontend Prune Mode

**Assumptions Verified:**
- Depends on Steps 3 and 4 — **Confirmed**, both must be complete before this step.
- `react-diff-view` supports custom gutters — **Confirmed** per library docs.

**Expected Outputs:**
- New files: `ui/src/components/review/PruneModeProvider.tsx`, `ui/src/components/review/PruneGutter.tsx`, `ui/src/components/review/PruneToolbar.tsx`, `ui/src/components/review/PrunePreviewModal.tsx`
- Modified: `ui/src/hooks/useReview.ts`, `ui/src/api/reviewClient.ts`, `ui/src/components/review/ReviewMergeTab.tsx`, `ui/src/components/review/DiffViewer.tsx`, `ui/src/components/review/FileListSection.tsx`

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-11 | `react-diff-view` custom gutter integration requires specific knowledge of the library's `renderGutter` or `widgets` API. The exact API version matters — `react-diff-view` v2 and v3 have different APIs. The task doesn't specify which version or API to use. | Medium | Task 2 should specify: "Use `react-diff-view`'s `gutterType` or `renderGutter` prop (check the installed version's API docs). For v2+, each `Hunk` component accepts a `gutterEvents` or custom render prop. Verify the specific API after installation in Step 3." |

---

### Step 6: Backend Test Execution Endpoint

**Assumptions Verified:**
- The routine's `auto_verify` commands are the test command source (per clarification Q2) — **Confirmed**.
- `src/orchestrator/review/test_runner.py` does not exist — **Confirmed**.

**Expected Outputs:**
- New files: `src/orchestrator/review/test_runner.py`, `tests/integration/test_review_test_runner.py`
- Modified: `src/orchestrator/api/schemas/review.py`, `src/orchestrator/api/routers/review.py`, `src/orchestrator/workflow/events.py`

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-12 | **How does the test runner access the routine's `auto_verify` commands?** The task says to use the routine's auto_verify config, but doesn't specify how to look it up. The review router endpoint receives a `run_id`. It must: (1) load the run, (2) find the run's routine, (3) access the routine's `auto_verify.items` (list of commands) from the current task/step configuration. The exact model path (e.g., `routine.steps[n].auto_verify.items`) needs to be traced through the codebase. | High | Task 3 should add explicit guidance: "To retrieve auto_verify commands: (1) Load the run via RunService. (2) Get the run's current routine configuration. (3) Access `auto_verify.items` from the task or step config. Inspect `src/orchestrator/workflow/service.py` and the routine model to find the exact access path. If auto_verify is not configured, return 422." |
| G-13 | In-memory test run tracking won't survive server restarts. Test run results are lost on restart. | Low | Acceptable for v1. Document as a known limitation. Consider persisting test run results in the database or as events in a future iteration. |
| G-14 | Preventing concurrent test runs (409 if already running) requires checking the in-memory store. If the server has multiple workers (e.g., uvicorn with multiple processes), in-memory tracking won't provide cross-process mutual exclusion. | Low | For v1 single-worker deployments this is acceptable. Add a comment in the code noting this limitation. For multi-worker deployments, consider a database-backed lock. |

---

### Step 7: Frontend Test Panel + Agent Fix Tests

**Assumptions Verified:**
- Agent executor exists at `src/orchestrator/agents/executor.py` — **Confirmed**.
- Agent dispatch infrastructure exists — **Confirmed**, but it's designed for full builder/verifier phases, not ad-hoc "fix tests" tasks.

**Expected Outputs:**
- New files: `ui/src/components/review/TestPanel.tsx`, `ui/src/components/review/TestLogsDrawer.tsx`, `ui/src/components/review/AgentFixTestsModal.tsx`
- Modified: `ui/src/api/reviewClient.ts`, `ui/src/hooks/useReview.ts`, `ui/src/components/review/ReviewMergeTab.tsx`

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-15 | **Agent dispatch for ad-hoc tasks.** The existing `AgentExecutor.spawn_for_run()` runs a full builder/verifier cycle with structured prompts and checklists. "Use Agent to Fix Tests" requires dispatching the agent with a specific prompt ("fix these failing tests") scoped to the worktree, without the builder/verifier lifecycle. There is no existing API for ad-hoc agent dispatch. | High | The backend needs a new endpoint pattern for ad-hoc agent tasks. Options: (1) Create a new `ReviewAgentExecutor` or a method on `AgentExecutor` that accepts a custom prompt and runs the agent without the builder/verifier lifecycle. (2) Create a lightweight "review task" that wraps the agent call in a minimal structure. This needs to be designed as part of the backend for Steps 7 and 9. Add a new task to Step 7: "Design and implement the ad-hoc agent dispatch mechanism for review-time actions. This differs from the builder/verifier cycle — the agent receives a specific prompt (e.g., 'Fix these failing tests: [test names]') and runs against the worktree without checklists or verification gates." |
| G-16 | ANSI color support in test logs (Task 2) requires a library to parse ANSI escape codes into styled HTML/React elements. No such library is currently installed. | Low | Task 2 should add: "Install and use `ansi-to-react` or `anser` to render ANSI-colored terminal output in the TestLogsDrawer." |

---

### Step 8: Backend Conflict Resolution Endpoints

**Assumptions Verified:**
- `src/orchestrator/git/conflict_ops.py` does not exist — **Confirmed**.
- `back_merge()` exists with signature `back_merge(repo_path, source_branch)` — **Confirmed**. Returns merge commit SHA on success, raises `MergeConflictError` on conflict (which already includes `conflicting_files`).
- `_get_conflict_files()` private helper already exists in `branch_ops.py` — **Confirmed**. Uses `git diff --name-only --diff-filter=U`.

**Expected Outputs:**
- New files: `src/orchestrator/git/conflict_ops.py`, `tests/unit/test_conflict_ops.py`
- Modified: `src/orchestrator/api/schemas/review.py`, `src/orchestrator/api/routers/review.py`, `src/orchestrator/workflow/events.py`, `src/orchestrator/git/branch_ops.py`, `tests/integration/test_review_api.py`

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-17 | **`back_merge()` behavior change.** Currently, `back_merge()` raises `MergeConflictError` on conflict (which aborts the merge via the error handler). The plan wants it to LEAVE the merge in progress (don't abort). This is a breaking behavioral change. The existing runs router's `POST /back-merge` endpoint catches `MergeConflictError` and returns a 409 error response. | High | Task 2 should specify: "The change to `back_merge()` must be carefully scoped. Option A: Add a new parameter `abort_on_conflict: bool = True` (default preserves existing behavior), and set it to `False` when called from the review router. Option B: Create a new `back_merge_for_review()` function that doesn't abort on conflict. Either way, the existing `POST /api/runs/{id}/back-merge` endpoint in `runs.py` must continue to work as before." |
| G-18 | **File path in URL for conflict resolution.** `POST /api/runs/{id}/review/conflicts/{file_path}/resolve` uses `file_path` as a URL path parameter, but file paths contain `/` characters (e.g., `src/foo/bar.py`). FastAPI requires a `path` converter (`{file_path:path}`) or the path must be URL-encoded. | Medium | Task 4 should specify: "Use FastAPI's `{file_path:path}` path converter in the route definition so that paths like `src/foo/bar.py` are captured correctly. Example: `@router.post('/conflicts/{file_path:path}/resolve')`." |
| G-19 | `revert_back_merge()` via `git revert --no-edit <merge_sha>` on a merge commit requires `-m 1` to specify which parent to revert to. Without it, git will refuse to revert a merge commit. | Medium | Task 2 should specify: "Use `git revert --no-edit -m 1 <merge_sha>` to revert the merge commit, where `-m 1` specifies reverting to the first parent (the run branch state before the merge)." |

---

### Step 9: Frontend Back Merge + Conflict Resolver

**Assumptions Verified:**
- Depends on Steps 3 and 8 — **Confirmed**.
- `DiffDialog` pattern available for full-screen overlay — **Confirmed** (created in Step 3).

**Expected Outputs:**
- New files: `ui/src/components/review/BackMergeModal.tsx`, `ui/src/components/review/BackMergeBanner.tsx`, `ui/src/components/review/ConflictFileList.tsx`, `ui/src/components/review/ConflictResolverDialog.tsx`, `ui/src/components/review/ConflictBlock.tsx`, `ui/src/components/review/AgentResolveConflictsModal.tsx`
- Modified: `ui/src/api/reviewClient.ts`, `ui/src/hooks/useReview.ts`, `ui/src/components/review/ReviewMergeTab.tsx`

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-20 | The existing `useBackMerge()` hook in `useApi.ts` calls `api.backMerge(runId)` which returns `Promise<void>`. The review UI needs the response data (merge commit SHA for the undo banner, or conflict file list). Either the existing hook needs updating or a new review-specific hook is needed. | Medium | Task 1 should note: "Create a new `useBackMergeForReview()` hook in `useReview.ts` that calls a new API client function returning the full `BackMergeResponse` (including merge commit SHA or conflict file list). Do not modify the existing `useBackMerge` hook in `useApi.ts` to avoid breaking existing consumers." |
| G-21 | "Manual Selection" in conflict blocks (Task 3) requires an inline editor for custom content. The task mentions it but doesn't specify the editor approach. An inline `<textarea>` or code editor is needed. | Low | Task 3 should clarify: "For 'Manual Selection', render a `<textarea>` pre-filled with the ours content (or a concatenation of ours+theirs). The user edits it to produce the resolved content. No syntax highlighting needed for v1." |

---

### Step 10: Merge Readiness Gating + Final Merge

**Assumptions Verified:**
- `merge_back()` already accepts a `strategy` parameter — **Confirmed**. Default is `"squash"`.
- Depends on Steps 5, 7, 9 — **Confirmed**.

**Expected Outputs:**
- New files: `ui/src/components/review/MergeReadinessBar.tsx`, `tests/integration/test_review_merge_readiness.py`
- Modified: `src/orchestrator/api/schemas/review.py`, `src/orchestrator/api/routers/review.py`, `src/orchestrator/git/branch_ops.py` (if changes needed), `ui/src/api/reviewClient.ts`, `ui/src/hooks/useReview.ts`, `ui/src/components/review/ReviewMergeTab.tsx`

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-22 | `merge_back()` already has a `strategy` parameter (default `"squash"`), so the "enhance with strategy parameter" task is partially redundant. However, the existing `merge_back()` operates on the main repo (not from within the worktree). The review merge-back needs to merge the worktree's run branch into the target branch from the main repo. This distinction needs to be clear. | Medium | Task 1 should clarify: "Verify that the existing `merge_back(main_repo_path, run_branch, source_branch, strategy, worktree_path)` signature is sufficient for the review merge-back use case. The review router should call it with the correct arguments, including the worktree path." |
| G-23 | The "no active jobs" gate requires knowing if any agent job or test run is currently active for this run. There's no centralized "active jobs" registry that tracks both agent executions and test runs. | Medium | Task 1 should specify: "The `no_active_jobs` gate must check: (1) `AgentExecutor.is_running(run_id)` for active agent jobs, (2) `TestRunner.is_running(run_id)` for active test runs. Inject both dependencies into the readiness computation function." |
| G-24 | The "tests_pass" gate needs the most recent test run result. If no tests have been run, should this gate pass or be N/A? | Low | Clarify: "If no test runs exist for this run, the `tests_pass` gate should be in 'pass' status with description 'No tests configured or run'. If the most recent test run failed, the gate fails." |

---

### Step 11: Branch History + Task File Attribution

**Assumptions Verified:**
- `useCommits()` hook created in Step 2 — **Confirmed**.
- Task commit ranges needed for per-task attribution — tasks store `start_commit` and `end_commit` per task.

**Expected Outputs:**
- New files: `ui/src/components/review/HistoryPanel.tsx`, `ui/src/components/review/TaskFilesPanel.tsx`
- Modified: `ui/src/components/review/ReviewMergeTab.tsx`

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-25 | **Task commit range availability.** The `TaskFilesPanel` needs `start_commit` and `end_commit` for each task to compute per-task file attribution. These values come from the run's task data. The step tasks assume this data is available via the existing run API, but don't specify how to access it. The agent needs to know the exact API path. | Medium | Task 2 should specify: "Fetch task commit ranges from the run detail API. Each task's `start_commit` and `end_commit` fields define the commit range. If a task has no commits (e.g., it was skipped), it has no files. Pass these ranges to `GET /review/diff/files?scope=task&ref={start}..{end}` to get per-task file lists." |
| G-26 | Badge detection by commit message patterns (Task 1: "prune:" prefix, "agent:" prefix, merge commits) is fragile. If the commit message format changes, badges break. | Low | Document as a known limitation. Consider adding structured metadata (git notes or commit trailers) in a future iteration. For v1, pattern matching is acceptable. |

---

### Step 12: Visual Polish + Edge States + Keyboard Shortcuts + Visual Regression Tests

**Assumptions Verified:**
- Playwright is installed (`@playwright/test ^1.58.2`) — **Confirmed**.
- All prior steps complete before this step — **Confirmed** (prerequisite: Steps 1-11).

**Expected Outputs:**
- Modified: Multiple existing review components (empty states, loading states, error boundaries)
- New: Keyboard shortcut system (hook or integration), Playwright visual regression test files
- Modified: `docs/ARCHITECTURE.md`

**Gaps Found:**

| ID | Gap | Severity | Remediation |
|----|-----|----------|-------------|
| G-27 | Playwright visual regression tests require a stable, seeded test environment with known data to produce consistent screenshots. The test setup is complex: start backend + frontend, create runs, make commits, trigger various states (conflicts, test failures, prune). | Medium | Task 5 should include explicit setup steps: "Create a shared Playwright fixture that seeds the test environment with: (1) a completed run with 5+ files changed, (2) a run with merge conflicts (3 files), (3) a run with a failed test result. Use these seeded runs to take visual regression screenshots. Consider using Playwright's `beforeAll` with API calls to set up state." |
| G-28 | `docs/ARCHITECTURE.md` updates (Task 4) need to be checked against the actual current state of that file. The task lists all new routes and files to add but doesn't account for the file's current structure. | Low | Task 4 should specify: "Read `docs/ARCHITECTURE.md` first. Locate the 'API routes' table and 'Directory map' section. Add all new `/api/runs/{id}/review/` routes to the table. Add all new source files to the directory map. Preserve the existing format." |

---

## Cross-Cutting Gaps

These gaps affect multiple steps and must be addressed before or during execution.

| ID | Gap | Severity | Steps Affected | Remediation |
|----|-----|----------|----------------|-------------|
| G-29 | **Async vs sync git subprocess calls.** The existing `_run_git()` is synchronous. New modules (`diff_ops.py`, `prune_ops.py`, `conflict_ops.py`) are described as async. The project uses `async` throughout (FastAPI, async by default per AGENTS.md). A consistent async git execution pattern needs to be established once and reused. | High | 1, 4, 8 | Create a shared `_run_git_async()` helper (either in a common git utilities module or replicated in each ops module). Alternatively, make the new modules async wrappers around synchronous git calls using `asyncio.to_thread()`. Decide once in Step 1 and reuse in Steps 4 and 8. |
| G-30 | **ReviewService dependency injection.** The architecture doc mentions `src/orchestrator/api/deps.py` should provide `ReviewService`, but none of the step tasks create a `ReviewService` class. The review router endpoints directly call git ops functions. This inconsistency should be resolved. | Medium | 1, 4, 6, 8, 10 | Either: (A) Create a thin `ReviewService` in Step 1 that aggregates git ops calls and inject it via `deps.py`, or (B) Accept that the review router calls git ops directly (simpler, acceptable for v1) and remove `ReviewService` from the architecture doc. Recommend option B for simplicity. |
| G-31 | **Agent dispatch for review actions** needs a backend mechanism that doesn't exist yet. Steps 7 (agent fix tests) and 9 (agent resolve conflicts) both need it. | High | 7, 9 | Design the ad-hoc agent dispatch mechanism early. Recommendation: create `POST /api/runs/{id}/review/agent-dispatch` as a generic endpoint that accepts a `prompt` and `agent_type`/`agent_config`, spawns the agent against the worktree, and returns a `job_id`. Steps 7 and 9 then use this generic endpoint with different prompts. Implement this as the first task of Step 7. |
| G-32 | **No Playwright E2E tests are defined in the step task files for Steps 2-11.** The plan mentions Playwright tests per milestone, but the actual step task files focus on unit and integration tests. Playwright tests are only explicitly detailed in Step 12. This may lead to accumulating UI debt without E2E verification. | Medium | 2-11 | Either: (A) Accept that Playwright tests are batched in Step 12 (simpler scheduling), or (B) Add a Playwright test task to each frontend step. Recommend option A since each step already has TypeScript compilation and build verification. |

---

## Summary of High-Severity Gaps

| ID | Gap | Steps | Required Action |
|----|-----|-------|-----------------|
| G-04 | RunDetail.tsx has no tab system — must be built from scratch | 2 | Add explicit tab creation guidance to Step 2 Task 5 |
| G-08 | Hunk/line-level prune algorithm unspecified | 4 | Add concrete reverse-patch construction algorithm to Step 4 Task 3 |
| G-12 | Test runner doesn't specify how to access auto_verify commands | 6 | Add explicit model traversal path to Step 6 Task 3 |
| G-15 | No ad-hoc agent dispatch mechanism exists | 7, 9 | Design and implement a new agent dispatch pattern for review actions |
| G-17 | back_merge() behavior change breaks existing callers | 8 | Add backward-compatible parameter or create new function |
| G-29 | Async vs sync git subprocess inconsistency | 1, 4, 8 | Establish async pattern in Step 1, reuse in later steps |
| G-31 | Agent dispatch for review actions needs new backend mechanism | 7, 9 | Create generic ad-hoc agent dispatch endpoint |

---

## Execution Order Validation

The declared dependency chain is:

```
Step 1 (backend diff) ──┬── Step 2 (frontend tab) ── Step 3 (diff dialog) ──┬── Step 5 (prune UI) ──┐
                        ├── Step 4 (backend prune) ──────────────────────────┘                       │
                        ├── Step 6 (backend test exec) ── Step 7 (test UI + agent fix) ──────────────┤
                        └── Step 8 (backend conflicts) ── Step 9 (conflict UI) ─────────────────────┤
                                                                                                     │
                                                          Step 10 (merge gating) ◄───────────────────┘
                                                          Step 11 (history + tasks) ◄── Steps 2, 3
                                                          Step 12 (polish) ◄── Steps 1-11
```

**Validation:** The dependency chain is sound. Steps 4, 6, and 8 can run in parallel (all depend only on Step 1). Steps 2 and 3 are sequential. Steps 5, 7, 9, 10, 11 can partially parallelize (5 after 3+4; 7 after 5+6; 9 after 3+8; 10 after 5+7+9; 11 after 2+3).

**Potential parallelization improvement:** Steps 4, 6, and 8 are independent backend steps that could be executed by separate agents simultaneously after Step 1 completes, reducing total wall-clock time.

---

## Expected Final State After All 12 Steps

### New Files Created (approximately 35 files):

**Backend (Python):**
- `src/orchestrator/review/__init__.py`
- `src/orchestrator/review/models.py`
- `src/orchestrator/review/test_runner.py`
- `src/orchestrator/git/diff_ops.py`
- `src/orchestrator/git/prune_ops.py`
- `src/orchestrator/git/conflict_ops.py`
- `src/orchestrator/api/routers/review.py`
- `src/orchestrator/api/schemas/review.py`

**Frontend (TypeScript/React):**
- `ui/src/types/review.ts`
- `ui/src/api/reviewClient.ts`
- `ui/src/hooks/useReview.ts`
- `ui/src/components/review/ReviewMergeTab.tsx`
- `ui/src/components/review/BranchStatusSection.tsx`
- `ui/src/components/review/FileListSection.tsx`
- `ui/src/components/review/DiffViewer.tsx`
- `ui/src/components/review/DiffDialog.tsx`
- `ui/src/components/review/PruneModeProvider.tsx`
- `ui/src/components/review/PruneGutter.tsx`
- `ui/src/components/review/PruneToolbar.tsx`
- `ui/src/components/review/PrunePreviewModal.tsx`
- `ui/src/components/review/TestPanel.tsx`
- `ui/src/components/review/TestLogsDrawer.tsx`
- `ui/src/components/review/AgentFixTestsModal.tsx`
- `ui/src/components/review/ConflictFileList.tsx`
- `ui/src/components/review/ConflictResolverDialog.tsx`
- `ui/src/components/review/ConflictBlock.tsx`
- `ui/src/components/review/AgentResolveConflictsModal.tsx`
- `ui/src/components/review/BackMergeModal.tsx`
- `ui/src/components/review/BackMergeBanner.tsx`
- `ui/src/components/review/MergeReadinessBar.tsx`
- `ui/src/components/review/HistoryPanel.tsx`
- `ui/src/components/review/TaskFilesPanel.tsx`

**Tests:**
- `tests/unit/test_diff_ops.py`
- `tests/unit/test_prune_ops.py`
- `tests/unit/test_conflict_ops.py`
- `tests/integration/test_review_api.py`
- `tests/integration/test_review_test_runner.py`
- `tests/integration/test_review_merge_readiness.py`
- Playwright visual regression test files

### Modified Files (approximately 10 files):
- `src/orchestrator/api/app.py`
- `src/orchestrator/git/branch_ops.py`
- `src/orchestrator/api/schemas/runs.py`
- `src/orchestrator/workflow/events.py`
- `ui/src/pages/RunDetail.tsx`
- `ui/package.json` (new dependencies)
- `docs/ARCHITECTURE.md`
