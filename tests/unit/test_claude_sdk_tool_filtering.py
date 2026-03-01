"""Tests for Claude SDK agent tool filtering."""

import logging

import pytest

from orchestrator.agents.claude_sdk import _build_tool_list


class TestClaudeSDKToolFiltering:
    """Test cases for _build_tool_list() function."""

    def test_builder_tools_when_none(self) -> None:
        """With available_tools=None, builder gets all builder tools."""
        tools = _build_tool_list(is_verifier=False, available_tools=None)
        names = {t["name"] for t in tools}
        assert "submit" in names
        assert "update_checklist" in names
        assert "request_clarification" in names
        assert "grade" not in names  # Builder doesn't get grade

    def test_verifier_tools_when_none(self) -> None:
        """With available_tools=None, verifier gets all verifier tools."""
        tools = _build_tool_list(is_verifier=True, available_tools=None)
        names = {t["name"] for t in tools}
        assert "grade" in names
        assert "submit" in names
        assert "update_checklist" in names
        assert "request_clarification" in names

    def test_unknown_tool_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unknown tools in available_tools produce a warning."""
        with caplog.at_level(logging.WARNING):
            tools = _build_tool_list(is_verifier=False, available_tools=["nonexistent_tool"])
        assert "nonexistent_tool" in caplog.text
        assert "Unknown tool" in caplog.text
        # Should still have all base tools
        names = {t["name"] for t in tools}
        assert "submit" in names
        assert "update_checklist" in names

    def test_phase_tools_always_included(self) -> None:
        """Step tools never remove phase tools."""
        tools = _build_tool_list(is_verifier=False, available_tools=["nonexistent"])
        names = {t["name"] for t in tools}
        assert "submit" in names
        assert "update_checklist" in names
        assert "request_clarification" in names

    def test_empty_available_tools(self) -> None:
        """With empty available_tools list, returns only phase tools."""
        tools = _build_tool_list(is_verifier=False, available_tools=[])
        names = {t["name"] for t in tools}
        assert "submit" in names
        assert "update_checklist" in names
        assert len(tools) == 3  # submit, update_checklist, request_clarification

    def test_verifier_has_grade(self) -> None:
        """Verifier phase includes grade tool."""
        tools = _build_tool_list(is_verifier=True, available_tools=None)
        names = {t["name"] for t in tools}
        assert "grade" in names

    def test_builder_no_grade(self) -> None:
        """Builder phase never includes grade tool."""
        tools = _build_tool_list(is_verifier=False, available_tools=None)
        names = {t["name"] for t in tools}
        assert "grade" not in names

    def test_tools_are_deep_copied(self) -> None:
        """Modifying returned tools doesn't affect the base tools."""
        tools1 = _build_tool_list(is_verifier=False, available_tools=None)
        tools2 = _build_tool_list(is_verifier=False, available_tools=None)
        # Should have the same content
        assert len(tools1) == len(tools2)
        # But modifying one shouldn't affect the other
        if tools1:
            tools1[0]["test_key"] = "test_value"
            assert "test_key" not in tools2[0]
