# Step Plan: Frontend Display (M6)

## Purpose

Render the per-model cost breakdown table in the UI on the run detail page. Includes TypeScript types, a breakdown table component, grand total computation, fallback for old runs, and "cost unknown" badges for unknown models.

## Prerequisites

- Step 05 complete: API returns `token_usage_by_model` on `RunResponse` and `AttemptSchema`

## Functional Contract

### Inputs

- `RunResponse.token_usage_by_model: ModelTokenUsage[]` from API
- Legacy flat fields (`total_tokens_cache`, `total_tokens_read`, `total_tokens_write`, `estimated_cost_usd`) for backward compatibility with old runs

### Outputs

- TypeScript `ModelTokenUsage` type in `ui/src/types/runs.ts` with all fields matching API schema
- Per-model cost breakdown table component on RunDetail page displaying:
  - Model name
  - Token counts (cache read, cache creation, input, output)
  - Cost rates (per 1M tokens)
  - Per-model total cost USD
- Grand total cost row = `sum(entry.total_cost_usd)` across all models
- "cost unknown" badge next to $0.00 rows where model has zero rates (unknown/unrecognized models)
- Fallback for old runs: when `token_usage_by_model` is empty, show legacy flat fields with "cost estimate, sub-agents not included" disclaimer badge

### Error Cases

- `token_usage_by_model` is `undefined` or `null`: treat as empty array, show fallback
- `token_usage_by_model` is empty array `[]`: show fallback with legacy fields
- All models are unknown (all zero rates): show table with "cost unknown" badges on every row

## Tasks

1. Add `ModelTokenUsage` TypeScript interface to `ui/src/types/runs.ts` and add `token_usage_by_model` field to the run response type.
2. Create per-model cost breakdown table component (or section within RunDetail) that displays model name, token counts, rates, and per-model total.
3. Compute and display grand total cost by summing `total_cost_usd` across all model entries.
4. Add "cost unknown" badge rendering for rows where all cost rates are zero (unknown models).
5. Add fallback rendering: when `token_usage_by_model` is empty, display legacy flat fields with disclaimer badge.
6. Write frontend tests:
   - Table renders correct rows for multi-model data
   - Grand total computed correctly
   - "cost unknown" badge appears for zero-rate models
   - Fallback renders when `token_usage_by_model` is empty
   - Handles single-model and many-model cases

## Verification Approach

### Auto-Verify

- All frontend tests pass (`npm test` in `ui/`)
- TypeScript type check clean (`npm run typecheck` in `ui/`)
- ESLint clean (`npm run lint` in `ui/`)
- Build passes (`npm run build` in `ui/`)

### Manual Verification

- Visual check: run detail page shows per-model cost table for a completed run
- Visual check: old run (pre-migration) shows legacy fields with disclaimer
- Visual check: unknown model row shows "cost unknown" badge

## Context & References

- Architecture: `docs/per-model-yaml/architecture.md` -- Frontend RunDetail section
- Clarification: show "cost unknown" badge next to $0.00 rows for unknown models
- Clarification: when `token_usage_by_model` is empty (old run), show legacy flat fields with disclaimer
- Memory: utility exports must live in separate files from components (React Fast Refresh requirement)
- Requirement IDs: I-10, I-11, I-23, I-25
