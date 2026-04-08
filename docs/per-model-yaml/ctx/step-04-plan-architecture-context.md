# Step 04: Architecture Context

## Run-Level Aggregation

Merge per-model token usage across all attempts into run-level totals. Updated after each attempt completes (not just at run/step completion) for real-time cost visibility.

### Aggregation Logic

Input: `list[list[ModelTokenUsage]]` (one list per attempt)

Output: merged `list[ModelTokenUsage]` where entries with the same base model name are summed:
- Token counts summed across matching model entries
- Cost rates preserved from first occurrence (rates are stable per model)

### Integration Point

`RunRepository.update_latest_attempt()` merges attempt-level `token_usage_by_model` into run-level totals by:
1. Iterating all attempts for the run
2. Grouping their `token_usage_by_model` entries by base model name
3. Summing token counts for each model
4. Storing result on `run.token_usage_by_model`

### Error Handling

- Empty `token_usage_by_model` on attempts: contributes nothing to run-level aggregation
- Conflicting rates for same model across attempts: use rates from first occurrence
- No completed attempts: `run.token_usage_by_model` remains `[]`

Legacy run-level flat fields (`total_tokens_cache`, etc.) populated from aggregated per-model data.
