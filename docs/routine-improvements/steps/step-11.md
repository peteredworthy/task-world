# Step 11: Step-level integration tests (A12)

**Milestone:** M4 — Schema & Architecture Extensions
**Plan:** [step-11-plan.md](../step-11-plan.md)
**Architecture:** [architecture.md](../architecture.md) §1 (Workflow Engine, A12) and §2 (Config Models, A12)
**Intent:** [intent.md](../intent.md) — Completion Criteria #8
**Clarification:** Q3 in [clarifications.md](../clarifications.md) — failure halts the run

## Tasks

### Task 11.1: Add step_auto_verify field to StepConfig

Add `step_auto_verify: list[AutoVerifyItemConfig]` to `StepConfig` with
empty default. Schema-only change.

**Files:** `src/orchestrator/config/models.py`
**LOC estimate:** ~10
**Verify:** Unit test — StepConfig accepts step_auto_verify field; validates
items correctly; empty default preserves existing behavior.

### Task 11.2: Execute step_auto_verify after step completion

In the step completion path in `engine.py`, after all tasks reach terminal
state, execute `step_auto_verify` commands. If any fail, mark step as failed
and halt the run (no auto-advance). If all pass, advance normally.

**Files:** `src/orchestrator/workflow/engine.py`
**LOC estimate:** ~50
**Verify:** Unit tests — passing step_auto_verify advances step; failing
step_auto_verify halts run; no step_auto_verify preserves existing behavior.
Existing step progression tests pass.
