"""Integration smoke coverage for workflow transitions through the HTTP API."""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture(scope="module")
async def api_client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    signal_transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
        auth_disabled=True,
    )
    app.state.signal_transport = signal_transport
    await init_db(app.state.engine)
    asgi = ASGITransport(app=app)  # type: ignore[arg-type]
    drain = make_drain_fn(app, signal_transport)
    async with AsyncClient(transport=asgi, base_url="http://test", timeout=30.0) as client:
        yield client, drain
    await app.state.engine.dispose()


@pytest.fixture
async def api_client(api_client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    client, _ = api_client_and_drain
    return client


@pytest.fixture
async def drain(api_client_and_drain: tuple[AsyncClient, DrainFn]) -> DrainFn:
    _, drain_fn = api_client_and_drain
    return drain_fn


async def _create_run(
    client: AsyncClient,
    routine_id: str = "simple-routine",
    repo_name: str = "test-repo",
) -> dict[str, Any]:
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": routine_id,
            "repo_name": repo_name,
            "branch": "main",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _start_run(client: AsyncClient, run_id: str, drain: DrainFn) -> dict[str, Any]:
    response = await client.post(f"/api/runs/{run_id}/start")
    assert response.status_code == 202, response.text
    await drain(run_id)
    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.status_code == 200, get_resp.text
    return get_resp.json()


async def _start_task(client: AsyncClient, run_id: str, task_id: str) -> None:
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True


async def _mark_checklist_done(client: AsyncClient, run_id: str, task_id: str) -> None:
    response = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    assert response.status_code == 200, response.text


async def _submit_task(client: AsyncClient, run_id: str, task_id: str, drain: DrainFn) -> None:
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert response.status_code == 200, response.text
    await drain(run_id)


async def _grade_item(
    client: AsyncClient,
    run_id: str,
    task_id: str,
    grade: str,
    reason: str | None = None,
) -> None:
    body: dict[str, str] = {"grade": grade}
    if reason is not None:
        body["grade_reason"] = reason
    response = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json=body,
    )
    assert response.status_code == 200, response.text


async def _complete_verification(
    client: AsyncClient, run_id: str, task_id: str, drain: DrainFn
) -> None:
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert response.status_code == 200, response.text
    await drain(run_id)


async def _get_run(client: AsyncClient, run_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def _get_task(client: AsyncClient, run_id: str, task_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _first_task_id(run_data: dict[str, Any]) -> str:
    return run_data["steps"][0]["tasks"][0]["id"]


async def test_revision_flow_failed_grade_then_pass(
    api_client: AsyncClient, drain: DrainFn
) -> None:
    run_data = await _create_run(api_client, repo_name="workflow-smoke-revision")
    run_id = run_data["id"]
    run_data = await _start_run(api_client, run_id, drain)
    task_id = _first_task_id(run_data)

    await _start_task(api_client, run_id, task_id)
    await _mark_checklist_done(api_client, run_id, task_id)
    await _submit_task(api_client, run_id, task_id, drain)
    await _grade_item(api_client, run_id, task_id, grade="F", reason="Needs work")
    await _complete_verification(api_client, run_id, task_id, drain)

    task_data = await _get_task(api_client, run_id, task_id)
    assert task_data["status"] == "building"
    assert len(task_data["attempts"]) == 2
    assert task_data["attempts"][0]["outcome"] == "revision_needed"
    assert task_data["checklist"][0]["grade_reason"] == "Needs work"

    await _mark_checklist_done(api_client, run_id, task_id)
    await _submit_task(api_client, run_id, task_id, drain)
    await _grade_item(api_client, run_id, task_id, grade="A")
    await _complete_verification(api_client, run_id, task_id, drain)

    task_data = await _get_task(api_client, run_id, task_id)
    assert task_data["status"] == "completed"
    assert len(task_data["attempts"]) == 2
    assert task_data["attempts"][1]["outcome"] == "passed"


async def test_concurrent_task_operations(api_client: AsyncClient, drain: DrainFn) -> None:
    run_tasks: list[tuple[str, str]] = []
    for i in range(3):
        run_data = await _create_run(api_client, repo_name=f"workflow-smoke-concurrent-{i}")
        run_data = await _start_run(api_client, run_data["id"], drain)
        run_tasks.append((run_data["id"], _first_task_id(run_data)))

    await asyncio.gather(
        *[_start_task(api_client, run_id, task_id) for run_id, task_id in run_tasks]
    )
    await asyncio.gather(
        *[_mark_checklist_done(api_client, run_id, task_id) for run_id, task_id in run_tasks]
    )

    for run_id, task_id in run_tasks:
        await _submit_task(api_client, run_id, task_id, drain)

    await asyncio.gather(
        *[_grade_item(api_client, run_id, task_id, grade="A") for run_id, task_id in run_tasks]
    )

    for run_id, task_id in run_tasks:
        await _complete_verification(api_client, run_id, task_id, drain)

    for run_id, _ in run_tasks:
        run_data = await _get_run(api_client, run_id)
        assert run_data["status"] == "completed"
