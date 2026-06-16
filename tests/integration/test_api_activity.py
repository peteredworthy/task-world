"""Integration tests for the activity feed endpoint."""

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import SqliteEventStore, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.workflow import AgentOutputEvent, InMemorySignalTransport
from tests.integration.conftest import cleanup_runs_for_repo
from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport_obj = InMemorySignalTransport()
    app.state.signal_transport = transport_obj
    drain = make_drain_fn(app, transport_obj)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


@pytest.fixture
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    return client_and_drain[0]


@pytest.fixture
async def client_app_and_drain() -> AsyncGenerator[tuple[AsyncClient, Any, DrainFn], None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport_obj = InMemorySignalTransport()
    app.state.signal_transport = transport_obj
    drain = make_drain_fn(app, transport_obj)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app, drain
    await app.state.engine.dispose()


async def _setup_active_run(client: AsyncClient, drain: DrainFn) -> tuple[str, str]:
    """Create a run and start it, returning (run_id, task_id)."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    await drain(run_id)
    return run_id, task_id


def _graph_event(
    run_id: str,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        causation_id="test",
        correlation_id=None,
        timestamp=datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
        payload=payload,
    )


async def _append_graph_events(
    app: Any,
    run_id: str,
    events: list[EventEnvelope],
) -> list[int]:
    async with app.state.session_factory() as session:
        stored = await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()
    return [event.position for event in stored]


async def test_activity_for_new_run_includes_run_created_event(client: AsyncClient) -> None:
    """A freshly created run exposes its events_v2 run_created event."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    run_id = resp.json()["id"]

    resp = await client.get(f"/api/runs/{run_id}/activity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == run_id
    event_types = [event["event_type"] for event in data["events"]]
    assert event_types[0] == "run_created"
    assert "step_created" in event_types
    assert "task_created" in event_types
    assert data["has_more"] is False


async def test_activity_after_task_lifecycle(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Starting a run and progressing a task produces the expected events."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, drain)

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
    assert "run_created" in event_types
    assert "task_status_changed" in event_types
    assert data["has_more"] is False

    # Events should be ordered by id ascending
    ids = [e["id"] for e in data["events"]]
    assert ids == sorted(ids)
    assert all(e["timestamp"].endswith("Z") for e in data["events"])


async def test_activity_pagination(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """Cursor pagination with limit returns correct subsets."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, drain)

    # Generate more events
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)

    # Fetch with small limit
    resp = await client.get(f"/api/runs/{run_id}/activity?limit=1")
    assert resp.status_code == 200
    page1 = resp.json()
    assert len(page1["events"]) == 1
    assert page1["has_more"] is True

    # Fetch next page using cursor
    last_id = page1["events"][-1]["id"]
    resp = await client.get(f"/api/runs/{run_id}/activity?after={last_id}&limit=1")
    assert resp.status_code == 200
    page2 = resp.json()
    assert len(page2["events"]) >= 1

    # No overlap between pages
    page1_ids = {e["id"] for e in page1["events"]}
    page2_ids = {e["id"] for e in page2["events"]}
    assert page1_ids.isdisjoint(page2_ids)


async def test_activity_event_type_filter(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Filtering by event_type returns only matching events."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, drain)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    # Filter to only task_status_changed events
    resp = await client.get(f"/api/runs/{run_id}/activity?event_type=task_status_changed")
    assert resp.status_code == 200
    data = resp.json()
    assert all(e["event_type"] == "task_status_changed" for e in data["events"])
    assert len(data["events"]) >= 1


async def test_activity_and_stream_read_agent_output_from_events_v2_only(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    repo_name: str,
) -> None:
    client, _drain, _repos_dir, _worktrees_dir, app = _shared_app_fixture
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": repo_name, "branch": "main"},
    )
    assert resp.status_code == 201
    run = resp.json()
    run_id = run["id"]
    task_id = run["steps"][0]["tasks"][0]["id"]

    async with app.state.session_factory() as session:
        store = SqliteEventStore(session)
        stored = await store.append(
            AgentOutputEvent(
                timestamp=datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
                run_id=run_id,
                event_type="agent_output",
                task_id=task_id,
                attempt_num=1,
                lines=["one", "two"],
                line_offset=0,
            )
        )
        await session.commit()

    agent_output_position = stored[0].position

    resp = await client.get(f"/api/runs/{run_id}/activity?event_type=agent_output")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_more"] is False
    assert len(data["events"]) == 1
    event = data["events"][0]
    assert event["id"] == agent_output_position
    assert event["event_type"] == "agent_output"
    assert event["payload"]["lines"] == ["one", "two"]
    assert event["payload"]["line_offset"] == 0

    events_received: list[dict[str, Any]] = []
    async with client.stream(
        "GET", f"/api/runs/{run_id}/activity/stream?event_type=agent_output&once=true"
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                events_received.append(json.loads(line[6:]))

    assert [event["id"] for event in events_received] == [agent_output_position]
    assert events_received[0]["payload"]["lines"] == ["one", "two"]

    await cleanup_runs_for_repo(client, repo_name)


async def test_activity_enrichment(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Task and step titles are populated in activity events."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, drain)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    resp = await client.get(f"/api/runs/{run_id}/activity")
    data = resp.json()

    # Find a task_status_changed event — it should have task_title and step_title
    task_events = [e for e in data["events"] if e["event_type"] == "task_status_changed"]
    assert len(task_events) >= 1
    event = task_events[0]
    assert event["task_title"] is not None
    assert event["step_title"] is not None


async def test_activity_includes_compact_graph_patch_decision_summaries(
    client_app_and_drain: tuple[AsyncClient, Any, DrainFn],
) -> None:
    client, app, _drain = client_app_and_drain
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    run_id = resp.json()["id"]

    await _append_graph_events(
        app,
        run_id,
        [
            _graph_event(
                run_id,
                "event-patch-accepted",
                "graph_patch_accepted",
                {
                    "patch_id": "patch-1",
                    "base_graph_position": 4,
                    "actor_role": "planner",
                    "proposed_by_node_id": "planner-1",
                    "successor_planner_node_ids": ["planner-2"],
                },
            ),
            _graph_event(
                run_id,
                "event-patch-rejected",
                "graph_patch_rejected",
                {
                    "patch_id": "patch-2",
                    "actor_role": "planner",
                    "proposed_by_node_id": "planner-1",
                    "reason": "read_set_changed",
                    "read_set_diff": {"changed": ["node-a"]},
                },
            ),
        ],
    )

    activity = (await client.get(f"/api/runs/{run_id}/activity")).json()["events"]
    accepted = next(event for event in activity if event["event_type"] == "graph_patch_accepted")
    rejected = next(event for event in activity if event["event_type"] == "graph_patch_rejected")

    assert accepted["payload"] == {
        "summary": (
            "Graph patch accepted: patch=patch-1; proposer=planner-1; "
            "actor=planner; successor_planners=planner-2"
        ),
        "decision": "accepted",
        "patch_id": "patch-1",
        "proposed_by_node_id": "planner-1",
        "actor_role": "planner",
        "base_graph_position": 4,
        "successor_planner_node_ids": ["planner-2"],
    }
    assert rejected["payload"]["summary"] == (
        "Graph patch rejected: patch=patch-2; proposer=planner-1; "
        "actor=planner; reason=read_set_changed"
    )
    assert rejected["payload"]["reason"] == "read_set_changed"
    assert rejected["payload"]["read_set_diff"] == {"changed": ["node-a"]}


async def test_activity_includes_graph_rejected_command_verifier_and_blocker_facts(
    client_app_and_drain: tuple[AsyncClient, Any, DrainFn],
) -> None:
    client, app, _drain = client_app_and_drain
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    run_id = resp.json()["id"]

    await _append_graph_events(
        app,
        run_id,
        [
            _graph_event(
                run_id,
                "event-malformed-patch",
                "command_rejected",
                {
                    "command_type": "submit_patch",
                    "reason": "malformed patch: missing patch_id",
                },
            ),
            _graph_event(
                run_id,
                "event-verification-failed",
                "verification_failed",
                {
                    "node_id": "verifier-1",
                    "verifier_node_id": "verifier-1",
                    "candidate_id": "candidate-1",
                    "task_region_id": "step-1/task-1",
                    "record_id": "verification-1",
                    "evidence": "raw verifier narrative is not copied",
                    "value": {
                        "grades": [
                            {
                                "requirement_id": "req-1",
                                "grade": "C",
                                "reason": "missing regression coverage",
                            }
                        ]
                    },
                },
            ),
            _graph_event(
                run_id,
                "event-node-deferred",
                "node_deferred",
                {"node_id": "verifier-2", "reason": "missing_required_input:candidate"},
            ),
            _graph_event(
                run_id,
                "event-review-blocker",
                "node_created",
                {
                    "node_id": "review-final",
                    "kind": "review",
                    "state": "blocked",
                    "blocker": "unresolved gap evidence",
                },
            ),
            _graph_event(
                run_id,
                "event-worker-node",
                "node_created",
                {
                    "node_id": "worker-raw",
                    "kind": "worker",
                    "state": "planned",
                    "prompt": "raw prompt transcript must not appear",
                },
            ),
        ],
    )

    activity = (await client.get(f"/api/runs/{run_id}/activity")).json()["events"]
    command = next(event for event in activity if event["event_type"] == "command_rejected")
    verification = next(event for event in activity if event["event_type"] == "verification_failed")
    blocker = next(event for event in activity if event["event_type"] == "node_deferred")
    invariant = next(
        event
        for event in activity
        if event["event_type"] == "node_created" and event["payload"]["node_id"] == "review-final"
    )

    assert command["payload"] == {
        "summary": (
            "Graph command rejected: command=submit_patch; reason=malformed patch: missing patch_id"
        ),
        "decision": "rejected",
        "command_type": "submit_patch",
        "reason": "malformed patch: missing patch_id",
    }
    assert verification["payload"]["summary"] == (
        "Graph verifier failed: verifier=verifier-1; candidate=candidate-1; "
        "task=step-1/task-1; grades=req-1=C"
    )
    assert verification["payload"]["grades"] == [
        {
            "requirement_id": "req-1",
            "grade": "C",
            "reason": "missing regression coverage",
        }
    ]
    assert "evidence" not in verification["payload"]
    assert blocker["payload"] == {
        "summary": "Graph node blocked: node=verifier-2; reason=missing_required_input:candidate",
        "node_id": "verifier-2",
        "reason": "missing_required_input:candidate",
    }
    assert invariant["payload"] == {
        "summary": "Graph final invariant blocked: node=review-final; reason=unresolved gap evidence",
        "node_id": "review-final",
        "kind": "review",
        "state": "blocked",
        "reason": "unresolved gap evidence",
    }
    assert all(event["payload"].get("node_id") != "worker-raw" for event in activity)


async def test_graph_activity_summaries_preserve_filtering_and_pagination(
    client_app_and_drain: tuple[AsyncClient, Any, DrainFn],
) -> None:
    client, app, _drain = client_app_and_drain
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    run_id = resp.json()["id"]

    await _append_graph_events(
        app,
        run_id,
        [
            _graph_event(
                run_id,
                "event-patch-accepted",
                "graph_patch_accepted",
                {
                    "patch_id": "patch-1",
                    "actor_role": "planner",
                    "proposed_by_node_id": "planner-1",
                    "successor_planner_node_ids": [],
                },
            ),
            _graph_event(
                run_id,
                "event-verification-passed",
                "verification_passed",
                {
                    "verifier_node_id": "verifier-1",
                    "candidate_id": "candidate-1",
                    "task_region_id": "step-1/task-1",
                    "value": {"grades": [{"requirement_id": "req-1", "grade": "A"}]},
                },
            ),
        ],
    )

    filtered = (
        await client.get(f"/api/runs/{run_id}/activity?event_type=verification_passed")
    ).json()
    assert [event["event_type"] for event in filtered["events"]] == ["verification_passed"]
    assert filtered["events"][0]["payload"]["verdict"] == "passed"

    page_1 = (await client.get(f"/api/runs/{run_id}/activity?limit=1")).json()
    page_2 = (
        await client.get(f"/api/runs/{run_id}/activity?after={page_1['events'][0]['id']}&limit=100")
    ).json()

    assert page_1["has_more"] is True
    assert {event["id"] for event in page_1["events"]}.isdisjoint(
        {event["id"] for event in page_2["events"]}
    )
    assert any(event["event_type"] == "graph_patch_accepted" for event in page_2["events"])
    assert any(event["event_type"] == "verification_passed" for event in page_2["events"])


async def test_activity_run_not_found(client: AsyncClient) -> None:
    """Activity for a non-existent run returns 404."""
    resp = await client.get("/api/runs/nonexistent/activity")
    assert resp.status_code == 404


# --- SSE Streaming Tests ---


async def test_sse_stream_endpoint_exists(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """The SSE stream endpoint returns text/event-stream."""
    client, drain = client_and_drain
    run_id, _ = await _setup_active_run(client, drain)

    # Use once=true for testing with ASGI transport
    async with client.stream("GET", f"/api/runs/{run_id}/activity/stream?once=true") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")


async def test_sse_stream_sends_events(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """SSE stream sends events as they occur."""
    client, drain = client_and_drain
    run_id, _task_id = await _setup_active_run(client, drain)

    # Use once=true to get all existing events
    events_received: list[dict[str, Any]] = []
    async with client.stream("GET", f"/api/runs/{run_id}/activity/stream?once=true") as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                event_data = json.loads(line[6:])  # Strip "data: " prefix
                events_received.append(event_data)

    # Should have received events from run start
    assert len(events_received) >= 1
    assert any(e["event_type"] == "run_created" for e in events_received)
    assert all(e["timestamp"].endswith("Z") for e in events_received)


async def test_sse_stream_since_id_resumption(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """SSE stream resumes from since_id parameter."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, drain)

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


async def test_sse_stream_event_type_filter(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """SSE stream respects event_type filter."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, drain)

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


async def test_sse_stream_enrichment(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """SSE stream events include task_title and step_title."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_active_run(client, drain)
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


async def test_sse_stream_client_disconnect(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """SSE stream handles client disconnect gracefully."""
    client, drain = client_and_drain
    run_id, _ = await _setup_active_run(client, drain)

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
