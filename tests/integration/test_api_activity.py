"""Integration tests for the activity feed endpoint."""

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

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


async def _setup_active_run(client: AsyncClient) -> tuple[str, str]:
    """Create a run and start it, returning (run_id, task_id)."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    await client.post(f"/api/runs/{run_id}/start")
    return run_id, task_id


async def test_activity_empty_for_new_run(client: AsyncClient) -> None:
    """A freshly created (not started) run has no events."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    run_id = resp.json()["id"]

    resp = await client.get(f"/api/runs/{run_id}/activity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == run_id
    assert data["events"] == []
    assert data["has_more"] is False


async def test_activity_after_task_lifecycle(client: AsyncClient) -> None:
    """Starting a run and progressing a task produces the expected events."""
    run_id, task_id = await _setup_active_run(client)

    # Start task (pending -> building)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Update checklist and submit (building -> verifying)
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")

    resp = await client.get(f"/api/runs/{run_id}/activity")
    assert resp.status_code == 200
    data = resp.json()

    event_types = [e["event_type"] for e in data["events"]]
    assert "run_status_changed" in event_types
    assert "task_status_changed" in event_types
    assert data["has_more"] is False

    # Events should be ordered by id ascending
    ids = [e["id"] for e in data["events"]]
    assert ids == sorted(ids)


async def test_activity_pagination(client: AsyncClient) -> None:
    """Cursor pagination with limit returns correct subsets."""
    run_id, task_id = await _setup_active_run(client)

    # Generate more events
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")

    # Fetch with small limit
    resp = await client.get(f"/api/runs/{run_id}/activity?limit=2")
    assert resp.status_code == 200
    page1 = resp.json()
    assert len(page1["events"]) == 2
    assert page1["has_more"] is True

    # Fetch next page using cursor
    last_id = page1["events"][-1]["id"]
    resp = await client.get(f"/api/runs/{run_id}/activity?after={last_id}&limit=2")
    assert resp.status_code == 200
    page2 = resp.json()
    assert len(page2["events"]) >= 1

    # No overlap between pages
    page1_ids = {e["id"] for e in page1["events"]}
    page2_ids = {e["id"] for e in page2["events"]}
    assert page1_ids.isdisjoint(page2_ids)


async def test_activity_event_type_filter(client: AsyncClient) -> None:
    """Filtering by event_type returns only matching events."""
    run_id, task_id = await _setup_active_run(client)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Filter to only run_status_changed events
    resp = await client.get(f"/api/runs/{run_id}/activity?event_type=run_status_changed")
    assert resp.status_code == 200
    data = resp.json()
    assert all(e["event_type"] == "run_status_changed" for e in data["events"])
    assert len(data["events"]) >= 1


async def test_activity_enrichment(client: AsyncClient) -> None:
    """Task and step titles are populated in activity events."""
    run_id, task_id = await _setup_active_run(client)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    resp = await client.get(f"/api/runs/{run_id}/activity")
    data = resp.json()

    # Find a task_status_changed event — it should have task_title and step_title
    task_events = [e for e in data["events"] if e["event_type"] == "task_status_changed"]
    assert len(task_events) >= 1
    event = task_events[0]
    assert event["task_title"] is not None
    assert event["step_title"] is not None


async def test_activity_run_not_found(client: AsyncClient) -> None:
    """Activity for a non-existent run returns 404."""
    resp = await client.get("/api/runs/nonexistent/activity")
    assert resp.status_code == 404


# --- SSE Streaming Tests ---


async def test_sse_stream_endpoint_exists(client: AsyncClient) -> None:
    """The SSE stream endpoint returns text/event-stream."""
    run_id, _ = await _setup_active_run(client)

    # Use once=true for testing with ASGI transport
    async with client.stream("GET", f"/api/runs/{run_id}/activity/stream?once=true") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")


async def test_sse_stream_sends_events(client: AsyncClient) -> None:
    """SSE stream sends events as they occur."""
    run_id, _task_id = await _setup_active_run(client)

    # Use once=true to get all existing events
    events_received: list[dict[str, Any]] = []
    async with client.stream("GET", f"/api/runs/{run_id}/activity/stream?once=true") as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                event_data = json.loads(line[6:])  # Strip "data: " prefix
                events_received.append(event_data)

    # Should have received events from run start
    assert len(events_received) >= 1
    assert any(e["event_type"] == "run_status_changed" for e in events_received)


async def test_sse_stream_since_id_resumption(client: AsyncClient) -> None:
    """SSE stream resumes from since_id parameter."""
    run_id, task_id = await _setup_active_run(client)

    # Start task to generate more events
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Get events via REST to find a checkpoint
    resp = await client.get(f"/api/runs/{run_id}/activity?limit=2")
    data = resp.json()
    assert len(data["events"]) >= 2

    # Use the first event ID as checkpoint
    checkpoint_id = data["events"][0]["id"]

    events_received: list[dict[str, Any]] = []
    async with client.stream(
        "GET", f"/api/runs/{run_id}/activity/stream?since_id={checkpoint_id}&once=true"
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                event_data = json.loads(line[6:])
                events_received.append(event_data)

    # All received events should have ID > checkpoint_id
    assert len(events_received) >= 1
    assert all(e["id"] > checkpoint_id for e in events_received)


async def test_sse_stream_event_type_filter(client: AsyncClient) -> None:
    """SSE stream respects event_type filter."""
    run_id, task_id = await _setup_active_run(client)

    # Start task to generate events
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    events_received: list[dict[str, Any]] = []
    async with client.stream(
        "GET", f"/api/runs/{run_id}/activity/stream?event_type=task_status_changed&once=true"
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                event_data = json.loads(line[6:])
                events_received.append(event_data)

    # All received events should be task_status_changed
    assert len(events_received) >= 1
    assert all(e["event_type"] == "task_status_changed" for e in events_received)


async def test_sse_stream_enrichment(client: AsyncClient) -> None:
    """SSE stream events include task_title and step_title."""
    run_id, task_id = await _setup_active_run(client)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    events_received: list[dict[str, Any]] = []
    async with client.stream("GET", f"/api/runs/{run_id}/activity/stream?once=true") as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                event_data = json.loads(line[6:])
                events_received.append(event_data)

    # Find a task event
    task_events = [e for e in events_received if e["event_type"] == "task_status_changed"]
    assert len(task_events) >= 1

    # Task events should have enrichment
    event = task_events[0]
    assert event.get("task_title") is not None
    assert event.get("step_title") is not None


async def test_sse_stream_run_not_found(client: AsyncClient) -> None:
    """SSE stream for non-existent run returns 404."""
    # Validation now happens BEFORE streaming starts, so we should get immediate 404
    resp = await client.get("/api/runs/nonexistent/activity/stream?once=true")
    assert resp.status_code == 404


async def test_sse_stream_client_disconnect(client: AsyncClient) -> None:
    """SSE stream handles client disconnect gracefully."""
    run_id, _ = await _setup_active_run(client)

    # Read partial stream (simulate disconnect by breaking early)
    async with client.stream("GET", f"/api/runs/{run_id}/activity/stream?once=true") as response:
        count = 0
        async for _line in response.aiter_lines():
            count += 1
            if count >= 1:
                # Disconnect early
                break

    # Verify the run is still accessible (server didn't crash)
    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
