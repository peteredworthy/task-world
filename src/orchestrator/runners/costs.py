"""Canonical model-cost resolution and pure usage pricing.

``get_model_costs`` is a temporary Task 3 compatibility bridge for legacy callers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Cost rates keyed by model name.  Each value is a dict with keys:
# cost_per_m_cache_read, cost_per_m_cache_creation, cost_per_m_input, cost_per_m_output
_cost_table: dict[str, dict[str, float]] = {}

_ZERO_COSTS: dict[str, float] = {
    "cost_per_m_cache_read": 0.0,
    "cost_per_m_cache_creation": 0.0,
    "cost_per_m_input": 0.0,
    "cost_per_m_output": 0.0,
}


class ModelCostResolution(BaseModel):
    """The pricing lookup result for a model at the time it is resolved."""

    cost_per_m_cache_read: float = Field(ge=0)
    cost_per_m_cache_creation: float = Field(ge=0)
    cost_per_m_input: float = Field(ge=0)
    cost_per_m_output: float = Field(ge=0)
    rate_missing: bool


def calculate_model_usage_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int,
    cache_creation_input_tokens: int,
    resolution: ModelCostResolution,
) -> float:
    """Price canonical, cache-inclusive usage from one resolved rate snapshot."""
    uncached_input = input_tokens - cache_read_input_tokens - cache_creation_input_tokens
    return (
        cache_read_input_tokens * resolution.cost_per_m_cache_read
        + cache_creation_input_tokens * resolution.cost_per_m_cache_creation
        + uncached_input * resolution.cost_per_m_input
        + output_tokens * resolution.cost_per_m_output
    ) / 1_000_000


def _find_cost_file() -> Path | None:
    """Locate model_costs.yaml, walking up from this file's directory."""
    # Try project root (3 levels up from src/orchestrator/runners/)
    candidate = Path(__file__).resolve().parent.parent.parent.parent / "model_costs.yaml"
    if candidate.exists():
        return candidate
    # Try CWD
    cwd_candidate = Path.cwd() / "model_costs.yaml"
    if cwd_candidate.exists():
        return cwd_candidate
    return None


def load_cost_table(path: Path | None = None) -> None:
    """Load (or reload) the cost table from a YAML file.

    Called automatically on first access.  Can be called explicitly
    to reload after editing the YAML file.
    """
    global _cost_table  # noqa: PLW0603

    if path is None:
        path = _find_cost_file()
    if path is None:
        logger.warning("model_costs.yaml not found — all costs will be 0")
        return

    raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    models: dict[str, Any] = raw.get("models", {})

    table: dict[str, dict[str, float]] = {}
    for model_name, rates in models.items():
        table[model_name] = {
            "cost_per_m_cache_read": float(rates.get("cache_read", 0)),
            "cost_per_m_cache_creation": float(rates.get("cache_creation", 0)),
            "cost_per_m_input": float(rates.get("input", 0)),
            "cost_per_m_output": float(rates.get("output", 0)),
        }

    _cost_table = table
    logger.debug("Loaded cost rates for %d models from %s", len(table), path)


def resolve_model_costs(model_name: str | None) -> ModelCostResolution:
    """Resolve rates and whether the model lookup itself succeeded.

    A matched entry may intentionally contain zero rates, so ``rate_missing``
    is determined only by matching the model name, never by inspecting rates.
    """
    if not _cost_table:
        load_cost_table()

    if model_name is None:
        return ModelCostResolution(**_ZERO_COSTS, rate_missing=True)

    # Exact match
    if model_name in _cost_table:
        return ModelCostResolution(**_cost_table[model_name], rate_missing=False)

    matches = [
        key
        for key in _cost_table
        if model_name.startswith(f"{key}-") or key.startswith(f"{model_name}-")
    ]
    if matches:
        key = max(matches, key=lambda candidate: (len(candidate), candidate))
        return ModelCostResolution(**_cost_table[key], rate_missing=False)

    return ModelCostResolution(**_ZERO_COSTS, rate_missing=True)


def get_model_costs(model_name: str | None) -> dict[str, float]:
    """Return legacy rate kwargs.

    Transitional bridge for untouched callers; Task 3 must use
    :func:`resolve_model_costs` so it retains ``rate_missing``.
    """
    return resolve_model_costs(model_name).model_dump(exclude={"rate_missing"})
