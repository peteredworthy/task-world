# Step 5: API Endpoint + Integration Tests (M2 Final)

Expose the expansion engine via REST endpoints and write the full integration test suite. This step completes Milestone 2 by connecting all engine logic to the API layer and verifying end-to-end behavior of every expansion type, budget scenario, and error case.

## Intent Verification
**Original Intent**: Add `POST .../expand` and `POST .../expand/approve` routes to the tasks router, register exception handlers for expansion errors, and write a comprehensive integration test suite covering all expansion types and error cases (see `docs/orchestrated-expansion/plan.md` Step 5).
**Functionality to Produce**:
- `POST /api/runs/{run_id}/tasks/{task_id}/expand` route returning `ExpansionResponse`
- `POST /api/runs/{run_id}/tasks/{task_id}/expand/approve` route for human approval
- Exception handlers: `ExpansionBudgetError` → 429, `ExpansionPhaseError` → 409
- Integration test suite `tests/integration/test_expansion.py` covering all expansion types, budget exhaustion, phase checks, provenance in activity feed, and human approval flow

**Final Verification Criteria**:
- `uv run pytest tests/integration/test_expansion.py -v` — all tests pass
- `uv run pytest tests/integration/ -v` — no regressions in other integration tests
- `uv run pyright src/orchestrator/api/routers/tasks.py` — no type errors

---

## Task 1: Add expand_task Route to tasks.py

**Description**: Add `POST /{run_id}/tasks/{task_id}/expand` endpoint that calls `WorkflowService.expand_task()` and returns `ExpansionResponse`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/api/routers/tasks.py`
- [ ] Add route: `@router.post("/{run_id}/tasks/{task_id}/expand", response_model=ExpansionResponse)`
- [ ] Validate request body via Pydantic `ExpansionRequest` (automatic)
- [ ] Call `service.expand_task(run_id, task_id, request)` (inject service via dependency)
- [ ] Map errors: `TaskNotFoundError` → 404; `ExpansionBudgetError` → 429; `ExpansionPhaseError` → 409
- [ ] Return `ExpansionResponse` directly on success

**Dependencies**
- [ ] Step 4 complete — `WorkflowService.expand_task()` implemented for all three expansion types

**References**
- `docs/orchestrated-expansion/step-05-plan.md` — Task 1
- `docs/orchestrated-expansion/architecture.md` — router definition, error mapping table
- Existing endpoint patterns: `submit` and `complete-verification` routes in `src/orchestrator/api/routers/tasks.py`

**Constraints**
- Route ordering matters: the `expand/approve` route (Task 2) must be registered before `expand` if both share a common prefix, to avoid route shadowing
- Do not inline error handling if an exception handler registration point exists (Task 3)

**Functionality (Expected Outcomes)**
- [ ] `POST .../expand` with valid `add_subtask` body returns 200 with `ExpansionResponse`
- [ ] `POST .../expand` with invalid type returns 422 (Pydantic validation)
- [ ] `POST .../expand` for nonexistent task/run returns 404

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/routers/tasks.py` — no type errors

---

## Task 2: Add approve_expansion Route to tasks.py

**Description**: Add `POST /{run_id}/tasks/{task_id}/expand/approve` endpoint that calls `WorkflowService.approve_expansion()`.

**Implementation Plan (Do These Steps)**
- [ ] In `src/orchestrator/api/routers/tasks.py`, add route BEFORE the `expand` route to avoid shadowing:
  `@router.post("/{run_id}/tasks/{task_id}/expand/approve")`
- [ ] Accept body: `{ "action": "approve" | "reject" }` — define a small schema or use `Literal`
- [ ] Call `service.approve_expansion(run_id, task_id, action)`
- [ ] Return `ExpansionResponse` (status `"created"` on approve; `{"status": "rejected"}` on reject)
- [ ] Map missing pending approval → 404

**Dependencies**
- [ ] Task 1 complete (expand route added; correct ordering established)
- [ ] Step 4 Task 3 complete — `WorkflowService.approve_expansion()` implemented

**References**
- `docs/orchestrated-expansion/step-05-plan.md` — Task 2
- `docs/orchestrated-expansion/architecture.md` — approval endpoint contract

**Constraints**
- Route must be registered before the `expand` route to prevent the path `/expand/approve` from being captured by `/{task_id}/expand` pattern
- `action` field must only accept `"approve"` or `"reject"` — use `Literal` type

**Functionality (Expected Outcomes)**
- [ ] `POST .../expand/approve` with `action="approve"` triggers stored expansion and returns `status="created"`
- [ ] `POST .../expand/approve` with `action="reject"` returns `status="rejected"`
- [ ] `POST .../expand/approve` when no pending approval exists returns 404

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/routers/tasks.py` — no type errors

---

## Task 3: Register Exception Handlers for Expansion Errors

**Description**: Register `ExpansionBudgetError` and `ExpansionPhaseError` exception handlers that produce correctly-shaped HTTP error responses.

**Implementation Plan (Do These Steps)**
- [ ] Locate the exception handler registration point (likely `src/orchestrator/api/error_handlers.py` or `src/orchestrator/api/app.py`)
- [ ] Add handler for `ExpansionBudgetError`:
  - Status: 429
  - Body: `{ "detail": "<message>", "limit_type": "<limit_type>" }`
- [ ] Add handler for `ExpansionPhaseError`:
  - Status: 409
  - Body: `{ "detail": "<message>" }`
- [ ] Register both handlers with the FastAPI app

**Dependencies**
- [ ] Task 1 complete — routes exist and need the handlers

**References**
- `docs/orchestrated-expansion/step-05-plan.md` — Task 3
- Existing handler registration in `src/orchestrator/api/error_handlers.py` or `app.py` (search for `GateBlockedError` handler for pattern reference)

**Constraints**
- `ExpansionBudgetError` response body MUST include `limit_type` field to aid agent debugging
- Follow existing handler pattern (do not write ad-hoc try/except in the route itself if a centralized handler location exists)

**Functionality (Expected Outcomes)**
- [ ] `ExpansionBudgetError` raised in service → 429 response with `detail` and `limit_type` fields
- [ ] `ExpansionPhaseError` raised in service → 409 response with `detail` field

**Final Verification (Proof of Completion)**
- [ ] Handler registration can be confirmed by importing the app module without error
- [ ] `uv run pyright src/orchestrator/api/` — no type errors

---

## Task 4: Write Full Integration Test Suite

**Description**: Create `tests/integration/test_expansion.py` covering all expansion types, budget exhaustion, phase checks, provenance, and human approval.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/integration/test_expansion.py`
- [ ] Test `add_subtask` blocking: parent transitions to `FAN_OUT_RUNNING`; child created with correct fields
- [ ] Test `add_subtask` non-blocking: child created; parent still `BUILDING`
- [ ] Test `add_peer_task`: peer task in current step; parent unaffected; peer has no `parent_task_id`
- [ ] Test `add_next_step`: step inserted at correct position; existing step `order_index` values shifted correctly; all tasks from `request.tasks` created
- [ ] Test budget exhaustion (total): 6th expansion with `max_total_expansions=5` returns 429
- [ ] Test budget exhaustion (subtask limit): returns 429 with `limit_type="subtask"`
- [ ] Test budget exhaustion (peer limit): returns 429 with `limit_type="peer"`
- [ ] Test budget exhaustion (inserted steps limit): returns 429 with `limit_type="inserted_steps"`
- [ ] Test phase check: expanding a `VERIFYING` task returns 409
- [ ] Test provenance: `TaskExpanded` event in activity feed includes `justification`, `requesting_task_id`, expansion type
- [ ] Test human approval: expansion with `require_human_approval=True` returns `pending_approval`; `POST .../expand/approve` with `action="approve"` triggers expansion; `action="reject"` cancels it
- [ ] Test task not in run: returns 404
- [ ] Test `add_next_step` with empty tasks: returns 422

**Dependencies**
- [ ] Tasks 1–3 complete (routes and handlers registered)

**References**
- `docs/orchestrated-expansion/step-05-plan.md` — Task 4
- Existing integration test patterns in `tests/integration/test_api_full_lifecycle.py`

**Constraints**
- Tests must use the HTTP client (not call service/engine directly) — integration tests validate the full API stack
- Each test must be independently runnable (no shared mutable state between tests)

**Functionality (Expected Outcomes)**
- [ ] All test scenarios pass
- [ ] `ExpansionResponse` shape asserted in each success test (all fields present and correctly typed)
- [ ] No regressions in existing integration tests

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/integration/test_expansion.py -v` — all tests pass
- [ ] `uv run pytest tests/integration/ -v` — no regressions
