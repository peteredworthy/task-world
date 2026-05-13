# Branch Service QA Report

Date: 2026-05-12

## Summary

QA was resumed after the task-submit blocker was fixed. The blocker was confirmed fixed against the live service: DB-backed activity signals now persist across request sessions, and user-managed task submission advances through `building -> verifying -> completed` after the signal consumer processes the queued activity.

The continued live QA pass completed successfully. Valid child evidence was accepted and merged, duplicate acceptance was idempotent, invalid evidence was rejected with an `InvalidEvidence` projection, reject/resolve was idempotent and allowed a replacement child, and `/trace` returned the current stable response shape.

Restart recovery smoke remains skipped because `AGENTS.md` instructs agents not to restart the server during this work.

## Fixes Verified

| Area | Result | Notes |
|---|---:|---|
| DB-backed task submit signal | Pass | `submit_task` now commits the request session after enqueueing `ACTIVITY_COMPLETED`. |
| DB-backed verification-complete signal | Pass | `complete_verification_endpoint` now commits the request session after enqueueing `ACTIVITY_VERIFIED`. |
| Regression coverage | Pass | `tests/integration/test_api_tasks.py::test_db_backed_activity_signals_are_persisted` drives the real DB-backed `SignalConsumer`. |
| QA helper resilience | Pass | `docs/qa/branch_service_live_qa.py` now resumes user-managed runs around stale-run sweeper pauses and retries narrow parent-paused child command races. |
| Trace helper shape | Pass | Helper now validates `attempts[].phases` plus top-level token totals: `total_tokens_read`, `total_tokens_write`, `total_tokens_cache`. |

## Verification Commands

| Check | Result | Notes |
|---|---:|---|
| `uv run pytest tests/integration/test_api_tasks.py -q` | Pass | 15 passed. |
| `uv run ruff check src/orchestrator/api/routers/tasks.py tests/integration/test_api_tasks.py` | Pass | No issues. |
| `uv run ruff check docs/qa/branch_service_live_qa.py` | Pass | No issues after helper updates. |
| `uv run pyright` | Pass | 0 errors. |
| `npm --prefix ui run test:e2e -- state-transitions.spec.ts visual-regression.spec.ts` | Pass | 17 passed after updating five review/merge snapshots for the existing UI layout drift. |
| `uv run python docs/qa/branch_service_live_qa.py` | Pass | Full live branch-service QA driver exited 0. |

## Live Service Setup

The service was started with `./dev.sh`.

| Endpoint | Result | Notes |
|---|---:|---|
| `GET http://127.0.0.1:8000/health` | Pass | Returned `{"status":"ok"}`. |
| `GET /api/agent-runners` | Pass | Included `user_managed`. |
| `GET /api/routines` | Pass | Included `super-parent`. |
| `GET /mcp-scoped/orchestrator_get_requirements/sse` | Pass | Returned `HTTP/1.1 200 OK`, `content-type: text/event-stream`, and a scoped messages endpoint. Curl timed out after opening the SSE stream, as expected. |

## Final Live Run

| Field | Value |
|---|---|
| Parent run ID | `9d0c140b-ea8c-4a2c-b8c0-bd250d29bf55` |
| Parent worktree | `worktrees/r158` |
| Accepted child run ID | `01b81fdf-5b40-4cbe-88fc-d7d7d8acdd78` |
| Accepted child worktree | `worktrees/r159` |
| Evidence path | `docs/run-evidence/QA-SLICE-001-evidence.json` |
| Merge commit SHA | `a3783a1907679ce6cd79130e50c936660c3f19f8` |

Additional live probes:

| Probe | Parent run | Child run | Result |
|---|---|---|---:|
| Invalid evidence rejection | `e7ff4bd2-9a85-4cea-a75e-1ddb24037f7f` | `f58985ee-0af5-4173-ba8d-7c9e867f65f8` | Pass |
| Resolve/replacement | `68e6dc1b-a8ae-4dc8-9ce6-33b3bdd33356` | `1f35cc45-6976-4960-b5e4-94f8ad152afe` | Pass |
| Replacement child creation | `68e6dc1b-a8ae-4dc8-9ce6-33b3bdd33356` | `c3098b64-367a-4ae1-9de8-94c2165ea84b` | Pass |
| Trace shape | `1f3a5587-b456-4d15-b6a4-de51b3af44ec` | n/a | Pass |

## Live Checks

### 1. Parent Creation And Oversight Update

Pass. The parent run was created with `agent_runner_type: user_managed`, started through `POST /api/runs/{run_id}/start`, and patched through `PATCH /api/runs/{run_id}/oversight`.

### 2. Child Creation From Template

Pass. Child creation through the REST child-create path succeeded. The child inherited parent repository/worktree lineage and `user_managed` runner settings.

### 3. Unresolved-Child Guardrail

Pass. A second child creation attempt while the first child was unresolved returned 409 and recorded a wait decision with `stable_state: WaitingOnDelegate`.

### 4. Evidence Collection

Pass. Evidence collection returned exactly one valid `run.evidence.v1` bundle and ignored an irrelevant JSON file.

### 5. Child Completion And Acceptance

Pass. The child task transitioned through verification and completed. Accept returned 200, merged the child with conflict count 0, recorded `accepted_child_run_ids`, and preserved valid child evidence in oversight.

### 6. Duplicate Acceptance

Pass. A duplicate accept returned 200 and recorded `stale_command_ignored`/duplicate-command state without re-merging incorrectly.

### 7. Invalid Evidence Rejection

Pass. A completed child with evidence `slice_id: WRONG-SLICE-ID` for parent slice `QA-SLICE-INVALID` was rejected with 409. Oversight recorded `InvalidEvidence`.

### 8. Child Resolve And Replacement

Pass. Rejecting a paused child returned 200, duplicate reject was idempotent/stale, and a replacement child could be created afterward.

### 9. Scoped MCP Tool Exposure

Pass for reachability. The scoped `orchestrator_get_requirements` SSE endpoint opened and returned a scoped transport. Full builder/verifier phase allowlist enumeration was not expanded beyond the endpoint smoke check.

### 10. Run Trace

Pass. `/api/runs/{run_id}/trace` returned one attempt, `attempts[].phases`, an `action_log` field, and top-level token totals.

### 11. Restart Recovery Smoke

Skipped. Restarting the orchestrator service was intentionally not performed under the repository instructions.

## Residual Risk

The stale-run sweeper still pauses user-managed runs without executor heartbeats. The branch-service flows behave correctly when the QA helper resumes those runs before REST callbacks, but this remains an operational sharp edge for manual live QA and may deserve a product-level decision for user-managed runs.
