# Step 05: Code Locations

## Code Locations

- `src/orchestrator/api/schemas/tasks.py` — `ModelTokenUsageSchema` lines 81–92: add new schema with all token/cost fields + `total_cost_usd` computed property
- `src/orchestrator/api/schemas/tasks.py` — `AttemptSchema.token_usage_by_model` line 109: add `list[ModelTokenUsageSchema]` field
- `src/orchestrator/api/schemas/runs.py` — `RunResponse.token_usage_by_model` line 159: add `list[ModelTokenUsageSchema]` field
- `src/orchestrator/api/schemas/runs.py` — `RunResponse.estimated_cost_usd` line 160: update to use accurate per-model sum instead of flat gpt-4o estimate
- `src/orchestrator/api/routers/runs.py` — `_run_to_response()` lines 176–203: build `ModelTokenUsageSchema` list, compute `estimated_cost_usd` from per-model totals
- `src/orchestrator/api/metrics.py` — `estimate_cost()` lines 34–70: legacy fallback when no per-model data
