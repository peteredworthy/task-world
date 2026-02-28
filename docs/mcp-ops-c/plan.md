# Plan: MCP Operations — Per-Step Tool & External MCP Configuration

## Overview

Implement step-level tool availability and external MCP server support across all five agent types in a phased approach. Each phase delivers a runnable system with passing tests. The plan front-loads schema changes and context plumbing (low risk, high value), then implements agent-specific filtering (medium risk, parallelizable), and finishes with external MCP wiring and integration tests.

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

Each agent respects `context.available_tools` to restrict which tools are available.

- **Quick wins (2a):**
  - Codex Server: add `is_verifier` param to `build_dynamic_tool_specs()` to exclude `grade` from builders
  - User-Managed MCP: register all tools at startup, remove phase filtering from `_register_tools()`
- **Standard filtering (2b):**
  - Claude SDK: filter tool list based on `context.available_tools` before passing to `messages.create()`
  - OpenHands: filter built-in tools at `Agent()` construction based on `context.available_tools`
  - Codex Server: extend `build_dynamic_tool_specs()` to accept `context` and filter by `available_tools`
- **Optional (2c):**
  - CLI: add step-level tool hints to enriched prompt text

**Verification:** Unit tests per agent confirm: (a) when `available_tools=["terminal"]` only terminal tool is included; (b) when `available_tools=None` all standard tools are included (backward compat); (c) phase filtering still works (builders don't get `grade`, verifiers get `grade`).

### Milestone 3: External MCP Wiring (Phase 3)

Wire `context.mcp_servers` to each agent's native MCP mechanism.

- Claude SDK: convert `MCPServerConfig` list to Claude API `mcp_servers` parameter format
- OpenHands: convert to `mcp_config` dict for `Agent()` constructor
- Codex Server: write MCP config to `config.toml` or pass via `dynamicTools`
- CLI: write `.mcp.json` to subprocess working dir and/or include MCP URLs in prompt
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

3. **Step 3: Quick-win agent fixes**
   - Prerequisites: Step 1 (for Codex phase filtering), None (for MCP all-tools)
   - Files: `src/orchestrator/agents/codex_server_common.py`, `src/orchestrator/mcp/server.py`
   - Deliverables: `is_verifier` parameter on `build_dynamic_tool_specs()`; MCP server registers all tools
   - Tests: Codex builder doesn't see grade tool; MCP server exposes all tools

4. **Step 4: Claude SDK tool filtering + MCP wiring**
   - Prerequisites: Step 2
   - Files: `src/orchestrator/agents/claude_sdk.py`
   - Deliverables: Tool filtering by `context.available_tools`; `mcp_servers` passed to Claude API
   - Tests: Unit tests for filtered vs. unfiltered tool lists; MCP passthrough test

5. **Step 5: OpenHands tool filtering + MCP wiring**
   - Prerequisites: Step 2
   - Files: `src/orchestrator/agents/openhands.py`
   - Deliverables: Built-in tool filtering; `mcp_config` passed to Agent constructor
   - Tests: Unit tests for tool filtering; MCP config passthrough

6. **Step 6: Codex Server full context filtering + MCP wiring**
   - Prerequisites: Steps 2, 3
   - Files: `src/orchestrator/agents/codex_server_common.py`, `src/orchestrator/agents/codex_server.py`
   - Deliverables: `build_dynamic_tool_specs(context)` with full filtering; MCP config in thread creation
   - Tests: Unit tests for context-based filtering

7. **Step 7: CLI agent tool hints + MCP info in prompt**
   - Prerequisites: Step 2
   - Files: `src/orchestrator/agents/cli.py`
   - Deliverables: Available tools listed in prompt; MCP URLs/config in prompt or .mcp.json
   - Tests: Unit test for prompt content includes tool hints and MCP info

8. **Step 8: User-Managed agent MCP info in prompt response**
   - Prerequisites: Step 2
   - Files: `src/orchestrator/api/routers/tasks.py`, `src/orchestrator/api/schemas/tasks.py`
   - Deliverables: `CallbackInstructions` includes `mcp_servers` field; prompt response includes MCP info
   - Tests: Unit test for prompt response schema

9. **Step 9: Integration tests + example routines**
   - Prerequisites: Steps 3-8
   - Files: `tests/integration/test_step_tool_control.py`, `examples/routines/`
   - Deliverables: End-to-end tests for step-level tools and MCPs; example routine YAML
   - Tests: Integration tests pass; existing test suite unchanged

10. **Step 10: Final validation**
    - Prerequisites: Step 9
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
| External MCP for Claude SDK | Native `mcp_servers` API parameter | Cleanest integration; per-request scoping; lowest effort |
| Phase filtering strategy | Keep existing phase logic; step-level is additive | Don't break what works; step filtering is an additional layer |

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
