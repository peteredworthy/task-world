# Step 01 Plan Context: M1 - Core Data Model and Cost Config

## Milestone M1: Core Data Model and Cost Config

Add the `ModelTokenUsage` class and cost rate configuration. No behavior changes yet -- this is pure additive infrastructure.

**Steps:**
1. Add `ModelTokenUsage` Pydantic class to `state/models.py` with token count fields, cost rate fields, and `total_cost_usd` computed property. [I-03, I-16]
2. Create `config/model_costs.yaml` with Sonnet, Haiku, and Opus rates plus `unknown_model` zero-rate default. [I-04, I-17]
3. Create `runners/costs.py` with `get_model_costs(model_name)` that loads rates from YAML, normalizes model names by base name (stripping version suffixes), and returns zero-rate dict for unknown models. [I-04, I-17]
4. Add `token_usage_by_model: list[ModelTokenUsage] = []` field to `Attempt` and `Run` in `state/models.py`. [I-03, I-19]
5. Unit tests for `ModelTokenUsage.total_cost_usd` computation and `get_model_costs()` lookup (including unknown model fallback). [I-25]

**Verification:** All existing tests pass. New unit tests pass. No behavior change to running system. [I-24]

## Implementation Order

Each milestone ends with a working system where runs can still be created and executed.

M1 (data model + config) is the first step. M1-M4 are strictly sequential (each builds on the prior). M5 depends on M4. M6 depends on M5.

## Testing Strategy

| Milestone | Backend Tests | Frontend Tests | Manual Check |
|-----------|--------------|----------------|--------------|
| M1 | Unit: cost computation, YAML loading, unknown model fallback | N/A | N/A |

## Risk Mitigations

- **ActionLog structure variance**: Inspect real ActionLog data before coding M3. Handle missing sub-agent fields with zero defaults.
- **Migration safety**: Test migration on a copy of production DB before applying. Columns default to empty JSON array so existing rows are unaffected.
- **Backward compatibility**: Legacy flat fields always populated. Frontend falls back gracefully for pre-migration runs.
- **Incremental commits**: Each milestone committed separately. If M6 has issues, M1-M5 are safe and functional.
