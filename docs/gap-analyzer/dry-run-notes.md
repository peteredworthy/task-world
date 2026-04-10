# Dry-Run Simulation Notes

**Simulation Date**: 2026-03-12
**Scope**: Steps 01–05, all tasks

---

## Per-Step Simulation Results

### Step 1: Data Models + Schema

**Task 1: Add Enums and Config Models**
- Assumptions: `StepConfig._validate_file_exclusivity` does not need updating (adding `step_verifier=None` won't trigger the "field set when file is set" error). Correct — the validator only errors if the field is non-None/non-empty. No issue.
- Expected output: `StepVerdict` in enums.py, `StepVerifierConfig` in models.py, `step_verifier` on `StepConfig`.
- Blocker: Task 1 instructions say "Verify `max_iterations < 1` raises Pydantic validation error" but do not specify HOW to implement the validator. An agent that implements the field without a `@field_validator` will pass the model but fail the test. **Gap 9.**

**Task 2: Add GapAction, GapReport, StepState fields**
- Architecture defines `GapAction.type` as `Literal["retry_task", "spawn_fix", "pass", "fail"]`. The task description says only `type: str`. An agent may choose `str`, which won't guard against invalid action types. Minor — the engine must handle unknown types gracefully regardless. Note for unit test coverage.
- `GapReport.actions: list[GapAction] = []` — `default_factory` pattern must be used; if agent writes `= []` directly, Pydantic v2 will warn.
- **MISSING**: `TaskState.spawned_by_gap_report` field. Architecture says `spawn_fix` creates `TaskState(spawned_by_gap_report=True, ...)` but this field is not in Step 1 Task 2 instructions. **Gap 2.**
- **MISSING**: `TaskState.gap_report_feedback` field. `retry_task` action must "prepend feedback to next builder prompt" — there's no field to store this between loop iterations. **Gap 3.**

**Task 3: Add DB Columns and Alembic Migration**
- Adds `verifying` (Integer) and `gap_reports` (JSON) to `StepModel`.
- **MISSING**: `verifier_iterations` column. `StepState.verifier_iterations` exists in Task 2 but no corresponding DB column is specified in Task 3 or the step-01-plan. Step 2 Task 4 expects to persist/load it. **Gap 1.**
- **MISSING**: `TaskModel.spawned_by_gap_report` column (needed by Gap 2). **Gap 2.**
- **MISSING**: `TaskModel.gap_report_feedback` column (needed by Gap 3). **Gap 3.**
- Alembic autogenerate note: agent must run in the worktree context (not main project root per MEMORY.md rules).

**Task 4: Add Event Types and Unit Tests**
- Event types look clean; standard `@dataclass` pattern.
- Unit tests straightforward.
- One risk: `StepVerificationStarted` needs `max_iterations` field, but at emission time the engine needs to access `step_config.step_verifier.max_iterations`. The engine loads routine config from `run.routine_embedded`. If routine_embedded is None at emission time (bare Run without embedded routine), the engine will crash. Need a guard.

---

### Step 2: Engine Lifecycle + Action Dispatch

**Task 1: start_step_verification**
- Engine must load `step_config.step_verifier.max_iterations` to include in `StepVerificationStarted` event. This requires loading `RoutineConfig` from `run.routine_embedded`. The same pattern exists in `complete_verification()` (line 418). Clean reference available.
- Idempotency guard on double-call: straightforward.

**Task 2: complete_step_verification**
- "Call existing step completion path" is underspecified. The existing path is `check_step_progression(run, routine_config=..., clock=..., emitter=...)` + `check_run_completion(run, clock.now())` with the same arg construction as in `engine.py:418–461`. If an agent inlines the logic or calls the wrong path, step won't advance. **Gap 4.**
- `max_iterations` check order: architecture spec says check happens BEFORE verdict dispatch, regardless of verdict. Must be explicit.
- `pass` verdict must set `step.verifying = False` AND emit `StepVerificationCompleted` BEFORE calling step completion path (otherwise step is still marked verifying when the completion cascade runs).

**Task 3: retry_task and spawn_fix dispatch**
- `retry_task`:
  - "Prepend `action.feedback` to next builder prompt context": there is no field in `TaskState` to hold pending feedback. Without **Gap 3** fix (adding `gap_report_feedback` field), this is silently dropped. An agent will write code that calls `task.pending_feedback = ...` on a nonexistent attribute and either gets an AttributeError or silently fails with Pydantic strict mode.
  - Reset to PENDING: `task.status = TaskStatus.PENDING` and reset `current_attempt`? Architecture is silent on whether to reset `current_attempt`. If not reset, the attempt counter will be at its current value — which is checked before being incremented on `start_task`. This should be left at its current value (not reset) so `max_attempts` semantics work correctly. Clarify in task.
- `spawn_fix`:
  - Creates new `TaskState(spawned_by_gap_report=True, ...)` — field doesn't exist without Gap 2 fix.
  - `requirements` from GapAction is `list[dict]` in the API schema but `list[RequirementConfig] | None` in architecture. An agent creating `TaskState` from `GapAction.requirements` must construct `ChecklistItem` objects or `RequirementConfig` objects. The `TaskState` stores `checklist: list[ChecklistItem]`, not `requirements`. Need to specify the conversion.

**Task 4: WorkflowService persistence + engine unit tests**
- Serialize `gap_reports` as JSON list of dicts: `[r.model_dump(mode="json") for r in step.gap_reports]`. Deserialize with `[GapReport(**d) for d in raw]`. `GapReport` uses `StepVerdict` enum field — JSON stores string "pass"/"retry" etc. Since `StepVerdict` is `str, Enum`, `GapReport(**d)` will coerce correctly. Clean.
- `verifier_iterations` persistence: requires the missing DB column from Gap 1.
- "Confirm `check_step_progression()` diff is empty" — good guard, keep it.
- `spawned_by_gap_report` and `gap_report_feedback` must be in the Service read/write paths (part of Gap 2 and Gap 3 fixes).

---

### Step 3: Executor + Prompts

**Task 1: build_step_verifier_prompt**
- Clean function signature; pure function, easy to test.
- Risk: `step_state.tasks` may contain fan-out child tasks. The prompt should show only "root" tasks (those with `parent_task_id is None`) since child tasks are ephemeral. Specify this filter in the task.
- `auto_verify_results` can be an empty list — "omit section or show None" — prefer omitting the section to avoid confusing the LLM with an empty section header.

**Task 2: Wire Executor to Step Verification Loop**
- **Gap 5**: "Locate the inner task execution loop where step completion is checked" — there is NO step completion check in the current executor loop. The correct insertion point is BEFORE the `break` at lines ~509–512 of executor.py:
  ```python
  if task_state is None:
      # NEW: check if current step has step_verifier and needs verification
      ...
      break
  ```
  The step verifier check should:
  1. Find the current step (`run.steps[run.current_step_index]`)
  2. Look up step config from `routine_config.steps[...]` by `config_id`
  3. Check `step_config.step_verifier is not None` and not a fan-out parent step
  4. Check `step_state.verifying == False` (not already in a verification cycle) — OR: check if any tasks are PENDING (means retry was dispatched, just need to wait)

  Actually the loop structure is more subtle: after `complete_step_verification` with RETRY/FIX, new tasks become PENDING — `_find_next_task` will return them. The step verifier re-runs AFTER those tasks complete (i.e., when `_find_next_task` returns None again and `step.verifying == True`). So the check is:
  - `task_state is None` AND step has `step_verifier` AND step is not yet `completed` → run verifier

- **Gap 6**: "Spawn verifier agent with prompt (use same agent runner as tasks in step)" — the executor has no `spawn_agent(prompt) -> str` function. The agent runner is accessed via the `AgentRunner.execute(context, on_output, on_agent_metadata)` interface. The executor needs to:
  1. Get the current agent runner via `self._get_agent(agent_type, agent_config, ...)` (or equivalent)
  2. Create an `ExecutionContext` with the verifier prompt
  3. Call `agent.execute(ctx, on_output=collect_output, on_agent_metadata=noop)`
  4. Join collected output lines into a string

  Specify this pattern in the task instructions.

- Fan-out parent step check: need `is_fan_out_parent_step(step)` — check if any task in step has `status == FAN_OUT_RUNNING` or has children. Function does not currently exist; provide inline check: `any(t.status == TaskStatus.FAN_OUT_RUNNING for t in step.tasks)`.

---

### Step 4: API Surface + Integration Tests

**Task 1: GapReportSchema and StepSummary**
- `GapReportSchema.verdict: str` — forward-compatible. Good.
- **Gap 10**: `spawned_by_gap_report` needs to be added to `TaskSummary` in the API schema. Currently `TaskSummary` has no such field. Without it, the frontend (Step 5) has nothing to bind to. Step 4 Task 1 must add this. **Gap 10.**

**Task 2: Update Serialization**
- `StepModel.verifying` is `Integer` → coerce to `bool`: `bool(step_model.verifying)`. Already pattern-matched in existing code (`bool(step_model.completed)`).
- `gap_reports` deserialization risk: `StepModel.gap_reports` may be `None` for pre-migration rows. `(step_model.gap_reports or [])` handles it.
- `TaskModel.spawned_by_gap_report` deserialization required. Part of Gap 2 fix.

**Task 3: Integration Tests**
- **Gap 7**: "Mock or stub the verifier agent output" — no mechanism specified. Looking at existing tests:
  - Tests in `test_mock_agent_workflow.py` use `MockAgent` directly with `WorkflowService`
  - Tests that need executor behavior use `spawn_agents=False` on `AgentRunnerExecutor`
  - For gap-analyzer integration tests, the recommended approach is to call `WorkflowService` methods directly (bypassing the executor), using `service.start_step_verification()` and `service.complete_step_verification()` with a fabricated `GapReport`. This tests the full stack (DB persistence, engine dispatch, API response) without needing to mock agent output.
  - For executor-level tests (scenarios that test the executor detecting the step-verifier condition), a separate test using `MockAgent` + `AgentRunnerExecutor(spawn_agents=True)` with the mock returning controlled JSON is needed.
  Specify this two-track approach in the task.

- **Gap 8**: All 8 scenarios lack concrete assertions. Specify below (see Integration Test Assertions section).

---

### Step 5: Frontend Display

**Task 1: TypeScript Types**
- `spawned_by_gap_report?: boolean` — must be optional with `false` default for backward compat. Specified in step.
- `StepSummary` new fields must have defaults to avoid breaking existing component usage. Checked: `verifying: boolean = false`, `verifier_iterations: number = 0`, `gap_reports: GapReport[] = []`.

**Task 2: StepTimeline**
- `getStepState()` union type must include `'verifying'`. Check test coverage.
- `max_iterations` not on `StepSummary` — denominator unavailable at frontend; show "Verifying N" without denominator. Already specified in step.

**Task 3: GapReportCard**
- Collapsible pattern: check existing codebase for accordion/collapsible. Likely uses CSS `details/summary` or Tailwind `hidden/block` toggled by state.
- Fast Refresh: if utilities are exported from the component file, it will break. Must ensure `GapReportCard` exports only the component (no utilities mixed in).

**Task 4: Fix-up Tasks and Activity Feed**
- Event type strings must match EXACTLY: `"step_verification_started"`, `"gap_report_generated"`, `"step_verification_completed"` (snake_case per existing event pattern in `events.py` — check `event_type` field values of existing events like `"task_status_changed"`, `"step_completed"`).
- Step 1 Task 4 instructions say to add event dataclasses but don't specify the `event_type` string values. Specify these as the snake_case equivalents of the class names.

---

## Persistence Mapping Audit

New state model fields introduced (gaps identified and fixed — all applied to step files):

| State Field | DB Column | Repo Write | Repo Read | Migration |
|---|---|---|---|---|
| `StepState.verifying` | `StepModel.verifying` (Integer, default=0) | `int(step.verifying)` — Step 2 Task 4 ✓ | `bool(step_model.verifying)` — Step 2 Task 4 ✓ | Step 1 Task 3 ✓ |
| `StepState.verifier_iterations` | `StepModel.verifier_iterations` (Integer, default=0) — Step 1 Task 3 ✓ | `step.verifier_iterations` — Step 2 Task 4 ✓ | `step_model.verifier_iterations or 0` — Step 2 Task 4 ✓ | Step 1 Task 3 ✓ |
| `StepState.gap_reports` | `StepModel.gap_reports` (JSON, default=list) | `[r.model_dump(mode="json") for r in step.gap_reports]` — Step 2 Task 4 ✓ | `[GapReport(**d) for d in (step_model.gap_reports or [])]` — Step 2 Task 4 ✓ | Step 1 Task 3 ✓ |
| `TaskState.spawned_by_gap_report` | `TaskModel.spawned_by_gap_report` (Integer, default=0) — Step 1 Task 3 ✓ | `int(task.spawned_by_gap_report)` — Step 2 Task 4 ✓ | `bool(task_model.spawned_by_gap_report)` — Step 2 Task 4 ✓ | Step 1 Task 3 ✓ |
| `TaskState.gap_report_feedback` | `TaskModel.gap_report_feedback` (Text, nullable) — Step 1 Task 3 ✓ | `task.gap_report_feedback` — Step 2 Task 4 ✓ | `task_model.gap_report_feedback` — Step 2 Task 4 ✓ | Step 1 Task 3 ✓ |

**No MISSING cells.** All gaps resolved: Step 1 Task 3 adds DB columns + Alembic migration; Step 2 Task 4 adds `_to_domain()` and `_to_model()` mappings in `repositories.py`.

---

## Failure Mode Analysis

| Step | Failure Mode | Likelihood | Hardening Action |
|---|---|---|---|
| S1-T1 | `max_iterations < 1` not validated — test fails because agent didn't add validator | HIGH | Add explicit `@field_validator("max_iterations")` instruction with example |
| S1-T2 | `spawned_by_gap_report` field missing from `TaskState` — spawn_fix crashes at runtime | HIGH | Add field to Step 1 Task 2 instructions |
| S1-T2 | `gap_report_feedback` missing from `TaskState` — feedback silently dropped on retry | HIGH | Add field to Step 1 Task 2 instructions |
| S1-T3 | `verifier_iterations` missing DB column — service.py can't persist it, integration tests fail | HIGH | Add to migration instructions |
| S1-T3 | `spawned_by_gap_report` missing DB column — spawn_fix tasks lose flag on reload | HIGH | Add to migration instructions |
| S1-T3 | `gap_report_feedback` missing DB column — feedback lost on server restart mid-loop | HIGH | Add to migration instructions |
| S1-T4 | `event_type` string values not specified for new events — frontend strings don't match | MEDIUM | Specify snake_case values in Task 4 instructions |
| S2-T2 | "call existing step completion path" — agent inlines `check_step_progression` or calls wrong method | HIGH | Reference exact function call with line numbers |
| S2-T3 | `retry_task` feedback can't be stored — no field exists yet | HIGH | Resolved by Gap 3 fix; add cross-reference |
| S2-T3 | `spawn_fix` requirements → checklist conversion unspecified — agent creates `TaskState` without checklist | HIGH | Specify conversion: `requirements: list[dict]` → `checklist: list[ChecklistItem]` |
| S2-T3 | `task.current_attempt` behavior on retry — unclear if it should reset | MEDIUM | Clarify: do NOT reset current_attempt; keep it for max_attempts semantics |
| S3-T2 | Executor insertion point wrong — agent checks AFTER break instead of before | HIGH | Specify exact location relative to `if task_state is None:` block |
| S3-T2 | "spawn verifier agent" mechanism — agent imports wrong class or uses wrong API | HIGH | Specify: use `AgentRunner.execute()` via same pattern as `PhaseHandler._run_agent_phase()` |
| S3-T2 | Fan-out parent check — `is_fanout_parent_step` doesn't exist | MEDIUM | Replace with inline check |
| S3-T2 | `step.verifying` still True after RETRY/FIX — executor loop detects step verifying and skips tasks | MEDIUM | Clarify: tasks reset to PENDING will be picked up; verifying flag stays True |
| S4-T1 | `spawned_by_gap_report` missing from `TaskSummary` — frontend type error | HIGH | Add to Step 4 Task 1 |
| S4-T3 | No test mock strategy — tests can't control verifier output | HIGH | Specify WorkflowService direct-call approach |
| S4-T3 | Scenario assertions absent — tests pass vacuously or test wrong things | HIGH | Add concrete `assert` statements to each scenario |
| S5-T4 | `event_type` string mismatch frontend/backend | MEDIUM | Cross-reference backend event_type values |

---

## Plan Changes (Applied to Step Files)

### Gap 1: `verifier_iterations` DB column missing
**Applied to step files: YES** — Step 1 Task 3 updated to add `verifier_iterations` column.

### Gap 2: `spawned_by_gap_report` missing from persistence stack
**Applied to step files: YES** — Step 1 Task 2 (TaskState field), Step 1 Task 3 (TaskModel column + migration), Step 2 Task 4 (repo read/write), Step 4 Task 1 (TaskSummary), Step 4 Task 2 (serialization).

### Gap 3: `gap_report_feedback` missing from persistence stack
**Applied to step files: YES** — Step 1 Task 2 (TaskState field), Step 1 Task 3 (TaskModel column + migration), Step 2 Task 3 (set in retry_task dispatch), Step 2 Task 4 (repo read/write), Step 3 Task 1 (include in prompt), Step 3 Task 2 (pass to prompt builder).

### Gap 4: "call existing step completion path" underspecified
**Applied to step files: YES** — Step 2 Task 2 updated with exact function references.

### Gap 5: Executor insertion point underspecified
**Applied to step files: YES** — Step 3 Task 2 updated with exact insertion location and guard conditions.

### Gap 6: "spawn verifier agent" mechanism underspecified
**Applied to step files: YES** — Step 3 Task 2 updated with specific agent execution pattern.

### Gap 7: Integration test mock strategy missing
**Applied to step files: YES** — Step 4 Task 3 updated with direct-call + MockAgent strategies.

### Gap 8: Integration test assertions missing
**Applied to step files: YES** — Step 4 Task 3 updated with concrete assertion per scenario.

### Gap 9: `max_iterations` validator instruction missing
**Applied to step files: YES** — Step 1 Task 1 updated with `@field_validator` instruction.

### Gap 10: `spawned_by_gap_report` missing from `TaskSummary` API schema
**Applied to step files: YES** — Step 4 Task 1 updated to include `TaskSummary` extension.

### Additional: `spawn_fix` requirements → checklist conversion unspecified
**Applied to step files: YES** — Step 2 Task 3 updated with explicit conversion instructions.

### Additional: `event_type` string values not specified
**Applied to step files: YES** — Step 1 Task 4 updated with snake_case string values.

### Additional: Fan-out parent check function doesn't exist
**Applied to step files: YES** — Step 3 Task 2 updated with inline check.

### Additional: `retry_task` `current_attempt` behavior clarified
**Applied to step files: YES** — Step 2 Task 3 updated with explicit guidance.

---

## Integration Test Assertions (Gap 8 Detail)

### Scenario 1: Full lifecycle → pass → step advances
```python
# Setup: routine with step_verifier, 1 task
# Actions: start_run, complete task to COMPLETED, call start_step_verification, complete_step_verification(verdict=PASS)
assert run.steps[0].verifying == False
assert run.steps[0].completed == True
assert run.steps[0].verifier_iterations == 1
assert run.current_step_index == 1  # advanced to next step
assert len(run.steps[0].gap_reports) == 1
assert run.steps[0].gap_reports[0].verdict == StepVerdict.PASS
```

### Scenario 2: retry_task → re-run → pass → completes
```python
# First verifier call: verdict=RETRY with retry_task action
assert run.steps[0].verifying == True
task = run.steps[0].tasks[0]
assert task.status == TaskStatus.PENDING
assert task.gap_report_feedback == "the feedback string"
# After task completes and second verifier call: verdict=PASS
assert run.steps[0].completed == True
assert run.steps[0].verifier_iterations == 2
```

### Scenario 3: spawn_fix → new task runs → pass → completes
```python
# After spawn_fix dispatch
assert len(run.steps[0].tasks) == 2
assert run.steps[0].tasks[1].spawned_by_gap_report == True
# After all tasks complete and second verifier pass
assert run.steps[0].completed == True
```

### Scenario 4: fail verdict → run paused
```python
assert run.status == RunStatus.PAUSED
assert run.pause_reason == "step_verifier_failed"
assert run.steps[0].verifying == False
```

### Scenario 5: max_iterations → run paused
```python
# Set max_iterations=1, call complete_step_verification with retry verdict
assert run.status == RunStatus.PAUSED
assert run.pause_reason == "step_verifier_max_iterations"
```

### Scenario 6: invalid JSON → run paused
```python
# Agent returns "not json"
gap_report = run.steps[0].gap_reports[-1]
assert gap_report.verdict == StepVerdict.FAIL
assert "Parse error" in gap_report.assessment
assert run.status == RunStatus.PAUSED
```

### Scenario 7: GET response includes new fields
```python
response = client.get(f"/api/runs/{run_id}")
step = response.json()["steps"][0]
assert "verifying" in step
assert "verifier_iterations" in step
assert "gap_reports" in step
assert isinstance(step["gap_reports"], list)
```

### Scenario 8: Regression — step without step_verifier advances normally
```python
# Routine without step_verifier; task completes
assert run.steps[0].completed == True
assert run.status == RunStatus.COMPLETED
# Confirm none of start_step_verification / complete_step_verification were called
```
