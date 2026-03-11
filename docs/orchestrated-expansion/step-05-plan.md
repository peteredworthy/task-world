# Step Plan: API Endpoint + Integration Tests (M2 Final)

## Purpose

Expose the expansion engine via a REST endpoint and write the full integration test suite. This step completes Milestone 2 by connecting all the engine logic to the API layer and verifying the end-to-end behavior of every expansion type, budget scenario, and error case through integration tests.

## Prerequisites

- **Step 3 complete** — `add_subtask` engine logic and service wrapper functional.
- **Step 4 complete** — `add_peer_task`, `add_next_step`, and human approval mode functional.

## Functional Contract

### Inputs

`POST /api/runs/{run_id}/tasks/{task_id}/expand`:
- Path: `run_id: str`, `task_id: str`
- Body: `ExpansionRequest` (validated by Pydantic)
- Auth: same as other task endpoints (no additional auth required)

`POST /api/runs/{run_id}/tasks/{task_id}/expand/approve`:
- Path: `run_id: str`, `task_id: str`
- Body: `{ "action": "approve" | "reject" }`

### Outputs

`POST .../expand` success:
- `200 OK` with `ExpansionResponse`:
  - `status: "created"` (or `"pending_approval"` if `require_human_approval=True`)
  - `expansion_type`: echoes request type
  - `created_task_id`: set for `add_subtask`, `add_peer_task`; null for `add_next_step`
  - `created_step_id`: set for `add_next_step`; null for subtask/peer
  - `created_task_ids`: list of task IDs for `add_next_step`; null otherwise
  - `total_expansions_used`: updated run total
  - `budget_remaining`: dict with remaining capacity for each limit type

`POST .../expand/approve` success:
- `200 OK` with `ExpansionResponse` (status `"created"` on approve; `{ "status": "rejected" }` on reject)

### Error Cases

| Condition | HTTP Status |
|-----------|-------------|
| `ExpansionBudgetError` | 429 with JSON body: `{ "detail": "...", "limit_type": "..." }` |
| `ExpansionPhaseError` | 409 with JSON body: `{ "detail": "..." }` |
| Task not found | 404 |
| Run not found | 404 |
| `request.tasks` empty for `add_next_step` | 422 (Pydantic validation) |
| Invalid `type` value | 422 (Pydantic validation) |
| Approve/reject with no pending approval | 404 |

## Tasks

1. **`src/orchestrator/api/routers/tasks.py`**: Add `expand_task` route:
   - `@router.post("/{run_id}/tasks/{task_id}/expand")`
   - Validate request body (Pydantic does this automatically)
   - Call `service.expand_task(run_id, task_id, request)`
   - Map `ExpansionBudgetError` → 429, `ExpansionPhaseError` → 409, not-found → 404

2. **`src/orchestrator/api/routers/tasks.py`**: Add `approve_expansion` route:
   - `@router.post("/{run_id}/tasks/{task_id}/expand/approve")`
   - Call `service.approve_expansion(run_id, task_id, action)`

3. **`src/orchestrator/api/error_handlers.py`** (or inline): Register exception handlers for `ExpansionBudgetError` and `ExpansionPhaseError` that produce the correct HTTP responses.

4. **`tests/integration/test_expansion.py`**: Full integration test suite:
   - `add_subtask` blocking: verify parent transitions to `FAN_OUT_RUNNING`, child task created with correct fields
   - `add_subtask` non-blocking: child created, parent still `BUILDING`
   - `add_peer_task`: peer task in current step, parent unaffected
   - `add_next_step`: step inserted at correct position, existing step `order_index` values shifted correctly
   - Budget exhaustion (total): 6th expansion with `max_total_expansions=5` returns 429
   - Budget exhaustion (per-type): subtask limit, peer limit, inserted steps limit — each returns 429 with correct `limit_type`
   - Phase check: expanding a `VERIFYING` task returns 409
   - Provenance: `TaskExpanded` event in activity feed includes `justification`, `requesting_task_id`, expansion type
   - Human approval: expansion with `require_human_approval=True` returns `pending_approval`; approve triggers expansion; reject cancels it
   - Task not in run: returns 404
   - `add_next_step` with empty tasks: returns 422

5. **Verify `ExpansionResponse` shape** in integration tests: assert all fields present and correctly typed.

## Verification Approach

### Auto-Verify

- `uv run pytest tests/integration/test_expansion.py -v` — all tests pass
- `uv run pytest tests/integration/ -v` — no regressions in other integration tests
- `uv run pyright src/orchestrator/api/routers/tasks.py` — no type errors

### Manual Verification

- Use `curl` or a REST client to call `POST .../expand` with each type and confirm response shape
- Confirm 429 response body includes both `detail` message and `limit_type` field to aid agent debugging
- Confirm the approval endpoint is correctly ordered after the expand endpoint in the router (no route shadowing)

## Context & References

- Plan: `docs/orchestrated-expansion/plan.md` — Step 5 specification
- Architecture: `docs/orchestrated-expansion/architecture.md` — router definition, error mapping table
- Existing router patterns: `src/orchestrator/api/routers/tasks.py` (submit, complete-verification endpoints)
- Clarification Q4: Human approval mode fully implemented
