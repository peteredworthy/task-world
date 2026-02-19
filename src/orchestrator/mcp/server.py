"""MCP server exposing orchestrator tools to external agents.

Uses the mcp SDK's FastMCP for server setup and tool registration.
FastMCP introspects function signatures, so each tool function must
have explicit parameter names matching its schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from mcp.server import FastMCP

from orchestrator.mcp.tools import ORCHESTRATOR_TOOLS, ToolHandler
from orchestrator.workflow.service import WorkflowService

BUILDER_TOOLS = {
    "orchestrator_get_requirements",
    "orchestrator_update_checklist",
    "orchestrator_submit",
    "orchestrator_request_clarification",
    "orchestrator_list_repos",
    "orchestrator_list_branches",
}

VERIFIER_TOOLS = {
    "orchestrator_get_requirements",
    "orchestrator_set_grade",
    "orchestrator_submit",
}


class OrchestratorMCPServer:
    """MCP server that exposes orchestrator tools for external agents.

    External agents (e.g., Cursor, Windsurf) connect to this server
    and use the tools to interact with the orchestrator workflow.
    """

    def __init__(
        self,
        service: WorkflowService | None = None,
        handler: ToolHandler | None = None,
        repos_dir: Path | None = None,
        phase: Literal["building", "verifying"] = "building",
    ) -> None:
        if handler is not None:
            self._handler = handler
        elif service is not None:
            self._handler = ToolHandler(service, repos_dir=repos_dir)
        else:
            raise ValueError("Either service or handler must be provided")
        if phase not in ("building", "verifying"):
            raise ValueError("phase must be one of: building, verifying")

        self.phase: Literal["building", "verifying"] = phase
        self._allowed_tools = BUILDER_TOOLS if self.phase == "building" else VERIFIER_TOOLS
        self._repos_dir = repos_dir
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

        async def orchestrator_request_clarification(
            run_id: str,
            task_id: str,
            questions: list[dict[str, str | list[str]]],
        ) -> str:
            """Request clarification from the human.

            The task will pause until the human answers.
            Answers will be appended to the clarifications artifact file.
            """
            result = await handler.handle(
                "orchestrator_request_clarification",
                {"run_id": run_id, "task_id": task_id, "questions": questions},
            )
            return json.dumps(result)

        if "orchestrator_get_requirements" in self._allowed_tools:
            self._mcp.add_tool(
                orchestrator_get_requirements,
                name="orchestrator_get_requirements",
                description="Get the list of requirements (checklist items) for a task.",
            )
        if "orchestrator_update_checklist" in self._allowed_tools:
            self._mcp.add_tool(
                orchestrator_update_checklist,
                name="orchestrator_update_checklist",
                description="Mark a requirement as done, not applicable, or blocked.",
            )
        if "orchestrator_submit" in self._allowed_tools:
            self._mcp.add_tool(
                orchestrator_submit,
                name="orchestrator_submit",
                description="Submit the task for verification after completing requirements.",
            )
        if "orchestrator_set_grade" in self._allowed_tools:
            self._mcp.add_tool(
                orchestrator_set_grade,
                name="orchestrator_set_grade",
                description="Set a grade for a requirement (used by verifier).",
            )
        if "orchestrator_request_clarification" in self._allowed_tools:
            self._mcp.add_tool(
                orchestrator_request_clarification,
                name="orchestrator_request_clarification",
                description=(
                    "Request clarification from the human. "
                    "The task will pause until the human answers. "
                    "Answers will be appended to the clarifications artifact file."
                ),
            )

        async def orchestrator_list_repos() -> str:
            """List available repositories in the repos directory."""
            result = await handler.handle("orchestrator_list_repos", {})
            return json.dumps(result)

        async def orchestrator_list_branches(
            repo_name: str,
            pattern: str = "",
            local_only: bool = False,
            limit: int = 100,
        ) -> str:
            """List branches in a repository with optional glob pattern filter."""
            result = await handler.handle(
                "orchestrator_list_branches",
                {
                    "repo_name": repo_name,
                    "pattern": pattern,
                    "local_only": local_only,
                    "limit": limit,
                },
            )
            return json.dumps(result)

        if "orchestrator_list_repos" in self._allowed_tools:
            self._mcp.add_tool(
                orchestrator_list_repos,
                name="orchestrator_list_repos",
                description="List available repositories in the repos directory.",
            )
        if "orchestrator_list_branches" in self._allowed_tools:
            self._mcp.add_tool(
                orchestrator_list_branches,
                name="orchestrator_list_branches",
                description="List branches in a repository with optional glob pattern filter.",
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
        await self._mcp.run_sse_async(host=host, port=port)  # type: ignore[call-arg]

    def tool_names(self) -> list[str]:
        """Return list of registered tool names."""
        return [t["name"] for t in ORCHESTRATOR_TOOLS if t["name"] in self._allowed_tools]
