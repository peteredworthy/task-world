# Step Plan: API Exposure (M5)

## Purpose

Expose per-model token usage data through the REST API by adding schema types and including the new fields in attempt and run responses. Replace the inaccurate `estimated_cost_usd` (flat gpt-4o estimate) with the accurate per-model sum.

## Prerequisites

- Step 04 complete: `run.token_usage_by_model` and `attempt.token_usage_by_model` are populated and persisted

## Functional Contract

### Inputs

- `Attempt.token_usage_by_model: list[ModelTokenUsage]` from domain model
- `Run.token_usage_by_model: list[ModelTokenUsage]` from domain model

### Outputs

- `ModelTokenUsageSchema` Pydantic schema in API schemas with fields:
  - `model: str`
  - `cache_read_tokens`, `cache_creation_tokens`, `input_tokens`, `output_tokens: int`
  - `cost_per_m_cache_read`, `cost_per_m_cache_creation`, `cost_per_m_input`, `cost_per_m_output: float`
  - `total_cost_usd: float`
- `AttemptSchema.token_usage_by_model: list[ModelTokenUsageSchema] = []`
- `RunResponse.token_usage_by_model: list[ModelTokenUsageSchema] = []`
- `estimated_cost_usd` replaced with accurate per-model sum (no more flat gpt-4o estimate with disclaimer)
- `GET /api/runs/{id}` returns per-model token data in response
- `GET /api/runs/{id}/tasks/{id}` returns per-model token data on attempts

### Error Cases

- Old runs with empty `token_usage_by_model`: returns `[]` (empty array), no error
- `estimated_cost_usd` for old runs with empty per-model data: returns 0.0

## Tasks

1. Add `ModelTokenUsageSchema` to `src/orchestrator/api/schemas/` (runs.py or tasks.py as appropriate).
2. Add `token_usage_by_model: list[ModelTokenUsageSchema] = []` to `AttemptSchema` and `RunResponse`.
3. Update response builders in `src/orchestrator/api/routers/runs.py` to populate the new field. Replace `estimated_cost_usd` computation with accurate per-model sum.
4. Write integration test: create a run, verify API response includes `token_usage_by_model` with expected structure. Verify backward compatibility (old runs return empty list).

## Verification Approach

### Auto-Verify

- All existing tests pass
- New integration tests pass:
  - API response includes `token_usage_by_model` array
  - Each entry has all expected fields (model, token counts, rates, total_cost_usd)
  - Old runs return `[]` without error
  - `estimated_cost_usd` matches sum of per-model `total_cost_usd`
- TypeScript type check and ESLint clean (no frontend changes yet)

### Manual Verification

- `curl http://localhost:8000/api/runs/{id}` returns `token_usage_by_model` in response

## Context & References

- Architecture: `docs/per-model-yaml/architecture.md` -- API Changes section with example response fragment
- Clarification: `estimated_cost_usd` replaced with accurate per-model sum (not kept as backward-compat field)
- Requirement IDs: I-09, I-22, I-25
