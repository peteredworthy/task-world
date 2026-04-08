# Step 06: Code Locations

## Code Locations

- `ui/src/types/runs.ts` — `ModelTokenUsage` interface lines 40–51: add TypeScript type with all token/cost fields matching API schema
- `ui/src/types/runs.ts` — `RunResponse` interface lines 58–93: add `token_usage_by_model` field
- `ui/src/types/tasks.ts` — `AttemptSchema` interface lines 81–101: add `token_usage_by_model` field
- `ui/src/components/detail/RunDetail.tsx` or similar: add per-model breakdown table component displaying model name, token counts, cost rates, per-model total cost, and grand total
- `ui/src/components/` (new or existing utility file): display logic for "cost unknown" badges (render when all cost rates are zero) and fallback rendering for old runs with legacy fields + disclaimer
