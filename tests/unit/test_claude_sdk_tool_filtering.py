"""Tests for Claude SDK agent tool filtering and MCP wiring."""

import logging
from unittest.mock import patch

import pytest

from orchestrator.agents.claude_sdk import _build_tool_list, _build_mcp_params
from orchestrator.config.models import MCPServerConfig


class TestClaudeSDKToolFiltering:
    """Test cases for _build_tool_list() function."""

    def test_builder_tools_when_none(self) -> None:
        """With available_tools=None, builder gets all builder tools."""
        tools = _build_tool_list(is_verifier=False, available_tools=None)
        names = {t["name"] for t in tools}
        assert "submit" in names
        assert "update_checklist" in names
        assert "request_clarification" in names
        assert "grade" not in names  # Builder doesn't get grade

    def test_verifier_tools_when_none(self) -> None:
        """With available_tools=None, verifier gets all verifier tools."""
        tools = _build_tool_list(is_verifier=True, available_tools=None)
        names = {t["name"] for t in tools}
        assert "grade" in names
        assert "submit" in names
        assert "update_checklist" in names
        assert "request_clarification" in names

    def test_unknown_tool_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unknown tools in available_tools produce a warning."""
        with caplog.at_level(logging.WARNING):
            tools = _build_tool_list(is_verifier=False, available_tools=["nonexistent_tool"])
        assert "nonexistent_tool" in caplog.text
        assert "Unknown tool" in caplog.text
        # Should still have all base tools
        names = {t["name"] for t in tools}
        assert "submit" in names
        assert "update_checklist" in names

    def test_phase_tools_always_included(self) -> None:
        """Step tools never remove phase tools."""
        tools = _build_tool_list(is_verifier=False, available_tools=["nonexistent"])
        names = {t["name"] for t in tools}
        assert "submit" in names
        assert "update_checklist" in names
        assert "request_clarification" in names

    def test_empty_available_tools(self) -> None:
        """With empty available_tools list, returns only phase tools."""
        tools = _build_tool_list(is_verifier=False, available_tools=[])
        names = {t["name"] for t in tools}
        assert "submit" in names
        assert "update_checklist" in names
        assert len(tools) == 3  # submit, update_checklist, request_clarification

    def test_verifier_has_grade(self) -> None:
        """Verifier phase includes grade tool."""
        tools = _build_tool_list(is_verifier=True, available_tools=None)
        names = {t["name"] for t in tools}
        assert "grade" in names

    def test_builder_no_grade(self) -> None:
        """Builder phase never includes grade tool."""
        tools = _build_tool_list(is_verifier=False, available_tools=None)
        names = {t["name"] for t in tools}
        assert "grade" not in names

    def test_tools_are_deep_copied(self) -> None:
        """Modifying returned tools doesn't affect the base tools."""
        tools1 = _build_tool_list(is_verifier=False, available_tools=None)
        tools2 = _build_tool_list(is_verifier=False, available_tools=None)
        # Should have the same content
        assert len(tools1) == len(tools2)
        # But modifying one shouldn't affect the other
        if tools1:
            tools1[0]["test_key"] = "test_value"
            assert "test_key" not in tools2[0]


class TestClaudeSDKMCPParams:
    """Test cases for _build_mcp_params() function."""

    def test_https_server_included(self) -> None:
        """HTTPS URL-based server is converted to beta API format."""
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        params = _build_mcp_params([mcp])
        assert "mcp_servers" in params
        assert params["mcp_servers"][0]["url"] == "https://ctx7.example.com"
        assert params["mcp_servers"][0]["name"] == "ctx7"
        assert params["mcp_servers"][0]["type"] == "url"

    def test_stdio_server_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """STDIO-transport server is skipped with warning."""
        mcp = MCPServerConfig(name="local", command="context7-mcp")
        with caplog.at_level(logging.WARNING):
            params = _build_mcp_params([mcp])
        assert params == {}
        assert "STDIO" in caplog.text or "STDIO transport" in caplog.text

    def test_none_returns_empty(self) -> None:
        """None input returns empty dict."""
        params = _build_mcp_params(None)
        assert params == {}

    def test_empty_list_returns_empty(self) -> None:
        """Empty list returns empty dict."""
        params = _build_mcp_params([])
        assert params == {}

    def test_auth_token_from_env(self) -> None:
        """Authorization token is resolved from env var."""
        mcp = MCPServerConfig(
            name="auth",
            url="https://auth.example.com",
            auth_token_env="MY_TOKEN",
        )
        with patch.dict("os.environ", {"MY_TOKEN": "secret123"}):
            params = _build_mcp_params([mcp])
        assert params["mcp_servers"][0].get("authorization_token") == "secret123"

    def test_auth_token_missing_env_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Warning logged when auth_token_env is not set in environment."""
        mcp = MCPServerConfig(
            name="auth",
            url="https://auth.example.com",
            auth_token_env="MISSING_TOKEN",
        )
        with patch.dict("os.environ", {}, clear=True):
            with caplog.at_level(logging.WARNING):
                params = _build_mcp_params([mcp])
        assert "MISSING_TOKEN" in caplog.text
        # Server should still be included, just without auth token
        assert "mcp_servers" in params
        assert params["mcp_servers"][0].get("authorization_token") is None

    def test_mixed_stdio_and_https(self) -> None:
        """STDIO servers skipped, HTTPS servers included."""
        mcp_https = MCPServerConfig(name="remote", url="https://remote.example.com")
        mcp_stdio = MCPServerConfig(name="local", command="local-mcp")
        params = _build_mcp_params([mcp_https, mcp_stdio])
        assert len(params["mcp_servers"]) == 1
        assert params["mcp_servers"][0]["name"] == "remote"

    def test_multiple_https_servers(self) -> None:
        """Multiple HTTPS servers are all included."""
        mcp1 = MCPServerConfig(name="server1", url="https://server1.example.com")
        mcp2 = MCPServerConfig(name="server2", url="https://server2.example.com")
        params = _build_mcp_params([mcp1, mcp2])
        assert len(params["mcp_servers"]) == 2
        names = {s["name"] for s in params["mcp_servers"]}
        assert names == {"server1", "server2"}

    def test_all_stdio_servers_returns_empty(self, caplog: pytest.LogCaptureFixture) -> None:
        """When all servers are STDIO, empty dict returned."""
        mcp1 = MCPServerConfig(name="local1", command="cmd1")
        mcp2 = MCPServerConfig(name="local2", command="cmd2")
        with caplog.at_level(logging.WARNING):
            params = _build_mcp_params([mcp1, mcp2])
        assert params == {}
