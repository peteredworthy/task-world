# Plan: Orchestrated Expansion (Option D)

## Overview

Implement dynamic run expansion in four milestones: (1) data models and budget system, (2) expansion engine logic and API endpoint, (3) executor and prompt integration, (4) frontend display. Each milestone delivers testable, independently useful functionality. The approach front-loads the data shape decisions (models) so later milestones can build on a stable foundation.

## Milestones

### M1: Data Models + Budget System

**Goal:** Extend all data models to represent expansions and limits. Nothing runs yet, but the system can store and represent expansion state.

**Deliverables:**
- `ExpansionLimits` Pydantic model in `src/orchestrator/config/models.py` (`max_subtasks_per_task`, `max_peer_tasks_per_step`, `max_inserted_steps`, `max_total_expansions`, `require_human_approval`)
- `expansion_limits` field on `RoutineConfig` (optional, defaults to `ExpansionLimits()`)
- `TaskState` gains: `expansions_requested: int = 0`, `expanded_from_task_id: str | None = None`, `expansion_justification: str | None = None`
- `Run` gains: `total_expansions: int = 0`
- `TaskModel` gains: `expanded_from_task_id`, `expansion_justification`, `is_expansion` columns
- `RunModel` gains: `expansion_count` column
- `ExpansionRequest` and `ExpansionResponse` schemas in `src/orchestrator/api/schemas/tasks.py`
- `TaskExpanded` event type in `src/orchestrator/workflow/events.py`
- DB migration (Alembic) covering all new columns; defaults ensure existing rows remain valid
- Unit tests: `ExpansionLimits` defaults, serialization round-trip

**Verification:** `uv run pytest tests/unit/ -v` passes, `uv run pyright` clean, existing tests unaffected.

### M2: Expansion Engine + API Endpoint

**Goal:** Implement the three expansion types in the workflow engine and expose the endpoint. Budget enforcement, provenance recording, and `add_next_step` index reordering all work correctly.

**Deliverables:**
- `WorkflowEngine.expand_task()` method: validates budget, dispatches by type, records provenance, increments counters
  - `add_subtask` blocking: reuse `expand_fan_out_task` / `complete_fan_out_parent`; parent transitions to `FAN_OUT_RUNNING`
  - `add_subtask` non-blocking: create child task with `parent_task_id` set, add to current step, leave parent in BUILDING
  - `add_peer_task`: create new `TaskState` in current step; persist to DB; executor picks it up on next cycle
  - `add_next_step`: create `StepState`, insert at `current_step_index + 1`, shift all subsequent `order_index` values, persist atomically
- `WorkflowService.expand_task()`: wraps engine call, saves to DB, emits `TaskExpanded` event
- `POST /api/runs/{run_id}/tasks/{task_id}/expand` router: validates request, calls service, returns 429 on budget exhaustion, 409 if task not in build phase
- Human approval mode: when `require_human_approval=True`, create a pending approval record, return `status: "pending_approval"` in response; existing approval infrastructure handles the gate
- Integration tests: `add_subtask` blocking, `add_subtask` non-blocking, `add_peer_task`, `add_next_step` with correct index reordering, budget exhaustion returns 429, build-phase-only validation, provenance in activity events

**Verification:** `uv run pytest tests/integration/ -v` passes, endpoint returns correct shapes.

### M3: Executor + Prompt Integration

**Goal:** Close the loop so agents actually know about the expansion API and the executor correctly handles expanded tasks.

**Deliverables:**
- `workflow/prompts.py`: add expansion callback instructions to builder prompt — available types, when to use them, that they add work (don't transfer parent obligations), and current budget remaining
- Budget remaining is calculated at prompt-generation time and injected as a string (e.g., "Expansions used: 2/10. Subtasks per task: 0/5.")
- `runners/executor.py`: ensure expanded peer tasks (new tasks added mid-step) are discovered and executed — the executor's step-task loop must handle task lists that grow during execution
- `runners/executor.py`: blocking subtask flow — parent pauses after `add_subtask` blocking call; executor detects `FAN_OUT_RUNNING` and runs children; parent resumes via `complete_fan_out_parent`
- MCP tool registration: `expand_task` available as MCP tool alongside `submit_for_verification` and `update_checklist`
- Unit tests: prompt includes expansion instructions, budget string reflects remaining capacity

**Verification:** `uv run pytest tests/unit/ tests/integration/ -v` passes. Manual smoke test confirms expansion instructions appear in builder prompt.

### M4: Frontend Display

**Goal:** Render expansion state in the UI so users can see what was expanded, why, by whom, and the budget usage.

**Deliverables:**
- `ui/src/types/runs.ts` and `ui/src/types/tasks.ts`: add `expanded_from_task_id`, `expansion_justification`, `is_expansion` to task and step types; add `expansion_count`, `expansion_limits` to run types
- `TaskDetailCard.tsx`: expanded children section with cyan/teal accent, "Expanded" badge, provenance info (which task requested it, justification text)
- Step view: peer task expansions with dashed border, "Added by T-XX" label using `expanded_from_task_id`
- `StepTimeline.tsx`: inserted steps get "+" indicator to show they were dynamically added
- `ActivityFeed.tsx`: `TaskExpanded` events rendered prominently (expansion type, title, which task requested, justification)
- Run detail (`RunDetail.tsx`): expansion budget display — "Expansions: 2/10 used" in run metadata area; pending expansion approvals shown in pending actions area when `require_human_approval=True`
- Frontend tests: expansion display in `TaskDetailCard`, inserted step indicator in `StepTimeline`, `TaskExpanded` event in `ActivityFeed`

**Verification:** `npx vitest run` passes, visual inspection of expansion UI.

## Implementation Order

### Step 1: Data Models (M1 core)
**Prerequisites:** None.
**Deliverables:** `ExpansionLimits`, state field additions, DB model additions. No logic yet.
**Why first:** All subsequent steps depend on stable model definitions. DB schema changes are safest to batch.

### Step 2: DB Migration (M1 remaining)
**Prerequisites:** Step 1 (column definitions finalized).
**Deliverables:** Alembic migration for `TaskModel`, `RunModel` new columns. Schemas and event type.
**Why here:** Decoupled from logic — just structure. Keeps migration isolated and reviewable.

### Step 3: Expansion Engine — add_subtask (M2 core)
**Prerequisites:** Steps 1-2.
**Deliverables:** `WorkflowEngine.expand_task()` for `add_subtask` type (blocking and non-blocking). Budget check. Provenance recording. Service wrapper. Event emission.
**Why first among M2:** Most complex type; reuses fan-out path well understood from existing code. Gets the core pattern right before tackling step insertion.

### Step 4: Expansion Engine — add_peer_task + add_next_step (M2 remaining)
**Prerequisites:** Step 3 (engine pattern established).
**Deliverables:** `add_peer_task` and `add_next_step` implementations. Step index reordering. Human approval mode.

### Step 5: API Endpoint + Integration Tests (M2 final)
**Prerequisites:** Steps 3-4.
**Deliverables:** Router registration. Full integration test suite for all types and error cases.

### Step 6: Executor + Prompt (M3)
**Prerequisites:** Steps 3-5.
**Deliverables:** Prompt additions. Executor mid-step task discovery. MCP tool.

### Step 7: Frontend (M4)
**Prerequisites:** Step 5 (API contract stable).
**Deliverables:** All UI changes, types, tests.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| `add_subtask` blocking implementation | Reuse `FAN_OUT_RUNNING` + `complete_fan_out_parent` | Fan-out infrastructure already handles parent-wait-for-children correctly; avoids duplicating complex async logic |
| Budget enforcement granularity | Five independent limits + total | Prevents any single expansion type from dominating; total cap prevents compound abuse |
| Budget exhaustion response | 429 with clear message | Standard HTTP semantics for rate limiting; message explains which limit was hit |
| Phase restriction | Only during build phase | Verified tasks shouldn't be able to spawn new work; completed tasks are done |
| `add_next_step` index shifting | Shift `order_index` on all subsequent steps atomically | Consistent with existing `order_index` pattern; atomic DB update prevents partial states |
| Human approval mode | Pending action on task, not a new run state | Reuse existing approval infrastructure; avoids new state machine transitions |
| Budget tracking | Counter on `Run` + counter on `TaskState` | Run total enforces global cap; per-task counter enforces per-task subtask limit |
| Prompt budget display | Calculated at prompt-generation time | Agent knows current remaining budget before deciding whether to expand |
| MCP tool | Registered alongside existing callback tools | Consistent with submit/checklist pattern; agents already know how to call these |

## Risks and Unknowns

| Risk | Mitigation |
|------|------------|
| Executor doesn't discover peer tasks added mid-step | Refresh task list from DB at each executor loop iteration; test with integration test that adds peer task and verifies it executes |
| `add_next_step` index shift conflicts with `current_step_index` on concurrent requests | Use DB transaction for step insertion + index shift; run-level lock already held during step transitions |
| Blocking subtask from fan-out parent (nested fan-out) | Detect and reject: `add_subtask` blocking disallowed if task already has `parent_task_id` set (avoids double-nesting) |
| Human approval mode creates deadlock if approval never arrives | No automatic timeout; users must approve/reject; document this; future enhancement could add expiry |
| Agent calls expand in a loop, exhausting budget before doing actual work | Budget limits; `expansions_requested` tracked per task; consider rate-limiting at prompt level (document that expansion is for discovered scope, not design-time planning) |
| DB migration on large DBs with many existing tasks/steps | Defaults for new columns ensure no data change; additive migration only |
| Step insertion concurrency (two agents insert steps simultaneously) | Run-level lock in `InMemoryLockManager` prevents concurrent writes; acceptable limitation for current scale |

## References

- [idea.md](idea.md) — Full feature specification
- `src/orchestrator/workflow/engine.py` — Workflow state machine
- `src/orchestrator/runners/executor.py` — Fan-out implementation (L1009–L1314)
- `src/orchestrator/config/models.py` — `RoutineConfig`, `StepConfig`, `FanOutConfig`
- `src/orchestrator/state/models.py` — `TaskState`, `StepState`, `Run`
- `src/orchestrator/db/models.py` — `TaskModel`, `StepModel`, `RunModel`
- `src/orchestrator/workflow/events.py` — Event types
- `src/orchestrator/api/routers/tasks.py` — Task endpoint patterns
- `docs/conditional-steps/plan.md` — Prior feature plan for reference on plan format
