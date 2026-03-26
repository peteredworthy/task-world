"""Unit tests for MCP server tool registration.

All tools are registered regardless of phase. Runtime validation prevents phase-inappropriate calls.
"""

import pytest

from orchestrator.api import ALL_TOOLS, OrchestratorMCPServer


class _NoOpHandler:
    async def handle(self, tool_name: str, args: dict[str, object]) -> dict[str, object]:
        raise AssertionError(f"Unexpected call: {tool_name} with {args}")


def test_builder_phase_registers_all_tools() -> None:
    """Builder phase now registers all tools including set_grade.

    Runtime validation prevents phase-inappropriate calls.
    """
    server = OrchestratorMCPServer(handler=_NoOpHandler(), phase="building")

    names = server.tool_names()
    # All tools should be registered
    assert "orchestrator_set_grade" in names
    assert "orchestrator_update_checklist" in names


def test_verifier_phase_registers_all_tools() -> None:
    """Verifier phase registers all tools including update_checklist.

    Runtime validation prevents phase-inappropriate calls.
    """
    server = OrchestratorMCPServer(handler=_NoOpHandler(), phase="verifying")

    names = server.tool_names()
    # All tools should be registered
    assert "orchestrator_update_checklist" in names
    assert "orchestrator_set_grade" in names


def test_invalid_phase_raises_value_error() -> None:
    with pytest.raises(ValueError, match="phase must be one of: building, verifying"):
        OrchestratorMCPServer(handler=_NoOpHandler(), phase="unknown")  # type: ignore[arg-type]


def test_all_tools_registered() -> None:
    """All tools are registered regardless of phase."""
    server = OrchestratorMCPServer(handler=_NoOpHandler())

    assert set(server.tool_names()) == ALL_TOOLS
