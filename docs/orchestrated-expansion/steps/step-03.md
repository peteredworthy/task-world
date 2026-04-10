# Step 3: Expansion Engine — add_subtask (M2 Core)

Implement `WorkflowEngine.expand_task()` for the `add_subtask` expansion type (blocking and non-blocking), budget enforcement, provenance recording, and the `WorkflowService.expand_task()` wrapper with DB persistence and event emission. Getting the engine pattern right here establishes the foundation for `add_peer_task` and `add_next_step` in Step 4.

## Intent Verification
**Original Intent**: Implement the core `expand_task()` path for `add_subtask`, including phase checks, budget guards, fan-out integration, and service-layer persistence (see `docs/orchestrated-expansion/plan.md` Step 3).
**Functionality to Produce**:
- `ExpansionBudgetError` and `ExpansionPhaseError` exception classes
- `WorkflowEngine.expand_task()` handling `add_subtask` (blocking and non-blocking)
- `WorkflowService.expand_task()` with DB persistence, `RunModel.expansion_count` increment, `TaskExpanded` event emission
- Human approval stub (`require_human_approval=True` returns `pending_approval`)
- Unit tests for budget/phase errors and subtask creation

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_expansion_budget.py tests/unit/test_expansion_subtask.py -v` — all tests pass
- `uv run pyright src/orchestrator/workflow/engine.py src/orchestrator/workflow/service.py` — no type errors
- `uv run pytest tests/unit/ -v` — no regressions

---

## Task 1: Define ExpansionBudgetError and ExpansionPhaseError

**Description**: Add the two new exception classes used throughout the expansion engine.

**Implementation Plan (Do These Steps)**
- [ ] Locate the appropriate errors module (e.g., `src/orchestrator/workflow/errors.py` or inline in engine)
- [ ] Add `ExpansionBudgetError(Exception)` with fields: `message: str`, `limit_type: str` (e.g., `"total"`, `"subtask"`, `"peer"`, `"inserted_steps"`)
- [ ] Add `ExpansionPhaseError(Exception)` with field: `message: str`
- [ ] Export both from the module

**Dependencies**
- [ ] Step 1 complete — `ExpansionLimits` and `ExpansionRequest` schemas defined

**References**
- `docs/orchestrated-expansion/architecture.md` — error cases table
- `docs/orchestrated-expansion/step-03-plan.md` — Task 1
- Existing error classes in `src/orchestrator/workflow/errors.py` for pattern reference

**Constraints**
- `limit_type` must be a string that can be returned verbatim in a 429 response body
- Do not modify existing error classes

**Functionality (Expected Outcomes)**
- [ ] `ExpansionBudgetError("msg", "total")` constructs and `raise`s correctly
- [ ] `ExpansionPhaseError("msg")` constructs and `raise`s correctly

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.workflow.errors import ExpansionBudgetError, ExpansionPhaseError; print('OK')"` succeeds

---

## Task 2: Implement expand_task() in WorkflowEngine for add_subtask

**Description**: Add `expand_task()` method to `WorkflowEngine` handling the `add_subtask` type, including all guards and state transitions.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/workflow/engine.py`
- [ ] Add `expand_task(run, task_id, request, expansion_limits)` method
- [ ] Phase check: task must be in `BUILDING` status — raise `ExpansionPhaseError` otherwise
- [ ] Budget check (total): `run.total_expansions >= expansion_limits.max_total_expansions` → raise `ExpansionBudgetError(limit_type="total")`
- [ ] Budget check (per-task subtasks): `task.expansions_requested >= expansion_limits.max_subtasks_per_task` → raise `ExpansionBudgetError(limit_type="subtask")`
- [ ] Nested fan-out guard: if `blocking=True` and task has `parent_task_id` set → raise `ExpansionPhaseError("blocking subtask not allowed for child tasks")`
- [ ] Create child `TaskState` with: `parent_task_id=task_id` (for blocking), `expanded_from_task_id=task_id`, `expansion_justification=request.justification`, `is_expansion=True`
- [ ] For `blocking=True`: call existing `expand_fan_out_task()` to set parent → `FAN_OUT_RUNNING`
- [ ] For `blocking=False`: add child to `run.steps[current_step_index].tasks`; parent stays `BUILDING`
- [ ] Increment `task.expansions_requested += 1` and `run.total_expansions += 1` (only on success)
- [ ] Return `(child_task, None)`

**Dependencies**
- [ ] Task 1 complete (error classes defined)
- [ ] Step 2 complete (DB columns migrated)

**References**
- `docs/orchestrated-expansion/architecture.md` — engine method signature, budget check order
- `docs/orchestrated-expansion/step-03-plan.md` — Task 2
- Existing fan-out: `src/orchestrator/runners/executor.py` `_execute_fan_out`
- Existing engine methods: `expand_fan_out_task()` / `complete_fan_out_parent()` in `engine.py`
- Clarification Q3: `FAN_OUT_RUNNING` agents cannot call expand (not applicable, no guard needed)

**Constraints**
- Call `expand_fan_out_task()` with the same arguments as the static fan-out path
- Counters must only increment on success (after all checks pass)
- Non-blocking subtask must not alter parent task status

**Functionality (Expected Outcomes)**
- [ ] Blocking subtask: child created, parent transitions to `FAN_OUT_RUNNING`
- [ ] Non-blocking subtask: child created, parent remains `BUILDING`
- [ ] Phase check rejects tasks in `VERIFYING` status
- [ ] Budget checks reject when limits exceeded

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/workflow/engine.py` — no type errors

---

## Task 3: Implement expand_task() in WorkflowService

**Description**: Add `WorkflowService.expand_task()` to load the run, call the engine, persist results, and emit events.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/workflow/service.py`
- [ ] Add `expand_task(run_id, task_id, request)` async method
- [ ] Load run from DB; raise `TaskNotFoundError` if task not in run
- [ ] Load `expansion_limits` from run's routine config (use `ExpansionLimits()` defaults if not set)
- [ ] If `require_human_approval=True`: create pending approval record stub, return `ExpansionResponse(status="pending_approval", ...)`
- [ ] Otherwise: call `engine.expand_task(run, task_id, request, expansion_limits)`
- [ ] Persist new `TaskModel` to DB with all expansion fields populated
- [ ] Update `RunModel.expansion_count += 1`
- [ ] Emit `TaskExpanded` event
- [ ] Return `ExpansionResponse(status="created", created_task_id=..., total_expansions_used=..., budget_remaining=...)`

**Dependencies**
- [ ] Task 2 complete (engine method implemented)

**References**
- `docs/orchestrated-expansion/step-03-plan.md` — Task 3
- `docs/orchestrated-expansion/architecture.md` — service layer description
- Existing service methods for DB persistence and event emission patterns

**Constraints**
- Human approval stub in this step just needs to return `pending_approval` — full implementation is in Step 4
- `budget_remaining` dict must include keys for all limit types

**Functionality (Expected Outcomes)**
- [ ] `expand_task()` persists new `TaskModel` with `is_expansion=True`, `expanded_from_task_id`, `expansion_justification`
- [ ] `RunModel.expansion_count` incremented in DB
- [ ] `TaskExpanded` event emitted with correct fields
- [ ] Returns `ExpansionResponse` with `status="created"`

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/workflow/service.py` — no type errors

---

## Task 4: Write Unit Tests for Budget and Phase Errors

**Description**: Create `tests/unit/test_expansion_budget.py` testing all budget and phase error scenarios.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_expansion_budget.py`
- [ ] Test: total budget exhausted (`run.total_expansions >= max_total_expansions`) → `ExpansionBudgetError`
- [ ] Test: per-task subtask limit exhausted → `ExpansionBudgetError` with `limit_type="subtask"`; other tasks can still expand
- [ ] Test: blocking subtask from child task → `ExpansionPhaseError`
- [ ] Test: task in `VERIFYING` status → `ExpansionPhaseError`
- [ ] Test: task in `BUILDING` status → expansion allowed (no error)
- [ ] Run tests to confirm all pass

**Dependencies**
- [ ] Tasks 1–2 complete (engine and error classes defined)

**References**
- `docs/orchestrated-expansion/step-03-plan.md` — Task 4

**Constraints**
- Tests should test the engine directly (unit tests — no DB or HTTP)

**Functionality (Expected Outcomes)**
- [ ] All budget/phase error cases covered
- [ ] Each test asserts on the correct exception type and `limit_type` where applicable

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_expansion_budget.py -v` — all tests pass

---

## Task 5: Write Unit Tests for add_subtask

**Description**: Create `tests/unit/test_expansion_subtask.py` testing subtask creation and state transitions.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_expansion_subtask.py`
- [ ] Test `add_subtask` blocking: child has correct provenance fields; parent transitions to `FAN_OUT_RUNNING`
- [ ] Test `add_subtask` non-blocking: child created; parent remains `BUILDING`
- [ ] Test counters incremented correctly after each expansion

**Dependencies**
- [ ] Task 2 complete (engine method implemented)

**References**
- `docs/orchestrated-expansion/step-03-plan.md` — Task 5

**Constraints**
- Tests operate on `WorkflowEngine` directly without needing a running server

**Functionality (Expected Outcomes)**
- [ ] All subtask creation scenarios covered
- [ ] Provenance fields (`expanded_from_task_id`, `expansion_justification`, `is_expansion`) asserted on child

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_expansion_subtask.py -v` — all tests pass
- [ ] `uv run pytest tests/unit/ -v` — no regressions
