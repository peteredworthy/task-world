"""Unit tests for the per-execution graph MCP tool server builder."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
import pytest

from orchestrator.graph import (
    BATCH_DECISION_SCHEMA_ID,
    BATCH_DECISION_SCHEMA_VERSION,
    batch_decision_schema,
    canonical_decision_answer,
)
from orchestrator.graph_runtime.graph_mcp_tools import build_graph_mcp_server
from orchestrator.runners import (
    SubmissionAcknowledgement,
    SubmissionContract,
    SubmissionOutputContract,
    submission_tool_input_schema,
)


async def _tool_names(mcp: FastMCP) -> set[str]:
    return {tool.name for tool in await mcp.list_tools()}


async def test_builder_server_has_submit_graph_patch_and_macro_tools_but_not_grade() -> None:
    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        return "ok"

    mcp = build_graph_mcp_server(on_submit_graph_patch, None)
    names = await _tool_names(mcp)
    assert "submit_graph_patch" in names
    assert "create_work_region" in names
    assert "attach_verifier" in names
    assert "graph_grade" not in names


async def test_verifier_server_has_graph_grade_tool() -> None:
    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        return "ok"

    async def on_grade(req_id: str, grade: str, grade_reason: str | None) -> None:
        return None

    mcp = build_graph_mcp_server(on_submit_graph_patch, on_grade)
    assert "graph_grade" in await _tool_names(mcp)


@pytest.mark.parametrize(
    ("disposition", "message"),
    [
        ("rejected", "submission rejected: acceptance command failed"),
        ("durably_staged", "durably staged; pending runner completion and not yet accepted"),
        ("finalized_accepted", "submission is durably finalized and accepted"),
    ],
)
async def test_semantic_worker_server_exposes_three_way_submit_acknowledgement(
    disposition: str,
    message: str,
) -> None:
    calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        return "ok"

    async def on_submit(args: dict[str, Any]) -> SubmissionAcknowledgement:
        calls.append(args)
        return SubmissionAcknowledgement.model_validate(
            {
                "disposition": disposition,
                "message": message,
                "execution_id": "execution-1",
                "graph_position": 12,
            }
        )

    contract = SubmissionContract(
        outputs=(
            SubmissionOutputContract(
                port="semantic_artifact",
                schema_name="SemanticArtifact",
                semantic_schema_id="plan",
                semantic_schema_version=1,
                semantic_role="implementation_plan",
                content_json_schema={
                    "type": "object",
                    "required": ["batches"],
                    "properties": {"batches": {"type": "array"}},
                },
            ),
        )
    )
    mcp = build_graph_mcp_server(
        on_submit_graph_patch,
        None,
        allowed_tools=[],
        on_submit=on_submit,
        submission_contract=contract,
    )

    assert await _tool_names(mcp) == {"submit"}
    submit_tool = next(tool for tool in await mcp.list_tools() if tool.name == "submit")
    assert submit_tool.inputSchema["title"] == "submitArguments"
    assert "additionalProperties" not in submit_tool.inputSchema
    assert submit_tool.inputSchema["required"] == ["outputs"]
    outputs_schema = submit_tool.inputSchema["properties"]["outputs"]
    assert outputs_schema["required"] == ["semantic_artifact"]
    assert outputs_schema["additionalProperties"] is False
    assert outputs_schema["properties"]["semantic_artifact"] == {
        "type": "object",
        "required": ["batches"],
        "properties": {"batches": {"type": "array"}},
    }
    result = await mcp.call_tool(
        "submit",
        {
            "outputs": {"semantic_artifact": {"batches": [{"batch_id": "b1"}]}},
            "legacy_extra": True,
        },
    )
    assert calls == [{"outputs": {"semantic_artifact": {"batches": [{"batch_id": "b1"}]}}}]
    rendered = " ".join(str(item) for item in result)
    assert disposition in rendered
    assert message in rendered


async def test_decision_submit_schema_is_self_contained_and_matches_codex_contract() -> None:
    calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        return "ok"

    async def on_submit(args: dict[str, Any]) -> SubmissionAcknowledgement:
        calls.append(args)
        canonical_decision_answer("batch_decision", args["outputs"]["decision"])
        return SubmissionAcknowledgement(
            disposition="durably_staged",
            message="staged",
            execution_id="execution-1",
            graph_position=12,
        )

    contract = SubmissionContract(
        interaction_contract="decision-v1",
        outputs=(
            SubmissionOutputContract(
                port="decision",
                schema_name="BatchDecision",
                semantic_schema_id=BATCH_DECISION_SCHEMA_ID,
                semantic_schema_version=BATCH_DECISION_SCHEMA_VERSION,
                semantic_role="batch_decision",
                content_json_schema=batch_decision_schema(),
            ),
        ),
    )
    canonical = submission_tool_input_schema(contract)
    mcp = build_graph_mcp_server(
        on_submit_graph_patch,
        None,
        allowed_tools=[],
        on_submit=on_submit,
        submission_contract=contract,
    )
    submit_tool = next(tool for tool in await mcp.list_tools() if tool.name == "submit")

    assert submit_tool.inputSchema["required"] == canonical["required"]
    assert submit_tool.inputSchema["properties"]["outputs"]["required"] == ["decision"]
    assert (
        submit_tool.inputSchema["properties"]["outputs"]["properties"]["decision"]
        == canonical["properties"]["outputs"]["properties"]["decision"]
    )
    assert '"$ref"' not in str(submit_tool.inputSchema)
    valid = {
        "outputs": {
            "decision": {
                "disposition": "proceed",
                "implementation_notes": "Implement the selected batch.",
            }
        }
    }
    await mcp.call_tool("submit", valid)
    invalid = {"outputs": {"decision": {"disposition": "invented"}}}
    assert calls == [valid]
    with pytest.raises(ToolError, match="disposition"):
        await mcp.call_tool(
            "submit",
            invalid,
        )
    assert calls == [valid, invalid]


async def test_verifier_empty_allowlist_does_not_expose_planner_macros() -> None:
    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        return "ok"

    async def on_grade(req_id: str, grade: str, grade_reason: str | None) -> None:
        return None

    mcp = build_graph_mcp_server(
        on_submit_graph_patch,
        on_grade,
        allowed_tools=[],
    )

    assert await _tool_names(mcp) == {"graph_grade"}


async def test_submit_graph_patch_tool_calls_the_closure() -> None:
    calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        calls.append(payload)
        return "graph patch p1 accepted"

    mcp = build_graph_mcp_server(on_submit_graph_patch, None)
    result = await mcp.call_tool(
        "submit_graph_patch",
        {"patch_id": "p1", "base_graph_position": 1, "ops": []},
    )
    assert calls == [{"patch_id": "p1", "base_graph_position": 1, "ops": []}]
    assert any("accepted" in str(item) for item in result)


async def test_submit_graph_patch_advertises_typed_flat_envelope_without_defaults() -> None:
    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        return "ok"

    mcp = build_graph_mcp_server(on_submit_graph_patch, None)
    tool = next(tool for tool in await mcp.list_tools() if tool.name == "submit_graph_patch")
    schema = tool.inputSchema

    assert schema["required"] == ["patch_id", "base_graph_position"]
    assert "patch" not in schema["properties"]
    assert schema["properties"]["patch_id"]["type"] == "string"
    assert schema["properties"]["base_graph_position"]["type"] == "integer"
    assert schema["properties"]["ops"]["type"] == "array"
    assert schema["properties"]["macro_invocations"]["type"] == "array"
    assert schema["properties"]["rationale_record_id"]["type"] == "string"
    assert all(
        "default" not in property_schema for property_schema in schema["properties"].values()
    )
    assert "omitted" not in str(schema).lower()


async def test_submit_graph_patch_preserves_atomic_macro_invocation_order() -> None:
    calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        calls.append(payload)
        return "graph patch skeleton accepted"

    invocations = [
        {"macro": "create_discovery_region", "args": {"region_id": "discovery"}},
        {"macro": "create_plan_verification", "args": {"region_id": "verification"}},
        {"macro": "create_successor_planner", "args": {"region_id": "successor"}},
    ]
    mcp = build_graph_mcp_server(on_submit_graph_patch, None)
    result = await mcp.call_tool(
        "submit_graph_patch",
        {
            "patch_id": "skeleton",
            "base_graph_position": 7,
            "macro_invocations": invocations,
        },
    )

    assert calls == [
        {
            "patch_id": "skeleton",
            "base_graph_position": 7,
            "macro_invocations": invocations,
        }
    ]
    assert any("accepted" in str(item) for item in result)


async def test_submit_graph_patch_preserves_explicit_null_ops() -> None:
    calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        calls.append(payload)
        return "rejected"

    mcp = build_graph_mcp_server(on_submit_graph_patch, None)
    await mcp.call_tool(
        "submit_graph_patch",
        {"patch_id": "p-null", "base_graph_position": 7, "ops": None},
    )

    assert calls == [{"patch_id": "p-null", "base_graph_position": 7, "ops": None}]


async def test_create_work_region_tool_normalizes_and_calls_the_closure() -> None:
    calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        calls.append(payload)
        return "graph patch p1 accepted"

    mcp = build_graph_mcp_server(on_submit_graph_patch, None)
    await mcp.call_tool(
        "create_work_region",
        {"patch_id": "p1", "base_graph_position": 1, "region_id": "r1"},
    )
    assert calls == [
        {
            "patch_id": "p1",
            "base_graph_position": 1,
            "macro_invocations": [{"macro": "create_work_region", "args": {"region_id": "r1"}}],
        }
    ]


async def test_graph_grade_tool_calls_the_closure() -> None:
    calls: list[tuple[str, str, str | None]] = []

    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        return "ok"

    async def on_grade(req_id: str, grade: str, grade_reason: str | None) -> None:
        calls.append((req_id, grade, grade_reason))

    mcp = build_graph_mcp_server(on_submit_graph_patch, on_grade)
    await mcp.call_tool("graph_grade", {"req_id": "R-01", "grade": "A", "grade_reason": "Good"})
    assert calls == [("R-01", "A", "Good")]
