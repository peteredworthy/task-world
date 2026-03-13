# Step 4: Executor, Prompts, and API Surface (M4)

Connect the executor to the phase dispatch loop, generate phase-type-specific prompts, and expose phase state through the API. Tasks with any `phases_config` pipeline execute correctly end-to-end; the API returns `current_phase_index`, `current_phase_type`, `phase_count`, and `phase_outputs`.

## Intent Verification
**Original Intent**: Replace the hardcoded build/verify dispatch in the executor with a phase dispatch loop, add prompt builders for new phase types, and add phase fields to `TaskDetailResponse` and `PromptResponse`.
**Functionality to Produce**:
- Phase dispatch loop in executor with per-type handlers (agent, script, auto_verify, human_review)
- Prompt builders: `build_plan_phase_prompt`, `build_summarize_phase_prompt`, `build_gap_check_phase_prompt` with prior output injection
- `TaskDetailResponse` fields: `current_phase_index`, `current_phase_type`, `phase_count`, `phase_outputs`
- `PromptResponse` field: `phase_type`
- Integration tests in `tests/integration/test_phase_pipelines.py`

**Final Verification Criteria**:
- `uv run pytest tests/integration/test_phase_pipelines.py -v` — all new integration tests pass
- `uv run pytest tests/integration/ -v` — no regressions
- GET `/api/tasks/{id}` returns all new phase fields with correct values

---

## Task 1: Replace Executor Dispatch with Phase Loop

**Description**: Replace the hardcoded build/verify dispatch sequence in `src/orchestrator/runners/executor.py` with a phase dispatch loop.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/runners/executor.py`
- [ ] ARCHITECTURE NOTE: The executor already extracts phase execution into `src/orchestrator/runners/execution/phase_handler.py`. `PhaseHandler.execute_phase()` currently handles `"building"`, `"verifying"`, `"recovering"`. ⚠️ See Gap 11 note below before deciding how to add pipeline phase support — routing all new phase types through `execute_phase()` is one option but has pitfalls around string mapping and internal state transitions. Option A (handle pipeline phases directly in the executor loop without going through `execute_phase`) is often simpler.
- [ ] CRITICAL: Call `task = service._with_phases(run, task)` (the re-synthesis helper from Step 3 Task 4) immediately after loading `task` and BEFORE checking `task.phases_config`. Without this, `phases_config` is always None after DB load and the feature is completely broken.
- [ ] Check `task.phases_config` at the top of the execute flow in executor.py: if `None`, fall through to the existing legacy path (full backward compat — do not touch it)
- [ ] Add phase dispatch loop in executor.py starting at `task.current_phase_index`:
  - For each phase, determine the prompt using `_get_phase_prompt()` from `prompts.py` (Task 2 below)
  - If `phase.profile` is set, override the agent config model for this phase:
    `effective_config = {**run.agent_config, "profile": phase.profile.value}` when `phase.profile is not None`; use `effective_config` to construct the agent instead of `run.agent_config`
  - ⚠️ HARDENING NOTE (Gap 11): `PhaseHandler.execute_phase()` currently only accepts strings `"building"`, `"verifying"`, `"recovering"` — PhaseType values use different strings (`"build"`, `"plan"`, `"summarize"`, `"gap_check"`, `"verify"`). Passing `phase.type.value` directly raises `ValueError("Unknown phase: build")`. You have two implementation choices; pick **one** and be consistent:
    - **Option A (preferred)**: Do NOT route pipeline phases through `phase_handler.execute_phase()`. Instead, call `agent.execute(context, ...)` directly in the executor loop, then capture `task_state.attempts[-1].agent_output` as the output string, then call `engine.complete_phase(run_id, task_id, output or "")`. This avoids all string-mapping confusion.
    - **Option B**: Add new elif branches in `PhaseHandler.execute_phase()` for `"build"`, `"plan"`, `"summarize"`, `"gap_check"` — each runs the agent then RETURNS (does NOT call `submit_for_verification()` internally, which would break the pipeline). The executor then captures output and calls `engine.complete_phase()`. Either way, the handler for pipeline agent phases must never internally call state-transition methods (`submit_for_verification`, `complete_verification`).
  - ⚠️ HARDENING NOTE (Gap 12): For `PhaseType.verify` in a pipeline, do NOT reuse the existing `_execute_verifying` / `complete_verification()` flow unmodified — `complete_verification()` performs its own task completion/failure transitions that conflict with the pipeline's `complete_phase()` call, causing a double-transition bug. Instead:
    - Run the verifier agent to collect grade data
    - Evaluate grades to determine pass/fail
    - **If PASS**: call `engine.complete_phase(run_id, task_id, grade_summary)` to advance the pipeline
    - **If FAIL**: call `engine.complete_verification()` as normal — Step 3 Task 3's retry logic will set `current_phase_index = retry_target` and transition to BUILDING. The executor's phase loop then refreshes `task` and re-dispatches from the new `current_phase_index`.
    - This means the verify phase needs a dedicated pipeline handler that separates "run verifier" from "decide transition".
  - `PhaseType.script`: run `phase.cmd` via subprocess directly in executor.py; exit 0 → `service.engine.complete_phase(run_id, task_id, stdout)`; non-zero → phase failure (advance to `retry_target` or fail task)
  - `PhaseType.auto_verify`: run `LocalAutoVerifyRunner` (from `orchestrator.workflow.auto_verify`); all must items pass → `complete_phase(results_summary)`; any fail → phase failure. Use `LocalAutoVerifyRunner`, not `AutoVerifyRunner`.
  - `PhaseType.human_review`: transition task to `PENDING_USER_ACTION`; executor exits. The resume callback (`POST /tasks/{id}/submit`) normally calls `submit_for_verification()` which transitions BUILDING→VERIFYING. For phase-pipeline tasks in human_review, the callback must instead call `engine.complete_phase(run_id, task_id, "")`. Add a guard in the submit handler in `routers/tasks.py`: if the loaded task has `phases_config` set and the current phase type is `human_review`, call `engine.complete_phase` instead of `submit_for_verification`.
- [ ] After each `complete_phase` call, refresh `task` from service (engine updated the index)

**Dependencies**
- Step 3 complete: `engine.complete_phase` and `engine.advance_phase` implemented

**References**
- `docs/phase-pipelines/step-04-plan.md` — Task 1
- `docs/phase-pipelines/architecture.md` — executor dispatch loop, status mapping table
- `docs/phase-pipelines/clarifications.md` — Q1: status mapping (build→BUILDING, verify→VERIFYING, human_review→PENDING_USER_ACTION)

**Constraints**
- When `phases_config` is `None`, do NOT change existing behavior (full backward compat)
- `phase.cmd` security: apply the existing pipe-rejection validator from `AutoVerifyItemConfig`

**Functionality (Expected Outcomes)**
- [ ] Task with explicit `phases` executes each phase in order
- [ ] Legacy task (no `phases`) runs identically to current behavior
- [ ] Script phase exit 0 → COMPLETED; exit 1 → retries or FAILED

**Final Verification (Proof of Completion)**
- [ ] Integration tests pass (see Task 5)
- [ ] Backward compat: existing task YAML without `phases` runs identically

---

## Task 2: Add Phase Prompt Builders

**Description**: Add `build_plan_phase_prompt`, `build_summarize_phase_prompt`, `build_gap_check_phase_prompt`, and `_format_prior_outputs` to `src/orchestrator/workflow/prompts.py`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/workflow/prompts.py`
- [ ] NOTE: Existing functions `generate_builder_prompt` and `generate_verifier_prompt` return dataclass objects (`BuilderPrompt`, `VerifierPrompt`). The NEW phase prompt builders return `str` directly — they produce the prompt text string to be set as the agent's task context for that phase. This is different from the existing pattern.
- [ ] Add `_format_prior_outputs(prior_outputs: dict[int, str], phases_config: list[PhaseConfig]) -> str`:
  - For each entry in `prior_outputs`, include phase type label and output text truncated to 2000 chars
- [ ] Add `build_plan_phase_prompt(task_config: TaskConfig, phase: PhaseConfig, prior_outputs: dict[int, str], phases_config: list[PhaseConfig]) -> str` — returns a plain string prompt
- [ ] Add `build_summarize_phase_prompt(task_config: TaskConfig, phase: PhaseConfig, prior_outputs: dict[int, str], phases_config: list[PhaseConfig]) -> str`
- [ ] Add `build_gap_check_phase_prompt(task_config: TaskConfig, phase: PhaseConfig, prior_outputs: dict[int, str], phases_config: list[PhaseConfig]) -> str`
- [ ] Add `_get_phase_prompt(task_config: TaskConfig, phase: PhaseConfig, prior_outputs: dict[int, str], phases_config: list[PhaseConfig]) -> str` dispatcher — if `phase.prompt` is set, return it directly (override); otherwise dispatch:
  - `PhaseType.build`: delegate to `generate_builder_prompt(task_config, task_state, ...)` and concatenate `.system + "\n\n" + .user` to produce a plain string
  - `PhaseType.verify`: delegate to existing verifier prompt generation similarly
  - `PhaseType.plan`, `summarize`, `gap_check`: use the new builders above
  - Unknown types: raise `ValueError(f"No prompt builder for phase type: {phase.type}")`

**Dependencies**
- Step 1 complete: `PhaseType`, `PhaseConfig` importable

**References**
- `docs/phase-pipelines/step-04-plan.md` — Tasks 2–3
- `docs/phase-pipelines/architecture.md` — prompt injection design

**Constraints**
- Truncate each prior output to 2000 chars in prompt injection (full text preserved in `phase_outputs` for API display)
- `phase.prompt` field (if set) overrides the default prompt template

**Functionality (Expected Outcomes)**
- [ ] Plan output appears in build phase prompt when prior_outputs has phase 0 entry
- [ ] Each prompt builder returns non-empty string for valid inputs

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.workflow.prompts import build_plan_phase_prompt; print('OK')"` succeeds

---

## Task 3: Update API Schemas

**Description**: Add phase fields to `TaskDetailResponse` and `PromptResponse` in `src/orchestrator/api/schemas/tasks.py`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/api/schemas/tasks.py`
- [ ] Add to `TaskDetailResponse`:
  - `current_phase_index: int = 0`
  - `current_phase_type: str | None = None`
  - `phase_count: int = 0`
  - `phase_outputs: dict[int, str] = Field(default_factory=dict)`
- [ ] ⚠️ HARDENING NOTE (Gap 10): `PromptResponse` already has a `phase: str` field (values: "building" or "verifying"). Do NOT remove or rename this field. Add a NEW field alongside it:
  - `phase_type: str | None = None` — the pipeline phase type from `PhaseType` enum values (e.g. "plan", "build", "summarize"), more granular than the existing `phase` field
  - Both fields coexist. When setting `phase_type` in the router, also ensure `phase` is correctly set: BUILDING-status → `"building"`, VERIFYING-status → `"verifying"`, all others → `"building"` as default.

**Dependencies**
- Step 1 complete: `PhaseType` values known

**References**
- `docs/phase-pipelines/step-04-plan.md` — Tasks 4–5
- `docs/phase-pipelines/clarifications.md` — Q5: dict[int, str] JSON keys

**Constraints**
- All new fields must have defaults so existing API consumers are not broken
- The existing `phase: str` field on `PromptResponse` MUST be preserved — do not remove it

**Functionality (Expected Outcomes)**
- [ ] `TaskDetailResponse` has all 4 new phase fields
- [ ] `PromptResponse` has `phase_type` field

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.api.schemas.tasks import TaskDetailResponse, PromptResponse; print('OK')"` succeeds

---

## Task 4: Populate New Fields in Router Serialization

**Description**: Populate the new `TaskDetailResponse` phase fields in `src/orchestrator/api/routers/tasks.py`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/api/routers/tasks.py`
- [ ] In `get_task` serialization, populate:
  - `current_phase_index` from `task_state.current_phase_index`
  - `current_phase_type` from `task_state.current_phase_type` (property added in Step 2 Task 1)
  - `phase_count`: `phases_config` is NOT persisted to DB. To compute it, you need to re-synthesize from the task config. The routine config is available via `run.routine_embedded` — use `find_task_config()` from `service.py` to get the `TaskConfig`, then call `_synthesize_phases()` from `factory.py` and take `len(result)`. If synthesis returns None, use 0. If the task_state already has `phases_config` populated (it should be set by the executor on load), use `len(task_state.phases_config)`. Handle None gracefully.
  - `phase_outputs` from `task_state.phase_outputs`
- [ ] In the prompt endpoint, populate `phase_type` on `PromptResponse` from `task_state.current_phase_type`

**Dependencies**
- [ ] Task 3 must be complete (schema fields added)

**References**
- `docs/phase-pipelines/step-04-plan.md` — Task 6

**Constraints**
- Handle `phases_config = None` gracefully (return `phase_count=0`)

**Functionality (Expected Outcomes)**
- [ ] GET `/api/tasks/{id}` returns all 4 new phase fields
- [ ] GET `/api/tasks/{id}/prompt` returns `phase_type`

**Final Verification (Proof of Completion)**
- [ ] API response includes all phase fields with correct values

---

## Task 5: Write Integration Tests

**Description**: Create `tests/integration/test_phase_pipelines.py` covering end-to-end phase pipeline execution.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/integration/test_phase_pipelines.py`
- [ ] Write tests with EXPLICIT assertions (not just scenario names):
  - `test_explicit_plan_build_verify_pipeline`: Create a 3-phase task `[plan, build, verify]`. Run it end-to-end. Assert: `task.status == "completed"`, `len(task.phase_outputs) == 3`, plan output (phase 0) is injected into the build phase prompt (check `task.phase_outputs[0]` is non-empty and appears in attempt `builder_prompt`)
  - `test_script_phase_exit_zero`: Script phase with `cmd="exit 0"`. Assert: `task.status == "completed"`, `task.phase_outputs[0]` contains stdout (may be empty string)
  - `test_script_phase_exit_nonzero`: Script phase with `cmd="exit 1"`, `max_attempts=1`. Assert: `task.status == "failed"`, task does NOT remain in building
  - `test_auto_verify_phase_pass`: Auto-verify phase where all `must=True` commands exit 0. Assert: `task.status == "completed"`, `task.phase_outputs[N]` contains pass summary
  - `test_auto_verify_phase_fail`: Auto-verify phase where one `must=True` command exits 1. Assert: task goes back to BUILDING (if attempts remain) or FAILED (if max_attempts exhausted); `task.current_phase_index` is reset to retry_target
  - `test_conditional_phase_skipped`: Phase with `condition` expression that evaluates to False. Assert: phase is skipped, `task.current_phase_index` advances past it, final `task.status == "completed"` after last non-conditional phase
  - `test_verify_retry_target`: Verify phase with `retry_target=0`. Verification fails (verifier grades below threshold). Assert: `task.current_phase_index == 0` (back to phase 0), `task.status == "building"`
  - `test_human_review_phase`: Human_review phase. Assert: `task.status == "pending_user_action"` after executor yields. Submit callback. Assert: task advances to next phase and eventually `task.status == "completed"`
  - `test_backward_compat_no_phases`: Task config with `task_context` only, no explicit `phases`. Assert: task runs build → verify (synthesized), `task.status == "completed"`, identical behavior to pre-feature baseline
  - `test_get_task_includes_phase_fields`: GET `/api/tasks/{id}`. Assert response JSON includes `current_phase_index` (int), `current_phase_type` (str or null), `phase_count` (int), `phase_outputs` (object/dict). For a task mid-pipeline, assert `current_phase_index > 0` and `phase_count > 1`.
- [ ] Run: `uv run pytest tests/integration/test_phase_pipelines.py -v`

**Dependencies**
- [ ] Tasks 1–4 must be complete

**References**
- `docs/phase-pipelines/step-04-plan.md` — Task 7

**Constraints**
- Use the existing test server fixture; do not start a new server

**Functionality (Expected Outcomes)**
- [ ] All 10 integration test cases pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/integration/test_phase_pipelines.py -v` — all pass
- [ ] `uv run pytest tests/integration/ -v` — no regressions

---
