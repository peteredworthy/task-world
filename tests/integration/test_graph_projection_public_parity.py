import json
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api import create_app
from orchestrator.db import init_db
from tests.graph_fr17_fixture import create_graph_run, seed_less_used_readback_graph


FR17_GOLDEN_RUN_ID = "fr17-public-golden"
PUBLIC_VIEW_GOLDENS = (
    Path(__file__).parent.parent
    / "fixtures"
    / "graph_projection_migration"
    / "public_view_goldens.json"
)


@pytest.mark.asyncio
async def test_complete_fr17_public_surfaces_match_golden_through_sqlite() -> None:
    expected = json.loads(PUBLIC_VIEW_GOLDENS.read_text())
    app = create_app(db_path=":memory:", routine_dirs=[])
    await init_db(app.state.engine)
    try:
        await create_graph_run(app.state.session_factory, FR17_GOLDEN_RUN_ID)
        await seed_less_used_readback_graph(app.state.session_factory, FR17_GOLDEN_RUN_ID)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            actual = await _read_complete_fr17_surfaces(client)

        assert _normalize_volatile_run_transport_fields(actual) == expected["fr17_complete"]
    finally:
        await app.state.engine.dispose()


async def _read_complete_fr17_surfaces(client: AsyncClient) -> dict[str, Any]:
    run = FR17_GOLDEN_RUN_ID
    return {
        "run": await _get_json(client, f"/api/runs/{run}"),
        "graph": await _get_json(client, f"/api/runs/{run}/graph"),
        "events": await _get_json(client, f"/api/runs/{run}/graph/events?payload_mode=full"),
        "topology": await _get_json(client, f"/api/runs/{run}/graph/topology"),
        "scheduler": await _get_json(client, f"/api/runs/{run}/graph/scheduler"),
        "decisions": await _get_json(client, f"/api/runs/{run}/graph/decisions"),
        "patches": await _get_json(client, f"/api/runs/{run}/graph/patches"),
        "regions": await _get_json(client, f"/api/runs/{run}/graph/regions"),
        "final_blockers": await _get_json(client, f"/api/runs/{run}/graph/final-blockers"),
        "recovery_node": await _get_json(
            client, f"/api/runs/{run}/graph/nodes/recovery-1?payload_mode=full"
        ),
        "review_node": await _get_json(client, f"/api/runs/{run}/graph/nodes/review-1"),
    }


def _normalize_volatile_run_transport_fields(surfaces: dict[str, Any]) -> dict[str, Any]:
    """Stabilize run timestamps and generated DB identifiers after API shaping."""
    normalized = {**surfaces}
    run = {**surfaces["run"]}
    run["created_at"] = "<volatile-created-at>"
    run["updated_at"] = "<volatile-updated-at>"
    run["steps"] = [
        {
            **step,
            "id": "<volatile-step-id>",
            "tasks": [{**task, "id": "<volatile-task-id>"} for task in step["tasks"]],
        }
        for step in run["steps"]
    ]
    normalized["run"] = run
    return normalized


async def _get_json(client: AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200, response.text
    return response.json()
