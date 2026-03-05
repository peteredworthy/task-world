# Step 2: Require verification on every task (A2)

## Milestone
M1: Gate Fixes & Safety

## Purpose
Ensure every task has at least one verification mechanism (auto_verify items or a verifier rubric). Tasks with neither are "undefended" — their completion is based solely on self-reported status, which provides no quality assurance.

## Prerequisites / Dependencies
- None. Independent of Step 1, though both are in M1.

## Functional Contract

### Inputs
- **Load-time:** `TaskConfig` model receives task definition from routine YAML
- **Runtime:** `transition_after_verification()` evaluates whether auto-grading is permitted

### Outputs
- **Load-time (default mode):** Task with no auto_verify and no verifier rubric -> log warning, allow loading
- **Load-time (strict mode):** `strict_validation: true` on routine config -> `ValueError` raised, routine rejected
- **Runtime:** Auto-grade path blocked for tasks with no verification configured -> task cannot silently pass

### Errors
- `ValueError` — raised at load time when `strict_validation` is enabled and a task has neither auto_verify nor verifier rubric
- Warning log — emitted at load time in default mode for undefended tasks

### Configuration
- `strict_validation: bool` field on routine config (default: `false`)

## Files Modified
- `src/orchestrator/config/models.py` — `TaskConfig` model_validator
- `src/orchestrator/workflow/transitions.py` — block auto-grade path

## Verification Strategy
- **Unit test:** `TaskConfig` with no auto_verify and no verifier -> warning logged (default mode).
- **Unit test:** `TaskConfig` with `strict_validation: true` and no verification -> `ValueError` raised.
- **Unit test:** `TaskConfig` with auto_verify OR verifier -> validation passes in both modes.
- **Unit test:** `transition_after_verification()` blocks auto-grade when no verification configured.
- **Integration test:** Routine load with undefended task in strict mode -> validation error response.
- **Regression:** Existing routines without strict mode continue to load.
