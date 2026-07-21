"""ASGI dispatcher forwarding /mcp-graph/{token}/... to per-execution MCP apps.

Mirrors the existing ``_ScopedMcpDispatcher`` pattern in ``api/app.py``, but
looks up its sub-apps in a ``GraphMcpExecutionRegistry`` (populated by
``GraphDispatchExecutor`` for exactly the lifetime of one graph-node
execution) instead of lazily building and caching them by tool-allowlist.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry


class GraphMcpDispatcher:
    """Serve per-execution graph MCP servers under ``/mcp-graph/{token}``."""

    def __init__(self, registry: GraphMcpExecutionRegistry) -> None:
        self._registry = registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            response = JSONResponse(
                status_code=404,
                content={"detail": "Graph MCP only supports HTTP transport"},
            )
            await response(scope, receive, send)
            return

        raw_path = str(scope.get("path", "")).strip("/")
        if raw_path.startswith("mcp-graph/"):
            raw_path = raw_path.removeprefix("mcp-graph/")
        token, _, rest = raw_path.partition("/")

        sub_app = self._registry.get(token) if token else None
        if sub_app is None or not rest:
            response = JSONResponse(
                status_code=404,
                content={"detail": "Unknown or expired graph MCP execution token"},
            )
            await response(scope, receive, send)
            return

        root_path = str(scope.get("root_path") or "").rstrip("/")
        if root_path.endswith("/mcp-graph"):
            token_root_path = f"{root_path}/{token}"
        else:
            token_root_path = f"{root_path}/mcp-graph/{token}"
        scoped_scope = dict(scope)
        if rest == "messages":
            scoped_scope["root_path"] = ""
            scoped_scope["path"] = "/messages/"
        elif rest.startswith("messages/"):
            scoped_scope["root_path"] = ""
            scoped_scope["path"] = f"/{rest}"
        else:
            scoped_scope["root_path"] = token_root_path
            scoped_scope["path"] = f"{token_root_path}/{rest}"
        await sub_app(scoped_scope, receive, send)
