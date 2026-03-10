# Intent: Orchestrated Expansion (Option D)

## Original Request

Give running tasks the ability to request additional work through the orchestrator, replacing untracked tool escape hatches (agents shelling out to sub-agents) with tracked, verified, visible work items. The key constraint is **append-only**: agents can add new tasks and steps but can never remove or weaken existing requirements.

## Goal

Enable builder agents to dynamically expand the scope of a run during execution — adding subtasks, peer tasks, or entirely new steps — while keeping all work visible in the UI, subject to the same build/verify pipeline, and bounded by configurable budget limits. This replaces the common pattern of agents silently shelling out to sub-processes or doing all discovered work within a single task context.

## Scope

### In Scope

- **Expansion API endpoint** — `POST /api/runs/{run_id}/tasks/{task_id}/expand` accepting `ExpansionRequest` with type, title, context, justification, requirements, blocking flag, and optional agent profile.
- **Three expansion types:**
  - `add_subtask` — creates a child task under the requesting task. Blocking mode reuses fan-out infrastructure (`FAN_OUT_RUNNING` + `complete_fan_out_parent`). Non-blocking creates independent child.
  - `add_peer_task` — creates a new task in the current step, running in parallel. Always non-blocking from parent's perspective.
  - `add_next_step` — inserts a new step immediately after the current step, shifting all subsequent step indices. Full build/verify for all tasks in the new step.
- **Budget and limits system** — `ExpansionLimits` model with `max_subtasks_per_task`, `max_peer_tasks_per_step`, `max_inserted_steps`, `max_total_expansions`, and `require_human_approval`. Configurable per routine in YAML. Exhausted budget → 429 response.
- **Provenance tracking** — Every expansion records requesting task ID, justification, creation timestamp, expansion type, and approval mode. Stored on new task/step and emitted as `TaskExpanded` activity event.
- **Expansion callback in agent prompts** — Builder prompt includes expansion instructions: when to use it, available types, that expansion adds work (doesn't transfer parent obligations), and remaining budget.
- **Human approval mode** — When `require_human_approval: true`, expansions create a pending approval request. UI shows request with justification; human approves or rejects.
- **Frontend display** — Expanded tasks shown with cyan/teal accent, "Expanded" badge, and provenance info in `TaskDetailCard`. Peer expansions in step view have dashed border and "Added by T-XX" label. Inserted steps have "+" indicator in `StepTimeline`. `ActivityFeed` shows expansion events. Budget usage displayed in run detail.
- **Run-level expansion counter** — `total_expansions: int` on `Run` / `RunModel` to enforce `max_total_expansions`.

### Out of Scope

- Phase pipelines (Option A) — separate effort; expansion `phases` field is reserved for future use only.
- Gap analyzer (Option B) — separate effort; B's `spawn_fix` would consume this API as a later enhancement.
- Conditional step execution (Option C) — already implemented; no dependency.
- Removing or modifying existing tasks, steps, or requirements — append-only invariant.
- Expansion during verify phase or after task completion — only allowed during build phase.
- Cross-run expansion (creating tasks in other runs).
- Nested expansion approval (an approval task that itself expands).

## Definition of Complete

- [ ] `ExpansionLimits` Pydantic model exists in `src/orchestrator/config/models.py` with all five fields and defaults.
- [ ] `RoutineConfig` has `expansion_limits: ExpansionLimits` field (optional, defaults to `ExpansionLimits()`).
- [ ] `Run` state model has `total_expansions: int = 0`.
- [ ] `TaskState` has `expansion_justification: str | None`, `expanded_from_task_id: str | None`, and `expansions_requested: int = 0`.
- [ ] `TaskModel` and `StepModel` have DB columns for expansion provenance (`expanded_from_task_id`, `expansion_justification`, `is_expansion: bool`). `RunModel` has `expansion_count` column.
- [ ] `ExpansionRequest` and `ExpansionResponse` schemas exist in `src/orchestrator/api/schemas/tasks.py`.
- [ ] `POST /api/runs/{run_id}/tasks/{task_id}/expand` endpoint is registered and handles all three expansion types.
- [ ] Budget enforcement: endpoint returns 429 when any relevant limit is exhausted.
- [ ] `add_subtask` with `blocking=True` transitions parent to `FAN_OUT_RUNNING` and resumes after child completes, reusing existing fan-out infrastructure.
- [ ] `add_peer_task` creates a new task in the current step and the executor picks it up.
- [ ] `add_next_step` inserts a step at `current_step_index + 1`, shifting subsequent indices, and persists correctly.
- [ ] `TaskExpanded` event type exists and is emitted with expansion details.
- [ ] Builder prompt includes expansion callback instructions with types, budget, and guidance.
- [ ] Human approval mode: when `require_human_approval: true`, expansion creates a pending action; run unblocks when approved or rejected.
- [ ] Frontend: `TaskDetailCard` shows expanded children with cyan accent and provenance info.
- [ ] Frontend: peer task expansions in step view have dashed border and "Added by T-XX" label.
- [ ] Frontend: `StepTimeline` shows "+" indicator for dynamically inserted steps.
- [ ] Frontend: `ActivityFeed` renders `TaskExpanded` events prominently.
- [ ] Frontend: budget usage (e.g., "Expansions: 2/10 used") visible in run detail.
- [ ] Frontend types (`runs.ts`, `tasks.ts`) include `expanded_from_task_id`, `expansion_justification`, `is_expansion`.
- [ ] Unit tests: budget enforcement (all five limits), phase validation (only during build), type validation.
- [ ] Integration tests: `add_subtask` blocking and non-blocking, `add_peer_task`, `add_next_step` with index reordering, human approval mode, provenance in activity events.
- [ ] Frontend tests: expansion display in `TaskDetailCard`, inserted step in `StepTimeline`.
- [ ] All existing tests continue to pass (no regressions).
- [ ] `uv run pre-commit run --all-files` passes.
