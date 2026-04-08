# Plan: Per-Model Token Accounting

## Milestones

Each milestone ends with a working system where runs can still be created and executed.

### M1: Core Data Model and Cost Config

Add the `ModelTokenUsage` class and cost rate configuration. No behavior changes yet -- this is pure additive infrastructure.

**Steps:**
1. Add `ModelTokenUsage` Pydantic class to `state/models.py` with token count fields, cost rate fields, and `total_cost_usd` computed property. [I-03, I-16]
2. Create `model_costs.yaml` at project root with Sonnet, Haiku, and Opus rates plus `unknown_model` zero-rate default. [I-04, I-17]
3. Create `runners/costs.py` with `get_model_costs(model_name)` that loads rates from YAML and returns zero-rate dict for unknown models. [I-04, I-17]
4. Add `token_usage_by_model: list[ModelTokenUsage] = []` field to `Attempt` and `Run` in `state/models.py`. [I-03, I-19]
5. Unit tests for `ModelTokenUsage.total_cost_usd` computation and `get_model_costs()` lookup (including unknown model fallback). [I-25]

**Verification:** All existing tests pass. New unit tests pass. No behavior change to running system. [I-24]

### M2: DB Migration and Persistence

Persist the new fields to the database.

**Steps:**
1. Add `token_usage_by_model` JSON column to `AttemptModel` and `RunModel` in `db/orm/models.py`. [I-08, I-21]
2. Create Alembic migration adding both columns with default empty JSON array. [I-08, I-12, I-21]
3. Update `db/access/repositories.py` to serialize/deserialize the `token_usage_by_model` field when reading/writing attempts and runs. [I-08]
4. Integration test: create a run, verify empty `token_usage_by_model` persists and round-trips. [I-25]

**Verification:** Migration applies cleanly. Existing runs unaffected (empty list default). All tests pass. [I-24]

### M3: Phase Handler Extraction

Wire up the actual token extraction from `ActionLog` data in the phase handler.

**Steps:**
1. Modify `phase_handler.py` to build `list[ModelTokenUsage]` from `ActionLog` parent-agent fields using `get_model_costs()` for rate lookup. [I-05, I-18]
2. Add sub-agent token extraction: iterate `ActionLog.sub_agents`, group by model name, sum token counts per model, stamp cost rates. [I-05, I-18]
3. Store result on `attempt.token_usage_by_model`. [I-19]
4. Continue populating legacy flat fields (`tokens_cache`, `tokens_read`, `tokens_write`) as the sum across all models. [I-07, I-20]
5. Unit tests for extraction logic with mock ActionLog data covering: parent-only, parent+sub-agents, unknown model, multiple sub-agents of same model. [I-25]

**Verification:** After a run completes, `attempt.token_usage_by_model` is populated with correct per-model breakdown. Legacy fields still correct. [I-18, I-20, I-24]

### M4: Run-Level Aggregation

Accumulate per-model usage across all attempts into run-level totals.

**Steps:**
1. Add aggregation logic: iterate all attempts across all tasks/steps, merge `token_usage_by_model` entries by model name (sum tokens, preserve rates). [I-06]
2. Populate `run.token_usage_by_model` when run completes or on step completion. [I-06, I-19]
3. Continue populating legacy run-level flat fields from the aggregated data. [I-07, I-20]
4. Unit tests for aggregation: multiple attempts with different models, same model across attempts, empty attempts. [I-25]

**Verification:** Run-level `token_usage_by_model` correctly sums across all attempts. Legacy flat fields match. [I-06, I-24]

### M5: API Exposure

Expose per-model data through the REST API.

**Steps:**
1. Add `ModelTokenUsageSchema` to API schemas (`api/schemas/`). [I-09, I-22]
2. Add `token_usage_by_model` field to `AttemptSchema` and `RunResponse`. [I-09, I-22]
3. Update response builders in `api/routers/runs.py` to include the new field. [I-09]
4. Integration test: create a run, verify API response includes `token_usage_by_model` with expected structure. [I-25]

**Verification:** `GET /api/runs/{id}` returns per-model token data. Existing API fields unchanged. [I-22, I-24]

### M6: Frontend Display

Render the per-model breakdown in the UI.

**Steps:**
1. Add TypeScript types for `ModelTokenUsage` in `ui/src/types/runs.ts`. [I-10]
2. Create per-model cost breakdown table component for the run detail page. Display model name, token counts, cost rates, and per-model total cost. [I-10, I-23]
3. Compute and display grand total cost by summing `total_cost_usd` across models. [I-10]
4. Add fallback: when `token_usage_by_model` is empty (old run), show legacy flat fields with "cost estimate, sub-agents not included" disclaimer badge. [I-11, I-23]
5. Frontend tests for the breakdown component: with data, empty data, fallback rendering. [I-25]

**Verification:** Run detail page shows per-model cost table for new runs and disclaimer for old runs. All frontend tests pass. [I-23, I-24]

## Implementation Order

```
M1 (data model + config) -> M2 (DB migration) -> M3 (phase handler) -> M4 (run aggregation) -> M5 (API) -> M6 (frontend)
```

M1-M4 are strictly sequential (each builds on the prior). M5 depends on M4. M6 depends on M5.

## Testing Strategy Per Milestone

| Milestone | Backend Tests | Frontend Tests | Manual Check |
|-----------|--------------|----------------|--------------|
| M1 | Unit: cost computation, YAML loading, unknown model fallback | N/A | N/A |
| M2 | Integration: migration applies, round-trip serialization | N/A | N/A |
| M3 | Unit: extraction from ActionLog (parent, sub-agents, unknowns) | N/A | Run a task, inspect DB |
| M4 | Unit: aggregation across attempts/models | N/A | Complete a run, inspect DB |
| M5 | Integration: API response structure, backward compat | N/A | curl API |
| M6 | N/A | Component: table rendering, fallback, totals | Visual check |

## Risk Mitigations

- **ActionLog structure variance**: Inspect real ActionLog data before coding M3. Handle missing sub-agent fields with zero defaults.
- **Migration safety**: Test migration on a copy of production DB before applying. Columns default to empty JSON array so existing rows are unaffected.
- **Backward compatibility**: Legacy flat fields always populated. Frontend falls back gracefully for pre-migration runs.
- **Incremental commits**: Each milestone committed separately. If M6 has issues, M1-M5 are safe and functional.
