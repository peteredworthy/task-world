# Step Plan: Engine Lifecycle (M3)

## Purpose

Wire phase advancement into the workflow engine so the state machine drives phase progression.
After this step the engine can advance through any `phases_config` pipeline, skip conditional
phases, loop verify failures to the correct retry target, and persist phase state across server
restarts.

## Prerequisites

- Step 1 complete: `PhaseType`, `PhaseConfig`, `PhaseStarted`, `PhaseCompleted` defined.
- Step 2 complete: `TaskState.current_phase_index`, `phase_outputs`, `phases_config` exist;
  factory synthesizes `phases_config`; DB columns and migration applied.

## Functional Contract

### Inputs

- `run_id: str`, `task_id: str` — identify the task within a run
- `output: str` — phase output text passed to `complete_phase`
- `TaskState.phases_config` — phase list set by factory; must not be `None` when engine methods
  are called
- `TaskState.current_phase_index` — current position in the pipeline (may be > 0 on resume)

### Outputs

- `advance_phase(run_id, task_id)`:
  - Increments `current_phase_index`, skipping phases whose `condition` evaluates to false
  - If all phases exhausted → calls existing task completion path
  - Emits `PhaseStarted` for the new active phase
  - Persists updated `TaskState` to DB
- `complete_phase(run_id, task_id, output)`:
  - Stores `output` in `phase_outputs[current_phase_index]`
  - Emits `PhaseCompleted`
  - Persists state, then calls `advance_phase`
- Verify failure path:
  - Reads `retry_target` from the verify `PhaseConfig`
  - Defaults to `current_phase_index - 1` when `retry_target` is `None`
  - Sets `current_phase_index` to the retry target and persists

### Error Cases

- `phases_config` is `None` when `advance_phase` or `complete_phase` is called — raise
  `RuntimeError` (should never happen for non-fan-out tasks after factory runs)
- `next_index` goes out of bounds after condition skipping — treated as pipeline complete
- `condition` evaluation raises `ConditionEvalError` — propagate; run paused with
  `pause_reason="unexpected_error"`

## Tasks

1. Add `advance_phase(run_id, task_id)` async method to `WorkflowEngine` in
   `src/orchestrator/workflow/engine.py`:
   - Get task state, compute `next_index = current_phase_index + 1`.
   - Walk forward skipping phases where `condition` evaluates to false (reuse existing
     `ConditionEvaluator`).
   - If `next_index >= len(phases_config)` → call `_complete_task`.
   - Else: set `current_phase_index = next_index`, persist, emit `PhaseStarted`.
2. Add `complete_phase(run_id, task_id, output)` async method to `WorkflowEngine`:
   - Store output in `phase_outputs`, emit `PhaseCompleted`, persist, call `advance_phase`.
3. Update verify failure path in `complete_verification` (or equivalent engine method):
   - Read `retry_target` from current phase config; default to `current_phase_index - 1`.
   - Set `current_phase_index = retry_target` and persist (do not call `advance_phase`).
4. Update `start_task()` to start at `current_phase_index` rather than 0 when the index is
   already > 0 (supports resuming mid-pipeline after server reload).
5. Update `WorkflowService` to persist/load `current_phase_index` and `phase_outputs` from
   `TaskModel` when reading and writing task state.
6. Create `tests/unit/test_phase_engine.py`:
   - `advance_phase` increments index and emits `PhaseStarted`.
   - `advance_phase` with false condition skips to the next valid phase.
   - `advance_phase` with all conditions false exhausts pipeline → `_complete_task` called.
   - `complete_phase` stores output, emits `PhaseCompleted`, then calls `advance_phase`.
   - Verify failure with `retry_target=1` → `current_phase_index` set to 1.
   - Verify failure with no `retry_target` → `current_phase_index` set to `current - 1`.
   - Resume: `start_task` at `current_phase_index=2` starts phase 2, not phase 0.
   - Final phase complete → task reaches COMPLETED status.

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/test_phase_engine.py -v` — all new tests pass.
- `uv run pytest tests/unit/ tests/integration/ -v` — no regressions.
- `uv run pyright src/orchestrator/workflow/engine.py src/orchestrator/workflow/service.py`
  — no type errors.

### Manual Verification

- Trace a synthesized `[build, verify]` pipeline through the engine: confirm `advance_phase`
  moves from phase 0 to phase 1, then marks task complete after phase 1.
- Confirm that a verify failure with default `retry_target` returns to phase 0 (the build phase),
  matching the pre-existing behavior.

## Context & References

- Plan: `docs/phase-pipelines/plan.md` — M3 and Step 3 specification.
- Architecture: `docs/phase-pipelines/architecture.md` — `advance_phase`, `complete_phase`,
  verify retry path, interaction diagram.
- Clarification Q1: `TaskStatus` enum unchanged; phase types map to existing status values.
- Clarification Q4: `retry_target` default is `current_phase_index - 1` (matches current
  hardcoded behavior).
- Existing code: `src/orchestrator/workflow/condition_evaluator.py` — reuse for phase condition
  evaluation.
