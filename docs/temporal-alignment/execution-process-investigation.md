# ExecutionProcess Superclass Investigation

## Context

This document investigates whether a shared `ExecutionProcess` base class should be
introduced to unify the state and lifecycle of Runs, fan-out children, and Attempts.

The prior art is `BaseActivityAdapter` (M3) — a thin abstract base that puts shared
lifecycle logic (`_tasks` dict, `start`/`cancel`, `_build_execution_context`) in one
place and lets runner-specific behaviour be explicit overrides. The same principle is
the question here: identify what is genuinely shared, evaluate whether a base class
serves the code better than a shared interface.

---

## 1. Shared State and Lifecycle: What Do Runs and Fan-out Children Have in Common?

### 1.1 Run (the top-level execution unit)

Fields relevant to execution identity and lifecycle (from `state/models.py` and
`db/models.py`):

| Field | Purpose |
|---|---|
| `id` | Stable UUID identity |
| `status` | `DRAFT → ACTIVE → PAUSED → COMPLETED / FAILED` |
| `pause_reason` | Why the run is paused (e.g., `server_shutdown`, `gate_blocked`) |
| `last_error` | Terminal error message |
| `created_at`, `updated_at`, `started_at`, `completed_at` | Lifecycle timestamps |
| `agent_started_at` | When the agent subprocess actually began |
| `steps` / `current_step_index` | Progression through workflow steps |
| `total_tokens_*`, `total_duration_ms`, `total_num_actions` | Aggregate metrics |
| `worktree_path` | Isolated filesystem environment |
| `source_branch` | Git branch for the worktree |

Event association: every `WorkflowEvent` carries `run_id`. The events table has a
`run_id` FK. The run's full lifecycle is captured as an ordered event stream.

### 1.2 Fan-out Children (TaskState with `parent_task_id`)

Fan-out children are `TaskState` objects (same model as regular tasks) with extra
fields:

| Field | Purpose |
|---|---|
| `id` | Task UUID (but generated at expansion time, not durable across restarts today) |
| `status` | `PENDING → ACTIVE → VERIFYING → COMPLETED / FAILED` (TaskStatus enum) |
| `parent_task_id` | Link to the parent task |
| `fan_out_index` | 0-based position in the fan-out set |
| `fan_out_input` | Input path matched by the glob |
| `fan_out_output` | Derived output path |
| `attempts` | List of `Attempt` records |
| `current_attempt` | Index into attempts list |
| `max_attempts` | Retry ceiling |

Children do **not** have their own event stream — all lifecycle events (`ChildSpawned`,
`ChildCompleted`, `ChildFailed`) are emitted into the parent run's event stream tagged
with `child_task_id`.

Children do **not** have their own worktree; they share the parent run's worktree.
Children do **not** have their own run-level heartbeat; they rely on the parent
executor's `RunWorkflow` loop.

### 1.3 Attempts

Attempts are the unit of one build/verify cycle within a task (normal or fan-out child):

| Field | Purpose |
|---|---|
| `id` | UUID (generated at creation) |
| `attempt_num` | 1-based counter within the parent task |
| `started_at`, `completed_at` | Lifecycle timestamps |
| `outcome` | `passed`, `revision_needed`, `failed`, `None` (in progress) |
| `agent_type`, `agent_model`, `agent_settings` | Agent snapshot at attempt start |
| `start_commit`, `end_commit` | Git provenance of this attempt |
| `metrics` | `AttemptMetrics` (tokens, duration, num_actions) |
| `grade_snapshot` | Verifier grades at completion time |
| `auto_verify_results` | Results from auto-verification |
| `builder_prompt`, `verifier_prompt` | The prompts used |
| `agent_output`, `error` | Captured output or failure reason |
| `action_log` | Structured tool call log |

Attempts do **not** have a `status` field — their state is implicit: no `started_at`
means pending; `started_at` set, no `completed_at` means active; `outcome` set means
terminal.

Attempts have **no independent event stream** — their lifecycle is inferred from task-level
events (`TaskStatusChanged`) and attempt-level events (`GradeEvaluated`,
`AutoVerifyCompleted`).

---

## 2. Does a Shared `ExecutionProcess` Base Make Sense?

### 2.1 What Would It Share?

If we defined a base class `ExecutionProcess`, it would need to capture things that
are genuinely common across Runs, fan-out children, and Attempts. Examining the three:

**Runs and fan-out children share:**
- A status lifecycle (though different enums: `RunStatus` vs `TaskStatus`)
- Lifecycle timestamps (`started_at`, `completed_at`)
- Aggregate metrics
- Linkage to a parent (Runs have no parent; fan-out children have `parent_task_id`)
- Attempt containers

**Runs and Attempts share:**
- Lifecycle timestamps
- Metrics (Runs aggregate; Attempts record per-unit)
- Git provenance (`start_commit`, `end_commit` on both)
- Agent snapshot fields

**Fan-out children and Attempts share:**
- Both are sub-units within a Run
- Both have `attempt_num`-style sequencing
- Both have outcome / error fields

**What does NOT share well:**
- Status enums are different: `RunStatus`, `TaskStatus` — structurally similar but
  semantically distinct and non-interchangeable
- Worktree: only Runs have one
- Event stream ownership: only Runs own the stream; children and attempts emit *into*
  the run's stream
- Heartbeat: only Runs (via the executor loop) have a heartbeat
- The attempt lifecycle is *implicit* (inferred from fields) while Run/Task lifecycles
  are *explicit* (a `status` field)

### 2.2 The `BaseActivityAdapter` Analogy

`BaseActivityAdapter` works well because:
1. All four adapters do the exact same lifecycle management (`_tasks` dict, asyncio Task
   creation, cleanup on cancel)
2. The divergences are pure overrides (`start` body for ClaudeSdk; callbacks for Codex)
3. The shared logic is non-trivial enough to justify a base (avoids duplicating ~40 lines
   across four concrete classes)

For an `ExecutionProcess` base, the analogous question is: *what non-trivial logic
would be shared?* The answer is: **not much that isn't already shared by virtue of
using the same model types.**

- Lifecycle timestamps and status transitions live in the service layer, not in the
  models themselves — there's no shared method body to extract
- Metrics aggregation is already handled by `AttemptMetrics` and summed at the service layer
- Event emission is centralized in `PersistentEventEmitter`, not on the entity

A base class here would be a data-carrying base with no real behaviour — essentially
a marker interface with shared fields. That's useful for typing but not for logic
reuse.

---

## 3. Concrete Recommendation

**Recommendation: Keep types separate; introduce a shared `AttemptRecord` interface.**

### Rationale

The three types (Run, TaskState/fan-out child, Attempt) have different enough
responsibilities that a unified base would create more confusion than clarity:

- `Run` owns the worktree, the event stream, and the outer retry/pause/resume lifecycle.
  It maps to a Temporal Workflow.
- `TaskState` (including fan-out children) is a unit of work within a Run. It maps to
  a Temporal Activity or Child Workflow.
- `Attempt` is the historical record of one execution of a task. It maps to a Temporal
  Activity execution (activity ID + attempt number).

These are three genuinely distinct concepts. Forcing them into a common base would blur
those distinctions and make the Temporal mapping harder to explain.

**What to do instead:**

### 3a. Introduce `AttemptRecord` as a typed canonical shape

The fan-out gaps (documented in `temporal-alignment.md`) reveal that attempt storage
is inconsistent: fan-out children have attempts but the attempt event model is thin.

Define a canonical `AttemptRecord` — not a base class but a typed data structure that
every attempt (normal, fan-out child, script) is stored as. This ensures:

```python
@dataclass
class AttemptRecord:
    """Canonical shape for one execution attempt, regardless of task type."""
    id: str                          # Stable UUID — durable across restarts
    task_id: str                     # Which task this attempt belongs to
    attempt_num: int                 # 1-based within the task
    status: AttemptStatus            # pending | active | completed | failed
    started_at: datetime | None
    completed_at: datetime | None
    outcome: str | None              # passed | revision_needed | failed
    agent_type: AgentRunnerType | None
    agent_model: str | None
    start_commit: str | None
    end_commit: str | None
    metrics: AttemptMetrics
    error: str | None
    # ... other fields as needed
```

This is analogous to what `BaseActivityAdapter` does: it doesn't change who owns the
logic, but it enforces a consistent shape that code can depend on.

### 3b. Give fan-out children their own `child_run_id` or stable attempt IDs

Today fan-out children are `TaskState` objects but their `id` is generated at expansion
time. If the run is paused and restarted, the child task IDs survive in the DB, but
there's no guarantee they're consistently addressable across replay.

The fix is **not** to make children into Runs (that would add unnecessary overhead), but
to:
1. Assign child task IDs deterministically (e.g., `f"{parent_task_id}-child-{index}"`)
   so they're stable and predictable from the parent's event stream
2. Give each child attempt a stable UUID, stored explicitly in `AttemptRecord.id`, so
   fan-out child attempts are first-class records, not embedded sub-objects

### 3c. Add `status` to Attempt explicitly

The implicit attempt lifecycle (inferred from `started_at`/`completed_at`/`outcome`
presence) should be made explicit:

```python
class AttemptStatus(str, Enum):
    PENDING = "pending"      # created, not yet started
    ACTIVE = "active"        # agent executing
    COMPLETED = "completed"  # outcome set (passed / revision_needed)
    FAILED = "failed"        # terminal failure
```

This enables event-sourced reconstruction of attempt state without ambiguity.

---

## 4. Impact on Fan-out Child Implementation (T-02)

The recommendation above directly shapes what T-02 should do:

1. **Stable child task IDs**: generate as `f"{parent_task_id}-child-{fan_out_index:04d}"`
   or use a deterministic UUID5 derived from `(parent_task_id, fan_out_index)`. This
   makes child IDs predictable from the parent's event stream without a DB lookup.

2. **Per-child event tags**: child lifecycle events (`ChildSpawned`, `ChildCompleted`,
   `ChildFailed`) already carry `child_task_id`. T-02 should ensure that attempt-level
   events for fan-out children also carry `child_task_id` so per-child attempt history
   is filterable from the parent stream.

3. **Canonical `AttemptRecord` for children**: fan-out child attempts should use the
   same `AttemptRecord` shape as normal task attempts. No special-casing.

4. **No separate Run per child**: fan-out children remain `TaskState` objects within
   the parent run. They do not become separate `Run` rows. This keeps the data model
   simple and avoids the complexity of run-to-run linkage, at the cost of all children
   sharing the parent's event stream (filtered by `child_task_id`).

5. **No `ExecutionProcess` base in T-02**: T-02 does not need to introduce a shared
   base class. It should focus on stable IDs, canonical attempt shape, and richer
   per-child event payloads.

---

## 5. Temporal Compatibility Considerations

The `distributed-work-queue/temporal-alignment.md` document already captures the
Run → Workflow and TaskState/Attempt → Activity mapping. This investigation adds:

### 5.1 Fan-out children → Temporal Child Workflows or Activities?

Two options exist for a future Temporal mapping of fan-out children:

**Option A: Fan-out children as Temporal Child Workflows**
- Each child gets its own workflow history
- Supports independent pause/resume/cancel per child
- Adds per-child overhead (workflow registration, history management)
- Better match when children are long-running or need independent lifecycle control

**Option B: Fan-out children as Temporal Activities**
- Children are retryable activities within the parent workflow
- Simpler: no child workflow registration needed
- Parent waits via `await asyncio.gather(...)` on activity futures
- Better match when children are bounded and short-lived
- Parent can aggregate results inline

**Recommendation for Temporal mapping (deferred):** Design for Option B (activities)
but keep child IDs stable so upgrading to Option A is a data-model addition, not a
rewrite. The key invariant: each child has a stable `child_task_id` and each child
attempt has a stable `attempt_id` that would map to a Temporal activity ID in Option A
or a Temporal activity attempt number in Option B.

### 5.2 Attempt IDs → Temporal Activity IDs

In Temporal's async-completion model, an activity is started by the workflow,
runs externally (like our CLI/HTTP agents), and calls `activity.complete()` when done.
The Temporal Activity ID maps directly to our `Attempt.id`.

Pre-condition for migration: every attempt must have a stable UUID that is assigned
*before* the agent starts (so the agent can use it as a callback identifier). Today
`Attempt.id` is generated at creation time, which is already correct — but it's not
yet surfaced in the agent's callback context. T-02 (or a subsequent task) should
ensure `attempt_id` is included in `ActivityContext` so agents can reference it in
callback calls.

### 5.3 Attempt Status Reconstruction

Temporal reconstructs activity state from the event history (scheduled, started,
completed, failed events). Our event model today relies on `TaskStatusChanged` events
which reflect task-level status, not attempt-level boundaries.

For Temporal parity, add explicit attempt-boundary events:
- `AttemptStarted(task_id, attempt_id, attempt_num, agent_type, start_commit)`
- `AttemptCompleted(task_id, attempt_id, outcome, end_commit, metrics)`
- `AttemptFailed(task_id, attempt_id, error, end_commit)`

This maps cleanly to Temporal's `ActivityScheduled`, `ActivityStarted`,
`ActivityCompleted`, `ActivityFailed` history event types.

---

## 6. Open Questions for Future Temporal Mapping Decision

1. **Fan-out as activities or child workflows?** The recommendation above defers this.
   The key input needed: do fan-out children need independent pause/resume/cancel, or
   is all lifecycle control mediated through the parent? If independent lifecycle
   control is needed, child workflows are correct. If not, activities are simpler.

2. **Where do child event streams live if children become child workflows?** Temporal
   child workflows have their own execution ID and their own event history. Our current
   model emits child events into the parent run stream tagged with `child_task_id`. A
   Temporal migration would split these into separate histories. Decide: do we want
   a per-child stream today (preparing for migration) or a tagged parent stream
   (simpler now, migration refactor later)?

3. **Attempt IDs as Temporal Activity IDs?** Temporal Activity IDs are strings assigned
   by the workflow at schedule time. Our `Attempt.id` UUIDs are equivalent. But Temporal
   also has a concept of *activity attempt number* (separate from Temporal's `ScheduleToStart`
   timeout retry count). Clarify the mapping before migration.

4. **Do script tasks (non-agent tasks, if they exist) share the `AttemptRecord` shape?**
   If the system adds first-class script tasks (run a shell command as a workflow step),
   they would also generate attempts. The canonical shape should accommodate them.

5. **Deterministic vs. random child task IDs?** Deterministic IDs (UUID5 from parent +
   index) make replay safer but require that expansion is idempotent (same inputs →
   same IDs). Random UUIDs are simpler but require the expansion event to be the
   authoritative source of child IDs. The choice affects replay correctness when fan-out
   expansion is re-run after a crash mid-expansion.

---

## Summary

| Question | Finding |
|---|---|
| Do Runs, fan-out children, and Attempts share meaningful lifecycle logic? | Partially: shared timestamps, metrics patterns, and status concepts — but different enums and different ownership |
| Should `ExecutionProcess` base class be introduced? | **No** — would blur distinct concepts (Workflow vs. Activity vs. Activity Execution) without extracting real shared logic |
| What *should* be standardized? | Canonical `AttemptRecord` shape; explicit `AttemptStatus` enum; stable child task IDs |
| How does this affect T-02? | T-02 should implement stable child IDs, canonical attempt shape for fan-out children, and richer per-child event payloads — not a new base class |
| Is the design Temporal-compatible? | Yes: keeps Run → Workflow, TaskState → Activity, Attempt → Activity Execution mapping clean; defers choice of child-workflow vs. activity for fan-out |
