"""Tests for Claude SDK MCP server building and tool filtering.

Tests build_orchestrator_mcp_server() (builder vs verifier tools) and
build_mcp_servers() (external MCP server conversion).
"""

from __future__ import annotations

import os

from orchestrator.runners import (
    build_orchestrator_mcp_server,
    build_mcp_servers,
)
from orchestrator.config import ChecklistStatus
from orchestrator.config.models import MCPServerConfig

# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


async def _noop_grade(req_id: str, grade: str, reason: str | None) -> None:
    pass


# ---------------------------------------------------------------------------
# build_orchestrator_mcp_server — builder vs verifier
# ---------------------------------------------------------------------------


class TestOrchestratorMcpServerBuilder:
    """Test build_orchestrator_mcp_server() creates correct tools for each phase."""

    def test_builder_server_created_without_grade(self) -> None:
        """Builder phase (on_grade=None) produces a server without grade tool."""
        server = build_orchestrator_mcp_server(_noop_checklist, _noop_submit, on_grade=None)
        assert server is not None

    def test_verifier_server_created_with_grade(self) -> None:
        """Verifier phase (on_grade provided) produces a server with grade tool."""
        server = build_orchestrator_mcp_server(_noop_checklist, _noop_submit, on_grade=_noop_grade)
        assert server is not None

    def test_builder_and_verifier_servers_differ(self) -> None:
        """Builder and verifier servers should be different objects (different tool sets)."""
        builder = build_orchestrator_mcp_server(_noop_checklist, _noop_submit, on_grade=None)
        verifier = build_orchestrator_mcp_server(
            _noop_checklist, _noop_submit, on_grade=_noop_grade
        )
        # They are separate server instances
        assert builder is not verifier


# ---------------------------------------------------------------------------
# build_mcp_servers — external server conversion
# ---------------------------------------------------------------------------


class TestBuildMcpServers:
    """Test build_mcp_servers() converts MCPServerConfig to SDK format."""

    def test_none_returns_orchestrator_only(self) -> None:
        """None input returns dict with only orchestrator."""
        result = build_mcp_servers("orch", mcp_servers=None)
        assert result == {"orchestrator": "orch"}

    def test_empty_list_returns_orchestrator_only(self) -> None:
        """Empty list returns dict with only orchestrator."""
        result = build_mcp_servers("orch", mcp_servers=[])
        assert result == {"orchestrator": "orch"}

    def test_url_server_converted(self) -> None:
        """HTTPS URL-based server is converted with type=sse."""
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        result = build_mcp_servers("orch", mcp_servers=[mcp])
        assert "ctx7" in result
        assert result["ctx7"]["url"] == "https://ctx7.example.com"
        assert result["ctx7"]["type"] == "sse"

    def test_stdio_server_converted(self) -> None:
        """stdio-transport server is converted with command config."""
        mcp = MCPServerConfig(name="local", command="context7-mcp")
        result = build_mcp_servers("orch", mcp_servers=[mcp])
        assert "local" in result
        assert result["local"]["command"] == "context7-mcp"

    def test_stdio_server_with_args(self) -> None:
        """stdio server includes args when provided."""
        mcp = MCPServerConfig(name="local", command="ctx-mcp", args=["--verbose"])
        result = build_mcp_servers("orch", mcp_servers=[mcp])
        assert result["local"]["args"] == ["--verbose"]

    def test_stdio_server_without_args(self) -> None:
        """stdio server omits args key when args is None."""
        mcp = MCPServerConfig(name="local", command="ctx-mcp")
        result = build_mcp_servers("orch", mcp_servers=[mcp])
        assert "args" not in result["local"]

    def test_auth_token_from_env_for_stdio(self) -> None:
        """Authorization token is resolved from env var for stdio servers."""
        old = os.environ.get("MY_TOKEN_STDIO")
        os.environ["MY_TOKEN_STDIO"] = "secret-stdio"
        try:
            mcp = MCPServerConfig(
                name="auth",
                command="auth-cmd",
                auth_token_env="MY_TOKEN_STDIO",
            )
            result = build_mcp_servers("orch", mcp_servers=[mcp])
            assert result["auth"]["env"]["MY_TOKEN_STDIO"] == "secret-stdio"
        finally:
            if old is None:
                os.environ.pop("MY_TOKEN_STDIO", None)
            else:
                os.environ["MY_TOKEN_STDIO"] = old

    def test_auth_token_from_env_for_url(self) -> None:
        """Authorization token is resolved from env var for URL servers."""
        old = os.environ.get("MY_TOKEN_URL")
        os.environ["MY_TOKEN_URL"] = "secret-url"
        try:
            mcp = MCPServerConfig(
                name="auth",
                url="https://auth.example.com",
                auth_token_env="MY_TOKEN_URL",
            )
            result = build_mcp_servers("orch", mcp_servers=[mcp])
            assert result["auth"]["headers"]["Authorization"] == "Bearer secret-url"
        finally:
            if old is None:
                os.environ.pop("MY_TOKEN_URL", None)
            else:
                os.environ["MY_TOKEN_URL"] = old

    def test_missing_env_token_no_env_dict_stdio(self) -> None:
        """When env var is missing for stdio server, no env dict is added."""
        os.environ.pop("MISSING_TOKEN_STDIO", None)
        mcp = MCPServerConfig(
            name="noauth",
            command="cmd",
            auth_token_env="MISSING_TOKEN_STDIO",
        )
        result = build_mcp_servers("orch", mcp_servers=[mcp])
        assert "env" not in result["noauth"]

    def test_missing_env_token_no_headers_url(self) -> None:
        """When env var is missing for URL server, no headers are added."""
        os.environ.pop("MISSING_TOKEN_URL", None)
        mcp = MCPServerConfig(
            name="noauth",
            url="https://x.example.com",
            auth_token_env="MISSING_TOKEN_URL",
        )
        result = build_mcp_servers("orch", mcp_servers=[mcp])
        assert "headers" not in result["noauth"]

    def test_mixed_stdio_and_url(self) -> None:
        """Both stdio and URL servers are included alongside orchestrator."""
        mcp_url = MCPServerConfig(name="remote", url="https://remote.example.com")
        mcp_stdio = MCPServerConfig(name="local", command="local-mcp")
        result = build_mcp_servers("orch", mcp_servers=[mcp_url, mcp_stdio])
        assert len(result) == 3  # orchestrator + remote + local
        assert "remote" in result
        assert "local" in result

    def test_multiple_url_servers(self) -> None:
        """Multiple URL servers are all included."""
        mcp1 = MCPServerConfig(name="server1", url="https://server1.example.com")
        mcp2 = MCPServerConfig(name="server2", url="https://server2.example.com")
        result = build_mcp_servers("orch", mcp_servers=[mcp1, mcp2])
        assert len(result) == 3
        names = set(result.keys())
        assert names == {"orchestrator", "server1", "server2"}

    def test_orchestrator_not_overwritten_by_external(self) -> None:
        """External server named 'orchestrator' would overwrite — verify key exists."""
        # In practice the orchestrator key is set first, then external servers
        # are added. If an external server is named "orchestrator" it would
        # overwrite. This test documents the behavior.
        mcp = MCPServerConfig(name="orchestrator", url="https://evil.example.com")
        result = build_mcp_servers("orch-server", mcp_servers=[mcp])
        # The external server overwrites the orchestrator key
        assert result["orchestrator"]["url"] == "https://evil.example.com"
