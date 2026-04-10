# Step Plan: Manual Gate Skip Option + API Surface

## Purpose

Add the skip-step API endpoint for manual gates and expose all conditional step data through the API schema. After this step, external clients can see skip state, conditions, and skip reasons on steps, and users can choose to skip manually gated steps.

## Prerequisites

- **Step 2** (Data Model Extensions) -- `skipped`, `skip_reason`, `StepCondition` models exist.
- **Step 3** (Engine Wiring) -- Manual gate pause mechanism works; engine skips steps with `False` conditions.

## Functional Contract

### Inputs

- `POST /runs/{id}/steps/{step_id}/skip` -- new endpoint to skip a manually gated step
- `GET /runs/{id}` -- existing endpoint, now includes conditional step data

### Outputs

- **Skip-step endpoint**: When a run is paused at a manual gate (`pause_reason="manual_gate"`):
  - Marks the gated step as `skipped=True` with `skip_reason="manual_skip"`
  - Emits `StepSkipped` event
  - Advances to the next step (evaluating its condition if present)
  - Resumes the run
  - Returns 200 with updated run state
  - Returns 409 if run is not paused at a manual gate
- **StepSummary schema**: Gains `skipped: bool`, `skip_reason: str | None`, `condition: StepConditionSchema | None` fields
- **RunResponse serialization**: Includes skip data and condition info from `StepModel`

### Error Cases

- Skip-step called when run is not paused -- returns 409 Conflict
- Skip-step called when run is paused but not at a manual gate -- returns 409 Conflict
- Skip-step called with invalid step ID -- returns 404
- Skip-step called for a step that is not the current gated step -- returns 409

## Tasks

1. Add `StepConditionSchema` to `src/orchestrator/api/schemas/runs.py` with `when` and `repeat_for` fields
2. Add `skipped: bool = False`, `skip_reason: str | None = None`, `condition: StepConditionSchema | None = None` to `StepSummary` schema
3. Update `RunResponse` serialization to populate skip data and condition from `StepModel`/`StepState`
4. Add `POST /runs/{id}/steps/{step_id}/skip` endpoint in `src/orchestrator/api/routers/runs.py`:
   - Validate run is paused at manual gate
   - Validate step_id matches the current gated step
   - Mark step as skipped, emit event, advance, resume
5. Update `WorkflowService` with a `skip_step()` method if needed
6. Integration tests in `tests/integration/`:
   - GET run response includes `skipped`, `skip_reason`, `condition` on steps
   - Skipped steps have `StepSkipped` event in activity
   - Skip-step endpoint works for manual gate paused runs (skip and advance)
   - Skip-step returns 409 when not at a manual gate

## Verification Approach

### Auto-Verify

- `uv run pytest tests/integration/ -v` -- all integration tests pass
- `uv run pyright` -- no type errors in schemas or router
- API response schema matches expected fields

### Manual Verification

- Pause a run at a manual gate via API; call skip-step; verify step is skipped and run advances
- GET the run; verify `StepSummary` includes `skipped`, `skip_reason`, and `condition` fields

## Context & References

- Plan: `docs/conditional-steps/plan.md` -- Step 5 specification (M2 remaining)
- Architecture: `docs/conditional-steps/architecture.md` -- Manual gate resume with skip option, `StepSummary` schema
- Clarification Q1: Add skip option so users can choose to skip OR execute
- `src/orchestrator/api/schemas/runs.py` -- `StepSummary` schema
- `src/orchestrator/api/routers/runs.py` -- run endpoints
