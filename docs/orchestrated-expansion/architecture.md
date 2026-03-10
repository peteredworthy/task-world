# Architecture: Orchestrated Expansion (Option D)

## Current State

The orchestrator's run model is fully static after creation. `create_run_from_routine()` builds all steps and tasks up-front. The executor processes tasks sequentially through the step list, with no mechanism for agents to request new work. Fan-out (`FAN_OUT_RUNNING`) is the only dynamic behavior, and it is configured statically in the routine YAML.

**Key files and their roles:**

| File | Role |
|------|------|
| `src/orchestrator/config/models.py` | `RoutineConfig`, `StepConfig`, `TaskConfig` — routine YAML shape |
| `src/orchestrator/state/models.py` | `Run`, `StepState`, `TaskState` — runtime state |
| `src/orchestrator/db/models.py` | `RunModel`, `StepModel`, `TaskModel` — persistent storage |
| `src/orchestrator/workflow/engine.py` | `WorkflowEngine` — state transitions |
| `src/orchestrator/workflow/service.py` | `WorkflowService` — persistence + event emission wrapper |
| `src/orchestrator/runners/executor.py` | `Executor` — drives agents, handles fan-out (`_execute_fan_out` at L1009) |
| `src/orchestrator/workflow/prompts.py` | Builder and verifier prompt generation |
| `src/orchestrator/workflow/events.py` | Event types for activity tracking |
| `src/orchestrator/api/routers/tasks.py` | Task-level API endpoints |
| `src/orchestrator/api/schemas/tasks.py` | Task API schemas |
| `ui/src/components/detail/TaskDetailCard.tsx` | Task detail rendering including fan-out children |
| `ui/src/components/dashboard/StepTimeline.tsx` | Step timeline rendering |
| `ui/src/components/detail/ActivityFeed.tsx` | Activity event rendering |

## Proposed Changes

### New Components

#### `ExpansionLimits` — `src/orchestrator/config/models.py`

```python
class ExpansionLimits(BaseModel):
    max_subtasks_per_task: int = 5
    max_peer_tasks_per_step: int = 3
    max_inserted_steps: int = 2
    max_total_expansions: int = 10
    require_human_approval: bool = False
```

Added to `RoutineConfig` as `expansion_limits: ExpansionLimits = Field(default_factory=ExpansionLimits)`.

#### `ExpansionRequest` / `ExpansionResponse` — `src/orchestrator/api/schemas/tasks.py`

`add_next_step` supports multiple tasks via a `tasks` array (Q2 decision). Single-task types (`add_subtask`, `add_peer_task`) use top-level `title`/`context`/`requirements`. For `add_next_step`, the `tasks` array defines all tasks in the new step; top-level `title` becomes the step title.

```python
class ExpansionTaskSpec(ApiModel):
    """Specification for a single task within an add_next_step expansion."""
    title: str
    context: str
    requirements: list[dict] | None = None
    agent_profile: str | None = None

class ExpansionRequest(ApiModel):
    type: Literal["add_subtask", "add_peer_task", "add_next_step"]
    title: str          # Task title for add_subtask/add_peer_task; step title for add_next_step
    context: str        # Task context for add_subtask/add_peer_task; ignored for add_next_step
    justification: str
    requirements: list[dict] | None = None  # For add_subtask/add_peer_task checklist
    blocking: bool = True
    agent_profile: str | None = None
    tasks: list[ExpansionTaskSpec] | None = None  # Required for add_next_step (multiple tasks)

class ExpansionResponse(ApiModel):
    status: Literal["created", "pending_approval"]
    expansion_type: str
    created_task_id: str | None = None        # Set for add_subtask and add_peer_task
    created_step_id: str | None = None        # Set for add_next_step
    created_task_ids: list[str] | None = None # Set for add_next_step (all tasks in new step)
    total_expansions_used: int
    budget_remaining: dict[str, int]  # which limits remain
```

#### `TaskExpanded` event — `src/orchestrator/workflow/events.py`

```python
class TaskExpanded(WorkflowEvent):
    requesting_task_id: str
    expansion_type: str  # "add_subtask" | "add_peer_task" | "add_next_step"
    created_task_id: str | None
    created_step_id: str | None
    justification: str
    blocking: bool
    approved: bool  # False if pending human approval
```

### Modified Components

#### `TaskState` — `src/orchestrator/state/models.py`

Add fields:
```python
expansions_requested: int = 0
expanded_from_task_id: str | None = None
expansion_justification: str | None = None
```

#### `Run` — `src/orchestrator/state/models.py`

Add field:
```python
total_expansions: int = 0
```

#### `TaskModel` — `src/orchestrator/db/models.py`

Add columns (Alembic migration):
```python
expanded_from_task_id = Column(String, ForeignKey("tasks.id"), nullable=True)
expansion_justification = Column(String, nullable=True)
is_expansion = Column(Boolean, default=False, nullable=False)
```

#### `StepModel` — `src/orchestrator/db/models.py`

Add columns (Alembic migration, Q1 decision):
```python
is_expansion = Column(Boolean, default=False, nullable=False)
expanded_from_task_id = Column(String, ForeignKey("tasks.id"), nullable=True)
```

These record whether a step was dynamically inserted and which task requested the insertion.

#### `RunModel` — `src/orchestrator/db/models.py`

Add column:
```python
expansion_count = Column(Integer, default=0, nullable=False)
```

#### `WorkflowEngine.expand_task()` — `src/orchestrator/workflow/engine.py`

New method implementing all three expansion types:

```python
async def expand_task(
    self,
    run: Run,
    task_id: str,
    request: ExpansionRequest,
    expansion_limits: ExpansionLimits,
) -> tuple[TaskState | None, StepState | None]:
    """
    Validates budget, creates new task/step state, records provenance.
    Returns (created_task, created_step) — one will be None depending on type.
    Raises ExpansionBudgetError if any limit is exhausted.
    Raises ExpansionPhaseError if task is not in build phase.
    """
```

**Budget checks (in order):**
1. Task not in `BUILDING` status → raise `ExpansionPhaseError` (409)
2. `total_expansions >= max_total_expansions` → raise `ExpansionBudgetError` (429)
3. For `add_subtask`: `task.expansions_requested >= max_subtasks_per_task` → 429
4. For `add_peer_task`: count peer tasks in current step → if `>= max_peer_tasks_per_step` → 429
5. For `add_next_step`: count previously inserted steps → if `>= max_inserted_steps` → 429

**Per-type implementation:**

`add_subtask` + `blocking=True`:
- Create `TaskState` with `parent_task_id=task_id`, `expanded_from_task_id=task_id`, `expansion_justification=justification`, `is_expansion=True`
- Add to current step's `tasks` list
- Call `expand_fan_out_task()` logic to set parent to `FAN_OUT_RUNNING` (reuses existing infrastructure exactly as static fan-out does)
- Executor's existing `_execute_fan_out` path handles the rest

`add_subtask` + `blocking=False`:
- Create `TaskState` with `parent_task_id=task_id` and expansion fields set
- Add to current step; parent remains `BUILDING`
- Executor picks up new task on next cycle (requires task list refresh)

`add_peer_task`:
- Create `TaskState` with `expanded_from_task_id=task_id`, no `parent_task_id`
- Add to current step alongside existing tasks
- Parent remains `BUILDING`; executor picks up peer on next cycle

`add_next_step`:
- Create `StepState` with tasks built from `request.tasks` array (each `ExpansionTaskSpec` becomes a `TaskState`); `request.title` becomes the step title. `request.tasks` must have at least one entry — validation error if empty/missing.
- Mark new `StepState` with `is_expansion=True` and `expanded_from_task_id=task_id`
- Insert into `run.steps` at `current_step_index + 1`
- Increment `order_index` of all steps at index > `current_step_index` by 1
- Return `(None, new_step_state)`

#### `WorkflowService.expand_task()` — `src/orchestrator/workflow/service.py`

```python
async def expand_task(
    self,
    run_id: str,
    task_id: str,
    request: ExpansionRequest,
) -> ExpansionResponse:
    """Load run, call engine.expand_task(), persist, emit TaskExpanded event."""
```

Persists new task/step to DB, updates `RunModel.expansion_count`, emits `TaskExpanded`.

When `require_human_approval=True`: instead of calling engine, create a pending approval record on the task (`pending_action_type="expansion_approval"`), return `status="pending_approval"`. On approval, complete the expansion; on rejection, return a rejection response.

#### `POST /api/runs/{run_id}/tasks/{task_id}/expand` — `src/orchestrator/api/routers/tasks.py`

```python
@router.post("/{run_id}/tasks/{task_id}/expand")
async def expand_task(
    run_id: str,
    task_id: str,
    request: ExpansionRequest,
    service: WorkflowService = Depends(get_workflow_service),
) -> ExpansionResponse:
    ...
```

Error mapping:
- `ExpansionBudgetError` → 429
- `ExpansionPhaseError` → 409
- Task not found → 404

#### `workflow/prompts.py` — Builder prompt additions

New section added to builder callback instructions:

```
## Expansion API (Optional)

If you discover work that is genuinely outside this task's scope, you may request expansion:

# For add_subtask and add_peer_task:
POST /api/runs/{run_id}/tasks/{task_id}/expand
{
  "type": "add_subtask" | "add_peer_task",
  "title": "Short descriptive title",
  "context": "Full task context for the new work",
  "justification": "Why this expansion is needed",
  "requirements": [{"id": "R1", "desc": "...", "must": true}],
  "blocking": true  # set false if parent can continue independently
}

# For add_next_step (supports multiple tasks in the new step):
POST /api/runs/{run_id}/tasks/{task_id}/expand
{
  "type": "add_next_step",
  "title": "Step title",
  "justification": "Why this step is needed",
  "tasks": [
    {"title": "Task 1", "context": "...", "requirements": [...]},
    {"title": "Task 2", "context": "..."}
  ]
}

Types:
- add_subtask: creates a child task; with blocking=true, you pause until it completes
- add_peer_task: creates a parallel task in the current step (non-blocking)
- add_next_step: inserts a new step after this step (for discovered prerequisites)

Current budget: {used}/{total} expansions used. Remaining: subtasks {s_used}/{s_max}, peer tasks {p_used}/{p_max}, inserted steps {i_used}/{i_max}.

IMPORTANT: Expansion adds work — it does NOT transfer your obligations. You must still complete all requirements in this task.
```

#### `runners/executor.py` — Mid-step task discovery

The executor's task loop currently iterates over a snapshot of tasks at step start. Add a refresh step after each task completes to pick up newly added peer tasks and non-blocking subtasks:

```python
# After completing a task, refresh task list from DB
tasks = await service.get_step_tasks(run_id, step_id)
pending = [t for t in tasks if t.status == TaskStatus.PENDING]
```

For blocking subtasks: the executor detects `FAN_OUT_RUNNING` (existing check at L743-L747) and delegates to `_execute_fan_out`. No changes needed there — the expansion engine sets `FAN_OUT_RUNNING` the same way static fan-out does.

### Interactions

```
Builder Agent                Expansion API               Workflow Engine            Executor
─────────────                ─────────────               ───────────────            ────────
POST /expand                 validate budget
 type: add_subtask           validate phase
 blocking: true              call engine.expand_task()
                               create child TaskState
                               set parent FAN_OUT_RUNNING
                               persist to DB
                               emit TaskExpanded
                             return 200

                                                          next executor cycle:
                                                           detect FAN_OUT_RUNNING
                                                           _execute_fan_out()
                                                             run child tasks
                                                             complete_fan_out_parent()
                                                           parent resumes BUILDING

POST /expand                 validate budget
 type: add_next_step         validate phase
                             call engine.expand_task()
                               create StepState
                               insert at index+1
                               shift subsequent indices
                               persist atomically
                               emit TaskExpanded
                             return 200
                                                          (step insertion visible
                                                          at next run state load;
                                                          current step continues)

POST /expand                 require_human_approval=True
 (any type)                  create pending_action
                             return pending_approval
                                          ↓
                             UI shows approval request
                             human approves
                             POST /approve
                             engine.expand_task() executes
                             emit TaskExpanded
```

## Technology Choices

| Choice | Option Selected | Alternatives Considered | Rationale |
|--------|----------------|------------------------|-----------|
| `add_subtask` blocking implementation | Reuse `FAN_OUT_RUNNING` / `complete_fan_out_parent` | New state machine state; separate blocking mechanism | Fan-out already handles concurrent children, resumption, and cancellation correctly; duplicating this logic would be risky |
| Budget exhaustion response | 429 with JSON body specifying which limit | 403 Forbidden; custom error code | 429 is standard HTTP for "too many requests" / rate limiting; easy for agents to detect |
| Step index tracking after insertion | `order_index` DB column increment for affected steps | Recompute on every load; position in array only | `order_index` already used for steps; atomic DB update preserves ordering on restart |
| Expansion phase restriction | Only `BUILDING` status allowed | Allow in any non-terminal status | Verified tasks have a defined scope that shouldn't change; prevents expanding after human already reviewed |
| Human approval | Pending action on task (`pending_action_type`) | New run pause state; separate approval table | Existing `pending_action_type` infrastructure handles similar patterns (clarifications, approvals); reuse avoids new state machine |
| Mid-step task discovery | Refresh task list after each task completes | Polling loop; separate watcher | Refresh after completion is minimal overhead; natural refresh point in existing executor loop |
| Budget counters | Per-task `expansions_requested` + run-level `total_expansions` | Single counter only; no run-level counter | Need both: per-task to enforce per-task limit, run-level for total cap |

## Testing Strategy

### Unit Tests — `tests/unit/`

**Budget enforcement** (`tests/unit/test_expansion_budget.py`):
- `max_total_expansions` reached → `ExpansionBudgetError` raised
- `max_subtasks_per_task` reached → error (but other task can still expand)
- `max_peer_tasks_per_step` reached → error
- `max_inserted_steps` reached → error
- `require_human_approval=True` → pending response, not immediate execution
- Budget decrements correctly after successful expansion

**Phase validation** (`tests/unit/test_expansion_phase.py`):
- Task in `VERIFYING` → `ExpansionPhaseError`
- Task in `PASSED` → `ExpansionPhaseError`
- Task in `BUILDING` → allowed
- Task in `FAN_OUT_RUNNING` → not applicable; an agent in `FAN_OUT_RUNNING` is not executing and cannot call the API (Q3 decision — no test case needed)

**Step index reordering** (`tests/unit/test_expansion_step_insert.py`):
- Insert step at index 1 of 3 → steps at index 2, 3 shift to 3, 4
- Insert at last position → no existing steps shift
- Insert multiple times → indices remain consistent

### Integration Tests — `tests/integration/`

**Expansion lifecycle** (`tests/integration/test_expansion.py`):
- `add_subtask` blocking: parent transitions to `FAN_OUT_RUNNING`, child executes, parent resumes
- `add_subtask` non-blocking: child created, parent continues building independently
- `add_peer_task`: peer task created in current step, executor picks it up, step doesn't complete until all tasks (including peer) are done
- `add_next_step`: step inserted after current, current step completes normally, new step is next
- Budget exhaustion: sixth expansion attempt on a run with `max_total_expansions=5` returns 429
- Provenance: `TaskExpanded` event in activity feed includes justification and requesting task ID
- Wrong phase: attempt to expand a `VERIFYING` task returns 409
- Human approval: expansion with `require_human_approval=True` creates pending action; approval triggers expansion; rejection cancels

### Frontend Tests — `ui/src/`

**TaskDetailCard** (additions to existing test file):
- Task with `expanded_from_task_id` set renders "Expanded" badge
- Expansion provenance section shows requesting task ID and justification
- Expanded children section with cyan accent for tasks with `parent_task_id` matching expansion

**StepTimeline** (additions):
- Step with `is_expansion=True` renders "+" indicator
- Regular steps not affected

**ActivityFeed** (additions):
- `TaskExpanded` event renders with expansion type, title, requesting task, and justification

## Security Considerations

- **Append-only invariant enforced at engine level** — `expand_task()` never modifies existing tasks/steps/requirements. Only creates new ones.
- **Phase validation at engine level** — Cannot expand completed or verified tasks, even via direct API calls.
- **Budget limits are routine-level config** — Agents can't change their own limits.
- **`add_next_step` doesn't skip existing steps** — Inserts at `current_step_index + 1`, not at an arbitrary position.
- **No cross-run expansion** — `task_id` is validated to belong to `run_id`; creating tasks in other runs is not possible.
- **Justification is required** — Provides audit trail and makes expansions reviewable.

## Performance Considerations

- **Step index reordering is bounded** — Only steps after insertion point are updated; typically a small number (routine rarely has >10 steps).
- **Mid-step task refresh is O(tasks in step)** — Small; happens only after each task completes.
- **Budget checks are O(1)** — Counter comparisons against stored integers.
- **Human approval mode adds no background load** — Pending actions are checked only on task load.
