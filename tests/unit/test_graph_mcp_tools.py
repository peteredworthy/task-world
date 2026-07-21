"""Unit tests for the per-execution graph MCP tool server builder."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from orchestrator.graph_runtime.graph_mcp_tools import build_graph_mcp_server


def _tool_names(mcp: FastMCP) -> set[str]:
    # FastMCP's tool manager keeps registered tools in _tool_manager._tools.
    return set(mcp._tool_manager._tools.keys())  # noqa: SLF001 -- test-only introspection


async def test_builder_server_has_submit_graph_patch_and_macro_tools_but_not_grade() -> None:
    async def on_submit_graph_patch(payload: dict[str, Any]) -> str:
        return "ok"

    mcp = build_graph_mcp_server(on_submit_graph_patch, None)
    names = _tool_names(mcp)
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
    assert "graph_grade" in _tool_names(mcp)


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
