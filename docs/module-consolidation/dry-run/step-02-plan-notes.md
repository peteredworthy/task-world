# Dry-Run Analysis: Step 2 — Absorb cache/ + review/ + repos/ → git/

Analyzed against the current codebase state (pre-Phase-0, pre-Phase-1).

---

## Overall Assessment

The step is structurally sound and the logic is correct. However, it has **one blocking prerequisite issue** (Phase 0 must complete first), **one missing file in the consumer list**, and **several incomplete export lists** in the `__init__.py` specifications. None of these are design flaws — they are specification gaps that will cause failures if not corrected before execution.

---

## Phase 0 Prerequisite State

**BLOCKING**: `src/orchestrator/git/diff_models.py` does **not exist** in the current codebase. Phase 0 (Step 0) must be completed before Step 2 can run. Task 4's guard check ("Inspect `git/diff_models.py` to confirm it contains CommitInfo...") correctly catches this and halts execution.

Corollary: `src/orchestrator/git/diff_ops.py` currently imports:
```python
from orchestrator.review.models import CommitInfo, FileStatus, ModifiedFile
```
Task 4's "OLD" import path (`from orchestrator.git.diff_models import ...`) is only correct **post-Phase 0**. The step plan is technically accurate for its stated prerequisites, but the implementor must understand that Task 4 is describing post-Phase-0 code, not current code.

**Action**: Add a preflight check at the top of the step file: "Run `test -f src/orchestrator/git/diff_models.py || echo STOP: Phase 0 incomplete` before beginning any task."

---

## Task-by-Task Analysis

### Task 1: Scaffold git/ sub-packages

**Assumptions**: The four sub-package directories don't exist yet. Verified correct.

**Expected output**: Four new empty `__init__.py` files. No other changes.

**Risks**: None. This is additive-only.

---

### Task 2: Absorb cache/ → git/diff/lru_cache.py

**Consumers of `orchestrator.cache.lru_cache` (verified)**:
- `src/orchestrator/git/cached_diff_ops.py` line 6: `from orchestrator.cache.lru_cache import Cache` ✓ listed
- `src/orchestrator/api/routers/review.py` line 51: `from orchestrator.cache.lru_cache import LRUCache` ✓ listed
- `tests/unit/cache/test_lru_cache.py` ✓ listed
- `tests/unit/cache/test_cached_diff_ops.py` ✓ listed

**No consumers of `orchestrator.cache` (top-level __init__)** — the cache `__init__.py` re-exports Cache and LRUCache, but no external file uses this shorthand. All callers import directly from `lru_cache`. Safe to delete.

**Risks**: None. All four consumers are correctly identified.

---

### Task 3: Absorb repos/ → git/repos/

**Consumers of `orchestrator.repos.*` (verified)**:
- `src/orchestrator/mcp/tools.py` ✓ listed
- `src/orchestrator/cli/repos.py` ✓ listed
- `src/orchestrator/api/routers/repos.py` ✓ listed
- `src/orchestrator/api/errors.py` ✓ listed

**MISSING FILE**: `tests/unit/repos/test_discovery.py` is NOT in the step plan's update list. This file imports:
```python
from orchestrator.repos import (
    RepoNotFoundError, branch_count, get_repo,
    list_branches, list_repos, match_branches,
)
```
After `repos/` is deleted, this test will fail with `ModuleNotFoundError`. The fix is to change the import to `from orchestrator.git.repos import ...`.

**Action**: Add `tests/unit/repos/test_discovery.py` to the Task 3 consumer update list.

**BranchNotFoundError naming collision**: Two distinct classes share this name:
- `orchestrator.git.errors.BranchNotFoundError(branch: str)` — for git worktree/branch operations
- `orchestrator.repos.errors.BranchNotFoundError(repo_name: str, branch_name: str)` — for repo discovery

After the move, the repos version lives at `orchestrator.git.repos.errors.BranchNotFoundError`. These are at different import paths and won't collide at runtime. However, `git/__init__.py` already exports `BranchNotFoundError` (the git.errors version). The `git/repos/__init__.py` also exports a `BranchNotFoundError`. As long as `git/__init__.py` does NOT re-export from `git.repos`, there is no shadowing. The step plan's proposed `git/__init__.py` (Task 7) does not include repos exports, so no collision at the top-level module.

**Risk (low)**: Future maintainers may be confused by two `BranchNotFoundError` classes in the git ecosystem.

**Action (informational)**: Document in `git/repos/errors.py` that this class is distinct from `git.errors.BranchNotFoundError`. No code change required.

---

### Task 4: Consolidate diff models → git/diff/models.py

**Assumptions being made**:
1. `git/diff_models.py` exists (Phase 0 artifact) — NOT currently true; correct post-Phase 0
2. `diff_ops.py` imports from `git.diff_models` not `review.models` — NOT currently true; correct post-Phase 0
3. `review/models.py` remains with only `DiffScope` and `DiffResult` (CommitInfo/FileStatus/ModifiedFile already moved) — correct post-Phase 0

**All three assumptions are valid only after Phase 0**. The Task 4 gate check handles this correctly.

**Post-Phase-0, the content of `git/diff/models.py` will be**:
- From `git/diff_models.py`: `CommitInfo`, `FileStatus` (enum: ADDED/MODIFIED/DELETED/RENAMED), `ModifiedFile`
- From `review/models.py` (remaining): `DiffScope` (enum: FILE/BRANCH/COMMIT), `DiffResult`

The step plan's `git/diff/__init__.py` exports all five types. Verified correct.

**Action**: None — logic is sound; just gates on Phase 0.

---

### Task 5: Absorb review/test_runner.py → git/testing/ and delete review/

**Consumers of `orchestrator.review.test_runner` (verified)**:
- `src/orchestrator/api/deps.py` line 25 ✓ listed
- `src/orchestrator/api/routers/runs.py` line 27 ✓ listed
- `src/orchestrator/api/app.py` line 502 (lazy import inside startup function) ✓ listed
- `src/orchestrator/api/routers/review.py` line 62 ✓ listed
- `tests/integration/test_review_test_api.py` lines 211, 288 (lazy imports in test functions) ✓ listed
- `tests/integration/test_review_test_runner.py` lines 185, 283 (lazy imports in test functions) ✓ listed
- `tests/integration/test_merge_readiness.py` line 24 ✓ listed

**Important**: The step plan says `api/routers/review.py` imports `TestRunResult, TestRunner`. Confirmed correct (line 62).

**Verify before delete**: After Phase 0, `review/models.py` retains `DiffScope`, `DiffResult`. The pre-delete grep check (`grep -r "from orchestrator\.review" src/ tests/`) must return zero. After Task 4 absorbs `review/models.py` types into `git/diff/models.py`, the only remaining consumers of `review` are `test_runner` consumers (handled in Task 5) and `review/__init__.py` itself. No external code uses `orchestrator.review` (the top-level `__init__`). Safe to delete.

**Risks**: None. All consumers correctly identified.

---

### Task 6: Move diff_ops.py and cached_diff_ops.py into git/diff/

**Import chain for `cached_diff_ops.py`**:

`git/cached_diff_ops.py` currently imports:
```python
from orchestrator.cache.lru_cache import Cache          # → updated to git.diff.lru_cache in Task 2
from orchestrator.git.diff_ops import (CommitInfo, ModifiedFile, get_branch_diff, ...)
```

By Task 6, after Task 2 updated the cache import and Task 4 moved diff models, `cached_diff_ops.py` at the git root will have:
```python
from orchestrator.git.diff.lru_cache import Cache          # (updated in Task 2)
from orchestrator.git.diff_ops import (CommitInfo, ModifiedFile, ...)
```
(Note: `diff_ops.py` itself is still at git root at this point, updated in Task 4 to import from `git.diff.models`.)

When Task 6 creates `git/diff/cached_diff_ops.py`, it correctly changes `from orchestrator.git.diff_ops import ...` to `from orchestrator.git.diff.diff_ops import ...`. This is correct.

**External consumers of `git.cached_diff_ops` (verified)**:
- `src/orchestrator/api/routers/review.py` line 52: `from orchestrator.git.cached_diff_ops import CachedDiffOps, DiffOps, GitDiffOps` ✓ listed
- `tests/unit/cache/test_cached_diff_ops.py` line 10: `from orchestrator.git.cached_diff_ops import CachedDiffOps` ✓ listed

**External consumers of `git.diff_ops` (verified)**:
- `tests/unit/test_diff_ops.py` line 8: `from orchestrator.git.diff_ops import (...)` ✓ listed
- (Note: `git/cached_diff_ops.py` import is handled within the task)

**Risks**: Low. The multi-step import chain (cache import in Task 2, models import in Task 4, then ops move in Task 6) is logically correct but must be executed in order.

---

### Task 7: Create git/ops/ and relocate branch/conflict/prune ops

**INCOMPLETE EXPORT LISTS**: The proposed `git/ops/__init__.py` is missing several symbols that exist in the source files.

`branch_ops.py` defines: `BranchStatus`, `BackMergeResult`, `RevertBackMergeResult`, `get_branch_status`, `back_merge`, `revert_back_merge`, `merge_back`, **`sync_branch_to_worktree`** — the last one is absent from the `__init__.py`.

`conflict_ops.py` defines: `ConflictBlock`, `BlockResolution`, `get_conflict_files`, `get_conflict_blocks`, `resolve_conflict`, **`parse_conflict_blocks`**, **`mark_all_resolved`** — the last two are absent.

`prune_ops.py` defines: `FileSelectionEntry`, `apply_prune`, `compute_selection_preview`, `prune_hunks`, `prune_lines`, `revert_file`, **`preview_prune`**, **`FileDiffSection`**, **`PruneStats`**, **`Hunk`** — the last four are absent.

Some missing symbols are referenced by test files (imported directly from sub-modules, not from `git.ops`):
- `tests/unit/test_conflict_ops.py` imports `parse_conflict_blocks` from `git.conflict_ops` — after Task 7 becomes `git.ops.conflict_ops` ✓ (path update handles it)
- `tests/unit/test_prune_ops.py` imports `Hunk` from `git.prune_ops` — after Task 7 becomes `git.ops.prune_ops` ✓ (path update handles it)

No external caller currently imports these symbols from `orchestrator.git` top-level (they import from sub-modules directly), so they don't need to be in `git/ops/__init__.__all__`. However, they must be importable via `git.ops.branch_ops.sync_branch_to_worktree` etc., which they will be since the files are copied verbatim.

**Verdict**: The missing exports don't cause runtime failures because no caller uses `from orchestrator.git.ops import sync_branch_to_worktree`. But the `__init__.py` `__all__` as specified is incomplete relative to the actual public API of these modules.

**Action (recommended)**: Enumerate the complete `__all__` for `git/ops/__init__.py` by reading actual file contents before writing. Minimum: add `sync_branch_to_worktree`, `parse_conflict_blocks`, `mark_all_resolved`, `preview_prune`, `Hunk`, `FileDiffSection`, `PruneStats`, `FileSelectionEntry` to the list.

**`git/__init__.py` update**: The step plan's proposed new `git/__init__.py` removes all `conflict_ops`, `prune_ops`, and diff-related exports (they were never in `git/__init__.py` to begin with — they were imported directly from sub-modules). This is correct. The step plan correctly updates all direct consumers (review.py, runs.py, test files) to use the new `git.ops.*` paths.

**External consumers of `git.branch_ops` not yet identified**:
- The step plan finds all three inline imports in `api/routers/runs.py` (lines 1153, 1211, 1264-1265). Verified correct.
- `api/routers/review.py` line 43: `from orchestrator.git.branch_ops import get_branch_status, revert_back_merge` ✓ listed in Task 7

**External consumers of `git.conflict_ops` (verified)**:
- `api/routers/review.py` lines 45-50 ✓ listed in Task 7

**External consumers of `git.prune_ops` (verified)**:
- `api/routers/review.py` lines 54-61 ✓ listed in Task 7

---

### Task 8: Full verification and cleanup

Plan is correct and comprehensive. One addition: include the `tests/unit/repos/test_discovery.py` import verification in the repos grep check.

---

## Complete Consumer Summary (for implementor reference)

### `orchestrator.cache.*` → `orchestrator.git.diff.lru_cache`
| File | Import | Task |
|------|--------|------|
| `git/cached_diff_ops.py` | `Cache` | 2 |
| `api/routers/review.py` | `LRUCache` | 2 |
| `tests/unit/cache/test_lru_cache.py` | `LRUCache` | 2 |
| `tests/unit/cache/test_cached_diff_ops.py` | `LRUCache` | 2 |

### `orchestrator.review.test_runner` → `orchestrator.git.testing.test_runner`
| File | Import | Task |
|------|--------|------|
| `api/deps.py` | `TestRunner` | 5 |
| `api/routers/runs.py` | `TestRunner` | 5 |
| `api/app.py` (line 502, lazy) | `TestRunner` | 5 |
| `api/routers/review.py` | `TestRunResult, TestRunner` | 5 |
| `tests/integration/test_review_test_api.py` (2 lazy) | `TestRunner` | 5 |
| `tests/integration/test_review_test_runner.py` (2 lazy) | `TestRunner` | 5 |
| `tests/integration/test_merge_readiness.py` | `TestRunResult` | 5 |

### `orchestrator.repos.*` → `orchestrator.git.repos.*`
| File | Import | Task |
|------|--------|------|
| `mcp/tools.py` | `get_repo, list_branches, list_repos, RepoNotFoundError` | 3 |
| `cli/repos.py` | `get_repo, list_branches, list_repos, RepoNotFoundError` | 3 |
| `api/routers/repos.py` | `branch_count, get_repo, list_branches, list_repos` | 3 |
| `api/errors.py` | `RepoNotFoundError` | 3 |
| **`tests/unit/repos/test_discovery.py`** | `RepoNotFoundError, branch_count, get_repo, list_branches, list_repos, match_branches` | **3 (MISSING)** |

### `orchestrator.git.diff_ops` → `orchestrator.git.diff.diff_ops`
| File | Import | Task |
|------|--------|------|
| `git/cached_diff_ops.py` | `CommitInfo, ModifiedFile, get_branch_diff, ...` | 6 (internal) |
| `tests/unit/test_diff_ops.py` | diff functions | 6 |

### `orchestrator.git.cached_diff_ops` → `orchestrator.git.diff.cached_diff_ops`
| File | Import | Task |
|------|--------|------|
| `api/routers/review.py` | `CachedDiffOps, DiffOps, GitDiffOps` | 6 |
| `tests/unit/cache/test_cached_diff_ops.py` | `CachedDiffOps` | 6 |

### `orchestrator.git.branch_ops` → `orchestrator.git.ops.branch_ops`
| File | Import | Task |
|------|--------|------|
| `api/routers/review.py` | `get_branch_status, revert_back_merge` | 7 |
| `api/routers/runs.py` (3 inline) | `get_branch_status, BackMergeResult, back_merge, merge_back` | 7 |
| `tests/integration/test_branch_ops.py` | `back_merge, get_branch_status, merge_back` | 7 |

### `orchestrator.git.conflict_ops` → `orchestrator.git.ops.conflict_ops`
| File | Import | Task |
|------|--------|------|
| `api/routers/review.py` | `BlockResolution, get_conflict_blocks, get_conflict_files, resolve_conflict` | 7 |
| `tests/unit/test_conflict_ops.py` | `parse_conflict_blocks, ...` | 7 |

### `orchestrator.git.prune_ops` → `orchestrator.git.ops.prune_ops`
| File | Import | Task |
|------|--------|------|
| `api/routers/review.py` | `FileSelectionEntry, apply_prune, compute_selection_preview, prune_hunks, prune_lines, revert_file` | 7 |
| `tests/unit/test_prune_ops.py` | `Hunk, preview_prune, ...` | 7 |

---

## Hardening Actions Summary

| # | Severity | Issue | Hardening Action |
|---|----------|-------|-----------------|
| 1 | **BLOCKING** | `git/diff_models.py` not present in current codebase | Add preflight check at step start; document that Step 0 must complete before Step 2 |
| 2 | **HIGH** | `tests/unit/repos/test_discovery.py` missing from Task 3 consumer list | Add to Task 3 update list: `from orchestrator.repos import ...` → `from orchestrator.git.repos import ...` |
| 3 | **MEDIUM** | Task 7 `git/ops/__init__.py` missing exports: `sync_branch_to_worktree`, `parse_conflict_blocks`, `mark_all_resolved`, `preview_prune`, `Hunk`, `FileDiffSection`, `PruneStats` | Read source files before writing `__init__.py`; enumerate all public symbols |
| 4 | LOW | Two classes named `BranchNotFoundError` at different paths (`git.errors` vs `git.repos.errors`) | Document the distinction in `git/repos/errors.py` docstring; no code change needed |
| 5 | LOW | Task 4's "OLD" import path assumes Phase 0 already ran | Add note: "OLD path is post-Phase-0 state; do not apply if Phase 0 incomplete" |

---

## Component Wiring Assessment

This step is purely structural (file moves + import path updates). No new components, protocols, adapters, or handlers are introduced. There is no wiring gap to check. The existing code paths continue to work through the same logical interfaces — only the physical file locations change.
