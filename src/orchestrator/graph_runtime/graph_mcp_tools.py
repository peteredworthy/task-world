"""Builds a per-execution FastMCP tool server for a graph-dispatched node.

Each graph-dispatched claude_cli execution gets a fresh instance of this
server (see ``GraphDispatchExecutor._run_agent``), with every tool handler
closing directly over that execution's ``on_submit_graph_patch``/``on_grade``
callables — the same closures codex_server's in-process JSON-RPC session
already awaits directly today. All graph-patch tools funnel through the
shared ``graph_tool_routing.route_tool_call`` so the normalization logic
(macro-tool -> patch envelope) is identical to codex_server's.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any, cast

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import Tool
from pydantic import WithJsonSchema

from orchestrator.graph import (
    reliable_plan_check_decision_tool_schema,
    reliable_plan_dependencies_tool_schema,
)
from orchestrator.runners import submission_tool_input_schema, validate_reliable_plan_tool_specs
from orchestrator.runners.graph_tool_routing import route_tool_call
from orchestrator.runners.types import (
    GradeCallback,
    GraphPatchCallback,
    SubmissionContract,
    SubmissionAcknowledgement,
    SubmitCallback,
)

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
        "construct_reliable_plan_region",
        "create_discovery_region",
        "create_plan_verification",
        "create_successor_planner",
        "create_effectful_batch",
        "graph_grade",
    }
)


_OMITTED = object()

_GRAPH_PATCH_OPS_SCHEMA = {
    "type": "array",
    "items": {"type": "object"},
}
_GRAPH_PATCH_MACROS_SCHEMA = {
    "type": "array",
    "items": {"type": "object"},
}
_STRING_SCHEMA = {"type": "string"}


async def _noop_checklist(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _noop_submit(*_args: Any, **_kwargs: Any) -> None:
    return None


def build_graph_mcp_server(
    on_submit_graph_patch: GraphPatchCallback,
    on_grade: GradeCallback | None,
    *,
    allowed_tools: Sequence[str] | None = None,
    required_tools: Sequence[str] = (),
    on_submit: SubmitCallback | None = None,
    submission_contract: SubmissionContract | None = None,
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
    enabled_tools = frozenset(allowed_tools) if allowed_tools is not None else _GRAPH_MCP_ALLOWLIST
    concrete_specs: list[dict[str, Any]] = []

    def _add_tool(function: Any, *, name: str, description: str) -> None:
        if name in enabled_tools or name == "graph_grade":
            mcp.add_tool(function, name=name, description=description)
            concrete_specs.append(
                {
                    "name": name,
                    "inputSchema": Tool.from_function(
                        function, name=name, description=description
                    ).parameters,
                }
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

    if submission_contract is not None and submission_contract.requires_arguments:
        contract_summary = ", ".join(
            f"{output.port}: {output.schema_name} "
            f"{output.semantic_schema_id}@{output.semantic_schema_version}"
            for output in submission_contract.outputs
            if output.content_json_schema is not None
        )

        async def submit(outputs: dict[str, Any]) -> str:
            """Submit model-authored content keyed by the required output port."""
            callback = on_submit or _noop_submit
            typed_callback = cast(
                Callable[[dict[str, Any] | None], Awaitable[SubmissionAcknowledgement | None]],
                callback,
            )
            acknowledgement = await typed_callback({"outputs": outputs})
            return (
                acknowledgement.model_dump_json()
                if acknowledgement is not None
                else '{"disposition":"durably_staged","message":"submission is durably staged and pending runner completion; it is not yet accepted"}'
            )

        input_schema = submission_tool_input_schema(submission_contract)
        outputs_schema = cast(
            dict[str, Any],
            cast(dict[str, Any], input_schema["properties"])["outputs"],
        )
        submit.__annotations__["outputs"] = Annotated[
            dict[str, Any], WithJsonSchema(outputs_schema)
        ]

        mcp.add_tool(
            submit,
            name="submit",
            description=f"Submit required graph outputs. Contract: {contract_summary}",
        )

    async def submit_graph_patch(
        patch_id: str,
        base_graph_position: int,
        ops: Annotated[Any, WithJsonSchema(_GRAPH_PATCH_OPS_SCHEMA)] = _OMITTED,
        macro_invocations: Annotated[Any, WithJsonSchema(_GRAPH_PATCH_MACROS_SCHEMA)] = _OMITTED,
        rationale_record_id: Annotated[Any, WithJsonSchema(_STRING_SCHEMA)] = _OMITTED,
    ) -> str:
        """Submit one atomic graph patch envelope of raw ops and/or macros."""
        values = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "ops": ops,
            "macro_invocations": macro_invocations,
            "rationale_record_id": rationale_record_id,
        }
        args = {key: value for key, value in values.items() if value is not _OMITTED}
        return await _route("submit_graph_patch", args)

    _add_tool(
        submit_graph_patch,
        name="submit_graph_patch",
        description=(
            "Submit one atomic graph patch envelope of validated low-level ops and/or "
            "macro_invocations. Use macro_invocations when several reliable-plan regions "
            "must be accepted transactionally."
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
        objective: str | None = None,
        access_mode: str | None = None,
        acceptance: list[str] | None = None,
        access_mode_override_justification: str | None = None,
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
        if objective is not None:
            args["objective"] = objective
        if access_mode is not None:
            args["access_mode"] = access_mode
        if acceptance is not None:
            args["acceptance"] = acceptance
        if access_mode_override_justification is not None:
            args["access_mode_override_justification"] = access_mode_override_justification
        return await _route("create_work_region", args)

    _add_tool(
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
        objective: str | None = None,
        access_mode: str | None = None,
        acceptance: list[str] | None = None,
        access_mode_override_justification: str | None = None,
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
        if objective is not None:
            args["objective"] = objective
        if access_mode is not None:
            args["access_mode"] = access_mode
        if acceptance is not None:
            args["acceptance"] = acceptance
        if access_mode_override_justification is not None:
            args["access_mode_override_justification"] = access_mode_override_justification
        return await _route("create_corrective_region", args)

    _add_tool(
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

    _add_tool(
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

    _add_tool(
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

    _add_tool(
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

    _add_tool(
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

    _add_tool(
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

    _add_tool(
        retire_or_supersede,
        name="retire_or_supersede",
        description="Retire or supersede an existing graph node.",
    )

    async def construct_reliable_plan_region(
        patch_id: str,
        base_graph_position: int,
        operation_key: str,
        scope: str,
        objective: str,
        requirement_ids: list[str],
        acceptance: list[str],
        checks: list[dict[str, Any]],
        rubric: list[str],
        dependencies: list[str] | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Construct one complete reliable-plan region from semantic work decisions."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "operation_key": operation_key,
            "scope": scope,
            "objective": objective,
            "requirement_ids": requirement_ids,
            "acceptance": acceptance,
            "checks": checks,
            "rubric": rubric,
        }
        if dependencies is not None:
            args["dependencies"] = dependencies
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("construct_reliable_plan_region", args)

    check_decision_schema = reliable_plan_check_decision_tool_schema()
    construct_reliable_plan_region.__annotations__["checks"] = Annotated[
        list[dict[str, Any]],
        WithJsonSchema(
            {
                "type": "array",
                "description": (
                    "May be empty for initial discovery; effectful horizons require "
                    "at least one mechanical check."
                ),
                "items": check_decision_schema,
            }
        ),
    ]
    construct_reliable_plan_region.__annotations__["dependencies"] = Annotated[
        list[str] | None,
        WithJsonSchema(reliable_plan_dependencies_tool_schema()),
    ]

    _add_tool(
        construct_reliable_plan_region,
        name="construct_reliable_plan_region",
        description=(
            "Construct the complete reliable-plan horizon from semantic work decisions; "
            "the controller derives graph identities and all execution mechanics."
        ),
    )

    async def create_discovery_region(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        semantic_schema_id: str,
        semantic_schema_version: int,
        objective: str,
        acceptance: list[str],
        worker_id: str | None = None,
        requirement_source_node_ids: list[str] | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create a read-only discovery region with a declared semantic output."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
            "semantic_schema_id": semantic_schema_id,
            "semantic_schema_version": semantic_schema_version,
            "objective": objective,
            "acceptance": acceptance,
        }
        if worker_id is not None:
            args["worker_id"] = worker_id
        if requirement_source_node_ids is not None:
            args["requirement_source_node_ids"] = requirement_source_node_ids
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("create_discovery_region", args)

    _add_tool(
        create_discovery_region,
        name="create_discovery_region",
        description="Create a read-only discovery region with a declared semantic output.",
    )

    async def create_plan_verification(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        artifact_source_node_id: str,
        semantic_schema_id: str,
        semantic_schema_version: int,
        objective: str,
        acceptance: list[str],
        rubric: list[str],
        verifier_id: str | None = None,
        requirement_source_node_ids: list[str] | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create independent verification for a declared semantic plan artifact."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
            "artifact_source_node_id": artifact_source_node_id,
            "semantic_schema_id": semantic_schema_id,
            "semantic_schema_version": semantic_schema_version,
            "objective": objective,
            "acceptance": acceptance,
            "rubric": rubric,
        }
        if verifier_id is not None:
            args["verifier_id"] = verifier_id
        if requirement_source_node_ids is not None:
            args["requirement_source_node_ids"] = requirement_source_node_ids
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("create_plan_verification", args)

    _add_tool(
        create_plan_verification,
        name="create_plan_verification",
        description="Create independent verification for a declared semantic plan artifact.",
    )

    async def create_successor_planner(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        evidence_source_node_id: str,
        evidence_source_port: str,
        planning_horizon: int,
        node_id: str | None = None,
        semantic_schema_id: str | None = None,
        semantic_schema_version: int | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create one successor planning horizon from accepted semantic evidence."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
            "evidence_source_node_id": evidence_source_node_id,
            "evidence_source_port": evidence_source_port,
            "planning_horizon": planning_horizon,
        }
        if node_id is not None:
            args["node_id"] = node_id
        if semantic_schema_id is not None:
            args["semantic_schema_id"] = semantic_schema_id
        if semantic_schema_version is not None:
            args["semantic_schema_version"] = semantic_schema_version
        if rationale_record_id is not None:
            args["rationale_record_id"] = rationale_record_id
        return await _route("create_successor_planner", args)

    _add_tool(
        create_successor_planner,
        name="create_successor_planner",
        description="Create one successor planning horizon from accepted semantic evidence.",
    )

    async def create_effectful_batch(
        patch_id: str,
        base_graph_position: int,
        region_id: str,
        batch_id: str,
        plan_source_node_id: str,
        plan_verification_source_node_id: str,
        semantic_schema_id: str,
        semantic_schema_version: int,
        objective: str,
        acceptance: list[str],
        checks: list[dict[str, Any]],
        rubric: list[str],
        planning_horizon: int,
        worker_id: str | None = None,
        verifier_id: str | None = None,
        requirement_source_node_ids: list[str] | None = None,
        accepted_plan_amendment_record_id: str | None = None,
        rationale_record_id: str | None = None,
    ) -> str:
        """Create one declared implementation batch with checks and verification."""
        args: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": base_graph_position,
            "region_id": region_id,
            "batch_id": batch_id,
            "plan_source_node_id": plan_source_node_id,
            "plan_verification_source_node_id": plan_verification_source_node_id,
            "semantic_schema_id": semantic_schema_id,
            "semantic_schema_version": semantic_schema_version,
            "objective": objective,
            "acceptance": acceptance,
            "checks": checks,
            "rubric": rubric,
            "planning_horizon": planning_horizon,
        }
        for key, value in (
            ("worker_id", worker_id),
            ("verifier_id", verifier_id),
            ("requirement_source_node_ids", requirement_source_node_ids),
            ("accepted_plan_amendment_record_id", accepted_plan_amendment_record_id),
            ("rationale_record_id", rationale_record_id),
        ):
            if value is not None:
                args[key] = value
        return await _route("create_effectful_batch", args)

    _add_tool(
        create_effectful_batch,
        name="create_effectful_batch",
        description="Create one declared implementation batch with checks and verification.",
    )

    if on_grade is not None:

        async def graph_grade(req_id: str, grade: str, grade_reason: str | None = None) -> str:
            """Set a grade on a requirement (verifier phase only)."""
            return await _route(
                "grade", {"req_id": req_id, "grade": grade, "grade_reason": grade_reason}
            )

        _add_tool(
            graph_grade,
            name="graph_grade",
            description="Set a grade on a requirement (verifier phase only).",
        )

    if required_tools:
        validate_reliable_plan_tool_specs(concrete_specs)
    return mcp
