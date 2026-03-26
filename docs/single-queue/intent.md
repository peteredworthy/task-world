# Single-Queue Signal Model

## Purpose

Replace the dual-path signal routing with a single, uniform queue through which all
lifecycle signals pass. In the current model `WorkflowService` inspects a process-local
`_active_run_ids` set at enqueue time and either writes to the `pending_signals` table
or mutates the DB directly. This document specifies the target model and what must be
true when the work is complete.

---

## Out of Scope

- Separate runner processes. The goal is to not make that move harder, not to do it now.
- Event broadcast decoupling (`EventBroadcaster` / WebSocket/SSE). That is the remaining
  coupling point for future runner separation and is left for a follow-on piece of work.
- Any performance optimisation of the queue.

---

## The Target Model

All signals for all run lifecycle transitions are written to `pending_signals` before
any state change occurs. A consumer (the existing executor, restructured) reads from
the queue and routes each signal to the appropriate handler. The consumer is the sole
entity that creates and destroys `RunWorkflow` instances.

```
API / service layer
  └── writes signal to pending_signals (always, no routing decision)

Consumer (runs inside the executor process)
  └── reads signals in FIFO order per run_id
       ├── RUN_START / RUN_RESUME  →  create RunWorkflow, transition DB state
       ├── PAUSE / CANCEL          →  set run to STOPPING, deliver to RunWorkflow if active
       │                              OR apply directly to DB if no RunWorkflow is running
       ├── ACTIVITY_COMPLETED      →  deliver to RunWorkflow (as today)
       └── ACTIVITY_VERIFIED       →  deliver to RunWorkflow (as today)
```

---

## Requirements

### Signal table

**R1.** The `pending_signals` table primary key is a monotonically increasing integer
assigned by the database at insert time (`INTEGER PRIMARY KEY` / `BIGSERIAL`). The
current UUID string PK is removed.

**R2.** All drain queries order by the integer PK, not by `created_at`.

**R3.** The table gains two nullable timestamp columns: `delivered_at` (set when the
consumer dispatches the signal to a handler) and `handled_at` (set when the handler
returns without error). A signal with `handled_at IS NULL` and `delivered_at IS NOT NULL`
represents a signal that was dispatched but not yet acknowledged.

**R4.** `created_at` is retained as an audit field but is not used for ordering.

### Run state machine

**R5.** `RunStatus` gains a `STOPPING` value. It is entered from `ACTIVE` only, when
the consumer picks up a `PAUSE` or `CANCEL` signal for a run that has an active
`RunWorkflow`.

**R6.** The following transitions are the only valid ones involving `STOPPING`:

| From     | Signal / event                        | To       |
|----------|---------------------------------------|----------|
| ACTIVE   | consumer picks up PAUSE or CANCEL     | STOPPING |
| STOPPING | RunWorkflow acknowledges pause        | PAUSED   |
| STOPPING | RunWorkflow acknowledges cancel       | FAILED   |
| STOPPING | RunWorkflow crashes during stopping   | FAILED   |

**R7.** `WorkflowEngine.start_task()` rejects a run in `STOPPING` state with the same
class of error as it would for a `PAUSED` run.

**R8.** `WorkflowEngine.submit_for_verification()` rejects a run in `STOPPING` state.

**R9.** No other state machine transition accepts `STOPPING` as a source state. A run
in `STOPPING` cannot be resumed, restarted, or have a second PAUSE or CANCEL enqueued
by the API.

### Signal types

**R10.** A new `RUN_START` signal is added to `WorkflowSignal`. It is enqueued when a
run transitions from `DRAFT` to `ACTIVE` (`POST /runs/{id}/start`). The consumer
handles it by applying the DRAFT → ACTIVE DB transition and creating a `RunWorkflow`.

**R11.** The `RESUME` signal is no longer a no-op. The consumer handles it by applying
the PAUSED → ACTIVE DB transition and creating a `RunWorkflow`. The `handle_resume`
handler on `RunWorkflow` that currently logs "ignoring RESUME signal (already running)"
is removed.

**R12.** `PAUSE` and `CANCEL` signals carry the same payload fields they do today.
No new payload fields are required by this change.

### Sender-side routing removed

**R13.** `WorkflowService.pause_run()` always enqueues a `PAUSE` signal. The
`has_active_workflow` check and the direct-DB branch are removed.

**R14.** `WorkflowService.cancel_run()` always enqueues a `CANCEL` signal. The
`has_active_workflow` check and the direct-DB branch are removed.

**R15.** `WorkflowService.resume_run()` always enqueues a `RESUME` signal. The
`has_active_workflow` check and the direct-DB branch are removed.

**R16.** `WorkflowService.start_run()` always enqueues a `RUN_START` signal. It no
longer calls `executor.spawn_run()` directly or transitions run state itself.

**R17.** `retry_fan_out_child()` in `WorkflowService` removes its own
`has_active_workflow` check. If the run is ACTIVE it enqueues a `PAUSE` signal;
the consumer handles the ACTIVE → STOPPING → PAUSED transition.

### Consumer

**R18.** The consumer processes signals for each `run_id` serially (FIFO). It may
process signals for different runs concurrently.

**R19.** The consumer is the sole place that calls `register_active_run()` and
`unregister_active_run()`. No other code calls these functions.

**R20.** Before delivering a `PAUSE` or `CANCEL` signal to an active `RunWorkflow`,
the consumer updates the run status to `STOPPING` in the DB and commits that change.
It then delivers the signal. If no `RunWorkflow` is active, the consumer applies the
appropriate terminal transition (PAUSED or FAILED) directly without going through
STOPPING.

**R21.** The consumer sets `delivered_at` on a signal before invoking the handler and
`handled_at` after the handler returns successfully. If the handler raises, `handled_at`
is left null and the signal is eligible for redelivery on the next consumer pass.

**R22.** On startup, the consumer drains any signals with `delivered_at IS NOT NULL AND
handled_at IS NULL` for runs that are not currently being driven (i.e., the server
restarted mid-delivery). These are re-delivered.

**R23.** The `RunWorkflow.handle_pause` handler no longer calls
`unregister_active_run()` before delegating to `service.pause_run()`. The consumer
manages registration state; the handler only applies the state transition.

### Active-run registry

**R24.** `register_active_run()` and `unregister_active_run()` are moved or restricted
to the consumer module. They are not exported from `workflow/signals/signals.py` as part
of the public surface available to `WorkflowService`, routers, or any code outside the
consumer.

**R25.** `has_active_workflow()` is not called from `WorkflowService`, routers, or any
code path initiated by an API request. Its only callers are the consumer and tests that
exercise consumer behaviour directly.

---

## Guards

### Automated check (pre-commit)

A new script `scripts/check_signal_routing.py` is added to the pre-commit hook list.
It statically checks every Python source file and fails if any of the following symbols
are imported or called outside the consumer module
(`src/orchestrator/workflow/signals/consumer.py` or equivalent):

- `has_active_workflow`
- `register_active_run`
- `unregister_active_run`

The check follows the same structure as `scripts/check_module_imports.py`: it uses `ast`
to parse imports and call sites, prints the offending file and line, and exits non-zero
on any violation.

### AGENTS.md rules

The following rules are added to `AGENTS.md` under a new section
**"Signal Queue and Runner Isolation"**:

1. **Do not call `has_active_workflow`, `register_active_run`, or `unregister_active_run`
   outside the consumer module.** These are consumer-internal. The pre-commit check
   enforces this automatically.

2. **Do not add process-local state that both the API layer and the executor need to
   read.** If the API needs to know something about a running workflow, it reads from the
   DB. In-memory shared state (module-level sets, dicts keyed by run_id) that crosses
   the API/executor boundary re-introduces the coupling this change removed.

3. **`RunWorkflow` and `AgentRunnerExecutor` must not access `app.state` or any object
   that only exists in the FastAPI application context.** All dependencies the executor
   needs (DB session factory, config, broadcaster) are injected at construction time via
   `ExecutorCallbacks` or equivalent. Adding a new `app.state.X` access from within
   executor or workflow code is a violation.

4. **All run lifecycle transitions (start, resume, pause, cancel) are initiated by
   enqueueing a signal.** Do not add new code paths that bypass the queue and transition
   run state directly from an API route or service method. Direct DB state changes are
   only valid inside the consumer's own handlers.

---

## Relationship to Temporal Alignment

This change closes the specific gaps called out in `docs/distributed-work-queue/temporal-alignment.md`:

- Signal race condition (section on Signals) — resolved by queue-driven delivery and STOPPING state.
- `RunWorkflow` as a named runtime owner — the consumer making it the sole creator
  of `RunWorkflow` instances reinforces this boundary.
- Process-local registry incompatible with multi-worker — eliminated by R24/R25.

The remaining gap from that document — `EventBroadcaster` relying on in-process
WebSocket connections — is explicitly deferred and not addressed here.
