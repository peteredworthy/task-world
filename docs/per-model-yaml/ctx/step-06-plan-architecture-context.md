# Step 06: Architecture Context

## Frontend Display

### Data Model

TypeScript `ModelTokenUsage` interface in `ui/src/types/runs.ts`:

```typescript
interface ModelTokenUsage {
  model: string
  cache_read_tokens: number
  cache_creation_tokens: number
  input_tokens: number
  output_tokens: number
  cost_per_m_cache_read: number
  cost_per_m_cache_creation: number
  cost_per_m_input: number
  cost_per_m_output: number
  total_cost_usd: number
}
```

Updated `RunResponse` interface includes `token_usage_by_model: ModelTokenUsage[]`.

### Per-Model Breakdown Table

Rendered on RunDetail page displaying:
- Model name
- Token counts (cache read, cache creation, input, output)
- Cost rates (per 1M tokens)
- Per-model total cost USD
- Grand total cost row = `sum(entry.total_cost_usd)`

### Special Cases

**"Cost Unknown" Badge**: Render for rows where all cost rates are zero (unknown/unrecognized models).

**Fallback for Old Runs**: When `token_usage_by_model` is empty, show legacy flat fields with "cost estimate, sub-agents not included" disclaimer badge.

### Error Handling

- `token_usage_by_model` is `undefined` or `null`: treat as empty array, show fallback
- `token_usage_by_model` is empty array `[]`: show fallback with legacy fields
- All models are unknown: show table with "cost unknown" badges on every row
