"""Regression coverage for reliable-plan planner tool exposure."""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.graph_runtime.graph_mcp_tools import build_graph_mcp_server
from orchestrator.runners import (
    RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
    ReliablePlanToolPreflightError,
    build_dynamic_tool_specs,
    resolve_dispatch_tools,
    validate_reliable_plan_tool_specs,
)
from orchestrator.runners.types import ExecutionContext


def _context(available_tools: list[str]) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-reliable",
        task_id="planner-s-01",
        working_dir="/tmp/reliable-plan",
        prompt="Plan the graph.",
        requirements=[],
        node_kind="planner",
        node_role="planner",
        available_tools=available_tools,
        required_tools=RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
    )


def test_controller_owned_constructor_missing_fails_closed() -> None:
    with pytest.raises(ReliablePlanToolPreflightError) as raised:
        build_dynamic_tool_specs(
            context=_context(["submit_graph_patch"]),
        )

    assert raised.value.missing_tools == RELIABLE_PLAN_REQUIRED_TOOL_NAMES


def test_explicit_allowlist_is_authorized_and_deterministically_ordered() -> None:
    requested = [
        "submit_graph_patch",
        "create_effectful_batch",
        "read_file",
        "create_discovery_region",
        "construct_reliable_plan_region",
        "create_successor_planner",
        "create_plan_verification",
        "create_discovery_region",
        "create_corrective_region",
    ]

    resolved = resolve_dispatch_tools(
        node_kind="planner",
        node_role="planner",
        available_tools=requested,
    )

    assert resolved == (
        "read_file",
        *RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
        "create_discovery_region",
        "create_plan_verification",
        "create_successor_planner",
        "create_effectful_batch",
        "submit_graph_patch",
    )
    assert "create_corrective_region" not in resolved


def test_one_missing_required_macro_fails_closed() -> None:
    available = ["submit_graph_patch", *RELIABLE_PLAN_REQUIRED_TOOL_NAMES[:-1]]

    with pytest.raises(ReliablePlanToolPreflightError) as raised:
        build_dynamic_tool_specs(context=_context(available))

    assert raised.value.missing_tools == ("construct_reliable_plan_region",)


def test_malformed_required_schema_fails_closed_with_exact_tool() -> None:
    specs = [
        dict(spec)
        for spec in build_dynamic_tool_specs(
            context=_context(["submit_graph_patch", *RELIABLE_PLAN_REQUIRED_TOOL_NAMES])
        )
        if spec["name"] in RELIABLE_PLAN_REQUIRED_TOOL_NAMES
    ]
    malformed = next(spec for spec in specs if spec["name"] == "construct_reliable_plan_region")
    malformed["inputSchema"] = {"type": "array"}

    with pytest.raises(ReliablePlanToolPreflightError) as raised:
        validate_reliable_plan_tool_specs(specs)

    assert raised.value.invalid_tools == {
        "construct_reliable_plan_region": "inputSchema root type must be object"
    }


def test_required_macro_schema_cannot_omit_a_core_field() -> None:
    specs = [
        dict(spec)
        for spec in build_dynamic_tool_specs(
            context=_context(["submit_graph_patch", *RELIABLE_PLAN_REQUIRED_TOOL_NAMES])
        )
        if spec["name"] in RELIABLE_PLAN_REQUIRED_TOOL_NAMES
    ]
    malformed = next(spec for spec in specs if spec["name"] == "construct_reliable_plan_region")
    malformed_schema = dict(malformed["inputSchema"])
    malformed_schema["required"] = [
        field for field in malformed_schema["required"] if field != "checks"
    ]
    malformed["inputSchema"] = malformed_schema

    with pytest.raises(ReliablePlanToolPreflightError) as raised:
        validate_reliable_plan_tool_specs(specs)

    assert raised.value.invalid_tools == {
        "construct_reliable_plan_region": "missing required fields: checks"
    }


async def test_shared_graph_mcp_registers_and_routes_reliable_macros() -> None:
    calls: list[dict[str, Any]] = []

    async def receive_patch(payload: dict[str, Any]) -> str:
        calls.append(payload)
        return "accepted"

    allowed = ["submit_graph_patch", *RELIABLE_PLAN_REQUIRED_TOOL_NAMES]
    mcp = build_graph_mcp_server(
        receive_patch,
        None,
        allowed_tools=allowed,
        required_tools=RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
    )
    names = tuple(mcp._tool_manager._tools)
    assert names == (
        "submit_graph_patch",
        *RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
    )

    await mcp.call_tool(
        "construct_reliable_plan_region",
        {
            "patch_id": "patch-1",
            "base_graph_position": 4,
            "operation_key": "batch-2-attempt-1",
            "scope": "batch-2",
            "objective": "Implement batch 2.",
            "requirement_ids": ["REQ-2"],
            "dependencies": ["batch-1"],
            "acceptance": ["batch 2 passes"],
            "checks": [
                {
                    "name": "project tests",
                    "command_binding": "dynamic_feature_hidden_oracle",
                }
            ],
            "rubric": ["REQ-2 is satisfied"],
        },
    )
    assert calls == [
        {
            "patch_id": "patch-1",
            "base_graph_position": 4,
            "macro_invocations": [
                {
                    "macro": "construct_reliable_plan_region",
                    "args": {
                        "operation_key": "batch-2-attempt-1",
                        "scope": "batch-2",
                        "objective": "Implement batch 2.",
                        "requirement_ids": ["REQ-2"],
                        "dependencies": ["batch-1"],
                        "acceptance": ["batch 2 passes"],
                        "checks": [
                            {
                                "name": "project tests",
                                "command_binding": "dynamic_feature_hidden_oracle",
                            }
                        ],
                        "rubric": ["REQ-2 is satisfied"],
                    },
                }
            ],
        }
    ]


def test_ordinary_unknown_optional_tool_keeps_warning_and_skip(
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = ExecutionContext(
        run_id="ordinary",
        task_id="planner",
        working_dir="/tmp/ordinary",
        prompt="Plan.",
        requirements=[],
        node_kind="planner",
        node_role="planner",
        available_tools=["unknown_optional_tool"],
    )

    specs = build_dynamic_tool_specs(context=context)

    assert "unknown_optional_tool" in caplog.text
    assert "unknown_optional_tool" not in {spec["name"] for spec in specs}
