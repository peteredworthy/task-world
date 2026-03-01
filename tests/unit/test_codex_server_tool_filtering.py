"""Tests for Codex Server phase filtering, step tools, and MCP wiring."""

import logging

from orchestrator.agents.codex_server_common import build_dynamic_tool_specs
from orchestrator.agents.types import ExecutionContext


def _make_context(**overrides) -> ExecutionContext:
    defaults = dict(
        run_id="r1",
        task_id="t1",
        working_dir="/tmp",
        prompt="test",
        requirements=["R1"],
        available_tools=None,
        mcp_servers=None,
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


class TestCodexPhaseFiltering:
    def test_builder_no_grade(self):
        specs = build_dynamic_tool_specs(is_verifier=False)
        names = {s["name"] for s in specs}
        assert "grade" not in names
        assert "set_grade" not in names

    def test_verifier_has_grade(self):
        specs = build_dynamic_tool_specs(is_verifier=True)
        names = {s["name"] for s in specs}
        # grade or set_grade should be present
        assert "grade" in names or "set_grade" in names

    def test_common_tools_always_present(self):
        for is_verifier in [True, False]:
            specs = build_dynamic_tool_specs(is_verifier=is_verifier)
            names = {s["name"] for s in specs}
            assert "update_checklist" in names
            assert "submit" in names


class TestCodexStepTools:
    def test_unknown_tool_warning(self, caplog):
        ctx = _make_context(available_tools=["nonexistent"])
        with caplog.at_level(logging.WARNING):
            build_dynamic_tool_specs(is_verifier=False, context=ctx)
        assert "nonexistent" in caplog.text

    def test_no_context_backward_compat(self):
        specs = build_dynamic_tool_specs(is_verifier=False)
        assert len(specs) > 0  # Returns standard tools
