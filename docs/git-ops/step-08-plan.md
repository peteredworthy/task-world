# Step 08 Plan: Backend Conflict Resolution Endpoints

## Purpose

Implement the backend API for detecting, displaying, and resolving merge conflicts in the run worktree. This includes conflict file listing, structured conflict block parsing, per-file resolution (keep ours/theirs/manual), agent-assisted resolution dispatch, back merge enhancement for auto-committing clean merges, and undo (revert) of back merge commits.

## Prerequisites

- **Step 1** — Review router must be mounted and diff endpoints must exist (conflict resolution updates the diff state).
- Existing `src/orchestrator/git/branch_ops.py` provides `back_merge()` which needs enhancement.
- Existing agent executor infrastructure for dispatching agent work.

## Functional Contract

### Inputs

- `GET /api/runs/{id}/review/conflicts` — No additional params
- `POST /api/runs/{id}/review/conflicts/{file_path}/resolve` — Body: `ConflictResolutionRequest { resolutions: list[BlockResolution] }` where `BlockResolution { block_index: int, choice: "ours"|"theirs"|"manual", manual_content: str | None }`
- `POST /api/runs/{id}/review/conflicts/agent-resolve` — Body: `{ agent_type: str | None, agent_config: dict | None }` (None = use run's default agent)
- `POST /api/runs/{id}/back-merge` — Enhanced: auto-commits clean merges, returns conflict details on conflict
- `POST /api/runs/{id}/review/revert-back-merge` — No body (reverts the last back merge commit)

### Outputs

- `GET /conflicts` → `list[ConflictFile]` where `ConflictFile { path: str, status: "unresolved"|"resolved", block_count: int, blocks: list[ConflictBlock] }` and `ConflictBlock { index: int, ours_content: str, theirs_content: str, base_content: str | None }`
- `POST /conflicts/{path}/resolve` → `ConflictResolutionResponse { path: str, status: "resolved", remaining_conflicts: int }`
- `POST /conflicts/agent-resolve` → `{ job_id: str, status: "dispatched" }`
- `POST /back-merge` → Enhanced: `BackMergeResponse { status: "clean"|"conflicts", merge_commit_sha: str | None, conflict_files: list[str], conflict_count: int }`
- `POST /revert-back-merge` → `{ reverted_commit: str, new_head: str }`
- Events logged: `CONFLICT_RESOLVED`, `BACK_MERGE_COMPLETED`, `BACK_MERGE_REVERTED`, `AGENT_FIX_STARTED`, `AGENT_FIX_COMPLETED`

### Errors

- `404 Not Found` — Run does not exist, or file_path not a conflict file
- `409 Conflict` — No active worktree; no merge in progress (for conflict resolution); no back merge to revert; worktree is dirty
- `422 Unprocessable Entity` — Invalid block index; manual resolution missing content; invalid resolution choice
- `400 Bad Request` — File already resolved; trying to resolve a non-conflict file
- `500 Internal Server Error` — Git operation failure

## Tasks

1. Create `src/orchestrator/git/conflict_ops.py` with functions: `get_conflict_files()`, `get_conflict_blocks()`, `resolve_conflict()`, `mark_all_resolved()`
2. Implement conflict marker parser: parse `<<<<<<<`/`=======`/`>>>>>>>` markers into structured `ConflictBlock` objects
3. Implement resolution application: write resolved content for a file, stage it with `git add`
4. Enhance `back_merge()` in `branch_ops.py`: auto-commit clean merges (return merge commit SHA), return conflict file list on conflict (don't abort)
5. Implement `revert_back_merge()`: revert the last merge commit via `git revert --no-edit`
6. Add Pydantic schemas: `ConflictFile`, `ConflictBlock`, `ConflictResolutionRequest`, `ConflictResolutionResponse`
7. Add event types: `CONFLICT_RESOLVED`, `BACK_MERGE_COMPLETED`, `BACK_MERGE_REVERTED`
8. Add endpoints to review router: `GET /conflicts`, `POST /conflicts/{path}/resolve`, `POST /conflicts/agent-resolve`, `POST /revert-back-merge`
9. Write integration tests with real merge conflicts (`tests/integration/test_review_api.py` — conflict portion)

## Verification

### Auto-Verify

- [ ] `uv run pytest tests/unit/test_conflict_ops.py -v` — conflict parsing and resolution unit tests pass
- [ ] `uv run pytest tests/integration/test_review_api.py -v -k conflict` — conflict integration tests pass
- [ ] `uv run pyright src/orchestrator/git/conflict_ops.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/git/conflict_ops.py` — no lint errors

### Manual Verify

- [ ] `GET /conflicts` returns structured conflict blocks for files with merge conflicts
- [ ] Conflict blocks correctly identify ours/theirs content
- [ ] `POST /conflicts/{path}/resolve` with "ours" choice replaces file with ours content, removes conflict markers
- [ ] `POST /conflicts/{path}/resolve` with "theirs" choice replaces file with theirs content
- [ ] `POST /conflicts/{path}/resolve` with "manual" choice writes custom content
- [ ] Enhanced `back_merge` auto-commits clean merges and returns conflict details for conflicted ones
- [ ] `POST /revert-back-merge` reverts the last merge commit cleanly
- [ ] Events are logged for all operations

## Context & References

- `src/orchestrator/git/branch_ops.py` — `back_merge()` to enhance, `_run_git()` pattern
- `src/orchestrator/workflow/events.py` — event type definitions
- `tests/integration/test_branch_ops.py` — test patterns for creating merge conflicts
- `docs/git-ops/clarifications.md` — Q3: user chooses merge strategy; Q6: auto-commit clean merges with undo banner
- `docs/git-ops/architecture.md` — conflict_ops specification
