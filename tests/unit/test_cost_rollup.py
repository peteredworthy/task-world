"""Tests for the pure graph usage cost rollup reducer."""

from datetime import datetime, timezone

import pytest

import orchestrator.api as api
from orchestrator.api import CostRollupFact, CostRollupFilters, compute_cost_rollup


def _fact(
    *,
    run_id: str = "run-a",
    timestamp: datetime = datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
    node_kind: str = "builder",
    profile: str | None = "coder",
    execution_id: str = "execution-a",
    usage_index: int = 0,
    model: str = "gpt-5",
    gen_ai_usage_input_tokens: int = 10,
    gen_ai_usage_output_tokens: int = 5,
    gen_ai_usage_cache_read_input_tokens: int = 2,
    gen_ai_usage_cache_creation_input_tokens: int = 1,
    gen_ai_usage_reasoning_output_tokens: int = 3,
    cost_usd: float = 0.25,
    latency_ms: int = 100,
    num_actions: int = 4,
    rate_missing: bool = False,
) -> CostRollupFact:
    return CostRollupFact(
        run_id=run_id,
        timestamp=timestamp,
        node_kind=node_kind,
        profile=profile,
        execution_id=execution_id,
        usage_index=usage_index,
        model=model,
        gen_ai_usage_input_tokens=gen_ai_usage_input_tokens,
        gen_ai_usage_output_tokens=gen_ai_usage_output_tokens,
        gen_ai_usage_cache_read_input_tokens=gen_ai_usage_cache_read_input_tokens,
        gen_ai_usage_cache_creation_input_tokens=gen_ai_usage_cache_creation_input_tokens,
        gen_ai_usage_reasoning_output_tokens=gen_ai_usage_reasoning_output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        num_actions=num_actions,
        rate_missing=rate_missing,
    )


def test_groups_graph_usage_by_every_supported_dimension() -> None:
    facts = [
        _fact(),
        _fact(
            run_id="run-b",
            timestamp=datetime(2026, 7, 21, 1, tzinfo=timezone.utc),
            node_kind="verifier",
            profile=None,
            execution_id="execution-b",
            model="claude",
        ),
    ]

    response = compute_cost_rollup(facts, ("day", "node_kind", "model", "profile", "run"))

    assert response.group_by == ("day", "node_kind", "model", "profile", "run")
    assert [row.dimensions for row in response.rows] == [
        {
            "day": "2026-07-20",
            "node_kind": "builder",
            "model": "gpt-5",
            "profile": "coder",
            "run": "run-a",
        },
        {
            "day": "2026-07-21",
            "node_kind": "verifier",
            "model": "claude",
            "profile": None,
            "run": "run-b",
        },
    ]


def test_uses_utc_event_day_and_aggregates_canonical_usage_counts() -> None:
    response = compute_cost_rollup(
        [
            _fact(timestamp=datetime(2026, 7, 20, 23, tzinfo=timezone.utc)),
            _fact(
                execution_id="execution-b",
                timestamp=datetime(2026, 7, 21, 0, tzinfo=timezone.utc),
                gen_ai_usage_input_tokens=7,
                gen_ai_usage_output_tokens=11,
                gen_ai_usage_cache_read_input_tokens=13,
                gen_ai_usage_cache_creation_input_tokens=17,
                gen_ai_usage_reasoning_output_tokens=19,
                cost_usd=0.5,
                latency_ms=200,
                num_actions=6,
            ),
        ],
        ("day",),
    )

    assert [row.dimensions["day"] for row in response.rows] == ["2026-07-20", "2026-07-21"]
    assert response.rows[1].gen_ai_usage_input_tokens == 7
    assert response.rows[1].gen_ai_usage_output_tokens == 11
    assert response.rows[1].gen_ai_usage_cache_read_input_tokens == 13
    assert response.rows[1].gen_ai_usage_cache_creation_input_tokens == 17
    assert response.rows[1].gen_ai_usage_reasoning_output_tokens == 19
    assert response.rows[1].cost_usd == 0.5
    assert response.rows[1].num_actions == 6


def test_counts_execution_latency_and_actions_once_for_multiple_usage_facts() -> None:
    response = compute_cost_rollup(
        [
            _fact(),
            _fact(
                usage_index=1,
                gen_ai_usage_input_tokens=20,
                gen_ai_usage_output_tokens=30,
                cost_usd=0.75,
                latency_ms=999,
                num_actions=999,
            ),
        ],
        ("run",),
    )

    row = response.rows[0]
    assert row.execution_count == 1
    assert row.latency_ms == 100
    assert row.num_actions == 4
    assert row.gen_ai_usage_input_tokens == 30
    assert row.cost_usd == 1.0


def test_scopes_execution_identity_to_its_run_when_grouping_omits_run() -> None:
    response = compute_cost_rollup(
        [
            _fact(run_id="run-a", execution_id="shared", rate_missing=True, latency_ms=100),
            _fact(
                run_id="run-b",
                execution_id="shared",
                rate_missing=True,
                latency_ms=200,
                num_actions=6,
            ),
        ],
        ("day",),
    )

    row = response.rows[0]
    assert row.execution_count == 2
    assert row.latency_ms == 300
    assert row.num_actions == 10
    assert row.rate_missing_execution_count == 2


def test_normalizes_both_naive_time_filters_to_utc() -> None:
    filters = CostRollupFilters(
        start=datetime(2026, 7, 20),
        end=datetime(2026, 7, 21),
    )

    assert filters.start == datetime(2026, 7, 20, tzinfo=timezone.utc)
    assert filters.end == datetime(2026, 7, 21, tzinfo=timezone.utc)


def test_rejects_mixed_naive_and_aware_time_filters() -> None:
    with pytest.raises(ValueError, match="same timezone awareness"):
        CostRollupFilters(
            start=datetime(2026, 7, 20),
            end=datetime(2026, 7, 21, tzinfo=timezone.utc),
        )


def test_exports_cost_rollup_fact_loader_from_public_api() -> None:
    assert "load_cost_rollup_facts" in api.__all__
    assert callable(api.load_cost_rollup_facts)


def test_tracks_missing_rate_usage_without_inventing_missing_cost() -> None:
    response = compute_cost_rollup(
        [
            _fact(
                rate_missing=True,
                cost_usd=0.0,
                gen_ai_usage_input_tokens=11,
                gen_ai_usage_output_tokens=13,
            ),
            _fact(
                usage_index=1,
                rate_missing=True,
                cost_usd=0.0,
                gen_ai_usage_input_tokens=17,
                gen_ai_usage_output_tokens=19,
            ),
            _fact(execution_id="priced", cost_usd=2.0),
        ],
        ("run",),
    )

    row = response.rows[0]
    assert row.cost_usd == 2.0
    assert row.rate_missing_execution_count == 1
    assert row.rate_missing_input_tokens == 28
    assert row.rate_missing_output_tokens == 32
    assert row.has_rate_missing is True
    assert "rate_missing_cost_usd" not in row.model_dump()


def test_rejects_duplicate_group_dimensions() -> None:
    with pytest.raises(ValueError, match="unique"):
        compute_cost_rollup([_fact()], ("run", "run"))


def test_stops_before_materializing_more_than_one_thousand_groups() -> None:
    facts = [
        _fact(run_id=f"run-{index}", execution_id=f"execution-{index}") for index in range(1001)
    ]

    with pytest.raises(ValueError, match="1000"):
        compute_cost_rollup(facts, ("run",))
