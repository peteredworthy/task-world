# Step 06 Plan: Backend Test Execution Endpoint

## Purpose

Provide backend support for executing the routine's `auto_verify` commands against the run worktree from the Review & Merge workbench. This allows users to validate that the run's changes (including after pruning) still pass tests before merging.

## Prerequisites

- **Step 1** — Review router must be mounted in the API app so test endpoints can be added to it.
- Existing `src/orchestrator/workflow/events.py` provides the event system for `TEST_RUN_STARTED` / `TEST_RUN_COMPLETED` events.
- Existing auto-verify infrastructure in the codebase provides the pattern for executing commands in a subprocess.

## Functional Contract

### Inputs

- `POST /api/runs/{id}/review/test` — Body: `TestRunRequest { profile: str | None }` (profile is reserved for future use; v1 uses the routine's `auto_verify` commands)
- `GET /api/runs/{id}/review/test/{test_run_id}` — Retrieves result of a specific test run

### Outputs

- `POST /review/test` → `TestRunResponse { test_run_id: str, status: "running" }` (test executes asynchronously)
- `GET /review/test/{test_run_id}` → `TestRunResult { test_run_id: str, status: "running"|"passed"|"failed"|"error", summary: TestSummary | None, log_output: str, duration_ms: int | None, started_at: datetime, completed_at: datetime | None }` where `TestSummary { total: int, passed: int, failed: int, skipped: int }`
- `TEST_RUN_STARTED` and `TEST_RUN_COMPLETED` events logged
- Test commands sourced from the routine's `auto_verify` configuration for the current task/step

### Errors

- `404 Not Found` — Run does not exist, or test_run_id not found
- `409 Conflict` — Run has no active worktree; or another test run is already in progress for this run
- `422 Unprocessable Entity` — No `auto_verify` commands configured in the routine
- `500 Internal Server Error` — Subprocess execution failure (e.g., command not found)

## Tasks

1. Create `src/orchestrator/review/test_runner.py` — async test execution: spawns subprocess in worktree directory using routine's `auto_verify` commands, captures stdout/stderr, computes summary
2. Create `src/orchestrator/review/models.py` additions — `TestRunRequest`, `TestRunResult`, `TestSummary` domain models (if not already created in Step 1)
3. Add schemas to `src/orchestrator/api/schemas/review.py`: `TestRunRequest`, `TestRunResponse`, `TestRunResult`
4. Add `TEST_RUN_STARTED`, `TEST_RUN_COMPLETED` event types to `events.py`
5. Add endpoints to review router: `POST /test`, `GET /test/{test_run_id}`
6. Implement in-memory test run tracking (store active/completed test runs keyed by test_run_id)
7. Write integration tests (`tests/integration/test_review_test_runner.py`) — execute a simple test command in a real worktree, verify results

## Verification

### Auto-Verify

- [ ] `uv run pytest tests/integration/test_review_test_runner.py -v` — integration tests pass
- [ ] `uv run pyright src/orchestrator/review/test_runner.py` — no type errors
- [ ] `uv run ruff check src/orchestrator/review/` — no lint errors

### Manual Verify

- [ ] `POST /review/test` starts a test run and returns a test_run_id immediately
- [ ] `GET /review/test/{id}` returns "running" status while tests execute
- [ ] `GET /review/test/{id}` returns "passed" or "failed" with summary after completion
- [ ] Log output contains the actual stdout/stderr from the test command
- [ ] Test commands are sourced from the routine's auto_verify configuration
- [ ] Events are logged for test start and completion

## Context & References

- Existing auto-verify infrastructure — pattern for subprocess command execution
- `src/orchestrator/workflow/events.py` — event types and logging
- `src/orchestrator/api/routers/review.py` — review router to add endpoints
- `docs/git-ops/architecture.md` — test_runner specification
- `docs/git-ops/clarifications.md` — Q2: test commands come from routine's auto_verify
