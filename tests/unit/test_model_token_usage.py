"""Tests for canonical immutable model usage facts and real extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from orchestrator.runners import (
    ExecutionMetrics,
    ExecutionResult,
    extract_metrics_and_usage,
    load_cost_table,
    load_sub_agents,
)
from orchestrator.state import ActionLog, ModelTokenUsage, SubAgentLog


@pytest.fixture(autouse=True)
def _reset_cost_table():
    from orchestrator.runners.costs import _cost_table

    _cost_table.clear()
    yield
    from orchestrator.runners.costs import _cost_table

    _cost_table.clear()


@pytest.fixture()
def cost_file(tmp_path: Path) -> Path:
    path = tmp_path / "model_costs.yaml"
    path.write_text(
        yaml.dump(
            {
                "models": {
                    "known": {
                        "cache_read": 1,
                        "cache_creation": 2,
                        "input": 3,
                        "output": 4,
                    }
                }
            }
        )
    )
    load_cost_table(path)
    return path


class TestModelTokenUsage:
    def test_rejects_negative_counts_and_cache_larger_than_input(self) -> None:
        with pytest.raises(ValidationError):
            ModelTokenUsage(model="known", gen_ai_usage_output_tokens=-1)
        with pytest.raises(ValidationError, match="cache"):
            ModelTokenUsage(
                model="known",
                gen_ai_usage_input_tokens=10,
                gen_ai_usage_cache_read_input_tokens=6,
                gen_ai_usage_cache_creation_input_tokens=5,
            )

    def test_finish_reasons_round_trip_as_a_json_array(self) -> None:
        usage = ModelTokenUsage(
            model="known", gen_ai_response_finish_reasons=["stop", "tool_calls"]
        )

        restored = ModelTokenUsage.model_validate_json(usage.model_dump_json())

        assert restored.gen_ai_response_finish_reasons == ["stop", "tool_calls"]
        assert restored.model_dump(mode="json")["gen_ai_response_finish_reasons"] == [
            "stop",
            "tool_calls",
        ]

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda reasons: reasons.append("length"),
            lambda reasons: reasons.__setitem__(0, "length"),
            lambda reasons: reasons.__delitem__(0),
            lambda reasons: reasons.extend(["length"]),
        ],
    )
    def test_finish_reasons_cannot_be_mutated_in_place(self, mutation) -> None:
        usage = ModelTokenUsage(model="known", gen_ai_response_finish_reasons=["stop"])

        with pytest.raises((AttributeError, TypeError)):
            mutation(usage.gen_ai_response_finish_reasons)

        assert usage.gen_ai_response_finish_reasons == ["stop"]

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda r: r.insert(0, "x"),
            lambda r: r.pop(),
            lambda r: r.remove("stop"),
            lambda r: r.clear(),
            lambda r: r.reverse(),
            lambda r: r.sort(),
            lambda r: r.__iadd__(["x"]),
            lambda r: r.__imul__(2),
        ],
    )
    def test_finish_reasons_reject_remaining_list_mutators(self, mutation) -> None:
        with pytest.raises(TypeError):
            mutation(
                ModelTokenUsage(
                    model="known", gen_ai_response_finish_reasons=["stop"]
                ).gen_ai_response_finish_reasons
            )

    @pytest.mark.parametrize(
        "field",
        [
            "gen_ai_usage_input_tokens",
            "gen_ai_usage_output_tokens",
            "gen_ai_usage_cache_read_input_tokens",
            "gen_ai_usage_cache_creation_input_tokens",
            "gen_ai_usage_reasoning_output_tokens",
            "latency_ms",
            "cost_usd",
        ],
    )
    def test_rejects_every_negative_canonical_numeric_field(self, field: str) -> None:
        with pytest.raises(ValidationError):
            ModelTokenUsage(model="known", **{field: -1})

    @pytest.mark.parametrize("rate", [-1, float("inf"), float("nan"), "not-a-rate"])
    def test_rejects_invalid_legacy_rates_before_cost_construction(self, rate: float) -> None:
        with pytest.raises(ValidationError):
            ModelTokenUsage(model="known", input_tokens=1, cost_per_m_input=rate)

    def test_rejects_numeric_like_legacy_rate_before_float_conversion_or_arithmetic(self) -> None:
        class ExplosiveNumeric:
            def __float__(self) -> float:
                raise AssertionError("legacy rate reached float conversion")

            def __rmul__(self, _: object) -> float:
                raise AssertionError("legacy rate reached cost arithmetic")

        with pytest.raises(ValidationError):
            ModelTokenUsage(
                model="known",
                input_tokens=1,
                cost_per_m_input=ExplosiveNumeric(),
            )

    def test_rejects_overflowing_derived_legacy_cost(self) -> None:
        with pytest.raises(ValidationError):
            ModelTokenUsage(model="known", input_tokens=10**308, cost_per_m_input=10**308)

    def test_rejects_conflicting_canonical_and_legacy_values(self) -> None:
        with pytest.raises(ValidationError, match="conflicting"):
            ModelTokenUsage(
                model="known",
                input_tokens=10,
                gen_ai_usage_input_tokens=11,
            )

    def test_keeps_canonical_value_when_legacy_value_matches(self) -> None:
        usage = ModelTokenUsage(
            model="known",
            input_tokens=10,
            gen_ai_usage_input_tokens=10,
        )

        assert usage.gen_ai_usage_input_tokens == 10


class TestExtractMetricsAndUsage:
    def test_exclusive_input_is_normalized_to_include_cache(self, cost_file: Path) -> None:
        result = ExecutionResult(
            success=True,
            metrics=ExecutionMetrics(),
            action_log=ActionLog(
                agent_model="known",
                total_input_tokens=10,
                total_output_tokens=4,
                total_cache_read_tokens=20,
                total_cache_creation_tokens=30,
                input_tokens_include_cache=False,
            ),
        )

        _metrics, usage = extract_metrics_and_usage(result)

        assert usage[0].gen_ai_usage_input_tokens == 60
        assert usage[0].gen_ai_usage_cache_read_input_tokens == 20
        assert usage[0].gen_ai_usage_cache_creation_input_tokens == 30
        assert usage[0].cost_usd == pytest.approx((10 * 3 + 20 + 60 + 4 * 4) / 1_000_000)

    def test_inclusive_input_is_not_double_counted(self, cost_file: Path) -> None:
        result = ExecutionResult(
            success=True,
            metrics=ExecutionMetrics(),
            action_log=ActionLog(
                agent_model="known",
                total_input_tokens=60,
                total_output_tokens=4,
                total_cache_read_tokens=20,
                total_cache_creation_tokens=30,
                input_tokens_include_cache=True,
            ),
        )

        _metrics, usage = extract_metrics_and_usage(result)

        assert usage[0].gen_ai_usage_input_tokens == 60

    def test_reasoning_observability_does_not_change_captured_cost(self, cost_file: Path) -> None:
        result = ExecutionResult(
            success=True,
            action_log=ActionLog(agent_model="known", total_input_tokens=10, total_output_tokens=4),
        )
        base = extract_metrics_and_usage(result)[1][0]
        observed_reasoning = base.model_copy(update={"gen_ai_usage_reasoning_output_tokens": 3})

        assert observed_reasoning.cost_usd == base.cost_usd

    def test_same_model_executions_append_distinct_facts_and_propagate_rate_missing(
        self, cost_file: Path
    ) -> None:
        result = ExecutionResult(
            success=True,
            metrics=ExecutionMetrics(),
            action_log=ActionLog(
                agent_model="known",
                total_input_tokens=1,
                sub_agents=[
                    SubAgentLog(model="known", total_input_tokens=2),
                    SubAgentLog(model="unknown", total_input_tokens=3),
                ],
            ),
        )

        _metrics, usage = extract_metrics_and_usage(result)

        assert [fact.gen_ai_usage_input_tokens for fact in usage] == [1, 2, 3]
        assert [fact.rate_missing for fact in usage] == [False, False, True]

    def test_zero_parent_does_not_discard_nonzero_sub_agent_fact(self, cost_file: Path) -> None:
        result = ExecutionResult(
            success=True,
            metrics=ExecutionMetrics(),
            action_log=ActionLog(
                agent_model="known",
                sub_agents=[SubAgentLog(model="known", total_input_tokens=2)],
            ),
        )

        metrics, usage = extract_metrics_and_usage(result)

        assert len(usage) == 1
        assert usage[0].gen_ai_usage_input_tokens == 2
        assert metrics.tokens_read == 2

    def test_claude_sub_agent_exclusive_input_adds_cache_exactly_once(
        self, tmp_path: Path, cost_file: Path
    ) -> None:
        working_dir = str(tmp_path / "workspace")
        session_id = "parent-session"
        projects_dir = tmp_path / "projects"
        slug = working_dir.replace("/", "-")
        subagents_dir = projects_dir / slug / session_id / "subagents"
        subagents_dir.mkdir(parents=True)
        (subagents_dir / "worker.jsonl").write_text(
            '{"type":"assistant","message":{"id":"turn-1","model":"known",'
            '"usage":{"input_tokens":10,"output_tokens":4,'
            '"cache_read_input_tokens":2,"cache_creation_input_tokens":3},'
            '"content":[{"type":"text","text":"done"}]}}\n'
        )

        sub_agents = load_sub_agents(working_dir, session_id, projects_dir=projects_dir)

        assert len(sub_agents) == 1
        assert sub_agents[0].input_tokens_include_cache is False
        result = ExecutionResult(
            success=True,
            metrics=ExecutionMetrics(),
            action_log=ActionLog(sub_agents=sub_agents),
        )

        metrics, usage = extract_metrics_and_usage(result)

        assert usage[0].gen_ai_usage_input_tokens == 15
        assert usage[0].gen_ai_usage_cache_read_input_tokens == 2
        assert usage[0].gen_ai_usage_cache_creation_input_tokens == 3
        assert metrics.tokens_read == 15
