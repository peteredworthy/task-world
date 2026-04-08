# Step 03: Architecture Context

## Phase Handler Integration

Extract `ModelTokenUsage` from ActionLog data in phase handler. Build per-model breakdown from both parent agent and sub-agents. Stamp cost rates from `get_model_costs()` at execution time (rates are frozen in `ModelTokenUsage`, not looked up later).

### Data Flow

```
ActionLog populated with:
  ├── parent: agent_model, total_cache_read_tokens, total_input_tokens, ...
  └── sub_agents[]: model, total_cache_read_tokens, total_input_tokens, ...
    │
    ▼
phase_handler.py._extract_metrics_and_usage()
  ├── get_model_costs(agent_model) → cost rates
  ├── Build ModelTokenUsage for parent model
  ├── Group sub_agents by model, sum tokens per group
  ├── Build ModelTokenUsage for each sub-agent model
  └── Return list[ModelTokenUsage]
    │
    ▼
store_attempt_metrics(token_usage_by_model=...)
  └── Persist to attempt.token_usage_by_model
```

### Error Handling

- ActionLog with no `sub_agents` field or empty list: only parent model entry produced
- ActionLog with missing/null model name: use `"unknown"` as model, gets zero rates
- ActionLog with missing token fields: default to 0

Legacy flat fields (`tokens_cache`, `tokens_read`, `tokens_write`) continue to be populated as the sum across all models.
