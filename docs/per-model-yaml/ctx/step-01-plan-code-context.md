# Step 01: Code Locations

## Code Locations

- `src/orchestrator/state/models.py` — `Attempt` class line 238: add `token_usage_by_model: list[ModelTokenUsage] = []` field
- `src/orchestrator/state/models.py` — `Run` class line 378: add `token_usage_by_model: list[ModelTokenUsage] = []` field
- `src/orchestrator/state/models.py` — lines 162–191: add new `ModelTokenUsage` Pydantic class (model name, token counts, cost rates, `total_cost_usd` computed property)
- `src/orchestrator/state/models.py` — `AttemptMetrics` class lines 193–201: legacy flat metrics; leave unchanged
- `config/model_costs.yaml` (new file): YAML with per-model rates for Sonnet 4-6, Haiku 4-5, Opus 4-6, and `unknown_model` zero-rate default
- `src/orchestrator/runners/costs.py` (new file):
  - `_find_cost_file()` lines 30–40: locate `config/model_costs.yaml`
  - `load_cost_table()` lines 43–70: parse YAML into dict
  - `get_model_costs(model_name: str) -> dict[str, float]` lines 73–95: return cost rates; prefix-match for version-suffix normalization; zero-rate fallback for unknown models
