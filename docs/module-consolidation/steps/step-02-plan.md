# Step 2: Absorb cache/ + review/ + repos/ → git/

Consolidate three small single-consumer modules (`cache/`, `review/`, `repos/`) into `git/` as sub-packages. Each sub-package is created, populated, all consumers updated, and the old module deleted — leaving the codebase fully importable after every task.

## Intent Verification
**Original Intent**: Phase 2 of module consolidation (plan.md §Phase 2): absorb `cache/`, `review/`, `repos/` into `git/` to reduce the top-level module count from 19 to 16 and group git-infrastructure code together.

**Functionality to Produce**:
- `git/diff/` sub-package containing `lru_cache.py`, `models.py`, `diff_ops.py`, `cached_diff_ops.py`
- `git/repos/` sub-package containing `models.py`, `discovery.py`, `errors.py`
- `git/testing/` sub-package containing `test_runner.py`
- `git/ops/` sub-package containing `branch_ops.py`, `conflict_ops.py`, `prune_ops.py`
- `cache/`, `review/`, `repos/` top-level directories deleted entirely
- `git/__init__.py` updated to re-export all public symbols from sub-packages
- All import paths updated throughout `src/`, `tests/`, `scripts/`

**Final Verification Criteria**:
- `uv run pytest tests/unit/ tests/integration/ -x` passes with zero failures
- `grep -r "from orchestrator\.cache" src/ tests/` returns zero results
- `grep -r "from orchestrator\.review" src/ tests/` returns zero results
- `grep -r "from orchestrator\.repos" src/ tests/` returns zero results
- `src/orchestrator/cache/`, `src/orchestrator/review/`, `src/orchestrator/repos/` do not exist
- `uv run pre-commit run --all-files` passes

---

## Task 1: Scaffold git/ sub-packages

**Description**: Create the four empty `__init__.py` files that establish the new sub-package namespace. Nothing else changes; the codebase remains identical after this task.

**Implementation Plan (Do These Steps)**:

- [ ] Create `src/orchestrator/git/diff/__init__.py`:
```python
"""Diff models, operations, and caching for git."""
```

- [ ] Create `src/orchestrator/git/repos/__init__.py`:
```python
"""Repository discovery for git."""
```

- [ ] Create `src/orchestrator/git/testing/__init__.py`:
```python
"""Test runner for auto-verify commands."""
```

- [ ] Create `src/orchestrator/git/ops/__init__.py`:
```python
"""Branch, conflict, and prune operations for git."""
```

**Functionality (Expected Outcomes)**:
- [ ] `python -c "from orchestrator.git import diff, repos, testing, ops"` succeeds (empty packages importable)

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `python -c "from orchestrator.git import diff, repos, testing, ops"` — exits with code 0
- [ ] `git status` shows exactly 4 new files, no other changes

---

## Task 2: Absorb cache/ → git/diff/lru_cache.py

**Description**: Move `cache/lru_cache.py` into `git/diff/lru_cache.py`, update all importers, and delete the `cache/` directory. After this task, `orchestrator.cache` no longer exists.

**Implementation Plan (Do These Steps)**:

- [ ] Copy `src/orchestrator/cache/lru_cache.py` content verbatim into `src/orchestrator/git/diff/lru_cache.py` (no import changes needed — the file has no intra-package imports)

- [ ] Update `src/orchestrator/git/diff/__init__.py` to export the cache types:
```python
"""Diff models, operations, and caching for git."""

from orchestrator.git.diff.lru_cache import Cache, LRUCache

__all__ = ["Cache", "LRUCache"]
```

- [ ] Update `src/orchestrator/git/cached_diff_ops.py`: change the cache import:
```python
# OLD
from orchestrator.cache.lru_cache import Cache
# NEW
from orchestrator.git.diff.lru_cache import Cache
```

- [ ] Update `src/orchestrator/api/routers/review.py`: change the cache import:
```python
# OLD
from orchestrator.cache.lru_cache import LRUCache
# NEW
from orchestrator.git.diff.lru_cache import LRUCache
```

- [ ] Update `tests/unit/cache/test_lru_cache.py`: change the import:
```python
# OLD
from orchestrator.cache.lru_cache import LRUCache
# NEW
from orchestrator.git.diff.lru_cache import LRUCache
```

- [ ] Update `tests/unit/cache/test_cached_diff_ops.py`: change the import:
```python
# OLD
from orchestrator.cache.lru_cache import LRUCache
# NEW
from orchestrator.git.diff.lru_cache import LRUCache
```

- [ ] Delete `src/orchestrator/cache/` directory and all its contents (including `__pycache__/`)

**Functionality (Expected Outcomes)**:
- [ ] `from orchestrator.git.diff.lru_cache import Cache, LRUCache` succeeds
- [ ] `from orchestrator.cache` raises `ModuleNotFoundError`

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/cache/ -v` — all tests pass
- [ ] `grep -r "from orchestrator\.cache" src/ tests/` — zero results
- [ ] `test -d src/orchestrator/cache` exits with code 1 (directory absent)

---

## Task 3: Absorb repos/ → git/repos/

**Description**: Copy all three `repos/` files into `git/repos/`, update internal imports within those files, update all external consumers, and delete the `repos/` directory.

**Implementation Plan (Do These Steps)**:

- [ ] Create `src/orchestrator/git/repos/models.py` — copy content verbatim from `src/orchestrator/repos/models.py` (no intra-package imports to update)

- [ ] Create `src/orchestrator/git/repos/errors.py` — copy content verbatim from `src/orchestrator/repos/errors.py` (no intra-package imports to update)

- [ ] Create `src/orchestrator/git/repos/discovery.py` — copy content from `src/orchestrator/repos/discovery.py`, updating the two internal imports:
```python
# OLD
from orchestrator.repos.errors import RepoNotFoundError
from orchestrator.repos.models import BranchInfo, RepoInfo
# NEW
from orchestrator.git.repos.errors import RepoNotFoundError
from orchestrator.git.repos.models import BranchInfo, RepoInfo
```

- [ ] Update `src/orchestrator/git/repos/__init__.py`:
```python
"""Repository discovery for git."""

from orchestrator.git.repos.discovery import (
    branch_count,
    get_repo,
    list_branches,
    list_repos,
    match_branches,
)
from orchestrator.git.repos.errors import BranchNotFoundError, RepoNotFoundError
from orchestrator.git.repos.models import BranchInfo, RepoInfo

__all__ = [
    "BranchInfo",
    "BranchNotFoundError",
    "RepoInfo",
    "RepoNotFoundError",
    "branch_count",
    "get_repo",
    "list_branches",
    "list_repos",
    "match_branches",
]
```

- [ ] Update `src/orchestrator/mcp/tools.py` — change repos imports:
```python
# OLD
from orchestrator.repos.discovery import get_repo, list_branches, list_repos
from orchestrator.repos.errors import RepoNotFoundError
# NEW
from orchestrator.git.repos.discovery import get_repo, list_branches, list_repos
from orchestrator.git.repos.errors import RepoNotFoundError
```

- [ ] Update `src/orchestrator/cli/repos.py` — change repos imports:
```python
# OLD
from orchestrator.repos.discovery import get_repo, list_branches, list_repos
from orchestrator.repos.errors import RepoNotFoundError
# NEW
from orchestrator.git.repos.discovery import get_repo, list_branches, list_repos
from orchestrator.git.repos.errors import RepoNotFoundError
```

- [ ] Update `src/orchestrator/api/errors.py` — change repos import:
```python
# OLD
from orchestrator.repos.errors import RepoNotFoundError
# NEW
from orchestrator.git.repos.errors import RepoNotFoundError
```

- [ ] Update `src/orchestrator/api/routers/repos.py` — change repos import:
```python
# OLD
from orchestrator.repos import branch_count, get_repo, list_branches, list_repos
# NEW
from orchestrator.git.repos import branch_count, get_repo, list_branches, list_repos
```

- [ ] Delete `src/orchestrator/repos/` directory and all its contents

**Functionality (Expected Outcomes)**:
- [ ] `from orchestrator.git.repos import get_repo, list_repos, RepoNotFoundError` succeeds
- [ ] `from orchestrator.repos` raises `ModuleNotFoundError`

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -k "repo" -v` — passes (or matches zero tests without error)
- [ ] `grep -r "from orchestrator\.repos" src/ tests/` — zero results
- [ ] `test -d src/orchestrator/repos` exits with code 1 (directory absent)

---

## Task 4: Consolidate diff models → git/diff/models.py

**Description**: After Phase 0, `git/diff_models.py` holds `CommitInfo`, `FileStatus`, `ModifiedFile` (moved from `review.models`). `review/models.py` still holds `DiffResult`, `DiffScope`. Create `git/diff/models.py` combining both, update `git/diff_ops.py` to import from the new location, and remove `git/diff_models.py`.

Verify the Phase 0 state before starting: `git/diff_models.py` must exist. If it does not exist (Phase 0 not yet complete), stop and do not proceed.

**Implementation Plan (Do These Steps)**:

- [ ] Inspect `src/orchestrator/git/diff_models.py` to confirm it contains `CommitInfo`, `FileStatus`, `ModifiedFile`. Inspect `src/orchestrator/review/models.py` for remaining types.

- [ ] Create `src/orchestrator/git/diff/models.py` merging both files. It should contain all diff-related types:
```python
"""Diff and commit models for the git module."""

# (content: DiffScope, DiffResult, FileStatus, ModifiedFile, CommitInfo —
#  drawn from git/diff_models.py and review/models.py)
```
The exact content is the union of `git/diff_models.py` and `review/models.py`. Do not omit any type from either file.

- [ ] Update `src/orchestrator/git/diff/__init__.py` to export the model types (add them to the existing exports from Task 2):
```python
"""Diff models, operations, and caching for git."""

from orchestrator.git.diff.lru_cache import Cache, LRUCache
from orchestrator.git.diff.models import (
    CommitInfo,
    DiffResult,
    DiffScope,
    FileStatus,
    ModifiedFile,
)

__all__ = [
    "Cache",
    "CommitInfo",
    "DiffResult",
    "DiffScope",
    "FileStatus",
    "LRUCache",
    "ModifiedFile",
]
```

- [ ] Update `src/orchestrator/git/diff_ops.py` — change the models import:
```python
# OLD (post-Phase 0)
from orchestrator.git.diff_models import CommitInfo, FileStatus, ModifiedFile
# NEW
from orchestrator.git.diff.models import CommitInfo, FileStatus, ModifiedFile
```

- [ ] Update `tests/unit/test_diff_ops.py` — change the FileStatus import:
```python
# OLD
from orchestrator.review.models import FileStatus
# NEW
from orchestrator.git.diff.models import FileStatus
```

- [ ] Delete `src/orchestrator/git/diff_models.py`

**Constraints**:
- Do not modify `review/models.py` yet — it will be deleted in Task 5.
- Do not modify `review/__init__.py` yet.
- `git/diff_ops.py` and `git/cached_diff_ops.py` remain at the `git/` root until Task 6.

**Functionality (Expected Outcomes)**:
- [ ] `from orchestrator.git.diff.models import CommitInfo, FileStatus, ModifiedFile, DiffResult, DiffScope` succeeds
- [ ] `from orchestrator.git.diff_models` raises `ModuleNotFoundError`

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/test_diff_ops.py -v` — all tests pass
- [ ] `test -f src/orchestrator/git/diff_models.py` exits with code 1 (file absent)
- [ ] `grep -r "from orchestrator\.git\.diff_models" src/ tests/` — zero results

---

## Task 5: Absorb review/test_runner.py → git/testing/ and delete review/

**Description**: Move `review/test_runner.py` into `git/testing/`, update all consumers that import from `orchestrator.review.test_runner`, and delete the `review/` directory. `review/models.py` content is already absorbed (Task 4), so `review/` has no remaining consumers.

**Implementation Plan (Do These Steps)**:

- [ ] Create `src/orchestrator/git/testing/test_runner.py` — copy content verbatim from `src/orchestrator/review/test_runner.py` (no intra-package imports to update; `test_runner.py` has no `orchestrator.*` imports)

- [ ] Update `src/orchestrator/git/testing/__init__.py`:
```python
"""Test runner for auto-verify commands."""

from orchestrator.git.testing.test_runner import TestRunResult, TestRunner, TestSummary

__all__ = ["TestRunResult", "TestRunner", "TestSummary"]
```

- [ ] Update `src/orchestrator/api/app.py` — change the TestRunner import (lazy import inside a function at startup):
```python
# OLD
from orchestrator.review.test_runner import TestRunner
# NEW
from orchestrator.git.testing.test_runner import TestRunner
```

- [ ] Update `src/orchestrator/api/deps.py` — change the TestRunner import:
```python
# OLD
from orchestrator.review.test_runner import TestRunner
# NEW
from orchestrator.git.testing.test_runner import TestRunner
```

- [ ] Update `src/orchestrator/api/routers/runs.py` — change the TestRunner import (lazy import inside a function):
```python
# OLD
from orchestrator.review.test_runner import TestRunner
# NEW
from orchestrator.git.testing.test_runner import TestRunner
```

- [ ] Update `src/orchestrator/api/routers/review.py` — change the review.test_runner import:
```python
# OLD
from orchestrator.review.test_runner import TestRunResult, TestRunner
# NEW
from orchestrator.git.testing.test_runner import TestRunResult, TestRunner
```

- [ ] Update test files that import from `orchestrator.review.test_runner`:
  - `tests/integration/test_review_test_api.py` — two lazy imports inside test functions
  - `tests/integration/test_review_test_runner.py` — two lazy imports inside test functions
  - `tests/integration/test_merge_readiness.py` — one import of `TestRunResult`

- [ ] Verify no remaining imports from `review.models` anywhere in `src/` or `tests/`:
  ```bash
  grep -r "from orchestrator\.review" src/ tests/
  ```
  Must return zero results before deleting.

- [ ] Delete `src/orchestrator/review/` directory and all its contents

**Functionality (Expected Outcomes)**:
- [ ] `from orchestrator.git.testing import TestRunner, TestRunResult, TestSummary` succeeds
- [ ] `from orchestrator.review` raises `ModuleNotFoundError`

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/integration/test_review_test_runner.py tests/integration/test_review_test_api.py -v` — all tests pass
- [ ] `grep -r "from orchestrator\.review" src/ tests/` — zero results
- [ ] `test -d src/orchestrator/review` exits with code 1 (directory absent)

---

## Task 6: Move diff_ops.py and cached_diff_ops.py into git/diff/

**Description**: Relocate `git/diff_ops.py` and `git/cached_diff_ops.py` from the `git/` root into the `git/diff/` sub-package. Update their internal imports and all external consumers. After this task, the `git/diff/` sub-package contains all four diff files.

**Implementation Plan (Do These Steps)**:

- [ ] Create `src/orchestrator/git/diff/diff_ops.py` — copy content from `src/orchestrator/git/diff_ops.py`, updating the models import:
```python
# OLD (post-Task 4)
from orchestrator.git.diff.models import CommitInfo, FileStatus, ModifiedFile
# (same — no change needed if already updated in Task 4)
```
  Also confirm the `git.errors` import remains unchanged:
```python
from orchestrator.git.errors import GitCommandError  # unchanged — absolute path works from sub-package
```

- [ ] Create `src/orchestrator/git/diff/cached_diff_ops.py` — copy content from `src/orchestrator/git/cached_diff_ops.py`, updating the two internal imports:
```python
# OLD
from orchestrator.cache.lru_cache import Cache  # already updated to git.diff.lru_cache in Task 2
from orchestrator.git.diff_ops import (         # must update to git.diff.diff_ops
    CommitInfo, ModifiedFile,
    get_branch_diff, get_commit_diff,
    get_commit_log, get_modified_files,
    get_task_diff,
)
# NEW
from orchestrator.git.diff.lru_cache import Cache
from orchestrator.git.diff.diff_ops import (
    CommitInfo, ModifiedFile,
    get_branch_diff, get_commit_diff,
    get_commit_log, get_modified_files,
    get_task_diff,
)
```

- [ ] Update `src/orchestrator/git/diff/__init__.py` to also export diff operation types:
```python
"""Diff models, operations, and caching for git."""

from orchestrator.git.diff.cached_diff_ops import CachedDiffOps, DiffOps, GitDiffOps
from orchestrator.git.diff.diff_ops import (
    get_branch_diff,
    get_commit_diff,
    get_commit_log,
    get_modified_files,
    get_task_diff,
)
from orchestrator.git.diff.lru_cache import Cache, LRUCache
from orchestrator.git.diff.models import (
    CommitInfo,
    DiffResult,
    DiffScope,
    FileStatus,
    ModifiedFile,
)

__all__ = [
    "Cache",
    "CachedDiffOps",
    "CommitInfo",
    "DiffOps",
    "DiffResult",
    "DiffScope",
    "FileStatus",
    "GitDiffOps",
    "LRUCache",
    "ModifiedFile",
    "get_branch_diff",
    "get_commit_diff",
    "get_commit_log",
    "get_modified_files",
    "get_task_diff",
]
```

- [ ] Update `src/orchestrator/api/routers/review.py` — change the cached_diff_ops import:
```python
# OLD
from orchestrator.git.cached_diff_ops import CachedDiffOps, DiffOps, GitDiffOps
# NEW
from orchestrator.git.diff.cached_diff_ops import CachedDiffOps, DiffOps, GitDiffOps
```

- [ ] Update `tests/unit/cache/test_cached_diff_ops.py` — change the import:
```python
# OLD
from orchestrator.git.cached_diff_ops import CachedDiffOps
# NEW
from orchestrator.git.diff.cached_diff_ops import CachedDiffOps
```

- [ ] Update `tests/unit/test_diff_ops.py` — change the diff_ops import:
```python
# OLD
from orchestrator.git.diff_ops import (...)
# NEW
from orchestrator.git.diff.diff_ops import (...)
```

- [ ] Delete `src/orchestrator/git/diff_ops.py` and `src/orchestrator/git/cached_diff_ops.py`

**Functionality (Expected Outcomes)**:
- [ ] `from orchestrator.git.diff import CachedDiffOps, DiffOps, GitDiffOps, get_branch_diff` succeeds
- [ ] `from orchestrator.git.diff_ops` and `from orchestrator.git.cached_diff_ops` raise `ModuleNotFoundError`

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/test_diff_ops.py tests/unit/cache/test_cached_diff_ops.py -v` — all tests pass
- [ ] `grep -r "from orchestrator\.git\.diff_ops\|from orchestrator\.git\.cached_diff_ops" src/ tests/` — zero results
- [ ] `test -f src/orchestrator/git/diff_ops.py` exits with code 1 (file absent)
- [ ] `test -f src/orchestrator/git/cached_diff_ops.py` exits with code 1 (file absent)

---

## Task 7: Create git/ops/ and relocate branch/conflict/prune ops

**Description**: Move `git/branch_ops.py`, `git/conflict_ops.py`, and `git/prune_ops.py` from the `git/` root into the `git/ops/` sub-package. Update `git/__init__.py` to re-export from the new locations, and update all direct consumers.

**Implementation Plan (Do These Steps)**:

- [ ] Create `src/orchestrator/git/ops/branch_ops.py` — copy content verbatim from `src/orchestrator/git/branch_ops.py`. The internal import `from orchestrator.git.errors import ...` uses an absolute path and remains valid from the sub-package.

- [ ] Create `src/orchestrator/git/ops/conflict_ops.py` — copy content verbatim from `src/orchestrator/git/conflict_ops.py`. Same absolute-import reasoning applies.

- [ ] Create `src/orchestrator/git/ops/prune_ops.py` — copy content verbatim from `src/orchestrator/git/prune_ops.py`.

- [ ] Update `src/orchestrator/git/ops/__init__.py`:
```python
"""Branch, conflict, and prune operations for git."""

from orchestrator.git.ops.branch_ops import (
    BackMergeResult,
    BranchStatus,
    RevertBackMergeResult,
    back_merge,
    get_branch_status,
    merge_back,
    revert_back_merge,
)
from orchestrator.git.ops.conflict_ops import (
    BlockResolution,
    ConflictBlock,
    apply_resolution,
    get_conflict_blocks,
    get_conflict_files,
    resolve_conflict,
)
from orchestrator.git.ops.prune_ops import (
    FileSelectionEntry,
    apply_prune,
    compute_selection_preview,
    prune_hunks,
    prune_lines,
    revert_file,
)

__all__ = [
    "BackMergeResult",
    "BlockResolution",
    "BranchStatus",
    "ConflictBlock",
    "FileSelectionEntry",
    "RevertBackMergeResult",
    "apply_prune",
    "apply_resolution",
    "back_merge",
    "compute_selection_preview",
    "get_branch_status",
    "get_conflict_blocks",
    "get_conflict_files",
    "merge_back",
    "prune_hunks",
    "prune_lines",
    "resolve_conflict",
    "revert_back_merge",
    "revert_file",
]
```
  Note: Verify the exact exported names by reading `git/branch_ops.py`, `git/conflict_ops.py`, `git/prune_ops.py` — the above is a best-effort list. Match the actual exports exactly.

- [ ] Update `src/orchestrator/git/__init__.py` to import from the sub-packages instead of the root files. The new `__init__.py` should use `git.ops.*` paths. Keep existing exports for `errors`, `project_init`, `worktree`:
```python
"""Git integration for orchestrator."""

from orchestrator.git.errors import (
    BranchError,
    BranchNotFoundError,
    GitError,
    MergeConflictError,
    WorktreeError,
)
from orchestrator.git.ops.branch_ops import (
    BackMergeResult,
    BranchStatus,
    RevertBackMergeResult,
    back_merge,
    get_branch_status,
    merge_back,
    revert_back_merge,
)
from orchestrator.git.project_init import InitializedProject, init_project
from orchestrator.git.worktree import WorktreeInfo, WorktreeManager

__all__ = [
    "BackMergeResult",
    "BranchError",
    "BranchNotFoundError",
    "BranchStatus",
    "GitError",
    "InitializedProject",
    "MergeConflictError",
    "RevertBackMergeResult",
    "WorktreeError",
    "WorktreeInfo",
    "WorktreeManager",
    "back_merge",
    "get_branch_status",
    "init_project",
    "merge_back",
    "revert_back_merge",
]
```

- [ ] Update `src/orchestrator/api/routers/review.py` — change the branch/conflict/prune imports:
```python
# OLD
from orchestrator.git.branch_ops import get_branch_status, revert_back_merge
from orchestrator.git.conflict_ops import (...)
from orchestrator.git.prune_ops import (...)
# NEW
from orchestrator.git.ops.branch_ops import get_branch_status, revert_back_merge
from orchestrator.git.ops.conflict_ops import (...)
from orchestrator.git.ops.prune_ops import (...)
```

- [ ] Update `src/orchestrator/api/routers/runs.py` — change the three inline branch_ops imports (inside function bodies):
```python
# OLD (three locations)
from orchestrator.git.branch_ops import get_branch_status
from orchestrator.git.branch_ops import BackMergeResult, back_merge
from orchestrator.git.branch_ops import merge_back
# NEW
from orchestrator.git.ops.branch_ops import get_branch_status
from orchestrator.git.ops.branch_ops import BackMergeResult, back_merge
from orchestrator.git.ops.branch_ops import merge_back
```

- [ ] Update test files:
  - `tests/integration/test_branch_ops.py`: `from orchestrator.git.branch_ops import ...` → `from orchestrator.git.ops.branch_ops import ...`
  - `tests/unit/test_prune_ops.py`: `from orchestrator.git.prune_ops import ...` → `from orchestrator.git.ops.prune_ops import ...`
  - `tests/unit/test_conflict_ops.py`: `from orchestrator.git.conflict_ops import ...` → `from orchestrator.git.ops.conflict_ops import ...`

- [ ] Delete `src/orchestrator/git/branch_ops.py`, `src/orchestrator/git/conflict_ops.py`, `src/orchestrator/git/prune_ops.py`

**Functionality (Expected Outcomes)**:
- [ ] `from orchestrator.git.ops import back_merge, get_branch_status` succeeds
- [ ] `from orchestrator.git import back_merge, get_branch_status` succeeds (via `git/__init__.py`)
- [ ] `from orchestrator.git.branch_ops` raises `ModuleNotFoundError`

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/integration/test_branch_ops.py tests/unit/test_prune_ops.py tests/unit/test_conflict_ops.py -v` — all tests pass
- [ ] `grep -r "from orchestrator\.git\.branch_ops\|from orchestrator\.git\.conflict_ops\|from orchestrator\.git\.prune_ops" src/ tests/` — zero results
- [ ] `test -f src/orchestrator/git/branch_ops.py` exits with code 1

---

## Task 8: Full verification and cleanup

**Description**: Run the complete test suite, verify all old import paths are gone, and confirm the git/ sub-package structure is correct with no stubs or re-export shims.

**Implementation Plan (Do These Steps)**:

- [ ] Run the full unit test suite:
```bash
uv run pytest tests/unit/ -v
```

- [ ] Run the full integration test suite:
```bash
uv run pytest tests/integration/ -v
```

- [ ] Verify zero references to deleted modules:
```bash
grep -r "from orchestrator\.cache" src/ tests/
grep -r "from orchestrator\.review" src/ tests/
grep -r "from orchestrator\.repos" src/ tests/
```

- [ ] Verify zero references to deleted git root-level files:
```bash
grep -r "from orchestrator\.git\.diff_ops\b" src/ tests/
grep -r "from orchestrator\.git\.cached_diff_ops\b" src/ tests/
grep -r "from orchestrator\.git\.branch_ops\b" src/ tests/
grep -r "from orchestrator\.git\.conflict_ops\b" src/ tests/
grep -r "from orchestrator\.git\.prune_ops\b" src/ tests/
grep -r "from orchestrator\.git\.diff_models\b" src/ tests/
```

- [ ] Verify directories are absent:
```bash
test -d src/orchestrator/cache && echo "FAIL: cache/ still exists"
test -d src/orchestrator/review && echo "FAIL: review/ still exists"
test -d src/orchestrator/repos && echo "FAIL: repos/ still exists"
```

- [ ] Run pre-commit hooks:
```bash
uv run pre-commit run --all-files
```

- [ ] Run frontend tests (no frontend changes expected, but confirm nothing broke):
```bash
cd ui && npx vitest run
```

**Functionality (Expected Outcomes)**:
- [ ] All backend unit and integration tests pass
- [ ] All frontend tests pass
- [ ] Zero grep hits for any old import paths
- [ ] Pre-commit hooks pass
- [ ] `src/orchestrator/` contains no `cache/`, `review/`, `repos/` directories

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -v` exits with code 0
- [ ] All six grep commands above return zero results
- [ ] `uv run pre-commit run --all-files` exits with code 0
