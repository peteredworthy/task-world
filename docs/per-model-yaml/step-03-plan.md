# Step Plan: Phase Handler Token Extraction (M3)

## Purpose

Wire up actual per-model token extraction from `ActionLog` data in the phase handler. After this step, when an attempt completes, its `token_usage_by_model` is populated with a per-model breakdown of token usage including cost rates.

## Prerequisites

- Step 01 complete: `ModelTokenUsage` class and `get_model_costs()` available
- Step 02 complete: `token_usage_by_model` persisted to DB

## Functional Contract

### Inputs

- `ActionLog` object from agent execution containing:
  - Parent agent fields: `agent_model`, `total_cache_read_tokens`, `total_cache_creation_tokens`, `total_input_tokens`, `total_output_tokens`
  - `sub_agents` list: each with `model`, `total_cache_read_tokens`, `total_cache_creation_tokens`, `total_input_tokens`, `total_output_tokens`
- `get_model_costs(model_name)` from `runners/costs.py`

### Outputs

- `attempt.token_usage_by_model`: populated `list[ModelTokenUsage]` with one entry per unique model (parent + sub-agents grouped by base model name), each with:
  - Summed token counts for that model
  - Cost rates stamped from `get_model_costs()`
- Legacy flat fields (`tokens_cache`, `tokens_read`, `tokens_write`) still populated as the sum across all models (backward compatibility)

### Error Cases

- `ActionLog` with no `sub_agents` field or empty list: only parent model entry produced
- `ActionLog` with missing/null model name: use `"unknown"` as model, gets zero rates
- `ActionLog` with missing token fields: default to 0

## Tasks

1. Inspect real `ActionLog` structure in `phase_handler.py` to understand current token extraction code (~line 190) and available fields.
2. Modify `phase_handler.py` to build `list[ModelTokenUsage]` from `ActionLog`:
   - Create entry for parent agent model using `get_model_costs()` for rates
   - Iterate `sub_agents`, group by normalized model name, sum token counts per group
   - Create `ModelTokenUsage` entry for each sub-agent model group
3. Store result on `attempt.token_usage_by_model`.
4. Continue populating legacy flat fields (`tokens_cache`, `tokens_read`, `tokens_write`) as the sum across all models.
5. Write unit tests with mock `ActionLog` data covering:
   - Parent-only (no sub-agents)
   - Parent + sub-agents with different models
   - Multiple sub-agents of same model (should merge)
   - Unknown model (gets zero rates)

## Verification Approach

### Auto-Verify

- All existing tests pass
- New unit tests pass for all extraction scenarios
- Legacy flat fields match sum of per-model token counts

### Manual Verification

- Run a task through the system, inspect DB to verify `token_usage_by_model` is populated on the attempt
- Compare legacy flat fields with sum of per-model values

## Context & References

- Architecture: `docs/per-model-yaml/architecture.md` -- Phase Handler integration point section
- Key integration point: `phase_handler.py` ~line 190 where flat token counts are currently extracted
- Clarification: model name normalization groups by base name (e.g. all sonnet-4-6 variants together)
- Requirement IDs: I-05, I-07, I-18, I-19, I-20, I-25
