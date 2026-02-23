# Step 1: Backend Diff Endpoints + Branch Status Enhancements

Provide the backend API foundation for the Review & Merge workbench. This step delivers all diff generation, file listing, and commit history endpoints that the frontend will consume. It also enhances the existing branch status endpoint with conflict prediction and merge readiness fields.

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — Backend API endpoints for diff generation, merge simulation, prune operations, conflict details/resolution, test execution, and agent actions.

**Functionality to Produce**:
- `GET /api/runs/{id}/review/diff` endpoint returning unified diff text (aggregate, per-commit, per-task scopes)
- `GET /api/runs/{id}/review/diff/files` endpoint returning modified file list with change stats
- `GET /api/runs/{id}/review/commits` endpoint returning commit history for the run branch
- Enhanced `GET /api/runs/{id}/branch-status` with predicted conflict count and merge readiness fields
- Pydantic domain models and API response schemas for all review data
- Review router mounted in the FastAPI app

**Final Verification Criteria**:
- All diff endpoints return correct data for a run with committed changes
- Unit tests for diff generation logic pass
- Integration tests for API endpoints pass
- Type checking and linting pass on all new files

---

## Task 1: Create Review Domain Models

**Description**: Create the Pydantic domain models that represent diff results, modified files, and commit information in the review domain layer.

**Implementation Plan (Do These Steps)**

These models form the data contract between the git layer and the API layer. Creating them first allows subsequent tasks to type-check correctly.

- [ ] Create `src/orchestrator/review/__init__.py` (empty package init)
- [ ] Create `src/orchestrator/review/models.py` with domain models:

```python
# src/orchestrator/review/models.py
from pydantic import BaseModel
from datetime import datetime

class DiffResult(BaseModel):
    diff_text: str
    scope: str  # "aggregate" | "commit" | "task"
    base_ref: str
    head_ref: str
    file_count: int

class ModifiedFile(BaseModel):
    path: str
    status: str  # "added" | "modified" | "deleted" | "renamed"
    additions: int
    deletions: int
    tasks: list[str]

class CommitInfo(BaseModel):
    sha: str
    short_sha: str
    message: str
    author: str
    timestamp: datetime
    badges: list[str]
```

**References**
- `docs/git-ops/architecture.md` — domain model specifications
- `docs/git-ops/step-01-plan.md` — Task 2

**Functionality (Expected Outcomes)**
- [ ] `src/orchestrator/review/models.py` exists with `DiffResult`, `ModifiedFile`, `CommitInfo` models
- [ ] Models are importable and pass type checking

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/review/models.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/review/models.py` — no lint errors
- [ ] `uv run python -c "from orchestrator.review.models import DiffResult, ModifiedFile, CommitInfo; print('OK')"` — imports succeed

---

## Task 2: Create diff_ops.py Git Operations

**Description**: Implement the core diff generation functions that use git subprocess calls to produce diffs, file listings, and commit logs.

**Implementation Plan (Do These Steps)**

These functions follow the existing `_run_git()` async subprocess pattern from `branch_ops.py`. Each function calls git commands and parses the output into domain model objects.

- [ ] Create `src/orchestrator/git/diff_ops.py` with functions:

```python
# Key functions to implement:
async def get_branch_diff(worktree_path: str, base_ref: str, head_ref: str, context_lines: int = 3) -> str:
    """Return unified diff text for the full branch range."""

async def get_commit_diff(worktree_path: str, commit_sha: str, context_lines: int = 3) -> str:
    """Return unified diff text for a single commit."""

async def get_task_diff(worktree_path: str, start_commit: str, end_commit: str, context_lines: int = 3) -> str:
    """Return unified diff text for a task's commit range."""

async def get_modified_files(worktree_path: str, base_ref: str, head_ref: str) -> list[dict]:
    """Return list of changed files with stats (+/- lines, status)."""

async def get_commit_log(worktree_path: str, base_ref: str) -> list[dict]:
    """Return commit history from base to HEAD in reverse chronological order."""
```

- [ ] Use `asyncio.create_subprocess_exec` for git calls, following the `_run_git()` pattern in `branch_ops.py`
- [ ] Parse `git diff --numstat` output for file statistics
- [ ] Parse `git log --format=...` output for commit entries

**Dependencies**
- [ ] Task 1 must be complete (domain models exist)

**References**
- `src/orchestrator/git/branch_ops.py` — `_run_git()` pattern and git subprocess execution
- `docs/git-ops/architecture.md` — diff_ops specification
- `docs/git-ops/step-01-plan.md` — Task 1

**Functionality (Expected Outcomes)**
- [ ] `get_branch_diff()` returns unified diff text for a commit range
- [ ] `get_commit_diff()` returns unified diff for a single commit
- [ ] `get_task_diff()` returns unified diff for a commit range
- [ ] `get_modified_files()` returns file list with additions/deletions/status
- [ ] `get_commit_log()` returns commit entries in reverse chronological order

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/git/diff_ops.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/git/diff_ops.py` — no lint errors

---

## Task 3: Create Review API Schemas

**Description**: Create the Pydantic request/response schemas for all review API endpoints (diff, files, commits).

**Implementation Plan (Do These Steps)**

API schemas are separate from domain models to maintain the boundary between internal representation and external API contract.

- [ ] Create `src/orchestrator/api/schemas/review.py` with response schemas:

```python
# src/orchestrator/api/schemas/review.py
from pydantic import BaseModel
from datetime import datetime

class DiffResponse(BaseModel):
    diff_text: str
    scope: str
    base_ref: str
    head_ref: str
    file_count: int

class DiffFileEntry(BaseModel):
    path: str
    status: str  # "added" | "modified" | "deleted" | "renamed"
    additions: int
    deletions: int
    tasks: list[str]

class CommitEntry(BaseModel):
    sha: str
    short_sha: str
    message: str
    author: str
    timestamp: datetime
    badges: list[str]
```

**References**
- `src/orchestrator/api/schemas/runs.py` — existing API schema patterns
- `docs/git-ops/architecture.md` — API schema specifications
- `docs/git-ops/step-01-plan.md` — Task 3

**Functionality (Expected Outcomes)**
- [ ] All review response schemas are defined and importable
- [ ] Schemas match the API contract specified in the architecture doc

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/schemas/review.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/api/schemas/review.py` — no lint errors

---

## Task 4: Create Review API Router with Diff Endpoints

**Description**: Create the review API router with endpoints for diff retrieval, file listing, and commit history. Mount it in the FastAPI app.

**Implementation Plan (Do These Steps)**

The review router is mounted at `/api/runs/{run_id}/review/` and provides all diff-related endpoints. It validates that the run exists and has an active worktree before processing requests.

- [ ] Create `src/orchestrator/api/routers/review.py` with endpoints:

```python
# Endpoints to implement:
# GET /api/runs/{run_id}/review/diff
#   Query params: scope (aggregate|commit|task), ref (optional), context_lines (int, default 3)
#   Returns: DiffResponse

# GET /api/runs/{run_id}/review/diff/files
#   Query params: scope (aggregate|commit|task), ref (optional)
#   Returns: list[DiffFileEntry]

# GET /api/runs/{run_id}/review/commits
#   Returns: list[CommitEntry]
```

- [ ] Add run existence and worktree validation (404 if run not found, 409 if no worktree)
- [ ] Wire endpoints to `diff_ops` functions
- [ ] Mount the review router in `src/orchestrator/api/app.py`

**Dependencies**
- [ ] Tasks 1-3 must be complete (models, diff_ops, schemas)

**References**
- `src/orchestrator/api/routers/runs.py` — existing router patterns
- `src/orchestrator/api/app.py` — router mounting
- `docs/git-ops/step-01-plan.md` — Tasks 4, 7

**Functionality (Expected Outcomes)**
- [ ] `GET /api/runs/{id}/review/diff` returns unified diff text
- [ ] `GET /api/runs/{id}/review/diff/files` returns file list with change stats
- [ ] `GET /api/runs/{id}/review/commits` returns commit history
- [ ] 404 returned for non-existent runs
- [ ] 409 returned for runs without worktrees

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/routers/review.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/api/routers/review.py` — no lint errors

---

## Task 5: Enhance Branch Status with Merge Readiness Fields

**Description**: Add predicted conflict count and merge readiness fields to the existing branch status endpoint and response schema.

**Implementation Plan (Do These Steps)**

- [ ] Add `predicted_conflict_count: int` and `merge_readiness` fields to `BranchStatusResponse` in `src/orchestrator/api/schemas/runs.py`
- [ ] Enhance `get_branch_status()` in `src/orchestrator/git/branch_ops.py` to compute predicted conflict count using `git merge-tree` or `git merge --no-commit --no-ff` dry-run
- [ ] Ensure existing branch status tests still pass after the enhancement

**References**
- `src/orchestrator/api/schemas/runs.py` — existing `BranchStatusResponse`
- `src/orchestrator/git/branch_ops.py` — existing `get_branch_status()`
- `docs/git-ops/step-01-plan.md` — Tasks 5, 6

**Constraints**
- [ ] Do not break existing branch status behavior — new fields should be additive
- [ ] Keep backward compatibility with existing consumers of the branch status endpoint

**Functionality (Expected Outcomes)**
- [ ] Branch status response includes `predicted_conflict_count` field
- [ ] Predicted conflict count reflects the actual number of files that would conflict on merge

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/ -k branch_status -v` — existing branch status tests still pass
- [ ] `uv run pyright src/orchestrator/git/branch_ops.py src/orchestrator/api/schemas/runs.py` — no type errors

---

## Task 6: Write Unit Tests for Diff Operations

**Description**: Write unit tests for all diff generation functions using real git repos via `tmp_path` fixtures.

**Implementation Plan (Do These Steps)**

Tests create real git repositories with known commit states and verify that diff functions return correct output.

- [ ] Create `tests/unit/test_diff_ops.py` with tests:

```python
# Tests to implement:
# - test_get_branch_diff_returns_unified_diff: create repo with changes, verify diff text
# - test_get_commit_diff_for_single_commit: verify diff for one commit
# - test_get_task_diff_for_commit_range: verify diff for a range
# - test_get_modified_files_shows_correct_stats: verify file list with +/- counts
# - test_get_modified_files_detects_add_modify_delete: verify status detection
# - test_get_commit_log_reverse_chronological: verify commit ordering
# - test_get_commit_log_includes_all_fields: verify SHA, message, author, timestamp
```

- [ ] Use `tmp_path` to create git repos with known commit states
- [ ] Follow existing test patterns from `tests/integration/test_branch_ops.py`

**Dependencies**
- [ ] Task 2 must be complete (diff_ops module exists)

**References**
- `tests/integration/test_branch_ops.py` — test patterns for git operations
- `docs/git-ops/step-01-plan.md` — Task 8

**Functionality (Expected Outcomes)**
- [ ] All diff operation functions are tested with real git repos
- [ ] Tests cover correct output format, edge cases (empty diff, no commits)

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_diff_ops.py -v` — all tests pass (verify test count > 0)

---

## Task 7: Write Integration Tests for Review API Endpoints

**Description**: Write integration tests for the review API endpoints using a running FastAPI app with real git repos.

**Implementation Plan (Do These Steps)**

Integration tests create runs with actual worktrees, make commits, and verify that the API returns correct data.

- [ ] Create `tests/integration/test_review_api.py` with tests for diff endpoints:

```python
# Tests to implement:
# - test_get_diff_returns_aggregate_diff: verify full branch diff
# - test_get_diff_with_commit_scope: verify per-commit diff
# - test_get_diff_files_returns_file_list: verify file list with stats
# - test_get_commits_returns_history: verify commit entries
# - test_diff_endpoint_404_for_missing_run: verify 404
# - test_diff_endpoint_409_for_no_worktree: verify 409
```

- [ ] Use `AsyncClient` with the real FastAPI app
- [ ] Create test runs with actual git worktrees and known commits
- [ ] Follow patterns from `tests/integration/test_branch_ops.py`

**Dependencies**
- [ ] Task 4 must be complete (review router mounted)

**References**
- `tests/integration/test_branch_ops.py` — integration test patterns
- `docs/git-ops/step-01-plan.md` — Task 9

**Functionality (Expected Outcomes)**
- [ ] Integration tests verify end-to-end API behavior with real data
- [ ] Error cases (404, 409) are tested

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/integration/test_review_api.py -v -k diff` — all diff integration tests pass (verify test count > 0)
