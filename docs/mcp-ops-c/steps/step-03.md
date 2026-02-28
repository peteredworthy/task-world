# Step 3: CLI Agent Tool Hints + MCP Info in Prompt

Enable the CLI agent to communicate step-level tool availability and external MCP server information to its subprocess. Since CLI agents operate as opaque subprocesses (e.g., Claude Code), tool control is text-based — the agent includes tool hints and MCP configuration in the enriched prompt. This is **Priority 1** alongside Claude SDK.

## Intent Verification
**Original Intent**: CLI agent includes available tools and external MCP info in subprocess prompt (see `docs/mcp-ops-c/intent.md` — "Definition of Complete" bullet 8).
**Functionality to Produce**:
- Enriched prompt includes "Step Tools" section when `context.available_tools` is set
- Enriched prompt includes MCP server connection info when `context.mcp_servers` is set
- `.mcp.json` file written to subprocess working directory for Claude Code auto-discovery
- Auth tokens passed via environment variables, never in prompt text
- When both fields are `None`, prompt is unchanged (backward compatible)

**Final Verification Criteria**:
- Unit tests confirm prompt content includes tool hints and MCP info
- Unit tests confirm prompt is unchanged when fields are `None`
- Auth tokens never appear in prompt text
- All existing CLI agent tests pass

---

## Task 1: Add Step-Level Tool Hints to CLI Prompt
**Description**:
Update `CLIAgent.build_prompt()` in `src/orchestrator/agents/cli.py` to include a "Step Tools" section listing available tool names when `context.available_tools` is set. Unknown tool names are included as-is (CLI subprocess handles its own tools) with a warning logged.

**Implementation Plan (Do These Steps)**
The `build_prompt()` method (line ~120) is a static method that enriches the prompt with callback instructions. It already accepts a `context: ExecutionContext` parameter.

- [ ] In `src/orchestrator/agents/cli.py`, locate the `build_prompt()` method
- [ ] After the existing callback instructions section, add a conditional block for step tools:
```python
# Add step-level tool hints
if context.available_tools:
    sections.append("## Step Tools")
    sections.append("The following additional tools are available for this step:")
    for tool_name in context.available_tools:
        sections.append(f"- {tool_name}")
```
- [ ] Add a `logger.warning()` for any unknown tool names if a known-tool registry exists; otherwise just include names as-is (CLI subprocess is opaque)
- [ ] Verify that when `context.available_tools` is `None`, no tool section is added

**Dependencies**
- [ ] Step 2 complete: `ExecutionContext` carries `available_tools`

**References**
- Current CLI agent: `src/orchestrator/agents/cli.py` (line ~120 — `build_prompt()`)
- Key decision: CLI tool control is text hints in prompt (not enforced), since subprocess is opaque boundary
- Architecture: `docs/mcp-ops-c/architecture.md` — CLI agent row

**Constraints**
- Do not modify the method signature of `build_prompt()`
- Do not remove or change any existing prompt content

**Functionality (Expected Outcomes)**
- [ ] `available_tools=["terminal", "file_editor"]` → prompt contains "terminal" and "file_editor"
- [ ] `available_tools=None` → prompt unchanged from current behavior
- [ ] `available_tools=[]` → no tool section added (empty list treated as no tools)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -k "cli" -v` — all CLI tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 2: Add MCP Server Info to CLI Prompt and .mcp.json
**Description**:
When `context.mcp_servers` is set, include MCP server connection info in the prompt and write a `.mcp.json` file to the subprocess working directory for auto-discovery by Claude Code.

**Implementation Plan (Do These Steps)**
- [ ] In `build_prompt()`, add a conditional block for MCP servers after the tool hints section:
```python
# Add external MCP server info
if context.mcp_servers:
    sections.append("## External MCP Servers")
    sections.append("The following external MCP servers are available for this step:")
    for mcp in context.mcp_servers:
        if mcp.url:
            sections.append(f"- **{mcp.name}**: {mcp.url}")
        elif mcp.command:
            cmd_str = f"{mcp.command} {' '.join(mcp.args or [])}"
            sections.append(f"- **{mcp.name}**: (stdio) {cmd_str}")
```
- [ ] Add a method to write `.mcp.json` for Claude Code auto-discovery. This should be called before subprocess launch (in the `execute()` method, not in `build_prompt()`):
```python
def _write_mcp_json(self, working_dir: str, mcp_servers: list[MCPServerConfig]) -> None:
    """Write .mcp.json to working dir for Claude Code auto-discovery."""
    mcp_config = {"mcpServers": {}}
    for mcp in mcp_servers:
        server_entry: dict[str, Any] = {}
        if mcp.url:
            server_entry["url"] = mcp.url
        elif mcp.command:
            server_entry["command"] = mcp.command
            if mcp.args:
                server_entry["args"] = mcp.args
        if mcp.env:
            server_entry["env"] = dict(mcp.env)
        if mcp.auth_token_env:
            # Pass env var reference, not the actual token
            server_entry["env"] = server_entry.get("env", {})
            server_entry["env"][mcp.auth_token_env] = f"${{{mcp.auth_token_env}}}"
        mcp_config["mcpServers"][mcp.name] = server_entry

    mcp_json_path = Path(working_dir) / ".mcp.json"
    mcp_json_path.write_text(json.dumps(mcp_config, indent=2))
```
- [ ] In the `execute()` method, call `_write_mcp_json()` before launching subprocess when `context.mcp_servers` is set
- [ ] Ensure `auth_token_env` values are passed as environment variable references in `.mcp.json`, NOT resolved token values
- [ ] Import `json` and `Path` if not already present

**Dependencies**
- [ ] Task 1 complete: `build_prompt()` already handles step tools

**References**
- Key decision: Auth tokens via env vars to subprocess, never in prompt text
- `.mcp.json` format: Standard MCP client config format used by Claude Code

**Constraints**
- Auth token values must NEVER appear in prompt text or `.mcp.json` — only env var references
- Do not overwrite existing `.mcp.json` without merging (check if file exists first)

**Functionality (Expected Outcomes)**
- [ ] `mcp_servers=[MCPServerConfig(name="ctx7", url="https://...")]` → prompt includes MCP info + `.mcp.json` written
- [ ] `mcp_servers=None` → no MCP section in prompt, no `.mcp.json` written
- [ ] `.mcp.json` contains valid JSON with `mcpServers` key
- [ ] Auth tokens are env var references, not inline values

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -k "cli" -v` — all CLI tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 3: Write Unit Tests for CLI Tool Hints and MCP Info
**Description**:
Create unit tests verifying the CLI agent prompt includes tool hints and MCP info when configured, and remains unchanged when not.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_cli_tool_hints.py`:
```python
"""Tests for CLI agent step-level tool hints and MCP info."""
import json
from pathlib import Path
from unittest.mock import patch

from orchestrator.agents.cli import CLIAgent
from orchestrator.agents.types import ExecutionContext
from orchestrator.config.models import MCPServerConfig


def _make_context(**overrides) -> ExecutionContext:
    defaults = dict(
        run_id="r1", task_id="t1", working_dir="/tmp/test",
        prompt="Build the feature", requirements=["R1"],
        api_base_url="http://localhost:8000",
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


class TestCLIToolHints:
    def test_available_tools_in_prompt(self):
        ctx = _make_context(available_tools=["terminal", "file_editor"])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "terminal" in prompt
        assert "file_editor" in prompt

    def test_no_tools_section_when_none(self):
        ctx = _make_context(available_tools=None)
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "Step Tools" not in prompt

    def test_no_tools_section_when_empty(self):
        ctx = _make_context(available_tools=[])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "Step Tools" not in prompt


class TestCLIMCPInfo:
    def test_mcp_servers_in_prompt(self):
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        ctx = _make_context(mcp_servers=[mcp])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "ctx7" in prompt
        assert "https://ctx7.example.com" in prompt

    def test_no_mcp_section_when_none(self):
        ctx = _make_context(mcp_servers=None)
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        assert "External MCP" not in prompt

    def test_auth_token_not_in_prompt(self):
        mcp = MCPServerConfig(
            name="auth_svc", url="https://auth.example.com",
            auth_token_env="SECRET_TOKEN",
        )
        ctx = _make_context(mcp_servers=[mcp])
        prompt = CLIAgent.build_prompt(ctx.prompt, ctx)
        # The env var NAME may appear, but no resolved value should
        assert "SECRET_TOKEN" not in prompt or "auth_token_env" in prompt
```

**Functionality (Expected Outcomes)**
- [ ] All tool hint tests pass
- [ ] All MCP info tests pass
- [ ] Auth token security test passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/unit/test_cli_tool_hints.py -v` — all tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes
