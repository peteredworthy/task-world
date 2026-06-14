"""Unit tests for the shared, carrier-agnostic run token-usage sink.

`merge_token_usage_into_run` is the single place run-level token/cost accounting
happens, called by BOTH the legacy attempt path (update_latest_attempt) and the
graph dispatch path (via the on_agent_usage callback). These tests pin its maths
on a plain stand-in run object — no DB, no carrier.
"""

from __future__ import annotations

from types import SimpleNamespace

from orchestrator.db import merge_token_usage_into_run


def _run() -> SimpleNamespace:
    return SimpleNamespace(
        total_tokens_read=0,
        total_tokens_write=0,
        total_tokens_cache=0,
        total_duration_ms=0,
        total_num_actions=0,
        token_usage_by_model=[],
    )


def test_merge_accumulates_totals_and_tool_calls() -> None:
    run = _run()
    merge_token_usage_into_run(
        run,
        tokens_read=100,
        tokens_write=200,
        tokens_cache=50,
        duration_ms=1200,
        num_actions=7,
    )
    assert run.total_tokens_read == 100
    assert run.total_tokens_write == 200
    assert run.total_tokens_cache == 50
    assert run.total_duration_ms == 1200
    assert run.total_num_actions == 7  # tool-call count flows through


def test_merge_is_additive_across_executions() -> None:
    run = _run()
    merge_token_usage_into_run(run, tokens_write=200, num_actions=3)
    merge_token_usage_into_run(run, tokens_write=300, num_actions=4)
    assert run.total_tokens_write == 500
    assert run.total_num_actions == 7  # two agent executions accumulate


def test_merge_per_model_usage_sums_by_model() -> None:
    run = _run()
    merge_token_usage_into_run(
        run,
        token_usage_by_model=[
            {
                "model": "m1",
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_read_tokens": 5,
                "cache_creation_tokens": 1,
            },
        ],
    )
    merge_token_usage_into_run(
        run,
        token_usage_by_model=[
            {
                "model": "m1",
                "input_tokens": 7,
                "output_tokens": 3,
                "cache_read_tokens": 2,
                "cache_creation_tokens": 0,
            },
            {
                "model": "m2",
                "input_tokens": 100,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
            },
        ],
    )
    by_model = {u["model"]: u for u in run.token_usage_by_model}
    assert by_model["m1"]["input_tokens"] == 17  # 10 + 7 merged
    assert by_model["m1"]["output_tokens"] == 23
    assert by_model["m2"]["input_tokens"] == 100


def test_merge_none_run_is_noop() -> None:
    # Must not raise when there is no run model (e.g. a detached execution).
    merge_token_usage_into_run(None, tokens_write=999)
