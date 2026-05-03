"""Unit tests for MCP tool definitions — pure, zero I/O."""

from orchestrator.api import ORCHESTRATOR_TOOLS


def test_tool_definitions_well_formed() -> None:
    """Verify tool definitions have required fields."""
    assert len(ORCHESTRATOR_TOOLS) == 17

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
        "orchestrator_complete_recovery",
        "orchestrator_request_clarification",
        "orchestrator_escalate_requirement",
        "orchestrator_list_repos",
        "orchestrator_list_branches",
        "orchestrator_create_child_run",
        "orchestrator_list_child_runs",
        "orchestrator_accept_child_run",
        "orchestrator_wait_for_run",
        "orchestrator_get_run_evidence",
        "orchestrator_get_parent_oversight",
        "orchestrator_update_parent_oversight",
        "orchestrator_refresh_parent_oversight",
    }
