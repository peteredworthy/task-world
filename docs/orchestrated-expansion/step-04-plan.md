# Step Plan: Expansion Engine — add_peer_task + add_next_step + Human Approval (M2 Remaining)

## Purpose

Complete the expansion engine with the remaining two expansion types (`add_peer_task` and `add_next_step`) and implement human approval mode. `add_next_step` introduces step index reordering, which requires an atomic DB update. Human approval mode reuses the existing pending action infrastructure.

## Prerequisites

- **Step 3 complete** — `expand_task()` method exists in engine and service; `ExpansionBudgetError`/`ExpansionPhaseError` defined; budget enforcement infrastructure working.

## Functional Contract

### Inputs

`WorkflowEngine.expand_task(run, task_id, request, expansion_limits)` — same signature as Step 3, but now handles `type="add_peer_task"` and `type="add_next_step"`.

`WorkflowService.expand_task()` — same signature; human approval path now fully implemented.

Approval endpoint (new): `POST /api/runs/{run_id}/tasks/{task_id}/expand/approve`:
- `action: "approve" | "reject"` — human decision

### Outputs

`add_peer_task`:
- Returns `(created_task: TaskState, None)`
- New `TaskState` has: `expanded_from_task_id=task_id`, no `parent_task_id`, `is_expansion=True`
- Peer task added to `run.steps[current_step_index].tasks`
- Parent task remains `BUILDING`
- Budget: `run.total_expansions += 1`; per-step peer count checked against `max_peer_tasks_per_step`

`add_next_step`:
- Returns `(None, created_step: StepState)`
- New `StepState` built from `request.tasks` array (each `ExpansionTaskSpec` → `TaskState`); `request.title` → step title
- New `StepState` has: `is_expansion=True`, `expanded_from_task_id=task_id`
- Inserted into `run.steps` at `current_step_index + 1`
- All steps with index > `current_step_index` have `order_index` incremented by 1 (atomically)
- Budget: `run.total_expansions += 1`; inserted step count checked against `max_inserted_steps`

Human approval mode (`require_human_approval=True`):
- `WorkflowService.expand_task()` creates a pending action record: `pending_action_type="expansion_approval"`, stores serialized `ExpansionRequest` in the action payload
- Returns `ExpansionResponse(status="pending_approval", ...)`
- `TaskExpanded` emitted with `approved=False`
- On `POST .../expand/approve` with `action="approve"`: deserialize stored request, call `engine.expand_task()`, persist, emit `TaskExpanded` with `approved=True`
- On `POST .../expand/approve` with `action="reject"`: delete pending action, emit rejection event

### Error Cases

`add_peer_task`:
- Count of peer tasks already in current step `>= max_peer_tasks_per_step` → `ExpansionBudgetError` (429)
- Same phase check as other types (task must be `BUILDING`)

`add_next_step`:
- `request.tasks` is `None` or empty → `ExpansionValidationError` (422) — must have at least one task
- Count of previously inserted steps `>= max_inserted_steps` → `ExpansionBudgetError` (429)
- Step index shift and insertion must be atomic; partial insert → DB rollback

Human approval:
- Approve/reject on a task with no pending expansion approval → 404

## Tasks

1. **`src/orchestrator/workflow/engine.py`**: Extend `expand_task()` to handle `add_peer_task`:
   - Count existing peer tasks (tasks with `expanded_from_task_id` set, excluding self) in current step
   - Apply budget check against `max_peer_tasks_per_step`
   - Create peer `TaskState`, add to current step
   - Increment `run.total_expansions`

2. **`src/orchestrator/workflow/engine.py`**: Extend `expand_task()` to handle `add_next_step`:
   - Validate `request.tasks` is non-empty
   - Count previously inserted steps in run
   - Apply budget check against `max_inserted_steps`
   - Build `StepState` from `request.tasks` (each `ExpansionTaskSpec` → `TaskState` with provenance fields)
   - Insert step at `current_step_index + 1`
   - Update `order_index` on all steps after insertion point

3. **`src/orchestrator/workflow/service.py`**: Complete human approval mode:
   - When `require_human_approval=True`: serialize `ExpansionRequest` and store as pending action on task
   - Implement `approve_expansion(run_id, task_id, action)`: fetch pending action, deserialize, execute or discard

4. **`tests/unit/test_expansion_budget.py`**: Additional budget tests:
   - `max_peer_tasks_per_step` exhausted → error
   - `max_inserted_steps` exhausted → error

5. **`tests/unit/test_expansion_step_insert.py`**: Unit tests for index reordering:
   - Insert at index 1 of 3 steps → steps at 2, 3 shift to 3, 4
   - Insert at last position → no shift needed
   - Insert multiple times → indices remain consistent after each insert
   - `add_next_step` with empty tasks list → validation error

6. **`tests/unit/test_expansion_peer.py`**: Unit tests:
   - Peer task created with correct provenance (no `parent_task_id`, `is_expansion=True`)
   - Parent remains `BUILDING` after peer creation

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/test_expansion_budget.py tests/unit/test_expansion_step_insert.py tests/unit/test_expansion_peer.py -v` — all tests pass
- `uv run pyright src/orchestrator/workflow/` — no type errors
- `uv run pytest tests/unit/ -v` — no regressions

### Manual Verification

- Trace `add_next_step` through a 3-step run: verify `order_index` values before and after insertion are consistent
- Confirm that for `add_peer_task`, peer's `parent_task_id` is `None` (it is a sibling, not a child)
- Confirm human approval pending action stores full request payload for later deserialisation

## Context & References

- Plan: `docs/orchestrated-expansion/plan.md` — Step 4 specification
- Architecture: `docs/orchestrated-expansion/architecture.md` — per-type implementation, index shift logic, approval mode
- Clarification Q4: Human approval mode is fully required
- Existing pending action patterns: `src/orchestrator/workflow/engine.py` (search for `pending_action`)
