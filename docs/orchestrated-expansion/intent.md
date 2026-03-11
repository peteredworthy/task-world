# Intent: Orchestrated Expansion (Option D)

## Original Request

Give running tasks the ability to request additional work through the orchestrator, replacing untracked tool escape hatches (agents shelling out to sub-agents) with tracked, verified, visible work items. The key constraint is **append-only**: agents can add new tasks and steps but can never remove or weaken existing requirements. [S-01/T-04/R4, S-01/T-02/R1, S-01/T-04/R1, S-03/T-02/R3, S-05/T-01/R1]

## Goal

Enable builder agents to dynamically expand the scope of a run during execution — adding subtasks, peer tasks, or entirely new steps — while keeping all work visible in the UI, subject to the same build/verify pipeline, and bounded by configurable budget limits. [S-01/T-01/R1, S-01/T-01/R2, S-05/T-01/R1, S-05/T-01/R3, S-07/T-02/R1] This replaces the common pattern of agents silently shelling out to sub-processes or doing all discovered work within a single task context. [S-06/T-01/R1, S-06/T-02/R1]

## Scope

### In Scope

- **Expansion API endpoint** — `POST /api/runs/{run_id}/tasks/{task_id}/expand` accepting `ExpansionRequest` with type, title, context, justification, requirements, blocking flag, optional agent profile, and a `tasks` array (for `add_next_step` to specify multiple tasks in the new step). [S-01/T-04/R1, S-05/T-01/R1]
- **Three expansion types:** [S-03/T-02/R1, S-04/T-01/R1, S-04/T-02/R1]
  - `add_subtask` — creates a child task under the requesting task. Blocking mode reuses fan-out infrastructure (`FAN_OUT_RUNNING` + `complete_fan_out_parent`). Non-blocking creates independent child. [S-03/T-02/R1, S-03/T-02/R2]
  - `add_peer_task` — creates a new task in the current step, running in parallel. Always non-blocking from parent's perspective. [S-04/T-01/R1]
  - `add_next_step` — inserts a new step immediately after the current step, shifting all subsequent step indices. Supports multiple tasks in the new step via a `tasks` array in the request. Full build/verify for all tasks in the new step. [S-04/T-02/R1, S-04/T-02/R2, S-01/T-04/R3]
- **Budget and limits system** — `ExpansionLimits` model with `max_subtasks_per_task`, `max_peer_tasks_per_step`, `max_inserted_steps`, `max_total_expansions`, and `require_human_approval`. Configurable per routine in YAML. Exhausted budget → 429 response. [S-01/T-01/R1, S-01/T-01/R2, S-05/T-01/R3]
- **Provenance tracking** — Every expansion records requesting task ID, justification, creation timestamp, expansion type, and approval mode. Stored on new task/step and emitted as `TaskExpanded` activity event. [S-01/T-05/R1, S-03/T-03/R3, S-05/T-03/R1]
- **Expansion callback in agent prompts** — Builder prompt includes expansion instructions: when to use it, available types, that expansion adds work (doesn't transfer parent obligations), and remaining budget. [S-06/T-01/R1, S-06/T-01/R2]
- **Human approval mode** — When `require_human_approval: true`, expansions create a pending approval request. UI shows request with justification; human approves or rejects. [S-04/T-03/R1, S-04/T-03/R2, S-04/T-03/R3, S-07/T-04/R2]
- **Frontend display** — Expanded tasks shown with cyan/teal accent, "Expanded" badge, and provenance info in `TaskDetailCard`. Peer expansions in step view have dashed border and "Added by T-XX" label. Inserted steps have "+" indicator in `StepTimeline`. `ActivityFeed` shows expansion events. Budget usage displayed in run detail. [S-07/T-02/R1, S-07/T-02/R2, S-07/T-03/R1, S-07/T-03/R2, S-07/T-03/R3, S-07/T-04/R1]
- **Run-level expansion counter** — `total_expansions: int` on `Run` / `RunModel` to enforce `max_total_expansions`. [S-01/T-02/R2, S-01/T-03/R3]

### Out of Scope

- Phase pipelines (Option A) — separate effort; expansion `phases` field is reserved for future use only. [NO-REQ: explicitly out of scope, no routine requirement needed]
- Gap analyzer (Option B) — separate effort; B's `spawn_fix` would consume this API as a later enhancement. [NO-REQ: explicitly out of scope]
- Conditional step execution (Option C) — already implemented; no dependency. [NO-REQ: pre-existing feature]
- Removing or modifying existing tasks, steps, or requirements — append-only invariant. [S-01/T-02/R1, S-01/T-04/R1]
- Expansion during verify phase or after task completion — only allowed during build phase. [S-03/T-02/R3]
- Cross-run expansion (creating tasks in other runs). [NO-REQ: explicitly out of scope]
- Nested expansion approval (an approval task that itself expands). [NO-REQ: explicitly out of scope]

## Definition of Complete

- [ ] `ExpansionLimits` Pydantic model exists in `src/orchestrator/config/models.py` with all five fields and defaults. [S-01/T-01/R1]
- [ ] `RoutineConfig` has `expansion_limits: ExpansionLimits` field (optional, defaults to `ExpansionLimits()`). [S-01/T-01/R2]
- [ ] `Run` state model has `total_expansions: int = 0`. [S-01/T-02/R2]
- [ ] `TaskState` has `expansion_justification: str | None`, `expanded_from_task_id: str | None`, and `expansions_requested: int = 0`. [S-01/T-02/R1]
- [ ] `TaskModel` has DB columns: `expanded_from_task_id`, `expansion_justification`, `is_expansion`. `StepModel` has DB columns: `is_expansion`, `expanded_from_task_id` (Q1 decision — both model types track provenance). `RunModel` has `expansion_count` column. [S-01/T-03/R1, S-01/T-03/R2, S-01/T-03/R3]
- [ ] `ExpansionRequest`, `ExpansionTaskSpec`, and `ExpansionResponse` schemas exist in `src/orchestrator/api/schemas/tasks.py`; `ExpansionRequest.tasks` is a `list[ExpansionTaskSpec]` used for `add_next_step` multi-task creation (Q2 decision). [S-01/T-04/R1, S-01/T-04/R2, S-01/T-04/R3]
- [ ] `POST /api/runs/{run_id}/tasks/{task_id}/expand` endpoint is registered and handles all three expansion types. [S-05/T-01/R1]
- [ ] Budget enforcement: endpoint returns 429 when any relevant limit is exhausted. [S-05/T-01/R3, S-05/T-03/R2]
- [ ] `add_subtask` with `blocking=True` transitions parent to `FAN_OUT_RUNNING` and resumes after child completes, reusing existing fan-out infrastructure. [S-03/T-02/R1]
- [ ] `add_peer_task` creates a new task in the current step and the executor picks it up. [S-04/T-01/R1, S-06/T-02/R1]
- [ ] `add_next_step` inserts a step at `current_step_index + 1`, shifting subsequent indices, and persists correctly. [S-04/T-02/R1, S-04/T-02/R2]
- [ ] `TaskExpanded` event type exists and is emitted with expansion details. [S-01/T-05/R1, S-03/T-03/R3]
- [ ] Builder prompt includes expansion callback instructions with types, budget, and guidance. [S-06/T-01/R1, S-06/T-01/R2]
- [ ] Human approval mode: when `require_human_approval: true`, expansion creates a pending action; run unblocks when approved or rejected. [S-04/T-03/R1, S-04/T-03/R2, S-04/T-03/R3]
- [ ] Frontend: `TaskDetailCard` shows expanded children with cyan accent and provenance info. [S-07/T-02/R1, S-07/T-02/R2]
- [ ] Frontend: peer task expansions in step view have dashed border and "Added by T-XX" label. [S-07/T-03/R1]
- [ ] Frontend: `StepTimeline` shows "+" indicator for dynamically inserted steps. [S-07/T-03/R2]
- [ ] Frontend: `ActivityFeed` renders `TaskExpanded` events prominently. [S-07/T-03/R3]
- [ ] Frontend: budget usage (e.g., "Expansions: 2/10 used") visible in run detail. [S-07/T-04/R1]
- [ ] Frontend types (`runs.ts`, `tasks.ts`) include `expanded_from_task_id`, `expansion_justification`, `is_expansion`. [S-07/T-01/R1, S-07/T-01/R2]
- [ ] Unit tests: budget enforcement (all five limits), phase validation (only during build), type validation. [S-03/T-04/R1, S-03/T-04/R2, S-04/T-04/R1]
- [ ] Integration tests: `add_subtask` blocking and non-blocking, `add_peer_task`, `add_next_step` with index reordering, human approval mode, provenance in activity events. [S-05/T-03/R1, S-05/T-03/R2, S-05/T-03/R3]
- [ ] Frontend tests: expansion display in `TaskDetailCard`, inserted step in `StepTimeline`. [S-07/T-05/R1, S-07/T-05/R2]
- [ ] All existing tests continue to pass (no regressions). [S-01/T-06/R2, S-03/T-04/R3, S-05/T-03/R4, S-07/T-05/R2]
- [ ] `uv run pre-commit run --all-files` passes. [S-07/T-05/R4]
