"""Unit tests for explicit per-model cost resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import orchestrator.runners.costs as costs_mod
from orchestrator.runners.costs import load_cost_table, resolve_model_costs


@pytest.fixture(autouse=True)
def _reset_cost_table():
    """Reset the module-level cost table before and after every test."""
    costs_mod._cost_table = {}
    yield
    costs_mod._cost_table = {}


@pytest.fixture()
def cost_file(tmp_path: Path) -> Path:
    path = tmp_path / "model_costs.yaml"
    path.write_text(
        yaml.dump(
            {
                "models": {
                    "gpt-5": {
                        "cache_read": 0.25,
                        "cache_creation": 1.25,
                        "input": 2.50,
                        "output": 10.00,
                    },
                    "zero-priced": {},
                }
            }
        )
    )
    load_cost_table(path)
    return path


class TestResolveModelCosts:
    def test_exact_match_returns_rates_and_is_not_missing(self, cost_file: Path) -> None:
        resolved = resolve_model_costs("gpt-5")

        assert resolved.cost_per_m_input == 2.50
        assert resolved.cost_per_m_output == 10.00
        assert resolved.cost_per_m_cache_read == 0.25
        assert resolved.cost_per_m_cache_creation == 1.25
        assert resolved.rate_missing is False

    def test_prefix_match_returns_rates_and_is_not_missing(self, cost_file: Path) -> None:
        resolved = resolve_model_costs("gpt-5-20260719")

        assert resolved.cost_per_m_input == 2.50
        assert resolved.rate_missing is False

    def test_unmatched_model_marks_rate_missing(self, cost_file: Path) -> None:
        resolved = resolve_model_costs("unpriced-model")

        assert resolved.cost_per_m_input == 0.0
        assert resolved.cost_per_m_output == 0.0
        assert resolved.rate_missing is True

    def test_zero_rate_match_is_not_a_missing_rate(self, cost_file: Path) -> None:
        resolved = resolve_model_costs("zero-priced")

        assert resolved.cost_per_m_input == 0.0
        assert resolved.rate_missing is False
