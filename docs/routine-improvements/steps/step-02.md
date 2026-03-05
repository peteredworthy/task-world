# Step 2: Require verification on every task (A2)

**Milestone:** M1 — Gate Fixes & Safety
**Plan:** [step-02-plan.md](../step-02-plan.md)
**Architecture:** [architecture.md](../architecture.md) §2 (Config Models, A2)
**Intent:** [intent.md](../intent.md) — Completion Criteria #2
**Clarification:** Q2 in [clarifications.md](../clarifications.md) — warn by default, strict_validation flag

## Tasks

### Task 2.1: Add verification requirement validation to TaskConfig

Add `model_validator` on `TaskConfig` in `models.py` that checks every task
has at least one of: `auto_verify` items or verifier rubric. Default mode:
log warning. Add `strict_validation: bool` to routine config — when True,
raise `ValueError`.

**Files:** `src/orchestrator/config/models.py`
**LOC estimate:** ~40
**Verify:** Unit tests — warning logged in default mode; ValueError in strict
mode; valid tasks pass in both modes.

### Task 2.2: Block auto-grade path for unverified tasks

In `transitions.py`, block the auto-grade code path when no verification
mechanism is configured on the task. Prevent tasks from silently passing.

**Files:** `src/orchestrator/workflow/transitions.py`
**LOC estimate:** ~30
**Verify:** Unit test — `transition_after_verification()` blocks auto-grade
when no verification configured. Existing transition tests pass.

### Task 2.3: Integration test for routine load with strict validation

Test that loading a routine with an undefended task in strict mode returns
a validation error. Existing routines without strict mode continue to load.

**Files:** `tests/integration/` (new or existing test file)
**LOC estimate:** ~30
**Verify:** Test passes with correct validation error response.
