# Step Plan: Data Model Extensions

## Purpose

Extend all data models (config, state, DB, events, API schemas) to represent conditional steps. After this step, the system can store and serialize step conditions, skip state, and skip events -- even before the engine acts on them. All model changes are grouped into one step to avoid multiple migrations.

## Prerequisites

- **Step 1** (Safe Evaluator) -- `StepOutcome` and `ConditionEvalError` exist to reference in type annotations.

## Functional Contract

### Inputs

- Existing `StepConfig` in `src/orchestrator/config/models.py`
- Existing `StepState` in `src/orchestrator/state/models.py`
- Existing `StepModel` in `src/orchestrator/db/models.py`
- Existing event types in `src/orchestrator/workflow/events.py`

### Outputs

- `StepCondition` Pydantic model with `when: str | None` and `repeat_for: str | None` fields in `config/models.py`
- `StepConfig.condition: StepCondition | None = None` field (optional, backward compatible)
- `StepState.skipped: bool = False` and `StepState.skip_reason: str | None = None` fields in `state/models.py`
- `StepModel.skipped` (Boolean, default False) and `StepModel.skip_reason` (String, nullable) columns via Alembic migration
- `StepSkipped` event type in `workflow/events.py` with `step_index`, `step_id`, `condition`, `reason` fields
- Routine YAML files with `condition` blocks parse correctly into `StepConfig`

### Error Cases

- Alembic migration on existing DB must be safe: `skipped` defaults to `False`, `skip_reason` defaults to `None` for all existing rows
- Routines without `condition` blocks continue to parse identically (no regression)
- `StepCondition` with neither `when` nor `repeat_for` is valid (no-op condition)

## Tasks

1. Add `StepCondition` Pydantic model to `src/orchestrator/config/models.py`
2. Add `condition: StepCondition | None = None` field to `StepConfig`
3. Add `skipped: bool = False` and `skip_reason: str | None = None` to `StepState` in `state/models.py`
4. Add `skipped` and `skip_reason` columns to `StepModel` in `db/models.py`
5. Create Alembic migration for the new columns with safe defaults
6. Add `StepSkipped` event class to `workflow/events.py`
7. Ensure `create_run_from_routine()` in `state/factory.py` preserves the `condition` field on steps (no expansion at creation time)
8. Unit tests: verify `StepCondition` parsing, `StepConfig` with/without condition, `StepState` skip fields, `StepSkipped` event serialization

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/ -v` -- all existing + new tests pass
- `uv run pyright` -- no type errors
- Alembic migration applies cleanly: `uv run alembic upgrade head`
- Existing routines parse without errors (no regression)

### Manual Verification

- Create a routine YAML with `condition.when` and `condition.repeat_for` fields and verify it loads into `StepConfig` correctly
- Verify `StepModel` table has new columns after migration

## Context & References

- Plan: `docs/conditional-steps/plan.md` -- Step 2 specification (M1 remaining)
- Architecture: `docs/conditional-steps/architecture.md` -- `StepCondition`, `StepState`, `StepModel`, `StepSkipped` definitions
- `src/orchestrator/config/models.py` -- `StepConfig` definition
- `src/orchestrator/state/models.py` -- `StepState` definition
- `src/orchestrator/db/models.py` -- `StepModel` definition
- `src/orchestrator/workflow/events.py` -- event types
- `src/orchestrator/state/factory.py` -- `create_run_from_routine()`
