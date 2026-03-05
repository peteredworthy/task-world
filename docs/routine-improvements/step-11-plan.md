# Step 11: Step-level integration tests (A12)

## Milestone
M4: Schema & Architecture Extensions

## Purpose
Add `step_auto_verify` to `StepConfig`, allowing routine authors to define verification commands that run after all tasks in a step complete. These commands verify cross-task integration — e.g., that outputs from multiple tasks work together correctly.

## Prerequisites / Dependencies
- Step 1 (auto_verify timing fix) — shares the auto_verify execution infrastructure in the engine.
- Familiarity with step completion logic in `engine.py` (`check_step_progression` or equivalent).

## Functional Contract

### Inputs
- `StepConfig` with optional `step_auto_verify: list[AutoVerifyItemConfig]`
- Step completion event (all tasks in step have reached terminal state)

### Outputs
- **All step_auto_verify pass:** Step marked complete, run advances to next step
- **Any step_auto_verify fails:** Step marked as failed, run halts (no auto-advance)

### Errors
- Step failure halts the run. Tasks remain in their terminal states (complete or failed), but the step itself is marked failed.
- No intermediate "pending verification" state — it either passes and advances, or fails and stops.

### Schema Addition
```python
class StepConfig(BaseModel):
    # ... existing fields ...
    step_auto_verify: list[AutoVerifyItemConfig] = Field(default_factory=list)
```

## Files Modified
- `src/orchestrator/config/models.py` — add `step_auto_verify` field to `StepConfig`
- `src/orchestrator/workflow/engine.py` — execute step_auto_verify after step tasks complete

## Verification Strategy
- **Unit test:** `StepConfig` accepts `step_auto_verify` field and validates items correctly.
- **Unit test:** Step completion with passing step_auto_verify -> step advances.
- **Unit test:** Step completion with failing step_auto_verify -> step fails, run halts.
- **Unit test:** Step with no step_auto_verify -> existing behavior unchanged (step advances immediately).
- **Regression:** Existing step progression tests pass.
