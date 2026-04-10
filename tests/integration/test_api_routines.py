"""Integration tests for routine API endpoints."""

from pathlib import Path

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture(scope="module")
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


@pytest.fixture(scope="module")
async def empty_client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(db_path=":memory:", routine_dirs=[])
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


async def test_list_routines(client: AsyncClient) -> None:
    response = await client.get("/api/routines")
    assert response.status_code == 200
    data = response.json()
    routines = data["routines"]
    # Should find valid_simple.yaml and valid_complete.yaml (invalid_with_ref.yaml is skipped)
    assert len(routines) >= 2
    ids = {r["id"] for r in routines}
    assert "simple-routine" in ids
    assert "complete-routine" in ids


async def test_list_routines_returns_summary_fields(client: AsyncClient) -> None:
    response = await client.get("/api/routines")
    data = response.json()
    simple = next(r for r in data["routines"] if r["id"] == "simple-routine")
    assert simple["name"] == "Simple Routine"
    assert simple["source"] == "local"
    assert simple["step_count"] == 1
    assert simple["input_count"] == 0


async def test_get_routine_by_id(client: AsyncClient) -> None:
    response = await client.get("/api/routines/complete-routine")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "complete-routine"
    assert data["name"] == "Complete Routine"
    assert data["source"] == "local"
    assert len(data["steps"]) == 2
    assert data["steps"][0]["id"] == "S-01"
    assert data["steps"][0]["task_count"] == 1
    assert data["steps"][1]["id"] == "S-02"
    assert data["steps"][1]["task_count"] == 2
    assert len(data["inputs"]) == 2


async def test_get_routine_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/routines/nonexistent")
    assert response.status_code == 404


async def test_empty_dir_returns_empty_list(empty_client: AsyncClient) -> None:
    response = await empty_client.get("/api/routines")
    assert response.status_code == 200
    assert response.json() == {"routines": []}


# --- B3: validate routine endpoint tests ---

VALID_ROUTINE_YAML = """\
routine:
  id: test-routine
  name: Test Routine
  steps:
    - id: S-01
      title: Step One
      tasks:
        - id: T-01
          title: Task One
          task_context: Do something
          requirements:
            - id: R1
              desc: Requirement 1
"""

VALID_ROUTINE_YAML_UNWRAPPED = """\
id: test-routine
name: Test Routine
steps:
  - id: S-01
    title: Step One
    tasks:
      - id: T-01
        title: Task One
        task_context: Do something
        requirements:
          - id: R1
            desc: Requirement 1
"""

INVALID_ROUTINE_YAML_MISSING_FIELD = """\
routine:
  name: Missing ID
  steps: []
"""

INVALID_YAML_SYNTAX = """\
routine:
  id: bad
  name: [unterminated
"""


async def test_validate_routine_valid(client: AsyncClient) -> None:
    """Valid YAML with routine: wrapper returns valid=true."""
    response = await client.post(
        "/api/routines/validate",
        json={"yaml_content": VALID_ROUTINE_YAML},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["errors"] == []
    assert data["builder_feedback"] == []


async def test_validate_routine_valid_unwrapped(client: AsyncClient) -> None:
    """Valid YAML without routine: wrapper returns valid=true."""
    response = await client.post(
        "/api/routines/validate",
        json={"yaml_content": VALID_ROUTINE_YAML_UNWRAPPED},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["errors"] == []
    assert data["builder_feedback"] == []


async def test_validate_routine_invalid_missing_field(client: AsyncClient) -> None:
    """YAML missing required field returns valid=false with error details."""
    response = await client.post(
        "/api/routines/validate",
        json={"yaml_content": INVALID_ROUTINE_YAML_MISSING_FIELD},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert len(data["errors"]) > 0
    assert len(data["builder_feedback"]) > 0


async def test_validate_routine_invalid_yaml_syntax(client: AsyncClient) -> None:
    """Malformed YAML returns valid=false with parse error."""
    response = await client.post(
        "/api/routines/validate",
        json={"yaml_content": INVALID_YAML_SYNTAX},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert any("YAML parse error" in e for e in data["errors"])
    assert len(data["builder_feedback"]) > 0


async def test_validate_routine_empty_yaml(client: AsyncClient) -> None:
    """Empty YAML content returns valid=false."""
    response = await client.post(
        "/api/routines/validate",
        json={"yaml_content": ""},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert any("Empty" in e for e in data["errors"])
    assert len(data["builder_feedback"]) > 0


# --- Archive / unarchive endpoint tests ---


async def test_list_routines_includes_is_archived_false_by_default(client: AsyncClient) -> None:
    """Routines in list response include is_archived=false by default."""
    response = await client.get("/api/routines")
    assert response.status_code == 200
    for r in response.json()["routines"]:
        assert r["is_archived"] is False


async def test_archive_routine(client: AsyncClient) -> None:
    """Archiving a routine returns is_archived=true and hides it from default listing."""
    response = await client.post("/api/routines/simple-routine/archive")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "simple-routine"
    assert data["is_archived"] is True

    # Default list should no longer include it
    list_response = await client.get("/api/routines")
    ids = {r["id"] for r in list_response.json()["routines"]}
    assert "simple-routine" not in ids


async def test_include_archived_shows_archived_routines(client: AsyncClient) -> None:
    """include_archived=true returns archived routines with is_archived=true."""
    await client.post("/api/routines/simple-routine/archive")

    response = await client.get("/api/routines?include_archived=true")
    assert response.status_code == 200
    routines = response.json()["routines"]
    archived = [r for r in routines if r["id"] == "simple-routine"]
    assert len(archived) == 1
    assert archived[0]["is_archived"] is True


async def test_unarchive_routine(client: AsyncClient) -> None:
    """Unarchiving a previously archived routine restores it to default listing."""
    await client.post("/api/routines/simple-routine/archive")

    response = await client.post("/api/routines/simple-routine/unarchive")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "simple-routine"
    assert data["is_archived"] is False

    # Should appear in default listing again
    list_response = await client.get("/api/routines")
    ids = {r["id"] for r in list_response.json()["routines"]}
    assert "simple-routine" in ids


async def test_unarchive_never_archived_routine(client: AsyncClient) -> None:
    """Unarchiving a routine that was never archived is a no-op returning is_archived=false."""
    response = await client.post("/api/routines/simple-routine/unarchive")
    assert response.status_code == 200
    assert response.json()["is_archived"] is False


async def test_archive_nonexistent_routine(client: AsyncClient) -> None:
    """Archiving a routine that doesn't exist returns 404."""
    response = await client.post("/api/routines/nonexistent/archive")
    assert response.status_code == 404


async def test_unarchive_nonexistent_routine(client: AsyncClient) -> None:
    """Unarchiving a routine that doesn't exist returns 404."""
    response = await client.post("/api/routines/nonexistent/unarchive")
    assert response.status_code == 404


async def test_get_routine_includes_is_archived(client: AsyncClient) -> None:
    """GET /api/routines/{id} includes is_archived field."""
    response = await client.get("/api/routines/simple-routine")
    assert response.status_code == 200
    assert "is_archived" in response.json()
    assert response.json()["is_archived"] is False


async def test_get_archived_routine_by_id(client: AsyncClient) -> None:
    """GET /api/routines/{id} returns is_archived=true after archiving."""
    await client.post("/api/routines/simple-routine/archive")
    response = await client.get("/api/routines/simple-routine")
    assert response.status_code == 200
    assert response.json()["is_archived"] is True
