# Codex Server MCP Investigation: Complete Documentation Index

**Investigation Completed:** February 27, 2026
**Investigator:** Claude Code (Haiku 4.5)
**Total Documentation:** 4 files, ~3,500 lines

---

## Start Here

👉 **New to this investigation?** Read in this order:

1. **CODEX_MCP_FINDINGS_SUMMARY.md** (5 min read)
   - Quick answers to all 5 questions
   - One-page summary with key insights
   - Implementation timeline and effort estimates

2. **CODEX_JSONRPC_HANDSHAKE_REFERENCE.md** (15 min read)
   - JSON-RPC protocol message flow
   - Code locations and implementation details
   - Tool schema format reference

3. **CODEX_SERVER_MCP_INVESTIGATION.md** (30 min read)
   - Complete technical analysis
   - Current behavior documentation
   - Recommended implementation path with code examples

---

## Question-to-Document Mapping

### "Can Codex Server accept and use external MCPs dynamically?"

**Answer:** Yes, but with constraints on per-step variation.

**Read:**
- Primary: `CODEX_MCP_FINDINGS_SUMMARY.md` § "Quick Answers"
- Details: `CODEX_SERVER_MCP_INVESTIGATION.md` § "2. How MCPs Can Be Dynamic per Task"
- Implementation: `CODEX_SERVER_MCP_INVESTIGATION.md` § "8. Recommended Implementation Path"

### "Does Codex Server support MCPs at all currently?"

**Answer:** Supports them in JSON-RPC `thread/start`, but only orchestrator callback tools today.

**Read:**
- Technical: `CODEX_SERVER_MCP_INVESTIGATION.md` § "1. Current Codex Server MCP Support"
- Protocol: `CODEX_JSONRPC_HANDSHAKE_REFERENCE.md` § "Step 2: Create Thread (WITH TOOL REGISTRATION)"

### "Can MCPs be passed to the codex app-server subprocess?"

**Answer:** Yes, via JSON-RPC `thread/start.dynamicTools` parameter.

**Read:**
- Architecture: `CODEX_SERVER_MCP_INVESTIGATION.md` § "1.1 Subprocess Architecture"
- Protocol details: `CODEX_JSONRPC_HANDSHAKE_REFERENCE.md` § "Step 2"
- Code: `/src/orchestrator/agents/codex_server.py` line 435

### "What format would MCPs need to be in?"

**Answer:** JSON Schema tool objects.

**Read:**
- Format spec: `CODEX_SERVER_MCP_INVESTIGATION.md` § "5. Format for Passing MCP Configs"
- Schema reference: `CODEX_JSONRPC_HANDSHAKE_REFERENCE.md` § "Tool Registration Schema"
- Example: `CODEX_SERVER_MCP_INVESTIGATION.md` § "5.3 MCP Format Compatibility"

### "Can the JSON-RPC protocol handle MCP specifications?"

**Answer:** Yes, completely. JSON-RPC is just a transport; tools are plain JSON objects.

**Read:**
- Protocol capability: `CODEX_SERVER_MCP_INVESTIGATION.md` § "4. JSON-RPC Protocol Capabilities"
- Implementation proof: `CODEX_JSONRPC_HANDSHAKE_REFERENCE.md` § "Key Code Locations"

### "Can MCPs be different per thread/per execution?"

**Answer:** Yes per-execution (thread). No per-step within a task (protocol constraint).

**Read:**
- Analysis: `CODEX_SERVER_MCP_INVESTIGATION.md` § "6. Per-Execution vs. Per-Step Tool Control"
- Technical limitation: `CODEX_SERVER_MCP_INVESTIGATION.md` § "4.2 What the JSON-RPC Protocol Doesn't Support"
- Workarounds: `CODEX_SERVER_MCP_INVESTIGATION.md` § "6.2 Enabling Per-Step Control: Two Approaches"

---

## Document Details

### 1. CODEX_MCP_FINDINGS_SUMMARY.md
**Length:** ~300 lines | **Read Time:** 5-10 minutes | **Audience:** Everyone

- Executive summary format
- Quick answer table
- Current behavior overview
- Implementation timeline (phases + effort)
- Risk assessment
- File modification table

**Best for:** Decision makers, quick reference, executive updates.

### 2. CODEX_JSONRPC_HANDSHAKE_REFERENCE.md
**Length:** ~550 lines | **Read Time:** 15-20 minutes | **Audience:** Implementation team

- Complete message flow diagram
- Code location reference
- Helper function documentation
- Error handling patterns
- Tool registration schema
- Protocol constraint summary

**Best for:** Developers implementing tool control, protocol-level debugging.

### 3. CODEX_SERVER_MCP_INVESTIGATION.md
**Length:** ~800 lines | **Read Time:** 30-40 minutes | **Audience:** Technical leads, implementers

- Detailed technical analysis
- Subprocess architecture
- JSON-RPC handshake breakdown
- Tool lifecycle documentation
- Environment and configuration details
- Per-step control options (A, B, C)
- Feasibility assessment
- Implementation roadmap with code examples
- 10-point question-answer summary

**Best for:** Technical deep dives, implementation planning, architecture decisions.

### 4. CODEX_MCP_INDEX.md
**Length:** This file | **Read Time:** 5 minutes | **Audience:** Navigation

- Question-to-document mapping
- Quick reference guide
- Document descriptions
- Cross-references to other MCP docs

**Best for:** Finding the right document, understanding the investigation scope.

---

## Cross-References to Existing Documentation

### Related Investigation Documents

These documents were created as part of a broader MCP investigation across all agent types:

- `/docs/mcp-control/00-START-HERE.md` — Multi-agent MCP investigation navigation
- `/docs/mcp-control/README.md` — Comparison matrix across all agents
- `/docs/mcp-control/IMPLEMENTATION-ROADMAP.md` — Implementation guide for all agents
- `/docs/mcp-control/VERIFICATION-AND-CORRECTIONS.md` — Verification of findings
- `/docs/mcp-control/codex-server-agent.md` — Original Codex analysis (superseded by new docs)
- `/docs/mcp-control/claude-sdk-agent.md` — Claude SDK agent analysis
- `/docs/mcp-control/openhands-agent.md` — OpenHands agent analysis
- `/docs/mcp-control/cli-agent.md` — CLI agent analysis
- `/docs/mcp-control/user-managed-agent.md` — User-managed agent analysis

### Source Code Files Referenced

**Core Codex implementation:**
- `/src/orchestrator/agents/codex_server.py` (803 lines)
- `/src/orchestrator/agents/codex_server_common.py` (777 lines)

**Supporting types and configuration:**
- `/src/orchestrator/agents/types.py` (ExecutionContext definition)
- `/src/orchestrator/config/models.py` (StepConfig definition)
- `/src/orchestrator/agents/executor.py` (ExecutionContext creation site)

**Test files:**
- `/tests/unit/test_codex_server_agent.py`
- `/tests/unit/test_codex_server_common.py`
- `/tests/integration/test_api_full_lifecycle.py` (for integration context)

---

## Key Findings At A Glance

✅ **Codex Server CAN accept MCPs dynamically per task**
- Each task execution spawns new subprocess with its own tool set
- Tools passed via JSON-RPC `thread/start.dynamicTools` parameter
- JSON Schema format, compatible with Claude API and MCP specs

❌ **Codex Server CANNOT change MCPs mid-task**
- Tools locked once `thread/start` succeeds
- No `dynamicTools` parameter in `turn/start`
- Would need per-step threads (high overhead) or protocol extension

✅ **Implementation is feasible with minimal changes**
- Phase 0: Add `available_tools` to StepConfig (5 min)
- Phase 1: Extend ExecutionContext (30 min)
- Phase 2a: Codex phase filtering (15 min)
- Phase 2b: Per-agent filtering (20 min each)

⚠️ **Constraint: Per-step variation needs workaround**
- Option A: Multiple threads (overhead, loses context)
- Option B: Prompt-based tool hints (works with current protocol)
- Option C: Upstream Codex protocol extension (future)

---

## Implementation Quick Start

If you're ready to implement:

1. Start with **Phase 0** → add `available_tools` to `StepConfig`
2. Then **Phase 1** → extend `ExecutionContext` + update executor
3. Then **Phase 2a** → quick win in Codex (phase filtering)
4. Then **Phase 2b** → apply to other agents

**Detailed code examples:** See `CODEX_SERVER_MCP_INVESTIGATION.md` § "8. Recommended Implementation Path"

**Full roadmap with all agents:** See `/docs/mcp-control/IMPLEMENTATION-ROADMAP.md`

---

## File Statistics

| File | Lines | Focus | Time |
|------|-------|-------|------|
| CODEX_MCP_FINDINGS_SUMMARY.md | ~300 | Executive summary | 5 min |
| CODEX_JSONRPC_HANDSHAKE_REFERENCE.md | ~550 | Protocol details | 15 min |
| CODEX_SERVER_MCP_INVESTIGATION.md | ~800 | Complete analysis | 30 min |
| CODEX_MCP_INDEX.md | ~200 | Navigation (this file) | 5 min |
| **Total** | **~1,850** | **Complete coverage** | **55 min** |

Plus ~2,600 lines from existing MCP investigation docs.

**Total MCP investigation scope:** 4,450+ lines across 12 documents.

---

## Verification Checklist

✅ Source code analysis — All 5 questions verified against implementation
✅ JSON-RPC protocol — Message flows documented with code locations
✅ Tool registration — Current behavior and constraints documented
✅ Architecture constraints — Per-step vs. per-thread analyzed
✅ Implementation path — Phased approach with effort estimates provided
✅ Code examples — All recommendations include working code examples
✅ Risk assessment — Each change evaluated for breaking changes
✅ Cross-references — Links to related documentation and source files

---

## Feedback and Updates

This investigation is based on code as of February 27, 2026. If implementation changes:

1. Update CODEX_SERVER_MCP_INVESTIGATION.md with new findings
2. Update CODEX_JSONRPC_HANDSHAKE_REFERENCE.md if protocol changes
3. Update CODEX_MCP_FINDINGS_SUMMARY.md with timeline changes
4. Keep CODEX_MCP_INDEX.md as authoritative navigation

---

## Questions?

- **"I need the quick version"** → Start with CODEX_MCP_FINDINGS_SUMMARY.md
- **"I need implementation details"** → Start with CODEX_SERVER_MCP_INVESTIGATION.md § 8
- **"I need the protocol reference"** → See CODEX_JSONRPC_HANDSHAKE_REFERENCE.md
- **"I need to compare all agents"** → See /docs/mcp-control/00-START-HERE.md
- **"I need code examples"** → See CODEX_SERVER_MCP_INVESTIGATION.md or CODEX_JSONRPC_HANDSHAKE_REFERENCE.md

---

**Investigation Status: COMPLETE ✅**

All questions answered. Implementation roadmap provided. Ready to proceed.
