# Intent: MCP Operations — Per-Step Tool & External MCP Configuration

## Original Request

Implement the features described in `docs/mcp-control/`: enable per-step MCP tool availability and external MCP server configuration across all five agent types (Claude SDK, Codex Server, OpenHands, CLI, User-Managed).

## Goal

Transform the orchestrator's tool availability system from **phase-only** (builder vs. verifier) to **step-level** granularity, and add support for **external MCP servers** (e.g., chrome-mcp, context7) that can be configured per-step in routine YAML definitions. After implementation, routine authors can specify which tools and external MCPs are available at each step, and each agent type respects those constraints at execution time.

### Current State

- Tool availability is determined by **phase only** (builder gets checklist/submit tools; verifier gets grade tools)
- `StepConfig` has no `available_tools` or `mcp_servers` fields
- `ExecutionContext` carries no step-level tool information
- External MCPs are not supported by any agent type
- Each agent type implements tool selection differently with no unified mechanism

### Desired End State

- Routine YAML definitions support `available_tools` and `mcp_servers` per step
- `ExecutionContext` carries step-level tool and MCP configuration to every agent
- Each agent type filters/configures tools based on `context.available_tools`
- Each agent type wires external MCP servers using its native mechanism (API parameter, config file, prompt text)
- Phase-based filtering still works as a baseline when no step-level config is specified

## Scope

### In Scope

- Add `available_tools: list[str] | None` and `mcp_servers: list[MCPServerConfig] | None` fields to `StepConfig`
- Create `MCPServerConfig` Pydantic model (name, url, command, args, env, auth_token_env, timeout)
- Extend `ExecutionContext` with `step_id`, `available_tools`, and `mcp_servers`
- Update executor to populate step-level context from `StepConfig`
- Implement tool filtering in Claude SDK agent (filter tools passed to Messages API)
- Implement tool filtering in Codex Server agent (add `is_verifier` parameter and step-level `dynamicTools`)
- Implement tool filtering in OpenHands agent (filter tools at `Agent()` construction)
- Implement tool hints in CLI agent (include available tools/MCPs in prompt text)
- Register all tools in User-Managed MCP server (remove phase filtering, rely on runtime validation)
- Expose external MCP info in prompt response for User-Managed agents
- Wire external MCPs to Claude SDK (`mcp_servers` API parameter), Codex Server (config.toml or dynamicTools), OpenHands (`mcp_config` parameter), CLI (.mcp.json or prompt text)
- Unit tests for tool filtering per agent type
- Integration tests for step-level tool availability
- Integration tests for external MCP configuration passthrough

### Out of Scope

- Codex Server process-per-run optimization (documented in `CODEX-SERVER-OPTIMIZATION.md` but separate initiative)
- Frontend UI for configuring `available_tools` / `mcp_servers` in routine editor
- MCP client library implementation for proxy pattern (User-Managed proxy beyond info exposure)
- Dynamic tool updates mid-execution (tools are fixed at step start)
- Tool registry abstraction layer (Phase 3 future work)
- Production readiness for Codex Server variants (blocked by separate risk items R-01 through R-06)

## Definition of Complete

- [ ] `StepConfig` in `src/orchestrator/config/models.py` has `available_tools` and `mcp_servers` fields
- [ ] `MCPServerConfig` model exists with url/command/args/env/auth_token_env/timeout fields
- [ ] `ExecutionContext` in `src/orchestrator/agents/types.py` has `step_id`, `available_tools`, `mcp_servers`
- [ ] Executor populates step-level context from `StepConfig` when creating `ExecutionContext`
- [ ] Claude SDK agent filters tools based on `context.available_tools` and passes `mcp_servers` to API
- [ ] Codex Server agent uses `is_verifier` for phase filtering and supports step-level tool specs
- [ ] OpenHands agent filters built-in tools based on `context.available_tools` and passes `mcp_config`
- [ ] CLI agent includes available tools and external MCP info in subprocess prompt
- [ ] User-Managed MCP server registers all tools (no phase filtering at registration)
- [ ] User-Managed prompt response includes external MCP server information
- [ ] Existing routines without `available_tools`/`mcp_servers` still work (backward compatible)
- [ ] Unit tests pass for tool filtering in each agent type
- [ ] Integration tests verify step-level tool control works end-to-end
- [ ] Integration tests verify external MCP config reaches each agent type
- [ ] All existing tests continue to pass (no regressions)
- [ ] `uv run pre-commit run --all-files` passes cleanly
