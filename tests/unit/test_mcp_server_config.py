"""Tests for MCPServerConfig model and StepConfig extension."""

import pytest
from pydantic import ValidationError

from orchestrator.config.models import MCPServerConfig, StepConfig


class TestMCPServerConfig:
    def test_url_transport_valid(self):
        cfg = MCPServerConfig(name="remote", url="https://mcp.example.com")
        assert cfg.url == "https://mcp.example.com"
        assert cfg.command is None

    def test_command_transport_valid(self):
        cfg = MCPServerConfig(name="local", command="context7-mcp", args=["--verbose"])
        assert cfg.command == "context7-mcp"
        assert cfg.args == ["--verbose"]
        assert cfg.url is None

    def test_both_transports_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            MCPServerConfig(name="bad", url="https://x", command="y")

    def test_neither_transport_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            MCPServerConfig(name="empty")

    def test_timeout_default(self):
        cfg = MCPServerConfig(name="t", url="https://x")
        assert cfg.timeout_seconds == 30

    def test_auth_token_env_is_string_reference(self):
        cfg = MCPServerConfig(name="auth", url="https://x", auth_token_env="MY_TOKEN_VAR")
        assert cfg.auth_token_env == "MY_TOKEN_VAR"

    def test_env_vars(self):
        cfg = MCPServerConfig(name="e", command="cmd", env={"KEY": "val"})
        assert cfg.env == {"KEY": "val"}


class TestStepConfigExtension:
    def test_backward_compat_no_new_fields(self):
        """Existing StepConfig usage without available_tools/mcp_servers still works."""
        step = StepConfig(
            id="s1",
            title="Test Step",
            tasks=[{"id": "t1", "title": "Task 1", "task_context": "Context", "requirements": []}],
        )
        assert step.available_tools is None
        assert step.mcp_servers is None

    def test_available_tools_parsed(self):
        step = StepConfig(
            id="s1",
            title="Test Step",
            tasks=[{"id": "t1", "title": "Task 1", "task_context": "Context", "requirements": []}],
            available_tools=["terminal", "file_editor"],
        )
        assert step.available_tools == ["terminal", "file_editor"]

    def test_mcp_servers_parsed(self):
        step = StepConfig(
            id="s1",
            title="Test Step",
            tasks=[{"id": "t1", "title": "Task 1", "task_context": "Context", "requirements": []}],
            mcp_servers=[{"name": "ctx7", "url": "https://ctx7.example.com"}],
        )
        assert len(step.mcp_servers) == 1
        assert step.mcp_servers[0].name == "ctx7"
