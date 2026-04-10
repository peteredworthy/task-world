"""Integration tests for clarification API endpoints."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture(scope="module")
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    signal_transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    app.state.signal_transport = signal_transport
    await init_db(app.state.engine)
    asgi = ASGITransport(app=app)  # type: ignore[arg-type]
    drain = make_drain_fn(app, signal_transport)
    async with AsyncClient(transport=asgi, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


@pytest.fixture(scope="module")
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    c, _ = client_and_drain
    return c


async def _setup_building_task(
    client: AsyncClient, drain: DrainFn, routine_id: str = "simple-routine"
) -> tuple[str, str]:
    """Create a run, start it, and start building a task. Returns (run_id, task_id)."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": routine_id, "repo_name": "proj-1", "branch": "main"},
    )
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    return run_id, task_id


async def test_create_clarification(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    """Test creating a clarification request."""
    run_id, task_id = await _setup_building_task(client, drain)

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


async def test_get_pending_clarification(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    """Test retrieving a pending clarification request."""
    run_id, task_id = await _setup_building_task(client, drain)

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


async def test_respond_to_clarification(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    """Test responding to a clarification request."""
    run_id, task_id = await _setup_building_task(client, drain)

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


async def test_get_pending_actions_empty(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    """Test getting pending actions when there are none."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    run_id = resp.json()["id"]

    resp = await client.get(f"/api/runs/{run_id}/pending-actions")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_pending_actions_with_clarification(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    """Test getting pending actions when there's a clarification."""
    run_id, task_id = await _setup_building_task(client, drain)

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
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Test responding to a non-existent clarification request."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_building_task(client, drain)

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


async def test_create_clarification_invalid_task(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    """Test creating a clarification for a non-existent task."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
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


async def test_create_clarification_free_text_type(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    """Create a clarification with question_type='free_text'; assert stored question has correct type and no options."""
    run_id, task_id = await _setup_building_task(client, drain)

    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Describe your requirements in detail",
                    "context": "We need detailed requirements",
                    "options": [],
                    "question_type": "free_text",
                }
            ]
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["questions"]) == 1
    q = data["questions"][0]
    assert q["question_type"] == "free_text"
    assert q["options"] == []


async def test_create_clarification_multi_select_empty_options_returns_422(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Create a clarification with question_type='multi_select' and empty options; assert 422 response."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_building_task(client, drain)

    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Pick multiple",
                    "context": "Context",
                    "options": [],
                    "question_type": "multi_select",
                }
            ]
        },
    )

    assert resp.status_code == 422


async def test_respond_with_selected_options(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    """Respond with selected_options=['A', 'B']; assert task transitions to BUILDING."""
    run_id, task_id = await _setup_building_task(client, drain)

    # Create a multi_select clarification
    create_resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Which frameworks do you want?",
                    "context": "Select all that apply",
                    "options": ["A", "B", "C"],
                    "question_type": "multi_select",
                }
            ]
        },
    )
    assert create_resp.status_code == 200
    request_id = create_resp.json()["id"]

    # Respond with selected_options
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications/{request_id}/respond",
        json={
            "answers": [
                {
                    "question_id": "q1",
                    "selected_options": ["A", "B"],
                }
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


async def test_respond_with_skipped_true(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    client, drain = client_and_drain
    """Respond with skipped=True and skip_reason; assert task transitions back to BUILDING."""
    run_id, task_id = await _setup_building_task(client, drain)

    # Create a clarification
    create_resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Optional preference?",
                    "context": "This can be skipped",
                    "options": ["Yes", "No"],
                    "required": False,
                }
            ]
        },
    )
    assert create_resp.status_code == 200
    request_id = create_resp.json()["id"]

    # Respond with skipped=True
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications/{request_id}/respond",
        json={
            "answers": [],
            "skipped": True,
            "skip_reason": "Not needed",
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


async def test_respond_with_skipped_true_includes_skip_message_in_builder_prompt(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Respond with skipped=True; task prompt includes declined-to-answer context."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_building_task(
        client, drain, routine_id="routine-with-clarifications"
    )

    create_resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Optional preference?",
                    "context": "This can be skipped",
                    "options": ["Yes", "No"],
                    "required": False,
                }
            ]
        },
    )
    assert create_resp.status_code == 200
    request_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications/{request_id}/respond",
        json={
            "answers": [
                {
                    "question_id": "q1",
                    "skipped": True,
                    "skip_reason": "Too vague",
                }
            ],
            "skipped": True,
            "skip_reason": "Too vague",
        },
    )
    assert resp.status_code == 200

    prompt_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert prompt_resp.status_code == 200
    user_prompt = prompt_resp.json()["user"]
    assert "declined to answer" in user_prompt
    assert "Too vague" in user_prompt


# --- GET .../clarifications history endpoint tests ---


async def test_get_clarification_history_empty(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    """GET .../clarifications returns empty list when no rounds exist."""
    run_id, task_id = await _setup_building_task(client, drain)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/clarifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"items": []}


async def test_get_clarification_history_with_completed_round(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    """Complete a clarification round; GET .../clarifications returns 1 item with non-null response."""
    run_id, task_id = await _setup_building_task(client, drain)

    # Create a clarification
    create_resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Which language?",
                    "context": "Language choice",
                    "options": ["TypeScript", "JavaScript"],
                }
            ]
        },
    )
    assert create_resp.status_code == 200
    request_id = create_resp.json()["id"]

    # Respond to complete the round
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications/{request_id}/respond",
        json={
            "answers": [
                {
                    "question_id": "q1",
                    "selected_option": "TypeScript",
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Fetch history
    history_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/clarifications")
    assert history_resp.status_code == 200
    data = history_resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["request"]["id"] == request_id
    assert item["response"] is not None
    assert len(item["response"]["answers"]) == 1
    assert item["response"]["answers"][0]["question_id"] == "q1"
    assert item["response"]["answers"][0]["selected_option"] == "TypeScript"


async def test_get_clarification_history_with_pending_round(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    """Submit a pending clarification; GET .../clarifications returns item with response=null."""
    run_id, task_id = await _setup_building_task(client, drain)

    # Create a clarification but don't respond
    create_resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Which CSS framework?",
                    "context": "Styling choice",
                    "options": ["Tailwind", "Bootstrap"],
                }
            ]
        },
    )
    assert create_resp.status_code == 200
    request_id = create_resp.json()["id"]

    # Fetch history - pending item should appear with response=null
    history_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/clarifications")
    assert history_resp.status_code == 200
    data = history_resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["request"]["id"] == request_id
    assert item["response"] is None


async def test_get_clarification_history_nonexistent_run_returns_404(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    """GET .../clarifications with nonexistent run_id returns 404."""
    resp = await client.get("/api/runs/nonexistent-run/tasks/some-task/clarifications")
    assert resp.status_code == 404


async def test_get_clarification_history_nonexistent_task_returns_404(
    client: AsyncClient,
) -> None:
    """GET .../clarifications with nonexistent task_id returns 404."""
    run_resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert run_resp.status_code == 201
    run_id = run_resp.json()["id"]

    resp = await client.get(f"/api/runs/{run_id}/tasks/nonexistent-task/clarifications")
    assert resp.status_code == 404


async def test_get_clarification_history_multiple_rounds(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    client, drain = client_and_drain
    """History returns multiple rounds in ascending creation order."""
    run_id, task_id = await _setup_building_task(client, drain)

    # First round: create and complete
    create1 = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "First question?",
                    "context": "First context",
                    "options": ["A", "B"],
                }
            ]
        },
    )
    assert create1.status_code == 200
    request1_id = create1.json()["id"]

    resp1 = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications/{request1_id}/respond",
        json={"answers": [{"question_id": "q1", "selected_option": "A"}]},
    )
    assert resp1.status_code == 200

    # Start building again for second round
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Second round: create but leave pending
    create2 = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q2",
                    "question": "Second question?",
                    "context": "Second context",
                    "options": ["X", "Y"],
                }
            ]
        },
    )
    assert create2.status_code == 200
    request2_id = create2.json()["id"]

    # Fetch history
    history_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/clarifications")
    assert history_resp.status_code == 200
    data = history_resp.json()
    assert len(data["items"]) == 2

    # First item should be the completed round
    assert data["items"][0]["request"]["id"] == request1_id
    assert data["items"][0]["response"] is not None

    # Second item should be pending
    assert data["items"][1]["request"]["id"] == request2_id
    assert data["items"][1]["response"] is None


async def test_get_clarification_history_skipped_answer_response(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Respond with individual answer skipped=True; GET history shows response with skipped answer."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_building_task(client, drain)

    # Create a clarification
    create_resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
        json={
            "questions": [
                {
                    "id": "q1",
                    "question": "Optional question?",
                    "context": "Can be skipped",
                    "options": ["Yes", "No"],
                    "required": False,
                }
            ]
        },
    )
    assert create_resp.status_code == 200
    request_id = create_resp.json()["id"]

    # Respond with individual answer skipped
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/clarifications/{request_id}/respond",
        json={
            "answers": [
                {
                    "question_id": "q1",
                    "skipped": True,
                    "skip_reason": "Not relevant",
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # History shows the skipped answer in the response
    history_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/clarifications")
    assert history_resp.status_code == 200
    data = history_resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["response"] is not None
    assert item["response"]["answers"][0]["skipped"] is True
    assert item["response"]["answers"][0]["skip_reason"] == "Not relevant"
