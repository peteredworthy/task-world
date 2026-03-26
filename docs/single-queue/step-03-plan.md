# Step 03: Sender Rewiring

**Phase:** 3
**Goal:** Switch all `WorkflowService` methods to enqueue signals unconditionally. Remove the `has_active_workflow` branching.

---

## Purpose and Functionality

Rewire every lifecycle method in `WorkflowService` to enqueue signals instead of
branching on `has_active_workflow`. Wire the consumer into application startup so
it replaces direct-spawn paths. After this step, all lifecycle transitions flow
through the signal queue.

---

## Prerequisites / Dependencies

- **S-01 complete:** Schema changes and STOPPING state in place.
- **S-02 complete:** Consumer module exists and handles all signal types.

---

## Functional Contract

### Inputs

| Input | Source | Description |
|-------|--------|-------------|
| `WorkflowService.start_run()` | API router | Currently calls `executor.spawn_run()` directly |
| `WorkflowService.pause_run()` | API router | Currently branches on `has_active_workflow` |
| `WorkflowService.resume_run()` | API router | Currently branches on `has_active_workflow` |
| `WorkflowService.cancel_run()` | API router | Currently branches on `has_active_workflow` |
| `retry_fan_out_child()` | Workflow engine | Currently checks `has_active_workflow` |

### Outputs

| Output | Description |
|--------|-------------|
| `start_run()` | Enqueues `RUN_START` signal. No direct `executor.spawn_run()` call. No DRAFT→ACTIVE DB transition in service. |
| `pause_run()` | Enqueues `PAUSE` signal unconditionally. No `has_active_workflow` check. |
| `resume_run()` | Enqueues `RESUME` signal unconditionally. No `has_active_workflow` check. |
| `cancel_run()` | Enqueues `CANCEL` signal unconditionally. No `has_active_workflow` check. |
| `retry_fan_out_child()` | No `has_active_workflow` check. Enqueues PAUSE for active runs. |
| `RunWorkflow.handle_pause` | `unregister_active_run()` call removed (consumer owns this). |
| Consumer wired into startup | Consumer loop started as part of executor/app initialization. |

### Errors

| Error | Condition | Behavior |
|-------|-----------|----------|
| Signal enqueue failure | DB write fails | Raise exception, API returns 500 |
| Consumer not running | Consumer loop not started | Signals accumulate in queue, processed when consumer starts |

---

## Verification Strategy

1. **Per-method integration tests:**
   - `start_run()`: Run starts via signal queue (not direct spawn).
   - `pause_run()`: Signal enqueued, no `has_active_workflow` call.
   - `resume_run()`: Signal enqueued, no `has_active_workflow` call.
   - `cancel_run()`: Signal enqueued, no `has_active_workflow` call.

2. **`retry_fan_out_child()` test:**
   - Enqueues PAUSE signal for active runs.

3. **End-to-end integration test:**
   - Create run → start via API → consumer picks up signal → RunWorkflow created.

4. **Code audit:** Grep confirms no `has_active_workflow` calls in `service.py`, `routers/`, or any API-initiated code path.

5. **Regression:** Full test suite passes (update existing tests that assumed synchronous start).

---

## Files Changed

- Modify: `src/orchestrator/workflow/service.py`
- Modify: `src/orchestrator/workflow/run_workflow.py` (remove registry call from handle_pause)
- Modify: `src/orchestrator/executor.py` or `src/orchestrator/app.py` (wire consumer into startup)
- Modify: `tests/integration/test_api_full_lifecycle.py` (update expectations for async start)
- Modify: other integration tests as needed

---

## Traces

[I-01], [I-09], [I-10], [I-11], [I-13], [I-17], [I-27], [I-28]
