"""Unit tests for orchestrator.runners.costs — per-model cost rate lookup."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import orchestrator.runners.costs as costs_mod
from orchestrator.runners.costs import get_model_costs, load_cost_table


@pytest.fixture(autouse=True)
def _reset_cost_table():
    """Reset the module-level cost table before and after every test."""
    costs_mod._cost_table = {}
    yield
    costs_mod._cost_table = {}


# ---------------------------------------------------------------------------
# load_cost_table
# ---------------------------------------------------------------------------


class TestLoadCostTable:
    def test_loads_known_model_from_yaml(self, tmp_path: Path) -> None:
        cost_file = tmp_path / "model_costs.yaml"
        cost_file.write_text(
            yaml.dump(
                {
                    "models": {
                        "claude-sonnet-4-6": {
                            "cache_read": 0.30,
                            "cache_creation": 3.75,
                            "input": 3.00,
                            "output": 15.00,
                        }
                    }
                }
            )
        )
        load_cost_table(cost_file)
        assert "claude-sonnet-4-6" in costs_mod._cost_table
        entry = costs_mod._cost_table["claude-sonnet-4-6"]
        assert entry["cost_per_m_input"] == 3.00
        assert entry["cost_per_m_output"] == 15.00
        assert entry["cost_per_m_cache_read"] == 0.30
        assert entry["cost_per_m_cache_creation"] == 3.75

    def test_loads_multiple_models(self, tmp_path: Path) -> None:
        cost_file = tmp_path / "model_costs.yaml"
        cost_file.write_text(
            yaml.dump(
                {
                    "models": {
                        "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
                        "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
                    }
                }
            )
        )
        load_cost_table(cost_file)
        assert len(costs_mod._cost_table) == 2
        assert "claude-haiku-4-5" in costs_mod._cost_table

    def test_empty_models_section_leaves_empty_table(self, tmp_path: Path) -> None:
        cost_file = tmp_path / "model_costs.yaml"
        cost_file.write_text(yaml.dump({"models": {}}))
        load_cost_table(cost_file)
        assert costs_mod._cost_table == {}

    def test_missing_rate_fields_default_to_zero(self, tmp_path: Path) -> None:
        cost_file = tmp_path / "model_costs.yaml"
        cost_file.write_text(yaml.dump({"models": {"my-model": {"input": 2.50}}}))
        load_cost_table(cost_file)
        entry = costs_mod._cost_table["my-model"]
        assert entry["cost_per_m_output"] == 0.0
        assert entry["cost_per_m_cache_read"] == 0.0
        assert entry["cost_per_m_cache_creation"] == 0.0
        assert entry["cost_per_m_input"] == 2.50

    def test_reload_replaces_previous_table(self, tmp_path: Path) -> None:
        first = tmp_path / "first.yaml"
        first.write_text(yaml.dump({"models": {"model-a": {"input": 1.00}}}))
        load_cost_table(first)
        assert "model-a" in costs_mod._cost_table

        second = tmp_path / "second.yaml"
        second.write_text(yaml.dump({"models": {"model-b": {"input": 2.00}}}))
        load_cost_table(second)
        assert "model-b" in costs_mod._cost_table
        assert "model-a" not in costs_mod._cost_table


# ---------------------------------------------------------------------------
# get_model_costs
# ---------------------------------------------------------------------------


class TestGetModelCosts:
    def _load_fixture(self, tmp_path: Path) -> None:
        cost_file = tmp_path / "model_costs.yaml"
        cost_file.write_text(
            yaml.dump(
                {
                    "models": {
                        "claude-sonnet-4-6": {
                            "cache_read": 0.30,
                            "cache_creation": 3.75,
                            "input": 3.00,
                            "output": 15.00,
                        },
                        "claude-haiku-4-5": {
                            "cache_read": 0.08,
                            "cache_creation": 0.30,
                            "input": 0.80,
                            "output": 4.00,
                        },
                    }
                }
            )
        )
        load_cost_table(cost_file)

    def test_exact_match_returns_correct_rates(self, tmp_path: Path) -> None:
        self._load_fixture(tmp_path)
        costs = get_model_costs("claude-sonnet-4-6")
        assert costs["cost_per_m_input"] == 3.00
        assert costs["cost_per_m_output"] == 15.00
        assert costs["cost_per_m_cache_read"] == 0.30
        assert costs["cost_per_m_cache_creation"] == 3.75

    def test_prefix_match_versioned_name(self, tmp_path: Path) -> None:
        self._load_fixture(tmp_path)
        # Versioned model name with date suffix should resolve via prefix match
        costs = get_model_costs("claude-sonnet-4-6-20250514")
        assert costs["cost_per_m_input"] == 3.00
        assert costs["cost_per_m_output"] == 15.00

    def test_prefix_match_haiku(self, tmp_path: Path) -> None:
        self._load_fixture(tmp_path)
        costs = get_model_costs("claude-haiku-4-5-20251001")
        assert costs["cost_per_m_input"] == 0.80
        assert costs["cost_per_m_output"] == 4.00

    def test_unknown_model_returns_zero_costs(self, tmp_path: Path) -> None:
        self._load_fixture(tmp_path)
        costs = get_model_costs("gpt-totally-unknown")
        assert costs["cost_per_m_input"] == 0.0
        assert costs["cost_per_m_output"] == 0.0
        assert costs["cost_per_m_cache_read"] == 0.0
        assert costs["cost_per_m_cache_creation"] == 0.0

    def test_none_model_returns_zero_costs(self, tmp_path: Path) -> None:
        self._load_fixture(tmp_path)
        costs = get_model_costs(None)
        assert costs["cost_per_m_input"] == 0.0
        assert costs["cost_per_m_output"] == 0.0
        assert costs["cost_per_m_cache_read"] == 0.0
        assert costs["cost_per_m_cache_creation"] == 0.0

    def test_returns_copy_not_reference(self, tmp_path: Path) -> None:
        """Modifying the returned dict must not affect the internal table."""
        self._load_fixture(tmp_path)
        costs = get_model_costs("claude-sonnet-4-6")
        costs["cost_per_m_input"] = 999.0
        costs2 = get_model_costs("claude-sonnet-4-6")
        assert costs2["cost_per_m_input"] == 3.00

    def test_zero_costs_for_none_when_table_empty(self) -> None:
        """When table is empty and no cost file exists, None model still gives zeros."""
        costs = get_model_costs(None)
        assert costs["cost_per_m_input"] == 0.0
