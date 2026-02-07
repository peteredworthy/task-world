"""Integration tests for clarification API endpoints."""

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


async def _setup_building_task(client: AsyncClient) -> tuple[str, str]:
    """Create a run, start it, and start building a task. Returns (run_id, task_id)."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "project_id": "proj-1"},
    )
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    await client.post(f"/api/runs/{run_id}/start")
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    return run_id, task_id


async def test_create_clarification(client: AsyncClient) -> None:
    """Test creating a clarification request."""
    run_id, task_id = await _setup_building_task(client)

    # Create clarification request
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Should we use TypeScript or JavaScript?",
                    "context": "We need to decide on the language for the frontend",
                    "options": ["TypeScript", "JavaScript", "Both"],
                },
                {
                    "id": "q2",
                    "question": "Which CSS framework?",
                    "context": "Choose a styling approach",
                    "options": ["Tailwind", "Bootstrap", "Vanilla CSS"],
                },
            ]
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == run_id
    assert data["task_id"] == task_id
    assert data["attempt_num"] == 1
    assert len(data["questions"]) == 2
    assert data["questions"][0]["id"] == "q1"
    assert data["questions"][0]["question"] == "Should we use TypeScript or JavaScript?"
    assert data["questions"][1]["id"] == "q2"
    assert data["responded_at"] is None

    # Verify task is now in PENDING_USER_ACTION state
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.status_code == 200
    assert task_resp.json()["status"] == "pending_user_action"


async def test_get_pending_clarification(client: AsyncClient) -> None:
    """Test retrieving a pending clarification request."""
    run_id, task_id = await _setup_building_task(client)

    # No pending clarification initially
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/clarifications/pending")
    assert resp.status_code == 200
    assert resp.json() is None

    # Create a clarification
    await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Test question?",
                    "context": "Test context",
                    "options": ["Yes", "No"],
                }
            ]
        },
    )

    # Now should return the pending clarification
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/clarifications/pending")
    assert resp.status_code == 200
    data = resp.json()
    assert data is not None
    assert data["task_id"] == task_id
    assert len(data["questions"]) == 1


async def test_respond_to_clarification(client: AsyncClient) -> None:
    """Test responding to a clarification request."""
    run_id, task_id = await _setup_building_task(client)

    # Create a clarification
    create_resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Should we use TypeScript?",
                    "context": "Language choice",
                    "options": ["Yes", "No"],
                },
                {
                    "id": "q2",
                    "question": "Which framework?",
                    "context": "Framework choice",
                    "options": ["React", "Vue", "Svelte"],
                },
            ]
        },
    )
    request_id = create_resp.json()["id"]

    # Submit answers
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications/{request_id}/respond",
        json={
            "answers": [
                {
                    "question_id": "q1",
                    "selected_option": "Yes",
                },
                {
                    "question_id": "q2",
                    "free_text": "I prefer React for this project",
                },
            ]
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["new_status"] == "building"

    # Verify task is back to building
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.status_code == 200
    assert task_resp.json()["status"] == "building"

    # Verify no pending clarification anymore
    pending_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/clarifications/pending")
    assert pending_resp.json() is None


async def test_get_pending_actions_empty(client: AsyncClient) -> None:
    """Test getting pending actions when there are none."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "project_id": "proj-1"},
    )
    run_id = resp.json()["id"]

    resp = await client.get(f"/api/runs/{run_id}/pending-actions")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_pending_actions_with_clarification(client: AsyncClient) -> None:
    """Test getting pending actions when there's a clarification."""
    run_id, task_id = await _setup_building_task(client)

    # Create a clarification
    await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Test question?",
                    "context": "Test context",
                    "options": ["Yes", "No"],
                }
            ]
        },
    )

    # Get pending actions
    resp = await client.get(f"/api/runs/{run_id}/pending-actions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["task_id"] == task_id
    assert data[0]["action_type"] == "clarification"
    assert data[0]["clarification_request"] is not None
    assert len(data[0]["clarification_request"]["questions"]) == 1
    assert data[0]["clarification_request"]["questions"][0]["question"] == "Test question?"


async def test_respond_to_clarification_invalid_request_id(
    client: AsyncClient,
) -> None:
    """Test responding to a non-existent clarification request."""
    run_id, task_id = await _setup_building_task(client)

    # Create a clarification first
    await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Test?",
                    "context": "Context",
                    "options": ["Yes", "No"],
                }
            ]
        },
    )

    # Try to respond with invalid request_id
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications/invalid-id/respond",
        json={
            "answers": [
                {
                    "question_id": "q1",
                    "selected_option": "Yes",
                }
            ]
        },
    )

    assert resp.status_code == 404


async def test_create_clarification_invalid_task(client: AsyncClient) -> None:
    """Test creating a clarification for a non-existent task."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "project_id": "proj-1"},
    )
    run_id = resp.json()["id"]

    resp = await client.post(
        f"/api/runs/{run_id}/tasks/invalid-task-id/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Test?",
                    "context": "Context",
                    "options": ["Yes", "No"],
                }
            ]
        },
    )

    assert resp.status_code == 404
