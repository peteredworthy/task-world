# MCP Operations — Dry-Run Simulation Notes

Simulated execution of all 9 implementation steps against the actual codebase.
Each step was traced through the code to validate assumptions, identify expected
outputs, and surface blockers.

---

## Step 1: MCPServerConfig Model + StepConfig Extension

### Assumptions Validated
- `StepConfig` at `src/orchestrator/config/models.py:152` is a clean Pydantic BaseModel
- Adding `available_tools: list[str] | None = None` and `mcp_servers: list[MCPServerConfig] | None = None` is fully backward-compatible
- Existing `@model_validator` (`reject_inheritance_in_step`) only checks for `ref`/`use` keys; new fields don't conflict
- `MCPServerConfig` can live in the same file without circular imports

### Expected Outputs
- New `MCPServerConfig` Pydantic model with dual-transport validation (HTTP `url` XOR STDIO `command`)
- `StepConfig` gains two optional fields
- Routine YAML parsing via `loader.py` auto-validates new fields (uses `RoutineConfig.model_validate()`)
- No database migration needed — `RunModel.config` stores JSON blob

### Blockers: None
### Gaps: None

**Verdict: Ready to implement.**

---

## Step 2: ExecutionContext Extension + Executor Wiring

### Assumptions Validated
- `ExecutionContext` at `src/orchestrator/agents/types.py:52` has 9 fields, 3 already optional
- Executor creates `ExecutionContext` in **3 locations** (not 1):
  - Builder phase: `executor.py:~650`
  - Verifier phase: `executor.py:~820`
  - Recovery phase: `executor.py:~984`
- Current step config is accessible via `run.config.steps[run.current_step_index]`

### Expected Outputs
- `ExecutionContext` gains `step_id`, `available_tools`, `mcp_servers` fields (all optional)
- All 3 executor locations updated to populate from `StepConfig`
- Import of `MCPServerConfig` from `config.models` into `agents/types.py`

### Blockers: None
### Gaps

| Gap | Remediation |
|-----|-------------|
| **Bounds checking needed**: `run.current_step_index` could exceed `len(run.config.steps)` in edge cases (e.g., recovery after all steps complete) | Add guard: `if run.current_step_index < len(run.config.steps)` before accessing step config; default to `None` otherwise |
| **Recovery context**: Recovery phase at line ~984 has less context about which step is active | Use `run.current_step_index` with the same guard; recovery should still get step-level tools since recovery operates within the current step |

**Verdict: Ready to implement with minor guard clause.**

---

## Step 3: CLI Agent Tool Hints + MCP Info in Prompt

### Assumptions Validated
- `CLIAgent.build_prompt()` at `cli.py:114-204` already has phase-specific prompt sections
- MCP callback section exists at lines 153-172 for builder phase
- Auth header support is already implemented
- `.mcp.json` file generation is new functionality (no existing pattern to follow)

### Expected Outputs
- "Step Tools" section appended to enriched prompt when `context.available_tools` is set
- "External MCP Servers" section listing URLs/commands when `context.mcp_servers` is set
- `.mcp.json` file written to subprocess working directory
- Auth tokens passed via environment variables to subprocess (never in prompt text)

### Blockers
- **Depends on Steps 1-2**: Cannot access `context.available_tools` or `context.mcp_servers` until schema is extended

### Gaps

| Gap | Remediation |
|-----|-------------|
| **CLI is opaque**: Subprocess tool control is advisory only — agent may ignore hints | Document this limitation; no technical fix possible. Prompt wording should use "you should use" rather than "you must use" |
| **`.mcp.json` cleanup**: File written to working directory persists after step completes | Add cleanup in executor's step-completion logic, or use a temp directory that's cleaned up automatically |
| **`.mcp.json` format**: No standard schema for this file | Use the Claude Code `.mcp.json` format: `{"mcpServers": {"name": {"url": "...", "command": "...", "args": [...]}}}` — most CLI agents (Claude Code, Codex) recognize this |

**Verdict: Ready to implement after Steps 1-2. Advisory-only nature is acceptable.**

---

## Step 4: Claude SDK Tool Filtering + MCP Wiring

### Assumptions Validated
- Tool lists at `claude_sdk.py:172-292` are hardcoded per phase (`_BUILDER_TOOLS`, `_VERIFIER_TOOLS`)
- Tool selection at line 563: `tools = _VERIFIER_TOOLS if is_verifier else _BUILDER_TOOLS`
- Client creation at line ~545 uses `anthropic.Anthropic()` without beta configuration
- API call at line ~582 uses `client.messages.create()` (not beta path)

### Expected Outputs
- Additive tool filtering: step-level tools appended to phase tools list
- Unknown tool names logged as warnings but don't fail
- MCP Connector beta integration for external HTTPS servers
- STDIO-transport MCPs filtered out with warning (beta only supports remote HTTPS)

### Blockers
- **Depends on Steps 1-2**

### Gaps

| Gap | Severity | Remediation |
|-----|----------|-------------|
| **MCP Connector beta API stability unknown** | HIGH | The `mcp-client-2025-11-20` header and `client.beta.messages.create()` path need validation against the current Anthropic SDK version. If the beta API has changed, implementation must adapt. **Remediation**: Pin `anthropic` SDK version in `pyproject.toml`; add a try/except wrapper that falls back to standard `messages.create()` if beta path fails; log warning about MCP servers being unavailable |
| **STDIO MCPs silently dropped** | MEDIUM | Plan says STDIO MCPs are filtered out with warning, but routine authors won't know their MCPs are ignored until runtime. **Remediation**: Add a validation warning in `loader.py` when a routine uses STDIO MCPs with Claude SDK agent type; alternatively, document this limitation in the example routine YAML |
| **Tool name mapping**: Step-level `available_tools` names must match Anthropic API tool names | MEDIUM | Orchestrator tool names (e.g., `orchestrator_update_checklist`) differ from typical API tool names. **Remediation**: Step-level tools are external/custom tools — they map to tool definitions, not orchestrator callbacks. Add validation that step-level tool names don't collide with orchestrator tool names |
| **Beta header conflicts**: Adding beta header may conflict with other beta features | LOW | **Remediation**: Use header merging — `default_headers={**existing_headers, "anthropic-beta": "mcp-client-2025-11-20"}` |

**Verdict: Implementable but carries the highest technical risk. MCP Connector beta API must be validated early.**

---

## Step 5: Codex Server Phase Filtering + Context Filtering + MCP Wiring

### Assumptions Validated
- `build_dynamic_tool_specs()` at `codex_server_common.py:173-258` takes **no parameters** (confirmed bug)
- Returns all 5 tools unconditionally — builders see `grade` tool (confirmed bug)
- Called from `codex_server.py:435` without parameters, even though `is_verifier` is computed at line 364
- `CODEX_SERVER_TOOL_ALLOWLIST` at lines 309-317 defines 5 allowed tools
- `enforce_tool_allowlist()` at lines 320-346 validates against allowlist

### Expected Outputs
- `build_dynamic_tool_specs(is_verifier, context)` — new signature with phase + context params
- `grade` tool excluded from builder phase
- Step-level tools from `context.available_tools` added to tool specs
- MCP server configs wired via `dynamicTools` (per-thread control)

### Blockers
- **Depends on Steps 1-2**

### Gaps

| Gap | Severity | Remediation |
|-----|----------|-------------|
| **Phase filtering bug is pre-existing** | HIGH | Builders currently see `grade` tool. This bug should be fixed FIRST, independently of MCP work, as a standalone bugfix. **Remediation**: Fix `build_dynamic_tool_specs()` immediately by adding `is_verifier` parameter. Could be a separate PR |
| **Codex dynamicTools MCP schema unknown** | HIGH | Plan assumes MCP servers can be included in `dynamicTools` payload, but doesn't specify the exact JSON schema. The Codex app-server API may have a different mechanism for MCP. **Remediation**: Research Codex app-server documentation or source code for MCP tool registration format. If `dynamicTools` doesn't support MCP natively, consider: (a) proxying through orchestrator, (b) writing `.mcp.json` to working directory (same as CLI approach), or (c) deferring Codex MCP support to a future iteration |
| **Tool allowlist must grow**: Adding step-level tools means `CODEX_SERVER_TOOL_ALLOWLIST` is no longer static | MEDIUM | **Remediation**: Make allowlist dynamic — merge static orchestrator tools with step-level tool names at runtime. Update `enforce_tool_allowlist()` to accept an expanded allowlist |

**Verdict: Phase filtering bugfix is straightforward. MCP wiring for Codex needs research — may need to be deferred if dynamicTools doesn't support it.**

---

## Step 6: OpenHands Tool Filtering + MCP Wiring

### Assumptions Validated
- OpenHands `Agent.__init__()` at `openhands.py:386-404` **does accept `tools` parameter** (confirmed)
- `tools` stored as `self._tools` (line 401), used in `_register_sdk_tools()` at line 481
- `register_builtin_tools(tool_names)` in `openhands_common.py:412-433` handles tool module import
- Default tools: `["terminal", "file_editor"]`

### Expected Outputs
- Step-level tools added to `tools` parameter at Agent construction (additive to defaults)
- MCP server configs converted to OpenHands format: `{"mcpServers": {"name": {...}}}`
- Graceful fallback if `mcp_config` parameter is unsupported

### Blockers
- **Depends on Steps 1-2**

### Gaps

| Gap | Severity | Remediation |
|-----|----------|-------------|
| **Executor doesn't pass `tools` parameter** | HIGH | `executor.py:1413-1418` creates `OpenHandsAgent` without passing `tools`. This is a pre-existing gap (unrelated to MCP work). **Remediation**: Add `tools=agent_config.get("tools")` to OpenHandsAgent instantiation in executor. Step-level tools from `context.available_tools` should be merged with agent-config tools |
| **`mcp_config` parameter NOT confirmed** | HIGH | Plan flags this as "research required (Clarification Q3)" — the OpenHands `Agent()` constructor doesn't have an `mcp_config` parameter in the current codebase. Must confirm if the OpenHands SDK supports it. **Remediation**: (a) Check OpenHands SDK docs/source for `mcp_config` support; (b) If unsupported, write `.mcp.json` to working directory as fallback (same as CLI approach); (c) If partially supported, use what's available and document limitations |
| **Tool name mismatch risk**: OpenHands SDK tools (`terminal`, `file_editor`, `browser`) differ from orchestrator tool names | LOW | Step-level `available_tools` should map to SDK tool names, not orchestrator tool names. **Remediation**: Document that `available_tools` in routine YAML uses agent-native names, and orchestrator tools are always available regardless |

**Verdict: Implementable for tool filtering. MCP wiring needs SDK research — fallback to `.mcp.json` is viable.**

---

## Step 7: User-Managed MCP All-Tools + MCP Info in Prompt Response

### Assumptions Validated
- `OrchestratorMCPServer` at `mcp/server.py:42-68` has phase-based filtering (confirmed working)
- `BUILDER_TOOLS` and `VERIFIER_TOOLS` sets are defined and used for registration
- `CallbackInstructions` schema at `api/schemas/tasks.py:130-137` exists with REST + MCP instructions
- Prompt endpoint at `routers/tasks.py:408-506` returns `phase` field correctly

### Expected Outputs
- MCP server registers ALL tools (builder + verifier) — runtime validation prevents phase-inappropriate calls
- `CallbackInstructions` extended with `mcp_servers` field for external MCPs
- Prompt response includes external MCP server info from execution context

### Blockers
- **Depends on Steps 1-2**

### Gaps

| Gap | Severity | Remediation |
|-----|----------|-------------|
| **MCP server phase is hardcoded at startup** | HIGH | `app.py:518` creates MCP server with `phase="building"` (default). It's a singleton — phase doesn't change per-request. External verifier agents always see builder tools. **Remediation**: Two options: (a) Refactor to query task state dynamically in `_SessionPerCallHandler` before tool dispatch — check the task's current status and reject phase-inappropriate calls with clear error messages; (b) Create separate `/mcp/building` and `/mcp/verifying` endpoints. Option (a) is preferred — it matches the plan's "all-tools registered, runtime validation" approach |
| **CallbackInstructions are phase-unaware** | MEDIUM | Generated instructions list builder tools for both phases. Verifier agents don't see `orchestrator_set_grade` in the instructions. **Remediation**: Pass `phase` to `_build_callback_instructions()` and generate phase-appropriate tool documentation |
| **UserManagedAgent missing `on_agent_metadata` parameter** | MEDIUM | `user_managed.py` doesn't accept `on_agent_metadata` callback — protocol violation vs `interface.py:33`. **Remediation**: Add `on_agent_metadata: AgentMetadataCallback | None = None` parameter to `execute()`. This is a pre-existing bug, not MCP-specific |
| **No `mcp_servers` field in `CallbackInstructions`** | LOW | Plan says to add it. Simple schema addition. **Remediation**: Add `mcp_servers: list[dict] | None = None` field; populate from execution context in prompt endpoint |

**Verdict: Implementable. The MCP singleton phase issue requires architectural attention but the "all-tools + runtime validation" approach is sound.**

---

## Step 8: Integration Tests + Example Routines

### Assumptions Validated
- Test pattern established in `tests/integration/test_api_full_lifecycle.py` — uses ASGI transport with in-memory DB
- Test fixtures available at `tests/fixtures/routines/`
- Helper function pattern (flat functions, not test classes) is well-established

### Expected Outputs
- `tests/integration/test_step_tool_control.py` with E2E tests covering:
  - Step-level tools parsed from routine YAML
  - MCP servers parsed from routine YAML
  - Backward compatibility (routines without new fields still work)
  - Phase + step tool interaction (additive semantics)
  - All-tools registration in MCP server
- Example routine YAML files demonstrating `available_tools` and `mcp_servers` usage
- Routines parse without errors

### Blockers
- **Depends on all prior steps (1-7)**

### Gaps

| Gap | Severity | Remediation |
|-----|----------|-------------|
| **Can't test actual agent execution in integration tests** | MEDIUM | Agent execution happens outside request/response cycle (known architectural gap from MEMORY.md). Tests can only verify: YAML parsing, context population, prompt generation, tool filtering logic. **Remediation**: Test each layer independently: (a) config parsing tests for YAML → StepConfig; (b) unit tests for tool filtering functions; (c) integration tests for prompt endpoint returning correct tool info |
| **MCP Connector beta can't be tested without live Anthropic API** | MEDIUM | Claude SDK MCP wiring requires actual API calls. **Remediation**: Mock `anthropic.Anthropic` client in tests; verify correct beta headers and `mcp_servers` parameters are passed; don't test actual MCP connection |

**Verdict: Straightforward testing work. Layer-by-layer testing approach handles the agent execution limitation.**

---

## Step 9: Final Validation

### Assumptions Validated
- Test baseline: 330 unit + 235 integration + 221 frontend = 786 tests (from MEMORY.md)
- Pre-commit hooks configured
- TypeScript type checking and ESLint are part of CI

### Expected Outputs
- All existing tests still pass (no regressions)
- New tests pass
- Test count meets or exceeds baseline
- Pre-commit checks clean

### Blockers: None
### Gaps

| Gap | Severity | Remediation |
|-----|----------|-------------|
| **Frontend type updates may be needed** | LOW | If `CallbackInstructions` schema changes, TypeScript types in `ui/` may need updating. **Remediation**: Check `ui/src/types/` for any `CallbackInstructions` type definitions; update if present |

**Verdict: Standard validation step. No significant risks.**

---

## Cross-Cutting Gaps Summary

### Pre-Existing Bugs (should be fixed regardless of MCP work)

| Bug | Location | Impact |
|-----|----------|--------|
| Builders see `grade` tool in Codex Server | `codex_server_common.py:173` | Low risk (builders would get an error if they tried to use it) but violates principle of least privilege |
| `tools` parameter not passed to OpenHandsAgent | `executor.py:1413` | Tool filtering config in detector.py is dead code |
| UserManagedAgent missing `on_agent_metadata` | `user_managed.py:65` | Protocol violation — would fail if executor tried to pass metadata callback |
| MCP server phase hardcoded to "building" | `app.py:518` | Verifier agents connecting via MCP see wrong tools |
| CallbackInstructions not phase-aware | `routers/tasks.py:292` | Verifier agents don't see `orchestrator_set_grade` in docs |

### Research Required Before Implementation

| Topic | Blocking Step | How to Resolve |
|-------|--------------|----------------|
| Anthropic MCP Connector beta API stability | Step 4 | Check `anthropic` SDK version; test `client.beta.messages.create()` with `mcp_servers` param; pin SDK version |
| Codex dynamicTools MCP schema | Step 5 | Review Codex app-server docs/source for MCP in `dynamicTools` format |
| OpenHands `mcp_config` parameter support | Step 6 | Check OpenHands SDK source; test `Agent(mcp_config=...)` constructor |

### Implementation Risk Matrix

| Step | Risk Level | Primary Risk | Mitigation |
|------|-----------|--------------|------------|
| 1 | LOW | None significant | — |
| 2 | LOW | Bounds checking on step index | Guard clause |
| 3 | LOW | Advisory-only tool control for CLI | Acceptable; document limitation |
| 4 | **HIGH** | MCP Connector beta API may not match plan assumptions | Pin SDK; add try/except fallback; validate early |
| 5 | **MEDIUM** | Codex MCP schema unknown; pre-existing phase bug | Research first; fix bug independently |
| 6 | **MEDIUM** | OpenHands `mcp_config` may not exist | Fallback to `.mcp.json` approach |
| 7 | **MEDIUM** | MCP singleton phase architecture | "All-tools + runtime validation" approach is viable |
| 8 | LOW | Standard testing work | — |
| 9 | LOW | Standard validation | — |

### Recommended Implementation Order Adjustments

The plan's order (1→2→3→4→5→6→7→8→9) is sound, with these refinements:

1. **Fix pre-existing bugs first** (before Step 1): Codex phase filtering, executor tools param, UserManagedAgent protocol. These are independent of MCP work and reduce risk.
2. **Do API research early** (during Step 1-2): Validate MCP Connector beta, Codex dynamicTools schema, OpenHands mcp_config in parallel with schema work.
3. **Steps 1-2 are the critical path**: All subsequent steps are blocked until schema is extended.
4. **Step 4 (Claude SDK) is the highest risk**: Start with a spike/proof-of-concept for MCP Connector beta before full implementation.
5. **Steps 3, 6, 7 can be partially parallelized**: They modify different agent files with no interdependencies (beyond Steps 1-2).

---

## Overall Assessment

The plan is **well-structured and implementable**. The 9-step sequence correctly
identifies dependencies and the additive-semantics design decision simplifies
each step. The primary risks are external API uncertainties (Anthropic beta,
Codex dynamicTools, OpenHands mcp_config) — all addressable with early research
and fallback strategies.

**Estimated gap count**: 5 pre-existing bugs + 3 research items + ~12 step-specific gaps = ~20 items total, all with concrete remediation paths documented above.
