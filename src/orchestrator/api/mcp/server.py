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

from orchestrator.api.mcp.tools import ORCHESTRATOR_TOOLS, ToolHandler
from orchestrator.workflow.service import WorkflowService

BUILDER_TOOLS = {
    "orchestrator_get_requirements",
    "orchestrator_update_checklist",
    "orchestrator_submit",
    "orchestrator_request_clarification",
    "orchestrator_escalate_requirement",
    "orchestrator_list_repos",
    "orchestrator_list_branches",
    "orchestrator_create_child_run",
    "orchestrator_list_child_runs",
    "orchestrator_accept_child_run",
    "orchestrator_wait_for_run",
    "orchestrator_get_run_evidence",
    "orchestrator_get_parent_oversight",
    "orchestrator_update_parent_oversight",
    "orchestrator_refresh_parent_oversight",
}

VERIFIER_TOOLS = {
    "orchestrator_get_requirements",
    "orchestrator_set_grade",
    "orchestrator_submit",
    "orchestrator_complete_recovery",
}

# All tools registered regardless of phase; runtime validation prevents phase-inappropriate calls
ALL_TOOLS = BUILDER_TOOLS | VERIFIER_TOOLS


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
        self._allowed_tools = ALL_TOOLS
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

        # Register all tools regardless of phase; runtime validation prevents phase-inappropriate calls
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
        self._mcp.add_tool(
            orchestrator_request_clarification,
            name="orchestrator_request_clarification",
            description=(
                "Request clarification from the human. "
                "The task will pause until the human answers. "
                "Answers will be appended to the clarifications artifact file."
            ),
        )

        async def orchestrator_complete_recovery(
            run_id: str,
            task_id: str,
            outcome: str,
            notes: str,
        ) -> str:
            """Complete recovery for a task in failure state. Outcome: retry, skip, or abandon."""
            result = await handler.handle(
                "orchestrator_complete_recovery",
                {"run_id": run_id, "task_id": task_id, "outcome": outcome, "notes": notes},
            )
            return json.dumps(result)

        async def orchestrator_escalate_requirement(
            run_id: str,
            task_id: str,
            requirement_id: str,
            reason: str,
        ) -> str:
            """Flag a requirement as unfulfillable and pause the run for human review."""
            result = await handler.handle(
                "orchestrator_escalate_requirement",
                {
                    "run_id": run_id,
                    "task_id": task_id,
                    "requirement_id": requirement_id,
                    "reason": reason,
                },
            )
            return json.dumps(result)

        self._mcp.add_tool(
            orchestrator_complete_recovery,
            name="orchestrator_complete_recovery",
            description=(
                "Complete recovery for a task that entered a failure state. "
                "Choose an outcome: retry, skip, or abandon."
            ),
        )
        self._mcp.add_tool(
            orchestrator_escalate_requirement,
            name="orchestrator_escalate_requirement",
            description="Flag a requirement as unfulfillable and pause the run for human review.",
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

        self._mcp.add_tool(
            orchestrator_list_repos,
            name="orchestrator_list_repos",
            description="List available repositories in the repos directory.",
        )
        self._mcp.add_tool(
            orchestrator_list_branches,
            name="orchestrator_list_branches",
            description="List branches in a repository with optional glob pattern filter.",
        )

        async def orchestrator_create_child_run(
            parent_run_id: str,
            parent_slice_id: str,
            routine_embedded: dict[str, object],
            repo_name: str = "",
            branch: str = "",
            config: dict[str, object] | None = None,
            agent_runner_type: str = "",
            agent_runner_config: dict[str, object] | None = None,
            next_action_decision: str = "continue",
        ) -> str:
            """Create an oversight child run from an embedded routine."""
            args: dict[str, object] = {
                "parent_run_id": parent_run_id,
                "parent_slice_id": parent_slice_id,
                "routine_embedded": routine_embedded,
                "next_action_decision": next_action_decision,
            }
            if repo_name:
                args["repo_name"] = repo_name
            if branch:
                args["branch"] = branch
            if config is not None:
                args["config"] = config
            if agent_runner_type:
                args["agent_runner_type"] = agent_runner_type
            if agent_runner_config is not None:
                args["agent_runner_config"] = agent_runner_config
            result = await handler.handle("orchestrator_create_child_run", args)
            return json.dumps(result)

        async def orchestrator_list_child_runs(parent_run_id: str) -> str:
            """List child runs linked to an oversight parent run."""
            result = await handler.handle(
                "orchestrator_list_child_runs",
                {"parent_run_id": parent_run_id},
            )
            return json.dumps(result)

        async def orchestrator_accept_child_run(parent_run_id: str, child_run_id: str) -> str:
            """Merge an accepted child run into its parent run branch."""
            result = await handler.handle(
                "orchestrator_accept_child_run",
                {"parent_run_id": parent_run_id, "child_run_id": child_run_id},
            )
            return json.dumps(result)

        async def orchestrator_wait_for_run(
            run_id: str,
            timeout_seconds: float = 0,
        ) -> str:
            """Wait for a run to complete, fail, or pause, then return current status."""
            result = await handler.handle(
                "orchestrator_wait_for_run",
                {"run_id": run_id, "timeout_seconds": timeout_seconds},
            )
            return json.dumps(result)

        async def orchestrator_get_run_evidence(run_id: str) -> str:
            """Return structured run.evidence.v1 bundles from a run worktree."""
            result = await handler.handle("orchestrator_get_run_evidence", {"run_id": run_id})
            return json.dumps(result)

        async def orchestrator_get_parent_oversight(run_id: str) -> str:
            """Return the persisted super-parent oversight snapshot."""
            result = await handler.handle("orchestrator_get_parent_oversight", {"run_id": run_id})
            return json.dumps(result)

        async def orchestrator_update_parent_oversight(
            run_id: str,
            current_understanding: dict[str, object] | None = None,
            target_inventory: list[dict[str, object]] | None = None,
            final_validation: dict[str, object] | None = None,
            decisions: list[dict[str, object]] | None = None,
            decision: dict[str, object] | None = None,
        ) -> str:
            """Persist parent-authored super-parent oversight facts."""
            args: dict[str, object] = {"run_id": run_id}
            if current_understanding is not None:
                args["current_understanding"] = current_understanding
            if target_inventory is not None:
                args["target_inventory"] = target_inventory
            if final_validation is not None:
                args["final_validation"] = final_validation
            if decisions is not None:
                args["decisions"] = decisions
            if decision is not None:
                args["decision"] = decision
            result = await handler.handle("orchestrator_update_parent_oversight", args)
            return json.dumps(result)

        async def orchestrator_refresh_parent_oversight(run_id: str) -> str:
            """Recompute and persist the super-parent oversight snapshot."""
            result = await handler.handle(
                "orchestrator_refresh_parent_oversight",
                {"run_id": run_id},
            )
            return json.dumps(result)

        self._mcp.add_tool(
            orchestrator_create_child_run,
            name="orchestrator_create_child_run",
            description="Create an oversight child run from an embedded routine.",
        )
        self._mcp.add_tool(
            orchestrator_list_child_runs,
            name="orchestrator_list_child_runs",
            description="List child runs linked to an oversight parent run.",
        )
        self._mcp.add_tool(
            orchestrator_accept_child_run,
            name="orchestrator_accept_child_run",
            description="Merge an accepted child run into its parent run branch.",
        )
        self._mcp.add_tool(
            orchestrator_wait_for_run,
            name="orchestrator_wait_for_run",
            description="Wait for a run to complete, fail, or pause, then return current status.",
        )
        self._mcp.add_tool(
            orchestrator_get_run_evidence,
            name="orchestrator_get_run_evidence",
            description="Return structured run.evidence.v1 bundles from a run worktree.",
        )
        self._mcp.add_tool(
            orchestrator_get_parent_oversight,
            name="orchestrator_get_parent_oversight",
            description="Return the persisted super-parent oversight snapshot.",
        )
        self._mcp.add_tool(
            orchestrator_update_parent_oversight,
            name="orchestrator_update_parent_oversight",
            description="Persist parent-authored super-parent oversight facts.",
        )
        self._mcp.add_tool(
            orchestrator_refresh_parent_oversight,
            name="orchestrator_refresh_parent_oversight",
            description="Recompute and persist the super-parent oversight snapshot.",
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
