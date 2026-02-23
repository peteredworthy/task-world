# Step 8: Backend Conflict Resolution Endpoints

Implement the backend API for detecting, displaying, and resolving merge conflicts in the run worktree. This includes conflict file listing, structured conflict block parsing, per-file resolution, agent-assisted resolution dispatch, back merge enhancement, and undo (revert) of back merge commits.

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — Back merge action merges target branch into run branch. Conflict resolver displays conflict blocks with keep-ours/keep-theirs/manual-selection actions per block. "Use Agent to Resolve Conflicts" dispatches agent work scoped to unresolved conflicts.

**Functionality to Produce**:
- `GET /api/runs/{id}/review/conflicts` endpoint returning conflict files with structured blocks
- `POST /api/runs/{id}/review/conflicts/{path}/resolve` endpoint applying per-block resolutions
- `POST /api/runs/{id}/review/conflicts/agent-resolve` endpoint dispatching agent resolution
- Enhanced `POST /api/runs/{id}/back-merge` that auto-commits clean merges and returns conflict details
- `POST /api/runs/{id}/review/revert-back-merge` endpoint for undoing back merge
- Conflict marker parser (ours/theirs/base extraction)
- Event types for all conflict and merge operations

**Final Verification Criteria**:
- Conflict files endpoint returns structured blocks with ours/theirs content
- Resolution endpoint correctly writes resolved content and removes conflict markers
- Back merge auto-commits clean merges and returns conflict details for conflicted ones
- Revert-back-merge successfully reverts merge commits
- All events are logged

---

## Task 1: Create Conflict Operations Module

**Description**: Create the conflict detection, parsing, and resolution module.

**Implementation Plan (Do These Steps)**

- [ ] Create `src/orchestrator/git/conflict_ops.py` with:

```python
async def get_conflict_files(worktree_path: str) -> list[dict]:
    """List files with unresolved merge conflicts."""

def parse_conflict_blocks(file_content: str) -> list[dict]:
    """Parse <<<<<<</=======/>>>>>>> markers into structured blocks."""

async def get_conflict_blocks(worktree_path: str, file_path: str) -> list[dict]:
    """Read a conflict file and return structured conflict blocks."""

async def resolve_conflict(worktree_path: str, file_path: str, resolutions: list[dict]) -> None:
    """Apply per-block resolutions, write file, stage with git add."""

async def mark_all_resolved(worktree_path: str) -> None:
    """Verify no remaining conflict markers, stage remaining files."""
```

- [ ] Implement conflict marker parser for `<<<<<<<`/`=======`/`>>>>>>>` markers
- [ ] Handle three-way merge markers (with `|||||||` base section) where present
- [ ] `get_conflict_files()` uses `git diff --name-only --diff-filter=U` to list unmerged files
- [ ] `resolve_conflict()` writes resolved content and stages with `git add`

**References**
- `src/orchestrator/git/branch_ops.py` — `_run_git()` pattern
- `docs/git-ops/architecture.md` — conflict_ops specification
- `docs/git-ops/step-08-plan.md` — Tasks 1, 2, 3

**Functionality (Expected Outcomes)**
- [ ] Conflict files are correctly identified
- [ ] Conflict markers are parsed into structured blocks with ours/theirs content
- [ ] Resolution writes correct content and stages the file

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/git/conflict_ops.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/git/conflict_ops.py` — no lint errors

---

## Task 2: Enhance back_merge() and Add Revert

**Description**: Enhance the existing `back_merge()` to auto-commit clean merges and return conflict details on conflict. Implement back merge revert.

**Implementation Plan (Do These Steps)**

- [ ] Enhance `back_merge()` in `src/orchestrator/git/branch_ops.py`:
  - On clean merge: auto-commit (no `--abort`), return merge commit SHA
  - On conflict: leave merge-in-progress state (don't abort), return conflict file list
  - Return a response indicating `status: "clean"|"conflicts"` with appropriate details

- [ ] Implement `revert_back_merge()`:
  - Revert the last merge commit via `git revert --no-edit <merge_sha>`
  - Return the reverted commit SHA and new HEAD

**References**
- `src/orchestrator/git/branch_ops.py` — existing `back_merge()` function
- `docs/git-ops/clarifications.md` — Q6: auto-commit clean merges with undo option
- `docs/git-ops/step-08-plan.md` — Tasks 4, 5

**Constraints**
- [ ] Do not break existing back_merge callers — extend return type, don't change existing behavior for callers that don't use new fields

**Side Effects**
- [ ] Existing tests that use back_merge may need updating if the return type changes

**Functionality (Expected Outcomes)**
- [ ] Clean merges auto-commit and return merge commit SHA
- [ ] Conflicted merges leave merge-in-progress state with conflict file list
- [ ] Revert successfully reverts the last merge commit

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/git/branch_ops.py` — no type errors

---

## Task 3: Add Conflict Schemas and Event Types

**Description**: Create Pydantic schemas for conflict API and add event types for conflict/merge operations.

**Implementation Plan (Do These Steps)**

- [ ] Add conflict schemas to `src/orchestrator/api/schemas/review.py`:

```python
class ConflictBlock(BaseModel):
    index: int
    ours_content: str
    theirs_content: str
    base_content: str | None = None

class ConflictFile(BaseModel):
    path: str
    status: str  # "unresolved" | "resolved"
    block_count: int
    blocks: list[ConflictBlock]

class BlockResolution(BaseModel):
    block_index: int
    choice: str  # "ours" | "theirs" | "manual"
    manual_content: str | None = None

class ConflictResolutionRequest(BaseModel):
    resolutions: list[BlockResolution]

class ConflictResolutionResponse(BaseModel):
    path: str
    status: str
    remaining_conflicts: int

class BackMergeResponse(BaseModel):
    status: str  # "clean" | "conflicts"
    merge_commit_sha: str | None = None
    conflict_files: list[str]
    conflict_count: int
```

- [ ] Add event types to `src/orchestrator/workflow/events.py`:
  - `CONFLICT_RESOLVED`
  - `BACK_MERGE_COMPLETED`
  - `BACK_MERGE_REVERTED`

**References**
- `docs/git-ops/step-08-plan.md` — Tasks 6, 7

**Functionality (Expected Outcomes)**
- [ ] All conflict schemas validate correctly
- [ ] Event types are defined

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/schemas/review.py` — no type errors

---

## Task 4: Add Conflict API Endpoints

**Description**: Add conflict resolution endpoints to the review router.

**Implementation Plan (Do These Steps)**

- [ ] Add endpoints to `src/orchestrator/api/routers/review.py`:

```python
# GET /api/runs/{run_id}/review/conflicts
#   Returns: list[ConflictFile]

# POST /api/runs/{run_id}/review/conflicts/{file_path}/resolve
#   Body: ConflictResolutionRequest
#   Returns: ConflictResolutionResponse

# POST /api/runs/{run_id}/review/conflicts/agent-resolve
#   Body: { agent_type: str | None, agent_config: dict | None }
#   Returns: { job_id: str, status: "dispatched" }

# POST /api/runs/{run_id}/review/revert-back-merge
#   Returns: { reverted_commit: str, new_head: str }
```

- [ ] Wire endpoints to `conflict_ops` and `branch_ops` functions
- [ ] Log appropriate events for each operation

**Dependencies**
- [ ] Tasks 1-3 must be complete

**References**
- `docs/git-ops/step-08-plan.md` — Task 8

**Functionality (Expected Outcomes)**
- [ ] Conflict listing, resolution, agent dispatch, and revert endpoints work correctly
- [ ] Events are logged for all operations

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/routers/review.py` — no type errors

---

## Task 5: Write Conflict Tests

**Description**: Write unit and integration tests for conflict operations using real merge conflicts.

**Implementation Plan (Do These Steps)**

- [ ] Create `tests/unit/test_conflict_ops.py`:
  - `test_parse_conflict_blocks_simple` — parse two-way conflict markers
  - `test_parse_conflict_blocks_three_way` — parse three-way markers with base
  - `test_parse_multiple_blocks` — multiple conflict blocks in one file
  - `test_resolve_ours_removes_markers` — "ours" resolution writes ours content
  - `test_resolve_theirs_removes_markers` — "theirs" resolution writes theirs content
  - `test_resolve_manual_writes_custom_content` — "manual" writes provided content

- [ ] Add conflict integration tests to `tests/integration/test_review_api.py`:
  - Set up real merge conflicts in test repos
  - `test_get_conflicts_returns_files` — GET endpoint returns conflict files
  - `test_resolve_conflict_removes_markers` — POST resolve clears conflict
  - `test_back_merge_clean_auto_commits` — clean merge returns commit SHA
  - `test_back_merge_conflicts_returns_file_list` — conflicted merge returns files
  - `test_revert_back_merge` — revert reverses the merge commit

**Dependencies**
- [ ] Task 4 must be complete (endpoints exist)

**References**
- `tests/integration/test_branch_ops.py` — patterns for creating merge conflicts
- `docs/git-ops/step-08-plan.md` — Task 9

**Functionality (Expected Outcomes)**
- [ ] Conflict parsing tested with various marker formats
- [ ] Resolution tested for all choices (ours, theirs, manual)
- [ ] Integration tests use real merge conflicts

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_conflict_ops.py -v` — all tests pass (verify test count > 0)
- [ ] `uv run pytest tests/integration/test_review_api.py -v -k conflict` — conflict integration tests pass (verify test count > 0)
