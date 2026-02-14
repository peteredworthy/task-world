# Implementation Gaps: Idea-to-Plan Routine

## Executive Summary

The idea-to-plan routine has structural support for conditional transitions and dry-run execution but lacks complete implementation for:

1. **Backward transitions with state cleanup** - Can transition back but unclear how to clean up task lists and handle re-entry
2. **Dry-run integration with routine fixing** - Dry-run identifies gaps but no mechanism to loop back and fix them
3. **Context management for dry-runs** - Current dry-run uses limited context (4000 tokens), which may omit important details for small models
4. **Dry-run notes application** - Generated notes should drive specific remediation tasks but this flow isn't fully defined

---

## Current State Analysis

### Gap 1: Backward Transitions & Task List Cleanup

**Existing Code:**
- `TransitionTracker` model exists in `state/models.py` (tracks transitions via `counts` dict)
- `StepTransitions` with `on_condition` is defined in `config/models.py`
- `TransitionCondition` supports `max_iterations` limit

**Issues:**
- `TransitionTracker` exists but is never actually used in `workflow/engine.py` or `workflow/service.py`
- When transitioning backwards (S-04 → S-02), there's no explicit cleanup of:
  - Incomplete tasks in intermediate steps (S-03, S-04, S-05)
  - Task-level attempt counters
  - Checklist items marked as completed
- No clear mechanism to distinguish between "first iteration" of a step vs "re-entry after feedback"
- `max_iterations` is a blunt instrument - doesn't support intentional multi-pass iteration

**Questions:**
1. Should we track iteration count per task entry (when you start a task) separately from global transition counts?
2. When transitioning backward, should all downstream tasks be reverted to PENDING, or only the ones that blocked the backward transition?
3. Should there be an API to "clear task list for step" that reverts all tasks to PENDING state?

---

### Gap 2: Dry-Run Integration with Routine Fixing

**Existing Code:**
- `S-06` (Dry Run) has `type: dry_run` and `target_steps: ["S-09"]`
- `execute_dry_run()` in `workflow/dry_run.py` simulates execution and returns `DryRunResult` objects
- `build_dry_run_prompt()` tells the LLM to identify gaps, missing context, and unclear requirements

**Issues:**
- The dry-run simulates steps 1-5 but `target_steps: ["S-09"]` is confusing (S-09 is Execution Ready, which happens *after* the routine is created)
- S-06 task context says "Simulate execution across generated tasks" but the implementation targets a step that hasn't been created yet
- No clear mapping from dry-run gaps back to specific planning artifacts that need updating
- `dry-run-notes.md` template has "Gap Resolution" table but no mechanism to:
  - Extract actionable items from gaps
  - Generate intermediate tasks to fix them
  - Loop back to affected step (S-04 Step Planning, S-05 Task Breakdown, or S-09 routine generation)

**Questions:**
1. Should dry-run work on the actual generated `routines/{{feature}}/routine.yaml` to catch execution issues before final approval?
2. Should we generate intermediate tasks from dry-run gaps (e.g., "Task to improve step-02-plan.md based on identified gaps")?
3. Should there be a post-dry-run gate that checks dry-run severity before allowing progression?

---

### Gap 3: Context Management for Dry-Runs

**Current Implementation:**
- `dry_run.context_limit: 4000` tokens (fixed, per-step)
- `build_dry_run_context()` truncates artifacts evenly across remaining token budget
- Works for large models but may fail for smaller models with context limits

**Issue:**
- With 4000 tokens fixed and multiple artifacts (intent, plan, architecture, design-questions, step files), content gets truncated heavily
- Small models might not catch important gaps due to missing context
- No mechanism to iterate dry-run across multiple task-level simulations with fresh context

**User Suggestion - Dynamic Task Generation for Dry-Run:**
Instead of one monolithic dry-run with truncated context, generate intermediate dry-run tasks:

```
DRY_RUN_TASK_1: Simulate S-05 task execution with full context
  - Load: intent.md, plan.md, step-01-plan.md through step-XX-plan.md
  - Simulate: Each task from step files
  - Output: docs/{{feature}}/dry-run-task-1.md (JSON with results)

DRY_RUN_TASK_2: Compare S-05 simulations to intent
  - Load: intent.md, dry-run-task-1.md
  - Identify: Missing requirements, uncovered edge cases
  - Output: docs/{{feature}}/dry-run-task-2.md

DRY_RUN_TASK_3: Validate generated routine.yaml against step files
  - Load: routine.yaml, step files
  - Identify: Mapping errors, missing context, validation issues
  - Output: docs/{{feature}}/dry-run-task-3.md

DRY_RUN_SYNTHESIS: Aggregate all dry-run outputs
  - Load: dry-run-task-1.md, dry-run-task-2.md, dry-run-task-3.md
  - Synthesize: Consolidated gaps, prioritized fixes
  - Output: docs/{{feature}}/dry-run-notes.md (final report)
```

**Benefits:**
- Each task has fresh context budget
- Can be parallelized or sequenced
- Easier to identify which artifacts need fixing
- Provides clearer remediation path

---

### Gap 4: Dry-Run Notes → Routine Fixes

**Current State:**
- T-01 in S-06 generates `dry-run-notes.md`
- Rubric asks: "Are mitigations concrete enough to apply?"
- But no documented flow from dry-run notes to specific remediation

**Missing Flow:**
1. How should dry-run notes be *applied* to fix planning artifacts?
2. Should there be intermediate tasks that:
   - Read dry-run-notes.md
   - Update the affected artifacts (plan.md, step-XX-plan.md, routine.yaml)
   - Run dry-run validation again?
3. Who decides if dry-run gaps are "critical" (require looping back) vs "minor" (document and proceed)?

**Questions:**
1. Should S-09 T-02 (Create and Validate Routine YAML) have explicit reference to dry-run notes in its context?
2. Should there be a post-dry-run gate with rubric like "Critical gaps fixed?" with options: "No gaps" | "Minor gaps documented" | "Critical - must fix"?
3. If critical gaps found, should we auto-transition to S-05 (Task Breakdown) with a message like "Return to break down tasks based on dry-run feedback"?

---

## Proposed Solutions

### Solution 1: Implement Iteration Tracking Per Task Entry

**Scope:** `state/models.py`, `workflow/transitions.py`, `workflow/service.py`

**Changes:**
- Add `iteration_count` to `TaskState` (tracks attempts within a single task entry)
- Modify `transition_to_building()` to increment `iteration_count` only when transitioning from same step
- Update `max_attempts` semantics: if attempt fails, can retry; if exceeds max, stay in BUILDING until reset
- Add utility to "clear task list for step": revert all tasks to PENDING, reset attempt counts

**Benefit:** Distinguishes between "retrying a failed attempt" (increment attempt) and "re-entering step after feedback" (increment iteration)

---

### Solution 2: Improve Backward Transition Support

**Scope:** `workflow/engine.py`, `workflow/service.py`, `api/routers/tasks.py` (new endpoint)

**Changes:**
- Activate `TransitionTracker` in engine - use it to enforce `max_iterations` limit
- When transitioning backward (S-04 → S-02), explicitly revert downstream step states:
  - Set `S-03.tasks[*].status = PENDING`
  - Set `S-04.tasks[*].status = PENDING`
  - Set `S-05.tasks[*].status = PENDING`
  - Clear `human_approval` if re-entering gate step
- Add API endpoint `PATCH /api/runs/{run_id}/steps/{step_id}/reset` to allow manual reset
- Log transition with reason (e.g., "max_iterations reached for S-03→S-02")

**Benefit:** Explicit state cleanup prevents ghost tasks from blocking progression

---

### Solution 3: Refactor Dry-Run to Generate Intermediate Tasks (Dynamic Chunking)

**Scope:** `workflow/dry_run.py`, `workflow/service.py`, new `workflow/dry_run_tasks.py`

**Changes:**

1. **Create dry-run task generator** (`workflow/dry_run_tasks.py`):
   - Function: `generate_dry_run_tasks(feature, step_plans, routine_yaml) -> list[Task]`
   - For each major artifact group (step plans, routine YAML), generate a dry-run task
   - Tasks contain step context pointing to artifact, full task context for simulation, requirements
   - Output path for each: `dry-run-{task-name}.md` (JSON format)

2. **Modify S-06 routine**:
   - Instead of single T-01, generate multiple tasks dynamically in the routine
   - OR: Keep single T-01 but have it call service method that generates/executes sub-tasks
   - Each sub-task: simulate specific artifact group, write results
   - Final synthesis task aggregates results into `dry-run-notes.md`

3. **Enhanced prompt for dry-run tasks**:
   - Include full context (not truncated)
   - Task-specific instructions: "Simulate S-05 task execution with these step plans"
   - Output format: Structured JSON with step_id, task_id, simulated_outcome, gaps

**Benefit:** Fits small model context windows, provides detailed gap analysis per artifact group

---

### Solution 4: Link Dry-Run Notes to Routine Fixing with Post-Dry-Run Gate

**Scope:** `routine/idea-to-plan.yaml` (S-06, S-07), `workflow/service.py`

**Changes:**

1. **Add post-dry-run gate (new S-06B or within S-07)**:
   - Type: `human_approval` (or `auto_check` if we want to detect critical gaps programmatically)
   - Prompt: Review dry-run-notes.md and gaps table
   - Options: "No critical gaps" (proceed) | "Found critical gaps that need fixing" (return to S-05)

2. **Update S-09 T-02 context**:
   - Add to task_context: "Read docs/{{feature}}/dry-run-notes.md and incorporate feedback into routine.yaml"
   - Reference specific gap categories from dry-run output
   - Add requirement: "Routine YAML incorporates dry-run gap mitigations"

3. **Optional: Generate sub-tasks from dry-run gaps**:
   - If gap severity > threshold, create intermediate task:
     - "Update S-04 step plans based on dry-run findings"
     - "Regenerate S-05 task breakdown with improved specificity"
   - Transition back to S-05 if needed

**Benefit:** Closes loop from dry-run identification → explicit remediation → final routine

---

## Implementation Questions Needing Clarification

1. **Iteration vs Attempt Semantics**:
   - Current code: `max_attempts` on `TaskState` (how many times you can try to complete a task)
   - Should we add `iteration_count` (how many times you enter the step after feedback)?
   - Should exceeding `max_attempts` block task from re-entering, or just stay in BUILDING?

2. **Dry-Run Task Generation Approach**:
   - Option A: Generate dry-run tasks dynamically at S-06 runtime (cleaner, more flexible)
   - Option B: Hard-code them into routine YAML (simpler, less magic)
   - Option C: Hybrid - routine defines a "dry-run generator" task that creates others
   - Preference?

3. **Post-Dry-Run Loop-Back Policy**:
   - Should gap severity be auto-detected (e.g., critical = certain keywords in identified_gaps)?
   - Or always require human decision?
   - Should loop-back go to S-05 (Task Breakdown) or directly to S-04 (Step Planning)?

4. **Dry-Run Notes Application**:
   - Should S-09 T-02 (Create Routine YAML) explicitly read and apply dry-run-notes.md?
   - Or should there be an intermediate task "Apply dry-run feedback to plan artifacts" before S-09?
   - What if dry-run notes conflict with original plan?

5. **Backward Transition Cleanup**:
   - When transitioning S-04 → S-02, which downstream steps should be reset?
   - Just the next step (S-03)?
   - All downstream (S-03, S-04, S-05)?
   - The step that triggered the transition only (S-04)?

---

## Proposed First Implementation Milestone

**Phase 1: Enable backward transitions with state cleanup**
- Activate `TransitionTracker` in engine
- Implement step reset utility
- Add state cleanup on backward transition
- Write tests for transition tracking and cleanup

**Phase 2: Dynamic dry-run task generation**
- Create dry-run task generator
- Modify S-06 routine to use dynamic tasks
- Implement per-task dry-run with full context
- Aggregate results into dry-run-notes.md

**Phase 3: Post-dry-run integration**
- Add post-dry-run gate (manual or auto-detected)
- Update S-09 T-02 to reference dry-run notes
- Implement optional loop-back to S-05 based on severity

---

## Files That Will Need Changes

**Core:**
- `src/orchestrator/state/models.py` - Add iteration tracking, step reset tracking
- `src/orchestrator/workflow/transitions.py` - Implement transition checking against tracker
- `src/orchestrator/workflow/engine.py` - Use transition tracker, add step reset logic
- `src/orchestrator/workflow/service.py` - Add step reset API, dry-run task generation

**New:**
- `src/orchestrator/workflow/dry_run_tasks.py` - Task generator for dry-run
- `src/orchestrator/api/routers/steps.py` (if not exists) - Step reset endpoint
- `tests/unit/test_transitions_backward.py` - New tests for backward transitions
- `tests/unit/test_dry_run_tasks.py` - New tests for task generation

**Routine:**
- `routines/idea-to-plan.yaml` - Add dynamic dry-run task section, post-dry-run gate, apply feedback in S-09 T-02

**Documentation:**
- `docs/plan-runner/idea_to_plan_detailed.md` - Update dry-run section
- `docs/plan-runner/dry-run-process.md` - New detailed doc on how dry-run works end-to-end

---

## Next Steps

1. **Review & Feedback:** Please review this plan and provide:
   - Answers to the implementation questions above
   - Preferences on dynamic vs static dry-run task generation
   - Clarification on iteration/attempt semantics
   - Any constraints I've missed

2. **Refine:** Once I have feedback, I'll update this doc and create detailed task breakdown (steps/step-*.md)

3. **Implementation:** Execute phases in order, maintaining runnable system and passing tests throughout
