# Single-Queue Signal Model — Architecture

**Source:** `docs/single-queue/intent.md`, `docs/single-queue/plan.md`
**Last updated:** 2026-03-26

---

## Overview

This document describes how the single-queue signal model integrates with the existing
orchestrator architecture, the key component interactions, and the testing strategy.

---

## Current Architecture (Before)

```
API Router / WorkflowService
  ├── has_active_workflow(run_id)?
  │     ├── YES → mutate DB directly + deliver to RunWorkflow in-process
  │     └── NO  → write to pending_signals table
  │
  └── executor.spawn_run() ← called directly from start_run()

pending_signals table
  └── Polled by executor for runs not yet active
```

**Problems:**
- Sender must know whether a RunWorkflow is active (process-local state).
- Two code paths for every lifecycle operation (direct vs. queued).
- Race condition: `has_active_workflow` can be stale by the time the branch executes.
- `register/unregister_active_run` called from multiple modules (service, workflow, executor).

---

## Target Architecture (After)

```
API Router / WorkflowService
  └── ALWAYS writes signal to pending_signals (no routing decision)

Consumer (single module, runs inside executor process)
  └── Polls pending_signals ordered by integer PK
       ├── RUN_START   → DRAFT→ACTIVE, create RunWorkflow, register
       ├── RESUME      → PAUSED→ACTIVE, create RunWorkflow, register
       ├── PAUSE       → if active: ACTIVE→STOPPING→PAUSED, unregister
       │                  if not active: →PAUSED directly
       ├── CANCEL      → if active: ACTIVE→STOPPING→FAILED, unregister
       │                  if not active: →FAILED directly
       ├── ACTIVITY_COMPLETED → deliver to RunWorkflow
       └── ACTIVITY_VERIFIED  → deliver to RunWorkflow
```

**Key properties:**
- Single code path for every lifecycle operation.
- Consumer is sole owner of RunWorkflow lifecycle and active-run registry.
- `STOPPING` state makes in-flight pause/cancel observable.
- `delivered_at`/`handled_at` enable crash recovery without message loss.

---

## Component Interactions

### Signal Flow: Start a Run

```
POST /api/runs/{id}/start
  → WorkflowService.start_run()
    → INSERT INTO pending_signals (signal_type='RUN_START', run_id=...)
    → return 202 Accepted

Consumer loop (next poll cycle):
  → SELECT from pending_signals WHERE handled_at IS NULL ORDER BY id
  → Pick up RUN_START signal
  → SET delivered_at = now()
  → Transition run DRAFT → ACTIVE in DB
  → Create RunWorkflow instance
  → register_active_run(run_id)
  → SET handled_at = now()
```

### Signal Flow: Pause an Active Run

```
POST /api/runs/{id}/pause
  → WorkflowService.pause_run()
    → INSERT INTO pending_signals (signal_type='PAUSE', run_id=...)
    → return 202 Accepted

Consumer loop:
  → Pick up PAUSE signal
  → SET delivered_at = now()
  → Check: is RunWorkflow active for this run_id?
    → YES:
      → Transition run ACTIVE → STOPPING in DB
      → Deliver PAUSE to RunWorkflow.handle_pause()
      → RunWorkflow acknowledges (completes current work)
      → Transition run STOPPING → PAUSED in DB
      → unregister_active_run(run_id)
      → SET handled_at = now()
    → NO:
      → Transition run directly to PAUSED
      → SET handled_at = now()
```

### Crash Recovery Flow

```
Consumer startup:
  → SELECT from pending_signals
    WHERE delivered_at IS NOT NULL
    AND handled_at IS NULL
  → For each signal:
    → If run_id has no active RunWorkflow (server restarted):
      → Re-dispatch signal through normal handler
    → This covers: server died between delivered_at and handled_at
```

---

## State Machine: STOPPING

```
         PAUSE/CANCEL signal
              │
   ┌──────────┴──────────┐
   │                      │
   ▼                      ▼
ACTIVE ──→ STOPPING    (no active RunWorkflow)
              │              │
   ┌──────┬──┘              │
   │      │                 │
   ▼      ▼                 ▼
PAUSED  FAILED          PAUSED/FAILED
(ack)   (ack or crash)  (direct transition)
```

**Guards on STOPPING:**
- Cannot resume, restart, or enqueue duplicate pause/cancel.
- `start_task()` rejects with same error class as PAUSED.
- `submit_for_verification()` rejects.

---

## Database Changes

### `pending_signals` table

| Column | Before | After |
|--------|--------|-------|
| PK | `id TEXT (UUID)` | `id INTEGER PRIMARY KEY AUTOINCREMENT` |
| `created_at` | Used for ordering | Audit only, not used in ORDER BY |
| `delivered_at` | — | `TIMESTAMP NULL` (set when consumer dispatches) |
| `handled_at` | — | `TIMESTAMP NULL` (set when handler returns OK) |

### `runs` table

| Column | Change |
|--------|--------|
| `status` | Add `STOPPING` as valid value |

---

## Module Boundaries

```
src/orchestrator/
  ├── api/
  │   └── routers/runs.py      # Calls WorkflowService only. No registry access.
  ├── workflow/
  │   ├── service.py            # Enqueues signals only. No has_active_workflow.
  │   ├── engine.py             # State machine guards (rejects STOPPING).
  │   ├── run_workflow.py       # Handler logic. No registry calls.
  │   └── signals/
  │       ├── signals.py        # Signal types, enqueue function. Registry NOT exported.
  │       └── consumer.py       # Consumer loop. SOLE owner of registry functions.
  └── executor.py               # Starts consumer on init. No direct spawn_run calls.
```

**Enforced by:** `scripts/check_signal_routing.py` (pre-commit hook) — fails on
`has_active_workflow`, `register_active_run`, or `unregister_active_run` imports/calls
outside `consumer.py`.

---

## Integration Points

### With Existing Executor

The consumer runs inside the existing executor process. It replaces the current
direct-spawn paths in `executor.py`. The executor's role narrows to:
1. Starting the consumer loop on application startup.
2. Providing the `RunWorkflow` factory (DB session, config, broadcaster injected).
3. Managing agent subprocess lifecycle (unchanged).

### With Existing API

API routes continue to call `WorkflowService` methods. The only change is that
these methods now return immediately after enqueueing (202 Accepted pattern for
start/pause/resume/cancel). The API does not wait for the consumer to process
the signal.

### With EventBroadcaster

No changes. The consumer creates `RunWorkflow` instances the same way the executor
does today. `EventBroadcaster` continues to receive events from within `RunWorkflow`
handlers. This coupling is explicitly deferred (out of scope [I-19]).

### With Frontend

The frontend already polls for run status updates. The `STOPPING` state needs to
be added to the frontend `RunStatus` type and displayed appropriately (e.g.,
"Stopping..." indicator). This is a minor UI change.

---

## Testing Strategy

### Unit Tests

| Area | What to Test | Location |
|------|-------------|----------|
| STOPPING state machine | Valid/invalid transitions, guard rejections | `tests/unit/test_stopping_state.py` |
| Consumer dispatch | FIFO ordering, delivery tracking, error handling | `tests/unit/test_signal_consumer.py` |
| Signal handlers | Each signal type with/without active RunWorkflow | `tests/unit/test_signal_consumer.py` |
| Crash recovery | Redelivery of unhandled signals on startup | `tests/unit/test_signal_redelivery.py` |
| Pre-commit guard | Catches disallowed imports, passes clean code | `tests/unit/test_check_signal_routing.py` |

### Integration Tests

| Area | What to Test | Location |
|------|-------------|----------|
| Full lifecycle via queue | Start → build → verify → complete, all through signals | `tests/integration/test_api_full_lifecycle.py` |
| Pause/resume via queue | Pause active run (STOPPING path), resume paused run | `tests/integration/test_api_full_lifecycle.py` |
| Cancel via queue | Cancel active run (STOPPING path), cancel queued run | `tests/integration/test_api_full_lifecycle.py` |
| Concurrent runs | Two runs process signals independently | `tests/integration/test_signal_queue.py` |
| API rejection | 409 for disallowed transitions on STOPPING runs | `tests/integration/test_api_tasks.py` |

### Migration Tests

| Area | What to Test |
|------|-------------|
| Fresh DB | Migration creates correct schema |
| Existing signals | Migration backfills integer PKs from existing UUID rows |
| Rollback | Downgrade migration restores previous schema |

### Regression Strategy

- Run full test suite after every phase (plan.md Phase 6.1).
- Each phase is independently shippable — if tests fail, the phase is not complete.
- Frontend type check (`tsc --noEmit`) must pass after adding STOPPING to types.

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Consumer polling adds latency to run start | Start with 100ms poll interval; tune if needed. Users already experience async start. |
| Existing integration tests assume synchronous start | Update tests to wait for state transition rather than asserting immediately after API call. |
| STOPPING state confuses frontend | Add clear "Stopping..." UI indicator; STOPPING is transient (seconds, not minutes). |
| Migration on production DB with in-flight signals | Migration backfills existing rows. Handled signals (already processed) get NULL delivered_at/handled_at. |

---

## Relationship to Future Work

This change is a prerequisite for:
- **Multi-worker separation**: Consumer can be extracted to a separate process since it communicates via DB only.
- **EventBroadcaster decoupling** ([I-19]): Once the consumer owns RunWorkflow, the broadcaster can be swapped for a cross-process pub/sub without touching signal routing.
- **Distributed queue**: `pending_signals` could be replaced with Redis/Postgres queue with minimal consumer changes (interface stays the same).
