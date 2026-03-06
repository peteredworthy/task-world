"""Tests for ExecutionContext step-level fields."""

from orchestrator.runners.types import ExecutionContext
from orchestrator.config.models import MCPServerConfig


class TestExecutionContextStepFields:
    def test_defaults_to_none(self):
        ctx = ExecutionContext(
            run_id="r1",
            task_id="t1",
            working_dir="/tmp",
            prompt="do stuff",
            requirements=["R1"],
        )
        assert ctx.step_id is None
        assert ctx.available_tools is None
        assert ctx.mcp_servers is None

    def test_step_id_populated(self):
        ctx = ExecutionContext(
            run_id="r1",
            task_id="t1",
            working_dir="/tmp",
            prompt="do stuff",
            requirements=["R1"],
            step_id="step-1",
        )
        assert ctx.step_id == "step-1"

    def test_available_tools_populated(self):
        ctx = ExecutionContext(
            run_id="r1",
            task_id="t1",
            working_dir="/tmp",
            prompt="do stuff",
            requirements=["R1"],
            available_tools=["terminal", "file_editor"],
        )
        assert ctx.available_tools == ["terminal", "file_editor"]

    def test_mcp_servers_populated(self):
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        ctx = ExecutionContext(
            run_id="r1",
            task_id="t1",
            working_dir="/tmp",
            prompt="do stuff",
            requirements=["R1"],
            mcp_servers=[mcp],
        )
        assert len(ctx.mcp_servers) == 1
        assert ctx.mcp_servers[0].name == "ctx7"
