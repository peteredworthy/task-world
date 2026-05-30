"""Tests for token/cost fallback from per-entry metrics when action log aggregates are zero.

Covers the scenario where the CLI agent result event reports zero usage (overwriting
the per-turn accumulated total), leaving aggregate totals at zero while per-entry
metrics still hold valid turn-level data.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from orchestrator.api import compute_run_totals_from_attempts
from orchestrator.runners import PhaseHandler
from orchestrator.state.models import (
    ActionEntryKind,
    ActionLog,
    ActionLogEntry,
    TurnMetrics,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_creation: int = 0,
    kind: ActionEntryKind = ActionEntryKind.ASSISTANT_TEXT,
) -> ActionLogEntry:
    return ActionLogEntry(
        kind=kind,
        metrics=TurnMetrics(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
        ),
    )


def _make_tool_entry() -> ActionLogEntry:
    return ActionLogEntry(kind=ActionEntryKind.TOOL_USE)  # no metrics


def _make_action_log(
    entries: list[ActionLogEntry],
    *,
    total_input: int = 0,
    total_output: int = 0,
    total_cache_read: int = 0,
    total_cache_creation: int = 0,
    agent_model: str | None = "claude-sonnet-4-6",
) -> ActionLog:
    return ActionLog(
        entries=entries,
        agent_model=agent_model,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cache_read_tokens=total_cache_read,
        total_cache_creation_tokens=total_cache_creation,
    )


def _make_result(action_log: ActionLog | None) -> Any:
    from orchestrator.runners.types import ExecutionMetrics

    return SimpleNamespace(
        action_log=action_log,
        metrics=ExecutionMetrics(),
    )


# ---------------------------------------------------------------------------
# PhaseHandler._extract_metrics_and_usage
# ---------------------------------------------------------------------------


class TestExtractMetricsAndUsage:
    def test_uses_aggregate_when_populated(self) -> None:
        """When aggregate totals are non-zero, they take precedence over per-entry."""
        al = _make_action_log(
            entries=[_make_entry(input_tokens=999, output_tokens=888)],
            total_input=1000,
            total_output=500,
        )
        result = _make_result(al)
        metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        assert len(usage) == 1
        assert usage[0].input_tokens == 1000
        assert usage[0].output_tokens == 500
        assert metrics.tokens_read == 1000
        assert metrics.tokens_write == 500

    def test_falls_back_to_per_entry_when_aggregate_is_zero(self) -> None:
        """When aggregates are zero but entries have metrics, sum entries instead."""
        al = _make_action_log(
            entries=[
                _make_entry(input_tokens=500, output_tokens=200, cache_read=100),
                _make_tool_entry(),  # no metrics — should be skipped
                _make_entry(input_tokens=300, output_tokens=150, cache_creation=50),
            ],
            total_input=0,
            total_output=0,
        )
        result = _make_result(al)
        metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        assert len(usage) == 1
        assert usage[0].input_tokens == 800
        assert usage[0].output_tokens == 350
        assert usage[0].cache_read_tokens == 100
        assert usage[0].cache_creation_tokens == 50
        assert metrics.tokens_read == 800
        assert metrics.tokens_write == 350
        assert metrics.tokens_cache == 150  # cache_read + cache_creation

    def test_returns_empty_when_no_action_log(self) -> None:
        result = _make_result(action_log=None)
        metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        assert usage == []
        assert metrics.tokens_read == 0

    def test_returns_empty_when_aggregate_zero_and_no_entry_metrics(self) -> None:
        """No usage extracted when aggregate is 0 and entries have no metrics either."""
        al = _make_action_log(
            entries=[_make_tool_entry(), _make_tool_entry()],
            total_input=0,
            total_output=0,
        )
        result = _make_result(al)
        metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        assert usage == []
        assert metrics.tokens_read == 0

    def test_real_world_1_9m_tokens_scenario(self) -> None:
        """Simulate the 1.9M-displayed-tokens scenario: aggregate=0, entries have data."""
        turns = [
            _make_entry(input_tokens=100_000, output_tokens=5_000),
            _make_entry(input_tokens=200_000, output_tokens=8_000),
            _make_entry(input_tokens=1_600_000, output_tokens=30_000, cache_read=500_000),
        ]
        al = _make_action_log(entries=turns, total_input=0, total_output=0)
        result = _make_result(al)
        metrics, usage = PhaseHandler._extract_metrics_and_usage(result)

        assert len(usage) == 1
        assert usage[0].input_tokens == 1_900_000
        assert usage[0].output_tokens == 43_000
        assert usage[0].cache_read_tokens == 500_000
        assert metrics.tokens_read == 1_900_000
        assert metrics.tokens_write == 43_000


# ---------------------------------------------------------------------------
# compute_run_totals_from_attempts (presenter fallback)
# ---------------------------------------------------------------------------


def _make_run_with_action_log(action_log: ActionLog) -> Any:
    """Build a minimal fake Run object with a single attempt."""
    attempt = SimpleNamespace(
        token_usage_by_model=[],
        action_log=action_log,
        metrics=SimpleNamespace(
            duration_ms=0, num_actions=0, tokens_read=0, tokens_write=0, tokens_cache=0
        ),
    )
    task = SimpleNamespace(attempts=[attempt])
    step = SimpleNamespace(tasks=[task])
    return SimpleNamespace(steps=[step])


class TestComputeRunTotalsFromAttempts:
    def test_uses_per_entry_metrics_when_aggregate_zero(self) -> None:
        al = _make_action_log(
            entries=[
                _make_entry(input_tokens=400, output_tokens=100),
                _make_tool_entry(),
                _make_entry(input_tokens=600, output_tokens=200, cache_read=50),
            ],
            total_input=0,
            total_output=0,
        )
        run = _make_run_with_action_log(al)
        tokens_read, tokens_write, tokens_cache, _dur, _actions, usage = (
            compute_run_totals_from_attempts(run)
        )

        assert tokens_read == 1000
        assert tokens_write == 300
        assert tokens_cache == 50

    def test_uses_aggregate_when_populated(self) -> None:
        al = _make_action_log(
            entries=[_make_entry(input_tokens=999, output_tokens=999)],
            total_input=2000,
            total_output=1000,
            total_cache_read=200,
        )
        run = _make_run_with_action_log(al)
        tokens_read, tokens_write, tokens_cache, _dur, _actions, _usage = (
            compute_run_totals_from_attempts(run)
        )

        assert tokens_read == 2000
        assert tokens_write == 1000
        assert tokens_cache == 200

    def test_returns_zero_when_no_entries_and_aggregate_zero(self) -> None:
        al = _make_action_log(entries=[], total_input=0, total_output=0)
        run = _make_run_with_action_log(al)
        tokens_read, tokens_write, tokens_cache, _dur, _actions, usage = (
            compute_run_totals_from_attempts(run)
        )

        assert tokens_read == 0
        assert tokens_write == 0
        assert usage == []
