"""Behavioral coverage for typed advisory submissions."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator
from mcp.shared.memory import create_connected_server_and_client_session

from orchestrator.graph import RecoveryPlanValue
from orchestrator.graph_runtime import GraphDispatchContext
from orchestrator.graph_runtime.dispatch import (
    _semantic_output_records_from_submit_args,
    _submission_contract,
)
from orchestrator.graph_runtime.graph_mcp_tools import build_graph_mcp_server
from orchestrator.runners import (
    CLIAgent,
    ExecutionContext,
    build_codex_server_prompt,
    build_dynamic_tool_specs,
    submission_tool_input_schema,
)


def _context(kind: str = "oversight") -> GraphDispatchContext:
    node_id = f"{kind}-1"
    return GraphDispatchContext(
        run_id="run-1",
        node_id=node_id,
        node_kind=kind,
        node_role="oversight" if kind in {"appeal", "oversight"} else "recovery",
        node_payload={
            "node_id": node_id,
            "kind": kind,
            "role": "oversight" if kind in {"appeal", "oversight"} else "recovery",
            "task_region_id": "advisory-region",
            "attempt_number": 2,
            "max_attempts": 3,
            "outputs": [
                {
                    "port": "recovery_plan",
                    "direction": "output",
                    "schema": "RecoveryPlan",
                    "required": True,
                }
            ],
        },
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-1",
        lease_generation=1,
        execution_id="execution-1",
        base_snapshot_id="snapshot-1",
        dispatch_event_id="dispatch-1",
    )


def _execution_context(contract: Any, *, kind: str = "oversight") -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        execution_id="execution-1",
        task_id="advisory-region",
        working_dir="/tmp/worktree",
        prompt="Review the supplied failure and advise the controller.",
        requirements=[],
        node_kind=kind,
        node_role="oversight" if kind in {"appeal", "oversight"} else "recovery",
        api_base_url="http://localhost:8000",
        available_tools=["submit_graph_patch", "update_checklist", "request_clarification"],
        submission_contract=contract,
    )


def _valid_plan() -> dict[str, Any]:
    return {
        "action": "pause",
        "responsible_actor": "oversight",
        "graph_changes": [],
        "reason": "A human decision is required.",
        "attempt_number": 2,
        "max_attempts": 3,
    }


def test_advisory_contract_uses_existing_recovery_plan_schema() -> None:
    contract = _submission_contract(_context())

    assert contract is not None
    assert contract.interaction_contract == "legacy"
    assert contract.requires_arguments is True
    assert [(item.port, item.schema_name, item.record_type) for item in contract.outputs] == [
        ("recovery_plan", "RecoveryPlan", "recovery_plan")
    ]
    assert contract.outputs[0].content_json_schema == RecoveryPlanValue.model_json_schema()


def test_advisory_submission_is_validated_and_runtime_owns_record_identity() -> None:
    context = _context()
    contract = _submission_contract(context)
    assert contract is not None
    arguments = {"outputs": {"recovery_plan": _valid_plan()}}

    Draft202012Validator(submission_tool_input_schema(contract)).validate(arguments)
    records = _semantic_output_records_from_submit_args(context, arguments)

    assert len(records) == 1
    record = records[0]
    assert record["record_id"] == "recovery-plan-execution-1"
    assert record["record_kind"] == "output"
    assert record["record_type"] == "recovery_plan"
    assert record["producer_node_id"] == "oversight-1"
    assert record["value"] == _valid_plan()
    assert record["provenance"] == {
        "source": "agent_submit",
        "execution_id": "execution-1",
    }


def test_advisory_submit_rejects_unknown_authored_fields() -> None:
    context = _context()
    with pytest.raises(ValueError, match="validation failed|extra_forbidden|unknown"):
        _semantic_output_records_from_submit_args(
            context,
            {"outputs": {"recovery_plan": {**_valid_plan(), "node_id": "author-chosen"}}},
        )


@pytest.mark.asyncio
async def test_advisory_fastmcp_uses_shared_schema_without_mutation_tools() -> None:
    context = _context()
    contract = _submission_contract(context)
    assert contract is not None
    calls: list[dict[str, Any]] = []

    async def on_submit(args: dict[str, Any]) -> Any:
        calls.append(args)
        return None

    async def on_submit_graph_patch(_payload: dict[str, Any]) -> str:
        raise AssertionError("advisory submission must not route graph mutations")

    server = build_graph_mcp_server(
        on_submit_graph_patch,
        None,
        allowed_tools=["submit_graph_patch", "create_work_region"],
        on_submit=on_submit,
        submission_contract=contract,
    )
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == {"submit"}
    submit = next(tool for tool in tools if tool.name == "submit")
    assert submit.inputSchema == submission_tool_input_schema(contract)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("submit", {"outputs": {"recovery_plan": _valid_plan()}})
    assert result.isError is False
    assert calls == [{"outputs": {"recovery_plan": _valid_plan()}}]


@pytest.mark.parametrize("kind", ["appeal", "oversight", "recovery"])
def test_advisory_codex_catalog_and_prompt_are_submit_only(kind: str) -> None:
    context = _context(kind)
    contract = _submission_contract(context)
    assert contract is not None
    execution_context = _execution_context(contract, kind=kind)

    assert [spec["name"] for spec in build_dynamic_tool_specs(context=execution_context)] == [
        "submit"
    ]
    codex_prompt = build_codex_server_prompt(execution_context)
    claude_prompt = CLIAgent.build_prompt(execution_context.prompt, execution_context)
    for prompt in (codex_prompt, claude_prompt):
        assert "**submit**(outputs=...)" in prompt
        assert "submit_graph_patch" not in prompt
        assert "update_checklist" not in prompt
        assert "request_clarification" not in prompt
        assert "orchestrator_set_grade" not in prompt
