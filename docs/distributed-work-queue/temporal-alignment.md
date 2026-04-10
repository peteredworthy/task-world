# Temporal Alignment: Learning from Temporal's Design

## Purpose

This document is not a migration guide. It's a vocabulary and architecture alignment so that:

1. Our code uses the same **conceptual primitives** Temporal uses, even if implemented differently
2. A migration to Temporal (or any similar framework) would be structurally obvious, not a rewrite
3. We can adopt Temporal's hard-won design decisions without running their server

The goal is to look at what Temporal got right and ask: *do we have that concept? Is it coherently factored in our code?*

---

## Temporal's Core Model

Temporal models long-running work as **Workflows** composed of **Activities**, executed by **Workers**, coordinated by a **Temporal Server** that maintains durable execution history.

```
Temporal Server (durable execution engine)
  └── Workflow (long-running, stateful, restartable)
        ├── Activity (discrete unit of work, retryable)
        ├── Activity
        └── Child Workflow (composable)
Worker Process (polls task queue, executes activities)
Client (starts workflows, sends signals, queries state)
```

Key guarantees Temporal provides:
- **Durable execution**: workflow state survives worker crashes via history replay
- **Durable workflow progress**: completed workflow steps are not lost on worker restart, but activities still need idempotent/retry-safe boundaries
- **Signals**: external events that mutate running workflow state
- **Queries**: read workflow state without mutating it
- **Timers**: durable sleeps that survive restarts
- **Child workflows**: composable sub-workflows with their own lifecycles

---

## Mapping Our Concepts to Temporal's

### Workflow → Run

Our `Run` is a Temporal Workflow. A run has:
- A defined lifecycle (DRAFT → ACTIVE → PAUSED → COMPLETED/FAILED)
- State that must survive restarts
- A sequence of steps to execute
- The ability to be paused/resumed/cancelled externally

**Current:** `Run` (Pydantic domain model) + `RunModel` (ORM) + `executor._run_agent_loop()`
**Temporal equivalent:** `@workflow.defn class AgentRun`

**Gap:** Our "workflow" is split across three layers with no single owner. The executor loop *is* the workflow runtime, but it's not explicitly modeled as such.

---

### Activity → Task Execution

Our `TaskState` + `Attempt` maps to a Temporal Activity. An activity is:
- A discrete, bounded unit of work
- Retryable (our revision cycle)
- Capable of heartbeating (our executor heartbeat)
- Idempotent within a workflow (our attempt deduplication)

**Current:** `executor._execute_task()` + `WorkflowService.submit_for_verification()` + `complete_verification()`
**Temporal equivalent:** `@activity.defn async def execute_task(task_id: str)`

**Gap:** Our task execution is distributed across executor, service, and API callbacks. Temporal activities are self-contained — they run *to completion* in one worker invocation (or heartbeat and continue). Our model splits execution across agent subprocess + API callback, which is fine but means "activity completion" is an external event (the agent calling `/tasks/{id}/submit`), not a return value.

---

### Worker → Executor

Our `AgentRunnerExecutor` is a Temporal Worker. A worker:
- Polls for work (we poll via `_find_next_task()`)
- Claims tasks exclusively
- Reports heartbeats
- Executes activities

**Current:** `AgentRunnerExecutor` instance per uvicorn process
**Temporal equivalent:** `Worker(task_queue="agent-runs", workflows=[AgentRun], activities=[execute_task])`

**Gap:** Our worker is bound to the HTTP process. Temporal workers are separate processes that poll a task queue. This coupling is fine for now but means scaling workers requires scaling the API server.

---

### Task Queue → Run Queue

Temporal task queues route workflows/activities to appropriate workers. We don't have an explicit queue — work is discovered by scanning the DB.

**Current:** `executor._find_next_task()` scans `run.steps[current_step_index].tasks`
**Temporal equivalent:** Runs enqueued on `agent-runs` task queue; workers long-poll

**Gap:** Without an explicit queue, there's no backpressure, no priority, and no routing to specialized workers (e.g., "only GPU workers handle image tasks"). For now this is fine.

---

### Signal → pause/resume/cancel API

Temporal Signals are typed external events sent to a running workflow. Our pause/resume/cancel API calls are equivalent.

**Current:** `POST /runs/{id}/pause` → `service.pause_run()` → executor cancels asyncio task
**Temporal equivalent:** `workflow.signal("pause")` → workflow sets a flag and blocks

**Gap:** Our signals are fire-and-forget API calls that mutate DB state. Temporal signals are guaranteed-delivered, durable, and processed in-order. Our implementation has a race: if the executor loop is between iterations when a pause comes in, it reads the paused state on the next iteration. This is fine in practice but not formally correct.

A closer alignment: add a `PendingSignal` concept that the executor loop checks before each iteration, processed exactly once.

---

### Query → GET /runs/{id}

Temporal Queries read workflow state synchronously without mutating it. Our `GET /runs/{id}` is the equivalent — it reads from the DB without side effects.

**Current:** `GET /runs/{id}` → `RunRepository.get()` → serialize to response
**Temporal equivalent:** `@workflow.query def get_status()`

**Alignment is good here.** No gap.

---

### Workflow History → Event Journal

Temporal's core durability mechanism is the event history — every state change is appended, and on worker restart the workflow is *replayed* from history to reconstruct state.

Our `.orchestrator/state/history.jsonl` + `events` table is the equivalent. We already have this concept.

**Current:** `EventStore.append()` + JSONL journal + `db.recovery.replay_events()` + `db.journal_replay.replay_journal_to_repository()`
**Temporal equivalent:** Temporal Server's event history + workflow replay

**Gap:** We do have a replay engine, but it is not yet complete enough to treat event history as the sole workflow-control source of truth. Core run/task status and attempt progression can be replayed today, but some control-plane state still depends on persisted snapshots and in-memory conventions.

Temporal enforces this by design: workflows can only mutate state via recorded events. We allow the DB to be the primary source of truth with the journal as an audit log, which is slightly weaker.

---

### Timer → (missing)

Temporal provides durable timers: `await workflow.sleep(timedelta(hours=24))`. The timer survives worker restarts.

**Current:** We have no durable timers. If an agent needs to wait (e.g., retry after 5 minutes), we pause the run and rely on an external trigger to resume.

**Temporal equivalent:** `await workflow.sleep(timedelta(minutes=5))` inside the workflow

**This is a genuine gap.** For our use cases (retry backoff, scheduled runs, timed approvals), we'd need:
- A `scheduled_resume_at` column on `runs`
- A background poller that resumes runs whose `scheduled_resume_at` has passed
- Or integrate with an external scheduler (cron, APScheduler)

---

### Child Workflow → Fan-out

Temporal child workflows are sub-workflows that run independently with their own lifecycle but are logically owned by a parent.

Our fan-out tasks (`FanOutConfig`) are the equivalent — child tasks execute in parallel, parent waits for completion.

**Current:** `executor._execute_fan_out()` creates child tasks in DB, polls for completion
**Temporal equivalent:** `child_handle = await workflow.execute_child_workflow(SubTask, task_id)`

**Alignment is conceptually good.** The main difference: Temporal child workflows can be on different workers and have their own retry policies. Our fan-out is managed entirely by the parent executor today, but we can evolve toward a more explicit **parent/child workflow** model:

- Treat each fan-out branch as a *child workflow instance* with its own identity and lifecycle:
  - Either as separate Runs linked by `parent_run_id` / `parent_task_id`, or
  - As per-branch sub-state machines within a single Run, tagged with a `child_id`.
- Give each child its own event stream (or clearly tagged subset of the parent stream) so its state can be replayed independently.
- Have the parent `RunWorkflow` only depend on:
  - "I spawned children [ids]" events, and
  - "CHILD_COMPLETED(child_id, result)" events.

On replay, the **parent** reconstructs fan-out progress purely from these child events ("which children completed, with what results?") and applies its aggregation logic. The **children** reconstruct their detailed execution from their own histories. This keeps the parent deterministic and simple ("wait for child completions, then decide next step") while making reconstruction of both parent and children straightforward.

---

### Continue-As-New → (not needed yet)

Temporal `continue_as_new` truncates history when it gets too long (Temporal has a 50k event limit per workflow). Our runs are bounded in scope so this isn't relevant yet, but it's worth knowing: very long-running runs (many steps, many revisions) could eventually hit journal size concerns.

---

## Structural Recommendations

These changes bring our code closer to Temporal's model without requiring Temporal. They make reasoning about correctness easier and a future migration more mechanical.

### 1. Formalize the Executor Loop as a Workflow Runtime

Currently the executor loop is an unnamed `while True` inside `_run_agent_loop`. Temporal expects workflows to be defined in code, but our workflow *shape* is defined declaratively in routine YAML. The goal is not to abandon config-driven routines, but to have a **single runtime owner** that interprets that config and owns all state transitions.

Make the structure explicit:

```python
class RunWorkflow:
    """
    The runtime for a single Run. Equivalent to a Temporal workflow function.
    Reconstructible from: run_id + routine config + DB state.
    Communicates via: signals (pause/resume/cancel) and activity completions.
    """
    def __init__(self, run_id: str, worker_id: str): ...

    async def run(self) -> None:
        """Main loop. Must be idempotent on re-entry (restart-safe)."""
        ...

    async def on_signal(self, signal: WorkflowSignal) -> None:
        """Process an external signal. Called between iterations."""
        ...
```

This is mostly a naming/organization change, but it makes the intent visible: this class is the workflow runtime.

### 2. Make Activities Self-Contained

Temporal activities have a clear contract: inputs → outputs, retryable, heartbeatable. They can also complete **asynchronously** (start now, report completion later), which is closer to our reality.

Our task execution is spread across:
- `executor._execute_task()` (spawns agent via a particular runner)
- `POST /tasks/{id}/submit` (agent callback from MCP/tool/HTTP world)
- `executor._find_next_task()` (detects completion / verification)

Because we support multiple agent runners (OpenHands, CLI, user-managed HTTP/MCP) we shouldn't try to model "activity" as a single in-process function. Instead, align at the **boundary**:

```python
class ActivityAdapter(Protocol):
    """
    Runner-facing abstraction for a task activity.
    Each AgentRunner provides an implementation that knows how to:
      - start work for a task
      - cancel work for a task
    The actual work may use MCP, HTTP, or tool calls behind the scenes.
    """
    async def start(self, task_id: str, context: ActivityContext) -> None: ...
    async def cancel(self, task_id: str) -> None: ...
```

`RunWorkflow` then treats "start activity X on runner Y" as emitting an activity, and `/tasks/{id}/submit` + verification endpoints as delivering **activity completion signals** back into the workflow runtime. This matches Temporal's async-completion pattern without forcing all runners into a single execution model.

### 3. Explicit Signal Queue (Without Slowing Anything Down)

Rather than the executor discovering state changes by polling the DB, deliver signals explicitly. This does **not** change the basic latency model (the executor still reacts on its next loop tick) but it centralizes state transitions and removes races.

```python
class WorkflowSignal(Enum):
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    ACTIVITY_COMPLETED = "activity_completed"  # task submitted
    ACTIVITY_VERIFIED = "activity_verified"    # verification complete

@dataclass
class PendingSignal:
    signal: WorkflowSignal
    payload: dict
    created_at: datetime
```

The executor loop drains its signal queue at the top of each iteration before proceeding. This:
- Preserves today's responsiveness: pause/cancel still take effect on the next loop iteration, not "after the task finishes".
- Makes the pause/resume race condition structurally impossible — signals are ordered and processed exactly once.
- Enforces a single entry point for state changes: every transition is "workflow runtime applies signal", rather than ad-hoc DB mutations from multiple call sites.

### 4. Event-Driven State Reconstruction

Move toward being able to reconstruct `Run` state from events alone (no DB `SELECT` required beyond the event log). This aligns with Temporal's replay model.

Concretely: ensure that every state transition emits a sufficiently detailed event that replay can reconstruct a fully operational `Run` — not just the final state, but which step/task is current, why the run is paused, which steps were skipped, and which attempt is active for every task and fan-out child.

Currently some state is still reconstructed imperfectly or only from persisted snapshots. Audit and close these gaps systematically:
- `pause_reason` and `last_error`
- `step.skipped` / `skip_reason`
- attempt-level git metadata (`start_commit`, `end_commit`)
- fan-out child lifecycle and child-attempt progression
- any state derived from parent/child coordination rather than explicit events

This needs to **tie in cleanly with git-based artifacts**. Each attempt that changes the repo already records a `start_commit` / `end_commit` on the attempt; extend the journal so activity-completion events include:
- The task/attempt identifiers
- For fan-out, the child task identifier and child attempt number
- The git commit (or range) that contains the agent's output

That way, replay from events can reconstruct both logical state ("this task was verified as PASS") and *where in git* the corresponding changes live. Temporal would treat these commit IDs as part of the workflow's event payload; we can do the same without Temporal by making commit IDs first-class data in our events.

### 5. Typed Signal Handlers (Temporal-style)

Temporal's `@workflow.signal` decorator registers named signal handlers. Mimic this by making signal handling explicit on the executor:

```python
class RunWorkflow:
    @signal_handler("pause")
    async def handle_pause(self, reason: str) -> None: ...

    @signal_handler("cancel")
    async def handle_cancel(self) -> None: ...

    @signal_handler("activity_completed", task_id=str)
    async def handle_activity_completed(self, task_id: str, result: ActivityResult) -> None: ...
```

This makes it obvious what external events a workflow can receive, which is exactly what Temporal's signal model enforces.

---

## Migration Pre-Work

Before migrating execution to Temporal, close the gaps that would otherwise turn the migration into a semantic rewrite instead of a transport/runtime swap.

### 1. Complete Event-Sourced Reconstruction

Do not migrate while replay is only partial. The current system already has replay machinery, but it is not yet sufficient to rebuild all workflow-control state from events alone.

Pre-work:
- Add replay coverage for `pause_reason`, `last_error`, skipped steps, approval-pending state, and any other control-plane fields the executor relies on.
- Add event payloads for attempt-level git metadata (`start_commit`, `end_commit`) so replay restores both logical progress and repo provenance.
- Add explicit replay tests for pause/resume, manual gates, condition-based skips, recovery, and fan-out resumption.

### 2. Make Activity Boundaries Idempotent

Temporal will retry activities and may redeliver completion paths. Our submit/verify callbacks and runner-facing task lifecycle need stable idempotency boundaries before migration.

Pre-work:
- Assign durable activity identity at the task-attempt level.
- Make `submit`, verification completion, and cancellation duplicate-safe.
- Ensure external callbacks can be applied more than once without double-advancing workflow state.

### 3. Model Fan-Out Attempts Explicitly

Fan-out is the biggest missing piece in the original migration discussion. Parent progress is not enough; child attempt history also needs a durable identity, persistence model, and replay model. This is not only a child-workflow problem, it is also an **attempt storage** problem.

Pre-work:
- Give every fan-out child a stable identity that survives retries and restarts.
- Give every fan-out child attempt a stable identity as well, not just an incrementing `attempt_num`.
- Record child attempt boundaries explicitly: child started, child submitted, child verified, child failed, child retried.
- Persist enough child-attempt metadata to rebuild execution after restart: status, timestamps, agent snapshot, verifier feedback, auto-verify results, error state, and git provenance.
- Decide whether completed child attempts are immutable historical records or can be rewritten in place. Make that rule explicit before migration.
- Record parent aggregation events explicitly: children spawned, child completed, fan-out completed, fan-out failed.
- Add replay tests that prove a paused or restarted executor can resume a partially completed fan-out without duplicating completed child work.
- Add replay tests that prove child attempts are restored correctly, not just child terminal status. A restored run must know which child attempt is active, which attempts already passed, and which failed attempts are eligible for retry.
- Decide whether fan-out children will become Temporal child workflows or Temporal activities before migration starts. Both can work, but the event model should match that choice.

### 4. Normalize Attempt Storage Across All Task Types

The fan-out gaps expose a broader issue: attempts exist today for both normal tasks and fan-out children, but the event model does not yet capture enough attempt-level detail to make replay the authoritative source. A Temporal migration will force this to be explicit.

Pre-work:
- Define the canonical attempt record shape for every execution mode: normal task, fan-out child, script task, recovery retry.
- Ensure attempt creation, completion, retry, and failure are represented consistently in events and persistence.
- Stop relying on implicit reconstruction from `task_status_changed` alone for fields such as agent metadata, verifier feedback, and git commit boundaries.
- Decide whether attempt IDs will map directly to Temporal Activity IDs or remain application-level identifiers correlated to Temporal execution metadata.

### 5. Extract a Real Workflow Runtime Boundary

The current executor loop is close to a workflow runtime, but the ownership is still split across executor, service, and API callbacks.

Pre-work:
- Introduce a single runtime owner for run progression.
- Route external state changes through typed workflow inputs rather than ad-hoc service mutations.
- Keep the DB as a projection for UI/API concerns, not as the implicit workflow interpreter.

### 6. Separate Worker Concerns from API Hosting

Today the executor is created inside the API app process. That coupling is acceptable now, but it hides the deployment boundary that a Temporal migration will formalize.

Pre-work:
- Make worker startup, shutdown, and liveness independent from the web app.
- Ensure run execution can be hosted outside the API process without changing workflow semantics.
- Preserve the current API contract while moving execution responsibility behind a cleaner boundary.

### 7. Build Parity Tests Before the Migration

Do not rely on “it should map cleanly” as the migration safety plan. Capture the current behavior in tests first.

Pre-work:
- Add end-to-end parity fixtures for linear execution, revision cycles, recovery, condition-based skips, manual approvals, and fan-out.
- Assert parity on run status, current step/task, attempt counts, pause reasons, and git metadata.
- Include crash/restart cases so the migrated runtime is validated against the exact failure modes Temporal is meant to improve.

---

## What a Migration to Temporal Would Require

If you ever wanted to actually run on Temporal:

1. **Run a Temporal Server** (Docker or Temporal Cloud)
2. **Wrap `RunWorkflow` as a Temporal workflow** — register with `@workflow.defn`, replace `asyncio.sleep` polls with `await workflow.sleep()`
3. **Wrap agent execution as Temporal activities** — `@activity.defn`, heartbeating via `activity.heartbeat()`
4. **Replace `/pause`, `/resume` API calls with `workflow.signal()`**
5. **Replace `GET /runs/{id}` with `workflow.query()`** (or keep reading from DB — both work)
6. **Introduce dedicated worker processes only if/when operationally valuable**:
   - Temporal's model is “many workflows per worker process”, **not** “one process per run”.
   - You can keep running multiple runs concurrently per process, as today; the main change is that workers talk to Temporal Server over gRPC instead of scanning the DB directly.
7. **Let Temporal handle**: worker claims, heartbeat timeouts, orphan recovery, signal delivery, history durability.

The DB would still hold canonical run state for the UI and API. Temporal (or a Temporal-like runtime we own) would be the execution engine, not the data store. Aligning our internal model (centralized workflow runtime + signals + activities) keeps the communication simple within a single process today while making a later separation of API and workers a mechanical deployment choice rather than a redesign.

---

## Summary Table

| Temporal Concept | Our Current Equivalent | Gap |
|---|---|---|
| Workflow | `Run` + `_run_agent_loop` | Split across 3 layers, not explicitly named |
| Activity | `TaskState` + `Attempt` + agent subprocess | Completion is external callback, not return value |
| Worker | `AgentRunnerExecutor` | Bound to HTTP process |
| Task Queue | DB scan in `_find_next_task()` | No explicit queue, no backpressure |
| Signal | pause/resume/cancel API | Race condition possible; no ordering guarantee |
| Query | `GET /runs/{id}` | Well-aligned |
| Event History | `history.jsonl` + `events` table + replay engine | Replay exists, but control-state reconstruction is incomplete |
| Timer | — | Missing; need `scheduled_resume_at` + poller |
| Child Workflow | Fan-out tasks | Conceptually aligned, but child attempt identity/replay needs work |
| Continue-As-New | — | Not needed yet |
