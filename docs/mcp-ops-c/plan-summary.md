# MCP Operations — Execution Summary

## Intent Satisfaction

This plan fully addresses the original intent: **transform tool availability from phase-only to step-level granularity** and **add external MCP server support** across all five agent types.

All 16 Definition of Complete items from the intent are mapped 1:1 to implementation steps. The verification report confirms full alignment across intent, plan, architecture, step files, dry-run notes, and clarifications — with no critical conflicts.

### Coverage by Intent Area

| Intent Area | Steps | Status |
|-------------|-------|--------|
| Schema foundation (`MCPServerConfig`, `StepConfig`, `ExecutionContext`) | 1, 2 | Fully specified |
| Tool filtering per agent (5 agents) | 3, 4, 5, 6, 7 | Fully specified |
| External MCP wiring per agent | 3, 4, 5, 6, 7 | Fully specified (3 require API research) |
| Backward compatibility | 8 | Tested via integration tests |
| Regression safety | 9 | Full test suite + pre-commit |

---

## Ordered Step List

| Step | Description | Tasks | Files Modified | Risk |
|------|-------------|-------|----------------|------|
| 1 | MCPServerConfig model + StepConfig extension | 3 | `config/models.py` | LOW |
| 2 | ExecutionContext extension + Executor wiring | 3 | `agents/types.py`, `agents/executor.py` | LOW |
| 3 | CLI agent tool hints + MCP info in prompt | 3 | `agents/cli.py` | LOW |
| 4 | Claude SDK tool filtering + MCP Connector beta | 3 | `agents/claude_sdk.py` | **HIGH** |
| 5 | Codex Server phase filtering + MCP via dynamicTools | 3 | `agents/codex_server_common.py`, `agents/codex_server.py` | MEDIUM |
| 6 | OpenHands tool filtering + MCP wiring | 4 | `agents/openhands.py` | MEDIUM |
| 7 | User-Managed all-tools + MCP in prompt response | 4 | `mcp/server.py`, `api/routers/tasks.py`, `api/schemas/tasks.py` | MEDIUM |
| 8 | Integration tests + example routines | 2 | `tests/integration/`, `examples/routines/` | LOW |
| 9 | Final validation | 3 | None (validation only) | LOW |
| **Total** | | **28 tasks** | | |

### Dependencies

```
Step 1 ──→ Step 2 ──┬──→ Step 3 (CLI, Priority 1)
                    ├──→ Step 4 (Claude SDK, Priority 1)
                    ├──→ Step 5 (Codex Server, Priority 2)
                    ├──→ Step 6 (OpenHands, Priority 3)
                    └──→ Step 7 (User-Managed, Priority 3)
                              │
                    Steps 3-7 ──→ Step 8 ──→ Step 9
```

Steps 3-7 are parallelizable after Step 2 completes.

---

## Key Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Step-level vs phase-level interaction | **Additive** — step-level tools expand phase tools | Phase logic handles role-specific tools (submit, grade); step config adds capabilities on top |
| 2 | Unknown tool names | **Log warning, continue** | Avoids brittle failures from typos or version drift |
| 3 | MCP connection failures | **Defer to agents** | Each agent handles failures via its own error logic; no required/optional semantics |
| 4 | Agent priority | **CLI + Claude SDK first** | Most actively used agent types get priority |
| 5 | Claude SDK MCP wiring | **MCP Connector beta** (`mcp_servers` param, remote HTTPS only) | Native API support; per-request scoping; STDIO servers filtered with warning |
| 6 | OpenHands MCP wiring | **Native `mcp_config` parameter** (needs research) | SDK may support stdio/SSE/SHTTP via FastMCP; fallback to `.mcp.json` |
| 7 | Codex Server MCP wiring | **dynamicTools only** (no config.toml) | Per-thread control; consistent with existing callback tool pattern |
| 8 | User-Managed tool registration | **Register all tools, runtime validation** | Simpler than per-connection scoping; validation already exists |
| 9 | Auth token handling | **`auth_token_env` env var reference** | Tokens never appear in YAML, logs, or prompts — only env var names |
| 10 | CLI tool control | **Advisory text hints only** | CLI subprocess is an opaque boundary; enforcement not possible |
| 11 | Default when `available_tools` is None | **All standard tools available** | Backward compatibility — existing routines unchanged |
| 12 | Transport detection | **Field presence** (`url` XOR `command`) | Matches MCP spec conventions; validated by Pydantic model |

---

## Risks and Mitigations

### HIGH Risk

| Risk | Step | Impact | Mitigation |
|------|------|--------|------------|
| Anthropic MCP Connector beta API may differ from plan assumptions | 4 | Claude SDK MCP wiring may not work | Pin SDK version; wrap in try/except; fall back to standard `messages.create()` without MCP; validate early during Steps 1-2 |

### MEDIUM Risk

| Risk | Step | Impact | Mitigation |
|------|------|--------|------------|
| Codex `dynamicTools` may not support MCP natively | 5 | Codex MCP wiring blocked | Fall back to `.mcp.json` written to working dir (CLI approach); research Codex app-server docs first |
| OpenHands SDK may lack `mcp_config` parameter | 6 | OpenHands MCP wiring blocked | Dedicated research task (Task 1); fall back to `.mcp.json` if unsupported |
| MCP server phase hardcoded to "building" | 7 | Verifier agents see wrong tools | Mitigated by registering ALL tools + runtime validation for phase-inappropriate calls |
| Pre-existing Codex phase bug (builders see `grade`) | 5 | Increases risk surface | Fixed as part of Step 5 by adding `is_verifier` parameter |

### LOW Risk

| Risk | Step | Impact | Mitigation |
|------|------|--------|------------|
| Bounds checking on `current_step_index` | 2 | Possible IndexError in edge cases | Guard clause before accessing `run.config.steps[idx]` |
| `.mcp.json` file persists after step completes | 3 | Stale config in working dir | Cleanup in executor step-completion logic |
| Frontend type updates needed | 9 | TypeScript build may fail | Check `ui/src/types/` for `CallbackInstructions` types |

---

## Caveats for Execution

### Research Dependencies

Three steps require API/SDK research before implementation can be finalized. The plan includes fallback strategies for each, but implementers should perform this research early (during Steps 1-2) to de-risk:

1. **Anthropic MCP Connector beta** (Step 4) — Validate `client.beta.messages.create()` with `mcp_servers` param and `mcp-client-2025-11-20` header against the installed SDK version.
2. **Codex dynamicTools MCP schema** (Step 5) — Confirm the exact JSON format for MCP servers within `dynamicTools` thread creation payload.
3. **OpenHands `mcp_config` parameter** (Step 6) — Check OpenHands SDK source for native MCP support at the `Agent()` constructor level.

### Pre-Existing Bugs

The dry-run surfaced 5 pre-existing bugs unrelated to MCP work. Three are addressed within plan steps; two should be tracked separately:

- **Fixed in-scope:** Codex phase filtering (Step 5), executor `tools` param for OpenHands (Step 6), MCP singleton phase (Step 7)
- **Out-of-scope:** `UserManagedAgent` missing `on_agent_metadata` parameter, `CallbackInstructions` not fully phase-aware

### Testing Limitations

- **Agent execution is untestable end-to-end** via integration tests — execution happens outside the request/response cycle. Testing uses a layer-by-layer approach: config parsing, tool filtering logic, prompt generation, and API parameter passthrough.
- **MCP Connector beta requires mocking** — live Anthropic API calls aren't feasible in tests. Tests verify correct beta headers and `mcp_servers` parameters are passed to the client.

### CLI Tool Control is Advisory Only

The CLI subprocess is an opaque boundary. `available_tools` for CLI agents produces text hints in the prompt, not enforced restrictions. The agent may choose to use tools not listed. This is an accepted architectural limitation.

### All New Fields Are Optional

Every new field (`available_tools`, `mcp_servers`, `step_id`) defaults to `None`. Existing routines work without modification. This is the backward-compatibility guarantee.

### STDIO MCPs Not Supported by Claude SDK

The MCP Connector beta only supports remote HTTPS servers. STDIO-transport MCPs specified in routine YAML are filtered out with a warning when running through the Claude SDK agent. Other agents (OpenHands, CLI) may support STDIO depending on research outcomes.
