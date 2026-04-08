# Step 06 Plan Context: M6 - Frontend Display

## Milestone M6: Frontend Display

Render the per-model breakdown in the UI.

**Steps:**
1. Add TypeScript types for `ModelTokenUsage` in `ui/src/types/runs.ts`. [I-10]
2. Create per-model cost breakdown table component for the run detail page. Display model name, token counts, cost rates, and per-model total cost. [I-10, I-23]
3. Compute and display grand total cost by summing `total_cost_usd` across models. [I-10]
4. Add fallback: when `token_usage_by_model` is empty (old run), show legacy flat fields with "cost estimate, sub-agents not included" disclaimer badge. Show "cost unknown" badge next to $0.00 rows for unknown/unrecognized models. [I-11, I-23]
5. Frontend tests for the breakdown component: with data, empty data, fallback rendering. [I-25]

**Verification:** Run detail page shows per-model cost table for new runs and disclaimer for old runs. All frontend tests pass. [I-23, I-24]

## Implementation Order

M6 depends on M5. M1-M4 are strictly sequential (each builds on the prior). M5 depends on M4. M6 depends on M5.

## Testing Strategy

| Milestone | Backend Tests | Frontend Tests | Manual Check |
|-----------|--------------|----------------|--------------|
| M6 | N/A | Component: table rendering, fallback, totals | Visual check |

## Risk Mitigations

- **Backward compatibility**: Legacy flat fields always populated. Frontend falls back gracefully for pre-migration runs.
- **Incremental commits**: Each milestone committed separately. If M6 has issues, M1-M5 are safe and functional.
