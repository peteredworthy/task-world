"""MCP server exposing orchestrator tools to external agents.

Uses the mcp SDK's FastMCP for server setup and tool registration.
FastMCP introspects function signatures, so each tool function must
have explicit parameter names matching its schema.
"""

from __future__ import annotations

import json

from mcp.server import FastMCP

from orchestrator.mcp.tools import ORCHESTRATOR_TOOLS, ToolHandler
from orchestrator.workflow.service import WorkflowService


class OrchestratorMCPServer:
    """MCP server that exposes orchestrator tools for external agents.

    External agents (e.g., Cursor, Windsurf) connect to this server
    and use the tools to interact with the orchestrator workflow.
    """

    def __init__(
        self,
        service: WorkflowService | None = None,
        handler: ToolHandler | None = None,
    ) -> None:
        if handler is not None:
            self._handler = handler
        elif service is not None:
            self._handler = ToolHandler(service)
        else:
            raise ValueError("Either service or handler must be provided")
        self._mcp = FastMCP(
            name="orchestrator",
            instructions=(
                "Orchestrator MCP server. Use the provided tools to manage "
                "task requirements, update checklists, submit work, and set grades."
            ),
        )
        self._register_tools()

    def _register_tools(self) -> None:
        """Register orchestrator tools with the MCP server.

        Each tool function has explicit parameters so FastMCP can
        introspect the signature correctly.
        """
        handler = self._handler

        async def orchestrator_get_requirements(run_id: str, task_id: str) -> str:
            """Get the list of requirements (checklist items) for a task."""
            result = await handler.handle(
                "orchestrator_get_requirements",
                {"run_id": run_id, "task_id": task_id},
            )
            return json.dumps(result)

        async def orchestrator_update_checklist(
            run_id: str,
            task_id: str,
            req_id: str,
            status: str,
            note: str = "",
        ) -> str:
            """Mark a requirement as done, not applicable, or blocked."""
            args = {"run_id": run_id, "task_id": task_id, "req_id": req_id, "status": status}
            if note:
                args["note"] = note
            result = await handler.handle("orchestrator_update_checklist", args)
            return json.dumps(result)

        async def orchestrator_submit(run_id: str, task_id: str) -> str:
            """Submit the task for verification after completing requirements."""
            result = await handler.handle(
                "orchestrator_submit",
                {"run_id": run_id, "task_id": task_id},
            )
            return json.dumps(result)

        async def orchestrator_set_grade(
            run_id: str,
            task_id: str,
            req_id: str,
            grade: str,
            grade_reason: str = "",
        ) -> str:
            """Set a grade for a requirement (used by verifier)."""
            args = {
                "run_id": run_id,
                "task_id": task_id,
                "req_id": req_id,
                "grade": grade,
            }
            if grade_reason:
                args["grade_reason"] = grade_reason
            result = await handler.handle("orchestrator_set_grade", args)
            return json.dumps(result)

        self._mcp.add_tool(
            orchestrator_get_requirements,
            name="orchestrator_get_requirements",
            description="Get the list of requirements (checklist items) for a task.",
        )
        self._mcp.add_tool(
            orchestrator_update_checklist,
            name="orchestrator_update_checklist",
            description="Mark a requirement as done, not applicable, or blocked.",
        )
        self._mcp.add_tool(
            orchestrator_submit,
            name="orchestrator_submit",
            description="Submit the task for verification after completing requirements.",
        )
        self._mcp.add_tool(
            orchestrator_set_grade,
            name="orchestrator_set_grade",
            description="Set a grade for a requirement (used by verifier).",
        )

    @property
    def mcp(self) -> FastMCP:
        """Access the underlying FastMCP instance."""
        return self._mcp

    @property
    def sse_app(self) -> object:
        """Return a Starlette ASGI app for SSE transport.

        Mount this in FastAPI with ``app.mount("/mcp", mcp_server.sse_app)``.
        The app exposes ``/sse`` for the SSE endpoint and ``/messages/``
        for sending messages.
        """
        return self._mcp.sse_app()

    async def run_stdio(self) -> None:
        """Run the MCP server over stdio transport."""
        await self._mcp.run_stdio_async()

    async def run_sse(
        self,
        host: str = "0.0.0.0",
        port: int = 8001,
    ) -> None:
        """Run the MCP server over SSE transport (standalone).

        For mounting inside FastAPI, use the ``sse_app`` property instead.
        """
        await self._mcp.run_sse_async(host=host, port=port)

    def tool_names(self) -> list[str]:
        """Return list of registered tool names."""
        return [t["name"] for t in ORCHESTRATOR_TOOLS]
