"""In-memory registry of live per-execution graph MCP ASGI apps.

Populated by ``GraphDispatchExecutor`` for the lifetime of one claude_cli
graph-node execution and read by ``api.mcp.graph_dispatcher`` to forward
incoming HTTP requests to the right execution's tool handlers. Deliberately
framework-free (no Starlette/FastAPI imports) so ``graph_runtime`` stays
decoupled from the web layer.
"""

from __future__ import annotations

from typing import Any


class GraphMcpExecutionRegistry:
    """Maps an unguessable per-execution token to its live ASGI MCP app."""

    def __init__(self) -> None:
        self._apps: dict[str, Any] = {}

    def register(self, token: str, asgi_app: Any) -> None:
        self._apps[token] = asgi_app

    def unregister(self, token: str) -> None:
        self._apps.pop(token, None)

    def get(self, token: str) -> Any | None:
        return self._apps.get(token)
