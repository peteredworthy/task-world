# External MCP Support — Unified Implementation Guide

> **Date**: 2026-02-27
> **Status**: Ready for implementation
> **Scope**: Step-level external MCP server configuration across all agent types

---

## 1. Technical Verification

### 1.1 Claude SDK (Messages API) — CONFIRMED: Native MCP Connector

The Anthropic Messages API has a **first-class MCP connector** in public beta
(`anthropic-beta: mcp-client-2025-11-20`). External MCP servers are declared
per-request in the `mcp_servers` array and their tools are exposed via
`mcp_toolset` entries in the `tools` array.

**Key facts:**
- Servers must be publicly exposed over HTTPS (SSE or Streamable HTTP transport)
- STDIO-based MCP servers **cannot** be connected directly — they must be
  proxied behind an HTTP endpoint
- Multiple MCP servers per request are supported
- Tool allowlisting/denylisting is natively supported via `configs`
- OAuth bearer tokens are supported via `authorization_token`
- Response includes `mcp_tool_use` and `mcp_tool_result` content blocks

**Implication for our orchestrator:** The `ClaudeSDKAgent` can pass external
MCP servers directly in each `client.beta.messages.create()` call. No proxy
process is needed for HTTP-based MCP servers. This is the **cleanest**
integration path of all agent types.

**Limitation:** Only remote (HTTPS) MCP servers work. Local STDIO servers
(e.g., a local `chrome-mcp` process) cannot be used directly. To use STDIO
servers, we would need an HTTP-to-stdio bridge (e.g., `mcp-proxy` or
`supergateway`).

### 1.2 Codex Server (JSON-RPC) — CONFIRMED: Via config.toml

Codex supports MCP servers configured in `~/.codex/config.toml` under
`[mcp_servers.<name>]` tables. Both STDIO and Streamable HTTP transports
are supported.

**Key facts:**
- STDIO servers: `command`, `args`, `env`, `cwd` fields
- HTTP servers: `url`, `bearer_token_env_var`, `http_headers` fields
- Per-server options: `enabled_tools`, `disabled_tools`, `startup_timeout_sec`,
  `tool_timeout_sec`
- Servers launch automatically when a session starts
- There is **no documented per-session MCP configuration** via the JSON-RPC
  `thread/start` API — servers come from the config file

**Implication for our orchestrator:** The `CodexServerAgent` already creates an
isolated `CODEX_HOME` temp directory per session (see `_spawn_transport`). We
can write a dynamic `config.toml` into that temp directory with the desired MCP
servers before launching the process. This gives us per-task MCP control without
affecting the user's real config.

### 1.3 OpenHands (Local SDK) — CONFIRMED: Native mcp_config

The OpenHands SDK supports MCP integration via the `mcp_config` parameter on
the `Agent` constructor. Both STDIO and OAuth-protected HTTP servers are
supported.

**Key facts:**
- `mcp_config = {"mcpServers": {"name": {"command": "...", "args": [...]}}}}`
- HTTP servers: `{"url": "https://...", "auth": "oauth"}`
- Tool filtering via `filter_tools_regex` on the Agent
- MCP tools are automatically discovered and registered alongside built-in tools

**Implication for our orchestrator:** The `OpenHandsAgent` can pass external
MCP servers directly in the `Agent()` constructor call. This is straightforward.

### 1.4 CLI Subprocess (claude, codex) — CONFIRMED: Feasible via Config

CLI subprocess agents spawn `claude` or `codex` as child processes.

- **claude CLI**: Supports MCP servers via `~/.claude.json` or project-level
  `.mcp.json` files. The `--mcp-config` flag or `CLAUDE_MCP_CONFIG` env var
  can specify MCP servers at launch.
- **codex CLI**: Supports MCP servers via `~/.codex/config.toml` as documented
  above. The `CODEX_HOME` env var redirects config lookup.

**Implication:** For `claude` CLI, write a temporary `.mcp.json` in the
worktree. For `codex` CLI, write a temporary `config.toml` and set
`CODEX_HOME`.

### 1.5 User-Managed — N/A (External Control)

User-managed agents are external processes that connect to the orchestrator
via REST/MCP. The orchestrator does not control what tools they use. MCP
server configuration would be **informational** — included in the prompt
response so the external agent knows which servers it should connect to.

---

## 2. Unified Architecture

### 2.1 Common Pattern

All agent types follow the same pattern:

```
Routine YAML → StepConfig.mcp_servers → ExecutionContext.mcp_servers → Agent-specific wiring
```

1. **Declare** MCP servers at the step level in the routine YAML
2. **Thread** the config through `ExecutionContext`
3. **Wire** the servers into each agent's native mechanism

### 2.2 Configuration Model

```python
# src/orchestrator/config/models.py

class MCPServerConfig(BaseModel):
    """An external MCP server to make available to the agent."""

    name: str                              # Unique identifier (e.g., "context7", "chrome")
    transport: str = "stdio"               # "stdio" | "http"

    # STDIO transport fields
    command: str | None = None             # e.g., "npx", "uvx"
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    # HTTP transport fields
    url: str | None = None                 # e.g., "https://mcp.example.com/sse"
    auth_token_env: str | None = None      # Env var name holding the bearer token

    # Tool filtering (optional)
    enabled_tools: list[str] | None = None   # Allowlist (None = all tools)
    disabled_tools: list[str] | None = None  # Denylist

    # Timeouts
    startup_timeout_sec: int = 10
    tool_timeout_sec: int = 60
```

### 2.3 StepConfig Extension

```python
# src/orchestrator/config/models.py — extend StepConfig

class StepConfig(BaseModel):
    id: str
    title: str
    step_context: str | None = None
    gate: GateConfig | None = None
    tasks: list[TaskConfig] = Field(min_length=1)
    transitions: StepTransitions | None = None
    type: StepType = StepType.STANDARD
    dry_run: DryRunConfig | None = None
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)  # NEW
```

### 2.4 ExecutionContext Extension

```python
# src/orchestrator/agents/types.py — extend ExecutionContext

class ExecutionContext(BaseModel):
    run_id: str
    task_id: str
    working_dir: str
    prompt: str
    requirements: list[str]
    api_base_url: str | None = None
    auth_token: str | None = None
    end_commit: str | None = None
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)  # NEW
```

### 2.5 Routine YAML Format

```yaml
routine:
  id: feature-build
  name: Build Feature with Documentation
  steps:
    - id: S-01
      title: Implement Feature
      mcp_servers:
        - name: context7
          transport: stdio
          command: npx
          args: ["-y", "@upstash/context7-mcp@latest"]

        - name: browser
          transport: stdio
          command: npx
          args: ["-y", "@anthropic/chrome-mcp"]

        - name: github
          transport: http
          url: https://mcp.github.com/sse
          auth_token_env: GITHUB_TOKEN

      tasks:
        - id: T-01
          title: Implement the widget
          task_context: ...
```

All tasks within a step share the same MCP servers. This is the right
granularity because:
- Steps represent a phase of work (build, test, review)
- Different phases need different tools (browser for testing, not for building)
- Tasks within a step share the same working context

### 2.6 Auth Token Security

Auth tokens are **never stored in the routine YAML**. Instead, the YAML
references an **environment variable name** via `auth_token_env`. The actual
secret is resolved at runtime from the orchestrator's process environment.

Resolution chain (in `executor.py`):
1. Look up `mcp_server.auth_token_env` in `os.environ`
2. If not found, look up in `run.config` (run-level env overrides)
3. If not found, log a warning and skip the auth header (server may work
   without auth, or may fail gracefully)

This means secrets never appear in:
- Routine YAML files (committed to git)
- Database rows (run config stores env var names, not values)
- WebSocket events or API responses
- Agent output logs

---

## 3. Agent-Specific Wiring

### 3.1 Claude SDK Agent

The cleanest integration. MCP servers map directly to the Messages API's
`mcp_servers` + `mcp_toolset` parameters.

```python
# In ClaudeSDKAgent.execute(), build the mcp_servers and tools arrays:

def _build_mcp_params(
    mcp_servers: list[MCPServerConfig],
) -> tuple[list[dict], list[dict]]:
    """Convert MCPServerConfig list to Anthropic API parameters.

    Only HTTP-transport servers are supported by the Messages API.
    STDIO servers are silently skipped with a warning.
    """
    api_servers = []
    api_toolsets = []

    for server in mcp_servers:
        if server.transport != "http" or not server.url:
            logger.warning(
                "ClaudeSDKAgent: skipping STDIO MCP server '%s' — "
                "Messages API only supports HTTP servers",
                server.name,
            )
            continue

        # Resolve auth token from environment
        auth_token = None
        if server.auth_token_env:
            auth_token = os.environ.get(server.auth_token_env)

        api_servers.append({
            "type": "url",
            "url": server.url,
            "name": server.name,
            **({"authorization_token": auth_token} if auth_token else {}),
        })

        # Build toolset config
        toolset: dict[str, Any] = {
            "type": "mcp_toolset",
            "mcp_server_name": server.name,
        }
        if server.enabled_tools is not None:
            toolset["default_config"] = {"enabled": False}
            toolset["configs"] = {
                tool: {"enabled": True} for tool in server.enabled_tools
            }
        elif server.disabled_tools:
            toolset["configs"] = {
                tool: {"enabled": False} for tool in server.disabled_tools
            }

        api_toolsets.append(toolset)

    return api_servers, api_toolsets

# Then in the execute() agentic loop:
mcp_api_servers, mcp_toolsets = _build_mcp_params(context.mcp_servers)

response = await asyncio.to_thread(
    client.beta.messages.create,
    model=self._model,
    max_tokens=self._max_tokens,
    tools=tools + mcp_toolsets,       # orchestrator tools + MCP toolsets
    messages=messages,
    **({"mcp_servers": mcp_api_servers} if mcp_api_servers else {}),
    betas=["mcp-client-2025-11-20"],
)
```

**Key detail:** The `mcp_tool_use` and `mcp_tool_result` content blocks in
the response are handled **server-side by Anthropic** — the orchestrator does
not need to execute MCP tool calls itself. They appear in the conversation
history transparently.

### 3.2 Codex Server Agent

Writes a per-session `config.toml` into the isolated `CODEX_HOME` before
spawning the process.

```python
# In CodexServerAgent._spawn_transport(), after creating tmp_codex_home:

def _write_mcp_config(
    codex_home: Path,
    mcp_servers: list[MCPServerConfig],
) -> None:
    """Write MCP server definitions to config.toml in the temp CODEX_HOME."""
    if not mcp_servers:
        return

    lines = []
    for server in mcp_servers:
        lines.append(f'[mcp_servers.{server.name}]')

        if server.transport == "stdio" and server.command:
            lines.append(f'command = "{server.command}"')
            if server.args:
                args_str = ", ".join(f'"{a}"' for a in server.args)
                lines.append(f"args = [{args_str}]")
            if server.env:
                lines.append("[mcp_servers.{}.env]".format(server.name))
                for k, v in server.env.items():
                    lines.append(f'{k} = "{v}"')

        elif server.transport == "http" and server.url:
            lines.append(f'url = "{server.url}"')
            if server.auth_token_env:
                lines.append(f'bearer_token_env_var = "{server.auth_token_env}"')

        if server.enabled_tools is not None:
            tools_str = ", ".join(f'"{t}"' for t in server.enabled_tools)
            lines.append(f"enabled_tools = [{tools_str}]")
        if server.disabled_tools:
            tools_str = ", ".join(f'"{t}"' for t in server.disabled_tools)
            lines.append(f"disabled_tools = [{tools_str}]")

        lines.append(f"startup_timeout_sec = {server.startup_timeout_sec}")
        lines.append(f"tool_timeout_sec = {server.tool_timeout_sec}")
        lines.append("")  # blank line between servers

    config_path = codex_home / "config.toml"
    # Append to existing config if present (e.g., from "use-local" mode)
    existing = config_path.read_text() if config_path.exists() else ""
    config_path.write_text(existing + "\n" + "\n".join(lines))
```

Codex automatically discovers and launches configured MCP servers when a
session starts. No additional JSON-RPC messages are needed.

### 3.3 OpenHands Agent

Passes MCP servers directly via the `mcp_config` parameter.

```python
# In OpenHandsAgent.execute(), build the mcp_config dict:

def _build_openhands_mcp_config(
    mcp_servers: list[MCPServerConfig],
) -> dict[str, Any] | None:
    """Convert MCPServerConfig list to OpenHands mcp_config dict."""
    if not mcp_servers:
        return None

    servers = {}
    for server in mcp_servers:
        if server.transport == "stdio" and server.command:
            entry: dict[str, Any] = {
                "command": server.command,
                "args": server.args,
            }
            if server.env:
                entry["env"] = server.env
            servers[server.name] = entry

        elif server.transport == "http" and server.url:
            entry = {"url": server.url}
            if server.auth_token_env:
                token = os.environ.get(server.auth_token_env)
                if token:
                    entry["headers"] = {"Authorization": f"Bearer {token}"}
            servers[server.name] = entry

    return {"mcpServers": servers} if servers else None


# Then in execute():
mcp_config = _build_openhands_mcp_config(context.mcp_servers)

# Build filter regex from enabled_tools/disabled_tools if specified
filter_regex = _build_openhands_tool_filter(context.mcp_servers)

agent = OHAgent(
    llm=llm,
    tools=builtin_tools + orchestrator_tools,
    **({"mcp_config": mcp_config} if mcp_config else {}),
    **({"filter_tools_regex": filter_regex} if filter_regex else {}),
)
```

Both STDIO and HTTP servers are natively supported.

### 3.4 CLI Subprocess Agent

#### claude CLI

Write a temporary `.mcp.json` in the worktree directory:

```python
# In CLIAgent.execute(), before spawning the process:

def _write_claude_mcp_config(
    working_dir: str,
    mcp_servers: list[MCPServerConfig],
) -> Path | None:
    """Write .mcp.json in the working directory for the claude CLI."""
    if not mcp_servers:
        return None

    config: dict[str, Any] = {"mcpServers": {}}
    for server in mcp_servers:
        if server.transport == "stdio" and server.command:
            entry: dict[str, Any] = {
                "command": server.command,
                "args": server.args,
            }
            if server.env:
                entry["env"] = server.env
            config["mcpServers"][server.name] = entry

        elif server.transport == "http" and server.url:
            entry = {"type": "sse", "url": server.url}
            if server.auth_token_env:
                token = os.environ.get(server.auth_token_env)
                if token:
                    entry["headers"] = {"Authorization": f"Bearer {token}"}
            config["mcpServers"][server.name] = entry

    mcp_path = Path(working_dir) / ".mcp.json"
    mcp_path.write_text(json.dumps(config, indent=2))
    return mcp_path


# Clean up in finally block:
if mcp_config_path and mcp_config_path.exists():
    mcp_config_path.unlink()
```

#### codex CLI

Uses the same `CODEX_HOME` + `config.toml` approach as the Codex Server
agent. Since CLI subprocess `codex` uses `codex exec`, set `CODEX_HOME` env:

```python
# In the CLI agent when command == "codex":
if context.mcp_servers:
    tmp_codex_home = Path(tempfile.mkdtemp(prefix="orch-codex-cli-"))
    _write_mcp_config(tmp_codex_home, context.mcp_servers)
    child_env["CODEX_HOME"] = str(tmp_codex_home)
```

### 3.5 User-Managed Agent

Include MCP server URLs in the prompt response so external agents know what
to connect to:

```python
# In the GET /tasks/{id}/prompt endpoint:
if step_config.mcp_servers:
    mcp_section = "\n\n## Available MCP Servers\n"
    for server in step_config.mcp_servers:
        if server.transport == "http" and server.url:
            mcp_section += f"- **{server.name}**: {server.url}\n"
        elif server.transport == "stdio":
            mcp_section += f"- **{server.name}**: `{server.command} {' '.join(server.args)}`\n"
    prompt += mcp_section
```

---

## 4. Critical Architectural Answers

### 4.1 Step-Level Control Without Global Registration

Each agent type naturally scopes MCP servers to individual executions:

| Agent Type     | Scoping Mechanism                                           |
| -------------- | ----------------------------------------------------------- |
| Claude SDK     | Per-request `mcp_servers` array — no global state           |
| Codex Server   | Isolated `CODEX_HOME` per session — config is ephemeral     |
| OpenHands      | Per-`Agent()` constructor `mcp_config` — no global state    |
| CLI claude     | Per-worktree `.mcp.json` — cleaned up after execution       |
| CLI codex      | Isolated `CODEX_HOME` per execution                         |
| User-Managed   | Informational only — external agent decides                 |

None of these approaches require global MCP registration. Every execution
gets exactly the MCP servers declared in its step config.

### 4.2 Dynamic Mount/Unmount

- **Claude SDK**: Automatic. Each API call specifies its own MCP servers.
  No mount/unmount cycle exists.
- **Codex Server**: Servers launch when the session starts and terminate
  when the process exits. A new task gets a new process with potentially
  different MCP servers.
- **OpenHands**: Servers are configured at `Agent()` construction time.
  Each task creates a new Agent, so different tasks can have different servers.
- **CLI**: Config files are written before process launch and cleaned up
  after. Each execution is independent.

**Conclusion**: Dynamic mount/unmount is not needed. Each task execution is
already isolated. Different steps naturally get different MCP servers.

### 4.3 Tool Name Conflicts

If two MCP servers expose a tool with the same name:

- **Claude SDK**: The API handles this natively — tool calls include
  `server_name` to disambiguate. The model sees `server_name:tool_name`.
- **Codex**: Prefixes tool names with the server name automatically.
- **OpenHands**: Uses the server name as a namespace prefix.

**Recommendation**: Encourage unique server names in the YAML. If conflicts
arise, the agent's native namespacing handles it.

### 4.4 MCP Server Unavailability

If an MCP server is unreachable or crashes:

- **Non-blocking by default**: MCP servers are supplementary tools. If a
  server fails to start, the agent should still function using its built-in
  tools (file editing, shell commands).
- **Logging**: Log a warning when an MCP server fails to connect.
- **No retry**: Do not retry MCP server connections. If the agent needs the
  tool and cannot reach it, the agent's own error handling (retry, recovery)
  takes over.
- **Timeout config**: `startup_timeout_sec` and `tool_timeout_sec` prevent
  indefinite hangs.

For Codex, use `required = false` (the default) in the config.toml so the
session proceeds even if the MCP server fails.

---

## 5. Implementation Strategy

### 5.1 Implementation Order

| Phase | Work                                         | Effort | Risk |
| ----- | -------------------------------------------- | ------ | ---- |
| 1     | Config models (`MCPServerConfig`, StepConfig extension, ExecutionContext extension) | S | Low |
| 2     | Executor threading (pass mcp_servers from step config to ExecutionContext) | S | Low |
| 3     | Claude SDK agent wiring | M | Medium |
| 4     | Codex Server agent wiring | M | Low |
| 5     | OpenHands agent wiring | S | Low |
| 6     | CLI subprocess wiring | M | Low |
| 7     | User-managed prompt enrichment | S | Low |
| 8     | Frontend: StepConfig editor for MCP servers | M | Low |
| 9     | Tests | M | Low |

### 5.2 Start With: Claude SDK (Phase 3)

**Why Claude SDK first:**
1. **Cleanest API**: Per-request `mcp_servers` parameter, no file I/O
2. **No process management**: HTTP-based MCP servers are accessed remotely
3. **Easiest to test**: Mock the Anthropic client, verify `mcp_servers` param
4. **Most restrictive**: Only HTTP servers — forces us to design the right
   abstractions early

### 5.3 Minimal Viable Implementation (Phases 1-3)

The smallest useful increment is:

1. Add `MCPServerConfig` and `StepConfig.mcp_servers` to config models
2. Add `ExecutionContext.mcp_servers` to types
3. Thread mcp_servers from step config through executor to context
4. Wire Claude SDK to pass HTTP MCP servers to the Messages API
5. Write one routine YAML with an HTTP MCP server (e.g., context7)
6. Test end-to-end with a Claude SDK run

This gives us a working proof-of-concept with one agent type in ~2 days.

### 5.4 Future Enhancements

- **STDIO-to-HTTP bridge**: For Claude SDK, auto-start a local proxy
  (e.g., `supergateway`) for STDIO MCP servers
- **MCP server health checks**: Pre-flight check in executor before handing
  to agent
- **Cost tracking**: Track MCP server tool usage in execution metrics
- **MCP server library**: Curated list of known-good MCP servers with
  preset configs (like `context7`, `brave-search`, `github`)
- **Task-level MCP overrides**: Allow individual tasks to add/remove MCP
  servers from the step-level list
- **UI MCP management**: Manage MCP servers in the routine editor UI

---

## 6. Executor Wiring (Phase 2 Detail)

The key change is in `AgentExecutor._execute_task()` where the
`ExecutionContext` is constructed.

```python
# In executor.py, _execute_task method, after building requirements:

# Resolve MCP servers for this step
mcp_servers: list[MCPServerConfig] = []
if step_config_id:
    for step_cfg in routine_config.steps:
        if step_cfg.id == step_config_id:
            mcp_servers = step_cfg.mcp_servers
            break

context = ExecutionContext(
    run_id=run.id,
    task_id=task_state.id,
    working_dir=working_dir,
    prompt=f"{prompt.system}\n\n{prompt.user}",
    requirements=requirements,
    api_base_url=self._api_base_url,
    mcp_servers=mcp_servers,  # NEW — threaded from step config
)
```

The same applies to `_handle_verification()` — verifier agents also get
the step's MCP servers.

---

## 7. Testing Strategy

### 7.1 Unit Tests

```python
# tests/unit/test_mcp_config.py

def test_mcp_server_config_stdio():
    """MCPServerConfig validates STDIO transport fields."""
    cfg = MCPServerConfig(
        name="context7",
        transport="stdio",
        command="npx",
        args=["-y", "@upstash/context7-mcp"],
    )
    assert cfg.name == "context7"
    assert cfg.transport == "stdio"

def test_mcp_server_config_http():
    """MCPServerConfig validates HTTP transport fields."""
    cfg = MCPServerConfig(
        name="github",
        transport="http",
        url="https://mcp.github.com/sse",
        auth_token_env="GITHUB_TOKEN",
    )
    assert cfg.url.startswith("https://")

def test_step_config_with_mcp():
    """StepConfig accepts mcp_servers field."""
    step = StepConfig(
        id="S-01",
        title="Build",
        tasks=[TaskConfig(id="T-01", title="Task", task_context="ctx",
                          requirements=[RequirementConfig(id="R-01", desc="req")])],
        mcp_servers=[MCPServerConfig(name="ctx7", command="npx", args=["ctx7"])],
    )
    assert len(step.mcp_servers) == 1

def test_execution_context_mcp_passthrough():
    """ExecutionContext carries MCP servers to agents."""
    ctx = ExecutionContext(
        run_id="r1", task_id="t1", working_dir="/tmp",
        prompt="do it", requirements=["R-01"],
        mcp_servers=[MCPServerConfig(name="test", command="echo")],
    )
    assert len(ctx.mcp_servers) == 1
```

### 7.2 Agent-Specific Tests

```python
# tests/unit/test_claude_sdk_mcp.py

def test_build_mcp_params_http_only():
    """Only HTTP servers are included in Claude SDK MCP params."""
    servers = [
        MCPServerConfig(name="remote", transport="http",
                        url="https://mcp.example.com/sse"),
        MCPServerConfig(name="local", transport="stdio",
                        command="npx", args=["some-server"]),
    ]
    api_servers, toolsets = _build_mcp_params(servers)
    assert len(api_servers) == 1
    assert api_servers[0]["name"] == "remote"
    assert len(toolsets) == 1

def test_build_mcp_params_with_auth():
    """Auth token is resolved from environment."""
    servers = [MCPServerConfig(
        name="authed", transport="http",
        url="https://mcp.example.com/sse",
        auth_token_env="TEST_TOKEN",
    )]
    with patch.dict(os.environ, {"TEST_TOKEN": "secret-123"}):
        api_servers, _ = _build_mcp_params(servers)
    assert api_servers[0]["authorization_token"] == "secret-123"

def test_build_mcp_params_allowlist():
    """Tool allowlisting maps to MCP toolset configs."""
    servers = [MCPServerConfig(
        name="filtered", transport="http",
        url="https://mcp.example.com/sse",
        enabled_tools=["search", "fetch"],
    )]
    _, toolsets = _build_mcp_params(servers)
    assert toolsets[0]["default_config"]["enabled"] is False
    assert "search" in toolsets[0]["configs"]


# tests/unit/test_codex_server_mcp.py

def test_write_mcp_config_toml():
    """MCP servers are written to config.toml in CODEX_HOME."""
    tmp = Path(tempfile.mkdtemp())
    servers = [MCPServerConfig(
        name="context7", command="npx",
        args=["-y", "@upstash/context7-mcp"],
    )]
    _write_mcp_config(tmp, servers)
    content = (tmp / "config.toml").read_text()
    assert "[mcp_servers.context7]" in content
    assert 'command = "npx"' in content


# tests/unit/test_openhands_mcp.py

def test_build_openhands_mcp_config():
    """MCP servers map to OpenHands mcp_config dict."""
    servers = [MCPServerConfig(
        name="fetch", command="uvx",
        args=["mcp-server-fetch"],
    )]
    config = _build_openhands_mcp_config(servers)
    assert "mcpServers" in config
    assert "fetch" in config["mcpServers"]
    assert config["mcpServers"]["fetch"]["command"] == "uvx"
```

### 7.3 Integration Tests

```python
# tests/integration/test_mcp_e2e.py

async def test_routine_with_mcp_servers_parsed():
    """Routine YAML with mcp_servers is parsed into RoutineConfig."""
    yaml_content = '''
    routine:
      id: mcp-test
      name: MCP Test
      steps:
        - id: S-01
          title: Build
          mcp_servers:
            - name: context7
              command: npx
              args: ["-y", "@upstash/context7-mcp"]
          tasks:
            - id: T-01
              title: Task
              task_context: Do it
              requirements:
                - id: R-01
                  desc: Done
    '''
    config = RoutineConfig.model_validate(yaml.safe_load(yaml_content)["routine"])
    assert len(config.steps[0].mcp_servers) == 1
    assert config.steps[0].mcp_servers[0].name == "context7"

async def test_mcp_servers_threaded_to_execution_context(
    client, seed_run_with_mcp,
):
    """MCP servers from step config appear in ExecutionContext."""
    # Verify via a mock agent that receives the context
    ...
```

### 7.4 YAML Validation Tests

```python
def test_routine_without_mcp_servers():
    """Existing routines without mcp_servers still parse correctly."""
    # Backward compatibility — mcp_servers defaults to empty list
    ...

def test_mcp_server_requires_name():
    """MCPServerConfig requires a name field."""
    with pytest.raises(ValidationError):
        MCPServerConfig(command="npx")

def test_stdio_server_needs_command():
    """STDIO transport requires command field."""
    cfg = MCPServerConfig(name="test", transport="stdio")
    # command is optional at the model level but useless without it
    assert cfg.command is None  # Agent will skip it
```

---

## 8. Example: Adding context7 to a Routine

```yaml
routine:
  id: feature-with-docs
  name: Build Feature with Documentation Lookup
  description: Uses context7 MCP for up-to-date library documentation
  steps:
    - id: S-01
      title: Implement Feature
      step_context: |
        Build the requested feature. Use the context7 MCP server
        to look up current API documentation for any libraries you use.
      mcp_servers:
        - name: context7
          transport: stdio
          command: npx
          args: ["-y", "@upstash/context7-mcp@latest"]
      tasks:
        - id: T-01
          title: Build the widget component
          task_context: |
            Create a React widget component using the shadcn/ui library.
            Use the context7 tool to look up the latest shadcn/ui docs.
          requirements:
            - id: R-01
              desc: Widget component created
              priority: critical
            - id: R-02
              desc: Uses shadcn/ui components correctly
              priority: expected
```

### What happens at runtime:

1. Executor reads `step_config.mcp_servers` and passes to `ExecutionContext`
2. **Claude SDK**: Skips context7 (STDIO, not HTTP). To use it, deploy
   context7 behind an HTTP proxy or wait for the STDIO bridge enhancement.
3. **Codex Server**: Writes `[mcp_servers.context7]` to temp config.toml.
   Codex auto-launches the npx command when the session starts.
4. **OpenHands**: Passes `mcp_config={"mcpServers": {"context7": {"command": "npx", "args": [...]}}}` to Agent().
5. **CLI claude**: Writes `.mcp.json` to the worktree with the context7 server definition.
6. **CLI codex**: Same as Codex Server (temp CODEX_HOME with config.toml).

---

## 9. File Change Summary

| File | Change |
| ---- | ------ |
| `src/orchestrator/config/models.py` | Add `MCPServerConfig` model; add `mcp_servers` field to `StepConfig` |
| `src/orchestrator/agents/types.py` | Add `mcp_servers` field to `ExecutionContext` |
| `src/orchestrator/agents/executor.py` | Thread `mcp_servers` from step config to `ExecutionContext` in `_execute_task` and `_handle_verification` |
| `src/orchestrator/agents/claude_sdk.py` | Add `_build_mcp_params()` helper; use beta MCP connector in `execute()` |
| `src/orchestrator/agents/codex_server.py` | Add `_write_mcp_config()` helper; call in `_spawn_transport()` |
| `src/orchestrator/agents/openhands.py` | Add `_build_openhands_mcp_config()` helper; pass to `Agent()` |
| `src/orchestrator/agents/cli.py` | Add `_write_claude_mcp_config()` and codex CODEX_HOME helpers |
| `src/orchestrator/agents/user_managed.py` | No code change (prompt enrichment is in the tasks router) |
| `src/orchestrator/api/routers/tasks.py` | Include MCP server info in prompt response |
| `tests/unit/test_mcp_config.py` | New: config model tests |
| `tests/unit/test_claude_sdk_mcp.py` | New: Claude SDK MCP wiring tests |
| `tests/unit/test_codex_server_mcp.py` | New: Codex config.toml generation tests |
| `tests/unit/test_openhands_mcp.py` | New: OpenHands mcp_config generation tests |
| `tests/integration/test_mcp_e2e.py` | New: end-to-end MCP threading tests |

---

## 10. Sources

- [Anthropic MCP Connector Docs](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector)
- [Codex MCP Support](https://developers.openai.com/codex/mcp/)
- [Codex App Server Protocol](https://developers.openai.com/codex/app-server/)
- [OpenHands SDK MCP Guide](https://docs.openhands.dev/sdk/guides/mcp)
- [OpenHands Software Agent SDK](https://github.com/OpenHands/software-agent-sdk)
