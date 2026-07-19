"""Unit tests for canonical immutable model usage facts."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

import orchestrator.runners.costs as costs_mod
from orchestrator.runners.costs import load_cost_table
from orchestrator.state.models import ModelTokenUsage


class TestModelTokenUsage:
    def test_preserves_all_otel_usage_components(self) -> None:
        usage = ModelTokenUsage(
            model="gpt-5",
            gen_ai_usage_input_tokens=100,
            gen_ai_usage_output_tokens=40,
            gen_ai_usage_cache_read_input_tokens=20,
            gen_ai_usage_cache_creation_input_tokens=10,
            gen_ai_usage_reasoning_output_tokens=15,
            gen_ai_response_finish_reasons=["stop", "tool_calls"],
            latency_ms=250,
        )

        assert usage.model == "gpt-5"
        assert usage.gen_ai_usage_input_tokens == 100
        assert usage.gen_ai_usage_output_tokens == 40
        assert usage.gen_ai_usage_cache_read_input_tokens == 20
        assert usage.gen_ai_usage_cache_creation_input_tokens == 10
        assert usage.gen_ai_usage_reasoning_output_tokens == 15
        assert usage.gen_ai_response_finish_reasons == ["stop", "tool_calls"]
        assert usage.latency_ms == 250

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("gen_ai_usage_input_tokens", -1),
            ("gen_ai_usage_output_tokens", -1),
            ("gen_ai_usage_cache_read_input_tokens", -1),
            ("gen_ai_usage_cache_creation_input_tokens", -1),
            ("gen_ai_usage_reasoning_output_tokens", -1),
            ("latency_ms", -1),
        ],
    )
    def test_rejects_negative_counts(self, field: str, value: int) -> None:
        with pytest.raises(ValidationError):
            ModelTokenUsage(model="gpt-5", **{field: value})

    def test_rejects_cache_components_larger_than_input(self) -> None:
        with pytest.raises(ValidationError, match="cache"):
            ModelTokenUsage(
                model="gpt-5",
                gen_ai_usage_input_tokens=10,
                gen_ai_usage_cache_read_input_tokens=6,
                gen_ai_usage_cache_creation_input_tokens=5,
            )

    def test_round_trips_plural_finish_reasons_in_json(self) -> None:
        usage = ModelTokenUsage(
            model="gpt-5",
            gen_ai_response_finish_reasons=["stop", "length"],
        )

        restored = ModelTokenUsage.model_validate_json(usage.model_dump_json())

        assert restored == usage
        assert restored.gen_ai_response_finish_reasons == ["stop", "length"]

    def test_is_an_immutable_append_oriented_fact(self) -> None:
        usage = ModelTokenUsage(model="gpt-5", gen_ai_usage_input_tokens=10)

        with pytest.raises(ValidationError, match="frozen"):
            usage.gen_ai_usage_input_tokens = 11

        later_usage = ModelTokenUsage(model="gpt-5", gen_ai_usage_input_tokens=11)
        assert [usage, later_usage] == [usage, later_usage]

    def test_transitional_legacy_payload_round_trips_until_task_3(self) -> None:
        usage = ModelTokenUsage(
            model="legacy-model",
            input_tokens=100,
            output_tokens=40,
            cache_read_tokens=20,
            cache_creation_tokens=10,
            cost_per_m_input=2.50,
        )

        assert usage.gen_ai_usage_input_tokens == 100
        assert usage.model_dump()["input_tokens"] == 100
        assert usage.cost_per_m_input == 2.50

    def test_prices_cached_input_once_and_does_not_double_charge_reasoning(self, tmp_path) -> None:
        cost_file = tmp_path / "model_costs.yaml"
        cost_file.write_text(
            yaml.dump(
                {
                    "models": {
                        "gpt-5": {
                            "cache_read": 0.25,
                            "cache_creation": 1.25,
                            "input": 2.50,
                            "output": 10.00,
                        }
                    }
                }
            )
        )
        costs_mod._cost_table = {}
        load_cost_table(cost_file)
        usage = ModelTokenUsage(
            model="gpt-5",
            gen_ai_usage_input_tokens=100,
            gen_ai_usage_cache_read_input_tokens=20,
            gen_ai_usage_cache_creation_input_tokens=10,
            gen_ai_usage_output_tokens=40,
            gen_ai_usage_reasoning_output_tokens=15,
        )

        expected_cost = (70 * 2.50 + 20 * 0.25 + 10 * 1.25 + 40 * 10) / 1_000_000
        assert usage.total_cost_usd == pytest.approx(expected_cost)
