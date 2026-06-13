from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from orchestrator.config.models import RoutineConfig
from orchestrator.db import RunModel
from orchestrator.graph.clock import FakeClock, SequentialIdGenerator
from orchestrator.graph_runtime import seed_run
from tests.integration.conftest import cleanup_runs_for_repo
from tests.integration.signal_helpers import DrainFn


LEGACY_SUPER_PARENT_ROUTINE: dict[str, Any] = {
    "id": "super-parent",
    "name": "Super Parent",
    "planning": {"mode": "parent_child"},
    "steps": [
        {
            "id": "S-01",
            "title": "Parent planner",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Plan child work",
                    "task_context": "Create the planner chain for delegated work.",
                    "requirements": [{"id": "R1", "desc": "Plan child work"}],
                }
            ],
        }
    ],
}


@pytest.fixture
async def client_and_app(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Any, Any, Any],
    repo_name: str,
) -> tuple[AsyncClient, Any]:
    client, _drain, _repos_dir, _worktrees_dir, app = _shared_app_fixture
    yield client, app
    await cleanup_runs_for_repo(client, repo_name)


async def test_legacy_oversight_routes_are_gone(
    client_and_app: tuple[AsyncClient, Any],
) -> None:
    client, app = client_and_app

    assert (await client.get("/api/runs/parent/oversight")).status_code == 404
    assert (await client.patch("/api/runs/parent/oversight", json={})).status_code == 404
    assert (await client.post("/api/runs/parent/oversight/refresh")).status_code == 404
    assert (await client.get("/api/runs/parent/children")).status_code == 404
    assert (await client.post("/api/runs/parent/children", json={})).status_code == 404
    assert (await client.post("/api/runs/parent/children/child/accept")).status_code == 404
    assert (
        await client.post(
            "/api/runs/parent/children/child/resolve",
            json={"resolution": "abandon", "reason": "retired"},
        )
    ).status_code == 404


async def test_super_parent_routine_creates_graph_backed_run(
    client_and_app: tuple[AsyncClient, Any],
    repo_name: str,
) -> None:
    client, app = client_and_app

    response = await client.post(
        "/api/runs",
        json={
            "routine_embedded": LEGACY_SUPER_PARENT_ROUTINE,
            "repo_name": repo_name,
            "branch": "main",
            "execution_mode": "graph",
        },
    )

    assert response.status_code == 201
    body = response.json()
    await seed_run(
        app.state.session_factory,
        RoutineConfig.model_validate(LEGACY_SUPER_PARENT_ROUTINE),
        run_id=body["id"],
        clock=FakeClock(),
        id_gen=SequentialIdGenerator(),
    )
    fetched = await client.get(f"/api/runs/{body['id']}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["routine_id"] == "super-parent"
    assert body["is_graph_backed"] is True
    assert body["execution_mode"] == "graph"
    assert body["parent_run_id"] is None


async def test_archived_super_parent_run_loads_stored_facts_read_only(
    client_and_app: tuple[AsyncClient, Any],
    repo_name: str,
) -> None:
    client, app = client_and_app
    create_response = await client.post(
        "/api/runs",
        json={
            "routine_embedded": LEGACY_SUPER_PARENT_ROUTINE,
            "repo_name": repo_name,
            "branch": "main",
            "execution_mode": "graph",
        },
    )
    assert create_response.status_code == 201
    run_id = create_response.json()["id"]
    legacy_facts = {
        "schema_version": "super_parent.oversight.v1",
        "child_count": 1,
        "decisions": [{"action": "accept", "child_run_id": "child-1"}],
    }

    async with app.state.session_factory() as session:
        await session.execute(
            update(RunModel).where(RunModel.id == run_id).values(oversight_state=legacy_facts)
        )
        await session.commit()

    read_response = await client.get(f"/api/runs/{run_id}")

    assert read_response.status_code == 200
    assert read_response.json()["oversight_state"] == legacy_facts
