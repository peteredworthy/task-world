# Per-Model Token Accounting

## Problem

The UI shows ~27% of actual token cost because `AttemptMetrics.tokens_cache`
only includes parent-agent tokens. Sub-agent tokens (which are the majority of
cost in runs using Explore sub-agents) are invisible. The cost estimate is also
wrong because it applies a single $/M rate to all tokens, when in practice the
parent (Sonnet, $0.30/M cache_read) and sub-agents (Haiku, $0.08/M cache_read)
have very different pricing.

**Observed**: E8 Arm A showed $1.97 in the UI. Actual cost computed manually: $5.24.

## Root cause

`phase_handler.py:198` computes:
```python
tokens_cache = al.total_cache_read_tokens + al.total_cache_creation_tokens
```
This is parent-only. `al.sub_agent_total_*` fields are not included. The run-level
aggregates (`total_tokens_cache` etc.) inherit the same gap.

Even if we added sub-agent tokens, the flat `tokens_cache` field cannot distinguish
Sonnet tokens from Haiku tokens. A single cost rate applied to the sum produces a
wrong number regardless.

## Design

### Core data structure: per-model token breakdown with embedded cost rates

The attempt and run should carry a dict keyed by actual model name, where each
entry has token counts AND the per-token cost rates at the time of execution.
This means:
- No model→cost mapping in the frontend
- No "model class" abstraction that can get out of sync
- New models automatically appear with correct rates
- Historical data preserves the rates that were in effect when the run executed
  (prices change over time; embedding them makes historical cost accurate)

```python
class ModelTokenUsage(BaseModel):
    """Token usage and cost rates for a single model within an attempt."""

    model: str  # e.g. "claude-sonnet-4-6", "claude-haiku-4-5-20251001"

    # Token counts
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    # Cost rates (USD per 1M tokens) — embedded at execution time
    # so historical costs are accurate even after price changes
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

### Where cost rates come from: the agent runner

Each agent runner type knows which models it uses and their costs. The rates
should be defined as configuration, not hardcoded:

```python
# In a new file or in the runner's config:
MODEL_COSTS: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "cache_read": 0.30,
        "cache_creation": 3.75,
        "input": 3.00,
        "output": 15.00,
    },
    "claude-haiku-4-5-20251001": {
        "cache_read": 0.08,
        "cache_creation": 1.00,
        "input": 0.80,
        "output": 4.00,
    },
    # ... other models
}
```

This config could live in:
- A `model_costs.yaml` file in the project root (easiest to update)
- The `GlobalConfig` or agent config (ties costs to the runtime config)
- A dedicated `CostConfig` loaded at startup

The runner stamps the rates onto each `ModelTokenUsage` entry at execution time
by looking up the model name. If a model isn't in the cost table, rates default
to 0 and the frontend shows "cost unknown" rather than a wrong number.

### Data flow

```
Agent runner executes
    → ActionLog has: agent_model, sub_agents[].model, per-turn usage
    → Runner looks up cost rates for each model
    → Produces: list[ModelTokenUsage] with tokens + rates embedded

Phase handler stores on attempt
    → New field: Attempt.token_usage_by_model: list[ModelTokenUsage]
    → Replaces the flat AttemptMetrics.tokens_read/write/cache fields
      (or supplements them — keep the old fields for backward compat
      and populate from the sum of all models)

Run-level aggregation
    → Run.token_usage_by_model: list[ModelTokenUsage]
    → Accumulated from all attempts across all tasks/steps
    → Each model's tokens are summed; rates are preserved (they're the
      same for a given model within a run, but could differ across runs
      if prices change)

API response
    → RunResponse includes token_usage_by_model as a JSON array
    → Each entry: {model, cache_read_tokens, ..., cost_per_m_cache_read, ..., total_cost_usd}

Frontend
    → Reads the array, displays per-model breakdown
    → Computes total cost by summing total_cost_usd across models
    → No model→cost mapping needed in frontend code
```

### Schema changes

**Pydantic models** (`state/models.py`):
- Add `ModelTokenUsage` class (above)
- Add `token_usage_by_model: list[ModelTokenUsage] = []` to `Attempt`
- Add `token_usage_by_model: list[ModelTokenUsage] = []` to `Run`
- Keep existing flat fields (`AttemptMetrics.tokens_cache`, `Run.total_tokens_cache`)
  for backward compatibility — populate them as the sum across all models

**DB** (`db/orm/models.py`):
- Add `token_usage_by_model` JSON column to `attempts` table
- Add `token_usage_by_model` JSON column to `runs` table
- Alembic migration to add both columns

**API schemas** (`api/schemas/`):
- Add `ModelTokenUsageSchema` to the response schemas
- Include in `AttemptSchema` and `RunResponse`
- The frontend receives the full breakdown

### Where to build the ModelTokenUsage list

In `phase_handler.py` where metrics are currently extracted (lines ~190-201):

```python
# Current (broken):
tokens_cache = al.total_cache_read_tokens + al.total_cache_creation_tokens

# New:
from orchestrator.runners.costs import get_model_costs

usage_by_model: list[ModelTokenUsage] = []

# Parent model
parent_costs = get_model_costs(al.agent_model)
usage_by_model.append(ModelTokenUsage(
    model=al.agent_model or "unknown",
    cache_read_tokens=al.total_cache_read_tokens,
    cache_creation_tokens=al.total_cache_creation_tokens,
    input_tokens=al.total_input_tokens,
    output_tokens=al.total_output_tokens,
    **parent_costs,
))

# Sub-agent models (group by model name and sum)
sa_by_model: dict[str, ModelTokenUsage] = {}
for sa in al.sub_agents:
    model = sa.model or "unknown"
    if model not in sa_by_model:
        sa_costs = get_model_costs(model)
        sa_by_model[model] = ModelTokenUsage(model=model, **sa_costs)
    entry = sa_by_model[model]
    entry.cache_read_tokens += sa.total_cache_read_tokens
    entry.cache_creation_tokens += sa.total_cache_creation_tokens
    entry.input_tokens += sa.total_input_tokens
    entry.output_tokens += sa.total_output_tokens
usage_by_model.extend(sa_by_model.values())

# Store on attempt
attempt.token_usage_by_model = usage_by_model

# Also populate legacy flat fields for backward compat
metrics = ExecutionMetrics(
    tokens_read=sum(u.input_tokens for u in usage_by_model),
    tokens_write=sum(u.output_tokens for u in usage_by_model),
    tokens_cache=sum(u.cache_read_tokens + u.cache_creation_tokens for u in usage_by_model),
    ...
)
```

### Run-level aggregation

When the run completes (or on each step completion), aggregate:

```python
run_usage: dict[str, ModelTokenUsage] = {}
for step in run.steps:
    for task in step.tasks:
        for attempt in task.attempts:
            for u in attempt.token_usage_by_model:
                if u.model not in run_usage:
                    run_usage[u.model] = ModelTokenUsage(
                        model=u.model,
                        cost_per_m_cache_read=u.cost_per_m_cache_read,
                        cost_per_m_cache_creation=u.cost_per_m_cache_creation,
                        cost_per_m_input=u.cost_per_m_input,
                        cost_per_m_output=u.cost_per_m_output,
                    )
                entry = run_usage[u.model]
                entry.cache_read_tokens += u.cache_read_tokens
                entry.cache_creation_tokens += u.cache_creation_tokens
                entry.input_tokens += u.input_tokens
                entry.output_tokens += u.output_tokens
run.token_usage_by_model = list(run_usage.values())

# Legacy flat fields
run.total_tokens_cache = sum(u.cache_read_tokens + u.cache_creation_tokens
                             for u in run.token_usage_by_model)
run.total_tokens_read = sum(u.input_tokens for u in run.token_usage_by_model)
run.total_tokens_write = sum(u.output_tokens for u in run.token_usage_by_model)
```

### Frontend display

The API response gives the frontend everything it needs:

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
  ],
  "total_cost_usd": 5.11,
  "total_tokens_cache": 14593751
}
```

The frontend renders a per-model breakdown table. No model-name-to-cost mapping
needed in JS. Total cost is just `sum(entry.total_cost_usd)`.

### Cost config file

A simple YAML file at the project root, loaded at startup:

```yaml
# model_costs.yaml
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

# Default for unknown models — cost_per_m fields will be 0,
# frontend shows "cost unknown" badge
unknown_model:
  cache_read: 0
  cache_creation: 0
  input: 0
  output: 0
```

### Migration path

1. Add the Alembic migration for the new JSON columns
2. Existing runs keep their old flat fields (no backfill needed — the new fields
   default to empty list)
3. New runs get both: `token_usage_by_model` (accurate per-model) AND the legacy
   flat fields (populated as the sum, for backward compat with any code that reads them)
4. Frontend checks for `token_usage_by_model` presence: if non-empty, use it for
   display; if empty (old run), fall back to the legacy flat fields with a
   "cost estimate, sub-agents not included" disclaimer

### Files to change

| File | Change |
|------|--------|
| `state/models.py` | Add `ModelTokenUsage` class; add field to `Attempt` and `Run` |
| `db/orm/models.py` | Add JSON columns to ORM |
| `db/migrations/versions/` | New Alembic migration |
| `db/access/repositories.py` | Serialize/deserialize the new fields |
| `runners/execution/phase_handler.py` | Build `ModelTokenUsage` list from `ActionLog` |
| `runners/costs.py` (new) | Load `model_costs.yaml`, provide `get_model_costs(model_name)` |
| `model_costs.yaml` (new) | Cost rates per model |
| `api/schemas/runs.py` | Add `ModelTokenUsageSchema` to response |
| `api/schemas/tasks.py` | Add to attempt schema |
| `api/routers/runs.py` | Include in response builder |
| `ui/src/types/runs.ts` | Add TypeScript types |
| `ui/src/components/RunDetail.tsx` | Display per-model breakdown |

### Effort estimate

Backend: ~2 days (model, migration, phase_handler, API, cost config)
Frontend: ~1 day (types, display component)
Tests: ~1 day (unit tests for cost computation, integration test for API response)
Total: ~4 days

### What this fixes beyond the immediate bug

- Accurate cost display for all runs (including historical ones if backfilled)
- Per-model breakdown visible in the UI (user can see "70% of cost is Haiku sub-agents")
- Cost rates travel with the data (no frontend constants to update when prices change)
- New models automatically work (unknown models show $0 with a badge, not a crash)
- The E8 analysis we did manually (Sonnet parent vs Haiku SA cost breakdown) becomes
  a standard UI feature
