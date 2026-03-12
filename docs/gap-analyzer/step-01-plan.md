# Step Plan: Data Models + Schema

## Purpose

Define all new types — enums, Pydantic models, DB columns, and event types — so the rest of the system can reference them without touching the engine or executor. This is the foundation step: everything else depends on these types existing.

## Prerequisites

- None — this is the first step with no dependencies.

## Functional Contract

### Inputs

- Existing `StepConfig` in `src/orchestrator/config/models.py` (to add `step_verifier` field)
- Existing `StepState` in `src/orchestrator/state/models.py` (to add verification fields)
- Existing `StepModel` in `src/orchestrator/db/models.py` (to add DB columns)
- Existing enums in `src/orchestrator/config/enums.py`
- Existing event types in `src/orchestrator/workflow/events.py`

### Outputs

- `StepVerdict` enum (`PASS`, `RETRY`, `FIX`, `FAIL`) in `src/orchestrator/config/enums.py`
- `StepVerifierConfig` Pydantic model in `src/orchestrator/config/models.py` with `prompt: str`, `max_iterations: int = 3`, `auto_verify: AutoVerifyConfig | None = None`
- `step_verifier: StepVerifierConfig | None = None` field on `StepConfig` (optional, backward compatible)
- `GapAction` Pydantic model in `src/orchestrator/state/models.py` with `type`, `task_id`, `feedback`, `title`, `context`, `requirements` fields
- `GapReport` Pydantic model in `src/orchestrator/state/models.py` with `id`, `iteration`, `assessment`, `verdict`, `actions`, `timestamp` fields
- `StepState` gains `verifying: bool = False`, `verifier_iterations: int = 0`, `gap_reports: list[GapReport] = []`
- `StepModel` gains `verifying` (Integer/bool, default 0) and `gap_reports` (JSON, default list) columns
- Alembic migration `add_step_verifier_columns` — safe additive; existing rows default to `verifying=False`, `gap_reports=[]`
- `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` event types in `src/orchestrator/workflow/events.py`
- Unit tests in `tests/unit/test_gap_analyzer_models.py`

### Error Cases

- `StepVerifierConfig` with `max_iterations < 1` — Pydantic validation error
- `GapAction` with `type="retry_task"` and no `task_id` — valid model (engine enforces semantics); callers must supply `task_id`
- `GapReport` with unknown `verdict` string — Pydantic validation error (enum mismatch)
- Alembic migration on an existing DB — safe; no data loss; column defaults apply

## Tasks

1. Add `StepVerdict` enum to `src/orchestrator/config/enums.py`
2. Add `StepVerifierConfig` to `src/orchestrator/config/models.py`; add `step_verifier` field to `StepConfig`
3. Add `GapAction` and `GapReport` to `src/orchestrator/state/models.py`
4. Add `verifying`, `verifier_iterations`, `gap_reports` fields to `StepState`
5. Add `verifying` and `gap_reports` columns to `StepModel` in `src/orchestrator/db/models.py`
6. Create Alembic migration: `alembic revision -m "add step_verifier columns"`
7. Add `StepVerificationStarted`, `GapReportGenerated`, `StepVerificationCompleted` to `src/orchestrator/workflow/events.py`
8. Create `tests/unit/test_gap_analyzer_models.py` with tests for:
   - `GapReport` validation: valid data constructs successfully, missing required fields raise errors
   - `GapAction` with all four types (`retry_task`, `spawn_fix`, `pass`, `fail`)
   - `StepVerifierConfig` defaults: `max_iterations` defaults to 3, `auto_verify` defaults to None
   - `StepVerdict` values: all four members present with correct string values
   - `StepState` default values: `verifying=False`, `verifier_iterations=0`, `gap_reports=[]`
   - Event type construction: all three new event types instantiate correctly

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/test_gap_analyzer_models.py -v` — all new tests pass
- `uv run pytest tests/unit/ -v` — no existing tests broken
- `uv run pyright src/orchestrator/` — no type errors
- Alembic migration applies cleanly: `uv run alembic upgrade head`

### Manual Verification

- Confirm `StepConfig.step_verifier = None` by default (backward compatible; no existing routines break)
- Confirm migration SQL uses `DEFAULT 0` and `DEFAULT '[]'` (or equivalent) for new columns

## Context & References

- Plan: `docs/gap-analyzer/plan.md` — M1 specification
- Architecture: `docs/gap-analyzer/architecture.md` — `StepVerifierConfig`, `GapAction`, `GapReport`, event type definitions
- Clarification: JSON parsing failure → `fail` verdict; retry_task eligibility → COMPLETED tasks only
