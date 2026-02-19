# Step 3 Plan: Implement Failed-Run Recovery API (FAILED-RUN-RECOVERY — Backend)

## Purpose

Add a first-class recovery mechanism that lets a user roll a FAILED run back to a chosen task and resume execution from that point. Currently, `FAILED` is a terminal state with no outbound transitions; the only recovery path is direct SQL manipulation, which is not viable for non-technical users. This step introduces `POST /api/runs/{id}/recover`, which resets task/step state, restores the git worktree to the correct commit, and transitions the run to `PAUSED` so it can be resumed normally.

## Prerequisites

- None (independent of Steps 1–2)

## Functional Contract

### Inputs

- `POST /api/runs/{run_id}/recover`
- Request body (`RecoverRequest`):
  - `target_task_id` (string, required) — the task to roll back to and restart
  - `additional_attempts` (integer, optional, default 1) — how many additional attempts to grant the target task
  - `agent_type` (string, optional) — override the agent type for the restarted task
  - `agent_config` (object, optional) — override agent configuration
  - `preserve_checklist` (boolean, optional, default `false`) — if `true`, downstream task checklist item statuses are preserved; otherwise reset to `open`

### Outputs

- `RecoverResponse` — updated run summary with new status `PAUSED` and `pause_reason = "recovered"`
- Side effects:
  - Target task: `status → BUILDING`, `max_attempts` incremented by `additional_attempts`, new attempt record created
  - Downstream tasks: `status → PENDING`, attempt records cleared, checklist items reset to `open` (unless `preserve_checklist=true`)
  - Affected steps: `completed → false`
  - Worktree: `git checkout {end_commit}` using the target task's last attempt `end_commit` (falls back to run `source_branch` HEAD if no `end_commit` available)
  - Run: `status → PAUSED`, `completed_at` cleared, `current_step_index` updated, `pause_reason = "recovered"`

### Errors

- `404 Not Found` — run does not exist, or `target_task_id` does not belong to the specified run
- `409 Conflict` — run is not in `FAILED` status (COMPLETED recovery is explicitly out of scope and deferred; any non-FAILED status returns 409)
- `422 Unprocessable Entity` — invalid request body (missing `target_task_id`, invalid types)
- `500 Internal Server Error` — git checkout fails (e.g., worktree missing, merge conflicts); error is surfaced to the caller with a descriptive message

## Tasks

1. Add `RecoverRequest` and `RecoverResponse` schemas to `src/orchestrator/api/schemas/runs.py`
2. Add `WorkflowService.recover_run(run_id, target_task_id, additional_attempts, agent_type, agent_config, preserve_checklist)` async method to `src/orchestrator/workflow/service.py` implementing the 8-step recovery logic
3. Add `POST /api/runs/{id}/recover` route to `src/orchestrator/api/routers/runs.py` calling `service.recover_run()`
4. Write integration test: create a run in FAILED state with known task structure; POST to recover; assert run is PAUSED, target task is BUILDING, downstream tasks are PENDING, checklist items are open (and a second test with `preserve_checklist=true`)

## Verification

### Auto-Verify

- [ ] `pytest tests/integration/ -k "recover"` passes
- [ ] `POST /api/runs/{id}/recover` route exists in the OpenAPI schema
- [ ] `RecoverRequest` and `RecoverResponse` are importable from `api/schemas/runs.py`
- [ ] 409 is returned when run status is not FAILED (test coverage)

### Manual Verify

- [ ] Create a run, force it to FAILED in the DB, call `POST /api/runs/{id}/recover` with a valid `target_task_id`; confirm run transitions to PAUSED
- [ ] Confirm git worktree is checked out to the target task's `end_commit`
- [ ] Call `POST /api/runs/{id}/resume` after recovery; confirm execution resumes from the target task

## Context & References

- Bug report: `docs/bugs/FAILED-RUN-RECOVERY.md` — Proposed Design and Recovery Logic
- Architecture: `docs/bug-removal/architecture.md` — "Modified Components: service.py, routers/runs.py"
- Clarification: recovery is FAILED-only; COMPLETED run support is deferred to a follow-up
- Clarification: `preserve_checklist` defaults to `false` (reset to open); `true` preserves prior builder self-reports
- Dependent step: Step 4 (recovery UI) requires this endpoint to exist
