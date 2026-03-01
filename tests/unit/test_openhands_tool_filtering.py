"""Tests for OpenHands agent tool filtering and MCP config."""

import os

from orchestrator.config.models import MCPServerConfig


# Import the conversion function
from orchestrator.agents.openhands import _build_openhands_mcp_config


class TestOpenHandsMCPConfig:
    """Tests for MCP config conversion to OpenHands format."""

    def test_url_transport(self) -> None:
        """Test URL transport with MCP server config."""
        mcp = MCPServerConfig(name="remote", url="https://mcp.example.com")
        config = _build_openhands_mcp_config([mcp])
        assert config is not None
        assert "mcpServers" in config
        assert "remote" in config["mcpServers"]
        assert config["mcpServers"]["remote"]["url"] == "https://mcp.example.com"

    def test_stdio_transport(self) -> None:
        """Test stdio transport with command and args."""
        mcp = MCPServerConfig(name="local", command="ctx7", args=["--verbose"])
        config = _build_openhands_mcp_config([mcp])
        assert config is not None
        assert "mcpServers" in config
        assert "local" in config["mcpServers"]
        assert config["mcpServers"]["local"]["command"] == "ctx7"
        assert config["mcpServers"]["local"]["args"] == ["--verbose"]

    def test_stdio_transport_no_args(self) -> None:
        """Test stdio transport without args."""
        mcp = MCPServerConfig(name="local", command="ctx7")
        config = _build_openhands_mcp_config([mcp])
        assert config is not None
        assert config["mcpServers"]["local"]["command"] == "ctx7"
        assert "args" not in config["mcpServers"]["local"]

    def test_none_input_returns_none(self) -> None:
        """Test that None input returns None."""
        config = _build_openhands_mcp_config(None)
        assert config is None

    def test_empty_list_returns_none(self) -> None:
        """Test that empty list returns None."""
        config = _build_openhands_mcp_config([])
        assert config is None

    def test_multiple_servers(self) -> None:
        """Test multiple MCP servers in single config."""
        servers = [
            MCPServerConfig(name="a", url="https://a.com"),
            MCPServerConfig(name="b", command="b-cmd"),
        ]
        config = _build_openhands_mcp_config(servers)
        assert config is not None
        assert len(config["mcpServers"]) == 2
        assert "a" in config["mcpServers"]
        assert "b" in config["mcpServers"]
        assert config["mcpServers"]["a"]["url"] == "https://a.com"
        assert config["mcpServers"]["b"]["command"] == "b-cmd"

    def test_env_variables(self) -> None:
        """Test environment variables are included in config."""
        mcp = MCPServerConfig(
            name="test", url="https://test.com", env={"VAR1": "value1", "VAR2": "value2"}
        )
        config = _build_openhands_mcp_config([mcp])
        assert config is not None
        assert config["mcpServers"]["test"]["env"] == {"VAR1": "value1", "VAR2": "value2"}

    def test_auth_token_from_env_var(self) -> None:
        """Test auth token resolved from environment variable."""
        # Set up environment variable
        os.environ["TEST_AUTH_TOKEN"] = "secret123"
        try:
            mcp = MCPServerConfig(
                name="secured", url="https://secure.com", auth_token_env="TEST_AUTH_TOKEN"
            )
            config = _build_openhands_mcp_config([mcp])
            assert config is not None
            assert config["mcpServers"]["secured"]["env"] == {"AUTH_TOKEN": "secret123"}
        finally:
            del os.environ["TEST_AUTH_TOKEN"]

    def test_auth_token_missing_env_var(self) -> None:
        """Test graceful handling when auth token env var is not set."""
        # Ensure the env var doesn't exist
        if "MISSING_TOKEN_VAR" in os.environ:
            del os.environ["MISSING_TOKEN_VAR"]

        mcp = MCPServerConfig(
            name="secured", url="https://secure.com", auth_token_env="MISSING_TOKEN_VAR"
        )
        config = _build_openhands_mcp_config([mcp])
        assert config is not None
        # Should not include AUTH_TOKEN if env var is missing
        assert "env" not in config["mcpServers"]["secured"] or "AUTH_TOKEN" not in config[
            "mcpServers"
        ]["secured"].get("env", {})

    def test_auth_token_with_existing_env(self) -> None:
        """Test auth token merged with existing env variables."""
        os.environ["MY_TOKEN"] = "token456"
        try:
            mcp = MCPServerConfig(
                name="merged",
                url="https://merged.com",
                env={"EXISTING_VAR": "existing_value"},
                auth_token_env="MY_TOKEN",
            )
            config = _build_openhands_mcp_config([mcp])
            assert config is not None
            env = config["mcpServers"]["merged"]["env"]
            assert env["EXISTING_VAR"] == "existing_value"
            assert env["AUTH_TOKEN"] == "token456"
        finally:
            del os.environ["MY_TOKEN"]

    def test_mcp_config_structure(self) -> None:
        """Test the full MCP config structure with all fields."""
        os.environ["SECURE_TOKEN"] = "secret789"
        try:
            servers = [
                MCPServerConfig(
                    name="api_server",
                    url="https://api.example.com",
                    env={"DEBUG": "true"},
                ),
                MCPServerConfig(
                    name="local_server",
                    command="start-server",
                    args=["--port", "8080"],
                    auth_token_env="SECURE_TOKEN",
                ),
            ]
            config = _build_openhands_mcp_config(servers)

            assert config is not None
            assert "mcpServers" in config

            # Check api_server
            assert config["mcpServers"]["api_server"]["url"] == "https://api.example.com"
            assert config["mcpServers"]["api_server"]["env"] == {"DEBUG": "true"}

            # Check local_server
            assert config["mcpServers"]["local_server"]["command"] == "start-server"
            assert config["mcpServers"]["local_server"]["args"] == ["--port", "8080"]
            assert config["mcpServers"]["local_server"]["env"]["AUTH_TOKEN"] == "secret789"
        finally:
            del os.environ["SECURE_TOKEN"]
