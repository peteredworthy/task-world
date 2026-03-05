# Step 4: Verifier model pinning (A10)

## Milestone
M1: Gate Fixes & Safety

## Purpose
Pin the verifier model at run creation time so all verification within a run uses the same model, regardless of configuration changes made after the run starts. This ensures consistency within a run.

## Prerequisites / Dependencies
- None. Independent of other M1 steps.

## Functional Contract

### Inputs
- Run creation request with current agent/verifier config
- Current verifier model from config at run creation time

### Outputs
- `Run` state includes `verifier_model: str | None` field, set at creation
- All verifier invocations within the run use the pinned model

### Errors
- None new. If the pinned model becomes unavailable, existing agent error handling applies.

### State Changes
- New field `verifier_model` on `Run` state model, populated at run creation

## Files Modified
- `src/orchestrator/state/models.py` — add `verifier_model` field to Run state
- `src/orchestrator/workflow/engine.py` or `src/orchestrator/agents/executor.py` — set field at run creation, use pinned model for verifier calls

## Verification Strategy
- **Unit test:** Run creation stores current verifier model in `verifier_model` field.
- **Unit test:** Verifier invocation uses `run.verifier_model`, not current config value.
- **Unit test:** Changing config after run creation does not affect pinned model.
- **Regression:** Existing run creation and verification tests pass.
