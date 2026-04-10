# MCP Tool Control Investigation: Start Here

**Investigation Date:** 2026-02-27
**Investigation Scope:** All five agent types (Claude SDK, Codex, OpenHands, CLI, User-Managed)
**Status:** Complete ✅ with verification and corrections

---

## What This Investigation Answers

**Question:** How can we specify MCP tool availability on a step-by-step basis across all agent types?

**Answer:** It's possible but requires architectural changes across multiple layers:
1. Extend the routine schema with tool configuration per step
2. Pass this configuration through ExecutionContext to agents
3. Implement tool filtering in each agent type

**Expected Timeline:** 2-3 weeks with focused implementation

---

## Quick Navigation

### For Decision Makers
👉 **Start with:** [`IMPLEMENTATION-ROADMAP.md`](IMPLEMENTATION-ROADMAP.md)
- Clear phases with effort estimates
- Quick wins you can implement immediately
- Timeline and success criteria

### For Technical Leads
👉 **Start with:** [`VERIFICATION-AND-CORRECTIONS.md`](VERIFICATION-AND-CORRECTIONS.md)
- What was investigated and verified
- Critical errors in the initial analysis
- Architectural insights and prerequisites

### For Implementers
👉 **Start with:** [`IMPLEMENTATION-ROADMAP.md`](IMPLEMENTATION-ROADMAP.md), then individual agent docs
- Detailed code examples for each agent type
- Phase-by-phase implementation guide
- Testing strategy

---

## Directory Contents

### Summary Documents (Read These First)
| Document | Purpose | Read If |
|----------|---------|---------|
| `00-START-HERE.md` | This file — navigation guide | You're here 👈 |
| `README.md` | Overview and comparison matrix | Quick understanding of all agents |
| `VERIFICATION-AND-CORRECTIONS.md` | Verification report with corrections | Technical validation needed |
| `IMPLEMENTATION-ROADMAP.md` | Detailed implementation guide | Ready to implement |

### Agent-Specific Analyses (Reference)
| Document | Agent Type | Focus |
|----------|-----------|-------|
| `claude-sdk-agent.md` | Claude SDK Agent | Anthropic API integration |
| `codex-server-agent.md` | Codex Server Agent | JSON-RPC protocol handling |
| `openhands-agent.md` | OpenHands Agent | SDK registration and tool lifecycle |
| `cli-agent.md` | CLI Agent | External subprocess tool management |
| `user-managed-agent.md` | User-Managed Agent | MCP server configuration |

---

## Key Findings Summary

### What Works Today
✅ Phase-based tool availability (builder vs. verifier)
✅ Underlying APIs support per-call tool specification
✅ Tool validation at runtime works for most agents
✅ Executor has step information available

### What Doesn't Work Today
❌ Step-level (beyond phase) tool configuration
❌ No data source for tool availability config in routines
❌ ExecutionContext doesn't carry step information
❌ Each agent filters tools differently (no unified approach)

### Critical Prerequisites
🔴 **Add `available_tools` field to `StepConfig`** (required before agent implementation)
🟡 Execute context extension (Phase 1)
🟢 Agent-specific filtering (Phase 2)

---

## Implementation Snapshot

### Phase 0: Prerequisites (Very Low Effort)
```python
# In src/orchestrator/config/models.py
class StepConfig(BaseModel):
    id: str
    description: str
    # ... other fields ...
    available_tools: list[str] | None = None  # ← ADD THIS
```

### Phase 1: Context Extension (Low Effort)
```python
# In src/orchestrator/agents/types.py
class ExecutionContext(BaseModel):
    # ... existing fields ...
    available_tools: list[str] | None = None  # ← ADD THIS

# In executor.py: read from step_config and pass to context
```

### Phase 2: Agent Filtering (Medium Effort Per Agent)
```python
# Each agent filters tools based on context.available_tools
# Example: Claude SDK
if "terminal" in (context.available_tools or []):
    tools_list.append(terminal_tool)
```

---

## Quick Wins (Implement First)

These are very low effort, high value changes:

1. **Codex Server Phase Filtering**
   - File: `codex_server_common.py`
   - Change: Add `is_verifier` parameter to exclude `grade` tool from builders
   - Effort: 5 minutes
   - Benefit: Builders no longer see unavailable grading tool

2. **User-Managed MCP Simplification**
   - File: `mcp/server.py`
   - Change: Register all tools, rely on runtime validation
   - Effort: 10 minutes
   - Benefit: MCP clients see same tools as REST clients

---

## Comparison: Agent Tool Control Capabilities

| Agent | Current | After Implementation | Difficulty |
|-------|---------|----------------------|------------|
| **Claude SDK** | Phase-based | Step-based | Medium |
| **Codex** | Phase-based | Step-based | Medium |
| **OpenHands** | Phase-based | Step-based | Medium |
| **CLI** | Phase-based | Phase-based (step hints) | Low |
| **User-Managed** | Phase-unaware | Phase & step aware | Medium |

---

## Architecture Diagram

```
┌─────────────────────────────────────────┐
│  Routine Definitions (YAML)             │
│  steps:                                 │
│    - available_tools: [...]             │
└──────────────────┬──────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────┐
│  StepConfig                             │
│  - available_tools: list[str] | None    │  ← NEW FIELD
└──────────────────┬──────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────┐
│  Executor                               │
│  - Reads step.available_tools           │
│  - Populates ExecutionContext           │  ← ENHANCED
└──────────────────┬──────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────┐
│  Agent (All Types)                      │
│  - Receives ExecutionContext            │
│  - Filters tools to available_tools     │  ← NEW LOGIC
│  - Only those tools accessible          │
└─────────────────────────────────────────┘
```

---

## Corrected Facts (From Verification)

The investigation identified and corrected several inaccuracies:

1. **Codex Server** does NOT filter tools by phase at registration — it registers all tools and filters post-hoc
2. **CLI Agent** already has phase-specific prompts — the analysis initially missed this
3. **OpenHands** has a two-tier registration system, not a single global flag
4. **StepConfig** doesn't yet have a `tools` field — this must be added first
5. **User-Managed MCP** should register all tools, not phase-based subset

See `VERIFICATION-AND-CORRECTIONS.md` for full details.

---

## Next Steps (For You)

### If You're a Decision Maker
1. Read `IMPLEMENTATION-ROADMAP.md` for timeline and effort estimates
2. Identify resources and prioritize implementation phases
3. Mark "Phase 0" as prerequisite before agent work begins

### If You're a Technical Lead
1. Read `VERIFICATION-AND-CORRECTIONS.md` for architectural validation
2. Review `IMPLEMENTATION-ROADMAP.md` for phasing and dependencies
3. Identify quick wins (Codex phase filtering, MCP all-tools registration)
4. Plan Phase 1 (context extension) as blocking work

### If You're an Implementer
1. Read `IMPLEMENTATION-ROADMAP.md` for detailed code examples
2. Reference agent-specific docs (`claude-sdk-agent.md`, etc.) as you implement
3. Use testing strategy in roadmap for validation
4. Follow the phasing: Phase 0 → Phase 1 → Phase 2a → Phase 2b → Phase 2c

---

## Documents at a Glance

### 📊 High-Level Overview
- **README.md** — Comparison matrix, architecture overview

### 🔍 Detailed Analysis
- **claude-sdk-agent.md** — Claude SDK implementation details (179 lines)
- **codex-server-agent.md** — Codex Server implementation details (280 lines)
- **openhands-agent.md** — OpenHands implementation details (300 lines)
- **cli-agent.md** — CLI agent implementation details (317 lines)
- **user-managed-agent.md** — User-managed agent and MCP details (436 lines)

### ✅ Verification & Planning
- **VERIFICATION-AND-CORRECTIONS.md** — Verification report (270 lines)
- **IMPLEMENTATION-ROADMAP.md** — Detailed implementation guide (568 lines)

### 📍 Navigation
- **00-START-HERE.md** — This file

**Total:** ~2,600 lines of documentation across 8 markdown files

---

## Key Contacts in Your Codebase

### Important Files to Know

**Schema and Models:**
- `src/orchestrator/config/models.py` — StepConfig (line 152)
- `src/orchestrator/agents/types.py` — ExecutionContext (line 52)

**Agent Implementations:**
- `src/orchestrator/agents/claude_sdk.py` — Claude SDK (709 lines)
- `src/orchestrator/agents/codex_server.py` — Codex (803 lines)
- `src/orchestrator/agents/openhands.py` — OpenHands (634 lines)
- `src/orchestrator/agents/cli.py` — CLI agent (634 lines)
- `src/orchestrator/agents/user_managed.py` — User-managed (simple)

**MCP Server:**
- `src/orchestrator/mcp/server.py` — MCP server configuration
- `src/orchestrator/mcp/tools.py` — Tool definitions

**Executor:**
- `src/orchestrator/agents/executor.py` — Where ExecutionContext is created (lines 654-661)

---

## Questions?

Each document is self-contained and can be read independently:
- **How does Codex handle tools?** → `codex-server-agent.md`
- **What API does Claude SDK use?** → `claude-sdk-agent.md`
- **What needs to change to implement this?** → `IMPLEMENTATION-ROADMAP.md`
- **Are the recommendations actually feasible?** → `VERIFICATION-AND-CORRECTIONS.md`

---

## Investigation Methodology

This investigation was conducted using:
1. **Five parallel Haiku agents** — Each investigating one agent type in detail
2. **One Opus agent** — Technical verification and error detection
3. **Source code analysis** — Actual implementation review, not assumptions
4. **Cross-validation** — Comparing claims against actual codebase

All references include specific file paths and line numbers for easy verification.

---

**Ready to implement?** → Go to [`IMPLEMENTATION-ROADMAP.md`](IMPLEMENTATION-ROADMAP.md)

**Need technical validation?** → Go to [`VERIFICATION-AND-CORRECTIONS.md`](VERIFICATION-AND-CORRECTIONS.md)

**Want details on your agent type?** → Find it in the agent-specific docs
