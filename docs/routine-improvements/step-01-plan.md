# Step 1: Fix auto_verify timing (A1)

## Milestone
M1: Gate Fixes & Safety

## Purpose
Reorder `submit_for_verification()` in `engine.py` so auto_verify commands execute **before** the checklist gate evaluates self-reported status. Currently, auto_verify runs after the gate, meaning a builder can pass the gate by self-reporting all items as done even when auto_verify would fail. This fix restores the intended safety behavior.

## Prerequisites / Dependencies
- None. This is the first step and has no dependencies on other steps.

## Functional Contract

### Inputs
- `submit_for_verification()` call with task state containing:
  - Self-reported checklist item statuses
  - `auto_verify` configuration (list of commands with `must: true/false` flags)

### Outputs
- **Success:** Auto_verify commands all pass (or none configured) AND checklist gate passes -> transition to VERIFYING state
- **Failure:** Any `must: true` auto_verify item fails -> `GateBlockedError` raised with details of which items failed; task remains in BUILDING state

### Errors
- `GateBlockedError` — raised when a `must: true` auto_verify command returns non-zero exit code. Includes the failing command and its output.

### Side Effects
- Auto_verify commands are executed in the task's working directory before the checklist gate evaluation.

## Files Modified
- `src/orchestrator/workflow/engine.py` — reorder logic in `submit_for_verification()`

## Verification Strategy
- **Unit test:** `submit_for_verification()` with a failing `must: true` auto_verify item where all checklist items are self-reported as done -> verify `GateBlockedError` is raised and transition is blocked.
- **Unit test:** `submit_for_verification()` with passing auto_verify -> verify transition proceeds normally.
- **Integration test:** Full submit flow through API with auto_verify configured, verifying the correct HTTP response on failure (409).
- **Regression:** Existing gate tests continue to pass.
