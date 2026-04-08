# Step 01: Architecture Context

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

Legacy fields (`AttemptMetrics.tokens_cache`, etc.) remain unchanged.

## Cost Rate Configuration

### config/model_costs.yaml

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

Loads `config/model_costs.yaml` at import time. `get_model_costs(model_name: str) -> dict[str, float]` returns rate dict. Model names are normalized by base name via prefix matching (e.g. `claude-sonnet-4-6-20250514` → `claude-sonnet-4-6`). Unknown models return `unknown_model` rates (all zeros).
