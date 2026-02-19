"""Integration tests for run recovery API endpoint."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.db.connection import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


def _recover_test_routine() -> dict[str, object]:
    return {
        "id": "recover-test-routine",
        "name": "Recover Test Routine",
        "steps": [
            {
                "id": "S-01",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task 1",
                        "task_context": "Task 1 context",
                        "requirements": [{"id": "R1", "desc": "Req 1", "must": True}],
                        "retry": {"max_attempts": 1},
                    }
                ],
            },
            {
                "id": "S-02",
                "title": "Step 2",
                "tasks": [
                    {
                        "id": "T-02",
                        "title": "Task 2",
                        "task_context": "Task 2 context",
                        "requirements": [{"id": "R2", "desc": "Req 2", "must": True}],
                    }
                ],
            },
            {
                "id": "S-03",
                "title": "Step 3",
                "tasks": [
                    {
                        "id": "T-03",
                        "title": "Task 3",
                        "task_context": "Task 3 context",
                        "requirements": [{"id": "R3", "desc": "Req 3", "must": True}],
                    }
                ],
            },
        ],
    }


async def _create_recover_run(client: AsyncClient, repo_name: str) -> tuple[str, str, str, str]:
    response = await client.post(
        "/api/runs",
        json={
            "routine_embedded": _recover_test_routine(),
            "repo_name": repo_name,
            "branch": "main",
        },
    )
    assert response.status_code == 201
    run = response.json()
    return (
        run["id"],
        run["steps"][0]["tasks"][0]["id"],
        run["steps"][1]["tasks"][0]["id"],
        run["steps"][2]["tasks"][0]["id"],
    )


async def _fail_run_on_first_task(client: AsyncClient, run_id: str, task_1_id: str) -> None:
    await client.post(f"/api/runs/{run_id}/start")
    await client.post(f"/api/runs/{run_id}/tasks/{task_1_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_1_id}/checklist/R1",
        json={"status": "done"},
    )
    await client.post(f"/api/runs/{run_id}/tasks/{task_1_id}/submit")
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_1_id}/checklist/R1/grade",
        json={"grade": "D", "grade_reason": "force failure"},
    )
    await client.post(f"/api/runs/{run_id}/tasks/{task_1_id}/complete-verification")

    run_response = await client.get(f"/api/runs/{run_id}")
    assert run_response.status_code == 200
    assert run_response.json()["status"] == "failed"


async def test_recover_happy_path_sets_paused_and_rewinds(client: AsyncClient) -> None:
    run_id, task_1_id, task_2_id, task_3_id = await _create_recover_run(client, "recover-happy")
    await _fail_run_on_first_task(client, run_id, task_1_id)

    response = await client.post(
        f"/api/runs/{run_id}/recover",
        json={"target_task_id": task_2_id},
    )
    assert response.status_code == 200

    run_response = await client.get(f"/api/runs/{run_id}")
    assert run_response.status_code == 200
    run = run_response.json()

    assert run["status"] == "paused"
    assert run["pause_reason"] == "recovered"

    task_1 = run["steps"][0]["tasks"][0]
    task_2 = run["steps"][1]["tasks"][0]
    task_3 = run["steps"][2]["tasks"][0]

    assert task_1["id"] == task_1_id
    assert task_2["id"] == task_2_id
    assert task_3["id"] == task_3_id

    assert task_2["status"] == "building"
    assert task_3["status"] == "pending"

    task_2_detail = await client.get(f"/api/runs/{run_id}/tasks/{task_2_id}")
    task_3_detail = await client.get(f"/api/runs/{run_id}/tasks/{task_3_id}")
    assert task_2_detail.status_code == 200
    assert task_3_detail.status_code == 200

    assert task_2_detail.json()["checklist"][0]["status"] == "open"
    assert task_3_detail.json()["checklist"][0]["status"] == "open"


async def test_recover_preserve_checklist_true_keeps_downstream_items(client: AsyncClient) -> None:
    run_id, task_1_id, task_2_id, task_3_id = await _create_recover_run(client, "recover-preserve")

    # Pre-mark downstream checklist while run is ACTIVE; recover should retain this when requested.
    await client.post(f"/api/runs/{run_id}/start")
    preset_resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_3_id}/checklist/R3",
        json={"status": "done", "note": "keep me"},
    )
    assert preset_resp.status_code == 200

    await client.post(f"/api/runs/{run_id}/tasks/{task_1_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_1_id}/checklist/R1",
        json={"status": "done"},
    )
    await client.post(f"/api/runs/{run_id}/tasks/{task_1_id}/submit")
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_1_id}/checklist/R1/grade",
        json={"grade": "D", "grade_reason": "force failure"},
    )
    await client.post(f"/api/runs/{run_id}/tasks/{task_1_id}/complete-verification")

    failed_run = await client.get(f"/api/runs/{run_id}")
    assert failed_run.status_code == 200
    assert failed_run.json()["status"] == "failed"

    response = await client.post(
        f"/api/runs/{run_id}/recover",
        json={"target_task_id": task_2_id, "preserve_checklist": True},
    )
    assert response.status_code == 200

    task_3_detail = await client.get(f"/api/runs/{run_id}/tasks/{task_3_id}")
    assert task_3_detail.status_code == 200
    checklist_item = task_3_detail.json()["checklist"][0]
    assert checklist_item["status"] == "done"
    assert checklist_item["note"] == "keep me"


async def test_recover_non_failed_run_returns_409(client: AsyncClient) -> None:
    run_id, _task_1_id, task_2_id, _task_3_id = await _create_recover_run(
        client, "recover-conflict"
    )

    await client.post(f"/api/runs/{run_id}/start")

    response = await client.post(
        f"/api/runs/{run_id}/recover",
        json={"target_task_id": task_2_id},
    )
    assert response.status_code == 409


async def test_recover_task_id_from_other_run_returns_404(client: AsyncClient) -> None:
    failed_run_id, task_1_id, _task_2_id, _task_3_id = await _create_recover_run(
        client, "recover-run-a"
    )
    await _fail_run_on_first_task(client, failed_run_id, task_1_id)

    other_run_id, _other_task_1_id, other_task_2_id, _other_task_3_id = await _create_recover_run(
        client, "recover-run-b"
    )
    assert other_run_id != failed_run_id

    response = await client.post(
        f"/api/runs/{failed_run_id}/recover",
        json={"target_task_id": other_task_2_id},
    )
    assert response.status_code == 404
