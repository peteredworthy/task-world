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
        total_duration_ms=0,
        total_num_actions=0,
        token_usage_by_model=[],
    )


def test_merge_accumulates_duration_and_tool_calls_independently() -> None:
    run = _run()
    merge_token_usage_into_run(
        run,
        gen_ai_usage_input_tokens=100,
        gen_ai_usage_output_tokens=200,
        gen_ai_usage_cache_read_input_tokens=50,
        duration_ms=1200,
        num_actions=7,
    )
    assert run.total_duration_ms == 1200
    assert run.total_num_actions == 7  # tool-call count flows through


def test_merge_keeps_each_usage_execution_as_an_immutable_entry() -> None:
    run = _run()
    first_execution = {"model": "m1", "gen_ai_usage_output_tokens": 200}
    second_execution = {"model": "m1", "gen_ai_usage_output_tokens": 300}
    merge_token_usage_into_run(run, token_usage_by_model=[first_execution], num_actions=3)
    merge_token_usage_into_run(run, token_usage_by_model=[second_execution], num_actions=4)
    assert run.token_usage_by_model == [first_execution, second_execution]
    assert run.total_num_actions == 7


def test_merge_does_not_merge_usage_entries_with_the_same_model() -> None:
    run = _run()
    merge_token_usage_into_run(
        run,
        token_usage_by_model=[
            {
                "model": "m1",
                "gen_ai_usage_input_tokens": 10,
                "gen_ai_usage_output_tokens": 20,
                "gen_ai_usage_cache_read_input_tokens": 5,
                "gen_ai_usage_cache_creation_input_tokens": 1,
            },
        ],
    )
    merge_token_usage_into_run(
        run,
        token_usage_by_model=[
            {
                "model": "m1",
                "gen_ai_usage_input_tokens": 7,
                "gen_ai_usage_output_tokens": 3,
                "gen_ai_usage_cache_read_input_tokens": 2,
                "gen_ai_usage_cache_creation_input_tokens": 0,
            },
            {
                "model": "m2",
                "gen_ai_usage_input_tokens": 100,
                "gen_ai_usage_output_tokens": 0,
                "gen_ai_usage_cache_read_input_tokens": 0,
                "gen_ai_usage_cache_creation_input_tokens": 0,
            },
        ],
    )
    assert run.token_usage_by_model == [
        {
            "model": "m1",
            "gen_ai_usage_input_tokens": 10,
            "gen_ai_usage_output_tokens": 20,
            "gen_ai_usage_cache_read_input_tokens": 5,
            "gen_ai_usage_cache_creation_input_tokens": 1,
        },
        {
            "model": "m1",
            "gen_ai_usage_input_tokens": 7,
            "gen_ai_usage_output_tokens": 3,
            "gen_ai_usage_cache_read_input_tokens": 2,
            "gen_ai_usage_cache_creation_input_tokens": 0,
        },
        {
            "model": "m2",
            "gen_ai_usage_input_tokens": 100,
            "gen_ai_usage_output_tokens": 0,
            "gen_ai_usage_cache_read_input_tokens": 0,
            "gen_ai_usage_cache_creation_input_tokens": 0,
        },
    ]


def test_merge_none_run_is_noop() -> None:
    # Must not raise when there is no run model (e.g. a detached execution).
    merge_token_usage_into_run(None, gen_ai_usage_output_tokens=999)
