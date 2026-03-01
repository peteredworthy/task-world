"""Tests for User-Managed MCP all-tools registration and prompt MCP info."""

from orchestrator.api.schemas.tasks import CallbackInstructions
from orchestrator.config.models import MCPServerConfig


class TestCallbackInstructionsMCPServers:
    def test_mcp_servers_field_optional(self):
        cb = CallbackInstructions(
            run_id="r1",
            task_id="t1",
            api_base_url="http://localhost:8000",
            rest_instructions="REST...",
            mcp_instructions="MCP...",
        )
        assert cb.mcp_servers is None

    def test_mcp_servers_field_populated(self):
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        cb = CallbackInstructions(
            run_id="r1",
            task_id="t1",
            api_base_url="http://localhost:8000",
            rest_instructions="REST...",
            mcp_instructions="MCP...",
            mcp_servers=[mcp],
        )
        assert len(cb.mcp_servers) == 1
        assert cb.mcp_servers[0].name == "ctx7"

    def test_json_serialization_includes_mcp_servers(self):
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        cb = CallbackInstructions(
            run_id="r1",
            task_id="t1",
            api_base_url="http://localhost:8000",
            rest_instructions="REST...",
            mcp_instructions="MCP...",
            mcp_servers=[mcp],
        )
        data = cb.model_dump()
        assert "mcp_servers" in data
        assert data["mcp_servers"][0]["name"] == "ctx7"
