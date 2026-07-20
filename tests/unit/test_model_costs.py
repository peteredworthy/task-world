"""Unit tests for explicit, deterministic per-model cost resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from orchestrator.config.enums import SELECTABLE_AGENT_RUNNER_TYPES
from orchestrator.runners import (
    ModelCostResolution,
    get_builtin_config_schema,
    load_cost_table,
    resolve_model_costs,
)


@pytest.fixture(autouse=True)
def _reset_cost_table():
    from orchestrator.runners.costs import _cost_table

    _cost_table.clear()
    yield
    from orchestrator.runners.costs import _cost_table

    _cost_table.clear()


def _load(tmp_path: Path, models: dict[str, dict[str, float]]) -> None:
    path = tmp_path / "model_costs.yaml"
    path.write_text(yaml.dump({"models": models}))
    load_cost_table(path)


class TestResolveModelCosts:
    def test_runner_defaults_have_explicit_cost_classification(self) -> None:
        """Reconcile built-in provider defaults from runner config schemas."""
        load_cost_table(Path("model_costs.yaml"))

        default_models = {
            runner_type: next(
                (
                    field.default
                    for field in get_builtin_config_schema(runner_type)
                    if field.name == "model" and isinstance(field.default, str)
                ),
                None,
            )
            for runner_type in SELECTABLE_AGENT_RUNNER_TYPES
        }

        assert set(default_models) == SELECTABLE_AGENT_RUNNER_TYPES
        for runner_type, model in default_models.items():
            if model is None:
                continue

            resolution = resolve_model_costs(model)
            assert resolution.rate_missing is False, f"{runner_type.value}: {model}"
            assert resolution.cost_per_m_input > 0, f"{runner_type.value}: {model}"
            assert resolution.cost_per_m_output > 0, f"{runner_type.value}: {model}"

    @pytest.mark.parametrize(
        "field",
        [
            "cost_per_m_cache_read",
            "cost_per_m_cache_creation",
            "cost_per_m_input",
            "cost_per_m_output",
        ],
    )
    def test_rejects_every_negative_rate(self, field: str) -> None:
        with pytest.raises(ValidationError):
            ModelCostResolution(**{field: -1}, rate_missing=False)

    def test_exact_match_wins_over_prefixes(self, tmp_path: Path) -> None:
        _load(tmp_path, {"gpt-4o": {"input": 1}, "gpt-4o-mini": {"input": 2}})

        assert resolve_model_costs("gpt-4o").cost_per_m_input == 1

    def test_longest_valid_prefix_wins_for_overlapping_models(self, tmp_path: Path) -> None:
        _load(tmp_path, {"gpt-4o": {"input": 1}, "gpt-4o-mini": {"input": 2}})

        resolved = resolve_model_costs("gpt-4o-mini-20260719")

        assert resolved.cost_per_m_input == 2
        assert resolved.rate_missing is False

    def test_reverse_alias_uses_a_valid_model_boundary(self, tmp_path: Path) -> None:
        _load(tmp_path, {"gpt-4o-mini-20260719": {"input": 2}})

        assert resolve_model_costs("gpt-4o-mini").cost_per_m_input == 2

    def test_unmatched_and_zero_priced_matches_are_distinguished(self, tmp_path: Path) -> None:
        _load(tmp_path, {"zero": {}})

        assert resolve_model_costs("zero").rate_missing is False
        assert resolve_model_costs("unknown").rate_missing is True
