"""Tool allowlist checks for the super-parent routine."""

from pathlib import Path

from orchestrator.api import ORCHESTRATOR_TOOLS
from orchestrator.config import load_routine_from_path


def test_super_parent_tools_are_task_scoped_and_known() -> None:
    routine = load_routine_from_path(Path("routines/super-parent/routine.yaml"))
    known_tool_names = {tool["name"] for tool in ORCHESTRATOR_TOOLS}
    tasks_with_mcp = 0
    tasks_with_codesight = 0

    for step in routine.steps:
        assert step.available_tools is None
        assert step.mcp_servers is None
        for task in step.tasks:
            if task.mcp_servers:
                tasks_with_mcp += 1
                server_names = {server.name for server in task.mcp_servers}
                if "orchestrator" in server_names:
                    assert task.available_tools
                    assert set(task.available_tools).issubset(known_tool_names)
                if "codesight" in server_names:
                    tasks_with_codesight += 1
                    codesight = next(
                        server for server in task.mcp_servers if server.name == "codesight"
                    )
                    assert codesight.command == "npx"
                    assert codesight.args == ["-y", "codesight", "--mcp"]
                    assert codesight.cwd == "worktree"
            else:
                assert task.available_tools is None

    assert tasks_with_mcp == 7
    assert tasks_with_codesight == 7


def test_super_parent_does_not_grant_raw_child_creation_by_default() -> None:
    routine = load_routine_from_path(Path("routines/super-parent/routine.yaml"))
    granted_tools = {
        tool_name
        for step in routine.steps
        for task in step.tasks
        for tool_name in (task.available_tools or [])
    }

    assert "orchestrator_create_child_from_template" in granted_tools
    assert "orchestrator_create_child_run" not in granted_tools
