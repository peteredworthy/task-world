# Step Plan: Core Data Model and Cost Config (M1)

## Purpose

Add the `ModelTokenUsage` Pydantic class and cost rate configuration file. This is pure additive infrastructure with no behavior changes -- establishes the data model and cost lookup that all subsequent steps depend on.

## Prerequisites

- None. This is the first step.

## Functional Contract

### Inputs

- `config/model_costs.yaml`: YAML file with per-model cost rates (USD per 1M tokens) for cache_read, cache_creation, input, output. Includes `unknown_model` zero-rate default.
- Model name strings from agent runners (e.g. `"claude-sonnet-4-6"`, `"claude-sonnet-4-6-20250514"`)

### Outputs

- `ModelTokenUsage` Pydantic class in `src/orchestrator/state/models.py` with:
  - `model: str` -- base model name
  - `cache_read_tokens`, `cache_creation_tokens`, `input_tokens`, `output_tokens: int` (default 0)
  - `cost_per_m_cache_read`, `cost_per_m_cache_creation`, `cost_per_m_input`, `cost_per_m_output: float` (default 0.0)
  - `total_cost_usd: float` computed property = sum(tokens * rate) / 1_000_000
- `token_usage_by_model: list[ModelTokenUsage] = []` field added to both `Attempt` and `Run` in `state/models.py`
- `get_model_costs(model_name: str) -> dict[str, float]` function in `src/orchestrator/runners/costs.py` that:
  - Loads rates from `config/model_costs.yaml`
  - Normalizes model names by stripping version suffixes (prefix matching fallback)
  - Returns zero-rate dict for unknown models
- `config/model_costs.yaml` with rates for Sonnet, Haiku, Opus, and unknown_model

### Error Cases

- Missing `config/model_costs.yaml`: raise `FileNotFoundError` at import time (fail fast)
- Malformed YAML: raise parse error at import time
- Unknown model name: return `unknown_model` zero rates (not an error)

## Tasks

1. Create `config/model_costs.yaml` with Sonnet 4-6, Haiku 4-5, Opus 4-6 rates and `unknown_model` zero-rate default.
2. Add `ModelTokenUsage` Pydantic class to `src/orchestrator/state/models.py` with token count fields, cost rate fields, and `total_cost_usd` computed property.
3. Add `token_usage_by_model: list[ModelTokenUsage] = []` field to `Attempt` and `Run` classes in `state/models.py`.
4. Create `src/orchestrator/runners/costs.py` with `get_model_costs()` that loads YAML, normalizes model names via prefix matching, and returns zero rates for unknown models.
5. Write unit tests for `ModelTokenUsage.total_cost_usd` computation and `get_model_costs()` lookup (known models, unknown models, version-suffix normalization).

## Verification Approach

### Auto-Verify

- All existing tests pass (`pytest tests/`)
- New unit tests pass:
  - `ModelTokenUsage.total_cost_usd` returns correct value for various token/rate combinations
  - `get_model_costs("claude-sonnet-4-6")` returns correct Sonnet rates
  - `get_model_costs("claude-sonnet-4-6-20250514")` normalizes to Sonnet rates
  - `get_model_costs("unknown-model-xyz")` returns all-zero rates
- `config/model_costs.yaml` exists and is valid YAML
- TypeScript type check clean, ESLint clean

### Manual Verification

- N/A (no behavior change)

## Context & References

- Architecture: `docs/per-model-yaml/architecture.md` -- ModelTokenUsage class definition, cost config format
- Clarification: model name normalization strips version suffixes, grouping by base name
- Clarification: unknown models get zero rates (displayed with "cost unknown" badge in M6)
- Requirement IDs: I-03, I-04, I-16, I-17, I-19, I-25
