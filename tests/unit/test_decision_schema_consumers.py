"""Behavioral coverage for decision-v1 schema consumers and tool precedence."""

from __future__ import annotations

import inspect
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import BaseModel, ConfigDict, ValidationError
import pytest

from orchestrator.graph import (
    BATCH_DECISION_SCHEMA_ID,
    BATCH_DECISION_SCHEMA_VERSION,
    DECISION_PLAN_SCHEMA_ID,
    DECISION_PLAN_SCHEMA_VERSION,
    batch_decision_schema,
    build_projection,
    decision_plan_declaration,
    node_payload_view,
)
from orchestrator.graph_runtime import GraphDispatchContext
from orchestrator.graph_runtime.dispatch import (
    _prompt_for_node,
    _prompt_summary_for_node,
    _submission_contract,
)
from orchestrator.graph_runtime import graph_mcp_tools
from orchestrator.graph_runtime.graph_mcp_tools import build_graph_mcp_server
from orchestrator.runners import (
    CLIAgent,
    ExecutionContext,
    RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
    SubmissionAcknowledgement,
    SubmissionContract,
    SubmissionOutputContract,
    build_codex_server_prompt,
    build_dynamic_tool_specs,
    resolve_dispatch_tools,
    submission_prompt_instruction,
    submission_tool_input_schema,
)
from tests.unit.test_graph_decisions import decision_successor_events


_STALE_MUTATION_TOOLS = [
    "construct_reliable_plan_region",
    "submit_graph_patch",
    "create_effectful_batch",
]


def test_graph_mcp_adapter_uses_only_public_fastmcp_and_runner_boundaries() -> None:
    source = inspect.getsource(graph_mcp_tools)

    assert "._tool_manager" not in source
    assert ".fn_metadata" not in source
    assert "from orchestrator.runners.types" not in source


def _compiled_successor_context() -> GraphDispatchContext:
    events = decision_successor_events()
    projection = build_projection(events)
    return GraphDispatchContext(
        run_id="run-1",
        node_id="planner-plan",
        node_kind="planner",
        node_role="planner",
        node_payload=dict(node_payload_view(projection, "planner-plan")),
        requirements=["Implement the bounded requirement."],
        worktree_path="/tmp/worktree",
        lease_id="lease-1",
        lease_generation=1,
        execution_id="execution-1",
        base_snapshot_id="snapshot-1",
        dispatch_event_id="dispatch-1",
        graph_projection=projection,
        graph_events=events,
    )


def _batch_decision_contract() -> SubmissionContract:
    return SubmissionContract(
        interaction_contract="decision-v1",
        outputs=(
            SubmissionOutputContract(
                port="decision",
                schema_name="BatchDecision",
                semantic_schema_id=BATCH_DECISION_SCHEMA_ID,
                semantic_schema_version=BATCH_DECISION_SCHEMA_VERSION,
                # The explicit interaction marker, not provider-local schema
                # metadata, classifies this submission.
                semantic_role="legacy-looking-role",
                content_json_schema=batch_decision_schema(),
            ),
        ),
    )


def _implementation_plan_contract() -> SubmissionContract:
    return SubmissionContract(
        interaction_contract="decision-v1",
        outputs=(
            SubmissionOutputContract(
                port="semantic_artifact",
                schema_name="ImplementationPlan",
                semantic_schema_id=DECISION_PLAN_SCHEMA_ID,
                semantic_schema_version=DECISION_PLAN_SCHEMA_VERSION,
                semantic_role="implementation_plan",
                content_json_schema=decision_plan_declaration().json_schema,
            ),
        ),
    )


def _execution_context(contract: SubmissionContract) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        execution_id="execution-1",
        task_id="planner-plan",
        working_dir="/tmp/worktree",
        prompt="Use the supplied question and bounded evidence.",
        requirements=["Assess the selected batch."],
        node_kind="planner",
        node_role="planner",
        graph_mcp_url="http://localhost:8000/mcp-graph/token/sse",
        available_tools=list(_STALE_MUTATION_TOOLS),
        required_tools=RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
        submission_contract=contract,
    )


def test_submission_contract_marker_defaults_legacy_and_rejects_unknown_values() -> None:
    assert SubmissionContract().interaction_contract == "legacy"
    with pytest.raises(ValidationError, match="interaction_contract"):
        SubmissionContract.model_validate({"interaction_contract": "decision-v2"})


def test_provider_metadata_cannot_select_decision_mode() -> None:
    legacy = SubmissionContract(
        outputs=(
            SubmissionOutputContract(
                port="decision",
                schema_name="BatchDecision",
                semantic_role="batch_decision",
                content_json_schema=batch_decision_schema(),
            ),
        )
    )
    names = [spec["name"] for spec in build_dynamic_tool_specs(context=_execution_context(legacy))]

    assert legacy.interaction_contract == "legacy"
    assert "construct_reliable_plan_region" in names


def test_compiled_successor_uses_a_decision_packet_and_generated_batch_schema() -> None:
    context = _compiled_successor_context()
    contract = _submission_contract(context)

    assert contract is not None
    assert contract.interaction_contract == "decision-v1"
    assert contract.outputs[0].content_json_schema == batch_decision_schema()

    prompt = _prompt_for_node(context)
    assert "Decision packet:" in prompt
    assert '"question": "How should the selected verified implementation batch proceed?"' in prompt
    assert '"bound_evidence"' in prompt
    assert '"available_choices": ["proceed", "revise_plan", "blocked"]' in prompt
    assert '"answer_schema"' in prompt
    assert '"implementation_notes"' in prompt
    for internal_or_legacy_term in (
        "routine-snapshot-record",
        "accepted-decision-plan",
        "plan-passed",
        "requirement-record-1",
        "planner-plan",
        "patch_id",
        "base_graph_position",
        "construct_reliable_plan_region",
        "submit_graph_patch",
        "plain submit",
    ):
        assert internal_or_legacy_term not in prompt

    summary = _prompt_summary_for_node(context)
    assert summary["packet_type"] == "decision_packet"
    assert summary["packet_keys"] == [
        "answer_schema",
        "available_choices",
        "bound_evidence",
        "question",
    ]
    assert summary["prompt_sections"] == [
        "decision_question",
        "bound_evidence",
        "available_choices",
        "answer_schema",
        "typed_submit",
    ]


def test_shared_dispatch_tool_resolution_gives_decision_mode_precedence() -> None:
    assert resolve_dispatch_tools(
        node_kind="planner",
        node_role="planner",
        available_tools=[*_STALE_MUTATION_TOOLS, "read_evidence"],
        reliable_plan=True,
        decision_submission=True,
    ) == ("read_evidence",)


class _SentinelDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disposition: Literal["proceed"]
    implementation_notes: str
    canonical_schema_sentinel: str


@pytest.mark.asyncio
async def test_one_contract_propagates_a_generated_field_to_prompt_codex_and_fastmcp() -> None:
    calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(_payload: dict[str, Any]) -> str:
        return "unused"

    async def on_submit(args: dict[str, Any]) -> SubmissionAcknowledgement:
        calls.append(args)
        return SubmissionAcknowledgement(disposition="durably_staged", message="staged")

    contract = SubmissionContract(
        interaction_contract="decision-v1",
        outputs=(
            SubmissionOutputContract(
                port="decision",
                schema_name="SentinelDecision",
                semantic_role="not-used-for-classification",
                content_json_schema=_SentinelDecision.model_json_schema(),
            ),
        ),
    )
    canonical = submission_tool_input_schema(contract)
    context = _execution_context(contract)

    rendered = submission_prompt_instruction(contract)
    codex_prompt = build_codex_server_prompt(context)
    codex_submit = next(
        spec for spec in build_dynamic_tool_specs(context=context) if spec["name"] == "submit"
    )
    assert "canonical_schema_sentinel" in rendered
    assert "canonical_schema_sentinel" in codex_prompt
    assert codex_submit["inputSchema"] == canonical

    mcp = build_graph_mcp_server(
        on_submit_graph_patch,
        None,
        allowed_tools=_STALE_MUTATION_TOOLS,
        required_tools=RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
        on_submit=on_submit,
        submission_contract=contract,
    )
    fastmcp_submit = next(tool for tool in await mcp.list_tools() if tool.name == "submit")
    assert fastmcp_submit.inputSchema == canonical
    valid = {
        "outputs": {
            "decision": {
                "disposition": "proceed",
                "implementation_notes": "",
                "canonical_schema_sentinel": "owned once",
            }
        }
    }
    await mcp.call_tool("submit", valid)
    with pytest.raises(ToolError):
        await mcp.call_tool(
            "submit",
            {
                "outputs": {
                    "decision": {
                        "disposition": "proceed",
                        "implementation_notes": "",
                    }
                }
            },
        )
    assert calls == [valid]


@pytest.mark.asyncio
async def test_decision_precedence_removes_stale_mutation_tools_and_sequences() -> None:
    calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(_payload: dict[str, Any]) -> str:
        raise AssertionError("decision catalog must not route graph mutation")

    async def on_submit(args: dict[str, Any]) -> SubmissionAcknowledgement:
        calls.append(args)
        return SubmissionAcknowledgement(disposition="durably_staged", message="staged")

    contract = _batch_decision_contract()
    context = _execution_context(contract)
    codex_names = [spec["name"] for spec in build_dynamic_tool_specs(context=context)]
    assert codex_names == ["submit"]

    codex_prompt = build_codex_server_prompt(context)
    claude_prompt = CLIAgent.build_prompt(context.prompt, context)
    for rendered in (codex_prompt, claude_prompt):
        assert "supplied question and bounded evidence" in rendered
        assert "**submit**(outputs=...)" in rendered
        assert "construct_reliable_plan_region" not in rendered
        assert "submit_graph_patch" not in rendered
        assert "update_checklist" not in rendered
        assert "plain submit" not in rendered.lower()
        assert "accepted construction" not in rendered.lower()

    mcp = build_graph_mcp_server(
        on_submit_graph_patch,
        None,
        allowed_tools=_STALE_MUTATION_TOOLS,
        required_tools=RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
        on_submit=on_submit,
        submission_contract=contract,
    )
    assert {tool.name for tool in await mcp.list_tools()} == {"submit"}


_VALID = {
    "outputs": {
        "decision": {
            "disposition": "proceed",
            "implementation_notes": "Use the existing parser.",
        }
    }
}


@pytest.mark.parametrize(
    "arguments",
    [
        {"outputs": {"decision": {"disposition": "proceed"}}},
        {"outputs": {"decision": {"disposition": "invented"}}},
        {
            "outputs": {
                "decision": {
                    "disposition": "proceed",
                    "implementation_notes": "",
                    "unexpected": True,
                }
            }
        },
        {"outputs": {"unknown": {"disposition": "proceed"}}},
        {**_VALID, "unexpected": True},
    ],
    ids=[
        "missing-branch-field",
        "unknown-disposition",
        "inner-extra",
        "unknown-output",
        "top-level-extra",
    ],
)
@pytest.mark.asyncio
async def test_codex_and_fastmcp_share_complete_submit_validation(
    arguments: dict[str, Any],
) -> None:
    callback_calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(_payload: dict[str, Any]) -> str:
        return "unused"

    async def on_submit(args: dict[str, Any]) -> SubmissionAcknowledgement:
        callback_calls.append(args)
        return SubmissionAcknowledgement(disposition="durably_staged", message="staged")

    contract = _batch_decision_contract()
    canonical = submission_tool_input_schema(contract)
    codex_submit = next(
        spec
        for spec in build_dynamic_tool_specs(context=_execution_context(contract))
        if spec["name"] == "submit"
    )
    assert codex_submit["inputSchema"] == canonical
    assert canonical["additionalProperties"] is False

    mcp = build_graph_mcp_server(
        on_submit_graph_patch,
        None,
        allowed_tools=_STALE_MUTATION_TOOLS,
        required_tools=RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
        on_submit=on_submit,
        submission_contract=contract,
    )
    fastmcp_submit = next(tool for tool in await mcp.list_tools() if tool.name == "submit")
    assert fastmcp_submit.inputSchema == canonical

    codex_validator = Draft202012Validator(codex_submit["inputSchema"])
    with pytest.raises(JsonSchemaValidationError):
        codex_validator.validate(arguments)
    with pytest.raises(ToolError):
        await mcp.call_tool("submit", arguments)
    assert callback_calls == []


@pytest.mark.asyncio
async def test_codex_and_fastmcp_accept_the_same_valid_decision() -> None:
    callback_calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(_payload: dict[str, Any]) -> str:
        return "unused"

    async def on_submit(args: dict[str, Any]) -> SubmissionAcknowledgement:
        callback_calls.append(args)
        return SubmissionAcknowledgement(disposition="durably_staged", message="staged")

    contract = _batch_decision_contract()
    canonical = submission_tool_input_schema(contract)
    context = _execution_context(contract)
    codex_submit = next(
        spec for spec in build_dynamic_tool_specs(context=context) if spec["name"] == "submit"
    )
    Draft202012Validator(codex_submit["inputSchema"]).validate(_VALID)

    mcp = build_graph_mcp_server(
        on_submit_graph_patch,
        None,
        allowed_tools=_STALE_MUTATION_TOOLS,
        required_tools=RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
        on_submit=on_submit,
        submission_contract=contract,
    )
    await mcp.call_tool("submit", _VALID)

    assert codex_submit["inputSchema"] == canonical
    assert (
        next(tool for tool in await mcp.list_tools() if tool.name == "submit").inputSchema
        == canonical
    )
    assert callback_calls == [_VALID]


@pytest.mark.parametrize(
    "command_definition",
    [
        {"argv": ["tool", ""]},
        {"argv": [" ", "arg"], "cmd": "true"},
        {"argv": [], "command": "true"},
    ],
    ids=[
        "empty-trailing-argv",
        "invalid-argv-falls-back-to-cmd",
        "empty-argv-falls-back-to-command",
    ],
)
@pytest.mark.asyncio
async def test_codex_catalog_and_connected_fastmcp_accept_authoritative_command_forms(
    command_definition: dict[str, Any],
) -> None:
    callback_calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(_payload: dict[str, Any]) -> str:
        return "unused"

    async def on_submit(args: dict[str, Any]) -> SubmissionAcknowledgement:
        callback_calls.append(args)
        return SubmissionAcknowledgement(disposition="durably_staged", message="staged")

    arguments = {
        "outputs": {
            "semantic_artifact": {
                "summary": "Preserve the accepted command invocation semantics.",
                "batches": [
                    {
                        "key": "command-schema",
                        "objective": "Keep discovery transport aligned with dispatch.",
                        "scope": ["src/orchestrator/graph/command_bindings.py"],
                        "requirements": ["r1"],
                        "acceptance": ["Both decision transports accept the plan."],
                        "checks": [
                            {
                                "name": "authoritative command form",
                                "command_definition": command_definition,
                            }
                        ],
                    }
                ],
            }
        }
    }
    contract = _implementation_plan_contract()
    canonical = submission_tool_input_schema(contract)
    codex_submit = next(
        spec
        for spec in build_dynamic_tool_specs(context=_execution_context(contract))
        if spec["name"] == "submit"
    )
    assert codex_submit["inputSchema"] == canonical
    Draft202012Validator(codex_submit["inputSchema"]).validate(arguments)

    mcp = build_graph_mcp_server(
        on_submit_graph_patch,
        None,
        on_submit=on_submit,
        submission_contract=contract,
    )
    async with create_connected_server_and_client_session(mcp) as client:
        listed = await client.list_tools()
        fastmcp_submit = next(tool for tool in listed.tools if tool.name == "submit")
        assert fastmcp_submit.inputSchema == canonical

        result = await client.call_tool("submit", arguments)

    assert result.isError is False
    assert callback_calls == [arguments]


@pytest.mark.asyncio
async def test_decision_adapter_applies_schema_and_validation_through_mcp_protocol() -> None:
    callback_calls: list[dict[str, Any]] = []

    async def on_submit_graph_patch(_payload: dict[str, Any]) -> str:
        return "unused"

    async def on_submit(args: dict[str, Any]) -> SubmissionAcknowledgement:
        callback_calls.append(args)
        return SubmissionAcknowledgement(disposition="durably_staged", message="staged")

    contract = _batch_decision_contract()
    mcp = build_graph_mcp_server(
        on_submit_graph_patch,
        None,
        on_submit=on_submit,
        submission_contract=contract,
    )

    async with create_connected_server_and_client_session(mcp) as client:
        listed = await client.list_tools()
        submit = next(tool for tool in listed.tools if tool.name == "submit")
        assert submit.inputSchema == submission_tool_input_schema(contract)

        invalid_result = await client.call_tool("submit", {**_VALID, "unexpected": True})
        assert invalid_result.isError is True
        assert callback_calls == []

        valid_result = await client.call_tool("submit", _VALID)
        assert valid_result.isError is False
        assert callback_calls == [_VALID]
