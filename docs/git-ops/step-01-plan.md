# Step 01 Plan: Backend Diff Endpoints + Branch Status Enhancements

## Purpose

Provide the backend API foundation for the Review & Merge workbench. This step delivers all diff generation, file listing, and commit history endpoints that the frontend will consume to render diffs, file lists, and branch status. It also enhances the existing branch status endpoint with conflict prediction and merge readiness fields.

## Prerequisites

- None — this is the first step with no dependencies on other milestones.
- Existing `src/orchestrator/git/branch_ops.py` provides `get_branch_status()`, `back_merge()`, `merge_back()`.
- Existing `src/orchestrator/api/routers/runs.py` provides run CRUD and branch status endpoints.
- Existing `_run_git()` async subprocess pattern in `branch_ops.py`.

## Functional Contract

### Inputs

- `GET /api/runs/{run_id}/review/diff` — Query params: `scope` (aggregate|commit|task), `ref` (commit SHA or task commit range), `context_lines` (int, default 3)
- `GET /api/runs/{run_id}/review/diff/files` — Query params: `scope` (aggregate|commit|task), `ref` (optional commit SHA or range)
- `GET /api/runs/{run_id}/review/commits` — No additional params (derives base from run's start_commit)
- `GET /api/runs/{run_id}/branch-status` — Enhanced with predicted conflict count, merge readiness fields

### Outputs

- `GET /review/diff` → `DiffResponse { diff_text: str, scope: str, base_ref: str, head_ref: str, file_count: int }`
- `GET /review/diff/files` → `list[DiffFileEntry]` where `DiffFileEntry { path: str, status: str (added|modified|deleted|renamed), additions: int, deletions: int, tasks: list[str] }`
- `GET /review/commits` → `list[CommitEntry]` where `CommitEntry { sha: str, short_sha: str, message: str, author: str, timestamp: datetime, badges: list[str] }`
- `GET /branch-status` → Enhanced `BranchStatusResponse` with additional fields: `predicted_conflict_count: int`, `merge_readiness: MergeReadinessSnapshot`

### Errors

- `404 Not Found` — Run does not exist
- `409 Conflict` — Run has no active worktree (worktree was removed or never created)
- `422 Unprocessable Entity` — Invalid scope value or ref parameter
- `500 Internal Server Error` — Git subprocess failure (e.g., corrupted repo)

## Tasks

1. Create `src/orchestrator/git/diff_ops.py` with functions: `get_branch_diff()`, `get_commit_diff()`, `get_task_diff()`, `get_modified_files()`, `get_commit_log()`
2. Create `src/orchestrator/review/models.py` with Pydantic domain models: `DiffResult`, `ModifiedFile`, `CommitInfo`
3. Create `src/orchestrator/api/schemas/review.py` with API response schemas: `DiffResponse`, `DiffFileEntry`, `CommitEntry`
4. Create `src/orchestrator/api/routers/review.py` with endpoints: `GET /diff`, `GET /diff/files`, `GET /commits`
5. Enhance `BranchStatusResponse` in existing schemas with `predicted_conflict_count` and `merge_readiness` fields
6. Enhance `get_branch_status()` in `branch_ops.py` to compute predicted conflict count
7. Mount review router in `src/orchestrator/api/app.py`
8. Write unit tests for diff generation logic (`tests/unit/test_diff_ops.py`)
9. Write integration tests for API endpoints (`tests/integration/test_review_api.py` — diff/files/commits portion)

## Verification

### Auto-Verify

- [ ] `uv run pytest tests/unit/test_diff_ops.py -v` — all tests pass
- [ ] `uv run pytest tests/integration/test_review_api.py -v -k diff` — integration tests for diff endpoints pass
- [ ] `uv run pyright src/orchestrator/git/diff_ops.py src/orchestrator/api/routers/review.py src/orchestrator/api/schemas/review.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/git/diff_ops.py src/orchestrator/api/routers/review.py` — no lint errors

### Manual Verify

- [ ] Verify `GET /review/diff` returns valid unified diff text for a run with committed changes
- [ ] Verify `GET /review/diff/files` returns correct file list with accurate addition/deletion counts
- [ ] Verify `GET /review/commits` returns commit history in reverse chronological order
- [ ] Verify enhanced branch status includes predicted conflict count

## Context & References

- `src/orchestrator/git/branch_ops.py` — existing git operations and `_run_git()` pattern
- `src/orchestrator/api/routers/runs.py` — existing run API endpoints
- `src/orchestrator/api/schemas/runs.py` — existing `BranchStatusResponse`
- `tests/integration/test_branch_ops.py` — integration test patterns for git operations
- `docs/git-ops/architecture.md` — full architecture spec for diff_ops, review router, schemas
