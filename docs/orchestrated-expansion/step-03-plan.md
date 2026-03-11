# Step Plan: Expansion Engine — add_subtask (M2 Core)

## Purpose

Implement `WorkflowEngine.expand_task()` for the `add_subtask` expansion type (both blocking and non-blocking variants), budget enforcement, provenance recording, and the `WorkflowService.expand_task()` wrapper with DB persistence and event emission. This is the most complex expansion type because it reuses the existing fan-out infrastructure. Getting the engine pattern right here establishes the foundation for `add_peer_task` and `add_next_step` in Step 4.

## Prerequisites

- **Step 1 complete** — `ExpansionLimits`, `TaskState` fields, `Run.total_expansions`, `ExpansionRequest`/`ExpansionResponse` schemas, `TaskExpanded` event all defined.
- **Step 2 complete** — DB columns for expansion fields exist and are migrated.

## Functional Contract

### Inputs

`WorkflowEngine.expand_task(run, task_id, request, expansion_limits)`:
- `run: Run` — current run state loaded from DB
- `task_id: str` — the requesting task's ID
- `request: ExpansionRequest` — validated expansion request with `type="add_subtask"`
- `expansion_limits: ExpansionLimits` — from the routine config

`WorkflowService.expand_task(run_id, task_id, request)`:
- `run_id: str` — run identifier
- `task_id: str` — requesting task identifier
- `request: ExpansionRequest` — the expansion request

### Outputs

`WorkflowEngine.expand_task()` for `add_subtask`:
- Returns `(created_task: TaskState, None)` — the new child task state; second element is always None for subtask type
- For `blocking=True`: parent task transitions to `FAN_OUT_RUNNING`
- For `blocking=False`: child task created, parent remains `BUILDING`
- In both cases: `task.expansions_requested += 1`, `run.total_expansions += 1`
- New `TaskState` has: `parent_task_id=task_id`, `expanded_from_task_id=task_id`, `expansion_justification=request.justification`, `is_expansion=True`

`WorkflowService.expand_task()`:
- Persists new `TaskModel` to DB with all expansion fields set
- Updates `RunModel.expansion_count`
- Emits `TaskExpanded` event
- Returns `ExpansionResponse` with `status="created"`, `created_task_id`, budget info

### Error Cases

- Task not found in run → `TaskNotFoundError` (404 from router)
- Task not in `BUILDING` status → raise `ExpansionPhaseError` (409)
- `run.total_expansions >= expansion_limits.max_total_expansions` → raise `ExpansionBudgetError` (429) with message indicating total limit hit
- `task.expansions_requested >= expansion_limits.max_subtasks_per_task` → raise `ExpansionBudgetError` (429) with message indicating per-task subtask limit hit
- `blocking=True` on a task that already has `parent_task_id` set (nested fan-out) → raise `ExpansionPhaseError` (409) with message "blocking subtask not allowed for child tasks"
- `require_human_approval=True` → `WorkflowService` creates pending approval record instead of calling engine; returns `status="pending_approval"` (handled in Step 4's approval mode; stub the service path here)

## Tasks

1. **`src/orchestrator/workflow/errors.py`** (or appropriate errors module): Define `ExpansionBudgetError` and `ExpansionPhaseError` exception classes with informative message fields.

2. **`src/orchestrator/workflow/engine.py`**: Implement `expand_task()` method:
   - Phase check (task must be `BUILDING`)
   - Budget checks (total + per-task subtask count)
   - Nested fan-out guard (blocking subtask from child task rejected)
   - Create child `TaskState` with all provenance fields
   - For `blocking=True`: call `expand_fan_out_task()` (reuse existing fan-out infrastructure) to set parent to `FAN_OUT_RUNNING` and register child
   - For `blocking=False`: add child to `run.steps[current_step_index].tasks`; parent stays `BUILDING`
   - Increment `task.expansions_requested` and `run.total_expansions`
   - Return `(child_task, None)`

3. **`src/orchestrator/workflow/service.py`**: Implement `WorkflowService.expand_task()`:
   - Load run from DB
   - Load `expansion_limits` from run's routine config
   - If `require_human_approval=True`: create pending approval stub (return `pending_approval`)
   - Otherwise: call `engine.expand_task()`
   - Persist new `TaskModel` to DB with all fields populated
   - Update `RunModel.expansion_count += 1`
   - Emit `TaskExpanded` event
   - Return `ExpansionResponse`

4. **`tests/unit/test_expansion_budget.py`**: Unit tests:
   - Total budget exhausted → `ExpansionBudgetError`
   - Per-task subtask limit exhausted → `ExpansionBudgetError` (other tasks can still expand)
   - Blocking subtask from child task → `ExpansionPhaseError`
   - Task in `VERIFYING` status → `ExpansionPhaseError`
   - Task in `BUILDING` status → allowed

5. **`tests/unit/test_expansion_subtask.py`**: Unit tests:
   - `add_subtask` blocking: child has correct provenance fields; parent transitions to `FAN_OUT_RUNNING`
   - `add_subtask` non-blocking: child created; parent remains `BUILDING`
   - Counters incremented correctly after expansion

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/test_expansion_budget.py tests/unit/test_expansion_subtask.py -v` — all tests pass
- `uv run pyright src/orchestrator/workflow/engine.py src/orchestrator/workflow/service.py` — no type errors
- `uv run pytest tests/unit/ -v` — no existing tests broken

### Manual Verification

- Confirm `expand_fan_out_task()` is called exactly as the static fan-out path calls it (same arguments, same state transitions)
- Confirm non-blocking subtask does not alter parent task status
- Confirm budget counters are only incremented on success, not on error

## Context & References

- Plan: `docs/orchestrated-expansion/plan.md` — Step 3 specification
- Architecture: `docs/orchestrated-expansion/architecture.md` — engine method signature, budget check order
- Existing fan-out: `src/orchestrator/runners/executor.py` L1009 (`_execute_fan_out`)
- Existing engine fan-out methods: `expand_fan_out_task()` / `complete_fan_out_parent()` in `engine.py`
- Clarification Q3: `FAN_OUT_RUNNING` agents cannot call expand (not applicable, no test needed)
