"""Helpers for scoping routine MCP server exposure to declared tools."""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from orchestrator.config.models import MCPServerConfig

BUILDER_WORKFLOW_MCP_TOOLS = {
    "orchestrator_get_requirements",
    "orchestrator_update_checklist",
    "orchestrator_submit",
    "orchestrator_request_clarification",
    "orchestrator_escalate_requirement",
}

VERIFIER_WORKFLOW_MCP_TOOLS = {
    "orchestrator_get_requirements",
    "orchestrator_submit",
    "orchestrator_set_grade",
    "orchestrator_complete_recovery",
}

WORKFLOW_MCP_TOOLS = BUILDER_WORKFLOW_MCP_TOOLS | VERIFIER_WORKFLOW_MCP_TOOLS


def scope_mcp_servers_to_available_tools(
    mcp_servers: list[MCPServerConfig] | None,
    available_tools: list[str] | None,
    phase: Literal["building", "verifying"] = "building",
) -> list[MCPServerConfig] | None:
    """Return MCP servers with orchestrator URLs scoped to phase plus task tools."""

    if not mcp_servers:
        return mcp_servers

    workflow_tools = (
        VERIFIER_WORKFLOW_MCP_TOOLS if phase == "verifying" else BUILDER_WORKFLOW_MCP_TOOLS
    )
    explicit_tools = {
        tool_name for tool_name in (available_tools or []) if tool_name.startswith("orchestrator_")
    }
    scoped_tools = sorted(workflow_tools | explicit_tools)

    return [_scope_server(server, scoped_tools) for server in mcp_servers]


def _scope_server(server: MCPServerConfig, scoped_tools: list[str]) -> MCPServerConfig:
    if server.name != "orchestrator" or not server.url:
        return server
    if "/mcp-scoped/" in server.url:
        return server
    if not server.url.endswith("/mcp/sse"):
        return server

    base_url = server.url.removesuffix("/mcp/sse")
    scope_key = quote(",".join(scoped_tools), safe=",_")
    return server.model_copy(update={"url": f"{base_url}/mcp-scoped/{scope_key}/sse"})


def resolve_mcp_server_cwd(server: MCPServerConfig, working_dir: str | None) -> str | None:
    """Resolve a routine MCP server cwd sentinel to a concrete directory."""

    if server.cwd == "worktree":
        return working_dir
    return None
