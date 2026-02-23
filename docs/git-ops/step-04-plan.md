# Step 04 Plan: Backend Prune Endpoints

## Purpose

Implement the backend API for pruning (selectively removing) unwanted changes from the run worktree. Prune operations allow users to remove entire files, specific hunks, or individual lines from the run branch before merging. Each prune operation creates a dedicated commit on the run branch for auditability.

## Prerequisites

- **Step 1** — Backend diff endpoints must exist so prune operations can reference diff content and validate selections against the current diff state.
- Existing `src/orchestrator/git/branch_ops.py` provides the `_run_git()` pattern.
- Existing `src/orchestrator/workflow/events.py` provides the event system.

## Functional Contract

### Inputs

- `POST /api/runs/{id}/prune/preview` — Body: `PruneSelection { files: list[FilePrune], scope: str }` where `FilePrune { path: str, mode: "file"|"hunk"|"line", hunks: list[int] | None, lines: list[LineRange] | None }`
- `POST /api/runs/{id}/prune/apply` — Body: same `PruneSelection` schema
- `POST /api/runs/{id}/revert-file` — Body: `{ file_path: str }`

### Outputs

- `POST /prune/preview` → `PrunePreviewResponse { resulting_diff: str, files_affected: int, hunks_removed: int, lines_removed: int }`
- `POST /prune/apply` → `PruneApplyResponse { commit_sha: str, files_affected: int, hunks_removed: int, lines_removed: int, event_id: str }`
- `POST /revert-file` → `{ commit_sha: str, file_path: str, reverted_to: str }`
- Prune-apply creates a new commit on the run branch with message `"prune: remove selected changes"`
- `PRUNE_APPLIED` event logged via event system

### Errors

- `404 Not Found` — Run does not exist
- `409 Conflict` — Run has no active worktree; or worktree has uncommitted changes (dirty state)
- `422 Unprocessable Entity` — Invalid prune selection (e.g., hunk index out of range, file not in diff, line range invalid)
- `400 Bad Request` — Prune selection results in empty diff (nothing to prune)
- `500 Internal Server Error` — `git apply --reverse` failure (patch doesn't apply cleanly)

## Tasks

1. Create `src/orchestrator/git/prune_ops.py` with functions: `preview_prune()`, `apply_prune()`, `revert_file()`
2. Implement file-level prune via `git checkout <base_ref> -- <file>` for full file revert
3. Implement hunk-level prune by constructing reverse patches and applying via `git apply --reverse`
4. Implement line-level prune by constructing selective reverse patches for specific line ranges
5. Create `PruneSelection`, `PrunePreviewResponse`, `PruneApplyResponse` schemas in `schemas/review.py`
6. Add `PRUNE_APPLIED` event type to `src/orchestrator/workflow/events.py`
7. Add prune endpoints to `src/orchestrator/api/routers/review.py`: `POST /prune/preview`, `POST /prune/apply`, `POST /revert-file`
8. Write unit tests for prune operations (`tests/unit/test_prune_ops.py`) — file-level, hunk-level, line-level
9. Write integration tests for prune API endpoints (`tests/integration/test_review_api.py` — prune portion)

## Verification

### Auto-Verify

- [ ] `uv run pytest tests/unit/test_prune_ops.py -v` — all tests pass
- [ ] `uv run pytest tests/integration/test_review_api.py -v -k prune` — prune integration tests pass
- [ ] `uv run pyright src/orchestrator/git/prune_ops.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/git/prune_ops.py` — no lint errors

### Manual Verify

- [ ] File-level prune: reverting a file restores it to base-branch state and creates a commit
- [ ] Hunk-level prune: removing a specific hunk leaves other hunks in the file intact
- [ ] Line-level prune: removing specific lines within a hunk preserves surrounding lines
- [ ] Preview returns accurate summary without modifying the worktree
- [ ] Prune-apply creates a dedicated commit with descriptive message
- [ ] `PRUNE_APPLIED` event is recorded in the event log

## Context & References

- `src/orchestrator/git/branch_ops.py` — `_run_git()` pattern and git subprocess execution
- `src/orchestrator/workflow/events.py` — event types and event logging
- `tests/integration/test_branch_ops.py` — integration test patterns with real git repos
- `docs/git-ops/architecture.md` — prune_ops specification
