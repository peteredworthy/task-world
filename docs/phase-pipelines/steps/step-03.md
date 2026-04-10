# Step 3: Engine Lifecycle (M3)

Wire phase advancement into the workflow engine. The state machine drives phase progression: advancing through `phases_config`, skipping conditional phases, looping verify failures to the correct retry target, and persisting phase state across server restarts.

## Intent Verification
**Original Intent**: Add `advance_phase` and `complete_phase` to `WorkflowEngine` so it can drive any `phases_config` pipeline, persist phase state, and handle retry loops and conditional skips.
**Functionality to Produce**:
- `WorkflowEngine.advance_phase(run_id, task_id)` — increments index, skips false conditions, completes task when exhausted, emits `PhaseStarted`
- `WorkflowEngine.complete_phase(run_id, task_id, output)` — stores output, emits `PhaseCompleted`, calls `advance_phase`
- Verify failure path reads `retry_target`, defaults to `current_phase_index - 1`
- `start_task()` resumes at persisted `current_phase_index` (not forced to 0)
- `WorkflowService` persists and loads `current_phase_index` and `phase_outputs`

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_phase_engine.py -v` — all new tests pass
- `uv run pytest tests/unit/ tests/integration/ -v` — no regressions
- `uv run pyright src/orchestrator/workflow/engine.py src/orchestrator/workflow/service.py` — no type errors

---

## Task 1: Add advance_phase to WorkflowEngine

**Description**: Add `async def advance_phase(run_id, task_id)` to `WorkflowEngine` in `src/orchestrator/workflow/engine.py`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/workflow/engine.py`
- [ ] Add `async def advance_phase(self, run_id: str, task_id: str) -> None`:
  - Load task state; assert `phases_config` is not None (raise `RuntimeError` if it is)
  - Compute `next_index = current_phase_index + 1`
  - Walk forward skipping phases where `condition` evaluates to false:
    - `ConditionEvaluator` in `condition_evaluator.py` evaluates expressions against a context dict. For phase conditions, pass a simple dict context: `{"phase_outputs": task.phase_outputs, "current_phase_index": task.current_phase_index}`. Do NOT pass a `StepOutcome` object — that is for step-level transitions only.
    - If `phases_config[next_index].condition` is set and evaluates to false, increment `next_index` and try the next phase
  - If `next_index >= len(phases_config)` → ⚠️ HARDENING NOTE (Gap 3): `_complete_task` does NOT exist in engine.py. `VALID_TRANSITIONS` has no BUILDING→COMPLETED path. You must:
    1. Add `transition_to_completed_direct(task: TaskState, now: datetime) -> TransitionResult` to `src/orchestrator/workflow/transitions.py` — sets `task.status = TaskStatus.COMPLETED` from BUILDING/VERIFYING/PENDING_USER_ACTION and records `task.attempts[-1].completed_at = now`
    2. Update `VALID_TRANSITIONS` in `transitions.py`: add `TaskStatus.COMPLETED` to `TaskStatus.BUILDING`'s valid set — `TaskStatus.BUILDING: {TaskStatus.VERIFYING, TaskStatus.PENDING_USER_ACTION, TaskStatus.FAILED, TaskStatus.COMPLETED}`
    3. In engine.py, add `_complete_phase_pipeline_task(run_id, task_id)` that calls `transition_to_completed_direct(task, now)`, emits `TaskStatusChanged`, and triggers step/run completion cascade (call `check_step_progression` + `check_run_completion`, same pattern as `complete_verification()`)
    (See Task 5 for the test that covers `transition_to_completed_direct`)
  - Else: set `task.current_phase_index = next_index`, persist via `self._state.update_run(run)`,
    emit `PhaseStarted(event_type="phase_started", timestamp=self._clock.now(), run_id=run_id, task_id=task_id, phase_index=next_index, phase_type=phases_config[next_index].type.value)`

**Dependencies**
- Step 2 complete: `TaskState.phases_config`, `PhaseStarted` event defined; persistence layer updated

**References**
- `docs/phase-pipelines/step-03-plan.md` — Task 1
- `docs/phase-pipelines/architecture.md` — advance_phase interaction diagram
- Existing: `src/orchestrator/workflow/condition_evaluator.py`

**Constraints**
- If `phases_config` is `None`, raise `RuntimeError` (not silently skip — this is a programming error)
- Condition evaluation errors should propagate; do not swallow them
- ⚠️ HARDENING NOTE (Gap 4): For phase condition evaluation, pass these exact values to `ConditionEvaluator().evaluate()`:
  - `variables = {str(i): output for i, output in task.phase_outputs.items()}` (phase outputs indexed by string position)
  - `step_outcomes = {}` (no step-level outcomes needed for phase conditions)
  - Full call: `ConditionEvaluator().evaluate(phase.condition, variables, step_outcomes)`
  - Do NOT pass a `StepOutcome` object or use the step-level context dict — those are for step-level transitions only. Using the wrong context causes conditions to silently evaluate against missing variables.

**Functionality (Expected Outcomes)**
- [ ] `advance_phase` increments `current_phase_index` and emits `PhaseStarted`
- [ ] False condition phases are skipped
- [ ] Exhausted pipeline triggers `_complete_task`

**Final Verification (Proof of Completion)**
- [ ] Unit tests for `advance_phase` pass (see Task 4)

---

## Task 2: Add complete_phase to WorkflowEngine

**Description**: Add `async def complete_phase(run_id, task_id, output)` to `WorkflowEngine`.

**Implementation Plan (Do These Steps)**
- [ ] Add `async def complete_phase(self, run_id: str, task_id: str, output: str) -> None`:
  - Load task state
  - Store `output` in `phase_outputs[current_phase_index]`
  - Emit `PhaseCompleted` event
  - Persist updated state
  - Call `await self.advance_phase(run_id, task_id)`

**Dependencies**
- [ ] Task 1 must be complete

**References**
- `docs/phase-pipelines/step-03-plan.md` — Task 2

**Constraints**
- State must be persisted before calling `advance_phase` so the output is saved even if advance fails

**Functionality (Expected Outcomes)**
- [ ] `complete_phase` stores output, emits `PhaseCompleted`, then advances to next phase

**Final Verification (Proof of Completion)**
- [ ] Unit tests for `complete_phase` pass (see Task 4)

---

## Task 3: Update Verify Failure Path and start_task Resume

**Description**: Update the verify failure path to read `retry_target` from phase config (defaulting to `current_phase_index - 1`) and update `start_task()` to resume at persisted `current_phase_index`.

**Implementation Plan (Do These Steps)**
- [ ] Find the verify failure path:
  - The verify-failure logic lives in `src/orchestrator/workflow/transitions.py::transition_after_verification()` (line ~268), called by `engine.complete_verification()`. Look at `engine.complete_verification()` to find where failed verification sends the task back to BUILDING for retry.
  - When `phases_config` is set and the current phase is a verify phase that failed (task going back to BUILDING), intercept after `transition_after_verification()` returns and before the state is persisted:
- [ ] Read `retry_target` from `phases_config[current_phase_index]` if `phases_config` is set and `current_phase_index` < len(phases_config)
- [ ] Default to `current_phase_index - 1` when `retry_target` is `None`
- [ ] Set `task.current_phase_index = retry_target` and persist (do NOT call `advance_phase`)
- [ ] ⚠️ HARDENING NOTE (Gap 7): Do NOT modify `start_task()` for resume. `start_task()` only manages the PENDING→BUILDING status transition — it does not control phase dispatch. The executor's phase dispatch loop (Step 4 Task 1) starts at `task.current_phase_index` (persisted in DB), which handles resume correctly. `start_task()` does not need modification for this purpose.

**Dependencies**
- [ ] Tasks 1–2 must be complete

**References**
- `docs/phase-pipelines/step-03-plan.md` — Tasks 3–4
- `docs/phase-pipelines/clarifications.md` — Q4: retry_target default is current - 1

**Constraints**
- The verify failure path must remain backward-compatible: if `phases_config` is `None`, use the old hardcoded retry behavior unchanged
- `start_task` resume must not re-emit `PhaseStarted` for already-completed phases

**Functionality (Expected Outcomes)**
- [ ] Verify failure with `retry_target=1` → `current_phase_index` set to 1
- [ ] Verify failure with no `retry_target` → `current_phase_index` set to `current - 1`
- [ ] `start_task` at `current_phase_index=2` starts phase 2, not phase 0

**Final Verification (Proof of Completion)**
- [ ] Unit tests for retry and resume pass (see Task 4)

---

## Task 4: Wire Repository Persistence

**Description**: Update `src/orchestrator/db/repositories.py` to persist and load `current_phase_index` and `phase_outputs` from `TaskModel`. The persistence mapping is NOT in `service.py` — it is in the repository's `_to_domain()` (read) and `_to_model()` (write) functions.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/db/repositories.py` (NOT `service.py`)
- [ ] In `_to_domain()` (around line 167), where `TaskState(...)` is constructed, add:
  - `current_phase_index=task_model.current_phase_index` (defaults to 0 if column is missing)
  - `phase_outputs={int(k): v for k, v in (task_model.phase_outputs or {}).items()}` — JSON serializes dict[int, str] keys as strings; must coerce back to int on read or `task.phase_outputs[0]` raises KeyError
- [ ] In `_to_model()` (around line 310), where `TaskModel(...)` is constructed, add:
  - `current_phase_index=task.current_phase_index`
  - `phase_outputs=task.phase_outputs`
- [ ] Verify round-trip: save a state with `current_phase_index=2`, reload it, confirm index is 2

**Dependencies**
- [ ] Task 3 complete (engine uses these fields)
- Step 2 complete: DB columns exist and `TaskState` has the fields

**References**
- `docs/phase-pipelines/step-03-plan.md` — Task 5

**Constraints**
- `phases_config` is NOT persisted to DB — it must be re-synthesized at runtime
- `phase_outputs` must handle JSON null → empty dict gracefully (see int-key coercion above)
- This task updates `repositories.py`, NOT `service.py`
- Also add `WorkflowService._with_phases(run: Run, task: TaskState) -> TaskState` in
  `src/orchestrator/workflow/service.py`: re-synthesizes `phases_config` by parsing
  `run.routine_embedded` as `RoutineConfig`, finding the `TaskConfig` with `id == task.config_id`,
  calling `_synthesize_phases(task_config)`, assigning to `task.phases_config`, and returning
  the task. Call `_with_phases()` in `WorkflowService.get_task()` before returning, and in
  `_execute_task()` before the phase dispatch check.

**Functionality (Expected Outcomes)**
- [ ] `current_phase_index` and `phase_outputs` survive server restart

**Final Verification (Proof of Completion)**
- [ ] Save state with `current_phase_index=2`, restart service, reload — index is 2

---

## Task 5: Write Engine Unit Tests

**Description**: Create `tests/unit/test_phase_engine.py` covering all engine phase lifecycle behaviors.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_phase_engine.py` with mocked dependencies
- [ ] Write tests:
  - `test_advance_phase_increments_index`: increments and emits `PhaseStarted`
  - `test_advance_phase_skips_false_condition`: skips to next valid phase
  - `test_advance_phase_exhausts_pipeline`: `next_index >= len(phases_config)` → `_complete_task` called (NOTE: "exhausting pipeline" means running out of phases, not "all conditions false"; write a separate test for all-conditional-skip reaching end)
  - `test_complete_phase_stores_output`: output stored, `PhaseCompleted` emitted, `advance_phase` called
  - `test_verify_failure_with_retry_target`: `retry_target=1` → index set to 1
  - `test_verify_failure_default_retry`: no `retry_target` → index set to `current - 1`
  - `test_start_task_resumes_at_index`: `current_phase_index=2` → starts at phase 2
  - `test_final_phase_complete_reaches_completed`: task reaches COMPLETED status
- [ ] Run: `uv run pytest tests/unit/test_phase_engine.py -v`

**Dependencies**
- [ ] Tasks 1–4 must be complete

**References**
- `docs/phase-pipelines/step-03-plan.md` — Task 6

**Constraints**
- Mock `WorkflowService` and DB; do not require a running server for unit tests

**Functionality (Expected Outcomes)**
- [ ] All 8 test cases pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_phase_engine.py -v` — all pass
- [ ] `uv run pytest tests/unit/ tests/integration/ -v` — no regressions

---
