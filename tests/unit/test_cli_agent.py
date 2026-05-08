"""Tests for CLIAgent construction, info, and prompt building."""

import re
from datetime import timedelta
from typing import Literal

from orchestrator.config.models import NudgerConfig
from orchestrator.config import AgentRunnerType
from orchestrator.runners import CLIAgent
from orchestrator.runners.types import ExecutionContext


def _make_context(
    api_base_url: str | None = None,
    prompt: str = "Do the thing",
    auth_token: str | None = None,
    work_mode: Literal["implementation", "oversight"] = "implementation",
) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt=prompt,
        requirements=["R1"],
        api_base_url=api_base_url,
        auth_token=auth_token,
        work_mode=work_mode,
    )


def test_cli_agent_info() -> None:
    agent = CLIAgent(command="claude")
    assert agent.info.agent_runner_type == AgentRunnerType.CLI_SUBPROCESS
    assert agent.info.name == "claude"


def test_cli_agent_info_codex() -> None:
    agent = CLIAgent(command="codex")
    assert agent.info.name == "codex"


def test_cli_agent_custom_nudger_config() -> None:
    """Custom nudger config is accepted without error."""
    config = NudgerConfig(output_timeout=timedelta(seconds=120), max_nudges=5)
    agent = CLIAgent(command="claude", nudger_config=config)
    assert agent.info.name == "claude"


def test_cli_agent_custom_args() -> None:
    """Custom args are accepted without error."""
    agent = CLIAgent(command="python3", args=["-c", "print('hello')"])
    assert agent.info.name == "python3"


def test_stdin_mode_default_close() -> None:
    """stdin_mode defaults to 'close'."""
    agent = CLIAgent(command="claude")
    assert agent._stdin_mode == "close"  # pyright: ignore[reportPrivateUsage]


def test_stdin_mode_open() -> None:
    """stdin_mode can be set to 'open'."""
    agent = CLIAgent(command="claude", stdin_mode="open")
    assert agent._stdin_mode == "open"  # pyright: ignore[reportPrivateUsage]


def test_callback_channel_default_rest() -> None:
    """callback_channel defaults to 'rest'."""
    agent = CLIAgent(command="claude")
    assert agent._callback_channel == "rest"  # pyright: ignore[reportPrivateUsage]


def test_callback_channel_mcp() -> None:
    """callback_channel can be set to 'mcp'."""
    agent = CLIAgent(command="claude", callback_channel="mcp")
    assert agent._callback_channel == "mcp"  # pyright: ignore[reportPrivateUsage]


def test_model_parameter_none() -> None:
    """When model is None, no --model flag is added to args."""
    agent = CLIAgent(command="claude", args=["-p"])
    assert agent._args == ["-p"]  # pyright: ignore[reportPrivateUsage]


def test_model_parameter_prepended() -> None:
    """When model is set, --model flag is prepended to args."""
    agent = CLIAgent(command="claude", model="claude-4", args=["-p"])
    assert agent._args == ["--model", "claude-4", "-p"]  # pyright: ignore[reportPrivateUsage]


def test_model_parameter_no_args() -> None:
    """When model is set and args is empty, only --model flag is in args."""
    agent = CLIAgent(command="claude", model="gpt-5-mini")
    assert agent._args == ["--model", "gpt-5-mini"]  # pyright: ignore[reportPrivateUsage]


def test_build_prompt_without_api_url() -> None:
    """Without api_base_url, builder phase adds git workflow section to prompt."""
    ctx = _make_context(api_base_url=None, prompt="Original prompt")
    result = CLIAgent.build_prompt("Original prompt", ctx)
    assert "Original prompt" in result
    assert "## Git Workflow" in result
    assert "git add" in result
    assert "git commit" in result


def test_build_prompt_without_api_url_oversight_mode_limits_git_workflow() -> None:
    """Oversight builders get coordination-only git instructions."""
    ctx = _make_context(api_base_url=None, prompt="Original prompt", work_mode="oversight")
    result = CLIAgent.build_prompt("Original prompt", ctx)

    assert "Original prompt" in result
    assert "commit only allowed oversight artifacts" in result
    assert "Do not edit or commit source code, tests, dependency files" in result
    assert "commit your changes to git" not in result


def test_build_prompt_without_api_url_verifier_phase_unchanged() -> None:
    """Without api_base_url, verifier phase returns prompt unchanged (no git section)."""
    ctx = _make_context(api_base_url=None, prompt="Original prompt")
    result = CLIAgent.build_prompt("Original prompt", ctx, phase="verifying")
    assert result == "Original prompt"


def test_build_prompt_with_api_url() -> None:
    """With api_base_url, prompt is enriched with REST API instructions."""
    ctx = _make_context(api_base_url="http://localhost:8000")
    result = CLIAgent.build_prompt("Do the thing", ctx)

    assert "Do the thing" in result
    assert "Orchestrator Integration" in result
    assert "REST API Endpoints" in result
    assert "http://localhost:8000" in result
    assert "run-1" in result
    assert "task-1" in result
    assert "PATCH" in result
    assert "POST" in result
    assert "GET" in result
    assert "/checklist/" in result
    assert "/submit" in result


def test_build_prompt_with_api_url_oversight_mode_limits_workflow() -> None:
    """Oversight builders with API access are told not to implement source/test changes."""
    ctx = _make_context(api_base_url="http://localhost:8000", work_mode="oversight")
    result = CLIAgent.build_prompt("Do the thing", ctx)

    assert "Perform only oversight/documentation/API operations" in result
    assert "Do not implement source or test changes" in result
    assert "Implement each requirement listed above" not in result


def test_build_prompt_strips_trailing_slash() -> None:
    """Trailing slash on api_base_url is stripped to avoid double slashes."""
    ctx = _make_context(api_base_url="http://localhost:8000/")
    result = CLIAgent.build_prompt("prompt", ctx)

    # Should not have double slashes like http://localhost:8000//api/...
    assert "http://localhost:8000//api" not in result
    assert "http://localhost:8000/api" in result


def test_build_prompt_mcp_channel() -> None:
    """With callback_channel='mcp', prompt is enriched with MCP instructions."""
    ctx = _make_context(api_base_url="http://localhost:8000")
    result = CLIAgent.build_prompt("Do the thing", ctx, callback_channel="mcp")

    assert "Do the thing" in result
    assert "Orchestrator Integration" in result
    assert "MCP Server Connection" in result
    assert "http://localhost:8000/mcp/sse" in result
    assert "run-1" in result
    assert "task-1" in result
    assert "orchestrator_get_requirements" in result
    assert "orchestrator_update_checklist" in result
    assert "orchestrator_submit" in result
    # Should NOT contain REST API instructions
    assert "PATCH" not in result
    assert "REST API" not in result


def test_build_prompt_mcp_strips_trailing_slash() -> None:
    """MCP prompt also strips trailing slash from api_base_url."""
    ctx = _make_context(api_base_url="http://localhost:8000/")
    result = CLIAgent.build_prompt("prompt", ctx, callback_channel="mcp")

    assert "http://localhost:8000/mcp/sse" in result
    assert "http://localhost:8000//mcp" not in result


def test_build_prompt_mcp_without_api_url() -> None:
    """Without api_base_url, MCP builder prompt includes git workflow section."""
    ctx = _make_context(api_base_url=None)
    result = CLIAgent.build_prompt("Original", ctx, callback_channel="mcp")
    assert "Original" in result
    assert "## Git Workflow" in result


# --- Prompt ↔ API route sync tests ---
# These catch drift between the URL patterns hardcoded in build_prompt
# and the actual API routes registered in FastAPI / MCP.


def test_rest_prompt_routes_match_task_router() -> None:
    """URL patterns in the REST enriched prompt match the actual FastAPI task routes.

    If someone renames an API route but forgets to update build_prompt,
    this test will fail.
    """
    from orchestrator.api import router

    # Collect all registered route path templates
    route_paths: set[str] = set()
    for route in router.routes:
        if hasattr(route, "path"):
            route_paths.add(route.path)  # type: ignore[union-attr]

    # Build the enriched prompt and extract the path patterns
    ctx = _make_context(api_base_url="http://example.com")
    prompt = CLIAgent.build_prompt("task", ctx, callback_channel="rest")

    # Extract paths mentioned in the prompt (after the base URL)
    mentioned_paths = re.findall(r"http://example\.com(/api/runs/\S+)", prompt)
    # Normalize: replace concrete IDs with FastAPI path params
    normalized: set[str] = set()
    for path in mentioned_paths:
        path = path.replace("run-1", "{run_id}")
        path = path.replace("task-1", "{task_id}")
        # Remove trailing whitespace / arrow descriptions
        path = path.split()[0]
        normalized.add(path)

    # Every path in the prompt must correspond to a registered route
    for path in normalized:
        assert path in route_paths, (
            f"Prompt mentions {path!r} but no matching route found in task router. "
            f"Registered routes: {sorted(route_paths)}"
        )


def test_mcp_prompt_tool_names_match_registered_tools() -> None:
    """MCP tool names in the enriched prompt match the tools registered on the MCP server.

    If someone renames an MCP tool but forgets to update build_prompt,
    this test will fail.
    """
    from orchestrator.api import ORCHESTRATOR_TOOLS

    registered_names = {t["name"] for t in ORCHESTRATOR_TOOLS}

    # Build the MCP enriched prompt
    ctx = _make_context(api_base_url="http://example.com")
    prompt = CLIAgent.build_prompt("task", ctx, callback_channel="mcp")

    # Extract tool names mentioned in the prompt (e.g., orchestrator_get_requirements)
    mentioned_names = set(re.findall(r"(orchestrator_\w+)", prompt))

    # Every tool name in the prompt must be a real registered tool
    for name in mentioned_names:
        assert name in registered_names, (
            f"Prompt mentions MCP tool {name!r} but it's not registered. "
            f"Registered tools: {sorted(registered_names)}"
        )

    # All agent-facing tools should be mentioned in the prompt
    # Exclude:
    # - orchestrator_set_grade: verifier-only
    # - orchestrator_complete_recovery: recovery-agent-only
    # - orchestrator_list_repos: informational, not workflow-related
    # - orchestrator_list_branches: informational, not workflow-related
    # - oversight parent/child tools: coordinator-only, not task callback flow
    excluded_tools = {
        "orchestrator_set_grade",
        "orchestrator_complete_recovery",
        "orchestrator_list_repos",
        "orchestrator_list_branches",
        "orchestrator_create_child_run",
        "orchestrator_list_child_runs",
        "orchestrator_accept_child_run",
        "orchestrator_resolve_child_run",
        "orchestrator_wait_for_run",
        "orchestrator_get_run_evidence",
        "orchestrator_get_parent_oversight",
        "orchestrator_update_parent_oversight",
        "orchestrator_refresh_parent_oversight",
    }
    agent_tools = registered_names - excluded_tools
    for name in agent_tools:
        assert name in mentioned_names, (
            f"Registered tool {name!r} is not mentioned in the MCP enriched prompt"
        )


# --- Auth token in prompt tests ---


def test_build_prompt_rest_with_auth_token() -> None:
    """REST prompt includes auth header when auth_token is set."""
    ctx = _make_context(api_base_url="http://localhost:8000", auth_token="tok-abc123")
    result = CLIAgent.build_prompt("Do the thing", ctx, callback_channel="rest")

    assert "Authentication" in result
    assert "Authorization: Bearer ${ORCHESTRATOR_AUTH_TOKEN}" in result


def test_build_prompt_mcp_with_auth_token() -> None:
    """MCP prompt includes auth header when auth_token is set."""
    ctx = _make_context(api_base_url="http://localhost:8000", auth_token="tok-abc123")
    result = CLIAgent.build_prompt("Do the thing", ctx, callback_channel="mcp")

    assert "Authentication" in result
    assert "Authorization: Bearer ${ORCHESTRATOR_AUTH_TOKEN}" in result


def test_build_prompt_no_auth_section_without_token() -> None:
    """No auth section when auth_token is None."""
    ctx = _make_context(api_base_url="http://localhost:8000")
    result = CLIAgent.build_prompt("Do the thing", ctx, callback_channel="rest")

    assert "Authentication" not in result
    assert "Bearer" not in result


def test_build_prompt_no_auth_section_without_api_url() -> None:
    """No auth section when api_base_url is None, even if auth_token is set."""
    ctx = _make_context(api_base_url=None, auth_token="tok-abc123")
    result = CLIAgent.build_prompt("Do the thing", ctx)

    assert "Authentication" not in result
    assert "Do the thing" in result
    # Git workflow section is added but no auth section
    assert "## Git Workflow" in result


# --- Step tools tests ---


def test_build_prompt_with_available_tools() -> None:
    """When available_tools is set, prompt includes Step Tools section."""
    ctx = _make_context(api_base_url="http://localhost:8000")
    ctx.available_tools = ["terminal", "file_editor"]
    result = CLIAgent.build_prompt("Do the thing", ctx)

    assert "Step Tools" in result
    assert "terminal" in result
    assert "file_editor" in result
    assert "additional tools are available" in result


def test_build_prompt_no_tools_section_when_none() -> None:
    """When available_tools is None, no Step Tools section is added."""
    ctx = _make_context(api_base_url="http://localhost:8000")
    ctx.available_tools = None
    result = CLIAgent.build_prompt("Do the thing", ctx)

    assert "Step Tools" not in result


def test_build_prompt_no_tools_section_when_empty() -> None:
    """When available_tools is empty list, no Step Tools section is added."""
    ctx = _make_context(api_base_url="http://localhost:8000")
    ctx.available_tools = []
    result = CLIAgent.build_prompt("Do the thing", ctx)

    assert "Step Tools" not in result


def test_build_prompt_available_tools_without_api_url() -> None:
    """When api_base_url is None, available_tools are not listed (no Step Tools section)."""
    ctx = _make_context(api_base_url=None)
    ctx.available_tools = ["terminal", "file_editor"]
    result = CLIAgent.build_prompt("Do the thing", ctx)

    # Without api_base_url, no Step Tools section is added
    assert "Step Tools" not in result
    # But git workflow is still added for builder phase
    assert "## Git Workflow" in result


def test_build_prompt_mcp_with_available_tools() -> None:
    """MCP prompt also includes Step Tools section when available_tools is set."""
    ctx = _make_context(api_base_url="http://localhost:8000")
    ctx.available_tools = ["browser", "grep"]
    result = CLIAgent.build_prompt("Do the thing", ctx, callback_channel="mcp")

    assert "Step Tools" in result
    assert "browser" in result
    assert "grep" in result


def test_build_prompt_verifier_with_available_tools() -> None:
    """Verifier prompt includes Step Tools section when available_tools is set."""
    ctx = _make_context(api_base_url="http://localhost:8000")
    ctx.available_tools = ["terminal", "file_editor"]
    result = CLIAgent.build_prompt("Review the code", ctx, phase="verifying")

    assert "Step Tools" in result
    assert "terminal" in result
    assert "file_editor" in result
    assert "Verifier" in result  # Verifier-specific section
