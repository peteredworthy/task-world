# Step Plan: Sender Rewiring

## Purpose

Switch all `WorkflowService` methods to enqueue signals unconditionally, removing
the `has_active_workflow` branching. Wire the consumer into executor startup so it
processes the enqueued signals. Change API responses from 200 to 202 Accepted.
This is the behavioral pivot — after this step, all lifecycle operations flow
through the single queue.

## Prerequisites

- **S-01 complete**: Schema changes, STOPPING state, RUN_START signal type.
- **S-02 complete**: Consumer loop with all signal handlers, redelivery logic.

## Functional Contract

### Inputs

- `WorkflowService.start_run()` currently calls `engine.start_run()` directly.
- `WorkflowService.pause_run()`, `resume_run()`, `cancel_run()` use `has_active_workflow`
  to choose between direct-DB mutation and signal enqueueing.
- `retry_fan_out_child()` checks `has_active_workflow`.
- API endpoints return 200 with `RunResponse` body.
- `RunWorkflow.handle_pause` calls `unregister_active_run()`.
- `env_lifecycle.on_run_start()` called in `WorkflowService.start_run()`.

### Outputs

- **`WorkflowService.start_run()`**: Enqueues `RUN_START` signal instead of calling
  `engine.start_run()`. No direct DRAFT → ACTIVE transition.
- **`WorkflowService.pause_run()`**: Enqueues `PAUSE` signal unconditionally.
  Removes `has_active_workflow` check and direct-DB branch.
- **`WorkflowService.resume_run()`**: Enqueues `RESUME` signal unconditionally.
  Removes `has_active_workflow` check and direct-DB branch.
- **`WorkflowService.cancel_run()`**: Enqueues `CANCEL` signal unconditionally.
  Removes `has_active_workflow` check. Moves env_lifecycle hooks and worktree
  cleanup to consumer's `_handle_cancel()`.
- **`retry_fan_out_child()`**: Removes `has_active_workflow` check. Enqueues
  PAUSE signal for active runs.
- **`RunWorkflow.handle_pause`**: `unregister_active_run()` call removed
  (consumer now owns this).
- **`env_lifecycle.on_run_start()`**: Moved from service to consumer's
  `_handle_run_start()` handler (runs inline, blocking that run only).
- **API endpoints** for start/pause/resume/cancel return **202 Accepted**.
- **Consumer started** as part of executor/app startup, before any service
  methods are called.

### Error Cases

- Dead-lettered signals if consumer not started before service methods called —
  mitigated by starting consumer first in app startup.
- Integration tests fail expecting 200 — must update to expect 202.
- Integration tests fail expecting synchronous state change — must wait for
  consumer to process signal.
- `env_lifecycle` hooks fail in consumer — error handling preserves signal for
  redelivery (handled_at stays null).

## Tasks

1. Rewire `WorkflowService.start_run()` to enqueue `RUN_START` signal.
2. Move `env_lifecycle.on_run_start()` to consumer `_handle_run_start()`.
3. Rewire `WorkflowService.pause_run()` to always enqueue PAUSE signal.
4. Rewire `WorkflowService.resume_run()` to always enqueue RESUME signal.
5. Rewire `WorkflowService.cancel_run()` to always enqueue CANCEL signal;
   move env_lifecycle hooks to consumer.
6. Remove `unregister_active_run()` from `RunWorkflow.handle_pause`.
7. Rewire `retry_fan_out_child()` to enqueue PAUSE instead of checking registry.
8. Change API endpoints to return 202 Accepted.
9. Wire consumer startup into `executor.py` or `app.py`.
10. Update integration tests for 202 responses and async state transitions.

## Verification Approach

### Auto-Verify

- `grep -r "has_active_workflow" src/orchestrator/workflow/service.py` returns no hits.
- `grep -r "has_active_workflow" src/orchestrator/api/` returns no hits.
- `grep -r "engine.start_run" src/orchestrator/workflow/service.py` returns no hits
  (start goes through signal queue).
- `grep -r "unregister_active_run" src/orchestrator/workflow/run_workflow.py` returns no hits.
- Integration test: create run → start via API → confirm 202 → confirm run becomes
  ACTIVE within 1–2 seconds.
- Integration test: pause active run → confirm STOPPING → confirm PAUSED.
- All existing tests pass (updated for 202 and async behavior).

### Manual Verification

- End-to-end: start a run via API, observe signal pickup by consumer, run
  transitions to ACTIVE.
- Pause/resume/cancel all flow through queue with no direct-DB mutations.

## Context & References

- Plan: `docs/single-queue-2/plan.md` — Phase 3 (§3.1, §3.2, §3.3, §3.4)
- Architecture: `docs/single-queue-2/architecture.md` — Target Architecture,
  Signal Flow diagrams, Integration Points
- Decision: 202 Accepted (breaking change)
- Decision: env_lifecycle hooks inline in consumer (blocks that run only)
- Caveat: Use `SignalQueue(DbSignalTransport(session))` pattern (see existing
  `pause_run()` at ~line 327 of service.py).
- Caveat: `start_run()` calls `engine.start_run()`, NOT `executor.spawn_run()`.
