# Caching Work Plan

**Date**: 2026-02-26
**Scope**: Three caches identified in `docs/performance-analysis.md` that were not addressed in the initial performance pass.

---

## Overview

Three values are repeatedly recomputed from `git` subprocess calls but change infrequently:

| Cache | Current cost | Trigger |
|-------|-------------|---------|
| Merge-base SHA | 1 subprocess per review endpoint call | Six endpoints each recompute it independently |
| Diff content | Full `git diff` subprocess per file-tab switch | No server-side caching; frontend has 30s `staleTime` but backend recomputes on every request |
| Merge readiness | 4 git subprocesses every 30s poll | `compute_readiness()` runs unconditionally on every `GET /review/merge-readiness` request |

All three caches live in `src/orchestrator/api/routers/review.py` and require no new infrastructure outside that file, plus a small helper module.

---

## Shared Infrastructure

### New file: `src/orchestrator/cache/ttl_cache.py`

A minimal TTL-aware in-memory cache. No new library dependency required.

```python
import time
from typing import Any, Generic, Hashable, TypeVar

V = TypeVar("V")

class TTLCache(Generic[V]):
    """Thread-safe (asyncio-safe) in-memory cache with per-entry TTL."""

    def __init__(self, ttl_seconds: float, maxsize: int = 256) -> None:
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        self._store: dict[Hashable, tuple[float, V]] = {}

    def get(self, key: Hashable) -> V | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: Hashable, value: V) -> None:
        # Evict oldest entry if at capacity
        if len(self._store) >= self._maxsize and key not in self._store:
            oldest = min(self._store, key=lambda k: self._store[k][0])
            del self._store[oldest]
        self._store[key] = (time.monotonic() + self._ttl, value)

    def invalidate(self, key: Hashable) -> None:
        self._store.pop(key, None)

    def invalidate_prefix(self, prefix: Any) -> None:
        """Remove all entries whose key starts with prefix (for tuple keys)."""
        to_remove = [k for k in self._store if isinstance(k, tuple) and k[0] == prefix]
        for k in to_remove:
            del self._store[k]
```

All three caches instantiate `TTLCache` at module level in `review.py`. Module-level instances are shared across requests within the same process and survive between requests, which is the desired behaviour.

---

## Cache 1: Merge-base SHA

**File**: `src/orchestrator/api/routers/review.py`
**Analysis reference**: §2.1

### Problem

Six endpoints (`get_diff`, `get_diff_files`, `get_commits`, `prune_preview`, `prune_apply`, `revert_file`) each independently call:

```python
base_sha, head_sha = await asyncio.gather(
    asyncio.to_thread(_get_merge_base_sync, worktree_path, run.source_branch),
    asyncio.to_thread(_get_head_sha_sync, worktree_path),
)
```

`git merge-base` forks a subprocess per call. On a page load that triggers `get_diff` + `get_diff_files` + `get_commits` simultaneously, the same merge-base is computed three times.

### Cache design

| Property | Value |
|----------|-------|
| Key | `(worktree_path_str, source_branch, head_sha)` |
| TTL | 5 minutes (safety net; structural invalidation is handled by key) |
| Invalidation | Implicit — a new commit changes `head_sha`, producing a cache miss automatically |
| Max size | 128 entries |

Including `head_sha` in the key means the cached value is automatically stale when the run branch gains new commits. `head_sha` must still be fetched on every call, but `git rev-parse HEAD` is cheaper than `git merge-base`.

### Implementation

Add to `review.py`, before the endpoint definitions:

```python
from orchestrator.cache.ttl_cache import TTLCache

_merge_base_cache: TTLCache[str] = TTLCache(ttl_seconds=300, maxsize=128)


async def _get_merge_base_cached(worktree_path: Path, source_branch: str) -> tuple[str, str]:
    """Return (base_sha, head_sha), using a cache keyed on head_sha.

    Fetching head_sha is cheap (git rev-parse HEAD). We use it as part of
    the cache key so any new commit on the run branch produces a cache miss.
    """
    head_sha = await asyncio.to_thread(_get_head_sha_sync, worktree_path)
    cache_key = (str(worktree_path), source_branch, head_sha)
    cached = _merge_base_cache.get(cache_key)
    if cached is not None:
        return cached, head_sha
    base_sha = await asyncio.to_thread(_get_merge_base_sync, worktree_path, source_branch)
    _merge_base_cache.set(cache_key, base_sha)
    return base_sha, head_sha
```

Replace every occurrence of the `asyncio.gather(_get_merge_base_sync, _get_head_sha_sync)` pattern with a call to `_get_merge_base_cached`. The six call sites are:

| Endpoint | Line | Change |
|----------|------|--------|
| `get_diff` (aggregate/task scope) | ~167 | Replace `asyncio.gather(...)` with `await _get_merge_base_cached(...)` |
| `get_diff_files` (aggregate scope) | ~221 | Same |
| `get_commits` | ~256 | Same |
| `prune_preview` | ~298 | Replace `asyncio.to_thread(_get_merge_base_sync, ...)` with `base_sha, _ = await _get_merge_base_cached(...)` |
| `prune_apply` | ~343 | Same |
| `revert_file_endpoint` | ~455 | Same |

### Expected impact

On a cold-cache page load triggering three concurrent review tab queries, the two most expensive calls (`git merge-base` for `get_diff` and `get_diff_files`) are eliminated after the first resolves. On subsequent requests within 5 minutes to the same worktree+branch, the merge-base is free.

---

## Cache 2: Diff content

**File**: `src/orchestrator/api/routers/review.py`
**Analysis reference**: §2.6

### Problem

Every time the user switches files in the Review tab, `GET /review/diff` is called. The backend computes `git diff <base>..<head>` from scratch. For a run with many commits or large files, this takes hundreds of milliseconds. Two browser tabs open to the same run each trigger a full subprocess.

The frontend sets `staleTime: 30000` in `useReview.ts`, so the client won't re-request within 30 seconds — but the backend has no corresponding cache, so different clients or a reconnect after 30 seconds always costs a full git subprocess.

### Cache design

| Property | Value |
|----------|-------|
| Key | `(run_id, scope, ref_or_empty, head_sha)` |
| TTL | 60 seconds |
| Invalidation | Implicit via `head_sha` in key — a prune, revert, or back-merge produces a cache miss |
| Max size | 64 entries (diff strings can be large) |

The `ref` parameter distinguishes task-scoped diffs (`ref="<start>..<end>"`) from the aggregate diff (`ref=""`). `head_sha` is already fetched by the endpoint, so including it in the key adds no subprocess cost.

### Implementation

```python
_diff_cache: TTLCache[str] = TTLCache(ttl_seconds=60, maxsize=64)
```

In `get_diff`, after computing `base_sha` and `head_sha`, check the cache before calling `get_branch_diff` / `get_task_diff`:

```python
cache_key = (run_id, scope, ref or "", head_sha)
cached_diff = _diff_cache.get(cache_key)
if cached_diff is not None:
    return DiffResponse(diff=cached_diff, scope=scope)

# ... compute diff_text as before ...

_diff_cache.set(cache_key, diff_text)
return DiffResponse(diff=diff_text, scope=scope)
```

Apply the same pattern to `get_diff_files` with a separate `_diff_files_cache: TTLCache[list[ModifiedFile]]` (or serialize to a JSON-compatible type for the cache value).

### Expected impact

File-switching in the Review tab becomes near-instant for any file already fetched in the same session. Two tabs viewing the same run share cached diffs.

---

## Cache 3: Merge readiness

**File**: `src/orchestrator/api/routers/review.py`
**Analysis reference**: §2.7

### Problem

`compute_readiness()` runs on every `GET /review/merge-readiness` request. The frontend polls this every 30 seconds. Each call triggers:

- `get_branch_status()` → up to 4 git subprocesses (`_branch_exists` × 2, `rev-list`, `merge-tree`)
- `get_conflict_files()` → 1 subprocess

Merge readiness only changes after a mutation: prune, revert, back-merge, conflict resolution, or a test run completing. Between mutations the result is identical — but it is recomputed from scratch every 30 seconds.

### Cache design

| Property | Value |
|----------|-------|
| Key | `run_id` |
| TTL | 60 seconds (safety net) |
| Invalidation | Explicit — mutation endpoints call `_invalidate_merge_readiness(run_id)` |
| Max size | 64 entries |

The TTL acts as a backstop if an invalidation call is ever missed (e.g., a mutation triggered from outside the API). Under normal operation the cache is invalidated immediately after each mutation, so the 30-second poll always returns a fresh result after a state change.

### Mutation endpoints that must invalidate

All of these can change branch divergence, conflicts, or test results:

| Endpoint | Router file | Reason |
|----------|-------------|--------|
| `prune_apply` | `review.py` | Creates a new commit on the run branch |
| `revert_file_endpoint` | `review.py` | Creates a new commit on the run branch |
| `revert_back_merge_endpoint` | `review.py` | Removes a merge commit |
| `resolve_conflict_endpoint` | `review.py` | Resolves one or more conflict files |
| `agent_resolve_conflicts` | `review.py` | Dispatches agent to resolve conflicts |
| `back_merge_endpoint` | `runs.py` | Merges source branch into run branch |

`prune_preview` does **not** invalidate (read-only preview with no commits).
`start_test_run` does not invalidate (test result gate only changes on completion, handled by TTL).

### Implementation

```python
from orchestrator.cache.ttl_cache import TTLCache
from orchestrator.api.schemas.review import MergeReadiness

_readiness_cache: TTLCache[MergeReadiness] = TTLCache(ttl_seconds=60, maxsize=64)


def _invalidate_merge_readiness(run_id: str) -> None:
    _readiness_cache.invalidate(run_id)
```

In `compute_readiness()`, wrap the body with a cache check:

```python
async def compute_readiness(
    run: Run,
    repo_path: Path,
    test_runner: TestRunner,
    executor: AgentExecutor,
) -> MergeReadiness:
    cached = _readiness_cache.get(run.id)
    if cached is not None:
        return cached

    # ... existing gate computation ...

    result = MergeReadiness(ready=ready, gates=gates)
    _readiness_cache.set(run.id, result)
    return result
```

In each mutation endpoint, add `_invalidate_merge_readiness(run_id)` after the mutating operation succeeds. Example for `prune_apply`:

```python
    # Log PRUNE_APPLIED event
    await emitter.emit(PruneApplied(...))
    _invalidate_merge_readiness(run_id)   # ← add this line
```

Note: `merge_back_endpoint` in `runs.py` calls `compute_readiness()` itself as a pre-flight check — no invalidation needed there since a successful merge-back completes the run.

### Expected impact

Under normal usage (no mutations between polls), the 30-second poll from the frontend hits the cache and returns in microseconds rather than spending 4–5 git subprocess calls. After any mutation the result is immediately stale and the next poll recomputes.

---

## Files Changed Summary

| File | Change |
|------|--------|
| `src/orchestrator/cache/__init__.py` | New package (empty) |
| `src/orchestrator/cache/ttl_cache.py` | New: `TTLCache` class |
| `src/orchestrator/api/routers/review.py` | Add 3 module-level caches; replace merge-base calls with `_get_merge_base_cached`; add diff cache reads/writes in `get_diff` and `get_diff_files`; add readiness cache in `compute_readiness`; add `_invalidate_merge_readiness` calls in 5 mutation endpoints |
| `src/orchestrator/api/routers/runs.py` | Add `_invalidate_merge_readiness(run_id)` call in `back_merge_endpoint` |

---

## Testing

### Unit tests for `TTLCache`

New file `tests/unit/test_ttl_cache.py`:

- `get` on empty cache returns `None`
- `set` then `get` returns value
- `get` after TTL expires returns `None`
- `invalidate` removes entry
- `invalidate_prefix` removes only matching entries
- At `maxsize`, setting a new key evicts the oldest

### Integration tests for each cache

**Merge-base cache** (`tests/integration/test_review_api.py`):

- Two concurrent requests to `GET /review/diff` and `GET /review/diff/files` trigger only one `git merge-base` call (use `unittest.mock.patch` on `_get_merge_base_sync` to count invocations).
- After a `prune_apply` (which changes HEAD), the next diff request recomputes (different `head_sha` = cache miss).

**Diff cache** (`tests/integration/test_review_api.py`):

- Second identical `GET /review/diff` call returns cached result without calling `git diff` again.
- `GET /review/diff` with different `ref` is a cache miss (separate key).

**Readiness cache** (`tests/integration/test_merge_readiness.py`):

- Two `GET /review/merge-readiness` calls within TTL trigger `get_branch_status` only once.
- `POST /review/prune/apply` invalidates the cache; subsequent readiness call recomputes.
- `POST /review/revert-file` invalidates the cache.
- `POST /review/conflicts/{file}/resolve` invalidates the cache.

---

## Implementation order

1. `TTLCache` class and tests — no dependencies, can be done in isolation
2. Merge-base cache — highest impact per line of code; touches only `review.py`
3. Merge readiness cache — requires coordinated invalidation across two router files
4. Diff content cache — lowest risk; isolated to `get_diff` and `get_diff_files`
