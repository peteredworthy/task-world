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


def test_original_all_four_skipped_condition_fails_closed() -> None:
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
        "submit_graph_patch",
    )
    assert "create_corrective_region" not in resolved


def test_one_missing_required_macro_fails_closed() -> None:
    available = ["submit_graph_patch", *RELIABLE_PLAN_REQUIRED_TOOL_NAMES[:-1]]

    with pytest.raises(ReliablePlanToolPreflightError) as raised:
        build_dynamic_tool_specs(context=_context(available))

    assert raised.value.missing_tools == ("create_effectful_batch",)


def test_malformed_required_schema_fails_closed_with_exact_tool() -> None:
    specs = [
        dict(spec)
        for spec in build_dynamic_tool_specs(
            context=_context(["submit_graph_patch", *RELIABLE_PLAN_REQUIRED_TOOL_NAMES])
        )
        if spec["name"] in RELIABLE_PLAN_REQUIRED_TOOL_NAMES
    ]
    malformed = next(spec for spec in specs if spec["name"] == "create_plan_verification")
    malformed["inputSchema"] = {"type": "array"}

    with pytest.raises(ReliablePlanToolPreflightError) as raised:
        validate_reliable_plan_tool_specs(specs)

    assert raised.value.invalid_tools == {
        "create_plan_verification": "inputSchema root type must be object"
    }


def test_required_macro_schema_cannot_omit_a_core_field() -> None:
    specs = [
        dict(spec)
        for spec in build_dynamic_tool_specs(
            context=_context(["submit_graph_patch", *RELIABLE_PLAN_REQUIRED_TOOL_NAMES])
        )
        if spec["name"] in RELIABLE_PLAN_REQUIRED_TOOL_NAMES
    ]
    malformed = next(spec for spec in specs if spec["name"] == "create_effectful_batch")
    malformed_schema = dict(malformed["inputSchema"])
    malformed_schema["required"] = [
        field for field in malformed_schema["required"] if field != "checks"
    ]
    malformed["inputSchema"] = malformed_schema

    with pytest.raises(ReliablePlanToolPreflightError) as raised:
        validate_reliable_plan_tool_specs(specs)

    assert raised.value.invalid_tools == {
        "create_effectful_batch": "missing required fields: checks"
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
        "create_successor_planner",
        {
            "patch_id": "patch-1",
            "base_graph_position": 4,
            "region_id": "horizon-2",
            "evidence_source_node_id": "verify-plan",
            "evidence_source_port": "verification_report",
            "planning_horizon": 2,
        },
    )
    assert calls == [
        {
            "patch_id": "patch-1",
            "base_graph_position": 4,
            "macro_invocations": [
                {
                    "macro": "create_successor_planner",
                    "args": {
                        "region_id": "horizon-2",
                        "evidence_source_node_id": "verify-plan",
                        "evidence_source_port": "verification_report",
                        "planning_horizon": 2,
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
