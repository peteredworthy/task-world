# Step Plan: Engine Lifecycle + Action Dispatch

## Purpose

Wire step verification into the workflow engine so the verification loop runs and actions are dispatched correctly. This step makes the engine aware of gap reports and capable of driving retry/fix/pass/fail outcomes — but does not yet connect to the executor or API.

## Prerequisites

- Step 1 complete: all new types (`StepVerdict`, `StepVerifierConfig`, `GapAction`, `GapReport`, event types, `StepState` fields, DB columns, migration) must exist.

## Functional Contract

### Inputs

- `start_step_verification(run_id: str, step_id: str)` — called by executor when all step tasks reach terminal state and `step_verifier` is configured
- `complete_step_verification(run_id: str, step_id: str, gap_report: GapReport)` — called by executor after parsing verifier agent output

### Outputs

**`start_step_verification`:**
- Sets `step.verifying = True`, increments `step.verifier_iterations`
- Emits `StepVerificationStarted(step_id, iteration, max_iterations)`
- Persists updated step state via `WorkflowService`

**`complete_step_verification` — verdict dispatch:**

| Condition | Outcome |
|-----------|---------|
| `verifier_iterations >= max_iterations` | Pause run with reason `step_verifier_max_iterations` |
| `verdict == PASS` | Clear `verifying`, emit `StepVerificationCompleted`, call existing step completion path |
| `verdict == FAIL` | Clear `verifying`, emit `StepVerificationCompleted`, pause run with reason `step_verifier_failed` |
| `verdict in (RETRY, FIX)` | Dispatch `retry_task` / `spawn_fix` actions; leave `verifying=True`; executor re-enters loop |

**`retry_task` action:**
- Target task must be `COMPLETED`; if not, skip (log warning)
- If `task.current_attempt >= task.max_attempts`, treat as `FAIL` (task exhausted)
- Reset task to `PENDING`; prepend `feedback` to next builder prompt

**`spawn_fix` action:**
- Create new `TaskState` with `spawned_by_gap_report=True`, `title`, `requirements` from `GapAction`
- Add to `step.tasks`; persist immediately

### Error Cases

- `start_step_verification` on a step that is already `verifying=True` — should be idempotent or raise; engine guards against double-call
- `retry_task` targeting non-existent `task_id` — log error, skip action (do not crash)
- `retry_task` on a `FAILED` task — skip (only COMPLETED tasks eligible)
- `retry_task` when `max_attempts` exhausted — treat whole gap report as `FAIL`, pause run
- `spawn_fix` with missing required fields (`title`) — validation at `GapAction` Pydantic level (caught earlier)

## Tasks

1. Add `start_step_verification(run_id, step_id)` to `WorkflowEngine` in `src/orchestrator/workflow/engine.py`
2. Add `complete_step_verification(run_id, step_id, gap_report)` to `WorkflowEngine` with full action dispatch logic
3. Update `WorkflowService` in `src/orchestrator/workflow/service.py` to persist/load `verifying`, `verifier_iterations`, `gap_reports` from `StepModel`
4. Ensure `check_step_progression()` in `src/orchestrator/workflow/transitions.py` is **not modified** — it is only called on the no-verifier path
5. Create `tests/unit/test_gap_analyzer_engine.py` with tests for:
   - `start_step_verification` sets `verifying=True`, increments `verifier_iterations`, emits `StepVerificationStarted`
   - `complete_step_verification` with `pass` → step completes, `verifying=False`, event emitted
   - `complete_step_verification` with `fail` → run paused with `step_verifier_failed`
   - `complete_step_verification` with `retry_task` on COMPLETED task → task reset to PENDING
   - `complete_step_verification` with `retry_task` on non-COMPLETED task → skipped
   - `complete_step_verification` with `spawn_fix` → new task appears in step
   - `verifier_iterations >= max_iterations` → auto-fail regardless of verdict
   - Two-pass iteration: `retry_task` → tasks complete → `pass` → step completes

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/test_gap_analyzer_engine.py -v` — all new tests pass
- `uv run pytest tests/unit/ tests/integration/ -v` — no existing tests broken
- `uv run pyright src/orchestrator/workflow/engine.py src/orchestrator/workflow/service.py` — no type errors

### Manual Verification

- Confirm `check_step_progression()` diff is empty (file unchanged)
- Confirm `spawn_fix` tasks have `spawned_by_gap_report=True` flag set

## Context & References

- Plan: `docs/gap-analyzer/plan.md` — M2 specification and key decisions table
- Architecture: `docs/gap-analyzer/architecture.md` — `WorkflowEngine` interface and interaction diagram
- Clarification: executor manages the step verification loop end-to-end; `check_step_progression()` is NOT modified for the verifier path
- Step 1 plan: `docs/gap-analyzer/step-01-plan.md` — types this step depends on
