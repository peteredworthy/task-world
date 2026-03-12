# Step 2: Engine Lifecycle + Action Dispatch

Wire step verification into the workflow engine so the verification loop runs and actions are dispatched correctly. The engine gains two new entry points (`start_step_verification`, `complete_step_verification`) and the service learns to persist/load the new step fields.

## Intent Verification
**Original Intent**: Implement the engine-side half of the gap-analyzer loop — lifecycle methods, action dispatch, and persistence — without touching the executor yet (see `docs/gap-analyzer/intent.md`).
**Functionality to Produce**:
- `WorkflowEngine.start_step_verification(run_id, step_id)` sets `verifying=True`, increments iteration counter, emits event
- `WorkflowEngine.complete_step_verification(run_id, step_id, gap_report)` dispatches verdict actions: `pass`, `fail`, `retry_task`, `spawn_fix`
- `WorkflowService` persists and loads `verifying`, `verifier_iterations`, `gap_reports` from `StepModel`
- `check_step_progression()` in `transitions.py` is **not modified**

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_gap_analyzer_engine.py -v` — all new tests pass
- `uv run pytest tests/unit/ tests/integration/ -v` — no existing tests broken
- `uv run pyright src/orchestrator/workflow/engine.py src/orchestrator/workflow/service.py` — no type errors

---

## Task 1: Add start_step_verification to WorkflowEngine

**Description**: Implement `start_step_verification(run_id, step_id)` on `WorkflowEngine` in `src/orchestrator/workflow/engine.py`. Sets `step.verifying = True`, increments `step.verifier_iterations`, emits `StepVerificationStarted`, and persists state.

**Implementation Plan (Do These Steps)**
- [ ] Add `async def start_step_verification(self, run_id: str, step_id: str) -> None` to `WorkflowEngine`
- [ ] Load step state via `WorkflowService`
- [ ] Guard: if `step.verifying` is already `True`, log warning and return (idempotent)
- [ ] Set `step.verifying = True`; increment `step.verifier_iterations`
- [ ] Emit `StepVerificationStarted(step_id=step_id, iteration=step.verifier_iterations, max_iterations=step_config.step_verifier.max_iterations)`
- [ ] Persist updated step state via `WorkflowService`

**Dependencies**
- [ ] Step 1 complete: `StepVerdict`, `StepVerifierConfig`, `GapReport`, `StepState` fields, event types all defined.

**References**
- `docs/gap-analyzer/plan.md` — M2 specification
- `docs/gap-analyzer/architecture.md` — `WorkflowEngine` interface and interaction diagram
- `docs/gap-analyzer/step-02-plan.md` — full step contract

**Constraints**
- Must be idempotent on double-call (log + return, not raise).
- Do not modify `check_step_progression()` — it must remain unchanged.

**Functionality (Expected Outcomes)**
- [ ] `engine.start_step_verification(run_id, step_id)` callable without error
- [ ] `step.verifying = True` and `step.verifier_iterations` incremented after call
- [ ] `StepVerificationStarted` event emitted

**Final Verification (Proof of Completion)**
- [ ] Unit test: `start_step_verification` sets `verifying=True`, increments `verifier_iterations`, emits event
- [ ] `uv run pyright src/orchestrator/workflow/engine.py` — no new type errors

---

## Task 2: Add complete_step_verification to WorkflowEngine

**Description**: Implement `complete_step_verification(run_id, step_id, gap_report)` with full verdict dispatch logic: `pass`, `fail`, `retry_task`, `spawn_fix`, and `max_iterations` guard.

**Implementation Plan (Do These Steps)**
- [ ] Add `async def complete_step_verification(self, run_id: str, step_id: str, gap_report: GapReport) -> None` to `WorkflowEngine`
- [ ] Append `gap_report` to `step.gap_reports`; emit `GapReportGenerated`
- [ ] Check `step.verifier_iterations >= step_config.step_verifier.max_iterations` → pause run with reason `step_verifier_max_iterations` (regardless of verdict)
- [ ] `verdict == PASS` → clear `step.verifying = False`; emit `StepVerificationCompleted`; call existing step completion path
- [ ] `verdict == FAIL` → clear `step.verifying = False`; emit `StepVerificationCompleted`; pause run with reason `step_verifier_failed`
- [ ] `verdict in (RETRY, FIX)` → dispatch actions (see Task 3); leave `verifying=True`
- [ ] Persist step state after all mutations

**Dependencies**
- [ ] Task 1 must be complete (`start_step_verification` exists)

**References**
- `docs/gap-analyzer/plan.md` — M2 verdict dispatch table
- `docs/gap-analyzer/architecture.md` — interaction diagram
- `docs/gap-analyzer/clarifications.md` — executor manages loop end-to-end

**Constraints**
- `max_iterations` check runs before verdict dispatch — if limit reached, always auto-fail.
- Existing step completion path (used by `pass` verdict) must not be duplicated — call it, don't copy it.

**Functionality (Expected Outcomes)**
- [ ] `pass` verdict: step advances, `verifying=False`, `StepVerificationCompleted` emitted
- [ ] `fail` verdict: run paused with `step_verifier_failed`
- [ ] `max_iterations` reached: run paused with `step_verifier_max_iterations`

**Final Verification (Proof of Completion)**
- [ ] Unit test: `complete_step_verification` with `pass` → step completes, event emitted
- [ ] Unit test: `complete_step_verification` with `fail` → run paused with correct reason
- [ ] Unit test: `verifier_iterations >= max_iterations` → auto-fail regardless of verdict

---

## Task 3: Implement retry_task and spawn_fix Action Dispatch

**Description**: Implement the `retry_task` and `spawn_fix` action handlers inside `complete_step_verification` (called when verdict is `RETRY` or `FIX`).

**Implementation Plan (Do These Steps)**
- [ ] `retry_task` handler:
  - Look up task by `action.task_id`; if not found, log error and skip
  - If task status is not `COMPLETED`, log warning and skip (only COMPLETED tasks eligible per clarifications)
  - If `task.current_attempt >= task.max_attempts`, treat as `FAIL` — pause run
  - Reset task to `PENDING`; prepend `action.feedback` to next builder prompt context
- [ ] `spawn_fix` handler:
  - Create new `TaskState` with `spawned_by_gap_report=True`, `title=action.title`, `requirements` from `action.requirements`
  - Add task to `step.tasks`; persist immediately
- [ ] After dispatching all actions, persist step state

**Dependencies**
- [ ] Task 2 must be complete (`complete_step_verification` skeleton exists)

**References**
- `docs/gap-analyzer/plan.md` — M2 action dispatch specification
- `docs/gap-analyzer/clarifications.md` — `retry_task` eligibility: COMPLETED tasks only; `spawn_fix` bespoke minimal (create TaskState directly)

**Constraints**
- `retry_task` on a `FAILED` (not `COMPLETED`) task must be skipped, not error.
- `spawn_fix` must set `spawned_by_gap_report=True` on the new `TaskState`.

**Functionality (Expected Outcomes)**
- [ ] `retry_task` on COMPLETED task resets it to PENDING with feedback
- [ ] `retry_task` on non-COMPLETED task is skipped silently
- [ ] `spawn_fix` adds new task to step with `spawned_by_gap_report=True`

**Final Verification (Proof of Completion)**
- [ ] Unit test: `retry_task` on COMPLETED task → task reset to PENDING
- [ ] Unit test: `retry_task` on non-COMPLETED task → skipped (no crash)
- [ ] Unit test: `spawn_fix` → new task in step.tasks with `spawned_by_gap_report=True`

---

## Task 4: Update WorkflowService Persistence + Write Engine Unit Tests

**Description**: Update `WorkflowService` in `src/orchestrator/workflow/service.py` to read and write `verifying`, `verifier_iterations`, and `gap_reports` from `StepModel`. Then write all engine unit tests in `tests/unit/test_gap_analyzer_engine.py`.

**Implementation Plan (Do These Steps)**
- [ ] In `WorkflowService`, update the step → `StepState` mapping to include `verifying`, `verifier_iterations`, `gap_reports`
- [ ] In `WorkflowService`, update the `StepState` → `StepModel` write path to persist these fields
- [ ] Serialize `gap_reports` as JSON for storage; deserialize back to `list[GapReport]` on load
- [ ] Create `tests/unit/test_gap_analyzer_engine.py` with tests for:
  - `start_step_verification` sets `verifying=True`, increments `verifier_iterations`, emits `StepVerificationStarted`
  - `complete_step_verification` with `pass` → step completes, `verifying=False`, event emitted
  - `complete_step_verification` with `fail` → run paused with `step_verifier_failed`
  - `complete_step_verification` with `retry_task` on COMPLETED task → task reset to PENDING
  - `complete_step_verification` with `retry_task` on non-COMPLETED task → skipped
  - `complete_step_verification` with `spawn_fix` → new task appears in step
  - `verifier_iterations >= max_iterations` → auto-fail regardless of verdict
  - Two-pass iteration: `retry_task` → tasks complete → `pass` → step completes

**Dependencies**
- [ ] Tasks 1-3 must be complete (all engine methods implemented)

**References**
- `docs/gap-analyzer/architecture.md` — `WorkflowService` responsibilities
- `docs/gap-analyzer/step-02-plan.md` — full test list

**Constraints**
- `gap_reports` serialization: store as JSON list of dicts; deserialize with `GapReport(**d)` on load.
- Confirm `check_step_progression()` diff is empty (file must be unchanged).

**Functionality (Expected Outcomes)**
- [ ] `WorkflowService` round-trips `verifying`, `verifier_iterations`, `gap_reports` through DB correctly
- [ ] All 8 engine unit test scenarios pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_gap_analyzer_engine.py -v` — all tests pass
- [ ] `uv run pytest tests/unit/ tests/integration/ -v` — no existing tests broken
- [ ] `git diff src/orchestrator/workflow/transitions.py` is empty (no changes to transitions)
