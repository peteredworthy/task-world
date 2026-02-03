"""Unit tests for MCP tool definitions — pure, zero I/O."""

from orchestrator.mcp.tools import ORCHESTRATOR_TOOLS


def test_tool_definitions_well_formed() -> None:
    """Verify tool definitions have required fields."""
    assert len(ORCHESTRATOR_TOOLS) == 4

    for tool in ORCHESTRATOR_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"
        assert "properties" in tool["inputSchema"]
        assert "required" in tool["inputSchema"]

    names = {t["name"] for t in ORCHESTRATOR_TOOLS}
    assert names == {
        "orchestrator_get_requirements",
        "orchestrator_update_checklist",
        "orchestrator_submit",
        "orchestrator_set_grade",
    }
