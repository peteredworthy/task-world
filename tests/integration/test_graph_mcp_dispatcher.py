"""Integration tests for the per-execution graph MCP dispatcher route."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from orchestrator.api import GraphMcpDispatcher
from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry


def _fake_sub_app() -> Starlette:
    async def handler(request: object) -> PlainTextResponse:
        return PlainTextResponse("ok-from-fake-sub-app")

    return Starlette(routes=[Route("/sse", handler)])


async def test_unknown_token_returns_404() -> None:
    registry = GraphMcpExecutionRegistry()
    dispatcher = GraphMcpDispatcher(registry)
    transport = ASGITransport(app=dispatcher)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/mcp-graph/unknown-token/sse")
    assert resp.status_code == 404


async def test_registered_token_forwards_to_its_app() -> None:
    registry = GraphMcpExecutionRegistry()
    registry.register("tok1", _fake_sub_app())
    dispatcher = GraphMcpDispatcher(registry)
    transport = ASGITransport(app=dispatcher)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/mcp-graph/tok1/sse")
    assert resp.status_code == 200
    assert resp.text == "ok-from-fake-sub-app"


async def test_unregistering_then_calling_returns_404() -> None:
    registry = GraphMcpExecutionRegistry()
    registry.register("tok1", _fake_sub_app())
    registry.unregister("tok1")
    dispatcher = GraphMcpDispatcher(registry)
    transport = ASGITransport(app=dispatcher)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/mcp-graph/tok1/sse")
    assert resp.status_code == 404
