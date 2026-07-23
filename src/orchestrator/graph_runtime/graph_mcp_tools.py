"""Builds a per-execution FastMCP tool server for a graph-dispatched node.

Each graph-dispatched claude_cli execution gets a fresh instance of this
server (see ``GraphDispatchExecutor._run_agent``), with every tool handler
closing directly over that execution's ``on_submit_graph_patch``/``on_grade``
callables — the same closures codex_server's in-process JSON-RPC session
already awaits directly today. All 9 graph-patch tools funnel through the
shared ``graph_tool_routing.route_tool_call`` so the normalization logic
(macro-tool -> patch envelope) is identical to codex_server's.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from orchestrator.runners.graph_tool_routing import route_tool_call
from orchestrator.runners.types import GradeCallback, GraphPatchCallback

_GRAPH_MCP_ALLOWLIST = frozenset(
    {
        "submit_graph_patch",
        "create_work_region",
        "create_corrective_region",
        "attach_verifier",
        "attach_check",
        "create_gap_planner",
        "create_join",
        "request_gate",
        "retire_or_supersede",
        "graph_grade",
    }
)


async def _noop_checklist(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _noop_submit() -> None:
    return None


def build_graph_mcp_server(
    on_submit_graph_patch: GraphPatchCallback,
    on_grade: GradeCallback | None,
) -> FastMCP:
    """Build a fresh MCP server exposing the graph tools for one execution.

    Args:
        on_submit_graph_patch: Closure the graph dispatcher built for this
            specific execution; every graph-patch tool call routes here
            after normalization.
        on_grade: The verifier-phase grade closure, or ``None`` for
            planner/builder executions (in which case ``graph_grade`` is
            not registered at all).
    """
    mcp = FastMCP(
        name="orchestrator-graph-exec",
        instructions=(
            "Graph tools for this single execution. Use submit_graph_patch "
            "or one of the macro tools to propose graph mutations."
        ),
    )

    async def _route(tool_name: str, args: dict[str, Any]) -> str:
        return await route_tool_call(
            tool_name,
            args,
            _noop_checklist,
            _noop_submit,
            on_submit_graph_patch=on_submit_graph_patch,
            on_grade=on_grade,
            allowlist=_GRAPH_MCP_ALLOWLIST | {"grade"},
            agent_label="claude_cli-graph-exec",
        )

    async def submit_graph_patch(
        patch_id: str,
        base_graph_position: int,
        ops: list[dict[str, Any]],
        rationale_record_id: str | None = None,
    ) -> str:
        """Submit a graph patch envelope of raw ops."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "ops": ops,
        }
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("submit_graph_patch", args)

    mcp.add_tool(
        submit_graph_patch,
        name="submit_graph_patch",
        description=(
            "Submit a graph patch envelope of validated low-level ops. "
            "Prefer the macro tools; use this only when no macro expresses "
            "the mutation you need."
        ),
    )

    async def create_work_region(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        worker_id: str | None = None,
        verifier_id: str | None = None,
        candidate_id: str | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create a work region in the graph."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
        }
        if worker_id is not None:
            args["worker_id"] = worker_id
        if verifier_id is not None:
            args["verifier_id"] = verifier_id
        if candidate_id is not None:
            args["candidate_id"] = candidate_id
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("create_work_region", args)

    mcp.add_tool(
        create_work_region,
        name="create_work_region",
        description="Create a work region in the graph.",
    )

    async def create_corrective_region(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        worker_id: str | None = None,
        verifier_id: str | None = None,
        candidate_id: str | None = None,
        classified_gap_source_node_id: str | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create a corrective region in the graph."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
        }
        if worker_id is not None:
            args["worker_id"] = worker_id
        if verifier_id is not None:
            args["verifier_id"] = verifier_id
        if candidate_id is not None:
            args["candidate_id"] = candidate_id
        if classified_gap_source_node_id is not None:
            args["classified_gap_source_node_id"] = classified_gap_source_node_id
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("create_corrective_region", args)

    mcp.add_tool(
        create_corrective_region,
        name="create_corrective_region",
        description="Create a corrective region in the graph.",
    )

    async def attach_verifier(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        verifier_id: str,
        candidate_source_node_id: str | None = None,
        candidate_id: str | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Attach a verifier to the current graph region."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
            "verifier_id": verifier_id,
        }
        if candidate_source_node_id is not None:
            args["candidate_source_node_id"] = candidate_source_node_id
        if candidate_id is not None:
            args["candidate_id"] = candidate_id
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("attach_verifier", args)

    mcp.add_tool(
        attach_verifier,
        name="attach_verifier",
        description="Attach a verifier to the current graph region.",
    )

    async def attach_check(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        check_id: str,
        evidence_source_node_id: str | None = None,
        command_binding: str | None = None,
        hidden_oracle_command: str | None = None,
        command_definition: dict[str, Any] | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Attach a check to the current graph region."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
            "check_id": check_id,
        }
        if evidence_source_node_id is not None:
            args["evidence_source_node_id"] = evidence_source_node_id
        if command_binding is not None:
            args["command_binding"] = command_binding
        if hidden_oracle_command is not None:
            args["hidden_oracle_command"] = hidden_oracle_command
        if command_definition is not None:
            args["command_definition"] = command_definition
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("attach_check", args)

    mcp.add_tool(
        attach_check,
        name="attach_check",
        description="Attach a check to the current graph region.",
    )

    async def create_gap_planner(
        patch_id: str,
        base_graph_position: int,
        node_id: str,
        region_id: str,
        evidence_source_node_id: str | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create a gap planner node for the graph."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "node_id": node_id,
            "region_id": region_id,
        }
        if evidence_source_node_id is not None:
            args["evidence_source_node_id"] = evidence_source_node_id
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("create_gap_planner", args)

    mcp.add_tool(
        create_gap_planner,
        name="create_gap_planner",
        description="Create a gap planner node for the graph.",
    )

    async def create_join(
        patch_id: str,
        base_graph_position: int,
        join_id: str,
        source_ids: list[str] | None = None,
        sources: list[dict[str, Any]] | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create a join node in the graph."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "join_id": join_id,
        }
        if source_ids is not None:
            args["source_ids"] = source_ids
        if sources is not None:
            args["sources"] = sources
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("create_join", args)

    mcp.add_tool(
        create_join,
        name="create_join",
        description="Create a join node in the graph.",
    )

    async def request_gate(
        patch_id: str,
        base_graph_position: int,
        node_id: str,
        kind: str | None = None,
        reason: str | None = None,
        requested_authority: list[str] | None = None,
        target_node_id: str | None = None,
        target_region_id: str | None = None,
        expires_at: str | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Request a human gate or authority decision for the current graph node."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "node_id": node_id,
        }
        if kind is not None:
            args["kind"] = kind
        if reason is not None:
            args["reason"] = reason
        if requested_authority is not None:
            args["requested_authority"] = requested_authority
        if target_node_id is not None:
            args["target_node_id"] = target_node_id
        if target_region_id is not None:
            args["target_region_id"] = target_region_id
        if expires_at is not None:
            args["expires_at"] = expires_at
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("request_gate", args)

    mcp.add_tool(
        request_gate,
        name="request_gate",
        description="Request a human gate or authority decision for the current graph node.",
    )

    async def retire_or_supersede(
        patch_id: str,
        base_graph_position: int,
        target_id: str,
        action: str,
        replacement_ops: list[dict[str, Any]] | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Retire or supersede an existing graph node."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "target_id": target_id,
            "action": action,
        }
        if replacement_ops is not None:
            args["replacement_ops"] = replacement_ops
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("retire_or_supersede", args)

    mcp.add_tool(
        retire_or_supersede,
        name="retire_or_supersede",
        description="Retire or supersede an existing graph node.",
    )

    if on_grade is not None:

        async def graph_grade(req_id: str, grade: str, grade_reason: str | None = None) -> str:
            """Set a grade on a requirement (verifier phase only)."""
            return await _route(
                "grade", {"req_id": req_id, "grade": grade, "grade_reason": grade_reason}
            )

        mcp.add_tool(
            graph_grade,
            name="graph_grade",
            description="Set a grade on a requirement (verifier phase only).",
        )

    return mcp
