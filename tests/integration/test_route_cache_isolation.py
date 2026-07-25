"""The API route cache must be invisible apart from the time it saves.

``create_app`` caches compiled API routes and grafts them onto each new app
(see ``set_route_cache_enabled``, enabled for the suite in
``tests/conftest.py``). That is only safe because ``APIRoute`` objects are not
bound to the app they were registered on — endpoints reach their collaborators
through ``request.app.state`` at request time.

If that ever stops holding, apps built from the cache would start sharing a
database or a manager, and the symptom would be a confusing cross-test failure
far from the cause. These tests pin the property directly: two apps built while
the cache is active must behave exactly like two independently built apps.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app, set_route_cache_enabled
from orchestrator.config import RoutineSource
from orchestrator.db import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

RUN_BODY = {"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"}


@pytest.fixture(autouse=True)
def _restore_route_cache() -> Generator[None, None, None]:
    """Re-enable the cache after tests that deliberately toggle it.

    These tests flip a process-wide switch, so leaving it off would silently
    slow every later test in this worker.
    """
    yield
    set_route_cache_enabled(True)


async def _make_app_and_client() -> tuple[object, AsyncClient]:
    app = create_app(db_path=":memory:", routine_dirs=[(FIXTURES, RoutineSource.LOCAL)])
    await init_db(app.state.engine)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")  # type: ignore[arg-type]
    return app, client


@pytest.fixture
async def two_apps() -> AsyncGenerator[tuple[AsyncClient, AsyncClient], None]:
    """Two apps alive at the same time, both served from the route cache."""
    set_route_cache_enabled(True)
    app_a, client_a = await _make_app_and_client()
    app_b, client_b = await _make_app_and_client()
    yield client_a, client_b
    await client_a.aclose()
    await client_b.aclose()
    await app_a.state.engine.dispose()  # type: ignore[attr-defined]
    await app_b.state.engine.dispose()  # type: ignore[attr-defined]


async def test_concurrently_live_apps_do_not_share_a_database(
    two_apps: tuple[AsyncClient, AsyncClient],
) -> None:
    """A run created through one app must be invisible to the other.

    Uses a hardcoded ``repo_name`` in both apps on purpose: identical
    identities must not collide, because the databases are separate.
    """
    client_a, client_b = two_apps

    created = await client_a.post("/api/runs", json=RUN_BODY)
    assert created.status_code == 201

    runs_a = (await client_a.get("/api/runs")).json()["runs"]
    runs_b = (await client_b.get("/api/runs")).json()["runs"]

    assert len(runs_a) == 1
    assert runs_b == []


async def test_grafted_routes_serve_requests_on_every_app(
    two_apps: tuple[AsyncClient, AsyncClient],
) -> None:
    """Both apps must serve the full surface, not just the one that compiled it."""
    client_a, client_b = two_apps

    for client in (client_a, client_b):
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/api/runs")).status_code == 200
        assert (await client.get("/api/routines")).status_code == 200
        # A route registered late in create_app, after the cached block.
        assert (await client.get("/api/config")).status_code == 200


async def test_state_objects_are_not_shared_between_apps() -> None:
    """Per-app collaborators must be distinct, including the MCP registry.

    ``GraphMcpDispatcher`` captures the registry when the MCP transport is
    mounted, so a shared registry would silently route one app's graph MCP
    traffic through another's.
    """
    set_route_cache_enabled(True)
    app_a = create_app(db_path=":memory:", routine_dirs=[])
    app_b = create_app(db_path=":memory:", routine_dirs=[])
    try:
        assert app_a is not app_b
        assert app_a.state.engine is not app_b.state.engine
        assert app_a.state.session_factory is not app_b.state.session_factory
        assert app_a.state.graph_mcp_registry is not app_b.state.graph_mcp_registry
        assert app_a.state.lock_manager is not app_b.state.lock_manager
        assert app_a.state.connection_manager is not app_b.state.connection_manager
        assert app_a.state.runner_executor is not app_b.state.runner_executor
    finally:
        await app_a.state.engine.dispose()
        await app_b.state.engine.dispose()


async def test_cached_and_uncached_apps_expose_the_same_routes() -> None:
    """The cache must not change the route table it stands in for."""
    set_route_cache_enabled(False)
    uncached = create_app(db_path=":memory:", routine_dirs=[])

    set_route_cache_enabled(True)
    first = create_app(db_path=":memory:", routine_dirs=[])  # populates the cache
    grafted = create_app(db_path=":memory:", routine_dirs=[])  # served from it

    def surface(app: object) -> set[tuple[str, str]]:
        return {
            (route.path, ",".join(sorted(route.methods)))  # type: ignore[attr-defined]
            for route in app.router.routes  # type: ignore[attr-defined]
            if getattr(route, "methods", None)
        }

    try:
        assert surface(grafted) == surface(uncached)
        assert surface(first) == surface(uncached)
    finally:
        for app in (uncached, first, grafted):
            await app.state.engine.dispose()  # type: ignore[attr-defined]
