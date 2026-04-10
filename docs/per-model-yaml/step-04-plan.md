# Step Plan: Run-Level Aggregation (M4)

## Purpose

Accumulate per-model token usage across all attempts into run-level totals. After this step, `run.token_usage_by_model` contains the merged breakdown across all completed attempts, updated in real-time after each attempt completes.

## Prerequisites

- Step 03 complete: `attempt.token_usage_by_model` is populated after each attempt

## Functional Contract

### Inputs

- All `attempt.token_usage_by_model` lists across all tasks/steps in the run
- Each `ModelTokenUsage` entry has: model name, token counts, cost rates

### Outputs

- `run.token_usage_by_model`: merged `list[ModelTokenUsage]` where entries with the same base model name are summed (tokens summed, rates preserved from first occurrence)
- Updated after each attempt completes (not just at run/step completion) for real-time cost visibility
- Legacy run-level flat fields (`total_tokens_cache`, etc.) populated from aggregated per-model data

### Error Cases

- Empty `token_usage_by_model` on attempts: contributes nothing to run-level aggregation
- Conflicting rates for same model across attempts: use rates from first occurrence (rates are stable per model)
- No completed attempts: `run.token_usage_by_model` remains `[]`

## Tasks

1. Add aggregation function: takes `list[list[ModelTokenUsage]]` (one list per attempt), merges by model name (sum tokens, preserve rates from first entry).
2. Wire aggregation into the attempt completion flow: after each attempt completes, re-aggregate across all attempts and update `run.token_usage_by_model`.
3. Continue populating legacy run-level flat fields from aggregated data.
4. Write unit tests:
   - Multiple attempts with different models
   - Same model across multiple attempts (sums correctly)
   - Empty attempts
   - Single attempt (passthrough)

## Verification Approach

### Auto-Verify

- All existing tests pass
- New unit tests pass for aggregation logic
- Legacy flat fields match sum of per-model data at run level

### Manual Verification

- Complete a multi-task run, inspect DB to verify `run.token_usage_by_model` correctly sums across attempts

## Context & References

- Architecture: `docs/per-model-yaml/architecture.md` -- Run Completion section
- Clarification: run-level aggregation updated after each attempt completes (real-time cost visibility)
- Requirement IDs: I-06, I-07, I-19, I-20, I-25
