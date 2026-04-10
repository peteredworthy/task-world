# Step Plan: Executor, Prompts, and API Surface (M4)

## Purpose

Connect the executor to the phase dispatch loop, generate phase-type-specific prompts, and expose
phase state through the API. After this step, tasks with any `phases_config` pipeline execute
correctly end-to-end, prior phase outputs are injected into subsequent phase prompts, and the API
returns `current_phase_index`, `current_phase_type`, `phase_count`, and `phase_outputs`.

## Prerequisites

- Step 1 complete: `PhaseType`, `PhaseConfig` defined.
- Step 2 complete: `TaskState.phases_config`, `phase_outputs` exist; factory synthesizes phases.
- Step 3 complete: `advance_phase`, `complete_phase` on `WorkflowEngine`; persistence wired.

## Functional Contract

### Inputs

- `TaskState` with non-None `phases_config` and correct `current_phase_index`
- `phase.type` — determines executor dispatch path
- `phase.cmd` — shell command for `script` phases
- `task.phase_outputs` — prior phase outputs passed to prompt builders
- `task_config.auto_verify` — used by `auto_verify` phase
- Human callback (for `human_review` phase): existing `POST /tasks/{id}/submit` flow

### Outputs

- **Agent phases** (`plan`, `build`, `summarize`, `gap_check`, `verify`): agent spawned with
  phase-specific prompt and optional `phase.profile` override; output passed to `complete_phase`
- **Script phase**: `phase.cmd` run via subprocess; exit 0 → `complete_phase("stdout")`; non-zero
  → phase failure (loop to `retry_target` or fail task)
- **Auto-verify phase**: `AutoVerifyRunner` executed; all `must` items pass → `complete_phase`
  with results summary; any fail → phase failure
- **Human-review phase**: task transitions to `PENDING_USER_ACTION`; executor exits; resumes when
  human submits callback → `complete_phase("")`
- **Prompt functions** (new, in `src/orchestrator/workflow/prompts.py`):
  - `build_plan_phase_prompt(task_config, phase, prior_outputs, phases_config) -> str`
  - `build_summarize_phase_prompt(task_config, phase, prior_outputs, phases_config) -> str`
  - `build_gap_check_phase_prompt(task_config, phase, prior_outputs, phases_config) -> str`
  - All inject prior outputs as context sections (truncated to 2000 chars per phase)
- **API additions** to `TaskDetailResponse`:
  - `current_phase_index: int`
  - `current_phase_type: str | None`
  - `phase_count: int`
  - `phase_outputs: dict[int, str]`
- **API addition** to `PromptResponse`:
  - `phase_type: str | None`

### Error Cases

- Script phase non-zero exit: loop to `retry_target` if set; otherwise fail task with
  `pause_reason="agent_execution_error"`
- Auto-verify failure: loop to `retry_target` if set; otherwise fail task
- `human_review` phase + server restart: `current_phase_index` already persisted; task resumes
  at correct phase index when human submits
- `phases_config` is `None` (fan-out or legacy path): executor skips phase dispatch loop and
  uses the old hardcoded build/verify flow unchanged

## Tasks

1. Replace the hardcoded build/verify dispatch sequence in `src/orchestrator/runners/executor.py`
   with a phase dispatch loop:
   - Check `task.phases_config`; if `None`, fall through to existing legacy path (backward compat).
   - Loop over phases starting at `task.current_phase_index`.
   - Dispatch per `phase.type` as described in Outputs above.
   - After each `complete_phase` call, refresh `task` from service (engine updated the index).
2. Add `_get_phase_prompt(task_config, phase, prior_outputs, phases_config) -> str` helper in
   executor (or prompts module) that dispatches to the correct prompt builder.
3. Add `build_plan_phase_prompt`, `build_summarize_phase_prompt`, `build_gap_check_phase_prompt`,
   and `_format_prior_outputs` to `src/orchestrator/workflow/prompts.py`.
4. Add `current_phase_index`, `current_phase_type`, `phase_count`, `phase_outputs` to
   `TaskDetailResponse` in `src/orchestrator/api/schemas/tasks.py`.
5. Add `phase_type` to `PromptResponse` in the same file.
6. Populate new fields in `get_task` serialization in `src/orchestrator/api/routers/tasks.py`
   (or wherever `TaskDetailResponse` is constructed).
7. Create `tests/integration/test_phase_pipelines.py`:
   - Task with explicit `phases: [plan, build, verify]` completes all three; plan output appears
     in build prompt.
   - Script-only task (exit 0) → COMPLETED.
   - Script-only task (exit 1) → FAILED (or loops to retry if `retry_target` set).
   - `auto_verify` phase after build: all must items pass → COMPLETED; any fail → task retries.
   - Conditional phase (`condition` evaluates false) → skipped; task advances to next phase.
   - Verify `retry_target: 1` failure → task goes to phase 1, not phase 0.
   - `human_review` phase → PENDING_USER_ACTION; resumes on human callback → advances to next
     phase.
   - Backward compat: task YAML without `phases` runs identically to current behavior.
   - GET task response includes all new phase fields.

## Verification Approach

### Auto-Verify

- `uv run pytest tests/integration/test_phase_pipelines.py -v` — all new integration tests pass.
- `uv run pytest tests/integration/ -v` — no regressions.
- `uv run pyright src/orchestrator/runners/executor.py src/orchestrator/workflow/prompts.py
  src/orchestrator/api/schemas/tasks.py` — no type errors.
- GET `/api/tasks/{id}` response includes `current_phase_index`, `current_phase_type`,
  `phase_count`, `phase_outputs` with correct values.

### Manual Verification

- Run a task with `phases: [plan, build]` through the orchestrator; confirm the plan output
  appears verbatim (up to 2000 chars) in the build phase's agent prompt.
- Confirm `PromptResponse.phase_type` returns `"build"` when the current phase is a build phase
  and `"verify"` for a verify phase.

## Context & References

- Plan: `docs/phase-pipelines/plan.md` — M4 and Step 4 specification.
- Architecture: `docs/phase-pipelines/architecture.md` — executor dispatch loop, prompt builders,
  API schema additions.
- Clarification Q1: Status mapping table (`build`→`BUILDING`, `verify`→`VERIFYING`,
  `human_review`→`PENDING_USER_ACTION`).
- Security note: `phase.cmd` shares the same trust level as `auto_verify.cmd` (routine YAML,
  not agent-supplied). Apply the existing pipe-rejection validator from `AutoVerifyItemConfig`.
- Performance note: truncate each prior output to 2000 chars in prompt injection to prevent
  context overflow; full text preserved in `phase_outputs` for API display.
