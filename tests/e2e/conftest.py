"""E2E test fixtures.

Uses in-process ASGITransport (same as integration tests) to avoid flaky
subprocess startup timeouts.  The test surface is identical — full HTTP
request/response through the real FastAPI app — but startup is instant.
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

# Root directory of the project
ROOT_DIR = Path(__file__).parent.parent.parent
FIXTURES = ROOT_DIR / "tests" / "fixtures" / "routines"


@pytest.fixture
def test_routine_path() -> Path:
    """Path to a simple test routine."""
    return FIXTURES / "valid_simple.yaml"


@pytest.fixture
def test_routines_dir() -> Path:
    """Directory containing test routines."""
    return FIXTURES


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Provide a temporary project directory."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
async def api_client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    """In-process ASGI client with in-memory DB and signal drain function."""
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
    """In-process ASGI client backed by a real FastAPI app with in-memory DB."""
    client, _ = api_client_and_drain
    return client


@pytest.fixture
async def drain(api_client_and_drain: tuple[AsyncClient, DrainFn]) -> DrainFn:
    """Signal drain function for the api_client's app."""
    _, drain_fn = api_client_and_drain
    return drain_fn


# Helper functions for common API operations


async def create_run(
    client: httpx.AsyncClient,
    routine_id: str = "simple-routine",
    repo_name: str = "test-repo",
    branch: str = "main",
    **extra: Any,
) -> dict[str, Any]:
    """Create a run via API.

    Args:
        client: HTTP client
        routine_id: ID of the routine to use
        repo_name: Repository name
        branch: Branch to base worktree on
        **extra: Additional fields for the request

    Returns:
        Response JSON data

    Raises:
        AssertionError: If the request fails
    """
    body: dict[str, Any] = {
        "routine_id": routine_id,
        "repo_name": repo_name,
        "branch": branch,
        **extra,
    }
    response = await client.post("/api/runs", json=body)
    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
    return response.json()


async def start_run(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    """Start a run via API.

    Args:
        client: HTTP client
        run_id: Run identifier

    Returns:
        Response JSON data

    Raises:
        AssertionError: If the request fails
    """
    response = await client.post(f"/api/runs/{run_id}/start")
    assert response.status_code == 200, f"Failed to start run: {response.text}"
    return response.json()


async def start_task(client: httpx.AsyncClient, run_id: str, task_id: str) -> dict[str, Any]:
    """Start a task via API.

    Args:
        client: HTTP client
        run_id: Run identifier
        task_id: Task identifier

    Returns:
        Response JSON data

    Raises:
        AssertionError: If the request fails
    """
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert response.status_code == 200, f"Failed to start task: {response.text}"
    data = response.json()
    assert data["success"] is True, f"start_task returned success=False: {data}"
    return data


async def mark_checklist_done(
    client: httpx.AsyncClient, run_id: str, task_id: str, req_id: str
) -> dict[str, Any]:
    """Mark a checklist item as done via API.

    Args:
        client: HTTP client
        run_id: Run identifier
        task_id: Task identifier
        req_id: Requirement identifier

    Returns:
        Response JSON data

    Raises:
        AssertionError: If the request fails
    """
    response = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}",
        json={"status": "done"},
    )
    assert response.status_code == 200, f"Failed to update checklist: {response.text}"
    return response.json()


async def submit_task(
    client: httpx.AsyncClient,
    run_id: str,
    task_id: str,
    drain: DrainFn | None = None,
) -> dict[str, Any]:
    """Submit a task for verification via API, then drain signals.

    Args:
        client: HTTP client
        run_id: Run identifier
        task_id: Task identifier
        drain: Signal drain function (required for state transition to occur)

    Returns:
        Dict with success=True and the current task state

    Raises:
        AssertionError: If the request fails
    """
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert response.status_code == 202, f"Failed to submit task: {response.text}"
    if drain is not None:
        await drain(run_id)
    return {"success": True}


async def grade_item(
    client: httpx.AsyncClient,
    run_id: str,
    task_id: str,
    req_id: str,
    grade: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Set a grade for a requirement via API.

    Args:
        client: HTTP client
        run_id: Run identifier
        task_id: Task identifier
        req_id: Requirement identifier
        grade: Grade value (e.g., "pass", "fail")
        reason: Optional reason for the grade

    Returns:
        Response JSON data

    Raises:
        AssertionError: If the request fails
    """
    body: dict[str, Any] = {"grade": grade}
    if reason is not None:
        body["grade_reason"] = reason
    response = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}/grade",
        json=body,
    )
    assert response.status_code == 200, f"Failed to set grade: {response.text}"
    return response.json()


async def complete_verification(
    client: httpx.AsyncClient,
    run_id: str,
    task_id: str,
    drain: DrainFn | None = None,
) -> dict[str, Any]:
    """Complete verification for a task via API, then drain signals.

    Args:
        client: HTTP client
        run_id: Run identifier
        task_id: Task identifier
        drain: Signal drain function (required for state transition to occur)

    Returns:
        Dict with success=True

    Raises:
        AssertionError: If the request fails
    """
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert response.status_code == 202, f"Failed to complete verification: {response.text}"
    if drain is not None:
        await drain(run_id)
    return {"success": True}


async def get_run(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    """Get run details via API.

    Args:
        client: HTTP client
        run_id: Run identifier

    Returns:
        Response JSON data

    Raises:
        AssertionError: If the request fails
    """
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200, f"Failed to get run: {response.text}"
    return response.json()


async def get_task(client: httpx.AsyncClient, run_id: str, task_id: str) -> dict[str, Any]:
    """Get task details via API.

    Args:
        client: HTTP client
        run_id: Run identifier
        task_id: Task identifier

    Returns:
        Response JSON data

    Raises:
        AssertionError: If the request fails
    """
    response = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert response.status_code == 200, f"Failed to get task: {response.text}"
    return response.json()


def get_first_task_id(run_data: dict[str, Any]) -> str:
    """Extract the first task ID from run data.

    Args:
        run_data: Run response data

    Returns:
        Task identifier

    Raises:
        IndexError: If no tasks found
    """
    return run_data["steps"][0]["tasks"][0]["id"]
