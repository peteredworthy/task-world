"""Unit tests for ModelTokenUsage and PhaseHandler._extract_metrics_and_usage."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import orchestrator.runners.costs as costs_mod
from orchestrator.runners.costs import load_cost_table
from orchestrator.runners import PhaseHandler
from orchestrator.runners.types import ExecutionMetrics, ExecutionResult
from orchestrator.state.models import (
    ActionEntryKind,
    ActionLog,
    ActionLogEntry,
    ModelTokenUsage,
    SubAgentLog,
    ToolUseDetail,
)


@pytest.fixture(autouse=True)
def _reset_cost_table():
    """Reset the module-level cost table before and after every test."""
    costs_mod._cost_table = {}
    yield
    costs_mod._cost_table = {}


@pytest.fixture()
def cost_file(tmp_path: Path) -> Path:
    """Write a deterministic cost YAML and load it; return the path."""
    path = tmp_path / "model_costs.yaml"
    path.write_text(
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
    load_cost_table(path)
    return path


# ---------------------------------------------------------------------------
# ModelTokenUsage.total_cost_usd
# ---------------------------------------------------------------------------


class TestModelTokenUsageTotalCostUsd:
    def test_computes_sum_of_all_token_types(self) -> None:
        u = ModelTokenUsage(
            model="claude-sonnet-4-6",
            cache_read_tokens=1_000_000,
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cost_per_m_cache_read=0.30,
            cost_per_m_input=3.00,
            cost_per_m_output=15.00,
        )
        assert u.total_cost_usd == pytest.approx(0.30 + 3.00 + 15.00)

    def test_cache_creation_included_in_total(self) -> None:
        u = ModelTokenUsage(
            model="claude-sonnet-4-6",
            cache_creation_tokens=1_000_000,
            cost_per_m_cache_creation=3.75,
        )
        assert u.total_cost_usd == pytest.approx(3.75)

    def test_zero_tokens_gives_zero_cost(self) -> None:
        u = ModelTokenUsage(
            model="claude-sonnet-4-6",
            cost_per_m_input=3.00,
            cost_per_m_output=15.00,
        )
        assert u.total_cost_usd == 0.0

    def test_zero_rates_gives_zero_cost(self) -> None:
        u = ModelTokenUsage(
            model="unknown-model",
            input_tokens=1_000_000,
            output_tokens=500_000,
        )
        assert u.total_cost_usd == 0.0

    def test_partial_tokens_scale_correctly(self) -> None:
        # 500k input tokens at $3/M = $1.50
        u = ModelTokenUsage(
            model="claude-sonnet-4-6",
            input_tokens=500_000,
            cost_per_m_input=3.00,
        )
        assert u.total_cost_usd == pytest.approx(1.50)


# ---------------------------------------------------------------------------
# PhaseHandler._extract_metrics_and_usage
# ---------------------------------------------------------------------------


def _make_tool_use_entry(seq: int = 1) -> ActionLogEntry:
    return ActionLogEntry(
        sequence_num=seq,
        kind=ActionEntryKind.TOOL_USE,
        tool_use=ToolUseDetail(tool_use_id=f"tu_{seq}", tool_name="bash"),
    )


class TestExtractMetricsAndUsage:
    def test_no_action_log_returns_result_metrics(self) -> None:
        original_metrics = ExecutionMetrics(
            tokens_read=100, tokens_write=50, tokens_cache=10, duration_ms=200
        )
        result = ExecutionResult(success=True, metrics=original_metrics, action_log=None)

        metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        assert metrics is original_metrics
        assert usage == []

    def test_parent_only_action_log(self, cost_file: Path) -> None:
        al = ActionLog(
            agent_model="claude-sonnet-4-6",
            total_input_tokens=500_000,
            total_output_tokens=250_000,
            total_cache_read_tokens=100_000,
            total_cache_creation_tokens=0,
            total_duration_ms=3000,
            entries=[_make_tool_use_entry(1), _make_tool_use_entry(2)],
        )
        result = ExecutionResult(success=True, action_log=al)

        metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        assert len(usage) == 1
        parent = usage[0]
        assert parent.model == "claude-sonnet-4-6"
        assert parent.input_tokens == 500_000
        assert parent.output_tokens == 250_000
        assert parent.cache_read_tokens == 100_000
        assert parent.cost_per_m_input == pytest.approx(3.00)
        assert parent.cost_per_m_output == pytest.approx(15.00)

    def test_legacy_metrics_built_from_parent_tokens(self, cost_file: Path) -> None:
        al = ActionLog(
            agent_model="claude-sonnet-4-6",
            total_input_tokens=1_000,
            total_output_tokens=2_000,
            total_cache_read_tokens=500,
            total_cache_creation_tokens=300,
            total_duration_ms=1500,
            entries=[_make_tool_use_entry(1), _make_tool_use_entry(2)],
        )
        result = ExecutionResult(success=True, action_log=al)

        metrics, _usage = PhaseHandler._extract_metrics_and_usage(result)

        assert metrics.tokens_read == 1_000
        assert metrics.tokens_write == 2_000
        assert metrics.tokens_cache == 500 + 300
        assert metrics.duration_ms == 1500
        assert metrics.num_actions == 2

    def test_sub_agents_added_as_separate_usage_entries(self, cost_file: Path) -> None:
        sa = SubAgentLog(
            agent_id="sub-1",
            model="claude-haiku-4-5",
            total_input_tokens=200_000,
            total_output_tokens=100_000,
            total_cache_read_tokens=0,
            total_cache_creation_tokens=0,
        )
        al = ActionLog(
            agent_model="claude-sonnet-4-6",
            total_input_tokens=1_000_000,
            total_output_tokens=500_000,
            total_duration_ms=5000,
            sub_agents=[sa],
            entries=[_make_tool_use_entry()],
        )
        result = ExecutionResult(success=True, action_log=al)

        _metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        assert len(usage) == 2
        models = {u.model for u in usage}
        assert "claude-sonnet-4-6" in models
        assert "claude-haiku-4-5" in models

    def test_sub_agents_with_same_model_are_grouped(self, cost_file: Path) -> None:
        sub_agents = [
            SubAgentLog(
                agent_id="sub-1",
                model="claude-haiku-4-5",
                total_input_tokens=100_000,
                total_output_tokens=50_000,
            ),
            SubAgentLog(
                agent_id="sub-2",
                model="claude-haiku-4-5",
                total_input_tokens=200_000,
                total_output_tokens=80_000,
            ),
        ]
        al = ActionLog(
            agent_model="claude-sonnet-4-6",
            total_input_tokens=1_000_000,
            total_output_tokens=500_000,
            total_duration_ms=4000,
            sub_agents=sub_agents,
            entries=[_make_tool_use_entry()],
        )
        result = ExecutionResult(success=True, action_log=al)

        _metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        # Should have exactly 2 entries: parent + one combined haiku entry
        assert len(usage) == 2
        haiku = next(u for u in usage if u.model == "claude-haiku-4-5")
        assert haiku.input_tokens == 300_000  # 100k + 200k
        assert haiku.output_tokens == 130_000  # 50k + 80k

    def test_legacy_metrics_include_sub_agent_tokens(self, cost_file: Path) -> None:
        sub_agents = [
            SubAgentLog(
                agent_id="sub-1",
                model="claude-haiku-4-5",
                total_input_tokens=200_000,
                total_output_tokens=100_000,
                total_cache_read_tokens=50_000,
                total_cache_creation_tokens=10_000,
            ),
        ]
        al = ActionLog(
            agent_model="claude-sonnet-4-6",
            total_input_tokens=1_000_000,
            total_output_tokens=500_000,
            total_cache_read_tokens=100_000,
            total_cache_creation_tokens=20_000,
            total_duration_ms=6000,
            sub_agents=sub_agents,
            entries=[_make_tool_use_entry()],
        )
        result = ExecutionResult(success=True, action_log=al)

        metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        # Legacy tokens_read = all input tokens from all models
        expected_input = 1_000_000 + 200_000
        expected_output = 500_000 + 100_000
        expected_cache = (100_000 + 20_000) + (50_000 + 10_000)

        assert metrics.tokens_read == expected_input
        assert metrics.tokens_write == expected_output
        assert metrics.tokens_cache == expected_cache

    def test_cost_rates_embedded_from_cost_table(self, cost_file: Path) -> None:
        al = ActionLog(
            agent_model="claude-sonnet-4-6",
            total_input_tokens=1_000_000,
            total_output_tokens=1_000_000,
            total_duration_ms=1000,
            entries=[_make_tool_use_entry()],
        )
        result = ExecutionResult(success=True, action_log=al)

        _metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        parent = usage[0]
        assert parent.cost_per_m_input == pytest.approx(3.00)
        assert parent.cost_per_m_output == pytest.approx(15.00)
        assert parent.total_cost_usd == pytest.approx(3.00 + 15.00)

    def test_action_log_with_zero_tokens_produces_no_usage(self, cost_file: Path) -> None:
        """An ActionLog with all-zero token counts should not emit a parent usage entry."""
        al = ActionLog(
            agent_model="claude-sonnet-4-6",
            total_input_tokens=0,
            total_output_tokens=0,
            total_duration_ms=0,
        )
        result = ExecutionResult(success=True, action_log=al)

        _metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        # No tokens → no usage entries built
        assert usage == []

    def test_unknown_model_in_sub_agent_gets_zero_rates(self, cost_file: Path) -> None:
        sub_agents = [
            SubAgentLog(
                agent_id="sub-x",
                model="gpt-unknown",
                total_input_tokens=50_000,
                total_output_tokens=25_000,
            )
        ]
        al = ActionLog(
            agent_model="claude-sonnet-4-6",
            total_input_tokens=1_000_000,
            total_output_tokens=500_000,
            total_duration_ms=2000,
            sub_agents=sub_agents,
            entries=[_make_tool_use_entry()],
        )
        result = ExecutionResult(success=True, action_log=al)

        _metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        unknown = next(u for u in usage if u.model == "gpt-unknown")
        assert unknown.cost_per_m_input == 0.0
        assert unknown.cost_per_m_output == 0.0
        assert unknown.total_cost_usd == 0.0
