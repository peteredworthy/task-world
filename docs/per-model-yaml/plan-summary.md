# Plan Summary: Per-Model Token Accounting

*Generated: 2026-04-08*

## Intent Satisfaction Summary

The per-model token accounting feature replaces the flat, parent-only token counter with a detailed per-model breakdown that includes embedded cost rates. This satisfies the core goal: **accurate run cost accounting that shows sub-agent tokens and different model price tiers**, addressing a ~27% cost undercount in discovery-heavy runs.

### Key Intent Items Satisfied

| Goal | How | YAML Coverage |
|------|-----|---------------|
| Per-model token tracking | `ModelTokenUsage` class with token counts + cost rates | S-01 (model + config) |
| Sub-agent visibility | Phase handler extracts from `ActionLog.sub_agents` | S-03 (extraction) |
| Different model tiers | Per-model rates (Sonnet, Haiku, Opus) in cost config | S-01 (config) |
| Accurate UI display | API exposes per-model array; frontend renders table | S-05–S-06 (API + UI) |
| Backward compatibility | Legacy flat fields populated as sum across models | S-03, S-04 (handlers) |
| Real-time visibility | Run-level aggregation updated per-attempt | S-04 (aggregation) |
| Historical accuracy | Cost rates embedded at execution time | S-03 (phase handler) |

**Status: All intent items [I-01 through I-25] addressed.**

---

## Ordered Step List with Task Counts

### Milestone M1: Core Data Model and Cost Config
**Purpose**: Establish data structures and configuration; no behavior changes yet.  
**Runnable after**: All tasks pass; runs still execute (no payload changes).

| Step | Task | Description | File Impact |
|------|------|-------------|-------------|
| S-01 | T-01 | Create `config/model_costs.yaml` with Sonnet, Haiku, Opus rates | 1 config file |
| | T-02 | Add `ModelTokenUsage` Pydantic class to `state/models.py` | state/models.py |
| | T-03 | Create `runners/costs.py` with `get_model_costs()` loader | 1 new module |
| | T-04 | Unit tests: cost computation, YAML loading, unknown fallback | tests/unit/test_costs.py |

**Task count: 4 tasks in 1 step.**

### Milestone M2: DB Migration and Persistence
**Purpose**: Persist new fields to database without affecting existing runs.  
**Runnable after**: All tasks pass; migration applied; empty lists default for old runs.

| Step | Task | Description | File Impact |
|------|------|-------------|-------------|
| S-02 | T-01 | Add `token_usage_by_model` JSON column to ORM (AttemptModel, RunModel) | db/orm/models.py |
| | T-02 | Create Alembic migration adding both columns | 1 migration file |
| | T-03 | Update repository serialization/deserialization | db/access/repositories.py |
| | T-04 | Integration tests: round-trip persistence, empty defaults | tests/integration/test_token_usage_persistence.py |

**Task count: 4 tasks in 1 step.**

### Milestone M3: Phase Handler Token Extraction
**Purpose**: Wire up actual token extraction from `ActionLog` data.  
**Runnable after**: All tasks pass; runs get per-model token breakdown in `token_usage_by_model`.

| Step | Task | Description | File Impact |
|------|------|-------------|-------------|
| S-03 | T-01 | Modify `phase_handler.py` to build per-model list from ActionLog | phase_handler.py |
| | T-02 | Unit tests: parent-only, parent+sub-agents, unknown model, multiple sub-agents | tests/unit/test_phase_handler_extraction.py |

**Task count: 2 tasks in 1 step.**

### Milestone M4: Run-Level Aggregation
**Purpose**: Accumulate per-model usage across all attempts into run totals.  
**Runnable after**: All tasks pass; `run.token_usage_by_model` populated after each attempt.

| Step | Task | Description | File Impact |
|------|------|-------------|-------------|
| S-04 | T-01 | Add aggregation logic to merge attempts by model name | orchestrator/service.py or executor.py |
| | T-02 | Populate `run.token_usage_by_model` after each attempt completes | orchestrator/service.py |
| | T-03 | Unit tests: multiple attempts, same model across attempts, empty attempts | tests/unit/test_run_aggregation.py |

**Task count: 3 tasks in 1 step.**

### Milestone M5: API Exposure
**Purpose**: Expose per-model data through REST API responses.  
**Runnable after**: All tasks pass; `GET /api/runs/{id}` returns per-model token data.

| Step | Task | Description | File Impact |
|------|------|-------------|-------------|
| S-05 | T-01 | Add `ModelTokenUsageSchema` to API schemas | api/schemas/tasks.py or runs.py |
| | T-02 | Add `token_usage_by_model` field to `AttemptSchema` and `RunResponse` | api/schemas/runs.py |
| | T-03 | Integration tests: API response structure, per-model array, cost computation | tests/integration/test_api_token_usage.py |

**Task count: 3 tasks in 1 step.**

### Milestone M6: Frontend Display
**Purpose**: Render per-model cost breakdown in the UI; fallback for old runs.  
**Runnable after**: All tasks pass; frontend type checks and tests clean.

| Step | Task | Description | File Impact |
|------|------|-------------|-------------|
| S-06 | T-01 | Add TypeScript types for `ModelTokenUsage` | ui/src/types/runs.ts |
| | T-02 | Create `ModelCostBreakdown` component for run detail page | ui/src/components/ModelCostBreakdown.tsx + integration in RunDetail.tsx |
| | T-03 | Frontend tests: breakdown rendering, fallback for old runs, totals | ui/tests/ModelCostBreakdown.test.tsx |

**Task count: 3 tasks in 1 step.**

### Summary
- **Total steps**: 6 (M1–M6)
- **Total tasks**: 19 (4 + 4 + 2 + 3 + 3 + 3)
- **Strictly sequential**: M1 → M2 → M3 → M4 → M5 → M6
- **Each milestone**: ~2–4 tasks per step; runnable after completion.

---

## Key Decisions

The following design decisions were made during the clarification round. See `docs/per-model-yaml/clarifications.md` for full Q&A.

1. **Unknown Model Display**  
   Show "cost unknown" badge next to $0.00 rows in the frontend cost breakdown. This signals to users that the model is not recognized in `model_costs.yaml`, not that cost is actually zero.

2. **Model Name Normalization**  
   Normalize model names by base name (e.g., `claude-sonnet-4-6-20250514` → `claude-sonnet-4-6`). Group variants together in both cost lookup (`get_model_costs()`) and UI display (single row per base model with aggregated tokens).

3. **Run-Level Aggregation Timing**  
   Update `run.token_usage_by_model` after **each attempt completes**, not just at run/step completion. This provides real-time cost visibility for in-progress runs and individual attempt costs.

4. **`estimated_cost_usd` Field**  
   Replace the legacy flat gpt-4o estimate with the accurate per-model sum from `token_usage_by_model`. No backward-compatibility shim needed; the verifier accepts the change.

5. **`model_costs.yaml` Location**  
   Lives at `config/model_costs.yaml` per the original plan—though note that `runners/costs.py` loads from the project root (not config/). The clarification notes update this explicitly.

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| `ActionLog.sub_agents` structure varies by runner type; some runners may not populate it | Medium | Incomplete token data for some runner types | Inspect actual ActionLog data from E8 runs before M3. Handle missing sub_agents with zero defaults in `phase_handler.py`. |
| JSON column size explodes with large runs | Low | Large DB rows and API payloads | Per-model list is typically 2–3 models; monitor in integration tests. Acceptable unless runs exceed 100 tasks. |
| Model name strings differ across runner types (e.g., `claude-sonnet-4-6` vs `sonnet-4-6`) | Medium | Mismatched keys in cost lookup; unknown-model fallback triggered too often | Implement robust normalization in `get_model_costs()` that strips version suffixes and handles common aliases. Group by base model in UI. |
| Legacy flat fields read by other code paths | Medium | Silent data corruption if we stop populating them | Explicitly populate flat fields as sum across all models. Add integration tests that assert legacy fields match for all runs. |
| Frontend component integration with existing RunDetail creates merge conflicts | Low | Build failures or layout issues | Per-model table is additive (new section), not a rewrite. Add clear TODOs for integration points. |
| Cost rates in `model_costs.yaml` become stale relative to actual API pricing | Low (mitigation in place) | Historical runs get inaccurate costs if rates change | Cost rates are embedded at execution time, so old runs keep their original rates. New runs pick up new rates automatically. |
| Alembic migration fails on production DB | Low | Rollback required; downtime | Test migration on a copy of production DB before applying. Columns default to empty JSON array, so existing rows unaffected. Migration is append-only (no column removal or type changes). |

---

## Caveats for Execution

### Pre-Execution Checklist

- [ ] Verify `model_costs.yaml` exists at project root (not `config/`); inspect current rates for Sonnet, Haiku, Opus.
- [ ] Inspect actual `ActionLog` structure from recent E8 runs to confirm `sub_agents` field and schema.
- [ ] Ensure all existing tests pass before starting M1.
- [ ] Check that no concurrent builder is modifying `state/models.py`, `db/orm/models.py`, or `api/schemas/`.

### During Execution

**M1 (Data Model & Config)**
- `costs.py` must look at project root for `model_costs.yaml`, not `config/`. The clarification notes confirm this.
- Unknown models default to zero-rate dict; ensure tests cover this fallback.
- `ModelTokenUsage.total_cost_usd` is a computed property (not stored); verify it rounds to 2 decimal places for display.

**M2 (DB Migration & Persistence)**
- Alembic migration must use `Column(JSON)` or `mapped_column(JSON)` depending on SQLAlchemy version. Check ORM model syntax before writing migration.
- Empty list default `[]` means old runs have `token_usage_by_model = []`; verify API response handles this gracefully (no None values).
- Run migrations on a test DB copy first to catch syntax errors.

**M3 (Phase Handler Extraction)**
- `ActionLog.sub_agents` may be a list of dicts or a nested structure. Inspect the actual data before implementing.
- Handle missing `sub_agents` field with `getattr(action_log, 'sub_agents', [])` to avoid KeyError.
- Legacy flat fields (`tokens_cache`, `tokens_read`, `tokens_write`) must be populated as the sum across all models for backward compatibility.

**M4 (Run-Level Aggregation)**
- Aggregation merges by model name (after normalization). Ensure the merge logic extracts and re-applies cost rates correctly.
- Update run-level fields after each attempt (not just at run completion) for real-time visibility.
- If `Attempt.token_usage_by_model` is empty, contribute nothing to the run total (treat as zero).

**M5 (API Exposure)**
- `ModelTokenUsageSchema` must include `total_cost_usd` as a computed field (not stored).
- Old runs (pre-migration) will have `token_usage_by_model = []`; API response must handle this and optionally fall back to legacy fields.
- The `estimated_cost_usd` field on `RunResponse` is replaced with the per-model sum (accurate, not an estimate).

**M6 (Frontend Display)**
- Imported component must be called `ModelCostBreakdown` or `MetricsBar` (per existing code). YAML notes that `MetricsBar` exists but is not wired; builder must choose one approach.
- "Cost unknown" badge shown next to $0.00 rows (unknown models).
- Grand total computed client-side by summing `total_cost_usd` across all models.
- Fallback: if `token_usage_by_model` is empty, show legacy flat fields with disclaimer "cost estimate, sub-agents not included."
- TypeScript: `AttemptSchema.token_usage_by_model` may be optional; fallback gracefully if missing.

### Post-Execution Checklist

- [ ] All 6 steps complete and committed.
- [ ] All existing tests pass (no regressions).
- [ ] New unit tests cover: cost computation, YAML loading, extraction logic, aggregation, API schema.
- [ ] New integration tests verify: persistence round-trip, API response structure, end-to-end flow (build → complete → verify cost).
- [ ] Frontend type checks and linting pass.
- [ ] Manual check: create a run, observe per-model cost breakdown in API response and UI.
- [ ] Verify old runs (pre-migration) show legacy fields with disclaimer.

### Known Limitations (Not Blocking)

1. **Rate value validation**: `S-01 T-01` auto_verify checks model key presence, not specific rate values. Builders should manually inspect `model_costs.yaml` for correctness.
2. **Parent-only model testing**: Unit tests for unknown *parent* model (only unknown sub-agent) are not included. Behavior is correct; gap is test coverage only.
3. **Legacy run coupling**: Legacy flat run fields derive from `metrics` (same source as per-model data) rather than re-summed from `run.token_usage_by_model`. Functionally equivalent.
4. **AttemptSchema optional field**: `token_usage_by_model` may be missing from `AttemptSchema` in `tasks.ts`. This is acceptable for M6 (run-level table is the primary goal).

---

## Execution Order and Dependencies

```
M1: Data Model & Config
    ↓ (depends on M1 data structures)
M2: DB Migration & Persistence
    ↓ (depends on M2 database columns)
M3: Phase Handler Extraction
    ↓ (depends on M3 per-attempt population)
M4: Run-Level Aggregation
    ↓ (depends on M4 run-level data)
M5: API Exposure
    ↓ (depends on M5 API contract)
M6: Frontend Display
```

Each milestone must complete **and pass all tests** before the next milestone begins.

---

## Verification Strategy

### Per-Milestone Verification

| Milestone | Auto-Verify (Routine) | Manual Smoke Test |
|-----------|----------------------|-------------------|
| M1 | YAML loads; costs_module imports; tests pass | N/A |
| M2 | Migration applies; round-trip serialization | N/A |
| M3 | Phase handler imports; extraction contract; tests pass | Run a task, check DB `token_usage_by_model` |
| M4 | Aggregation tests pass; legacy fields match | Complete a run, check run totals in DB |
| M5 | API schema imports; response structure; tests pass | `curl` API response, inspect per-model array |
| M6 | TypeScript compiles; component imports; tests pass | Open run detail page, visually verify table |

### End-to-End Test

After M6 completes:
1. Create a new run with 2+ tasks and multiple sub-agents.
2. Verify `GET /api/runs/{id}` includes `token_usage_by_model` array with multiple models.
3. Verify frontend displays per-model cost table.
4. Create an old run (pre-migration) and verify fallback disclaimer is shown.
5. Verify grand total matches sum of per-model costs (accounting for floating-point rounding).

---

## Success Criteria

- ✓ All 19 tasks in 6 steps complete.
- ✓ All existing tests pass (no regressions).
- ✓ New unit and integration tests pass (25+ new test cases covering cost computation, extraction, aggregation, API, UI).
- ✓ Verification routine passes all auto_verify checks.
- ✓ API response includes per-model breakdown with computed cost and embedded rates.
- ✓ Frontend displays cost table for new runs and disclaimer for old runs.
- ✓ Legacy flat fields still populated for backward compatibility.
- ✓ Alembic migration applies cleanly; old runs unaffected.

---

## References

- **Intent**: `docs/per-model-yaml/intent.md`
- **Plan**: `docs/per-model-yaml/plan.md`
- **Step Details**: `docs/per-model-yaml/step-0N-plan.md` (N=1–6)
- **Verification Report**: `docs/per-model-yaml/verification-report.md`
- **Clarifications**: `docs/per-model-yaml/clarifications.md`
