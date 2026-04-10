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
- [ ] `verdict == PASS`:
  - Set `step.verifying = False`
  - Emit `StepVerificationCompleted(step_id=step_id, total_iterations=step.verifier_iterations, final_verdict="pass")`
  - Call the existing step completion path (same as the no-verifier case). Use:
    ```python
    routine_config = None
    if run.routine_embedded is not None:
        try:
            routine_config = RoutineConfig.model_validate(run.routine_embedded)
        except Exception:
            pass
    prev_step_index = run.current_step_index
    step_changed = check_step_progression(
        run,
        routine_config=routine_config,
        clock=self._clock,
        emitter=self._emitter,
        worktree_path=None,
        run_config=run.config,
    )
    if step_changed:
        for i in range(prev_step_index, run.current_step_index + 1):
            s = run.steps[i]
            if s.completed:
                self._emitter.emit(StepCompleted(...))
        old_run_status = run.status
        new_run_status = check_run_completion(run, self._clock.now())
        if new_run_status is not None:
            self._emitter.emit(RunStatusChanged(...))
    ```
    This is the identical pattern to `complete_verification()` at engine.py lines 418–463. Do NOT copy/duplicate it — import `check_step_progression` and `check_run_completion` from `transitions.py` (they are already imported at top of engine.py).
- [ ] `verdict == FAIL`:
  - Set `step.verifying = False`
  - Emit `StepVerificationCompleted(step_id=step_id, total_iterations=step.verifier_iterations, final_verdict="fail")`
  - Call `self.pause_run(run_id, reason="step_verifier_failed")`
- [ ] `verdict in (RETRY, FIX)` → dispatch actions (see Task 3); leave `verifying=True`
- [ ] Persist step state after all mutations: `self._state.update_run(run)`

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
  - If `task.current_attempt >= task.max_attempts`, treat entire gap report as FAIL — pause run with reason `"step_verifier_failed"` and return
  - Reset task to `PENDING`: set `task.status = TaskStatus.PENDING`
  - **Do NOT reset `task.current_attempt`** — leave it at its current value; the next `start_task` call will increment it and the max_attempts check will apply correctly
  - Store feedback for next builder invocation: set `task.gap_report_feedback = action.feedback` (this field is on `TaskState`; it will be injected into the builder prompt by `generate_builder_prompt` or the phase handler — see Step 3 Task 2)
- [ ] `spawn_fix` handler:
  - Create new `TaskState`:
    ```python
    new_task = TaskState(
        id=generate_id(),
        config_id=f"gap_fix_{generate_id()[:8]}",
        title=action.title or "Gap fix task",
        status=TaskStatus.PENDING,
        spawned_by_gap_report=True,
        max_attempts=3,
        checklist=[
            ChecklistItem(
                req_id=req.get("id", f"R{i+1}"),
                desc=req.get("desc", ""),
                priority=Priority(req.get("priority", "critical")),
            )
            for i, req in enumerate(action.requirements or [])
        ],
    )
    ```
  - Add task to `step.tasks` list; the task will be picked up by the executor loop automatically
  - Persist immediately via `self._state.update_run(run)` (the service layer calls `repo.save()`)
- [ ] After dispatching all actions for RETRY/FIX verdict, call `self._state.update_run(run)` to persist all mutations

**Dependencies**
- [ ] Task 2 must be complete (`complete_step_verification` skeleton exists)
- [ ] Step 1 Task 2 must be complete (`spawned_by_gap_report` and `gap_report_feedback` fields on `TaskState`)

**References**
- `docs/gap-analyzer/plan.md` — M2 action dispatch specification
- `docs/gap-analyzer/clarifications.md` — `retry_task` eligibility: COMPLETED tasks only; `spawn_fix` bespoke minimal (create TaskState directly)
- Import required: `from orchestrator.state.models import TaskState, ChecklistItem, generate_id`
- Import required: `from orchestrator.config.enums import Priority`

**Constraints**
- `retry_task` on a `FAILED` (not `COMPLETED`) task must be skipped, not error.
- `spawn_fix` must set `spawned_by_gap_report=True` on the new `TaskState`.
- `task.current_attempt` must NOT be reset on retry — only `task.status` is reset to `PENDING`.

**Functionality (Expected Outcomes)**
- [ ] `retry_task` on COMPLETED task: task status → PENDING, `gap_report_feedback` set
- [ ] `retry_task` on non-COMPLETED task: skipped silently (no crash)
- [ ] `retry_task` when `current_attempt >= max_attempts`: run paused with `step_verifier_failed`
- [ ] `spawn_fix`: new task in step.tasks with `spawned_by_gap_report=True` and correct checklist

**Final Verification (Proof of Completion)**
- [ ] Unit test: `retry_task` on COMPLETED task → task reset to PENDING, `gap_report_feedback` populated
- [ ] Unit test: `retry_task` on non-COMPLETED task → skipped (no crash)
- [ ] Unit test: `retry_task` on exhausted task (current_attempt >= max_attempts) → run paused
- [ ] Unit test: `spawn_fix` → new task in step.tasks with `spawned_by_gap_report=True`

---

## Task 4: Update WorkflowService Persistence + Write Engine Unit Tests

**Description**: Update `repositories.py` (`_to_domain` and `_to_model`) to read and write all new step and task fields. Then write all engine unit tests in `tests/unit/test_gap_analyzer_engine.py`.

**Implementation Plan (Do These Steps)**
- [ ] In `src/orchestrator/db/repositories.py`, in `_to_domain()`, update the `StepState(...)` constructor call to include:
  ```python
  verifying=bool(step_model.verifying),
  verifier_iterations=step_model.verifier_iterations or 0,
  gap_reports=[GapReport(**d) for d in (step_model.gap_reports or [])],
  ```
  Import `GapReport` from `orchestrator.state.models` at top of file.
- [ ] In `_to_domain()`, update `TaskState(...)` constructor to include:
  ```python
  spawned_by_gap_report=bool(task_model.spawned_by_gap_report),
  gap_report_feedback=task_model.gap_report_feedback,
  ```
- [ ] In `_to_model()`, update `StepModel(...)` constructor to include:
  ```python
  verifying=int(step.verifying),
  verifier_iterations=step.verifier_iterations,
  gap_reports=[r.model_dump(mode="json") for r in step.gap_reports],
  ```
- [ ] In `_to_model()`, update `TaskModel(...)` constructor to include:
  ```python
  spawned_by_gap_report=int(task.spawned_by_gap_report),
  gap_report_feedback=task.gap_report_feedback,
  ```
- [ ] Serialize `gap_reports`: use `r.model_dump(mode="json")` per report (handles `datetime` and `Enum` serialization). Deserialize with `GapReport(**d)` — `StepVerdict` is a `str, Enum` so string values coerce automatically.
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
- `verifying` and `spawned_by_gap_report` are Integer columns — coerce to `bool` on read and `int` on write.
- Confirm `check_step_progression()` diff is empty (file must be unchanged).
- Do NOT modify `WorkflowService` methods — the persistence is in `repositories.py` (`_to_domain` / `_to_model`). The `_persist` / `_build_engine` cycle in `WorkflowService` calls `repo.save(run)` which calls `_to_model` — no extra wiring needed.

**Functionality (Expected Outcomes)**
- [ ] `repositories.py` round-trips `verifying`, `verifier_iterations`, `gap_reports` through DB correctly
- [ ] `repositories.py` round-trips `spawned_by_gap_report`, `gap_report_feedback` through DB correctly
- [ ] All engine unit test scenarios pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_gap_analyzer_engine.py -v` — all tests pass
- [ ] `uv run pytest tests/unit/ tests/integration/ -v` — no existing tests broken
- [ ] `uv run --no-pager git diff src/orchestrator/workflow/transitions.py` is empty (no changes to transitions)
