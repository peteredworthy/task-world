"""Tests for CLI agent step-level tool hints and MCP info."""

import json
import tempfile
from pathlib import Path

from orchestrator.config.models import MCPServerConfig
from orchestrator.runners import CLIAgent
from orchestrator.runners.mcp_scope import BUILDER_WORKFLOW_MCP_TOOLS, VERIFIER_WORKFLOW_MCP_TOOLS
from orchestrator.runners.types import ExecutionContext


def _scoped_orchestrator_url(*tool_names: str, phase: str = "building") -> str:
    workflow_tools = (
        VERIFIER_WORKFLOW_MCP_TOOLS if phase == "verifying" else BUILDER_WORKFLOW_MCP_TOOLS
    )
    scoped_tools = ",".join(sorted(workflow_tools | set(tool_names)))
    return f"http://localhost:8000/mcp-scoped/{scoped_tools}/sse"


def _make_context(**overrides) -> ExecutionContext:
    """Create a test ExecutionContext with sensible defaults."""
    defaults = dict(
        run_id="r1",
        task_id="t1",
        working_dir="/tmp/test",
        prompt="Build the feature",
        requirements=["R1"],
        api_base_url="http://localhost:8000",
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


class TestCLIToolHints:
    """Tests for step-level tool hints in CLI prompt."""

    def test_available_tools_in_prompt(self):
        """Test that available_tools are included in the prompt."""
        ctx = _make_context(available_tools=["terminal", "file_editor"])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "terminal" in prompt
        assert "file_editor" in prompt
        assert "## Step Tools" in prompt

    def test_no_tools_section_when_none(self):
        """Test that no tool section is added when available_tools is None."""
        ctx = _make_context(available_tools=None)
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "## Step Tools" not in prompt

    def test_no_tools_section_when_empty(self):
        """Test that no tool section is added when available_tools is empty."""
        ctx = _make_context(available_tools=[])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "## Step Tools" not in prompt

    def test_multiple_tools_in_prompt(self):
        """Test that multiple tools are all listed in the prompt."""
        tools = ["terminal", "file_editor", "browser", "grep"]
        ctx = _make_context(available_tools=tools)
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        for tool in tools:
            assert tool in prompt


class TestCLIMCPInfo:
    """Tests for MCP server info in CLI prompt and generated MCP config."""

    def test_mcp_servers_in_prompt(self):
        """Test that MCP servers are included in the prompt."""
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        ctx = _make_context(mcp_servers=[mcp])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "ctx7" in prompt
        assert "https://ctx7.example.com" in prompt
        assert "## External MCP Servers" in prompt
        assert "Use the registered MCP tools" in prompt
        assert "do not call raw MCP SSE/message endpoints with curl" in prompt

    def test_mcp_prompt_describes_structured_clarifications(self):
        """Clarification tool guidance steers finite decisions to select options."""
        mcp = MCPServerConfig(name="orchestrator", url="http://localhost:8000/mcp/sse")
        ctx = _make_context(mcp_servers=[mcp])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx, callback_channel="mcp")

        assert "Parent needed:" in prompt
        assert "Child did:" in prompt
        assert "Decision needed:" in prompt
        assert "question_type='single_select' or 'multi_select'" in prompt
        assert "Do not put a/b/c choices in a free_text question" in prompt
        assert "Reject this child and replan the slice" in prompt

    def test_no_mcp_section_when_none(self):
        """Test that no MCP section is added when mcp_servers is None."""
        ctx = _make_context(mcp_servers=None)
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "## External MCP Servers" not in prompt

    def test_no_mcp_section_when_empty(self):
        """Test that no MCP section is added when mcp_servers is empty."""
        ctx = _make_context(mcp_servers=[])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "## External MCP Servers" not in prompt

    def test_mcp_server_with_url(self):
        """Test that URL-based MCP servers are formatted correctly."""
        mcp = MCPServerConfig(name="api_server", url="https://api.example.com")
        ctx = _make_context(mcp_servers=[mcp])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "api_server" in prompt
        assert "https://api.example.com" in prompt

    def test_mcp_server_with_command(self):
        """Test that command-based MCP servers are formatted correctly."""
        mcp = MCPServerConfig(name="local_tool", command="python", args=["-m", "mcp_server"])
        ctx = _make_context(mcp_servers=[mcp])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "local_tool" in prompt
        assert "(stdio)" in prompt
        assert "python" in prompt

    def test_multiple_mcp_servers(self):
        """Test that multiple MCP servers are all listed in the prompt."""
        mcps = [
            MCPServerConfig(name="server1", url="https://server1.example.com"),
            MCPServerConfig(name="server2", command="python", args=["-m", "tool"]),
        ]
        ctx = _make_context(mcp_servers=mcps)
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "server1" in prompt
        assert "server2" in prompt

    def test_auth_token_env_name_not_in_mcp_prompt(self):
        """Test that auth token env name doesn't appear as a value in the MCP servers section.

        The context.auth_token is correctly included in the Authentication section.
        This test verifies that auth_token_env is handled correctly as an env var reference.
        """
        mcp = MCPServerConfig(
            name="auth_svc",
            url="https://auth.example.com",
            auth_token_env="SECRET_TOKEN",
        )
        ctx = _make_context(
            mcp_servers=[mcp],
            auth_token="test_token_value",
        )
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        # The auth_token for orchestrator API is expected in the Authentication section
        # but it should only appear as "Bearer {token}" or similar, not embedded in MCP section
        # The MCP section should only mention the server name and URL
        lines = prompt.split("\n")
        mcp_section = []
        in_mcp = False
        for line in lines:
            if "## External MCP Servers" in line:
                in_mcp = True
            elif line.startswith("##") and in_mcp:
                in_mcp = False
            elif in_mcp:
                mcp_section.append(line)

        mcp_text = "\n".join(mcp_section)
        # The MCP section should NOT contain the actual token value
        assert "test_token_value" not in mcp_text

    def test_mcp_json_written_with_url(self):
        """Test that generated MCP config is written correctly for URL-based servers."""
        agent = CLIAgent(command="claude")
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
            agent._write_mcp_json(tmpdir, [mcp])

            mcp_json_path = agent._mcp_json_path(tmpdir)
            assert mcp_json_path.exists()

            config = json.loads(mcp_json_path.read_text())
            assert "mcpServers" in config
            assert "ctx7" in config["mcpServers"]
            assert config["mcpServers"]["ctx7"]["type"] == "sse"
            assert config["mcpServers"]["ctx7"]["url"] == "https://ctx7.example.com"

    def test_mcp_json_written_with_command(self):
        """Test that generated MCP config is written correctly for command-based servers."""
        agent = CLIAgent(command="claude")
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp = MCPServerConfig(
                name="local_tool",
                command="python",
                args=["-m", "mcp_server"],
                cwd="worktree",
            )
            agent._write_mcp_json(tmpdir, [mcp])

            mcp_json_path = agent._mcp_json_path(tmpdir)
            config = json.loads(mcp_json_path.read_text())
            assert config["mcpServers"]["local_tool"]["command"] == "python"
            assert config["mcpServers"]["local_tool"]["args"] == ["-m", "mcp_server"]
            assert config["mcpServers"]["local_tool"]["cwd"] == tmpdir

    def test_mcp_json_with_env_vars(self):
        """Test that generated MCP config includes environment variables."""
        agent = CLIAgent(command="claude")
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp = MCPServerConfig(
                name="api_server",
                url="https://api.example.com",
                env={"API_URL": "https://internal.example.com", "DEBUG": "true"},
            )
            agent._write_mcp_json(tmpdir, [mcp])

            mcp_json_path = agent._mcp_json_path(tmpdir)
            config = json.loads(mcp_json_path.read_text())
            assert config["mcpServers"]["api_server"]["type"] == "sse"
            assert (
                config["mcpServers"]["api_server"]["env"]["API_URL"]
                == "https://internal.example.com"
            )
            assert config["mcpServers"]["api_server"]["env"]["DEBUG"] == "true"

    def test_mcp_json_with_auth_token_env(self):
        """Test that auth_token_env is written as env var reference, not value."""
        agent = CLIAgent(command="claude")
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp = MCPServerConfig(
                name="secure_api",
                url="https://secure.example.com",
                auth_token_env="SECURE_TOKEN",
            )
            agent._write_mcp_json(tmpdir, [mcp])

            mcp_json_path = agent._mcp_json_path(tmpdir)
            config = json.loads(mcp_json_path.read_text())
            # Auth token should be a reference, not a value
            assert config["mcpServers"]["secure_api"]["env"]["SECURE_TOKEN"] == "${SECURE_TOKEN}"

    def test_mcp_json_with_combined_env_and_auth(self):
        """Test that both regular env vars and auth token env are in generated MCP config."""
        agent = CLIAgent(command="claude")
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp = MCPServerConfig(
                name="full_config",
                url="https://api.example.com",
                env={"API_URL": "https://internal.example.com"},
                auth_token_env="API_TOKEN",
            )
            agent._write_mcp_json(tmpdir, [mcp])

            mcp_json_path = agent._mcp_json_path(tmpdir)
            config = json.loads(mcp_json_path.read_text())
            env = config["mcpServers"]["full_config"]["env"]
            assert env["API_URL"] == "https://internal.example.com"
            assert env["API_TOKEN"] == "${API_TOKEN}"

    def test_mcp_json_valid_json_format(self):
        """Test that generated MCP config is valid JSON."""
        agent = CLIAgent(command="claude")
        with tempfile.TemporaryDirectory() as tmpdir:
            mcps = [
                MCPServerConfig(name="server1", url="https://server1.example.com"),
                MCPServerConfig(name="server2", command="python", args=["-m", "tool"]),
            ]
            agent._write_mcp_json(tmpdir, mcps)

            mcp_json_path = agent._mcp_json_path(tmpdir)
            content = mcp_json_path.read_text()
            config = json.loads(content)  # This will raise if JSON is invalid
            assert "mcpServers" in config
            assert len(config["mcpServers"]) == 2

    def test_empty_mcp_json_is_valid_strict_config(self):
        """An empty generated MCP config lets Claude ignore user/global MCP servers."""
        agent = CLIAgent(command="claude")
        with tempfile.TemporaryDirectory() as tmpdir:
            agent._write_mcp_json(tmpdir, [], available_tools=None)

            config = json.loads(agent._mcp_json_path(tmpdir).read_text())
            assert config == {"mcpServers": {}}

    def test_orchestrator_mcp_json_scoped_to_available_tools(self):
        """Orchestrator MCP URLs are rewritten to task-scoped endpoints."""
        agent = CLIAgent(command="claude")
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp = MCPServerConfig(name="orchestrator", url="http://localhost:8000/mcp/sse")
            agent._write_mcp_json(
                tmpdir,
                [mcp],
                available_tools=[
                    "orchestrator_update_parent_oversight",
                    "orchestrator_get_parent_oversight",
                ],
            )

            config = json.loads(agent._mcp_json_path(tmpdir).read_text())
            assert config["mcpServers"]["orchestrator"]["url"] == _scoped_orchestrator_url(
                "orchestrator_get_parent_oversight",
                "orchestrator_update_parent_oversight",
            )

    def test_orchestrator_mcp_json_scoped_to_workflow_tools_by_default(self):
        """Builder workflow MCP tools remain available when task tools are omitted."""
        agent = CLIAgent(command="claude")
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp = MCPServerConfig(name="orchestrator", url="http://localhost:8000/mcp/sse")
            agent._write_mcp_json(tmpdir, [mcp], available_tools=None)

            config = json.loads(agent._mcp_json_path(tmpdir).read_text())
            assert config["mcpServers"]["orchestrator"]["url"] == _scoped_orchestrator_url()

    def test_orchestrator_mcp_json_verifier_uses_verifier_workflow_tools(self):
        """Verifier generated MCP config excludes builder-only workflow tools."""
        agent = CLIAgent(command="claude", phase="verifying")
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp = MCPServerConfig(name="orchestrator", url="http://localhost:8000/mcp/sse")
            agent._write_mcp_json(tmpdir, [mcp], available_tools=None)

            url = json.loads(agent._mcp_json_path(tmpdir).read_text())["mcpServers"][
                "orchestrator"
            ]["url"]
            assert url == _scoped_orchestrator_url(phase="verifying")
            assert "orchestrator_set_grade" in url
            assert "orchestrator_update_checklist" not in url

    def test_orchestrator_mcp_prompt_lists_scoped_url(self):
        """Prompt MCP server inventory mirrors the scoped Claude config URL."""
        mcp = MCPServerConfig(name="orchestrator", url="http://localhost:8000/mcp/sse")
        ctx = _make_context(
            mcp_servers=[mcp],
            available_tools=["orchestrator_get_parent_oversight"],
        )

        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)

        assert _scoped_orchestrator_url("orchestrator_get_parent_oversight") in prompt
        assert "http://localhost:8000/mcp/sse" not in prompt

    def test_claude_args_include_explicit_mcp_config(self):
        """Claude CLI receives explicit scoped MCP and tool-clutter reduction flags."""
        agent = CLIAgent(command="claude", args=["-p"])
        path = Path("/tmp/work/.orchestrator/mcp.json")

        args = agent._args_with_mcp_config(path, ["Task"])

        assert args == [
            "-p",
            "--tools",
            "Bash,Edit,MultiEdit,Read,Write,Glob,Grep,LS,TodoWrite,Task",
            "--disable-slash-commands",
            "--setting-sources",
            "project,local",
            "--no-chrome",
            "--mcp-config",
            str(path),
            "--strict-mcp-config",
        ]

    def test_claude_args_do_not_duplicate_mcp_config(self):
        """Existing user-provided --mcp-config is preserved and made strict."""
        agent = CLIAgent(command="claude", args=["-p", "--mcp-config", "custom.json"])

        args = agent._args_with_mcp_config(Path("/tmp/work/.orchestrator/mcp.json"))

        assert args == [
            "-p",
            "--mcp-config",
            "custom.json",
            "--tools",
            "Bash,Edit,MultiEdit,Read,Write,Glob,Grep,LS,TodoWrite",
            "--disable-slash-commands",
            "--setting-sources",
            "project,local",
            "--no-chrome",
            "--strict-mcp-config",
        ]

    def test_claude_args_do_not_override_user_tool_restrictions(self):
        """User-provided --tools stays authoritative."""
        agent = CLIAgent(command="claude", args=["-p", "--tools", "Bash,Read"])

        args = agent._args_with_mcp_config(None)

        assert args == [
            "-p",
            "--tools",
            "Bash,Read",
            "--disable-slash-commands",
            "--setting-sources",
            "project,local",
            "--no-chrome",
        ]

    def test_claude_verifier_args_use_read_only_builtin_tools(self):
        """Verifier sessions do not expose edit/write tools by default."""
        agent = CLIAgent(command="claude", args=["-p"], phase="verifying")

        args = agent._args_with_mcp_config(Path("/tmp/work/.orchestrator/mcp.json"))

        assert args == [
            "-p",
            "--tools",
            "Bash,Read,Glob,Grep,LS",
            "--disable-slash-commands",
            "--setting-sources",
            "project,local",
            "--no-chrome",
            "--mcp-config",
            "/tmp/work/.orchestrator/mcp.json",
            "--strict-mcp-config",
        ]

    def test_claude_bare_args_skip_settings_sources(self):
        """Bare mode avoids project/local setting discovery to reduce startup context."""
        agent = CLIAgent(command="claude", args=["-p"], bare=True)

        args = agent._args_with_mcp_config(Path("/tmp/work/.orchestrator/mcp.json"))

        assert args == [
            "-p",
            "--bare",
            "--tools",
            "Bash,Edit,MultiEdit,Read,Write,Glob,Grep,LS,TodoWrite",
            "--disable-slash-commands",
            "--no-chrome",
            "--mcp-config",
            "/tmp/work/.orchestrator/mcp.json",
            "--strict-mcp-config",
        ]

    def test_non_claude_args_do_not_get_mcp_config(self):
        """Other CLI commands are not given Claude-specific flags."""
        agent = CLIAgent(command="codex", args=["exec"])

        args = agent._args_with_mcp_config(Path("/tmp/work/.orchestrator/mcp.json"))

        assert args == ["exec"]


class TestCLIPromptBackwardCompatibility:
    """Test that CLI prompt behavior is backward compatible."""

    def test_prompt_unchanged_when_no_tools_or_mcp(self):
        """Test that prompt is unchanged when both fields are None."""
        ctx = _make_context(available_tools=None, mcp_servers=None)
        # Should still include the Orchestrator Integration section
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "## Orchestrator Integration" in prompt

    def test_tools_and_mcp_both_present(self):
        """Test that prompt includes both tools and MCP when both are configured."""
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        ctx = _make_context(available_tools=["terminal", "file_editor"], mcp_servers=[mcp])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "## Step Tools" in prompt
        assert "## External MCP Servers" in prompt
        assert "terminal" in prompt
        assert "ctx7" in prompt

    def test_verifier_prompt_with_mcp_servers(self):
        """Test that verifier prompt includes MCP servers when configured."""
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        ctx = _make_context(mcp_servers=[mcp])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx, callback_channel="rest", phase="verifying")
        assert "## External MCP Servers" in prompt
        assert "ctx7" in prompt

    def test_verifier_prompt_with_tools(self):
        """Test that verifier prompt includes tools when configured."""
        ctx = _make_context(available_tools=["terminal"])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx, callback_channel="rest", phase="verifying")
        assert "## Step Tools" in prompt
        assert "terminal" in prompt
