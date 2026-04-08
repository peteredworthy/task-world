# Step 05 Plan Context: M5 - API Exposure

## Milestone M5: API Exposure

Expose per-model data through the REST API.

**Steps:**
1. Add `ModelTokenUsageSchema` to API schemas (`api/schemas/`). [I-09, I-22]
2. Add `token_usage_by_model` field to `AttemptSchema` and `RunResponse`. [I-09, I-22]
3. Update response builders in `api/routers/runs.py` to include the new field. Replace `estimated_cost_usd` with accurate per-model sum (no more flat gpt-4o estimate). [I-09]
4. Integration test: create a run, verify API response includes `token_usage_by_model` with expected structure. [I-25]

**Verification:** `GET /api/runs/{id}` returns per-model token data. Existing API fields unchanged. [I-22, I-24]

## Implementation Order

M5 depends on M4. M1-M4 are strictly sequential (each builds on the prior). M5 depends on M4. M6 depends on M5.

## Testing Strategy

| Milestone | Backend Tests | Frontend Tests | Manual Check |
|-----------|--------------|----------------|--------------|
| M5 | Integration: API response structure, backward compat | N/A | curl API |

## Risk Mitigations

- **Backward compatibility**: Legacy flat fields always populated. Frontend falls back gracefully for pre-migration runs.
- **Incremental commits**: Each milestone committed separately. If M6 has issues, M1-M5 are safe and functional.
