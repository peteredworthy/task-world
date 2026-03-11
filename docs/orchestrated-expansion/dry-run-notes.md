# Dry-Run Notes: Orchestrated Expansion (Option D)

Generated: 2026-03-11
Simulation based on: `docs/orchestrated-expansion/plan.md`, `steps/step-01.md` through `steps/step-07.md`, and codebase inspection.

---

## Per-Step Simulation Results

### Step 1: Data Models (M1 Core)

**Assumptions**
- `config/models.py`, `state/models.py`, `db/models.py`, `api/schemas/tasks.py`, and `workflow/events.py` are all writable and independently testable.
- `pyright` is configured and passes cleanly on current codebase.
- `StepState` (runtime model) also needs expansion fields added, but the step description only mentions `StepModel` (DB). The runtime state must match the DB model.

**Expected outputs**
- `ExpansionLimits` importable, defaults (5, 3, 2, 10, False) correct.
- `TaskState` gains 3 new fields with zero-value defaults.
- `Run` gains `total_expansions: int = 0`.
- `StepModel` and `TaskModel` gain new columns; existing rows still valid.
- `ExpansionRequest`, `ExpansionResponse`, `ExpansionTaskSpec` pass Pydantic validation.
- `TaskExpanded` dataclass importable.
- Unit test file `test_expansion_models.py` passes.

**Blockers / risks**
- `StepState` (runtime model in `state/models.py`) is NOT mentioned in the step description but must also gain `is_expansion` and `expanded_from_task_id` fields to stay in sync with `StepModel`. If omitted, Step 4's `add_next_step` will fail to set these fields on the in-memory state object.
- Events in `workflow/events.py` use `@dataclass` pattern. Step description says "Pydantic model" in one place but all existing events are dataclasses. The agent must follow the `@dataclass` pattern.
- `requirements` field type: `architecture.md` uses `list[dict] | None`, step description uses `list[str] | None`. These are incompatible. Given `RequirementConfig` has `{id, desc, must, priority}` structure, `list[dict]` is correct.

---

### Step 2: DB Migration (M1 Remaining)

**Assumptions**
- Alembic is configured to target `src/orchestrator/db/migrations/` with its own `alembic.ini`.
- Step 2 says `alembic/versions/` repeatedly, but the actual path is `src/orchestrator/db/migrations/versions/`.
- `batch_alter_table` is required for all column additions (SQLite does not support `ALTER TABLE ADD COLUMN ... REFERENCES`).
- Existing migrations use constraint names like `fk_tasks_parent_task_id` — the new migration should follow the same naming convention.

**Expected outputs**
- Migration file in `src/orchestrator/db/migrations/versions/` adding 6 columns.
- `alembic upgrade head` succeeds on fresh and seeded DBs.
- `alembic downgrade -1` removes all 6 columns cleanly.

**Blockers / risks**
- **Wrong migration directory in step description.** Step-02 says `alembic/versions/` in multiple places. The actual path is `src/orchestrator/db/migrations/versions/`. The `alembic` CLI command must also use `--config src/orchestrator/db/migrations/alembic.ini` (or equivalent) or be run from the migrations directory. Running `uv run alembic revision --autogenerate` from the project root without `--config` will fail.
- **Autogenerate noise.** `alembic revision --autogenerate` will likely include unrelated diffs if the DB is out of sync with the ORM. The agent must trim carefully.
- **Self-referencing FK on `tasks.expanded_from_task_id`.** The existing `parent_task_id` FK (`fk_tasks_parent_task_id`) already demonstrates this pattern works via `batch_alter_table` with an explicit constraint name. Follow that exact pattern.
- **`use_alter=True` on ORM model vs migration.** `use_alter=True` in the ORM column definition is relevant for `create_all()` table creation order; but for `batch_alter_table` migrations, it is not strictly needed. Consistency with `parent_task_id` approach is safer.

---

### Step 3: Expansion Engine — add_subtask (M2 Core)

**Assumptions**
- `WorkflowEngine` methods operate on in-memory `Run`/`TaskState` objects.
- `expand_fan_out_task()` is on `WorkflowService`, NOT `WorkflowEngine`.
- The engine's responsibility is state transitions (setting statuses, creating new state objects). Persistence is the service layer's job.

**Expected outputs**
- `ExpansionBudgetError` and `ExpansionPhaseError` in `workflow/errors.py`.
- `WorkflowEngine.expand_task()` handles `add_subtask` blocking and non-blocking.
- `WorkflowService.expand_task()` persists, increments `RunModel.expansion_count`, emits `TaskExpanded`.

**Blockers / risks**
- **`expand_fan_out_task()` is on WorkflowService, not WorkflowEngine.** Step-03 Task 2 says the engine should "Call existing `expand_fan_out_task()` logic." But `expand_fan_out_task` lives in `service.py` (L693) — the engine doesn't have access to the service. Three resolution paths:
  1. The engine sets parent task to `FAN_OUT_RUNNING` directly (duplicating just the status-change part of `expand_fan_out_task`), and the service calls `expand_fan_out_task` after the engine returns.
  2. The engine returns a flag indicating "this parent should be fan-outed" and the service handles it.
  3. The engine is given a reference to the service (breaks separation of concerns).
  **Recommended hardening**: The engine sets parent status to `FAN_OUT_RUNNING` and adds child to step tasks list. The service layer calls `expand_fan_out_task()` as usual (since it already handles worktrees, config lookups, etc.). The engine's job is only state mutation, not the full fan-out setup.
- **TaskModel for expanded tasks.** `TaskModel` doesn't currently have `is_expansion`, `expanded_from_task_id` columns until Step 2's migration is applied. If Step 2 is not complete, persisting the new `TaskModel` will fail with an IntegrityError or silently drop new columns. **Hard dependency on Step 2 being applied before Step 3's integration.**
- **Human approval stub.** Step 3 says "create a pending approval record stub." The existing `pending_action_type` field only stores a string ("expansion_approval"). There is no field to store the `ExpansionRequest` payload — which is needed for Step 4's `approve_expansion()` to deserialize and execute. A new `pending_expansion_request: str | None` (JSON) field is needed on both `TaskState` and `TaskModel`. This is a gap — it should be added in Step 1 or Step 2, not discovered in Step 3.

---

### Step 4: Expansion Engine — add_peer_task + add_next_step + Human Approval (M2 Remaining)

**Assumptions**
- `add_peer_task` budget check counts tasks with `expanded_from_task_id` set in the current step (excluding the calling task).
- `add_next_step` inserts at `current_step_index + 1` in `run.steps` list and increments `order_index` on affected `StepModel` rows.
- The `approve_expansion()` service method can fetch the stored expansion request from the `pending_expansion_request` field (see Step 3 blocker above).

**Expected outputs**
- Engine handles all 3 expansion types.
- `WorkflowService.approve_expansion()` implemented.
- Unit tests for peer, step insertion, and approval pass.

**Blockers / risks**
- **`StepState` lacks `is_expansion` and `expanded_from_task_id` fields** (see Step 1 gap). When `add_next_step` creates a new `StepState`, it can't set `is_expansion=True` on it unless `StepState` has that field.
- **Peer task budget counter definition ambiguity.** Step 4 says to count "tasks with `expanded_from_task_id` set, excluding self." But this counts ALL expansions (subtasks too, if non-blocking). The correct count is peer tasks (no `parent_task_id`). The counter should filter: `[t for t in step.tasks if t.expanded_from_task_id and not t.parent_task_id]`.
- **`approve_expansion()` needs the stored expansion request.** This requires the `pending_expansion_request` JSON field from Step 3. If not added there, `approve_expansion()` cannot recover the original request.
- **Atomic DB step index shift.** The plan says to atomically update `order_index` for all shifted steps. This means the service layer must issue a bulk DB update inside a transaction before inserting the new step. The plan describes this correctly but the agent needs to be careful about `run.steps` in-memory list ordering vs `order_index` DB values staying in sync.

---

### Step 5: API Endpoint + Integration Tests (M2 Final)

**Assumptions**
- Exception handler registration is in `src/orchestrator/api/errors.py` (`register_error_handlers` function).
- Route ordering: `/expand/approve` must be registered before `/expand` to avoid FastAPI path shadowing.
- Integration tests use `AsyncClient` against a test app instance (same pattern as `test_api_full_lifecycle.py`).

**Expected outputs**
- `POST /api/runs/{run_id}/tasks/{task_id}/expand` returns `ExpansionResponse`.
- `POST /api/runs/{run_id}/tasks/{task_id}/expand/approve` handles approve/reject.
- Exception handlers for 429 and 409 registered.
- Full integration test suite in `tests/integration/test_expansion.py` passes.

**Blockers / risks**
- **Route shadowing.** FastAPI processes routes in registration order. If `POST /{run_id}/tasks/{task_id}/expand` is registered before `POST /{run_id}/tasks/{task_id}/expand/approve`, the latter path will match the former pattern (treat "approve" as the body). Step description correctly identifies this — the agent must register `/expand/approve` first.
- **Integration test setup complexity.** Creating a run in ACTIVE state with a task in BUILDING state requires the same multi-step setup as other integration tests. If the test setup is wrong, all 13+ test cases will fail. The agent should create a helper fixture or reuse the existing `active_run_with_task` pattern from `test_api_full_lifecycle.py`.
- **Budget exhaustion test requires a routine with `max_total_expansions=5`.** This requires passing a custom `expansion_limits` config. The integration test must embed the routine with `expansion_limits` configured — this works only if `RoutineConfig.expansion_limits` is wired correctly (Step 1).
- **Human approval test requires a run with `require_human_approval=True`.** The routine config must be embedded in the run with this flag. If the flag isn't respected during run creation, this test will fail.

---

### Step 6: Executor + Prompt Integration (M3)

**Assumptions**
- The builder prompt function signature can be extended to accept `expansion_limits` and `run.total_expansions`.
- The executor's main step-task loop is in `_execute_step()` or a similar method (the task-fetch/execute loop that calls `_get_next_task()`).
- MCP tools are registered in `src/orchestrator/mcp/tools.py` in the `ORCHESTRATOR_TOOLS` list, with a `ToolHandler.dispatch()` method for routing.

**Expected outputs**
- Builder prompt includes "Expansion API" section with budget line.
- Executor refreshes task list after each task completion.
- `orchestrator_expand_task` tool registered in `ORCHESTRATOR_TOOLS`.
- Unit tests for prompt and executor discovery pass.

**Blockers / risks**
- **MCP tool name convention.** Existing tools use `orchestrator_` prefix (`orchestrator_submit`, `orchestrator_update_checklist`). The plan says "register `expand_task` as an MCP tool" without the prefix. The agent must use `orchestrator_expand_task` to maintain consistency.
- **Executor task list refresh updates in-memory Run object.** The executor operates on an in-memory `Run` object loaded at step start. Calling `service.get_step_tasks()` returns fresh DB data but doesn't automatically update `run.steps[idx].tasks`. The agent needs to either: (a) update `run.steps[current_step_index].tasks` in-memory after refresh, or (b) reload the full `Run` object. Partial update is safer to avoid losing other in-memory state.
- **Prompt function signature change.** `build_prompt()` is called from multiple places. Adding required parameters will break all call sites. Parameters should have defaults: `expansion_limits: ExpansionLimits | None = None`, `total_expansions: int = 0`.
- **Budget string for non-expansion routines.** If `expansion_limits` is None (old routine), the prompt section should either be omitted or show defaults gracefully. The plan says "use defaults" — this is correct, but the section should note it's available even if the routine doesn't configure it.

---

### Step 7: Frontend Display (M4)

**Assumptions**
- `ui/src/types/tasks.ts` and `ui/src/types/runs.ts` are the canonical type sources.
- Vitest and testing-library are set up; existing tests pass.
- Components use existing Tailwind/CSS classes (no new CSS files needed).

**Expected outputs**
- TypeScript types updated with optional expansion fields.
- "Expanded" badge, peer task dashed border, "+" step indicator, `task_expanded` event renderer, and budget display all render correctly.
- All frontend tests pass with `npx vitest run`.

**Blockers / risks**
- **`task_expanded` event type key in API.** The `ActivityFeed.tsx` renders events by `event.type`. The backend `TaskExpanded` dataclass has `event_type: str` inherited from `WorkflowEvent`. The actual string value must match what the API serializes (likely `"task_expanded"` — needs to be confirmed against the event serialization code).
- **Finding the "step view component."** Step 7 Task 3 says "identify the correct step/task-list component" — it may be `StepDetail.tsx`, `StepCard.tsx`, or similar. The agent must search before editing. If the component is not found quickly, this task could stall.
- **`expanded_from_task_id` may be a full UUID in the UI label.** "Added by T-{id}" looks better with a short ID (first 8 chars). The step description doesn't specify truncation. The agent should apply consistent ID shortening.
- **Pending expansion approval UI in RunDetail.** The existing `pending_action_type` rendering in RunDetail only handles "clarification" and "approval". Adding "expansion_approval" requires understanding how `get_pending_actions()` returns data and how the approval endpoint differs from the clarification approval path.

---

## Failure Mode Analysis

| Step | Failure Mode | Likelihood | Hardening Action |
|------|-------------|-----------|-----------------|
| 1 | `StepState` not updated with `is_expansion`/`expanded_from_task_id` fields | HIGH | Add to Step 1 requirements: "StepState also gains `is_expansion: bool = False` and `expanded_from_task_id: str | None = None`" |
| 1 | `requirements` field type inconsistency (`list[dict]` vs `list[str]`) | HIGH | Standardize to `list[dict] \| None` in step-01 task description |
| 1 | `TaskExpanded` uses Pydantic instead of `@dataclass` | MEDIUM | Add explicit constraint: "Follow the `@dataclass` pattern from `WorkflowEvent`" |
| 1 | Missing `pending_expansion_request` field for human approval | HIGH | Add `pending_expansion_request: str \| None = None` to `TaskState` and `TaskModel` in Step 1; add DB column to Step 2 migration |
| 2 | Wrong migration directory (`alembic/versions/` vs `src/orchestrator/db/migrations/versions/`) | VERY HIGH | Fix step description to say `src/orchestrator/db/migrations/versions/`. Add explicit alembic command with `--config` flag |
| 2 | `alembic revision --autogenerate` fails or generates noise | MEDIUM | Add note: run from project root as `uv run alembic --config src/orchestrator/db/migrations/alembic.ini revision --autogenerate -m "..."` |
| 3 | Agent tries to call `expand_fan_out_task()` from within `WorkflowEngine` | HIGH | Clarify in step description: engine sets parent to `FAN_OUT_RUNNING` directly; service calls `expand_fan_out_task()` afterwards |
| 3 | Human approval stub has nowhere to store `ExpansionRequest` payload | HIGH | Add `pending_expansion_request: str \| None` to models in Step 1; reference this in Step 3 Task 3 |
| 4 | Peer budget counter includes subtasks (counts all `expanded_from_task_id`) | MEDIUM | Tighten counter: only count tasks where `parent_task_id is None` AND `expanded_from_task_id == task_id` |
| 4 | `StepState` missing expansion fields causes attribute error | HIGH | Fixed by Step 1 hardening above |
| 5 | Route shadowing: `/expand` captures `/expand/approve` | HIGH | Already identified in plan; ensure task description emphasizes registration order |
| 5 | Integration test setup requires non-trivial state | MEDIUM | Add a reusable `create_active_run_with_building_task()` fixture in `conftest.py` |
| 6 | MCP tool registered without `orchestrator_` prefix | MEDIUM | Specify `orchestrator_expand_task` explicitly in step description |
| 6 | Executor refreshes DB tasks but doesn't update in-memory `Run` | HIGH | Add explicit note: after refresh, update `run.steps[current_step_index].tasks` to include new tasks |
| 6 | `build_prompt()` signature change breaks call sites | MEDIUM | Add defaults to new parameters so all existing call sites continue to work |
| 7 | `task_expanded` event type string mismatch (backend vs frontend) | MEDIUM | Add explicit note: check event serialization to confirm string is `"task_expanded"` |
| 7 | Step view component not immediately identifiable | LOW | Add search instruction: `grep -r "task.status" ui/src/components` to find the right component |

---

## Gaps Requiring Remediation

### Gap 1: `StepState` missing expansion fields (Critical)

**Problem**: `StepState` in `src/orchestrator/state/models.py` does not have `is_expansion` or `expanded_from_task_id` fields. Steps 1 and 4 only mention `StepModel` (DB) but not `StepState` (runtime). When `add_next_step` creates a new `StepState`, it cannot set these fields.

**Remediation**: Add to Step 1 Task 2 (or as a new Task 2b):
```python
# In StepState:
is_expansion: bool = False
expanded_from_task_id: str | None = None
```

---

### Gap 2: Missing `pending_expansion_request` storage field (Critical)

**Problem**: Human approval mode needs to store the `ExpansionRequest` payload so `approve_expansion()` can deserialize and execute it. The existing `pending_action_type` is just a string tag — there's no field for the payload. (Clarifications use `pending_clarification_id` to look up a separate table. Expansion requests have no such table.)

**Remediation**: Add to Step 1 Task 2 (state models) and Step 1 Task 3 (DB models):
- `TaskState.pending_expansion_request: str | None = None` (JSON-serialized `ExpansionRequest`)
- `TaskModel.pending_expansion_request = Column(Text, nullable=True)`

And add the DB column to Step 2's migration.

---

### Gap 3: Alembic migration path discrepancy (Critical)

**Problem**: Step 2 tasks consistently reference `alembic/versions/` but migrations live at `src/orchestrator/db/migrations/versions/`. The `alembic` command also needs to know where `alembic.ini` is.

**Remediation**: Update Step 2 task descriptions:
- Replace all occurrences of `alembic/versions/` with `src/orchestrator/db/migrations/versions/`
- Replace `uv run alembic revision ...` with `uv run alembic --config src/orchestrator/db/migrations/alembic.ini revision ...` (or verify the alembic.ini location)

---

### Gap 4: `expand_fan_out_task()` location (Significant)

**Problem**: Step 3 Task 2 says the engine should "Call existing `expand_fan_out_task()` logic" but this method is on `WorkflowService`, not `WorkflowEngine`. The engine can't call service methods.

**Remediation**: Update Step 3 Task 2 to clarify the responsibility split:
- **Engine's job**: Create child `TaskState`, set `parent.status = TaskStatus.FAN_OUT_RUNNING`, add child to `step.tasks` (for blocking). Return result.
- **Service's job**: After calling `engine.expand_task()`, call `service.expand_fan_out_task(run_id, task_id)` to trigger worktree creation and the full fan-out setup — OR skip `expand_fan_out_task()` (which handles static fan-out setup) and instead persist the child `TaskModel` directly, letting the executor's existing `FAN_OUT_RUNNING` detection handle the rest.

---

### Gap 5: `requirements` field type inconsistency (Moderate)

**Problem**: `architecture.md` defines `requirements: list[dict] | None` in `ExpansionRequest` and `ExpansionTaskSpec`, but `step-01.md` Task 4 says `list[str] | None`. These are incompatible.

**Remediation**: Standardize to `list[dict] | None` in all step descriptions, matching `RequirementConfig`'s structure. The dict should accept `{id, desc, must, priority}` keys.

---

### Gap 6: MCP tool naming convention (Moderate)

**Problem**: Step 6 Task 3 says to register "expand_task" as an MCP tool, but all existing tools use the `orchestrator_` prefix.

**Remediation**: Update Step 6 Task 3 to say `orchestrator_expand_task`.

---

### Gap 7: Executor in-memory state refresh (Moderate)

**Problem**: The executor operates on an in-memory `Run` object. Calling `service.get_step_tasks()` returns DB data but doesn't update the `Run` object. The executor's `_get_next_task()` method iterates `step.tasks` on the in-memory `Run`, so newly discovered tasks won't be seen.

**Remediation**: Update Step 6 Task 2 to explicitly state:
- After refresh, append any NEW tasks (not already in `step.tasks`) to `run.steps[current_step_index].tasks`
- Identify new tasks by comparing task IDs in the refreshed list against those already in the in-memory list

---

## Plan Changes Recommended

1. **Step 1 Task 2**: Add `StepState` expansion fields (`is_expansion: bool = False`, `expanded_from_task_id: str | None = None`). Add `TaskState.pending_expansion_request: str | None = None`.

2. **Step 1 Task 3**: Add `TaskModel.pending_expansion_request = Column(Text, nullable=True)` to the DB model.

3. **Step 1 Task 4**: Change `requirements: list[str] | None = None` to `requirements: list[dict] | None = None` in both `ExpansionRequest` and `ExpansionTaskSpec`.

4. **Step 2 (all tasks)**: Replace all references to `alembic/versions/` with `src/orchestrator/db/migrations/versions/`. Update alembic commands to use `--config src/orchestrator/db/migrations/alembic.ini`. Add `pending_expansion_request` column to the migration.

5. **Step 3 Task 2**: Clarify engine/service responsibility split for blocking subtasks. Engine sets `FAN_OUT_RUNNING` + adds child task; service handles the rest via existing `expand_fan_out_task()`.

6. **Step 3 Task 3**: Reference `pending_expansion_request` field for storing the serialized `ExpansionRequest` when `require_human_approval=True`.

7. **Step 4 Task 1**: Tighten peer budget counter to only count peer expansions (no `parent_task_id`), not all expansions.

8. **Step 5 Task 4**: Add a shared test fixture `create_active_run_with_building_task()` to reduce test setup duplication.

9. **Step 6 Task 2**: Explicitly state that the in-memory `run.steps[current_step_index].tasks` list must be updated after the DB refresh (not just the local `pending` variable).

10. **Step 6 Task 3**: Rename the MCP tool to `orchestrator_expand_task`.

---

## Environment Checks to Add as Early Auto-Verify

The following shell checks should be added as `auto_verify` commands to Step 1 and Step 2 tasks to catch environment issues early:

- **Verify pyright passes before coding**: `uv run pyright src/orchestrator/config/models.py` (Step 1 Task 1)
- **Verify alembic config path**: `ls src/orchestrator/db/migrations/alembic.ini` (Step 2 Task 1)
- **Verify migration head before generating**: `uv run alembic --config src/orchestrator/db/migrations/alembic.ini current` (Step 2 Task 1)
- **Verify no regressions after each step**: `uv run pytest tests/unit/ -x -q` (after every step)

---

## Summary

The 7-step plan is well-structured and front-loads the correct decisions. The main risk areas are:

1. **Two critical missing model fields** (`StepState.is_expansion`, `TaskState.pending_expansion_request`) that will cause failures in Steps 4 and 3 respectively if not added in Step 1.
2. **Wrong migration path** (`alembic/versions/` vs `src/orchestrator/db/migrations/versions/`) that will cause Step 2 to fail immediately.
3. **Engine/service boundary confusion** for blocking subtasks that will require implementation judgment calls.
4. **Executor in-memory state** requires explicit syncing after DB refresh.

All other risks are moderate and have clear mitigation paths. Steps 5, 6, and 7 are relatively straightforward given the foundation built in Steps 1–4.
