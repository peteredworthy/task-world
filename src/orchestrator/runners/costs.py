"""Per-model cost rate lookup.

Loads ``model_costs.yaml`` from the project root and provides
``get_model_costs(model_name)`` which returns the cost-rate kwargs
suitable for constructing a ``ModelTokenUsage`` instance.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

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


def get_model_costs(model_name: str | None) -> dict[str, float]:
    """Return cost-rate kwargs for a model name.

    Returns zero costs for unknown models (frontend shows "cost unknown").
    Tries prefix matching for versioned model names.
    """
    if not _cost_table:
        load_cost_table()

    if model_name is None:
        return dict(_ZERO_COSTS)

    # Exact match
    if model_name in _cost_table:
        return dict(_cost_table[model_name])

    # Prefix match (e.g. "claude-sonnet-4-6-20250514" → "claude-sonnet-4-6")
    for key in _cost_table:
        if model_name.startswith(key):
            return dict(_cost_table[key])

    return dict(_ZERO_COSTS)
