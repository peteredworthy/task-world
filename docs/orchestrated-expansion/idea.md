# Option D: Orchestrated Expansion (Append-Only Runtime Dynamism)

## Idea

Give running tasks the ability to request additional work through the orchestrator, replacing untracked tool escape hatches (agents shelling out to sub-agents) with tracked, verified, visible work items. The key constraint is **append-only**: agents can add new tasks and steps but can never remove or weaken existing requirements.

Currently, routines are fully static once a run starts. If a builder task discovers work needs to be subdivided, or needs a specialist sub-agent (e.g., a security reviewer), or discovers a prerequisite that wasn't planned, it has no way to express this through the orchestration system. The only options are: (a) do everything within the single task context, losing visibility and verification granularity, or (b) shell out to sub-agents via tools, bypassing orchestration entirely.

## What to Build

### 1. Expansion API Endpoint

A new endpoint `POST /api/runs/{run_id}/tasks/{task_id}/expand` that accepts structured expansion requests. This follows the same callback pattern as `submit_for_verification` — it's an MCP tool or REST call made by the builder agent during its build phase.

```python
class ExpansionRequest(ApiModel):
    type: Literal["add_subtask", "add_peer_task", "add_next_step"]
    title: str
    context: str  # task_context for the new work
    justification: str  # why this expansion is needed
    requirements: list[dict] | None = None  # optional requirements
    blocking: bool = True  # if true, parent waits for completion
    agent_profile: str | None = None  # optional specialist profile
    phases: list[str] | None = None  # future: custom phase list (for Option A)
```

### 2. Expansion Types

- **add_subtask**: Creates a child task under the requesting task. Uses existing parent/child linking (same as fan-out). If `blocking=True`, parent transitions to `FAN_OUT_RUNNING` and waits. If `blocking=False`, child runs independently.

- **add_peer_task**: Creates a new task in the current step. Runs in parallel with other tasks. Always non-blocking from the parent's perspective (parent continues its own build phase).

- **add_next_step**: Inserts a new step immediately after the current step. All subsequent step indices shift. The new step has its own tasks with full verification. This is the most impactful expansion type — use for discovered prerequisites.

### 3. Budget & Limits System

Each run has expansion limits to prevent runaway growth:

```python
class ExpansionLimits(BaseModel):
    max_subtasks_per_task: int = 5
    max_peer_tasks_per_step: int = 3
    max_inserted_steps: int = 2
    max_total_expansions: int = 10
    require_human_approval: bool = False
```

These are configurable per routine in the YAML:

```yaml
routine:
  id: my-routine
  expansion_limits:
    max_subtasks_per_task: 3
    max_total_expansions: 5
```

When a budget is exhausted, the expand endpoint returns 429 with a clear message.

### 4. Provenance Tracking

Every expansion records:
- Which task requested it and why (justification)
- When it was created
- The expansion type
- Whether it was auto-approved or human-approved

This is stored on the new task/step and emitted as an activity event.

### 5. Expansion Callback in Agent Prompts

The builder prompt must include expansion instructions, similar to how it includes submit/checklist callback instructions. The prompt should explain:
- When to use expansion (discovered work that can't be done within the current task)
- What types are available
- That expansion adds work, it doesn't transfer the parent's obligations
- Budget limits

This goes in `workflow/prompts.py` as part of the builder prompt callback instructions.

### 6. Human Approval Mode

When `require_human_approval: true`, expansions create a pending approval request instead of immediately executing. The UI shows the expansion request with the agent's justification, and the human approves or rejects.

## Codebase Context

Key files to modify:

- **Config models** (`src/orchestrator/config/models.py`): Add `ExpansionLimits` model. Add `expansion_limits` field to `RoutineConfig`.
- **State models** (`src/orchestrator/state/models.py`): Add expansion tracking fields to `TaskState` (e.g., `expansions_requested: int = 0`, `expanded_from_task_id: str | None = None`, `expansion_justification: str | None = None`). Add to `Run` level: `total_expansions: int = 0`.
- **DB models** (`src/orchestrator/db/models.py`): Add columns for expansion provenance on TaskModel and StepModel. Add `expansion_count` to RunModel.
- **API schemas** (`src/orchestrator/api/schemas/tasks.py`): Add `ExpansionRequest` and `ExpansionResponse` schemas.
- **API router** (`src/orchestrator/api/routers/tasks.py`): Add `POST /runs/{run_id}/tasks/{task_id}/expand` endpoint.
- **Workflow engine** (`src/orchestrator/workflow/engine.py`): Add `expand_task()` method that validates budget, creates new task/step state, records provenance, and handles blocking/non-blocking modes.
- **Workflow service** (`src/orchestrator/workflow/service.py`): Add `expand_task()` that wraps engine call with persistence and event emission. For `add_subtask` with `blocking=True`, reuse `expand_fan_out_task` / `complete_fan_out_parent` mechanics.
- **Executor** (`src/orchestrator/runners/executor.py`): Expansion callback instructions must be included in the builder prompt. When a blocking subtask is created, the executor must pause the parent and handle resumption.
- **Prompts** (`src/orchestrator/workflow/prompts.py`): Add expansion callback instructions to builder prompt. Include available expansion types and current budget remaining.
- **Events** (`src/orchestrator/workflow/events.py`): Add `TaskExpanded` event type with expansion details.
- **State factory** (`src/orchestrator/state/factory.py`): Ensure expansion limits are loaded from routine config.

### Frontend Changes

- **Task detail card** (`ui/src/components/detail/TaskDetailCard.tsx`): Show expansion section when a task has expanded children. Display similar to fan-out children but with a distinct visual treatment — cyan/teal accent color, "Expanded" badge, provenance info (which task requested it, justification).
- **Step view**: Peer task expansions should be visually distinct from original tasks — dashed border, "Added by T-XX" label.
- **Step timeline** (`ui/src/components/dashboard/StepTimeline.tsx`): Inserted steps need visual treatment — perhaps a "+" indicator showing they were dynamically added.
- **Activity feed** (`ui/src/components/detail/ActivityFeed.tsx`): Expansion events should be prominent — show what was expanded, why, and by which task.
- **Types** (`ui/src/types/runs.ts`, `ui/src/types/tasks.ts`): Add expansion-related fields to task and step types. `expanded_from_task_id`, `expansion_justification`, `is_expansion: boolean`.
- **Run detail** (`ui/src/pages/RunDetail.tsx`): If human approval is required for expansions, show pending expansion approvals in the pending actions area.
- **Budget display**: Show expansion budget usage somewhere in the run detail (e.g., "Expansions: 2/10 used").

### Implementation Strategy — Reuse Fan-Out

The `add_subtask` with `blocking=True` should reuse as much of the fan-out infrastructure as possible:
- Parent transitions to `FAN_OUT_RUNNING`
- Child tasks have `parent_task_id` set
- When all children complete, `complete_fan_out_parent()` is called
- The parent continues from where it left off

The difference from static fan-out:
- Children are created one at a time by the agent, not all at once from a glob
- The agent may continue to expand (add more subtasks) while in FAN_OUT_RUNNING
- Each child has independently authored requirements and context (not templated from a pattern)

### Step Insertion Mechanics

For `add_next_step`:
- Get current step index
- Create new StepState with tasks
- Insert into run.steps at current_step_index + 1
- All subsequent steps shift their index
- The run's step count increases
- Must handle the case where current step hasn't completed yet (the inserted step will run after current step completes)

## Safety Invariants

1. Original tasks, steps, and requirements are NEVER modified by expansion
2. New work goes through the same build/verify pipeline
3. Budget limits prevent unbounded growth
4. Parent task's own requirements must still be met regardless of expansions
5. Expansion is only allowed during build phase (not verify, not completed)
6. All expanded work is visible in UI and activity log

## Relationship to Other Options

- **After Option C** (conditional steps): Independent, no dependency
- **Before Option B** (gap analyzer): B's `spawn_fix` action becomes a consumer of D's expansion API
- **Enhances Option A** (phase pipelines): Expanded tasks could specify custom phases (future)

## Tests

- Unit tests for budget enforcement (limit reached → 429)
- Unit tests for expansion validation (only during build phase, valid types)
- Integration tests for add_subtask (blocking and non-blocking)
- Integration tests for add_peer_task
- Integration tests for add_next_step (verify step reindexing)
- Integration test for human approval mode
- Integration test for provenance tracking in activity events
- Frontend tests for expansion display in TaskDetailCard
- Frontend tests for inserted step display in StepTimeline
