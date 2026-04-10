# Intent: Per-Model Token Accounting

## Goal

Replace the flat, parent-only token counter with a per-model token breakdown that includes embedded cost rates, so the UI shows accurate run costs instead of the current ~27% undercount. [I-01]

Sub-agent tokens (the majority of cost in discovery-heavy runs) must be visible, and different model price tiers (Sonnet vs Haiku) must be accounted for separately rather than collapsed into a single flat rate. [I-02]

## Scope

### In Scope

- **`ModelTokenUsage` data model** -- new Pydantic class carrying per-model token counts (cache_read, cache_creation, input, output) and embedded cost rates (USD per 1M tokens). Added as a `list[ModelTokenUsage]` field on both `Attempt` and `Run`. [I-03]
- **Cost rate configuration** -- new `config/model_costs.yaml` file and `runners/costs.py` loader providing `get_model_costs(model_name)`. Ships with rates for Sonnet, Haiku, and Opus. Unknown models default to zero rates. Model names are normalized by base name (e.g. `claude-sonnet-4-6-20250514` maps to `claude-sonnet-4-6`) for both cost lookup and display grouping. [I-04]
- **Phase handler extraction** -- `phase_handler.py` builds the `ModelTokenUsage` list from `ActionLog` parent and sub-agent data, stamping cost rates at execution time. [I-05]
- **Run-level aggregation** -- accumulate per-model usage across all attempts/tasks/steps into `Run.token_usage_by_model`. Updated after each attempt completes for real-time cost visibility. [I-06]
- **Legacy field backward compatibility** -- existing flat fields (`AttemptMetrics.tokens_cache`, `Run.total_tokens_cache`, etc.) continue to be populated as the sum across all models, so nothing that reads them breaks. [I-07]
- **DB persistence** -- new JSON columns on `attempts` and `runs` tables via Alembic migration. Old runs keep empty lists; new runs get full breakdowns. [I-08]
- **API exposure** -- `ModelTokenUsageSchema` added to `AttemptSchema` and `RunResponse`. Frontend receives the full per-model array with embedded rates and computed `total_cost_usd`. The existing `estimated_cost_usd` field is replaced with the accurate per-model sum (no longer uses flat gpt-4o estimate). [I-09]
- **Frontend display** -- per-model breakdown table on the run detail page. Total cost computed client-side by summing `total_cost_usd` across models. Unknown models (zero rates) display a "cost unknown" badge. No model-to-cost mapping needed in frontend code. [I-10]
- **Fallback for old runs** -- frontend checks for `token_usage_by_model` presence; if empty (pre-migration run), falls back to legacy flat fields with a "cost estimate, sub-agents not included" disclaimer. [I-11]

### Out of Scope

- Backfilling historical runs with per-model data (they stay on legacy flat fields). [NO-REQ]
- Real-time streaming of token counts during execution. [NO-REQ]
- User-editable cost rates in the UI. [NO-REQ]
- Cost alerting or budget limits. [NO-REQ]

## Constraints

- Alembic migrations only -- no `create_all` or DB recreation. [I-12]
- Cost rates are embedded at execution time so historical accuracy is preserved when prices change. [I-13]
- The system must remain runnable after each milestone. [I-14]
- Each task touches fewer than 5 files and fewer than 500 lines. [I-15]

## Definition of Complete

1. `ModelTokenUsage` class exists in `state/models.py` with token counts and cost rate fields, plus a `total_cost_usd` computed property. [I-16]
2. `config/model_costs.yaml` ships with Sonnet, Haiku, and Opus rates; `runners/costs.py` loads it and returns zero-rate defaults for unknown models. [I-17]
3. `phase_handler.py` builds per-model usage from both parent and sub-agent `ActionLog` data. [I-18]
4. `Attempt.token_usage_by_model` and `Run.token_usage_by_model` are populated on new runs. [I-19]
5. Legacy flat token fields (`tokens_cache`, `total_tokens_cache`, etc.) still populated as the sum across all models. [I-20]
6. Alembic migration adds JSON columns to `attempts` and `runs` tables. [I-21]
7. API responses include `token_usage_by_model` array with per-model token counts, embedded rates, and computed cost. [I-22]
8. Frontend displays per-model cost breakdown table on run detail; old runs show legacy fields with disclaimer. [I-23]
9. All existing tests pass after each milestone. [I-24]
10. Unit tests cover cost computation, phase handler extraction, run-level aggregation, and API serialization. [I-25]

## Resolved Design Decisions

Decisions made via clarification round (see `docs/per-model-yaml/clarifications.md`):

1. **Unknown model display**: Show "cost unknown" badge next to $0.00 rows for unknown/unrecognized models in the frontend cost breakdown.
2. **Model name normalization**: Normalize by base model name (e.g. `claude-sonnet-4-6-20250514` → `claude-sonnet-4-6`). Group variants together in both cost lookup and UI display.
3. **Run-level aggregation timing**: Update `run.token_usage_by_model` after each attempt completes (not just at run/step completion), providing real-time cost visibility for in-progress runs.
4. **`estimated_cost_usd` field**: Replace the legacy flat gpt-4o estimate with the accurate per-model sum from `token_usage_by_model`. No backward-compatibility shim needed.
5. **`model_costs.yaml` location**: Lives at `config/model_costs.yaml` (dedicated config directory).

## Key Unknowns and Risks

| Unknown | Risk | Mitigation |
|---------|------|------------|
| `ActionLog.sub_agents` structure may vary by runner type | Some runners may not populate sub-agent fields | Inspect actual ActionLog data from E8 runs; handle missing fields gracefully [I-05] |
| JSON column size for runs with many attempts | Large JSON payloads in DB and API responses | Per-model list is small (typically 2-3 models); monitor but unlikely to be an issue [I-08] |
| Model name strings may differ across runner types | Mismatched keys in cost lookup | Normalize model names by base name (strip version suffixes) in `get_model_costs()`; group by base model in UI; unknown models get zero rates with "cost unknown" badge [I-04, I-17] |
| Legacy flat fields used by other code paths | Breaking changes if we stop populating them | Keep populating flat fields as sum across models -- explicitly backward compatible [I-07, I-20] |
| Frontend component integration with existing RunDetail | Merge conflicts or layout issues | Per-model table is additive (new section), not a rewrite of existing UI [I-10, I-23] |
