# Step 4: Expansion Engine — add_peer_task + add_next_step + Human Approval (M2 Remaining)

Complete the expansion engine with the remaining two expansion types (`add_peer_task` and `add_next_step`) and implement human approval mode. `add_next_step` introduces step index reordering, which requires an atomic DB update. Human approval mode reuses the existing pending action infrastructure.

## Intent Verification
**Original Intent**: Extend `WorkflowEngine.expand_task()` to handle `add_peer_task` and `add_next_step`, implement full human approval mode in `WorkflowService`, and add unit tests for index reordering and peer task creation (see `docs/orchestrated-expansion/plan.md` Step 4).
**Functionality to Produce**:
- `WorkflowEngine.expand_task()` handles `add_peer_task`: creates peer `TaskState` in current step, checks `max_peer_tasks_per_step`
- `WorkflowEngine.expand_task()` handles `add_next_step`: builds `StepState` from `request.tasks`, inserts at `current_step_index + 1`, shifts `order_index` on all later steps atomically
- `WorkflowService.expand_task()` fully implements human approval mode: serializes `ExpansionRequest` as pending action, returns `pending_approval` status
- `WorkflowService.approve_expansion(run_id, task_id, action)`: deserializes pending action, executes or discards based on `action="approve" | "reject"`
- Unit tests: `test_expansion_budget.py` extended with peer/step budget tests; `test_expansion_step_insert.py`; `test_expansion_peer.py`

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_expansion_budget.py tests/unit/test_expansion_step_insert.py tests/unit/test_expansion_peer.py -v` — all tests pass
- `uv run pyright src/orchestrator/workflow/` — no type errors
- `uv run pytest tests/unit/ -v` — no regressions

---

## Task 1: Extend expand_task() for add_peer_task

**Description**: Add handling for `type="add_peer_task"` in `WorkflowEngine.expand_task()`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/workflow/engine.py`
- [ ] In `expand_task()`, add a branch for `type == "add_peer_task"`
- [ ] Phase check: task must be in `BUILDING` status — raise `ExpansionPhaseError` otherwise
- [ ] Budget check (total): `run.total_expansions >= expansion_limits.max_total_expansions` → raise `ExpansionBudgetError(limit_type="total")`
- [ ] Count existing peer tasks in current step (tasks with `expanded_from_task_id` set, excluding self): if count `>= max_peer_tasks_per_step` → raise `ExpansionBudgetError(limit_type="peer")`
- [ ] Create peer `TaskState` with: `expanded_from_task_id=task_id`, no `parent_task_id`, `is_expansion=True`, `expansion_justification=request.justification`
- [ ] Add peer task to `run.steps[current_step_index].tasks`; parent task remains `BUILDING`
- [ ] Increment `run.total_expansions += 1`
- [ ] Return `(peer_task, None)`

**Dependencies**
- [ ] Step 3 complete — `expand_task()` method exists in engine; `ExpansionBudgetError`/`ExpansionPhaseError` defined

**References**
- `docs/orchestrated-expansion/step-04-plan.md` — Task 1
- `docs/orchestrated-expansion/architecture.md` — `add_peer_task` output contract and budget checks
- Existing `expand_task()` add_subtask branch in `src/orchestrator/workflow/engine.py`

**Constraints**
- Peer task must NOT have `parent_task_id` set (it is a sibling, not a child)
- Counter increments only on success (after all checks pass)
- Reuse the phase check and total budget check pattern from `add_subtask`

**Functionality (Expected Outcomes)**
- [ ] Peer task created in current step with correct provenance fields (`is_expansion=True`, no `parent_task_id`)
- [ ] Parent task remains `BUILDING` after peer creation
- [ ] `max_peer_tasks_per_step` exhausted → `ExpansionBudgetError(limit_type="peer")`

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/workflow/engine.py` — no type errors

---

## Task 2: Extend expand_task() for add_next_step

**Description**: Add handling for `type="add_next_step"` in `WorkflowEngine.expand_task()`, including step insertion with `order_index` shifting.

**Implementation Plan (Do These Steps)**
- [ ] In `expand_task()`, add a branch for `type == "add_next_step"`
- [ ] Validate `request.tasks` is non-empty (list must exist and have ≥1 element) → raise `ExpansionValidationError` or `ExpansionBudgetError` if empty
- [ ] Count previously inserted steps in `run.steps` (those with `is_expansion=True`): if count `>= max_inserted_steps` → raise `ExpansionBudgetError(limit_type="inserted_steps")`
- [ ] Build `StepState` from `request.tasks` array: each `ExpansionTaskSpec` → `TaskState` with provenance fields (`expanded_from_task_id=task_id`, `is_expansion=True`, `expansion_justification=request.justification`)
- [ ] Set `StepState.is_expansion=True`, `StepState.expanded_from_task_id=task_id`, step title from `request.title`
- [ ] Insert new `StepState` at `current_step_index + 1` in `run.steps`
- [ ] Increment `order_index` on all steps with index > `current_step_index` (atomically — update before inserting)
- [ ] Increment `run.total_expansions += 1`
- [ ] Return `(None, new_step)`

**Dependencies**
- [ ] Task 1 complete — pattern for adding to run state established

**References**
- `docs/orchestrated-expansion/step-04-plan.md` — Task 2
- `docs/orchestrated-expansion/architecture.md` — `add_next_step` output contract, index shift logic
- `docs/orchestrated-expansion/clarifications.md` — Q2: `add_next_step` supports multiple tasks via `tasks` array

**Constraints**
- Step index shift must be atomic — all steps after insertion point updated before inserting new step
- `request.tasks` empty → validation error (422), not budget error (429)
- Each `ExpansionTaskSpec` maps to a separate `TaskState` in the new step

**Functionality (Expected Outcomes)**
- [ ] Step inserted at `current_step_index + 1` with correct tasks
- [ ] Steps originally at index `current_step_index + 1` and above shift their `order_index` by 1
- [ ] `max_inserted_steps` exhausted → `ExpansionBudgetError(limit_type="inserted_steps")`
- [ ] Empty `request.tasks` → validation error

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/workflow/engine.py` — no type errors

---

## Task 3: Complete Human Approval Mode in WorkflowService

**Description**: Fully implement human approval mode in `WorkflowService`: serialize expansion request as a pending action, and implement `approve_expansion()` to execute or discard.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/workflow/service.py`
- [ ] In `expand_task()`, when `require_human_approval=True`: serialize the `ExpansionRequest` (e.g. `request.model_dump_json()`) and create a pending action record with `pending_action_type="expansion_approval"`, store payload in the action
- [ ] Return `ExpansionResponse(status="pending_approval", expansion_type=request.type, total_expansions_used=run.total_expansions, budget_remaining=...)` without calling the engine
- [ ] Emit `TaskExpanded` event with `approved=False`
- [ ] Implement `approve_expansion(run_id, task_id, action: Literal["approve", "reject"])` async method:
  - Fetch the pending action of type `"expansion_approval"` for the task; raise 404 if not found
  - If `action == "approve"`: deserialize stored request, call `engine.expand_task()`, persist, emit `TaskExpanded(approved=True)`, return `ExpansionResponse(status="created", ...)`
  - If `action == "reject"`: delete pending action, emit rejection event, return `{"status": "rejected"}`

**Dependencies**
- [ ] Tasks 1 and 2 complete — engine handles all three expansion types
- [ ] Existing pending action infrastructure in the service/engine — locate the pattern before implementing

**References**
- `docs/orchestrated-expansion/step-04-plan.md` — Task 3
- `docs/orchestrated-expansion/architecture.md` — approval mode description
- `docs/orchestrated-expansion/clarifications.md` — Q4: human approval is fully required
- Existing pending action patterns: search `src/orchestrator/workflow/` for `pending_action`

**Constraints**
- The stub implemented in Step 3 only returned `pending_approval`; this task replaces it with a stored action that is retrievable
- The `approve_expansion()` method must call the full engine path (not a shortcut) on approve
- On reject, no engine call is made; no new task or step is created

**Functionality (Expected Outcomes)**
- [ ] `expand_task()` with `require_human_approval=True` returns `status="pending_approval"` and creates a persistent pending action
- [ ] `approve_expansion(action="approve")` executes the stored expansion request and returns `status="created"`
- [ ] `approve_expansion(action="reject")` discards the pending action and returns `status="rejected"`
- [ ] `approve_expansion()` on a task with no pending approval → 404

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/workflow/service.py` — no type errors

---

## Task 4: Add Budget Tests for Peer and Step Limits

**Description**: Extend `tests/unit/test_expansion_budget.py` with budget tests for `max_peer_tasks_per_step` and `max_inserted_steps`.

**Implementation Plan (Do These Steps)**
- [ ] Open `tests/unit/test_expansion_budget.py`
- [ ] Add test: `max_peer_tasks_per_step` exhausted → `ExpansionBudgetError(limit_type="peer")`
- [ ] Add test: `max_inserted_steps` exhausted → `ExpansionBudgetError(limit_type="inserted_steps")`
- [ ] Run tests to confirm all pass

**Dependencies**
- [ ] Tasks 1 and 2 complete (peer and step engine branches implemented)

**References**
- `docs/orchestrated-expansion/step-04-plan.md` — Task 4
- Existing tests in `tests/unit/test_expansion_budget.py` for pattern reference

**Constraints**
- Tests operate on `WorkflowEngine` directly (unit tests — no DB or HTTP)

**Functionality (Expected Outcomes)**
- [ ] Both new budget error cases are covered with assertions on `limit_type`

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_expansion_budget.py -v` — all tests pass (including new ones)

---

## Task 5: Write Unit Tests for Step Insertion Index Reordering

**Description**: Create `tests/unit/test_expansion_step_insert.py` with unit tests for `add_next_step` index reordering behavior.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_expansion_step_insert.py`
- [ ] Test: insert at index 1 of a 3-step run → steps at indices 2 and 3 shift to 3 and 4
- [ ] Test: insert at the last position → no shift needed (no steps after insertion point)
- [ ] Test: insert multiple times → indices remain consistent after each insert
- [ ] Test: `add_next_step` with empty tasks list → validation error

**Dependencies**
- [ ] Task 2 complete (add_next_step engine branch implemented)

**References**
- `docs/orchestrated-expansion/step-04-plan.md` — Task 5

**Constraints**
- Tests must verify `order_index` values on all steps after insertion, not just the new step

**Functionality (Expected Outcomes)**
- [ ] All index reordering scenarios pass
- [ ] Empty tasks list correctly raises a validation error (not a budget error)

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_expansion_step_insert.py -v` — all tests pass

---

## Task 6: Write Unit Tests for add_peer_task

**Description**: Create `tests/unit/test_expansion_peer.py` with unit tests for `add_peer_task` creation and provenance.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_expansion_peer.py`
- [ ] Test: peer task created with correct provenance (`is_expansion=True`, `expanded_from_task_id=task_id`, no `parent_task_id`)
- [ ] Test: parent task remains `BUILDING` after peer creation
- [ ] Run tests to confirm all pass

**Dependencies**
- [ ] Task 1 complete (add_peer_task engine branch implemented)

**References**
- `docs/orchestrated-expansion/step-04-plan.md` — Task 6

**Constraints**
- Tests operate on `WorkflowEngine` directly (no DB or HTTP)
- Explicitly assert `peer_task.parent_task_id is None`

**Functionality (Expected Outcomes)**
- [ ] Peer provenance fields all correct
- [ ] Parent status unchanged

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_expansion_peer.py -v` — all tests pass
- [ ] `uv run pytest tests/unit/ -v` — no regressions
