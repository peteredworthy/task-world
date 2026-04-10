# UI/API Performance Analysis

**Date**: 2026-02-26
**Scope**: Dashboard slowness, Review & Merge git diff slowness, general API latency

---

## Executive Summary

Three root causes drive most of the UI sluggishness:

1. **Over-fetching at the DB layer** — every "list runs" query loads the entire object graph (run → steps → tasks → attempts) even when only summary fields are needed.
2. **No caching of repeated git operations** — the review endpoints recompute `merge-base` on every request and make N sequential subprocess calls where async/parallel calls would suffice.
3. **Unbounded client-side filtering** — the Dashboard fetches up to 50 complete run objects from the API, then filters locally rather than pushing filters to the DB.

---

## 1. Dashboard Slowness

### 1.1 Unbounded DB Queries (`GET /api/runs`)

**File**: `src/orchestrator/db/repositories.py:371–409`
**Severity**: HIGH

All four `list_*` methods (`list_by_repo`, `list_by_status`, `list_by_repo_and_status`, `list_recent`) have **no LIMIT clause** and use the `_eager_run_query()` which loads the full nested tree:

```python
def _eager_run_query() -> Any:
    return select(RunModel).options(
        selectinload(RunModel.steps)
            .selectinload(StepModel.tasks)
            .selectinload(TaskModel.attempts)   # entire tree
    )
```

A single "list all active runs" call loads every step, task, and attempt into Python objects. With 50 runs × 5 steps × 5 tasks × 3 attempts = 3,750 ORM rows → converted to 3,750 Pydantic domain objects, all to show a list of run titles.

**What to do**:
- Create a separate `list_runs_summary()` that selects only `RunModel` fields (no nested `selectinload`).
- Push `status`, `repo_name`, and `limit` filters into SQL — do not filter client-side in the API layer.
- The API's `list_runs` endpoint (`runs.py`) already accepts `limit` but only passes it to `list_all`; the other three `list_*` variants ignore it entirely.

### 1.2 Duplicate Nested Loops in `_run_to_response()`

**File**: `src/orchestrator/api/routers/runs.py:143–173`
**Severity**: MEDIUM

The function iterates over `run.steps → tasks → attempts` **twice** — once to sum actual cost, once to find the `model_hint`. Both traversals should be a single pass.

### 1.3 Client-Side Filtering on Dashboard

**File**: `ui/src/pages/Dashboard.tsx`
**Severity**: MEDIUM

The frontend fetches up to 50 runs (the `max_recent_runs` config value) with full data, then filters locally for status, repo, and "needs_input" states. Status and repo filters should be server-side SQL `WHERE` clauses. The "needs_input" computed filter (checking `pending_action_type` + `approval_status`) can also be a DB query once those fields are indexed.

### 1.4 Dashboard Polls Every 10s Including for Completed Runs

**File**: `ui/src/hooks/useApi.ts` (`useRuns` hook)
**Severity**: LOW–MEDIUM

`useRuns()` polls every 10 seconds unconditionally. Completed/failed runs in the list will never change; polling should stop or lengthen for them. The existing pattern for `useRun(runId)` already stops polling when the run reaches a terminal state — the same logic should apply to the runs list.

### 1.5 Missing Index on `runs.created_at`

**File**: `src/orchestrator/db/models.py`
**Severity**: LOW–MEDIUM

`list_recent()` filters by `created_at >= cutoff` and all list queries `ORDER BY created_at DESC`. There is no index on this column, requiring a full table scan + sort.

---

## 2. Review & Merge Slowness

### 2.1 Merge-Base SHA Recomputed on Every Request

**File**: `src/orchestrator/api/routers/review.py:80–110`
**Severity**: HIGH

Six different endpoints (`get_diff`, `get_diff_files`, `get_commits`, `prune_preview`, `prune_apply`, `revert_file`) each independently call:

```python
base_sha, head_sha = await asyncio.gather(
    asyncio.to_thread(_get_merge_base_sync, worktree_path, run.source_branch),
    asyncio.to_thread(_get_head_sha_sync, worktree_path),
)
```

`git merge-base` forks a subprocess per call. Because the merge-base between the run branch and source branch changes only when commits are added (prune/revert/back-merge), it is safe to cache per `(run_id, head_sha)`.

**What to do**:
- Add an in-memory or per-request LRU cache keyed on `(worktree_path, run_branch_head)`.
- Alternatively, store the last computed `merge_base_sha` on the `Run` domain object and invalidate it only when commits change.

### 2.2 N+1 Subprocess Calls for Conflict Block Parsing

**File**: `src/orchestrator/api/routers/review.py:641–677`
**Severity**: HIGH

`get_conflicts()` calls `get_conflict_files()` once (one subprocess), then loops and calls `get_conflict_blocks(worktree_path, file_path)` per file — each as a separate subprocess invocation. With 10 conflict files → 11 subprocesses.

```python
for file_path in conflict_file_paths:
    blocks = await get_conflict_blocks(worktree_path, file_path)
```

**What to do**: Use `asyncio.gather()` to run all `get_conflict_blocks()` calls concurrently:
```python
blocks_list = await asyncio.gather(
    *[get_conflict_blocks(worktree_path, fp) for fp in conflict_file_paths]
)
```

### 2.3 Two Separate `git diff` Calls Per File-List Request

**File**: `src/orchestrator/git/diff_ops.py:84–106`
**Severity**: MEDIUM

`get_modified_files()` runs `git diff --name-status` then a second `git diff --numstat` over the same commit range. These can be combined: `git diff --numstat` already includes file paths; `--name-status` is redundant.

### 2.4 Duplicate Conflict-File Detection Within Endpoints

**File**: `src/orchestrator/api/routers/review.py:704–812`
**Severity**: MEDIUM

In `agent_resolve_conflicts()` and `resolve_conflict_endpoint()`, `get_conflict_files()` is called 2–3 times within the same request handler. The result should be fetched once at the top of the handler and reused.

### 2.5 Branch Status Makes 4 Sequential Subprocess Calls

**File**: `src/orchestrator/git/branch_ops.py:92–159`
**Severity**: MEDIUM

`get_branch_status()` calls:
1. `_branch_exists(repo_path, run_branch)` — subprocess
2. `_branch_exists(repo_path, source_branch)` — subprocess
3. `git rev-list --left-right --count` — subprocess
4. `git merge-tree --write-tree` (conditional, when behind_count > 0) — subprocess

Steps 1 and 2 can be folded into the `rev-list` call (which will fail if either branch doesn't exist). Steps 3 and 4 could potentially run in parallel since merge-tree is independent of the count.

### 2.6 No Diff Content Caching

**File**: `ui/src/hooks/useReview.ts` + `src/orchestrator/api/routers/review.py`
**Severity**: MEDIUM

Every time the user switches files in the Review tab, `getDiff()` is called with the new file scope. The backend recomputes the diff from scratch. For a repo with large files or many commits, `git diff <base>..<head> -- <file>` is not trivial.

The frontend sets `staleTime: 30000` (30s) for diff results. However, the backend has no caching at all — if two browser tabs open the same run, they each trigger a full `git diff` subprocess.

**What to do**: Add a short-lived (e.g., 60s) in-memory LRU cache in the backend keyed on `(run_id, scope, ref, head_sha)`.

### 2.7 Merge Readiness Computed on Every Poll

**File**: `src/orchestrator/api/routers/review.py:840–1005`
**Severity**: LOW–MEDIUM

`compute_readiness()` calls `get_branch_status()` (4 git subprocesses) plus `get_conflict_files()` on every request. The frontend polls this every 30s. Since merge readiness only changes after a mutation (merge, back-merge, prune), it should be cached and invalidated on mutations rather than recomputed on every poll.

---

## 3. General API Layer Issues

### 3.1 Entire Run Tree Loaded for Activity Enrichment

**File**: `src/orchestrator/api/routers/runs.py:501–545`
**Severity**: MEDIUM

`get_activity()` loads the full run (with all steps/tasks/attempts via eager loading) just to build a `task_lookup` dictionary for event title enrichment. The same pattern is duplicated in `stream_activity()`.

**What to do**: Replace the full run load with a targeted query:
```sql
SELECT id, title, config_id FROM tasks WHERE run_id = ?
UNION
SELECT id, title, config_id FROM steps WHERE run_id = ?
```
This avoids loading attempts entirely.

### 3.2 SSE Streaming Polls DB Every 500ms

**File**: `src/orchestrator/api/routers/runs.py:590`
**Severity**: MEDIUM

The SSE `stream_activity()` generator polls SQLite every 500ms. With N concurrent SSE clients → N × 2 queries/second. Under load with 10 users watching 10 runs = 200 DB queries/second just for event streaming.

**What to do**: Use an in-memory pub/sub (e.g., `asyncio.Queue`) per run. The event emitter pushes to the queue; SSE clients `await queue.get()` with a timeout rather than polling.

### 3.3 Duplicate Active-Run Queries at Startup

**File**: `src/orchestrator/api/app.py:58–104`
**Severity**: LOW–MEDIUM

On startup, `list_by_status(ACTIVE)` is called twice (lines 58 and 77) with full eager loading. The results of the first call should be reused for the second.

### 3.4 Missing DB Indexes

**File**: `src/orchestrator/db/models.py`
**Severity**: MEDIUM

| Column | Used for | Currently indexed? |
|--------|----------|--------------------|
| `runs.created_at` | ORDER BY, list_recent cutoff | No |
| `events.event_type` | Paginated activity filtering | No |
| `tasks.status` | Recovery queries, agent startup | No |
| Composite `(events.run_id, events.event_type)` | Common paginated filter | No |

---

## 4. Frontend Issues

### 4.1 `useActivity` Polls Even When No More Events

**File**: `ui/src/hooks/useApi.ts`
**Severity**: LOW

`useActivity` polls every 10s unconditionally even when the response has `has_more: false` and the run is in a terminal state. Polling should stop for completed/failed/cancelled runs.

### 4.2 Review Tab Fetches All Data on Mount

**File**: `ui/src/components/review/ReviewMergeTab.tsx`
**Severity**: LOW

When the Review & Merge tab is opened, several queries fire simultaneously: `useDiffFiles`, `useCommits`, `useBranchStatus`, `useMergeReadiness`, `useConflicts`. The diff files and commits are the most expensive (git operations). Consider lazy-loading these only when the user expands the relevant section, or using Suspense boundaries to load them progressively.

---

## Priority Ranking

| # | Issue | Effort | Impact |
|---|-------|--------|--------|
| 1 | Summary-only DB query for run lists (no eager loading) | Medium | Eliminates Dashboard lag for large datasets |
| 2 | Cache merge-base SHA per request/run | Small | Cuts review endpoint latency by ~50% |
| 3 | Parallelize conflict block parsing (`asyncio.gather`) | Small | Immediate fix for conflict-heavy runs |
| 4 | Add missing DB indexes (`created_at`, `event_type`) | Small | Speeds up sorting and activity filtering |
| 5 | Combine two `git diff` calls into one | Small | Small saving per file-list request |
| 6 | Push run list filters to SQL (not client-side) | Medium | Reduces payload size + DB work |
| 7 | Replace SSE polling with async queue | Medium | Scalability for multiple concurrent users |
| 8 | Single-pass cost+model loop in `_run_to_response` | Small | Minor CPU saving per response |
| 9 | Cache merge readiness result | Medium | Cuts branch-status subprocess calls on polls |
| 10 | Stop polling completed runs on Dashboard | Small | Reduces unnecessary network traffic |

---

## Files to Change (Quick Reference)

| File | Issues |
|------|--------|
| `src/orchestrator/db/repositories.py` | Add summary query, add LIMIT to list methods |
| `src/orchestrator/db/models.py` | Add indexes on `created_at`, `event_type`, `tasks.status` |
| `src/orchestrator/api/routers/review.py` | Cache merge-base, parallelize conflict blocks, deduplicate conflict detection |
| `src/orchestrator/git/diff_ops.py` | Combine two git diff calls |
| `src/orchestrator/git/branch_ops.py` | Reduce sequential subprocess calls |
| `src/orchestrator/api/routers/runs.py` | Fix `_run_to_response` loops, lightweight activity enrichment, fix startup duplicate query |
| `ui/src/hooks/useApi.ts` | Stop polling terminal-state runs list, fix `useActivity` poll condition |
| `ui/src/pages/Dashboard.tsx` | Use server-side filters instead of client-side |
