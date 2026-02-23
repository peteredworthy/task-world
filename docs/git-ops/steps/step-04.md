# Step 4: Backend Prune Endpoints

Implement the backend API for pruning (selectively removing) unwanted changes from the run worktree. Prune operations allow users to remove entire files, specific hunks, or individual lines from the run branch before merging. Each prune operation creates a dedicated commit on the run branch for auditability.

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — Prune mode allows selecting files, hunks, and lines for removal with preview modal and apply confirmation. Prune operations are recorded in run events and visible in activity timeline.

**Functionality to Produce**:
- `POST /api/runs/{id}/prune/preview` endpoint returning preview of resulting state after pruning
- `POST /api/runs/{id}/prune/apply` endpoint applying prune selections and creating a commit
- `POST /api/runs/{id}/revert-file` endpoint reverting a file to base-branch state
- Prune logic supporting file-level, hunk-level, and line-level granularity
- `PRUNE_APPLIED` event type logged on prune operations
- Pydantic schemas for prune request/response

**Final Verification Criteria**:
- File-level prune restores a file to base-branch state
- Hunk-level prune removes specific hunks while preserving others
- Line-level prune removes specific lines within a hunk
- Preview returns accurate summary without modifying the worktree
- Each prune-apply creates a dedicated commit
- `PRUNE_APPLIED` event is logged
- All tests pass

---

## Task 1: Create Prune Schemas

**Description**: Create the Pydantic schemas for prune API requests and responses.

**Implementation Plan (Do These Steps)**

- [ ] Add prune schemas to `src/orchestrator/api/schemas/review.py`:

```python
class LineRange(BaseModel):
    start: int
    end: int

class FilePrune(BaseModel):
    path: str
    mode: str  # "file" | "hunk" | "line"
    hunks: list[int] | None = None
    lines: list[LineRange] | None = None

class PruneSelection(BaseModel):
    files: list[FilePrune]
    scope: str

class PrunePreviewResponse(BaseModel):
    resulting_diff: str
    files_affected: int
    hunks_removed: int
    lines_removed: int

class PruneApplyResponse(BaseModel):
    commit_sha: str
    files_affected: int
    hunks_removed: int
    lines_removed: int
    event_id: str
```

**References**
- `docs/git-ops/step-04-plan.md` — Task 5
- `docs/git-ops/architecture.md` — prune schemas

**Functionality (Expected Outcomes)**
- [ ] All prune schemas are defined and importable
- [ ] Schemas validate correctly for valid and invalid inputs

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/schemas/review.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/api/schemas/review.py` — no lint errors

---

## Task 2: Create prune_ops.py with File-Level Prune

**Description**: Implement the core prune operations module, starting with file-level prune (the simplest case).

**Implementation Plan (Do These Steps)**

File-level prune is the simplest operation: restore a file to its base-branch state using `git checkout <base_ref> -- <file>`.

- [ ] Create `src/orchestrator/git/prune_ops.py` with:

```python
async def revert_file(worktree_path: str, file_path: str, base_ref: str) -> str:
    """Revert a single file to its base-branch state. Returns commit SHA."""

async def preview_prune(worktree_path: str, selections: list, base_ref: str) -> dict:
    """Preview the result of pruning without modifying the worktree."""

async def apply_prune(worktree_path: str, selections: list, base_ref: str) -> dict:
    """Apply prune selections and create a commit. Returns commit info."""
```

- [ ] Implement `revert_file()` using `git checkout <base_ref> -- <file>` followed by `git commit`
- [ ] Implement file-level case in `apply_prune()` by delegating to `revert_file()`

**References**
- `src/orchestrator/git/branch_ops.py` — `_run_git()` pattern
- `docs/git-ops/step-04-plan.md` — Tasks 1, 2

**Functionality (Expected Outcomes)**
- [ ] `revert_file()` restores a file to base-branch state and creates a commit
- [ ] File-level prune in `apply_prune()` works correctly

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/git/prune_ops.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/git/prune_ops.py` — no lint errors

---

## Task 3: Implement Hunk-Level and Line-Level Prune

**Description**: Add hunk-level and line-level prune support to prune_ops.py by constructing reverse patches.

**Implementation Plan (Do These Steps)**

Hunk-level prune constructs a reverse patch for specific hunks and applies it via `git apply --reverse`. Line-level prune constructs selective reverse patches for specific line ranges within hunks.

- [ ] Implement hunk-level prune in `prune_ops.py`:
  - Extract specific hunks from the diff
  - Construct a reverse patch containing only the selected hunks
  - Apply via `git apply --reverse`

- [ ] Implement line-level prune in `prune_ops.py`:
  - Extract specific line ranges within hunks
  - Construct a selective reverse patch for those lines
  - Apply via `git apply --reverse`

- [ ] Implement `preview_prune()` that computes the resulting diff without modifying the worktree (use `git stash` or a temporary work area)

**Dependencies**
- [ ] Task 2 must be complete (prune_ops module exists)

**References**
- `docs/git-ops/step-04-plan.md` — Tasks 3, 4

**Constraints**
- [ ] Prune operations must only modify the run worktree branch, never the target branch

**Functionality (Expected Outcomes)**
- [ ] Hunk-level prune removes specific hunks while preserving other hunks in the file
- [ ] Line-level prune removes specific lines within a hunk while preserving surrounding lines
- [ ] Preview accurately reflects what will change without modifying the worktree

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/git/prune_ops.py` — no type errors

---

## Task 4: Add PRUNE_APPLIED Event and Prune API Endpoints

**Description**: Add the `PRUNE_APPLIED` event type and create the prune API endpoints in the review router.

**Implementation Plan (Do These Steps)**

- [ ] Add `PRUNE_APPLIED` event type to `src/orchestrator/workflow/events.py`
- [ ] Add prune endpoints to `src/orchestrator/api/routers/review.py`:

```python
# POST /api/runs/{run_id}/review/prune/preview
#   Body: PruneSelection
#   Returns: PrunePreviewResponse

# POST /api/runs/{run_id}/review/prune/apply
#   Body: PruneSelection
#   Returns: PruneApplyResponse (logs PRUNE_APPLIED event)

# POST /api/runs/{run_id}/review/revert-file
#   Body: { file_path: str }
#   Returns: { commit_sha, file_path, reverted_to }
```

- [ ] Wire endpoints to `prune_ops` functions
- [ ] Log `PRUNE_APPLIED` event on successful prune-apply

**Dependencies**
- [ ] Tasks 1-3 must be complete

**References**
- `src/orchestrator/workflow/events.py` — event types
- `docs/git-ops/step-04-plan.md` — Tasks 6, 7

**Functionality (Expected Outcomes)**
- [ ] Prune endpoints accept selections and return correct responses
- [ ] `PRUNE_APPLIED` event is logged on successful prune-apply
- [ ] Error responses for invalid selections (422), dirty worktree (409)

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/routers/review.py` — no type errors

---

## Task 5: Write Prune Tests

**Description**: Write unit and integration tests for prune operations.

**Implementation Plan (Do These Steps)**

- [ ] Create `tests/unit/test_prune_ops.py` with tests:
  - `test_revert_file_restores_base_state` — file-level prune
  - `test_prune_hunk_removes_selected_hunk` — hunk-level prune
  - `test_prune_hunk_preserves_other_hunks` — other hunks remain
  - `test_prune_lines_removes_selected_lines` — line-level prune
  - `test_preview_prune_does_not_modify_worktree` — preview is read-only
  - `test_prune_creates_commit` — commit exists after apply

- [ ] Add prune integration tests to `tests/integration/test_review_api.py`:
  - `test_prune_preview_returns_summary` — API preview endpoint
  - `test_prune_apply_creates_commit` — API apply endpoint
  - `test_revert_file_restores_to_base` — API revert endpoint

**Dependencies**
- [ ] Task 4 must be complete (endpoints exist)

**References**
- `tests/integration/test_branch_ops.py` — test patterns with real git repos
- `docs/git-ops/step-04-plan.md` — Tasks 8, 9

**Functionality (Expected Outcomes)**
- [ ] All prune operations tested at unit and integration level
- [ ] Tests use real git repos, no mocking

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_prune_ops.py -v` — all tests pass (verify test count > 0)
- [ ] `uv run pytest tests/integration/test_review_api.py -v -k prune` — prune integration tests pass (verify test count > 0)
