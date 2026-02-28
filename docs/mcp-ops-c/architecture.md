# Architecture: MCP Operations — Per-Step Tool & External MCP Configuration

## Current State

Tool availability is determined solely by **phase** (builder vs. verifier). Each agent type implements this differently:

- **Claude SDK** (`claude_sdk.py`): Hardcoded tool lists; builder gets `update_checklist`/`submit`/`request_clarification`; verifier gets `set_grade`/`submit`
- **Codex Server** (`codex_server_common.py`): `build_dynamic_tool_specs()` returns all 5 tools unconditionally for every thread regardless of phase
- **OpenHands** (`openhands.py`): Tools registered via `_register_sdk_tools()` with a boolean guard preventing re-registration
- **CLI** (`cli.py`): Phase-specific prompts already implemented (line 136); tool instructions are text-based
- **User-Managed** (`mcp/server.py`): Single global MCP server with phase hardcoded to "building"

`StepConfig` (config/models.py:152) has no tool or MCP fields. `ExecutionContext` (agents/types.py:52) has no step-level information. The executor (executor.py:650) creates context without step awareness.

## Proposed Changes

### New Components

#### MCPServerConfig Model

```python
# src/orchestrator/config/models.py
class MCPServerConfig(BaseModel):
    """Configuration for an external MCP server available during a step."""
    name: str                              # Unique identifier within a step
    url: str | None = None                 # HTTP transport (e.g., "http://localhost:3000")
    command: str | None = None             # STDIO transport (e.g., "context7-mcp")
    args: list[str] | None = None          # CLI args for STDIO transport
    env: dict[str, str] | None = None      # Environment variables for subprocess
    auth_token_env: str | None = None      # Env var name containing auth token (never inline)
    timeout_seconds: int = 30              # Connection timeout
```

Validates that exactly one of `url` or `command` is set (HTTP vs STDIO transport).

### Modified Components

#### StepConfig (config/models.py)

Add two optional fields:

```python
class StepConfig(BaseModel):
    # ... existing fields (id, title, step_context, gate, tasks, transitions, type, dry_run)
    available_tools: list[str] | None = None       # Tool names available in this step
    mcp_servers: list[MCPServerConfig] | None = None  # External MCP servers for this step
```

Both default to `None` (backward compatible — existing routines unchanged).

#### ExecutionContext (agents/types.py)

Add step-level fields:

```python
class ExecutionContext(BaseModel):
    # ... existing fields (run_id, task_id, working_dir, prompt, requirements, api_base_url, auth_token, end_commit)
    step_id: str | None = None                     # Current step identifier
    available_tools: list[str] | None = None        # Tool whitelist for this step
    mcp_servers: list[MCPServerConfig] | None = None  # External MCPs for this step
```

#### Executor (agents/executor.py ~line 650)

Populate new context fields from step config:

```python
step_config = run.routine.steps[run.current_step_index]
context = ExecutionContext(
    # ... existing fields ...
    step_id=step_config.id,
    available_tools=step_config.available_tools,
    mcp_servers=step_config.mcp_servers,
)
```

#### Agent Implementations

Each agent adds step-level tools **additively** to its phase tools and wires MCPs using its native mechanism. If `available_tools` references unknown tool names, a warning is logged but execution continues. MCP connection failures are deferred to each agent's error handling.

| Agent | Tool Filtering | MCP Wiring | Execution Boundary | Priority |
|-------|---------------|------------|-------------------|----------|
| CLI | Include tool list as text in prompt | Write `.mcp.json` to working dir or include URLs in prompt | Per-subprocess | 1st |
| Claude SDK | Add step tools to phase-filtered `tools` list before API call | MCP Connector beta: `client.beta.messages.create()` with `mcp_servers` + `mcp_toolset` tools (remote HTTPS only, beta header `mcp-client-2025-11-20`) | Per-request | 1st |
| Codex Server | Add step tools to `dynamicTools` in `thread/start` | Include MCP config in `dynamicTools` (no config.toml) | Per-thread | 2nd |
| OpenHands | Add step tools at `Agent()` construction | Pass `mcp_config` dict (`{"mcpServers": {...}}`) to constructor; supports stdio/SSE/SHTTP via FastMCP | Per-instance | 3rd |
| User-Managed | Register all tools; runtime validation | Include in `CallbackInstructions` in prompt response | Per-request | 3rd |

### Interactions

```
Routine YAML ──parse──▶ StepConfig
                           │
                           │ available_tools, mcp_servers
                           ▼
                        Executor
                           │
                           │ populate context (step tools ADDITIVE to phase tools)
                           ▼
                     ExecutionContext
                           │
              ┌────────────┼────────────┬────────────┬──────────┐
              ▼            ▼            ▼            ▼          ▼
           CLI        Claude SDK   Codex Server  OpenHands  User-Managed
              │            │            │            │          │
         text hint   add to phase  add to dyn.  add tools   all tools
         .mcp.json   MCP Connector dynamicTools  mcp_config  expose info
              │            │            │            │          │
              ▼            ▼            ▼            ▼          ▼
         subprocess   beta API     thread/start  Agent()    prompt resp
```

**Data flow is one-directional:** YAML → StepConfig → Executor → ExecutionContext → Agent. No feedback loop needed. Tools are fixed when a step starts.

**Additive semantics:** Step-level `available_tools` adds to (never restricts) the phase-determined tool set. Both Builder and Verifier get step-level MCPs. Phase-specific tools (submit, grade, etc.) are always determined by role.

## Technology Choices

| Area | Choice | Rationale |
|------|--------|-----------|
| Schema | Pydantic v2 `BaseModel` | Consistent with all existing models; validation built-in |
| Transport detection | `url` vs `command` field presence | Matches MCP spec (HTTP vs STDIO); explicit and self-documenting |
| Auth | Environment variable references only | Tokens never in YAML/logs/prompts; agent reads from env at runtime |
| Claude SDK MCP | MCP Connector beta (`mcp-client-2025-11-20`) | Native API support; remote HTTPS only; uses `mcp_servers` + `mcp_toolset` |
| OpenHands MCP | Native `mcp_config` parameter | SDK supports stdio/SSE/SHTTP via FastMCP library; `{"mcpServers": {...}}` format |
| Codex Server MCP | dynamicTools only | Per-thread control; consistent with existing orchestrator callback tool pattern |
| CLI MCP config | `.mcp.json` file in working dir | Standard MCP client config format; discovered automatically by Claude Code |
| User-Managed MCP info | `CallbackInstructions` in prompt response | No new endpoints needed; external agent decides which MCPs to connect to |
| MCP failures | Deferred to agents | No orchestrator-level required/optional semantics; simplest approach |
| Unknown tools | Log warning, continue | Avoids brittle failures from typos or version drift in `available_tools` |

## Testing Strategy

### Unit Tests

**Per-agent tool filtering** (6 test files, ~4 tests each):

```
tests/unit/test_claude_sdk_tool_filtering.py
tests/unit/test_codex_server_tool_filtering.py
tests/unit/test_openhands_tool_filtering.py
tests/unit/test_cli_tool_hints.py
tests/unit/test_mcp_server_all_tools.py
tests/unit/test_mcp_server_config.py
```

Each file tests:
- `available_tools=None` → all standard phase tools (backward compat)
- `available_tools=["terminal"]` → terminal tool added to phase tools (additive)
- Phase filtering still works (builders don't get `grade`, verifiers get `grade`)
- Unknown tool names in `available_tools` produce warning, don't fail
- `mcp_servers` config reaches the agent's underlying mechanism

**Schema tests:**
- `MCPServerConfig` validates url-or-command constraint
- `StepConfig` parses with and without new fields
- `ExecutionContext` populates correctly from step config

### Integration Tests

```
tests/integration/test_step_tool_control.py
```

- **test_step_level_available_tools**: Create run with routine having different `available_tools` per step. Verify executor creates correct context for each step.
- **test_step_level_mcp_servers**: Create run with routine having different `mcp_servers` per step. Verify context carries correct MCP config per step.
- **test_backward_compat_no_tools_field**: Create run from existing routine (no `available_tools`). Verify all standard tools available (context.available_tools is None).
- **test_phase_and_step_interaction**: Verify phase-based filtering (builder/verifier) still works alongside step-level `available_tools`.
- **test_codex_phase_filtering**: Verify builder threads don't see `grade` tool after quick-win fix.
- **test_mcp_all_tools_registration**: Verify User-Managed MCP server exposes both builder and verifier tools.

### E2E Tests

- Validate full lifecycle with a test routine that uses `available_tools` and `mcp_servers`:
  - Step 1: `available_tools: [terminal, file_editor]` + chrome MCP
  - Step 2: `available_tools: [file_editor]` + context7 MCP
  - Verify each step's agent gets the correct tool set and MCP config

## Security Considerations

- **Auth tokens never in YAML:** `MCPServerConfig.auth_token_env` stores an env var *name*, not a token value. The executor or agent reads `os.environ[auth_token_env]` at runtime.
- **Tokens never in prompts:** CLI agent passes auth via environment variables to subprocess, not in prompt text.
- **Tokens never in logs:** MCP configs logged with `auth_token_env` field (the variable name), not the resolved value.
- **No new attack surface:** External MCPs are opt-in per routine. If `mcp_servers` is not specified, no external connections are made.
- **Validation at call time:** User-Managed MCP server continues to validate tool calls at runtime (phase-inappropriate calls still rejected with clear error messages).

## Performance Considerations

- **Zero overhead for existing routines:** When `available_tools` and `mcp_servers` are None (the default), no filtering or MCP wiring occurs. The code path is identical to today.
- **Minimal overhead for configured steps:** Tool filtering is a single list intersection at step start (not per-turn). MCP config is passed through as data, not connected eagerly.
- **No eager MCP connections:** The executor passes MCP config as data. The agent decides when/whether to connect. Failed MCPs are handled by each agent individually (deferred to agents).
- **Agent-specific efficiency:**
  - Claude SDK: MCP Connector beta handles server connections on Anthropic's side; minimal client overhead
  - Codex Server: Tool specs built once per thread, not per turn; MCP config via dynamicTools
  - OpenHands: Tools and MCP config set once per agent instance via FastMCP
  - CLI: Config file written once to disk before subprocess starts
  - User-Managed: Info included in prompt response (no runtime cost)

## Files Requiring Changes

| File | Change | Priority |
|------|--------|----------|
| `src/orchestrator/config/models.py` | Add `MCPServerConfig`, extend `StepConfig` | Step 1 (foundation) |
| `src/orchestrator/agents/types.py` | Extend `ExecutionContext` | Step 2 (foundation) |
| `src/orchestrator/agents/executor.py` | Populate step-level context | Step 2 (foundation) |
| `src/orchestrator/agents/cli.py` | Tool hints + MCP info in prompt | Step 3 (Priority 1) |
| `src/orchestrator/agents/claude_sdk.py` | Additive tool filtering + MCP Connector beta wiring | Step 4 (Priority 1) |
| `src/orchestrator/agents/codex_server_common.py` | Add `is_verifier` param + additive context filtering + MCP via dynamicTools | Step 5 (Priority 2) |
| `src/orchestrator/agents/codex_server.py` | MCP config in thread creation via dynamicTools | Step 5 (Priority 2) |
| `src/orchestrator/agents/openhands.py` | Additive tool filtering + native `mcp_config` passthrough | Step 6 (Priority 3) |
| `src/orchestrator/mcp/server.py` | Register all tools (remove phase filter) | Step 7 (Priority 3) |
| `src/orchestrator/api/routers/tasks.py` | MCP info in prompt response | Step 7 (Priority 3) |
| `src/orchestrator/api/schemas/tasks.py` | `CallbackInstructions.mcp_servers` field | Step 7 (Priority 3) |
| `tests/unit/` (multiple) | Tool filtering tests per agent | Steps 3-7 |
| `tests/integration/test_step_tool_control.py` | End-to-end step-level tests | Step 8 |
| `examples/routines/` | Example routines with new fields | Step 8 |
