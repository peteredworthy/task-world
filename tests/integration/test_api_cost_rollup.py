"""Integration tests for the graph-only cost rollup endpoint."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import EventV2Model, RunModel


async def _add_graph_usage(
    session: AsyncSession,
    *,
    run_id: str,
    status: str = "completed",
    runner_type: str = "cli_subprocess",
    timestamp: str = "2026-07-20T12:00:00+00:00",
    model: str = "gpt-5",
    input_tokens: int = 10,
) -> None:
    session.add(
        RunModel(
            id=run_id,
            repo_name=f"repo-{run_id}",
            status=status,
            runner_type=runner_type,
            created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
    )
    session.add(
        EventV2Model(
            aggregate_id=f"graph:{run_id}",
            event_type="node_usage_recorded",
            payload=json.dumps(
                {
                    "node_id": "node-a",
                    "node_kind": "builder",
                    "profile": "coder",
                    "execution_id": f"execution-{run_id}",
                    "usage_index": 0,
                    "usage_count": 1,
                    "usage_key": f"execution-{run_id}:0",
                    "model": model,
                    "gen_ai_usage_input_tokens": input_tokens,
                    "gen_ai_usage_output_tokens": 5,
                    "cost_usd": 0.25,
                    "latency_ms": 100,
                    "num_actions": 2,
                }
            ),
            timestamp=timestamp,
            version=1,
        )
    )


async def test_cost_rollup_reads_only_graph_usage_events_and_applies_sql_filters(
    _shared_app_fixture: tuple[object, object, object, object, object],
) -> None:
    client, _, _, _, app = _shared_app_fixture
    async with app.state.session_factory() as session:
        await _add_graph_usage(session, run_id="included")
        await _add_graph_usage(session, run_id="wrong-status", status="paused")
        await _add_graph_usage(session, run_id="wrong-runner", runner_type="codex_server")
        await _add_graph_usage(
            session,
            run_id="outside-time",
            timestamp="2026-07-22T00:00:00+00:00",
        )
        session.add(
            EventV2Model(
                aggregate_id="run:included",
                event_type="node_usage_recorded",
                payload=json.dumps({"not": "a graph fact"}),
                timestamp="2026-07-20T12:00:00+00:00",
                version=1,
            )
        )
        await session.commit()

    response = await client.get(
        "/api/runs/cost-rollup",
        params={
            "group_by": "run",
            "status": "completed",
            "runner_type": "cli_subprocess",
            "from": "2026-07-20T00:00:00+00:00",
            "to": "2026-07-22T00:00:00+00:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["rows"] == [
        {
            "dimensions": {"run": "included"},
            "execution_count": 1,
            "gen_ai_usage_input_tokens": 10,
            "gen_ai_usage_output_tokens": 5,
            "gen_ai_usage_cache_read_input_tokens": 0,
            "gen_ai_usage_cache_creation_input_tokens": 0,
            "gen_ai_usage_reasoning_output_tokens": 0,
            "latency_ms": 100,
            "num_actions": 2,
            "cost_usd": 0.25,
            "rate_missing_execution_count": 0,
            "rate_missing_input_tokens": 0,
            "rate_missing_output_tokens": 0,
            "has_rate_missing": False,
        }
    ]


@pytest.mark.parametrize(
    "status",
    ["draft", "active", "paused", "stopping", "completed", "failed", "cancelled"],
)
async def test_cost_rollup_accepts_every_run_status_literal(
    _shared_app_fixture: tuple[object, object, object, object, object], status: str
) -> None:
    client, _, _, _, _ = _shared_app_fixture
    response = await client.get("/api/runs/cost-rollup", params={"status": status})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "runner_type",
    ["openhands_local", "openhands_docker", "cli_subprocess", "codex_server"],
)
async def test_cost_rollup_accepts_every_selectable_runner_literal(
    _shared_app_fixture: tuple[object, object, object, object, object], runner_type: str
) -> None:
    client, _, _, _, _ = _shared_app_fixture
    response = await client.get("/api/runs/cost-rollup", params={"runner_type": runner_type})
    assert response.status_code == 200


async def test_cost_rollup_rejects_invalid_literals_and_reversed_time_range(
    _shared_app_fixture: tuple[object, object, object, object, object],
) -> None:
    client, _, _, _, _ = _shared_app_fixture

    invalid_status = await client.get("/api/runs/cost-rollup", params={"status": "waiting"})
    assert invalid_status.status_code == 422
    assert "completed" in invalid_status.text

    invalid_runner = await client.get("/api/runs/cost-rollup", params={"runner_type": "retired"})
    assert invalid_runner.status_code == 422
    assert "codex_server" in invalid_runner.text

    reversed_range = await client.get(
        "/api/runs/cost-rollup",
        params={"from": "2026-07-21T00:00:00+00:00", "to": "2026-07-20T00:00:00+00:00"},
    )
    assert reversed_range.status_code == 422
    assert "from" in reversed_range.text
