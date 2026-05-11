"""Integration tests for MCP SSE transport mounted in FastAPI.

Verifies that the MCP server is accessible via the SSE transport
at /mcp/sse and /mcp/messages/ when mounted in the FastAPI app.
Also verifies that MCP tool dispatch through _SessionPerCallHandler
shares the SubmitEventRegistry and changes database state.
"""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport
from orchestrator.workflow.service import SubmitEventRegistry

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
    signal_transport = InMemorySignalTransport()
    _app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    _app.state.signal_transport = signal_transport
    await init_db(_app.state.engine)
    yield _app
    await _app.state.engine.dispose()


@pytest.fixture
async def drain(app: FastAPI) -> DrainFn:
    return make_drain_fn(app, app.state.signal_transport)


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    # Use localhost:8000 so MCP SDK's Host header validation passes.
    # FastMCP auto-enables DNS rebinding protection with allowed_hosts=["localhost:*"].
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        yield c


async def test_mcp_sse_endpoint_exists(client: AsyncClient) -> None:
    """The /mcp/sse endpoint responds (SSE transport is mounted)."""
    # SSE endpoint should be reachable. It returns a streaming response,
    # so we use a short timeout and just verify it doesn't 404.
    # The SSE endpoint streams events, so we can't easily get a full response,
    # but we can verify the route exists by checking it doesn't return 404.
    import anyio

    with anyio.move_on_after(0.2):
        async with client.stream("GET", "/mcp/sse") as response:
            # The SSE endpoint should return 200 with text/event-stream
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")


async def test_mcp_messages_endpoint_exists(client: AsyncClient) -> None:
    """The /mcp/messages/ endpoint responds to POST (even if invalid).

    A POST without a valid session should return an error, but not 404.
    """
    response = await client.post("/mcp/messages/", content=b"{}")
    # Should not be 404 (route exists), likely 400 or 500 for invalid request
    assert response.status_code != 404


async def test_scoped_mcp_sse_endpoint_exists_with_encoded_commas(
    app: FastAPI,
) -> None:
    """Scoped MCP SSE accepts comma-separated tool names encoded by clients."""
    import anyio

    scoped_path = "/mcp-scoped/orchestrator_get_requirements%2Corchestrator_submit/sse"
    sent_messages: list[dict[str, object]] = []
    endpoint_seen = anyio.Event()

    async def receive() -> dict[str, object]:
        await endpoint_seen.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)
        body = message.get("body")
        if isinstance(body, bytes) and b"data: " in body:
            endpoint_seen.set()

    with anyio.fail_after(1):
        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": scoped_path,
                "raw_path": scoped_path.encode(),
                "root_path": "",
                "query_string": b"",
                "headers": [(b"host", b"localhost:8000")],
                "client": ("127.0.0.1", 12345),
                "server": ("localhost", 8000),
            },
            receive,
            send,
        )

    expected_prefix = (
        "/mcp-scoped/orchestrator_get_requirements%2Corchestrator_submit/messages/?session_id="
    )
    response_start = next(
        message for message in sent_messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in sent_messages
        if message["type"] == "http.response.body"
    )
    data_line = next(
        line.removeprefix("data: ")
        for line in response_body.decode("utf-8").splitlines()
        if line.startswith("data: ")
    )
    assert response_start["status"] == 200
    assert data_line is not None
    assert data_line.startswith(expected_prefix)
    assert data_line.count("/mcp-scoped/") == 1


async def test_scoped_mcp_messages_endpoint_stays_under_scope(
    client: AsyncClient,
) -> None:
    """Scoped MCP message POSTs are handled under /mcp-scoped, not redirected away."""
    response = await client.post(
        "/mcp-scoped/"
        "orchestrator_get_requirements%2Corchestrator_submit"
        "/messages/?session_id=00000000000000000000000000000000",
        content=b"{}",
    )

    assert response.status_code != 307
    assert response.headers.get("location") is None


async def test_health_still_works_with_mcp_mounted(client: AsyncClient) -> None:
    """Health endpoint still works after MCP mount."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_api_runs_still_works_with_mcp_mounted(client: AsyncClient) -> None:
    """Regular API endpoints still work after MCP mount."""
    response = await client.get("/api/runs")
    assert response.status_code == 200


# --- MCP tool dispatch tests ---


async def _setup_building_task(client: AsyncClient, drain: DrainFn) -> tuple[str, str]:
    """Create a run with a building task via the REST API, returning (run_id, task_id)."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    await drain(run_id)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    return run_id, task_id


async def test_mcp_handler_submit_fires_registry_event(
    app: FastAPI,
    client: AsyncClient,
    drain: DrainFn,
) -> None:
    """_SessionPerCallHandler creates services sharing the SubmitEventRegistry.

    When orchestrator_submit is called through the MCP handler, the resulting
    WorkflowService shares the app-level SubmitEventRegistry.  This means a
    UserManagedAgent waiting on that registry will be woken up.
    """
    from orchestrator.api.app import _SessionPerCallHandler  # pyright: ignore[reportPrivateUsage]

    run_id, task_id = await _setup_building_task(client, drain)

    # Register an event on the shared registry (simulating UserManagedAgent)
    registry: SubmitEventRegistry = app.state.submit_event_registry
    event = registry.register(task_id)
    assert not event.is_set()

    # Call submit through the MCP session-per-call handler
    handler = _SessionPerCallHandler(app)
    result = await handler.handle(
        "orchestrator_submit",
        {"run_id": run_id, "task_id": task_id},
    )

    assert result["success"] is True
    assert result["new_status"] == "verifying"
    # The handler's service shared the registry, so the event fires
    assert event.is_set()

    # Clean up
    registry.unregister(task_id)


async def test_mcp_handler_updates_database_state(
    app: FastAPI,
    client: AsyncClient,
    drain: DrainFn,
) -> None:
    """MCP tool dispatch through _SessionPerCallHandler persists state to the DB.

    Verifies the full path: _SessionPerCallHandler → fresh DB session →
    WorkflowService → database commit → state visible via REST API.
    """
    from orchestrator.api.app import _SessionPerCallHandler  # pyright: ignore[reportPrivateUsage]

    # Create a run via REST API
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    await drain(run_id)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Update checklist via MCP handler (not REST API)
    handler = _SessionPerCallHandler(app)
    result = await handler.handle(
        "orchestrator_update_checklist",
        {
            "run_id": run_id,
            "task_id": task_id,
            "req_id": "R1",
            "status": "done",
            "note": "Updated via MCP handler",
        },
    )
    assert result["status"] == "done"

    # Verify the update is visible through the REST API (different DB session)
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    checklist = resp.json()["checklist"]
    assert checklist[0]["status"] == "done"
    assert checklist[0]["note"] == "Updated via MCP handler"
