# Phase Pipelines — Dry-Run Analysis Notes

Simulation date: 2026-03-12
Steps simulated: 1–5 (step-01.md through step-05.md)

Source files verified against: actual codebase state at simulation time.

---

## Per-Step Simulation Results

### Step 1 — Config Models + Enums

**S1-T1 (PhaseType Enum)**
- `src/orchestrator/config/enums.py` confirmed: pattern `class RunStatus(str, Enum)` is the model to follow.
- No dependencies. Safe first task.

**S1-T2 (PhaseConfig Model)**
- `src/orchestrator/config/models.py` confirmed, all imports in place.
- `ModelProfile` is already defined in `orchestrator.config.enums` and imported into `models.py`.

**S1-T3 (TaskConfig phases + validators)**
- **Gap 6 FOUND**: `TaskConfig` already has a `@model_validator(mode="after")` at line ~193. Pydantic
  allows only ONE `@model_validator(mode="after")` per class — a second one silently overrides the
  first, breaking existing validation for `fan_out + task_context`, `fan_out + script`, etc.
- Fix: extend the EXISTING validator body, not add a new method.

**S1-T4 (Unit tests)**: No issues. File `tests/unit/test_phase_config.py` does not yet exist.

---

### Step 2 — State, DB, and Factory

**S2-T1 (TaskState fields)**: Clean. No outstanding issues.

**S2-T2 (Phase Events)**
- **Gap 5 FOUND**: `plan.md` specifies `output_length: int` on `PhaseCompleted`; step file and
  architecture use `output: str`. The `output: str` version is correct — needed for prior-phase
  prompt injection. The plan.md field name is wrong.

**S2-T3 (TaskModel + Alembic migration)**
- **Gap 1 (partial) FOUND**: Agents following "update WorkflowService" instructions would NOT find
  the actual persistence code. The read/write mapping is in `repositories.py`:
  - Read: `_to_domain()` ~line 167 (TaskModel → TaskState)
  - Write: `_to_model()` ~line 311 (TaskState → TaskModel)
- Int key conversion: JSON serializes `dict[int, str]` keys as strings. Read path must convert back:
  `{int(k): v for k, v in (task_model.phase_outputs or {}).items()}`.

**S2-T4 (Phase Synthesis in Factory)**
- Synthesis ordering: `_warn_if_no_verification` auto-generates a rubric from `requirements` — the
  `auto_verify.items` check must come BEFORE the `verifier.rubric` check in synthesis logic.
- `phases_config` not persisted: after server restart, `TaskState.phases_config = None`. Need
  `WorkflowService._with_phases(run, task)` helper for re-synthesis on load.

**S2-T5 (Synthesis unit tests)**: `test_synthesize_build_auto_verify` must use `requirements=[]`
(no requirements) to prevent auto-rubric generation from converting to `[build, verify]`.

---

### Step 3 — Engine Lifecycle

**S3-T1 (advance_phase)**
- **Gap 3 FOUND**: `_complete_task` does NOT exist on `WorkflowEngine`. No BUILDING→COMPLETED path
  in `VALID_TRANSITIONS`. `complete_verification()` requires VERIFYING status.
  Fix: add `transition_to_completed_direct` to `transitions.py`, update `VALID_TRANSITIONS`,
  add `_complete_phase_pipeline_task` to engine.

- **Gap 4 FOUND**: `ConditionEvaluator.evaluate()` requires `variables` and `step_outcomes`.
  Phase conditions need: `variables = {str(i): output for i, output in task.phase_outputs.items()}`,
  `step_outcomes = {}`. Wrong values cause silent incorrect condition evaluation.

**S3-T2 (complete_phase)**: No additional issues.

**S3-T3 (Verify failure path + start_task resume)**
- **Gap 7 FOUND**: Instruction to "update start_task() to use current_phase_index" is wrong.
  `start_task()` only manages status transitions. The phase dispatch loop is in the executor.
  The resume fix (start at `current_phase_index`, not 0) belongs in executor (Step 4 Task 1).

**S3-T4 (Repository Persistence)**
- **Gap 1 (full) CONFIRMED**: Step originally said "Update WorkflowService" — wrong file.
  Actual mapping is in `src/orchestrator/db/repositories.py` `_to_domain()` and `_to_model()`.
  Int-key coercion required on read.

**S3-T5 (Engine unit tests)**: Need test for new `transition_to_completed_direct` function.

---

### Step 4 — Executor, Prompts, and API

**S4-T1 (Phase dispatch loop)**
- **Gap 2 FOUND**: After server restart, `task.phases_config is None` (not persisted). The
  `if task.phases_config is not None` check would fall through to legacy path for ALL resumed
  tasks. Must call `_with_phases(run, task)` before the dispatch check.

- **Gap 7 (executor side)**: Phase loop must start at `task.current_phase_index`, not 0.

- **Gap 11 FOUND**: `PhaseHandler.execute_phase()` only accepts `"building"`, `"verifying"`,
  `"recovering"` (with -ing suffix). PhaseType values are `"build"`, `"plan"`, `"summarize"`,
  `"gap_check"`, `"verify"` (no -ing). Passing `phase.type.value` directly raises
  `ValueError("Unknown phase: build")`. Additionally, the existing `_execute_building` ends
  by calling `submit_for_verification()` which is wrong for mid-pipeline build phases — it
  would transition to VERIFYING outside the pipeline flow. Fix: For pipeline agent phases
  (build/plan/summarize/gap_check), call `agent.execute()` directly then capture
  `task_state.attempts[-1].agent_output`, then call `engine.complete_phase()`. Do NOT route
  through the existing `_execute_building` which has wrong terminal behavior.

- **Gap 12 FOUND**: For `PhaseType.verify` in a pipeline context, reusing `_execute_verifying`
  / `complete_verification()` unmodified causes a double-transition bug: `complete_verification()`
  does its own task completion/failure transitions, and then the executor also tries to call
  `engine.complete_phase()` — two conflicting state mutations. Fix: Pipeline verify phases need
  a split approach: (a) run verifier agent and collect grades, (b) if PASS → call
  `engine.complete_phase(output)` to advance pipeline; (c) if FAIL → call
  `engine.complete_verification()` to trigger retry via the retry_target path from Step 3 Task 3.

**S4-T2 (Phase prompt builders)**: Confirmed existing builders return dataclasses, new ones must
return `str`. No additional issues.

**S4-T3 (API Schemas)**
- **Gap 10 FOUND**: `PromptResponse` already has `phase: str` field. Adding `phase_type: str | None`
  creates two similar fields. Both are useful but their relationship must be documented.

**S4-T5 (Integration tests)**
- **Gap 8 FOUND**: All test cases were scenario names without concrete assertions. Tests that don't
  assert specific values can pass vacuously and miss regressions.

---

### Step 5 — Frontend

**S5-T2 (PhaseIndicator component)**
- **Gap 9 FOUND**: Test path `ui/src/__tests__/PhaseIndicator.test.tsx` is wrong — that directory
  does not exist. Project convention: tests live adjacent to components in `__tests__/` subdirs.
  Correct: `ui/src/components/detail/__tests__/PhaseIndicator.test.tsx`.

**S5-T6 (Frontend tests)**
- **Gap 9 (full)**: Both `TaskDetailCard.test.tsx` and `ActivityFeed.test.tsx` do not exist yet.
  The step said "add to existing" — must instead CREATE these files.

---

## Persistence Mapping Audit

New state fields introduced in Step 2:

| State Field | DB Column | Repo Write | Repo Read | Migration |
|---|---|---|---|---|
| `TaskState.current_phase_index` | `tasks.current_phase_index` (Integer, default 0) | `repositories.py::_to_model()` — add `current_phase_index=task.current_phase_index` | `repositories.py::_to_domain()` ~line 167 — add `current_phase_index=task_model.current_phase_index` | Alembic migration, Step 2 Task 3 |
| `TaskState.phase_outputs` | `tasks.phase_outputs` (JSON, nullable) | `repositories.py::_to_model()` — add `phase_outputs=task.phase_outputs` | `repositories.py::_to_domain()` — `{int(k): v for k, v in (task_model.phase_outputs or {}).items()}` | Same migration |
| `TaskState.phases_config` | NOT PERSISTED — re-synthesized at load | N/A | `WorkflowService._with_phases(run, task)` helper re-synthesizes from `run.routine_embedded` | N/A |

Notes:
- `phase_outputs` stores `dict[int, str]` in Python. JSON serializes integer keys as strings.
  On DB read, **must coerce back**: `{int(k): v for k, v in raw.items()}`. Failure causes
  `task.phase_outputs[0]` to raise `KeyError` even when data is present.
- `phases_config` is re-synthesized by looking up `task.config_id` in the embedded routine config
  parsed from `run.routine_embedded`. The `_with_phases` helper must be called before any engine
  method or executor code that reads `phases_config`.

---

## Failure Mode Analysis

| Gap | Description | Steps Affected | Failure Mode | Severity |
|---|---|---|---|---|
| Gap 1 | `repositories.py` is the actual persistence layer, not `WorkflowService` | Step 2 T3, Step 3 T4 | Agent implements mapping in wrong file; phase state not persisted; silent data loss on restart | Critical |
| Gap 2 | `phases_config` is None after DB reload — executor must re-synthesize | Step 4 T1 | Resumed tasks fall back to legacy path; phase pipeline not used after server restart | Critical |
| Gap 3 | No BUILDING→COMPLETED transition exists — `_complete_task` is missing | Step 3 T1 | Runtime error calling nonexistent method; pipeline exhaustion crashes engine | Critical |
| Gap 4 | `ConditionEvaluator` variables for phase conditions are unspecified | Step 3 T1 | Conditions evaluate against wrong context; phases skip/run incorrectly; silent bug | High |
| Gap 5 | `PhaseCompleted` field inconsistency: `output_length` (plan.md) vs `output` (step file) | Step 2 T2 | Agent builds wrong event schema; prior-phase prompt injection broken | Medium |
| Gap 6 | Step 1 adds new `@model_validator` instead of extending existing one | Step 1 T3 | Existing fan_out/script/task_context validations silently disabled (second validator overrides first) | High |
| Gap 7 | "Update start_task()" is wrong — resume logic belongs in executor loop | Step 3 T3, Step 4 T1 | Fix applied to wrong method; loop always starts at 0; completed phases re-run after restart | High |
| Gap 8 | Integration test assertions are scenario names, not concrete assertions | Step 4 T5 | Tests pass vacuously; correctness not verified; regressions go undetected | Medium |
| Gap 9 | Frontend test path uses non-existent `ui/src/__tests__/` directory | Step 5 T2, T6 | Test files created in wrong location; never run by vitest | Low |
| Gap 10 | `PromptResponse` already has `phase` field — `phase_type` creates undocumented dual fields | Step 4 T3 | Agents may remove existing field; API consumers confused by two similar fields | Medium |
| Gap 11 | `PhaseHandler.execute_phase()` only accepts `"building"`, `"verifying"`, `"recovering"` — PhaseType values are `"build"`, `"plan"`, `"summarize"`, `"gap_check"`, `"verify"` (string mismatch); additionally `_execute_building` ends with `submit_for_verification()` which is wrong for pipeline phases | Step 4 T1 | `ValueError("Unknown phase: build")` at runtime; or pipeline mid-phases immediately transition to VERIFYING, breaking the loop | Critical |
| Gap 12 | For pipeline `verify` phases, calling both `complete_verification()` (internally in phase handler) AND `complete_phase()` (in executor loop) causes a double-transition bug | Step 4 T1 | Runtime state corruption: task transitions to COMPLETED or BUILDING twice in one cycle | Critical |

---

## Plan Changes Applied to Step Files

All 12 gaps have been applied as targeted edits to the affected step files.
No step file was fully rewritten — only additive notes, constraints, or implementation steps were inserted.

| Gap | Description | Applied to step files | Status |
|---|---|---|---|
| Gap 1 | `repositories.py` is the actual persistence layer (not WorkflowService) | step-02.md T3, step-03.md T4 | YES |
| Gap 2 | `phases_config` is None after DB reload — executor must re-synthesize | step-04.md T1 | YES |
| Gap 3 | `advance_phase` exhausted pipeline — no BUILDING→COMPLETED transition | step-03.md T1, T5 | YES |
| Gap 4 | `ConditionEvaluator` variables for phase conditions are unspecified | step-03.md T1 Constraints | YES |
| Gap 5 | `PhaseCompleted` field: `output: str` not `output_length: int` | step-02.md T2 Constraints | YES |
| Gap 6 | Must EXTEND existing `@model_validator`, not add a second one | step-01.md T3 | YES |
| Gap 7 | "update start_task()" is misleading — resume logic belongs in executor | step-03.md T3, step-04.md T1 | YES |
| Gap 8 | Integration test assertions are scenario names, not concrete assertions | step-04.md T5 | YES |
| Gap 9 | Frontend test path follows wrong convention — `ui/src/__tests__/` doesn't exist | step-05.md T2, T6 | YES |
| Gap 10 | `PromptResponse` already has `phase` field — `phase_type` creates dual fields | step-04.md T3 | YES |
| Gap 11 | `PhaseHandler.execute_phase()` string mismatch + wrong terminal behavior for pipeline agent phases | step-04.md T1 | YES |
| Gap 12 | Pipeline `verify` phase double-transition bug (`complete_verification()` + `complete_phase()`) | step-04.md T1 | YES |

### Summary of changes per file

- **step-01.md T3**: Changed "Add a NEW `@model_validator`" to "EXTEND the existing `@model_validator` at line ~193"; updated Constraints accordingly
- **step-02.md T2**: Added Constraint note that `output: str` is correct (not `output_length` from plan.md)
- **step-02.md T3**: Added int-key JSON conversion requirement to the read path instruction
- **step-03.md T1**: Replaced `_complete_task` reference with full `transition_to_completed_direct` + `VALID_TRANSITIONS` spec; added Gap 4 ConditionEvaluator variables to Constraints
- **step-03.md T3**: Replaced misleading start_task() resume instruction with correct note pointing to executor
- **step-03.md T4**: Already had int-key coercion and `_with_phases` helper spec from prior session
- **step-03.md T5**: Added `test_transition_to_completed_direct` test case
- **step-04.md T1**: Added Gap 2 re-synthesis note; Gap 7 loop-start note; updated ARCHITECTURE NOTE to flag phase_handler routing pitfalls; added Gap 11 with Option A/B for pipeline agent phase dispatch (avoid string mismatch + wrong terminal behavior); added Gap 12 with split pass/fail paths for pipeline verify phases (avoid double-transition bug)
- **step-04.md T3**: Added Gap 10 note clarifying `phase` vs `phase_type` coexistence with router population rules
- **step-05.md T2**: Already had correct path in Final Verification from prior session
- **step-05.md T6**: Changed `ui/src/__tests__/` to `ui/src/components/detail/__tests__/`; changed "add to existing" to "create new" for TaskDetailCard and ActivityFeed test files
