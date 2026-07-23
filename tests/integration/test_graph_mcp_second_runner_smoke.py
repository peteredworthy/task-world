"""End-to-end smoke test: a real per-execution graph MCP tool server,
registered under a real token in GraphMcpExecutionRegistry, served through
the real GraphMcpDispatcher.

This composes Tasks 4-6, each already unit-tested in isolation:
- Task 4: GraphMcpExecutionRegistry
- Task 5: GraphMcpDispatcher (tested there only against a fake sub-app)
- Task 6: build_graph_mcp_server (tested there only via mcp.call_tool
  in-process, never served over HTTP)

Matches the existing rigor level this codebase already accepts for its
shipped /mcp and /mcp-scoped mounts (see test_mcp_sse.py): confirms the
route resolves and serves the SSE transport, not a full JSON-RPC
handshake-and-call round trip (which none of the existing MCP integration
tests in this repo attempt either).
"""

from __future__ import annotations

from typing import Any

import anyio
from httpx import ASGITransport, AsyncClient

from orchestrator.api import GraphMcpDispatcher
from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry
from orchestrator.graph_runtime.graph_mcp_tools import build_graph_mcp_server


async def _noop_submit_graph_patch(payload: dict[str, Any]) -> str:
    return "accepted"


async def test_real_graph_mcp_server_is_reachable_through_the_real_dispatcher() -> None:
    registry = GraphMcpExecutionRegistry()
    mcp = build_graph_mcp_server(_noop_submit_graph_patch, None)
    token = "smoke-test-token"
    registry.register(token, mcp.sse_app(mount_path="/"))
    dispatcher = GraphMcpDispatcher(registry)

    transport = ASGITransport(app=dispatcher)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
        with anyio.move_on_after(0.2):
            async with client.stream("GET", f"/mcp-graph/{token}/sse") as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers.get("content-type", "")

        messages_response = await client.post(f"/mcp-graph/{token}/messages/", content=b"{}")
        assert messages_response.status_code != 404


async def test_unknown_token_is_never_reachable() -> None:
    registry = GraphMcpExecutionRegistry()
    dispatcher = GraphMcpDispatcher(registry)
    transport = ASGITransport(app=dispatcher)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
        resp = await client.get("/mcp-graph/never-registered/sse")
    assert resp.status_code == 404
