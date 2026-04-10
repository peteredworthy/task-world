# Code Map: Per-Model Token Accounting

## Core Data Model (M1)

- `src/orchestrator/state/models.py` — `ModelTokenUsage` lines 162–191: Pydantic class with token counts, cost rate fields, and `total_cost_usd` computed property
- `src/orchestrator/state/models.py` — `SubAgentLog` lines 88–112: Per-sub-agent token data with `model`, `total_input_tokens`, `total_output_tokens`, `total_cache_read_tokens`, `total_cache_creation_tokens`
- `src/orchestrator/state/models.py` — `ActionLog` lines 114–148: Parent-level token totals + `sub_agents: list[SubAgentLog]` (line 137) + sub-agent aggregate totals (lines 139–143)
- `src/orchestrator/state/models.py` — `Attempt.token_usage_by_model` line 238: `list[ModelTokenUsage]` field on Attempt
- `src/orchestrator/state/models.py` — `Run.token_usage_by_model` line 378: `list[ModelTokenUsage]` field on Run
- `src/orchestrator/state/models.py` — `AttemptMetrics` lines 193–201: Legacy flat metrics (`tokens_read`, `tokens_write`, `tokens_cache`)

## Cost Rate Configuration (M1)

- `config/model_costs.yaml` — Config directory: Sonnet, Haiku, Opus rates in USD per 1M tokens; `unknown_model` zero-rate default
- `src/orchestrator/runners/costs.py` — `_find_cost_file()` lines 30–40: Locates `config/model_costs.yaml` (config dir or CWD)
- `src/orchestrator/runners/costs.py` — `load_cost_table()` lines 43–70: Parses YAML into `_cost_table` dict
- `src/orchestrator/runners/costs.py` — `get_model_costs()` lines 73–95: Returns cost-rate dict for a model name; supports exact match and prefix matching; zero-rate fallback for unknown models

## DB Persistence (M2)

- `src/orchestrator/db/orm/models.py` — `RunModel.token_usage_by_model` lines 87–89: JSON column on runs table
- `src/orchestrator/db/orm/models.py` — `AttemptModel.token_usage_by_model` lines 219–221: JSON column on attempts table
- `src/orchestrator/db/migrations/versions/p1a2b3c4d5e6_add_token_usage_by_model.py` — Alembic migration adding both JSON columns with `server_default='[]'`
- `src/orchestrator/db/access/repositories.py` — `_to_domain()` lines 127–133, 279–281: Deserializes JSON → `ModelTokenUsage` objects for attempts and runs
- `src/orchestrator/db/access/repositories.py` — `_to_model()` lines 300–304, 420–424: Serializes `ModelTokenUsage` → JSON for storage

## Phase Handler Extraction (M3)

- `src/orchestrator/runners/execution/phase_handler.py` — `PhaseHandler._extract_metrics_and_usage()` lines 50–113: Builds `list[ModelTokenUsage]` from ActionLog parent (lines 67–80) and sub-agents grouped by model (lines 83–100); derives legacy flat metrics as sums (lines 102–111)
- `src/orchestrator/runners/execution/phase_handler.py` — `PhaseHandler._execute_building()` line 263: Calls `_extract_metrics_and_usage()`, passes result to `store_attempt_metrics()` at line 270
- `src/orchestrator/runners/execution/phase_handler.py` — `PhaseHandler._execute_verifying()` line 390: Same pattern for verifier phase
- `src/orchestrator/runners/execution/phase_handler.py` — `PhaseHandler._execute_recovering()` line 460: Same pattern for recovery phase

## Attempt Store & Run-Level Aggregation (M3/M4)

- `src/orchestrator/runners/execution/attempt_store.py` — `AttemptStore.store_attempt_metrics()` lines 109–131: Accepts `token_usage_by_model` kwarg, delegates to `RunRepository.update_latest_attempt()`
- `src/orchestrator/db/access/repositories.py` — `RunRepository.update_latest_attempt()` lines 842–869: Accumulates per-model usage into both attempt-level (lines 842–855) and run-level (lines 856–869) breakdowns by merging entries with matching model names

## API Exposure (M5)

- `src/orchestrator/api/schemas/tasks.py` — `ModelTokenUsageSchema` lines 81–92: API schema with all token/cost fields + `total_cost_usd`
- `src/orchestrator/api/schemas/tasks.py` — `AttemptSchema.token_usage_by_model` line 109: `list[ModelTokenUsageSchema]`
- `src/orchestrator/api/schemas/runs.py` — `RunResponse.token_usage_by_model` line 159: `list[ModelTokenUsageSchema]`
- `src/orchestrator/api/schemas/runs.py` — `RunResponse.estimated_cost_usd` line 160, `cost_disclaimer` line 161: Legacy cost fields
- `src/orchestrator/api/routers/runs.py` — `_run_to_response()` lines 176–203: Builds `ModelTokenUsageSchema` list, computes `estimated_cost_usd` from per-model totals (or falls back to legacy estimate)
- `src/orchestrator/api/metrics.py` — `estimate_cost()` lines 34–70: Legacy flat-token cost estimate (fallback when no per-model data)

## Frontend (M6)

- `ui/src/types/runs.ts` — `ModelTokenUsage` interface lines 40–51: TypeScript type for per-model token usage
- `ui/src/types/runs.ts` — `RunResponse` interface lines 58–93: Includes `token_usage_by_model`, `estimated_cost_usd`, `cost_disclaimer`
- `ui/src/types/tasks.ts` — `AttemptSchema` interface lines 81–101: Includes `token_usage_by_model`
- `ui/src/components/detail/MetricsBar.tsx` — `MetricsBar()` lines 40–81: Displays run-level tokens and cost; falls back to `estimateCost()` if no backend cost
- `ui/src/components/detail/AttemptHistory.tsx` — `AttemptHistory()` lines 10–57: Per-attempt flat metrics display
- `ui/src/components/dashboard/RunDetail.tsx` — `RunDetailInner()` lines 55+: Main run detail view composing MetricsBar and AttemptHistory
