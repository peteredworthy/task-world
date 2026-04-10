# Plan: MCP Operations — Per-Step Tool & External MCP Configuration

## Overview

Implement step-level tool availability and external MCP server support across all five agent types in a phased approach. Each phase delivers a runnable system with passing tests. The plan front-loads schema changes and context plumbing (low risk, high value), then implements agent-specific filtering (medium risk, parallelizable), and finishes with external MCP wiring and integration tests.

**Implementation priority:** CLI and Claude SDK agents first, then Codex Server, OpenHands, and User-Managed.

**Step-level tool semantics:** Step-level `available_tools` and `mcp_servers` are **additive** to phase tools. If a step specifies MCP server A, both Builder and Verifier phases get access to MCP server A. Phase-specific tools (submit, grade, etc.) are always determined by role. Step-level tools add capabilities on top.

**Unknown tool handling:** If `available_tools` references a tool name that doesn't exist, log a warning and continue with the tools that do exist.

**MCP failure handling:** Defer to each agent's error-handling logic. No orchestrator-level required/optional semantics on MCP connections.

## Milestones

### Milestone 1: Schema & Context Foundation (Phase 0 + Phase 1)

Extend data models to carry step-level tool and MCP information from routine YAML through to agents.

- Add `MCPServerConfig` Pydantic model to `src/orchestrator/config/models.py`
- Add `available_tools` and `mcp_servers` fields to `StepConfig`
- Extend `ExecutionContext` with `step_id`, `available_tools`, `mcp_servers`
- Update executor to populate new fields from step config
- Update existing unit tests that construct `StepConfig` or `ExecutionContext`
- Validate YAML parsing of new fields with test routines

**Verification:** Existing tests pass. New unit tests confirm `ExecutionContext` is populated from step config. A routine YAML with `available_tools` and `mcp_servers` parses without error.

### Milestone 2: Agent Tool Filtering (Phase 2)

Each agent respects `context.available_tools` to add step-level tools to its phase tools. Step tools are additive — they expand what's available, they don't restrict phase tools.

- **Priority 1 (CLI + Claude SDK):**
  - CLI: add step-level tool hints to enriched prompt text; include MCP info
  - Claude SDK: filter tool list based on `context.available_tools` before passing to API; add step-level MCP tools additively
- **Priority 2 (Codex Server):**
  - Codex Server: add `is_verifier` param to `build_dynamic_tool_specs()` to exclude `grade` from builders
  - Codex Server: extend `build_dynamic_tool_specs()` to accept `context` and add step-level tools via `available_tools`
- **Priority 3 (OpenHands + User-Managed):**
  - OpenHands: add step-level tools at `Agent()` construction based on `context.available_tools`
  - User-Managed MCP: register all tools at startup, remove phase filtering from `_register_tools()`

Unknown tool names in `available_tools` are logged as warnings but do not cause failures.

**Verification:** Unit tests per agent confirm: (a) when `available_tools=["terminal"]`, terminal tool is added to phase tools; (b) when `available_tools=None` all standard tools are included (backward compat); (c) phase filtering still works (builders don't get `grade`, verifiers get `grade`); (d) unknown tool names produce a warning log but don't fail.

### Milestone 3: External MCP Wiring (Phase 3)

Wire `context.mcp_servers` to each agent's native MCP mechanism. MCP connection failures are deferred to each agent — no orchestrator-level handling.

- **Priority 1 (CLI + Claude SDK):**
  - Claude SDK: convert `MCPServerConfig` list to MCP Connector beta format (`client.beta.messages.create()` with `mcp_servers` parameter and `mcp_toolset` tools; requires beta header `mcp-client-2025-11-20`). Only remote HTTPS servers supported by this path.
  - CLI: write `.mcp.json` to subprocess working dir and/or include MCP URLs in prompt
- **Priority 2 (Codex Server):**
  - Codex Server: pass MCP config via `dynamicTools` in thread creation (no config.toml)
- **Priority 3 (OpenHands + User-Managed):**
  - OpenHands: convert `MCPServerConfig` list to `mcp_config` dict format (`{"mcpServers": {...}}`) for `Agent()` constructor. Supports stdio, SSE, and Streamable HTTP transports natively.
  - User-Managed: include `mcp_servers` info in `CallbackInstructions` / prompt response

**Verification:** Unit tests per agent confirm MCP config reaches the underlying API/subprocess. Integration test with a mock MCP server config in routine YAML verifies the config flows through executor to agent.

### Milestone 4: Integration Testing & Polish (Phase 4)

End-to-end validation and documentation.

- Integration test: routine with per-step `available_tools` — verify different steps get different tool sets
- Integration test: routine with per-step `mcp_servers` — verify different steps get different MCPs
- Integration test: backward compatibility — existing routines without new fields work unchanged
- Update example routines with `available_tools` / `mcp_servers` usage
- Run full test suite and pre-commit checks

**Verification:** All existing tests pass. New integration tests cover the happy path and backward compatibility. `uv run pre-commit run --all-files` passes.

## Implementation Order

Steps are ordered by priority (CLI + Claude SDK first) after the foundation work.

1. **Step 1: MCPServerConfig model + StepConfig extension**
   - Prerequisites: None
   - Files: `src/orchestrator/config/models.py`
   - Deliverables: `MCPServerConfig` model, `available_tools` and `mcp_servers` on `StepConfig`
   - Tests: Unit test for YAML parsing with new fields

2. **Step 2: ExecutionContext extension + Executor wiring**
   - Prerequisites: Step 1
   - Files: `src/orchestrator/agents/types.py`, `src/orchestrator/agents/executor.py`
   - Deliverables: `step_id`, `available_tools`, `mcp_servers` on `ExecutionContext`; executor reads from step config
   - Tests: Unit test confirming context populated from step config

3. **Step 3: CLI agent tool hints + MCP info in prompt** *(Priority 1)*
   - Prerequisites: Step 2
   - Files: `src/orchestrator/agents/cli.py`
   - Deliverables: Available tools listed in prompt; MCP URLs/config in prompt or .mcp.json
   - Tests: Unit test for prompt content includes tool hints and MCP info

4. **Step 4: Claude SDK tool filtering + MCP wiring** *(Priority 1)*
   - Prerequisites: Step 2
   - Files: `src/orchestrator/agents/claude_sdk.py`
   - Deliverables: Tool filtering by `context.available_tools` (additive to phase tools); `mcp_servers` passed via MCP Connector beta (`client.beta.messages.create()` with `mcp_servers` + `mcp_toolset` tools, beta header `mcp-client-2025-11-20`)
   - Tests: Unit tests for filtered vs. unfiltered tool lists; MCP passthrough test
   - Note: MCP Connector only supports remote HTTPS servers

5. **Step 5: Codex Server phase filtering + context filtering + MCP wiring** *(Priority 2)*
   - Prerequisites: Step 2
   - Files: `src/orchestrator/agents/codex_server_common.py`, `src/orchestrator/agents/codex_server.py`
   - Deliverables: `is_verifier` parameter on `build_dynamic_tool_specs()`; `build_dynamic_tool_specs(context)` with additive filtering; MCP config via dynamicTools in thread creation
   - Tests: Codex builder doesn't see grade tool; context-based filtering tests

6. **Step 6: OpenHands tool filtering + MCP wiring** *(Priority 3)*
   - Prerequisites: Step 2
   - Files: `src/orchestrator/agents/openhands.py`
   - Deliverables: Built-in tool filtering (additive); `mcp_config` dict passed to `Agent()` constructor (`{"mcpServers": {...}}` format, supports stdio/SSE/SHTTP)
   - Tests: Unit tests for tool filtering; MCP config passthrough

7. **Step 7: User-Managed MCP all-tools + MCP info in prompt response** *(Priority 3)*
   - Prerequisites: Step 2
   - Files: `src/orchestrator/mcp/server.py`, `src/orchestrator/api/routers/tasks.py`, `src/orchestrator/api/schemas/tasks.py`
   - Deliverables: MCP server registers all tools (remove phase filter); `CallbackInstructions` includes `mcp_servers` field; prompt response includes MCP info
   - Tests: MCP server exposes all tools; prompt response schema test

8. **Step 8: Integration tests + example routines**
   - Prerequisites: Steps 3-7
   - Files: `tests/integration/test_step_tool_control.py`, `examples/routines/`
   - Deliverables: End-to-end tests for step-level tools and MCPs; example routine YAML
   - Tests: Integration tests pass; existing test suite unchanged

9. **Step 9: Final validation**
   - Prerequisites: Step 8
   - Deliverables: Full test suite passes; pre-commit clean; no regressions
   - Verification: `uv run pre-commit run --all-files`; `uv run pytest`

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Field naming | `available_tools` (not `step_tools` or `allowed_tools`) | Consistent with verification report recommendation; clear semantics |
| Default when `available_tools` is None | All standard tools available | Backward compatibility — existing routines work without changes |
| MCP config model | `MCPServerConfig` with url/command dual transport | Supports both HTTP (url) and STDIO (command) MCP servers |
| Auth token handling | `auth_token_env` reference (not inline token) | Security — tokens never appear in YAML files, only env var names |
| User-Managed tool registration | Register all tools, rely on runtime validation | Simpler than per-connection scoping; consistent with REST API; validation already exists |
| CLI tool control | Text hints in prompt (not enforced) | CLI subprocess is an opaque boundary; enforcement not possible |
| External MCP for Claude SDK | MCP Connector beta (`mcp_servers` + `mcp_toolset`, remote HTTPS only) | Native API support confirmed; per-request scoping; lowest effort |
| External MCP for OpenHands | Native `mcp_config` parameter on `Agent()` constructor | SDK supports stdio/SSE/SHTTP via FastMCP; minimal wiring |
| External MCP for Codex Server | dynamicTools only (no config.toml) | Per-thread control; consistent with existing orchestrator tool pattern |
| Phase filtering strategy | Keep existing phase logic; step-level is **additive** | Step tools expand what's available; phase logic handles role-specific tools |
| MCP connection failures | Defer to each agent | Simplest approach; avoids required/optional semantics on MCPServerConfig |
| Unknown tool names in `available_tools` | Log warning, continue | Avoids brittle failures from typos or version drift |
| Agent implementation priority | CLI + Claude SDK first, then Codex, OpenHands, User-Managed | Most actively used agent types get priority |

## References

- `docs/mcp-control/00-START-HERE.md` — Investigation overview and navigation
- `docs/mcp-control/EXTERNAL-MCP-ARCHITECTURE.md` — External MCP design with per-agent wiring
- `docs/mcp-control/IMPLEMENTATION-ROADMAP.md` — Detailed implementation guide with code examples
- `docs/mcp-control/VERIFICATION-AND-CORRECTIONS.md` — Critical corrections to initial analysis
- `docs/mcp-control/README.md` — Agent comparison matrix and implementation checklist
- `docs/mcp-control/26-EXTERNAL-MCP-CONFIG.md` — CLI and User-Managed external MCP patterns
- `docs/ARCHITECTURE.md` — Codebase structure and API routes
- `src/orchestrator/config/models.py:152` — Current `StepConfig` (no tools/mcp fields)
- `src/orchestrator/agents/types.py:52` — Current `ExecutionContext` (no step-level info)
- `src/orchestrator/agents/executor.py:650` — Where `ExecutionContext` is created
