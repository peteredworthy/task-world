# Verification Report: Orchestrated Expansion (Option D)

Generated: 2026-03-11
Reviewer: Automated cross-check of intent → plan → steps → dry-run notes

---

## Executive Summary

The overall intent→plan→step chain is well-structured and internally coherent. Clarification decisions are reflected consistently. However, **three critical gaps** identified in the dry-run notes remain unresolved in the step files, and four moderate gaps are partially or fully unresolved. These gaps will cause build failures if not corrected before implementation begins.

**Status: READY WITH REQUIRED FIXES** — the implementation plan is sound, but the specific items listed in the "Unresolved Gaps" section below must be addressed before Step 1 agents begin work.

---

## 1. Intent → Plan Alignment

| Intent Item | Plan Coverage | Status |
|-------------|---------------|--------|
| Expansion API endpoint (`POST .../expand`) | M2, Step 5 | ✅ Covered |
| Three expansion types (add_subtask, add_peer_task, add_next_step) | M2, Steps 3–4 | ✅ Covered |
| ExpansionLimits with 5 fields | M1, Step 1 | ✅ Covered |
| Provenance tracking (expanded_from_task_id, justification, is_expansion) | M1, Steps 1–2 | ✅ Covered |
| TaskExpanded event | M1, Step 1 | ✅ Covered |
| Budget enforcement (429 on exhaustion) | M2, Step 5 | ✅ Covered |
| add_subtask blocking via FAN_OUT_RUNNING | M2, Step 3 | ✅ Covered |
| add_next_step index reordering | M2, Step 4 | ✅ Covered |
| Expansion callback in builder prompt | M3, Step 6 | ✅ Covered |
| Human approval mode (require_human_approval) | M2, Step 4; M2, Step 5 | ✅ Covered |
| MCP tool registration | M3, Step 6 | ✅ Covered |
| Frontend display (badges, dashed borders, step indicator) | M4, Step 7 | ✅ Covered |
| total_expansions on Run | M1, Step 1 | ✅ Covered |
| expansion_count on RunModel | M1, Step 1 | ✅ Covered |
| DB migration (Alembic) | M1, Step 2 | ✅ Covered |
| Integration tests | M2, Step 5 | ✅ Covered |
| Frontend tests | M4, Step 7 | ✅ Covered |

**Verdict: Intent and plan are fully aligned.** All intent items have corresponding plan deliverables.

---

## 2. Clarification Decisions → Step Files Alignment

| Decision | Step(s) Reflecting It | Status |
|----------|-----------------------|--------|
| Q1: StepModel gets is_expansion + expanded_from_task_id | step-01.md Task 3 | ✅ Reflected |
| Q2: add_next_step supports multiple tasks via `tasks` array | step-01.md Task 4 (ExpansionRequest.tasks field) | ✅ Reflected |
| Q3: FAN_OUT_RUNNING tasks cannot call expand (not applicable) | step-03.md Task 2 (Clarification Q3 note) | ✅ Reflected |
| Q4: human approval mode required | step-03.md Task 3, step-04.md | ✅ Reflected |
| Q5: MCP tool registration required | step-06.md Task 3 | ✅ Reflected |

**Verdict: All five clarification decisions are reflected in the step files.**

---

## 3. Dry-Run Gaps — Resolution Status

### Gap 1: StepState Missing Expansion Fields (CRITICAL — UNRESOLVED)

**Dry-run finding**: `StepState` in `state/models.py` needs `is_expansion: bool = False` and `expanded_from_task_id: str | None = None` fields. Without them, Step 4's `add_next_step` cannot set provenance on the new in-memory `StepState` object.

**Step file status**: `step-01.md` Task 2 only adds fields to `TaskState` and `Run`. `StepState` is not mentioned.

**Resolution required**: Add to step-01.md Task 2:
```python
# In StepState:
is_expansion: bool = False
expanded_from_task_id: str | None = None
```

---

### Gap 2: Missing `pending_expansion_request` Storage Field (CRITICAL — UNRESOLVED)

**Dry-run finding**: Human approval mode (Steps 3–4) needs to store the serialized `ExpansionRequest` payload so `approve_expansion()` can deserialize and execute it. The existing `pending_action_type` is only a string tag.

**Step file status**: `step-01.md` Task 2 does not add `pending_expansion_request` to `TaskState`. `step-01.md` Task 3 does not add the DB column to `TaskModel`. `step-03.md` Task 3 references creating a "pending approval record stub" but there is nowhere to store the payload.

**Resolution required**: Add to step-01.md Task 2:
```python
# In TaskState:
pending_expansion_request: str | None = None  # JSON-serialized ExpansionRequest
```
Add to step-01.md Task 3:
```python
# In TaskModel:
pending_expansion_request = Column(Text, nullable=True)
```
Add the corresponding column to Step 2's migration.

---

### Gap 3: Alembic Migration Path Discrepancy (CRITICAL — UNRESOLVED)

**Dry-run finding**: `step-02.md` consistently references `alembic/versions/` (5+ occurrences) but migrations live at `src/orchestrator/db/migrations/versions/`. The `alembic` command also needs `--config src/orchestrator/db/migrations/alembic.ini`.

**Step file status**: `step-02.md` still uses the wrong path throughout. Example from Task 1:
> "Run: `uv run alembic revision --autogenerate -m "add_expansion_columns"`"
> "Open the generated file in `alembic/versions/`"

**Resolution required**: Update all references in step-02.md:
- Replace `alembic/versions/` → `src/orchestrator/db/migrations/versions/`
- Replace `uv run alembic revision ...` → `uv run alembic --config src/orchestrator/db/migrations/alembic.ini revision ...`
- Same fix for `upgrade head`, `downgrade -1`, and `current` commands

---

### Gap 4: expand_fan_out_task() Location Ambiguity (SIGNIFICANT — PARTIALLY RESOLVED)

**Dry-run finding**: `expand_fan_out_task()` lives on `WorkflowService`, not `WorkflowEngine`. Step 3 says the engine should "call existing `expand_fan_out_task()` logic" but the engine doesn't have access to the service.

**Step file status**: `step-03.md` Task 2 says "For `blocking=True`: call existing `expand_fan_out_task()` to set parent → `FAN_OUT_RUNNING`" and lists `Constraints: Call expand_fan_out_task() with the same arguments as the static fan-out path`. This is potentially confusing — an implementor reading this cold may try to call `expand_fan_out_task` from within `WorkflowEngine`.

**Resolution required**: Clarify step-03.md Task 2 with explicit responsibility split:
- **Engine's responsibility**: Set `parent.status = FAN_OUT_RUNNING` directly; add child `TaskState` to `step.tasks`
- **Service's responsibility**: After `engine.expand_task()` returns, call `service.expand_fan_out_task(run_id, task_id)` for worktree creation and full fan-out setup

---

### Gap 5: `requirements` Field Type Inconsistency (MODERATE — UNRESOLVED)

**Dry-run finding**: `architecture.md` defines `requirements: list[dict] | None` in `ExpansionRequest` and `ExpansionTaskSpec`, but `step-01.md` Task 4 uses `list[str] | None`. These are incompatible.

**Step file status**: `step-01.md` Task 4 still says:
> `requirements: list[str] | None = None`

**Resolution required**: Change to `list[dict] | None = None` in both `ExpansionRequest` and `ExpansionTaskSpec` in step-01.md Task 4. Add note: "The dict should accept `{id, desc, must, priority}` keys matching `RequirementConfig`."

---

### Gap 6: MCP Tool Naming Convention (MODERATE — UNRESOLVED)

**Dry-run finding**: All existing MCP tools use the `orchestrator_` prefix (e.g., `orchestrator_submit`, `orchestrator_update_checklist`). Step 6 registers the tool as `expand_task` without the prefix.

**Step file status**: `step-06.md` Task 3 says "Register `expand_task` tool" — no prefix. The Final Verification check also uses `expand_task` in the GET response.

**Resolution required**: Update step-06.md Task 3 to use `orchestrator_expand_task` consistently throughout.

---

### Gap 7: Executor In-Memory State Refresh (MODERATE — PARTIALLY RESOLVED)

**Dry-run finding**: After DB refresh, the executor's `_get_next_task()` iterates `step.tasks` on the in-memory `Run` object — so new tasks from DB won't be seen unless `run.steps[current_step_index].tasks` is also updated.

**Step file status**: `step-06.md` Task 2 says to rebuild `pending` from `service.get_step_tasks()` but only mentions updating the local `pending` variable. It does not explicitly state that `run.steps[current_step_index].tasks` must also be updated.

**Resolution required**: Add to step-06.md Task 2:
> "After rebuild, also update `run.steps[current_step_index].tasks` to include any new task IDs from the refresh (append tasks not already present, matched by ID). This keeps the in-memory Run object consistent with DB state."

---

## 4. No Unresolved Critical Conflicts

The following were potential conflicts in the source documents; all have been resolved:

| Potential Conflict | Source | Resolution |
|-------------------|--------|------------|
| StepModel provenance (idea.md says yes; architecture.md omits) | Clarification Q1 | Both model types track provenance — reflected in step-01 Task 3 |
| add_next_step single vs. multi-task | Clarification Q2 | Multi-task via `tasks` array — reflected in step-01 Task 4 |
| FAN_OUT_RUNNING can expand vs. cannot | Clarification Q3 | Not applicable — FAN_OUT_RUNNING task is not executing — reflected in step-03 Task 2 |
| Human approval required or optional | Clarification Q4 | Required — reflected throughout Steps 3–5 |
| MCP tool required or optional | Clarification Q5 | Required — reflected in step-06 Task 3 |

---

## 5. Step File Quality Notes

### step-01.md
- **Missing StepState fields** (Gap 1 — critical)
- **Missing pending_expansion_request** (Gap 2 — critical)
- **requirements type wrong** (Gap 5 — moderate)
- Otherwise complete and well-structured

### step-02.md
- **Wrong migration paths throughout** (Gap 3 — critical, very high failure risk)
- Intent verification section still references wrong paths

### step-03.md
- **expand_fan_out_task location ambiguous** (Gap 4 — significant)
- Step references `engine.py` `expand_fan_out_task()` in Task 2 references — correctly notes existing fan-out in executor.py, but the responsibility split must be explicit
- Otherwise well-structured

### step-04.md
- Not fully reviewed in this pass; depends on Steps 1–3 gaps being resolved first
- Gap 4 (engine/service split) resolution will clarify `approve_expansion()` implementation

### step-05.md
- Not fully reviewed; depends on prior steps
- Route ordering note (register `/expand/approve` before `/expand`) is correctly identified

### step-06.md
- **MCP tool name missing prefix** (Gap 6 — moderate)
- **In-memory state update not explicit** (Gap 7 — moderate)
- Otherwise complete

### step-07.md
- Not reviewed in depth — frontend step; depends on stable API contract from Step 5
- Key risk: event type string (`task_expanded` vs other serialization) should be confirmed against `workflow/events.py` serialization before implementing `ActivityFeed` handler

---

## 6. Recommended Pre-Implementation Actions

**Must fix before any step begins (Critical):**

1. **step-01.md Task 2**: Add `StepState.is_expansion: bool = False` and `StepState.expanded_from_task_id: str | None = None`
2. **step-01.md Task 2**: Add `TaskState.pending_expansion_request: str | None = None`
3. **step-01.md Task 3**: Add `TaskModel.pending_expansion_request = Column(Text, nullable=True)`
4. **step-02.md (all tasks)**: Fix all `alembic/versions/` references to `src/orchestrator/db/migrations/versions/`; add `--config src/orchestrator/db/migrations/alembic.ini` to all alembic commands; add `pending_expansion_request` column to migration

**Fix before Step 3 begins (Significant):**

5. **step-03.md Task 2**: Clarify engine/service responsibility split for blocking subtask fan-out

**Fix before Step 6 begins (Moderate):**

6. **step-06.md Task 3**: Rename tool from `expand_task` to `orchestrator_expand_task`
7. **step-06.md Task 2**: Explicitly state `run.steps[current_step_index].tasks` must be updated after DB refresh

**Fix before Step 1 Task 4 (Moderate):**

8. **step-01.md Task 4**: Change `requirements: list[str] | None` to `list[dict] | None` in both `ExpansionRequest` and `ExpansionTaskSpec`

---

## 7. Unchanged — Already Correctly Specified

The following items from the dry-run notes are already correctly handled in the step files and require no changes:

- `TaskExpanded` must use `@dataclass` pattern (step-01.md Task 5 says "Match existing event definition patterns")
- Route shadowing (`/expand/approve` before `/expand`) — noted in step-05.md
- Budget exhaustion integration test setup — step-05.md references `expansion_limits` config
- FAN_OUT_RUNNING nested-subtask guard — step-03.md Task 2 has the `parent_task_id` check
- Prompt signature defaults (`expansion_limits: ExpansionLimits | None = None`) — step-06.md Task 1 handles this

---

## Summary Table

| Gap | Severity | Status | Action Required |
|-----|----------|--------|-----------------|
| Gap 1: StepState missing expansion fields | Critical | ❌ Unresolved | Fix step-01 Task 2 |
| Gap 2: Missing pending_expansion_request | Critical | ❌ Unresolved | Fix step-01 Tasks 2–3; step-02 migration |
| Gap 3: Wrong Alembic migration path | Critical | ❌ Unresolved | Fix all paths in step-02 |
| Gap 4: expand_fan_out_task location | Significant | ⚠️ Partial | Clarify step-03 Task 2 |
| Gap 5: requirements field type | Moderate | ❌ Unresolved | Fix step-01 Task 4 |
| Gap 6: MCP tool prefix | Moderate | ❌ Unresolved | Fix step-06 Task 3 |
| Gap 7: Executor in-memory update | Moderate | ⚠️ Partial | Add explicit note to step-06 Task 2 |

**Overall assessment: 3 critical gaps, 1 significant gap, and 3 moderate gaps require resolution before implementation. No critical conflicts exist between intent, plan, and decisions.**
