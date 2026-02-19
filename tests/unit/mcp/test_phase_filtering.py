"""Unit tests for MCP phase-based tool filtering."""

import pytest

from orchestrator.mcp.server import BUILDER_TOOLS, OrchestratorMCPServer


class _NoOpHandler:
    async def handle(self, tool_name: str, args: dict[str, object]) -> dict[str, object]:
        raise AssertionError(f"Unexpected call: {tool_name} with {args}")


def test_builder_phase_excludes_set_grade_tool() -> None:
    server = OrchestratorMCPServer(handler=_NoOpHandler(), phase="building")

    names = server.tool_names()
    assert "orchestrator_set_grade" not in names


def test_verifier_phase_excludes_update_checklist_tool() -> None:
    server = OrchestratorMCPServer(handler=_NoOpHandler(), phase="verifying")

    names = server.tool_names()
    assert "orchestrator_update_checklist" not in names


def test_invalid_phase_raises_value_error() -> None:
    with pytest.raises(ValueError, match="phase must be one of: building, verifying"):
        OrchestratorMCPServer(handler=_NoOpHandler(), phase="unknown")  # type: ignore[arg-type]


def test_default_phase_is_building_toolset() -> None:
    server = OrchestratorMCPServer(handler=_NoOpHandler())

    assert set(server.tool_names()) == BUILDER_TOOLS
