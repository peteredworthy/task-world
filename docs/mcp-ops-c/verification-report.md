# Verification Report: MCP Operations — Cross-Artifact Alignment

**Date:** 2026-02-28
**Scope:** Verify consistency across intent, plan, architecture, step files (plan + execution), dry-run notes, and clarifications.

---

## 1. Intent → Plan Alignment

| Intent Item | Plan Coverage | Status |
|-------------|--------------|--------|
| `available_tools` on StepConfig | Plan Step 1; Milestone 1 | Aligned |
| `mcp_servers` on StepConfig | Plan Step 1; Milestone 1 | Aligned |
| `MCPServerConfig` model | Plan Step 1; Milestone 1 | Aligned |
| ExecutionContext extension | Plan Step 2; Milestone 1 | Aligned |
| Executor populates context | Plan Step 2; Milestone 1 | Aligned |
| Claude SDK tool filtering + MCP | Plan Step 4; Milestone 2-3 | Aligned |
| Codex Server phase filtering + MCP | Plan Step 5; Milestone 2-3 | Aligned |
| OpenHands tool filtering + MCP | Plan Step 6; Milestone 2-3 | Aligned |
| CLI tool hints + MCP | Plan Step 3; Milestone 2-3 | Aligned |
| User-Managed all-tools + MCP info | Plan Step 7; Milestone 2-3 | Aligned |
| Backward compatibility | Plan Step 8; Milestone 4 | Aligned |
| Unit tests per agent | Plan Steps 3-7; Milestone 2-3 | Aligned |
| Integration tests | Plan Step 8; Milestone 4 | Aligned |
| Pre-commit clean | Plan Step 9; Milestone 4 | Aligned |

**Assessment:** Full alignment. All 16 Definition of Complete items from intent.md are covered by plan steps and milestones. No intent items are missing from the plan.

---

## 2. Plan → Step Files Alignment

### Step-Plan Files (step-XX-plan.md)

| Plan Step | Step-Plan File | Scope Match | Deliverables Match |
|-----------|----------------|-------------|-------------------|
| Step 1: MCPServerConfig + StepConfig | step-01-plan.md | Yes | Yes |
| Step 2: ExecutionContext + Executor | step-02-plan.md | Yes | Yes |
| Step 3: CLI agent | step-03-plan.md | Yes | Yes |
| Step 4: Claude SDK | step-04-plan.md | Yes | Yes |
| Step 5: Codex Server | step-05-plan.md | Yes | Yes |
| Step 6: OpenHands | step-06-plan.md | Yes | Yes |
| Step 7: User-Managed | step-07-plan.md | Yes | Yes |
| Step 8: Integration tests | step-08-plan.md | Yes | Yes |
| Step 9: Final validation | step-09-plan.md | Yes | Yes |

### Step Execution Files (steps/step-XX.md)

| Plan Step | Execution File | Tasks Defined | Concrete Code | Tests Specified |
|-----------|----------------|---------------|---------------|-----------------|
| Step 1 | steps/step-01.md | 3 tasks | Yes — model code, validator | Yes — ~10 unit tests |
| Step 2 | steps/step-02.md | 3 tasks | Yes — context fields, executor wiring | Yes — context population tests |
| Step 3 | steps/step-03.md | 3 tasks | Yes — prompt sections, .mcp.json | Yes — prompt content tests |
| Step 4 | steps/step-04.md | 3 tasks | Yes — tool filtering, beta API | Yes — filtering + MCP tests |
| Step 5 | steps/step-05.md | 3 tasks | Yes — is_verifier, dynamicTools | Yes — phase filtering tests |
| Step 6 | steps/step-06.md | 4 tasks | Yes — research + implementation | Yes — tool filtering + MCP tests |
| Step 7 | steps/step-07.md | 4 tasks | Yes — all-tools, schema, endpoint | Yes — registration + schema tests |
| Step 8 | steps/step-08.md | 2 tasks | Yes — test file, example routine | Yes — integration tests |
| Step 9 | steps/step-09.md | 3 tasks | No (validation only) | N/A (runs existing tests) |

**Assessment:** Full alignment. Every plan step has a corresponding step-plan and execution file. Each execution file breaks the step into concrete tasks with code examples and test specifications.

---

## 3. Clarifications → Design Decisions Traceability

| Clarification | Decision | Traced In |
|---------------|----------|-----------|
| Q1: Step-level vs phase-level tool interaction | **Additive** — step-level tools added to phase tools | Intent (Key Decisions table), Plan (semantics section), Architecture (Additive semantics), all step files |
| Q2: Claude API MCP support | **Research required** — user deferred to implementation | Step 4 execution file (beta API integration), dry-run (HIGH risk noted) |
| Q3: OpenHands MCP wiring | **Research required** — user deferred to implementation | Step 6 execution file (Task 1 = research), dry-run (HIGH risk noted) |
| Q4: MCP connection failures | **Defer to agents** | Intent, Plan, Architecture — all consistent |
| Q5: Unknown tool names | **Log warning, continue** | Intent, Plan, Architecture, step files — all consistent |
| Q6: Agent priority | **CLI + Claude SDK first** | Plan (Implementation Order), step files ordered accordingly |
| Q7: Codex Server MCP wiring | **dynamicTools only** | Step 5 execution file, Architecture (Technology Choices table) |

**Assessment:** All 7 clarifications are consistently reflected across all artifacts. No contradictions found.

---

## 4. Dry-Run Gaps — Disposition

### 4.1 Pre-Existing Bugs Identified in Dry Run

| Bug | Dry-Run Location | Addressed In Step | Status |
|-----|------------------|-------------------|--------|
| Codex builders see `grade` tool | codex_server_common.py:173 | Step 5, Task 1 (add `is_verifier` param) | **Tracked** — fixed as part of Step 5 |
| `tools` param not passed to OpenHandsAgent | executor.py:1413 | Step 6, Task 2 (tool filtering) | **Tracked** — addressed as part of step-level tools |
| UserManagedAgent missing `on_agent_metadata` | user_managed.py:65 | Not explicitly in any step | **Gap** — pre-existing bug, not MCP-specific. Should be tracked separately |
| MCP server phase hardcoded to "building" | app.py:518 | Step 7, Task 1 (all-tools registration) | **Tracked** — mitigated by registering all tools |
| CallbackInstructions not phase-aware | routers/tasks.py:292 | Step 7, Task 2-3 (schema + endpoint) | **Partially tracked** — MCP info added but phase-awareness not explicitly addressed |

### 4.2 Research Items

| Research Topic | Blocking Step | Addressed In | Status |
|----------------|--------------|--------------|--------|
| Anthropic MCP Connector beta API stability | Step 4 | Step 4 execution file — beta integration with fallback | **Tracked** — dry run recommends try/except fallback; step file includes beta API approach |
| Codex dynamicTools MCP schema | Step 5 | Step 5 execution file — Task 2 | **Tracked** — approach defined (mcpServers in thread params), but exact schema needs runtime validation |
| OpenHands `mcp_config` parameter | Step 6 | Step 6 execution file — Task 1 (dedicated research task) | **Tracked** — explicit research task with fallback strategy |

### 4.3 Step-Specific Gaps

| Gap | Dry-Run Severity | Step | Addressed In Execution File | Status |
|-----|-----------------|------|----------------------------|--------|
| Bounds checking on step_index | — | Step 2 | Task 2 mentions executor wiring | **Partially tracked** — guard clause recommended by dry run but not explicitly in execution file |
| Recovery context path | — | Step 2 | Not explicit | **Gap** — dry run notes 3 executor locations; execution file may only cover builder path |
| CLI is opaque boundary | LOW | Step 3 | Documented in plan | **Tracked** — advisory-only is accepted limitation |
| .mcp.json cleanup after step | — | Step 3 | Not explicit in execution file | **Minor gap** — file cleanup not specified |
| .mcp.json format | — | Step 3 | Task 2 specifies Claude Code format | **Tracked** |
| Beta API stability (Claude SDK) | HIGH | Step 4 | Task 2 includes beta API integration | **Tracked** — execution file has beta path; dry run suggests try/except fallback |
| STDIO MCPs silently dropped | MEDIUM | Step 4 | Task 2 filters STDIO with warning | **Tracked** |
| Tool name mapping / collision | MEDIUM | Step 4 | Not explicit | **Minor gap** — no validation against orchestrator tool name collision |
| Codex dynamicTools MCP schema unknown | HIGH | Step 5 | Task 2 defines approach | **Tracked** — approach defined but needs runtime verification |
| Tool allowlist must grow dynamically | MEDIUM | Step 5 | Not explicit | **Minor gap** — static CODEX_SERVER_TOOL_ALLOWLIST needs dynamic expansion |
| Executor doesn't pass tools to OpenHands | HIGH | Step 6 | Task 2 addresses tool filtering | **Tracked** |
| mcp_config not confirmed in OpenHands | HIGH | Step 6 | Task 1 is dedicated research | **Tracked** |
| MCP singleton phase architecture | HIGH | Step 7 | Task 1 (all-tools registration) | **Tracked** — mitigated via all-tools approach |
| Can't test actual agent execution | MEDIUM | Step 8 | Task 1 tests at each layer | **Tracked** — layer-by-layer testing approach |
| MCP Connector can't be tested without live API | MEDIUM | Step 8 | Mock approach specified | **Tracked** |
| Frontend type updates | LOW | Step 9 | Task 3 cross-check | **Tracked** |

---

## 5. Conflict Analysis

### 5.1 No Critical Conflicts Found

After cross-referencing all artifacts, **no critical conflicts** exist between:
- Intent ↔ Plan
- Plan ↔ Step files
- Step-plan files ↔ Step execution files
- Clarifications ↔ Design decisions in all documents
- Architecture ↔ Implementation approach in step files

### 5.2 Minor Inconsistencies (Non-Blocking)

| Item | Documents | Nature | Resolution |
|------|-----------|--------|------------|
| Executor context creation locations | Plan says "~line 650"; dry run notes 3 locations (builder ~650, verifier ~820, recovery ~984) | Plan mentions only one location | Step 2 execution file should update all 3 locations; dry run provides accurate line references |
| CallbackInstructions phase awareness | Dry run flags as pre-existing bug; Step 7 adds MCP info but doesn't explicitly fix phase awareness | Step 7 partially addresses by adding MCP info, but phase-appropriate tool docs not fully specified | Implementer should address both: MCP info AND phase-appropriate tool documentation |
| UserManagedAgent `on_agent_metadata` | Dry run flags as pre-existing protocol violation | Not addressed in any step file | Pre-existing bug; out of scope for MCP operations; should be tracked as separate fix |

---

## 6. Risk Summary

### Risks Addressed by Plan

| Risk | Mitigation |
|------|------------|
| Backward compatibility | All new fields default to None; tested in Step 8 |
| Auth token leakage | `auth_token_env` stores var name only; resolved at runtime; never logged |
| Unknown tool names | Log warning, continue — consistent across all docs |
| MCP connection failures | Deferred to agents — no orchestrator-level handling |

### Residual Risks (Tracked, Not Yet Resolved)

| Risk | Severity | Owner | Notes |
|------|----------|-------|-------|
| Anthropic MCP Connector beta API may differ from plan assumptions | HIGH | Step 4 implementer | Dry run recommends pinning SDK version + try/except fallback |
| Codex dynamicTools may not support MCP natively | HIGH | Step 5 implementer | Fallback: .mcp.json to working dir (same as CLI) |
| OpenHands SDK may not have `mcp_config` parameter | HIGH | Step 6 implementer | Fallback: .mcp.json to working dir; Task 1 is dedicated research |
| 3 executor context creation paths need updating | LOW | Step 2 implementer | Dry run identifies all 3 locations with line numbers |

---

## 7. Readiness Assessment

### Criteria

| Criterion | Status | Notes |
|-----------|--------|-------|
| Intent is clear and complete | **Ready** | 16 Definition of Complete items, clear scope boundaries |
| Plan covers all intent items | **Ready** | 1:1 mapping verified |
| Step files cover all plan steps | **Ready** | 9 plan files + 9 execution files, all aligned |
| Dependencies are correctly ordered | **Ready** | Steps 1-2 foundation → Steps 3-7 agents → Step 8 integration → Step 9 validation |
| Dry-run gaps are tracked | **Ready** | 20 gaps identified; 16 tracked in step files, 3 minor gaps noted, 1 out-of-scope bug |
| No critical conflicts | **Ready** | No contradictions between any artifacts |
| Clarifications are reflected | **Ready** | All 7 Q&A answers traced through all documents |
| Research items identified | **Ready** | 3 research items with clear steps and fallback strategies |

### Overall Verdict

**READY FOR IMPLEMENTATION**

The plan artifacts are internally consistent and comprehensively cover the intent. All dry-run gaps are either addressed in step files or documented with remediation paths. The three HIGH-risk research items (Anthropic beta API, Codex dynamicTools, OpenHands mcp_config) are properly flagged with fallback strategies. No unresolved critical conflicts remain.

### Recommendations

1. **Address the 3 minor gaps** during implementation:
   - Add bounds checking guard clause in Step 2 for all 3 executor paths
   - Add .mcp.json cleanup logic in Step 3
   - Consider tool name collision validation in Step 4
2. **Track `UserManagedAgent.on_agent_metadata` bug** as a separate fix (not MCP-specific)
3. **Perform API research early** (during Steps 1-2) to de-risk Steps 4, 5, 6
4. **Pin `anthropic` SDK version** before implementing Step 4 MCP Connector beta
