"""Integration tests for the MCP layer: server, SSE transport, and tool handlers."""

import json
import os
import shutil
import subprocess
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api import OrchestratorMCPServer, ToolHandler
from orchestrator.api.app import create_app
from orchestrator.config import ChecklistStatus, Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow import InMemorySignalTransport
from orchestrator.workflow.service import SubmitEventRegistry, WorkflowService

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


# ---------------------------------------------------------------------------
# Shared low-level fixtures (session, service)
# ---------------------------------------------------------------------------


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def service(session: AsyncSession) -> WorkflowService:
    return WorkflowService(session)


# ---------------------------------------------------------------------------
# MCP Server fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server(service: WorkflowService) -> OrchestratorMCPServer:
    return OrchestratorMCPServer(service)


# ---------------------------------------------------------------------------
# Tool handler fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler(service: WorkflowService) -> ToolHandler:
    return ToolHandler(service)


@pytest.fixture
def repos_dir(tmp_path: Path) -> Path:
    """Create a repos directory for repo tool tests."""
    repos = tmp_path / "repos"
    repos.mkdir()
    return repos


@pytest.fixture
def handler_with_repos(service: WorkflowService, repos_dir: Path) -> ToolHandler:
    """ToolHandler with repos_dir configured."""
    return ToolHandler(service, repos_dir=repos_dir)


# ---------------------------------------------------------------------------
# SSE / app-level fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_run() -> Run:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.DRAFT,
        routine_id="test-routine",
        routine_source=RoutineSource.LOCAL,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.PENDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="First requirement",
                                priority=Priority.CRITICAL,
                            ),
                            ChecklistItem(
                                req_id="R2",
                                desc="Second requirement",
                                priority=Priority.EXPECTED,
                            ),
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


def _parse_mcp_result(raw: object) -> dict[str, Any]:
    """Extract JSON from FastMCP call_tool result.

    call_tool returns (content_blocks_list, metadata_dict) or a list of content blocks.
    """
    raw_tuple: Any = raw
    content_blocks: Any = raw_tuple[0]
    text: str = content_blocks[0].text
    return json.loads(text)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# MCP Server Tests
# ---------------------------------------------------------------------------


def test_server_creation(server: OrchestratorMCPServer) -> None:
    """Server creates without error."""
    assert server.mcp is not None
    assert server.mcp.name == "orchestrator"


def test_tool_names(server: OrchestratorMCPServer) -> None:
    """Server registers all tools regardless of phase."""
    names = server.tool_names()
    assert len(names) == 19
    assert "orchestrator_get_requirements" in names
    assert "orchestrator_update_checklist" in names
    assert "orchestrator_submit" in names
    assert "orchestrator_set_grade" in names
    assert "orchestrator_complete_recovery" in names
    assert "orchestrator_request_clarification" in names
    assert "orchestrator_escalate_requirement" in names
    assert "orchestrator_list_repos" in names
    assert "orchestrator_list_branches" in names
    assert "orchestrator_create_child_run" in names
    assert "orchestrator_create_child_from_template" in names
    assert "orchestrator_list_child_runs" in names
    assert "orchestrator_accept_child_run" in names
    assert "orchestrator_resolve_child_run" in names
    assert "orchestrator_wait_for_run" in names
    assert "orchestrator_get_run_evidence" in names
    assert "orchestrator_get_parent_oversight" in names
    assert "orchestrator_update_parent_oversight" in names
    assert "orchestrator_refresh_parent_oversight" in names


async def test_server_lists_tools(server: OrchestratorMCPServer) -> None:
    """Server lists all tools regardless of phase."""
    tools = await server.mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "orchestrator_get_requirements" in tool_names
    assert "orchestrator_update_checklist" in tool_names
    assert "orchestrator_submit" in tool_names
    assert "orchestrator_set_grade" in tool_names


async def test_server_call_tool(server: OrchestratorMCPServer, service: WorkflowService) -> None:
    """Can call a tool through the server's FastMCP instance."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    run = Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.DRAFT,
        routine_id="test-routine",
        routine_source=RoutineSource.LOCAL,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.PENDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Test requirement",
                                priority=Priority.CRITICAL,
                            ),
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )
    await service.create_run(run)

    # Call tool directly through FastMCP
    result = await server.mcp.call_tool(
        "orchestrator_get_requirements",
        {"run_id": "run-1", "task_id": "task-1"},
    )
    # FastMCP returns a list of content blocks
    assert len(result) > 0


async def test_full_workflow_through_mcp_server(
    server: OrchestratorMCPServer,
    service: WorkflowService,
) -> None:
    """Full builder→verifier workflow exercised entirely through MCP call_tool."""
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    call = server.mcp.call_tool

    # 1. Get requirements
    raw = await call("orchestrator_get_requirements", {"run_id": "run-1", "task_id": "task-1"})
    data = _parse_mcp_result(raw)
    assert len(data["requirements"]) == 2

    # 2. Mark R1 done
    raw = await call(
        "orchestrator_update_checklist",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R1", "status": "done"},
    )
    data = _parse_mcp_result(raw)
    assert data["status"] == "done"

    # 3. Mark R2 done
    raw = await call(
        "orchestrator_update_checklist",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R2", "status": "done"},
    )
    data = _parse_mcp_result(raw)
    assert data["status"] == "done"

    # 4. Submit — transitions to verifying
    raw = await call(
        "orchestrator_submit",
        {"run_id": "run-1", "task_id": "task-1"},
    )
    data = _parse_mcp_result(raw)
    assert data["success"] is True
    assert data["new_status"] == "verifying"

    # 5. Grade R1 via verifier-phase MCP server
    verifier_server = OrchestratorMCPServer(service, phase="verifying")
    verify_call = verifier_server.mcp.call_tool
    raw = await verify_call(
        "orchestrator_set_grade",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R1", "grade": "A"},
    )
    data = _parse_mcp_result(raw)
    assert data["grade"] == "A"

    # 6. Grade R2
    raw = await verify_call(
        "orchestrator_set_grade",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R2", "grade": "A"},
    )
    data = _parse_mcp_result(raw)
    assert data["grade"] == "A"

    # 7. Complete verification (via service — not an MCP tool)
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# SSE Transport Tests
# ---------------------------------------------------------------------------


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


async def test_health_still_works_with_mcp_mounted(client: AsyncClient) -> None:
    """Health endpoint still works after MCP mount."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_api_runs_still_works_with_mcp_mounted(client: AsyncClient) -> None:
    """Regular API endpoints still work after MCP mount."""
    response = await client.get("/api/runs")
    assert response.status_code == 200


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


# ---------------------------------------------------------------------------
# Tool Handler Tests
# ---------------------------------------------------------------------------


async def test_get_requirements(handler: ToolHandler, service: WorkflowService) -> None:
    run = _make_run()
    await service.create_run(run)

    result = await handler.handle(
        "orchestrator_get_requirements",
        {"run_id": "run-1", "task_id": "task-1"},
    )

    assert "requirements" in result
    reqs = result["requirements"]
    assert len(reqs) == 2
    assert reqs[0]["req_id"] == "R1"
    assert reqs[0]["desc"] == "First requirement"
    assert reqs[0]["priority"] == "critical"
    assert reqs[0]["status"] == "open"
    assert reqs[1]["req_id"] == "R2"


async def test_update_checklist(handler: ToolHandler, service: WorkflowService) -> None:
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    result = await handler.handle(
        "orchestrator_update_checklist",
        {
            "run_id": "run-1",
            "task_id": "task-1",
            "req_id": "R1",
            "status": "done",
            "note": "Completed via MCP",
        },
    )

    assert result["req_id"] == "R1"
    assert result["status"] == "done"
    assert result["note"] == "Completed via MCP"

    # Verify in service
    task = await service.get_task("run-1", "task-1")
    assert task.checklist[0].status == ChecklistStatus.DONE


async def test_submit(handler: ToolHandler, service: WorkflowService) -> None:
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    # Complete all critical requirements first
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.update_checklist_item("run-1", "task-1", "R2", ChecklistStatus.DONE)

    result = await handler.handle(
        "orchestrator_submit",
        {"run_id": "run-1", "task_id": "task-1"},
    )

    assert result["success"] is True
    assert result["new_status"] == "verifying"


async def test_set_grade(handler: ToolHandler, service: WorkflowService) -> None:
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    # Complete and submit
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.update_checklist_item("run-1", "task-1", "R2", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")

    result = await handler.handle(
        "orchestrator_set_grade",
        {
            "run_id": "run-1",
            "task_id": "task-1",
            "req_id": "R1",
            "grade": "A",
            "grade_reason": "Well done",
        },
    )

    assert result["req_id"] == "R1"
    assert result["grade"] == "A"
    assert result["grade_reason"] == "Well done"


async def test_unknown_tool(handler: ToolHandler) -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        await handler.handle("nonexistent_tool", {})


async def test_full_workflow_via_tools(handler: ToolHandler, service: WorkflowService) -> None:
    """Full workflow: get requirements -> update -> submit -> grade -> verify."""
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    # 1. Get requirements
    reqs = await handler.handle(
        "orchestrator_get_requirements",
        {"run_id": "run-1", "task_id": "task-1"},
    )
    assert len(reqs["requirements"]) == 2

    # 2. Update checklist items
    await handler.handle(
        "orchestrator_update_checklist",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R1", "status": "done"},
    )
    await handler.handle(
        "orchestrator_update_checklist",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R2", "status": "done"},
    )

    # 3. Submit
    submit_result = await handler.handle(
        "orchestrator_submit",
        {"run_id": "run-1", "task_id": "task-1"},
    )
    assert submit_result["success"] is True

    # 4. Grade
    await handler.handle(
        "orchestrator_set_grade",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R1", "grade": "A"},
    )
    await handler.handle(
        "orchestrator_set_grade",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R2", "grade": "A"},
    )

    # 5. Complete verification
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Repo Tool Tests
# ---------------------------------------------------------------------------


async def test_list_repos_empty(handler_with_repos: ToolHandler) -> None:
    """List repos returns empty list when no repos exist."""
    result = await handler_with_repos.handle("orchestrator_list_repos", {})
    assert result["repos"] == []


async def test_list_repos_with_repos(
    handler_with_repos: ToolHandler, repos_dir: Path, _base_repo: Path
) -> None:
    """List repos returns repos in the repos directory."""
    # Create two repos
    repo1 = repos_dir / "alpha"
    shutil.copytree(str(_base_repo), str(repo1))

    repo2 = repos_dir / "beta"
    shutil.copytree(str(_base_repo), str(repo2))

    result = await handler_with_repos.handle("orchestrator_list_repos", {})
    repos = result["repos"]
    assert len(repos) == 2
    names = {r["name"] for r in repos}
    assert names == {"alpha", "beta"}
    for r in repos:
        assert "path" in r
        assert "default_branch" in r


async def test_list_repos_no_repos_dir(handler: ToolHandler) -> None:
    """List repos returns error when repos_dir is not configured."""
    result = await handler.handle("orchestrator_list_repos", {})
    assert "error" in result
    assert result["repos"] == []


async def test_list_branches(
    handler_with_repos: ToolHandler, repos_dir: Path, _base_repo: Path
) -> None:
    """List branches returns branches in a repo."""
    repo = repos_dir / "myrepo"
    shutil.copytree(str(_base_repo), str(repo))

    _git_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    # Create additional branches
    subprocess.run(
        ["git", "checkout", "-b", "feature/auth"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=_git_env,
    )
    subprocess.run(
        ["git", "checkout", "main"], cwd=repo, check=True, capture_output=True, env=_git_env
    )

    result = await handler_with_repos.handle(
        "orchestrator_list_branches",
        {"repo_name": "myrepo"},
    )
    branches = result["branches"]
    assert len(branches) == 2
    names = {b["name"] for b in branches}
    assert "main" in names
    assert "feature/auth" in names


async def test_list_branches_with_pattern(
    handler_with_repos: ToolHandler, repos_dir: Path, _base_repo: Path
) -> None:
    """List branches filters by pattern."""
    repo = repos_dir / "myrepo"
    shutil.copytree(str(_base_repo), str(repo))

    _git_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    # Create multiple branches
    for name in ["feature/auth", "feature/api", "bugfix/login"]:
        subprocess.run(
            ["git", "checkout", "-b", name],
            cwd=repo,
            check=True,
            capture_output=True,
            env=_git_env,
        )
    subprocess.run(
        ["git", "checkout", "main"], cwd=repo, check=True, capture_output=True, env=_git_env
    )

    result = await handler_with_repos.handle(
        "orchestrator_list_branches",
        {"repo_name": "myrepo", "pattern": "feature/*"},
    )
    branches = result["branches"]
    assert len(branches) == 2
    names = {b["name"] for b in branches}
    assert names == {"feature/auth", "feature/api"}


async def test_list_branches_repo_not_found(
    handler_with_repos: ToolHandler,
) -> None:
    """List branches returns error for non-existent repo."""
    result = await handler_with_repos.handle(
        "orchestrator_list_branches",
        {"repo_name": "nonexistent"},
    )
    assert "error" in result
    assert result["branches"] == []
