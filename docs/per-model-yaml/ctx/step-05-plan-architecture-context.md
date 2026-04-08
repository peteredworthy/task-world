# Step 05: Architecture Context

## API Changes

### New Schema

```python
class ModelTokenUsageSchema(BaseModel):
    model: str
    cache_read_tokens: int
    cache_creation_tokens: int
    input_tokens: int
    output_tokens: int
    cost_per_m_cache_read: float
    cost_per_m_cache_creation: float
    cost_per_m_input: float
    cost_per_m_output: float
    total_cost_usd: float
```

### Modified Responses

| Schema | New Field |
|--------|-----------|
| `AttemptSchema` | `token_usage_by_model: list[ModelTokenUsageSchema] = []` |
| `RunResponse` | `token_usage_by_model: list[ModelTokenUsageSchema] = []` |

`estimated_cost_usd` is replaced with the accurate per-model sum.

### Example API Response Fragment

```json
{
  "token_usage_by_model": [
    {
      "model": "claude-sonnet-4-6",
      "cache_read_tokens": 3567166,
      "cache_creation_tokens": 395302,
      "input_tokens": 71,
      "output_tokens": 51999,
      "cost_per_m_cache_read": 0.30,
      "cost_per_m_cache_creation": 3.75,
      "cost_per_m_input": 3.00,
      "cost_per_m_output": 15.00,
      "total_cost_usd": 2.97
    }
  ]
}
```

### Error Cases

Old runs with empty `token_usage_by_model`: returns `[]` (empty array), no error. `estimated_cost_usd` for old runs: returns 0.0.
