# Architecture: Per-Model Token Accounting

## Data Flow

```
Agent Runner executes task
    │
    ▼
ActionLog populated with:
  ├── parent: agent_model, total_cache_read_tokens, total_input_tokens, ...
  └── sub_agents[]: model, total_cache_read_tokens, total_input_tokens, ...
    │
    ▼
phase_handler.py (M3)
  ├── get_model_costs(agent_model) → cost rates
  ├── Build ModelTokenUsage for parent model
  ├── Group sub_agents by model, sum tokens per group
  ├── Build ModelTokenUsage for each sub-agent model
  └── Store list on attempt.token_usage_by_model
    │
    ▼
Run aggregation (M4)
  ├── Iterate all attempts across tasks/steps
  ├── Merge ModelTokenUsage entries by model name (sum tokens, keep rates)
  └── Store on run.token_usage_by_model
    │
    ▼
API response (M5)
  ├── ModelTokenUsageSchema in AttemptSchema and RunResponse
  └── JSON array with per-model tokens, rates, and total_cost_usd
    │
    ▼
Frontend (M6)
  ├── Per-model breakdown table on RunDetail page
  ├── Grand total = sum(entry.total_cost_usd)
  └── Fallback for old runs: legacy fields + disclaimer
```

## New Data Model

### ModelTokenUsage (state/models.py)

```python
class ModelTokenUsage(BaseModel):
    model: str                          # e.g. "claude-sonnet-4-6"

    # Token counts
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    # Cost rates (USD per 1M tokens) — embedded at execution time
    cost_per_m_cache_read: float = 0.0
    cost_per_m_cache_creation: float = 0.0
    cost_per_m_input: float = 0.0
    cost_per_m_output: float = 0.0

    @property
    def total_cost_usd(self) -> float:
        return (
            self.cache_read_tokens * self.cost_per_m_cache_read
            + self.cache_creation_tokens * self.cost_per_m_cache_creation
            + self.input_tokens * self.cost_per_m_input
            + self.output_tokens * self.cost_per_m_output
        ) / 1_000_000
```

### Fields on Existing Models

```
Attempt (state/models.py)
└── token_usage_by_model: list[ModelTokenUsage] = []

Run (state/models.py)
└── token_usage_by_model: list[ModelTokenUsage] = []
```

Legacy fields (`AttemptMetrics.tokens_cache`, `Run.total_tokens_cache`, etc.) remain and are populated as the sum across all models.

## Cost Rate Configuration

### model_costs.yaml (project root)

```yaml
models:
  claude-sonnet-4-6:
    cache_read: 0.30
    cache_creation: 3.75
    input: 3.00
    output: 15.00
  claude-haiku-4-5-20251001:
    cache_read: 0.08
    cache_creation: 1.00
    input: 0.80
    output: 4.00
  claude-opus-4-6:
    cache_read: 0.75
    cache_creation: 9.375
    input: 7.50
    output: 37.50

unknown_model:
  cache_read: 0
  cache_creation: 0
  input: 0
  output: 0
```

### runners/costs.py

- Loads `model_costs.yaml` at import time
- `get_model_costs(model_name: str) -> dict[str, float]` returns rate dict
- Unknown models return `unknown_model` rates (all zeros)
- Rates are stamped onto `ModelTokenUsage` at execution time, not looked up later

## DB Schema Changes

### Alembic Migration

Add two JSON columns:

```python
# attempts table
op.add_column('attempts', sa.Column('token_usage_by_model', sa.JSON(), server_default='[]'))

# runs table
op.add_column('runs', sa.Column('token_usage_by_model', sa.JSON(), server_default='[]'))
```

No backfill needed. Old rows get empty arrays. New runs populate both the new JSON columns and the legacy flat fields.

### ORM Changes (db/orm/models.py)

```python
class AttemptModel(Base):
    # ... existing columns ...
    token_usage_by_model = Column(JSON, default=list)

class RunModel(Base):
    # ... existing columns ...
    token_usage_by_model = Column(JSON, default=list)
```

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

Existing fields (`total_tokens_cache`, `estimated_cost_usd`, etc.) remain unchanged.

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
    },
    {
      "model": "claude-haiku-4-5-20251001",
      "cache_read_tokens": 9487639,
      "cache_creation_tokens": 1143644,
      "input_tokens": 4790,
      "output_tokens": 47914,
      "cost_per_m_cache_read": 0.08,
      "cost_per_m_cache_creation": 1.00,
      "cost_per_m_input": 0.80,
      "cost_per_m_output": 4.00,
      "total_cost_usd": 2.14
    }
  ]
}
```

## Files to Change

| File | Change | Milestone |
|------|--------|-----------|
| `src/orchestrator/state/models.py` | Add `ModelTokenUsage` class; add field to `Attempt` and `Run` | M1 |
| `model_costs.yaml` (new) | Cost rates per model | M1 |
| `src/orchestrator/runners/costs.py` (new) | YAML loader + `get_model_costs()` | M1 |
| `src/orchestrator/db/orm/models.py` | Add JSON columns to ORM | M2 |
| `src/orchestrator/db/migrations/versions/` | New Alembic migration | M2 |
| `src/orchestrator/db/access/repositories.py` | Serialize/deserialize new fields | M2 |
| `src/orchestrator/runners/execution/phase_handler.py` | Build `ModelTokenUsage` list from ActionLog | M3 |
| `src/orchestrator/api/schemas/runs.py` | Add `ModelTokenUsageSchema` to responses | M5 |
| `src/orchestrator/api/schemas/tasks.py` | Add to `AttemptSchema` | M5 |
| `src/orchestrator/api/routers/runs.py` | Include in response builder | M5 |
| `ui/src/types/runs.ts` | Add TypeScript types | M6 |
| `ui/src/components/RunDetail.tsx` | Per-model breakdown table | M6 |

## Integration Points

### Phase Handler (phase_handler.py ~line 190)

Current code extracts flat token counts:
```python
tokens_cache = al.total_cache_read_tokens + al.total_cache_creation_tokens
```

New code builds per-model breakdown from both parent and `al.sub_agents`, then derives the flat fields as sums. This is the critical integration point where cost rates get stamped.

### Run Completion

When a run completes (or a step completes), the aggregation logic iterates all attempts and merges their `token_usage_by_model` lists by model name. This is additive -- no existing completion logic changes.

### Frontend RunDetail

The per-model table is a new section added below existing run metrics. It reads `token_usage_by_model` from the API response. When the array is empty (old runs), it renders existing flat metrics with a disclaimer instead.

## Testing Strategy

### Unit Tests
- `ModelTokenUsage.total_cost_usd` computation with various token/rate combinations
- `get_model_costs()` for known models, unknown models, edge cases
- Phase handler extraction with mock `ActionLog` (parent-only, parent+sub-agents, multiple same-model sub-agents, unknown model)
- Run-level aggregation across multiple attempts and models

### Integration Tests
- Alembic migration applies and rolls back cleanly
- Round-trip: create attempt with `token_usage_by_model`, persist, read back, verify
- API response includes `token_usage_by_model` with correct structure
- Backward compat: old run (empty list) returns without error

### Frontend Tests
- Breakdown table renders correct rows for multi-model data
- Total cost computed correctly
- Fallback renders disclaimer when `token_usage_by_model` is empty
- Component handles single-model and many-model cases
