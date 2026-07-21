"""Unit test for the graph_mcp_url field on ExecutionContext."""

from __future__ import annotations

from orchestrator.runners.types import ExecutionContext


def test_graph_mcp_url_defaults_to_none() -> None:
    ctx = ExecutionContext(
        run_id="r1",
        task_id="t1",
        working_dir="/tmp",
        prompt="do the thing",
        requirements=[],
    )
    assert ctx.graph_mcp_url is None


def test_graph_mcp_url_can_be_set() -> None:
    ctx = ExecutionContext(
        run_id="r1",
        task_id="t1",
        working_dir="/tmp",
        prompt="do the thing",
        requirements=[],
        graph_mcp_url="http://localhost:8000/mcp-graph/abc123/sse",
    )
    assert ctx.graph_mcp_url == "http://localhost:8000/mcp-graph/abc123/sse"
