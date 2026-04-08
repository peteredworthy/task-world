# Step 04 Plan Context: M4 - Run-Level Aggregation

## Milestone M4: Run-Level Aggregation

Accumulate per-model usage across all attempts into run-level totals.

**Steps:**
1. Add aggregation logic: iterate all attempts across all tasks/steps, merge `token_usage_by_model` entries by model name (sum tokens, preserve rates). [I-06]
2. Populate `run.token_usage_by_model` after each attempt completes (real-time cost visibility), not just at run/step completion. [I-06, I-19]
3. Continue populating legacy run-level flat fields from the aggregated data. [I-07, I-20]
4. Unit tests for aggregation: multiple attempts with different models, same model across attempts, empty attempts. [I-25]

**Verification:** Run-level `token_usage_by_model` correctly sums across all attempts. Legacy flat fields match. [I-06, I-24]

## Implementation Order

M4 depends on M3. M1-M4 are strictly sequential (each builds on the prior). M5 depends on M4. M6 depends on M5.

## Testing Strategy

| Milestone | Backend Tests | Frontend Tests | Manual Check |
|-----------|--------------|----------------|--------------|
| M4 | Unit: aggregation across attempts/models | N/A | Complete a run, inspect DB |

## Risk Mitigations

- **Backward compatibility**: Legacy flat fields always populated. Frontend falls back gracefully for pre-migration runs.
- **Incremental commits**: Each milestone committed separately. If M6 has issues, M1-M5 are safe and functional.
