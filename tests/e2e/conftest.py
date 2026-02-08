"""E2E test fixtures.

Provides fixtures for running a real HTTP server in a subprocess and
making real HTTP requests to it.
"""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any

import httpx
import pytest

# Root directory of the project
ROOT_DIR = Path(__file__).parent.parent.parent


def _find_free_port() -> int:
    """Find an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def _wait_for_server(url: str, timeout: float = 10.0) -> None:
    """Wait for the server to become available.

    Args:
        url: Base URL of the server
        timeout: Maximum time to wait in seconds

    Raises:
        TimeoutError: If server doesn't start within timeout
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            response = httpx.get(f"{url}/health", timeout=1.0)
            if response.status_code == 200:
                return
        except (httpx.ConnectError, httpx.TimeoutException):
            time.sleep(0.1)
    raise TimeoutError(f"Server at {url} did not start within {timeout}s")


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
def test_routine_path() -> Path:
    """Path to a simple test routine."""
    return ROOT_DIR / "tests" / "fixtures" / "routines" / "valid_simple.yaml"


@pytest.fixture
def test_routines_dir() -> Path:
    """Directory containing test routines."""
    return ROOT_DIR / "tests" / "fixtures" / "routines"


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Provide a temporary project directory."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def api_server(
    tmp_db_path: Path, test_routines_dir: Path
) -> Generator[tuple[str, subprocess.Popen[bytes]], None, None]:
    """Start a real uvicorn server in a subprocess.

    Returns:
        Tuple of (base_url, process)
    """
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    # Create a minimal server script
    server_script = f"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path('{ROOT_DIR}') / 'src'))

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource

app = create_app(
    db_path='{tmp_db_path}',
    routine_dirs=[(Path('{test_routines_dir}'), RoutineSource.LOCAL)],
    auth_disabled=True,
)
"""

    # Write script to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        script_path = f.name
        f.write(server_script)

    process: subprocess.Popen[bytes] | None = None
    try:
        # Start uvicorn with the app
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                f"{Path(script_path).stem}:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "error",
            ],
            cwd=Path(script_path).parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to start
        try:
            _wait_for_server(base_url, timeout=10.0)
        except TimeoutError:
            # Print server output for debugging
            stdout, stderr = process.communicate(timeout=1.0)
            print("Server stdout:", stdout.decode())
            print("Server stderr:", stderr.decode())
            process.kill()
            raise

        yield base_url, process
    finally:
        # Cleanup
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        # Remove temp script
        try:
            os.unlink(script_path)
        except FileNotFoundError:
            pass


@pytest.fixture
async def api_client(api_server: tuple[str, Any]) -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client configured for the test API server.

    Args:
        api_server: Tuple of (base_url, process)

    Yields:
        Configured async HTTP client
    """
    base_url, _ = api_server
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        yield client


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


async def submit_task(client: httpx.AsyncClient, run_id: str, task_id: str) -> dict[str, Any]:
    """Submit a task for verification via API.

    Args:
        client: HTTP client
        run_id: Run identifier
        task_id: Task identifier

    Returns:
        Response JSON data

    Raises:
        AssertionError: If the request fails
    """
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert response.status_code == 200, f"Failed to submit task: {response.text}"
    return response.json()


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
    client: httpx.AsyncClient, run_id: str, task_id: str
) -> dict[str, Any]:
    """Complete verification for a task via API.

    Args:
        client: HTTP client
        run_id: Run identifier
        task_id: Task identifier

    Returns:
        Response JSON data

    Raises:
        AssertionError: If the request fails
    """
    response = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert response.status_code == 200, f"Failed to complete verification: {response.text}"
    return response.json()


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
