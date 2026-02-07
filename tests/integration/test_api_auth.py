"""Integration tests for API authentication."""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from orchestrator.api.app import create_app
from orchestrator.api.auth import AuthConfig, create_token


@pytest.fixture
async def client_no_auth() -> AsyncGenerator[AsyncClient, None]:
    """Client with auth disabled (default)."""
    app = create_app(db_path=":memory:")
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def auth_config() -> AuthConfig:
    """Auth config with a known secret for testing."""
    return AuthConfig(auth_disabled=False, jwt_secret="integration-test-secret")


@pytest.fixture
def valid_token(auth_config: AuthConfig) -> str:
    return create_token(auth_config)


@pytest.fixture
async def client_auth(auth_config: AuthConfig) -> AsyncGenerator[AsyncClient, None]:
    """Client with auth enabled and a known secret."""
    app = create_app(
        db_path=":memory:",
        auth_disabled=False,
        jwt_secret=auth_config.jwt_secret,
    )
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_auth_disabled_allows_all(client_no_auth: AsyncClient) -> None:
    """With default config (auth disabled), requests need no token."""
    response = await client_no_auth.get("/api/routines")
    assert response.status_code == 200


async def test_auth_enabled_rejects_missing_token(client_auth: AsyncClient) -> None:
    """When auth is enabled, requests without a token get 401."""
    response = await client_auth.get("/api/routines")
    assert response.status_code == 401


async def test_auth_enabled_accepts_valid_token(client_auth: AsyncClient, valid_token: str) -> None:
    """When auth is enabled, a valid Bearer token grants access."""
    response = await client_auth.get(
        "/api/routines",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200


async def test_auth_enabled_rejects_invalid_token(client_auth: AsyncClient) -> None:
    """When auth is enabled, an invalid token gets 401."""
    response = await client_auth.get(
        "/api/routines",
        headers={"Authorization": "Bearer invalid-token-here"},
    )
    assert response.status_code == 401


async def test_health_endpoint_no_auth_required(client_auth: AsyncClient) -> None:
    """Health endpoint should work without auth even when auth is enabled."""
    response = await client_auth.get("/health")
    assert response.status_code == 200


def test_websocket_auth_with_query_param(auth_config: AuthConfig, valid_token: str) -> None:
    """WebSocket connects when valid token is provided as query parameter."""
    app = create_app(
        db_path=":memory:",
        auth_disabled=False,
        jwt_secret=auth_config.jwt_secret,
    )
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/runs/run-1?token={valid_token}"):
            pass  # Connection established successfully


def test_websocket_auth_rejects_bad_token(auth_config: AuthConfig) -> None:
    """WebSocket rejects connection with invalid token."""
    app = create_app(
        db_path=":memory:",
        auth_disabled=False,
        jwt_secret=auth_config.jwt_secret,
    )
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/runs/run-1?token=bad-token"):
                pass


async def test_mcp_auth_rejects_no_token(auth_config: AuthConfig) -> None:
    """MCP endpoint rejects requests without a token when auth is enabled."""
    app = create_app(
        db_path=":memory:",
        auth_disabled=False,
        jwt_secret=auth_config.jwt_secret,
    )
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/mcp/sse")
        assert response.status_code == 401


async def test_mcp_auth_with_bearer(auth_config: AuthConfig, valid_token: str) -> None:
    """MCP auth middleware passes valid Bearer token through to MCP handler.

    We use /mcp/messages (POST) instead of /mcp/sse (GET) since SSE is a
    streaming endpoint with its own transport security that rejects test
    hostnames. The auth middleware runs before the MCP handler on all paths.
    """
    app = create_app(
        db_path=":memory:",
        auth_disabled=False,
        jwt_secret=auth_config.jwt_secret,
    )
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        # POST to /mcp/messages with valid auth — should get past auth middleware
        # (the MCP handler may return 4xx/5xx for missing session, but NOT 401)
        response = await client.post(
            "/mcp/messages/",
            headers={"Authorization": f"Bearer {valid_token}"},
            content="{}",
        )
        assert response.status_code != 401


async def test_mcp_auth_rejects_invalid_token(auth_config: AuthConfig) -> None:
    """MCP auth middleware rejects invalid Bearer token."""
    app = create_app(
        db_path=":memory:",
        auth_disabled=False,
        jwt_secret=auth_config.jwt_secret,
    )
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.post(
            "/mcp/messages/",
            headers={"Authorization": "Bearer bad-token"},
            content="{}",
        )
        assert response.status_code == 401
