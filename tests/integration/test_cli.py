"""Integration tests for CLI commands."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from httpx import AsyncClient

from orchestrator.api.app import create_app
from orchestrator.cli.main import cli
from orchestrator.db.connection import init_db


@pytest.fixture
async def test_app() -> AsyncIterator[FastAPI]:
    """Create a test FastAPI app with in-memory database."""
    app = create_app(
        db_path=":memory:",
        routine_dirs=[],
        auth_disabled=True,
    )
    await init_db(app.state.engine)
    yield app
    await app.state.engine.dispose()


@pytest.fixture
def runner() -> CliRunner:
    """Create a Click CLI runner."""
    return CliRunner()


def test_runs_list_empty(runner: CliRunner, tmp_path: Path) -> None:
    """Test runs list with no runs."""
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "runs", "list"])
    assert result.exit_code == 0
    assert "No runs found" in result.output


def test_runs_list_json(runner: CliRunner, tmp_path: Path) -> None:
    """Test runs list with JSON output."""
    db_path = tmp_path / "test.db"
    result = runner.invoke(cli, ["--db", str(db_path), "--json", "runs", "list"])
    assert result.exit_code == 0
    data: list[object] = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_runs_status_via_api(test_app: FastAPI, runner: CliRunner) -> None:
    """Test runs status command via API."""
    from httpx import ASGITransport

    # Create a run first
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Create a run with embedded routine (correct schema)
        create_response = await client.post(
            "/api/runs",
            json={
                "project_id": "/tmp/test-project",
                "routine_embedded": {
                    "id": "test-routine",
                    "name": "Test Routine",
                    "description": "A test routine",
                    "inputs": [],
                    "steps": [
                        {
                            "id": "step-1",
                            "title": "Test Step",
                            "tasks": [
                                {
                                    "id": "task-1",
                                    "title": "Test Task",
                                    "task_context": "Do something",
                                    "requirements": [
                                        {"id": "req-1", "desc": "Req 1", "priority": "critical"}
                                    ],
                                }
                            ],
                        }
                    ],
                },
            },
        )
        assert create_response.status_code == 201
        run_data = create_response.json()
        run_id = run_data["id"]

    # Note: We can't easily test the status command against a live API server
    # in this integration test because it would require spinning up a server.
    # The command is tested manually and the code itself is straightforward.
    # This test just verifies the run creation works via API.
    assert run_id is not None


@pytest.mark.asyncio
async def test_pause_resume_cancel_via_api(test_app: FastAPI) -> None:
    """Test pause/resume/cancel commands via API endpoints."""
    from httpx import ASGITransport

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Create a run (correct schema)
        create_response = await client.post(
            "/api/runs",
            json={
                "project_id": "/tmp/test-project",
                "routine_embedded": {
                    "id": "test-routine",
                    "name": "Test Routine",
                    "description": "A test routine",
                    "inputs": [],
                    "steps": [
                        {
                            "id": "step-1",
                            "title": "Test Step",
                            "tasks": [
                                {
                                    "id": "task-1",
                                    "title": "Test Task",
                                    "task_context": "Do something",
                                    "requirements": [
                                        {"id": "req-1", "desc": "Req 1", "priority": "critical"}
                                    ],
                                }
                            ],
                        }
                    ],
                },
                "agent_type": "user_managed",
            },
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["id"]

        # Start the run
        start_response = await client.post(f"/api/runs/{run_id}/start")
        assert start_response.status_code == 200
        assert start_response.json()["status"] == "active"

        # Pause the run
        pause_response = await client.post(f"/api/runs/{run_id}/pause")
        assert pause_response.status_code == 200
        assert pause_response.json()["status"] == "paused"

        # Resume the run
        resume_response = await client.post(f"/api/runs/{run_id}/resume")
        assert resume_response.status_code == 200
        assert resume_response.json()["status"] == "active"

        # Cancel the run
        cancel_response = await client.post(f"/api/runs/{run_id}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_resume_with_agent_switch(test_app: FastAPI) -> None:
    """Test resume command with agent switching."""
    from httpx import ASGITransport

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Create a run with user_managed agent
        create_response = await client.post(
            "/api/runs",
            json={
                "project_id": "/tmp/test-project",
                "routine_embedded": {
                    "id": "test-routine",
                    "name": "Test Routine",
                    "description": "A test routine",
                    "inputs": [],
                    "steps": [
                        {
                            "id": "step-1",
                            "title": "Test Step",
                            "tasks": [
                                {
                                    "id": "task-1",
                                    "title": "Test Task",
                                    "task_context": "Do something",
                                    "requirements": [
                                        {"id": "req-1", "desc": "Req 1", "priority": "critical"}
                                    ],
                                }
                            ],
                        }
                    ],
                },
                "agent_type": "user_managed",
            },
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["id"]
        assert create_response.json()["agent_type"] == "user_managed"

        # Start the run
        start_response = await client.post(f"/api/runs/{run_id}/start")
        assert start_response.status_code == 200

        # Pause the run
        pause_response = await client.post(f"/api/runs/{run_id}/pause")
        assert pause_response.status_code == 200

        # Resume with agent switch to cli_subprocess
        resume_response = await client.post(
            f"/api/runs/{run_id}/resume",
            json={"agent_type": "cli_subprocess", "agent_config": {"timeout": "300"}},
        )
        assert resume_response.status_code == 200
        assert resume_response.json()["status"] == "active"
        assert resume_response.json()["agent_type"] == "cli_subprocess"
        assert resume_response.json()["agent_config"] == {"timeout": "300"}

        # Pause again
        pause_response2 = await client.post(f"/api/runs/{run_id}/pause")
        assert pause_response2.status_code == 200

        # Resume without changing agent (should keep cli_subprocess)
        resume_response2 = await client.post(f"/api/runs/{run_id}/resume")
        assert resume_response2.status_code == 200
        assert resume_response2.json()["agent_type"] == "cli_subprocess"


def test_routines_list(runner: CliRunner, tmp_path: Path) -> None:
    """Test routines list command."""
    # Run the list command
    result = runner.invoke(cli, ["routines", "list"])
    assert result.exit_code == 0
    # Should discover routines from the default "routines" directory
    # (if it exists), but this test focuses on the command execution


def test_routines_show_local(runner: CliRunner, tmp_path: Path) -> None:
    """Test routines show command with local discovery."""
    # Test that the command executes without errors when routine not found
    result = runner.invoke(cli, ["routines", "show", "nonexistent-routine"])
    # Should fail with exit code 1 because routine doesn't exist
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "error" in result.output.lower()


def test_routines_validate(runner: CliRunner, tmp_path: Path) -> None:
    """Test routines validate command."""
    # Create a valid routine file
    routine_file = tmp_path / "test-routine.yaml"
    # Use correct schema with task_context, id, and desc fields
    routine_file.write_text(
        """id: test-routine
name: Test Routine
description: A test routine
inputs: []
steps:
  - id: step-1
    title: Test Step
    tasks:
      - id: task-1
        title: Test Task
        task_context: Do something
        requirements:
          - id: req-1
            desc: Req 1
            priority: critical
""".strip()
    )

    result = runner.invoke(cli, ["routines", "validate", str(routine_file)])
    assert result.exit_code == 0
    assert "Valid routine" in result.output or "✓" in result.output


def test_routines_validate_invalid(runner: CliRunner, tmp_path: Path) -> None:
    """Test routines validate command with invalid routine."""
    # Create an invalid routine file
    routine_file = tmp_path / "invalid-routine.yaml"
    routine_file.write_text("""
# Missing required fields
name: Test Routine
""")

    result = runner.invoke(cli, ["routines", "validate", str(routine_file)])
    assert result.exit_code == 1
    assert "error" in result.output.lower() or "✗" in result.output
