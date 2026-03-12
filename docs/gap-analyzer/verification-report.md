# Verification Report: Gap Analyzer + Targeted Retry

**Date**: 2026-03-12
**Scope**: Steps 01–05, all tasks
**Status**: ✓ Ready to Implement

---

## Summary

All five step files are aligned with the intent and plan. Every dry-run gap has been applied to the step files (not just documented). The persistence mapping audit shows no MISSING cells. Integration test step files specify concrete assertion logic. No unresolved conflicts remain.

---

## 1. Intent → Plan → Steps Alignment

| Milestone | Plan Section | Step File | Alignment |
|-----------|-------------|-----------|-----------|
| M1: Data Models + Schema | plan.md §M1 | step-01.md | ✓ |
| M2: Engine Lifecycle + Action Dispatch | plan.md §M2 | step-02.md | ✓ |
| M3 core: Executor + Prompts | plan.md §Step 3 | step-03.md | ✓ |
| M3 remaining: API Surface + Tests | plan.md §Step 4 | step-04.md | ✓ |
| M4: Frontend Display | plan.md §M4 | step-05.md | ✓ |

**Executor-loop clarification**: plan.md originally stated `check_step_progression()` would signal the engine to call `start_step_verification()`. This conflicted with architecture.md's interaction diagram. The clarification (documented in `clarifications.md`) resolves this: the executor manages the full verification loop end-to-end; `check_step_progression()` is not modified. Both plan.md and architecture.md have been updated. Step 2 Task 4 explicitly confirms: "Confirm `check_step_progression()` diff is empty (file must be unchanged)." Step 3 Task 2 wires the executor loop. **No unresolved conflict.**

---

## 2. Dry-Run Gap Application Audit

All 14 gaps (10 numbered + 4 additional) are applied to step files.

| Gap | Description | Applied to Step Files? | Evidence in Step Files |
|-----|-------------|----------------------|------------------------|
| Gap 1 | `verifier_iterations` DB column missing | **YES** | Step 1 T3: `verifier_iterations: Mapped[int] = mapped_column(Integer, default=0)` |
| Gap 2 | `spawned_by_gap_report` missing from persistence stack | **YES** | Step 1 T2 (TaskState field), T3 (TaskModel col+migration), Step 2 T4 (repo read/write), Step 4 T1 (TaskSummary), T2 (serialization) |
| Gap 3 | `gap_report_feedback` missing from persistence stack | **YES** | Step 1 T2 (TaskState field), T3 (TaskModel col+migration), Step 2 T3 (set on retry), T4 (repo read/write), Step 3 T1 (include in prompt), T2 (clear after use) |
| Gap 4 | "call existing step completion path" underspecified | **YES** | Step 2 T2: exact `check_step_progression()` + `check_run_completion()` call pattern with reference to engine.py lines 418–463 |
| Gap 5 | Executor insertion point underspecified | **YES** | Step 3 T2 Step A/B: exact `if task_state is None:` insertion point with full code block |
| Gap 6 | "spawn verifier agent" mechanism underspecified | **YES** | Step 3 T2 Step C: `_run_step_verification` with `agent.execute()` pattern specified in full |
| Gap 7 | Integration test mock strategy missing | **YES** | Step 4 T3: two-track approach — Track A (WorkflowService direct calls), Track B (API response via test client) |
| Gap 8 | Integration test assertions missing for all 8 scenarios | **YES** | Step 4 T3: every scenario has concrete `assert` statements (status, field values, list lengths) |
| Gap 9 | `max_iterations` validator instruction missing | **YES** | Step 1 T1: `@field_validator("max_iterations")` with example code block |
| Gap 10 | `spawned_by_gap_report` missing from `TaskSummary` API schema | **YES** | Step 4 T1: `spawned_by_gap_report: bool = False` added to `TaskSummary` |
| Additional | `spawn_fix` requirements → checklist conversion unspecified | **YES** | Step 2 T3: explicit `ChecklistItem(req_id=..., desc=..., priority=...)` conversion loop |
| Additional | `event_type` string values not specified | **YES** | Step 1 T4: exact snake_case values documented in code comments (`"step_verification_started"`, `"gap_report_generated"`, `"step_verification_completed"`) |
| Additional | Fan-out parent check function doesn't exist | **YES** | Step 3 T2: inline check `any(t.status == TaskStatus.FAN_OUT_RUNNING for t in step.tasks)` |
| Additional | `retry_task` `current_attempt` behavior on retry unclear | **YES** | Step 2 T3: "Do NOT reset `task.current_attempt`" explicitly stated with rationale |

**Result: All 14 gaps applied. No gap shows NO or missing "Applied to step files" field.**

---

## 3. Unresolved Critical Conflicts

None. The only conflict found (executor loop ownership) was resolved during clarification and both plan.md and architecture.md updated. Step files are consistent with the resolution.

---

## 4. Persistence Mapping Audit

New state model fields: 5. All cells in the persistence mapping table are filled.

| State Field | DB Column | Repo Write | Repo Read | Migration |
|---|---|---|---|---|
| `StepState.verifying` | `StepModel.verifying` (Integer, default=0) ✓ Step 1 T3 | `int(step.verifying)` ✓ Step 2 T4 | `bool(step_model.verifying)` ✓ Step 2 T4 | ✓ Step 1 T3 |
| `StepState.verifier_iterations` | `StepModel.verifier_iterations` (Integer, default=0) ✓ Step 1 T3 | `step.verifier_iterations` ✓ Step 2 T4 | `step_model.verifier_iterations or 0` ✓ Step 2 T4 | ✓ Step 1 T3 |
| `StepState.gap_reports` | `StepModel.gap_reports` (JSON, default=list) ✓ Step 1 T3 | `[r.model_dump(mode="json") for r in step.gap_reports]` ✓ Step 2 T4 | `[GapReport(**d) for d in (step_model.gap_reports or [])]` ✓ Step 2 T4 | ✓ Step 1 T3 |
| `TaskState.spawned_by_gap_report` | `TaskModel.spawned_by_gap_report` (Integer, default=0) ✓ Step 1 T3 | `int(task.spawned_by_gap_report)` ✓ Step 2 T4 | `bool(task_model.spawned_by_gap_report)` ✓ Step 2 T4 | ✓ Step 1 T3 |
| `TaskState.gap_report_feedback` | `TaskModel.gap_report_feedback` (Text, nullable) ✓ Step 1 T3 | `task.gap_report_feedback` ✓ Step 2 T4 | `task_model.gap_report_feedback` ✓ Step 2 T4 | ✓ Step 1 T3 |

**No MISSING cells.**

---

## 5. Integration Test Quality Audit

Step 4 Task 3 specifies assertion logic (not just scenario names) for all 8 scenarios.

| Scenario | Scenario Name | Has Concrete Assertions? | Sample Assertion |
|----------|---------------|--------------------------|-----------------|
| 1 | Full lifecycle → pass → step advances | **YES** | `assert step.verifying == False`, `assert run.current_step_index == 1`, `assert step.gap_reports[0].verdict == StepVerdict.PASS` |
| 2 | retry_task → re-run → pass → completes | **YES** | `assert task.status == TaskStatus.PENDING`, `assert task.gap_report_feedback == "try harder"`, `assert step.verifier_iterations == 2` |
| 3 | spawn_fix → new task runs → pass → completes | **YES** | `assert len(step.tasks) == 2`, `assert step.tasks[1].spawned_by_gap_report == True` |
| 4 | fail verdict → run paused | **YES** | `assert run.status == RunStatus.PAUSED`, `assert run.pause_reason == "step_verifier_failed"` |
| 5 | max_iterations → run paused | **YES** | `assert run.pause_reason == "step_verifier_max_iterations"` |
| 6 | invalid JSON → fail verdict in gap report | **YES** | `assert gap_report.verdict == StepVerdict.FAIL`, `assert "Parse error" in gap_report.assessment` |
| 7 | GET response includes new step fields | **YES** | `assert "verifying" in step_data`, `assert step_data["gap_reports"][0]["verdict"] == "retry"` |
| 8 | Regression — normal step advances without verifier | **YES** | `assert step.verifier_iterations == 0`, `assert step.gap_reports == []`, `assert run.status == RunStatus.COMPLETED` |

**All 8 scenarios specify assertion logic. None are scenario-name-only.**

---

## 6. Additional Cross-Checks

### Event Type String Consistency (frontend/backend)
Step 1 Task 4 specifies exact event_type values: `"step_verification_started"`, `"gap_report_generated"`, `"step_verification_completed"`.
Step 5 Task 4 references these exact strings: "Use these exact strings in the ActivityFeed switch/if-else."
**Consistent. ✓**

### `max_iterations` Guard Order
Step 2 Task 2 specifies: "Check `step.verifier_iterations >= step_config.step_verifier.max_iterations` → pause run… (regardless of verdict)" — this check is listed BEFORE verdict dispatch in the implementation plan. The constraint section repeats: "`max_iterations` check runs before verdict dispatch."
**Correctly ordered. ✓**

### `retry_task` COMPLETED-only Eligibility
Step 2 Task 3 constraint: "If task status is not `COMPLETED`, log warning and skip (only COMPLETED tasks eligible per clarifications)."
Aligns with intent.md: "`retry_task` action — re-run a specific completed task."
Aligns with clarifications.md: "`retry_task` eligibility: COMPLETED tasks only (not failed)."
**Consistent. ✓**

### `routine_embedded` None Guard
Step 3 Task 2 step verifier check condition: `if run.routine_embedded is not None` — ensures `start_step_verification` is only called when the routine config is available (preventing a crash inside the engine when accessing `step_config.step_verifier.max_iterations`).
**Guard present. ✓**

### React Fast Refresh Constraint
Step 5 Task 3: "Export from utility file if needed to satisfy React Fast Refresh (per MEMORY.md)."
MEMORY.md rule: "Utility exports must live in separate files from components."
**Referenced. ✓**

### `spawn_fix` `gap_report_feedback` Field on Spawned Tasks
Spawned fix-up tasks (`spawn_fix`) do not set `gap_report_feedback` — only `retry_task` does. Step 2 Task 3 correctly sets `gap_report_feedback = action.feedback` only in the `retry_task` branch. The `spawn_fix` branch creates a fresh `TaskState` with default `gap_report_feedback=None`.
**Correct. ✓**

---

## 7. Verdict

| Check | Result |
|-------|--------|
| Step files align with plan and intent | ✓ Pass |
| All critical/significant dry-run gaps applied to step files | ✓ Pass (14/14) |
| No unresolved critical conflicts | ✓ Pass |
| Persistence mapping has no MISSING cells | ✓ Pass (5/5 fields, 4/4 columns each) |
| Integration test step files specify assertion logic | ✓ Pass (8/8 scenarios) |

**Overall: ✓ Ready to Implement**

The step files are execution-ready. An implementing agent can work through steps 1–5 sequentially and produce a correct, complete gap-analyzer feature.
