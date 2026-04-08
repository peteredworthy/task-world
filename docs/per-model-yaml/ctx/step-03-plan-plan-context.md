# Step 03 Plan Context: M3 - Phase Handler Token Extraction

## Milestone M3: Phase Handler Extraction

Wire up the actual token extraction from `ActionLog` data in the phase handler.

**Steps:**
1. Modify `phase_handler.py` to build `list[ModelTokenUsage]` from `ActionLog` parent-agent fields using `get_model_costs()` for rate lookup. [I-05, I-18]
2. Add sub-agent token extraction: iterate `ActionLog.sub_agents`, group by model name, sum token counts per model, stamp cost rates. [I-05, I-18]
3. Store result on `attempt.token_usage_by_model`. [I-19]
4. Continue populating legacy flat fields (`tokens_cache`, `tokens_read`, `tokens_write`) as the sum across all models. [I-07, I-20]
5. Unit tests for extraction logic with mock ActionLog data covering: parent-only, parent+sub-agents, unknown model, multiple sub-agents of same model. [I-25]

**Verification:** After a run completes, `attempt.token_usage_by_model` is populated with correct per-model breakdown. Legacy fields still correct. [I-18, I-20, I-24]

## Implementation Order

M3 depends on M1 and M2. M1-M4 are strictly sequential (each builds on the prior). M5 depends on M4. M6 depends on M5.

## Testing Strategy

| Milestone | Backend Tests | Frontend Tests | Manual Check |
|-----------|--------------|----------------|--------------|
| M3 | Unit: extraction from ActionLog (parent, sub-agents, unknowns) | N/A | Run a task, inspect DB |

## Risk Mitigations

- **ActionLog structure variance**: Inspect real ActionLog data before coding M3. Handle missing sub-agent fields with zero defaults.
- **Backward compatibility**: Legacy flat fields always populated. Frontend falls back gracefully for pre-migration runs.
- **Incremental commits**: Each milestone committed separately. If M6 has issues, M1-M5 are safe and functional.
