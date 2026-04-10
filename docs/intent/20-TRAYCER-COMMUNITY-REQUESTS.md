# Traycer Community Requests: Implications for Orchestrator

Analysis of top Traycer community feedback requests and how they apply to our design.

---

## Top Requests by Vote Count

| Votes | Request | Status | Relevance to Us |
|-------|---------|--------|-----------------|
| 11 | Use Codex/Claude Code as the planning model | Open | **High** |
| 9 | Ability to use npx MCP servers | Open | **High** |
| 8 | Student pricing plans | Open | Low (business model) |
| 7 | Pricing restructure (artifact cooldown limits) | In Progress | **High** (validates BYOK) |
| 6 | BYOK (bring your own keys) | Open | **Already solved** |
| 4 | Collaboration on artifacts | In Progress | Medium (future) |
| 4 | End-to-end Epic Mode automation | Planned | **High** |
| 4 | Dedicated conversations per phase | Open | **High** |
| 4 | Support for Warp terminal | Open | Medium |
| 3 | Configurable YOLO execution stoppage | Open | **High** |
| 3 | Multiple chats in Epic mode | In Progress | Medium |

---

## High-Relevance Requests: Deep Analysis

### 1. BYOK — Bring Your Own Keys (6 votes)

**What users want:** Use their own API keys for artifact generation instead of Traycer's metered slots.

**Why they want it:** 
- Unlimited usage without cooldown
- Cost predictability (pay API provider directly)
- Use preferred models

**Our position:** ✅ **Already solved by architecture**

Orchestrator is local-first with user-provided API keys. This is foundational, not a feature request.

**Design implication:** Make this a headline differentiator in positioning.

---

### 2. Configurable Verification/YOLO Stoppage (3 votes)

**What users want:** Configure:
- Number of re-verification attempts before stopping
- When to do fresh verification vs. re-verification
- Exit criteria for automated loops

**User quote:** *"Can the configuration be such that we can configure to automatically attempt a fresh verification after every 2 reverifications and stop after 2 additional fresh verifications"*

**Our position:** ✅ **Designed for this**

Our `retry` configuration per task already supports:
```yaml
retry:
  max_attempts: 3
```

**Gap identified:** We don't have:
- Separate config for "re-verify" vs "fresh verify" cycles
- Configurable escalation (e.g., "after 2 re-verifies, do fresh")

**Design implication:** Extend retry config:

```yaml
retry:
  max_attempts: 3
  verification:
    re_verify_limit: 2        # After this many re-verifies...
    escalate_to_fresh: true   # ...do a fresh verification
    fresh_verify_limit: 2     # Then stop after this many fresh
```

**Add to:** Phase 2 (Workflow Engine) or Phase 9 (Advanced Workflows)

---

### 3. Dedicated Conversations per Phase (4 votes)

**What users want:** When an agent has questions during a phase, track that conversation separately from the main workflow conversation.

**User quote:** *"During development in each phase, the AI agent may have questions or need to validate specific items. It would be very helpful to have a conversation specific to those questions inside the phase otherwise it can be challenging to track in the larger conversation."*

**Our position:** ⚠️ **Partially addressed**

Our builder/verifier separation with fresh context handles some of this — each phase starts clean. But we don't have:
- A way to capture agent questions during execution
- A mechanism for mid-task human clarification
- Per-step conversation history

**Design implication:** Consider:
1. **Step-level notes/conversation log** — Capture agent questions and human responses per step
2. **Pause-for-clarification state** — Agent can signal "I need input" without failing

```yaml
task:
  allow_clarification: true  # Agent can pause and ask questions
  clarification_timeout: 30m # Auto-fail if no response
```

**Add to:** Phase 9 as Slice 9.7 or future phase

---

### 4. End-to-End Epic Mode Automation (4 votes)

**What users want:** Full automation from idea → specs → tickets → execution without manual intervention.

**Our position:** ✅ **This is our `idea_to_plan` routine**

The Phase 9 planning routine template demonstrates exactly this flow. The difference is we have explicit human gates where needed, while still supporting full automation for the automated portions.

**Design implication:** 
- Ensure YOLO/autonomous mode is a first-class toggle
- Human gates should be explicitly opt-in, not default
- Make it easy to run end-to-end without human intervention when desired

---

### 5. Use Better Models for Planning (11 votes — highest!)

**What users want:** Use Claude Code or Codex capabilities for the planning/orchestration layer, not just for code execution.

**User quote:** *"Imagine traycer powered by claude code or codex, so traycer can use more native model capabilities"*

**Our position:** ✅ **Already designed for this**

Our `model_overrides` per task lets users specify any model:
```yaml
task:
  model_overrides:
    "claude-sonnet-4-20250514":
      task_context: "..."
    "o3":
      task_context: "..."
```

But we could go further — let users configure the **verifier model** separately from the **builder model**.

**Design implication:** Extend agent config:

```yaml
agent_config:
  builder:
    model: "claude-sonnet-4-20250514"
  verifier:
    model: "o3"  # Use reasoning model for verification
```

**Add to:** Phase 5 (Agent Integration) — already have model_overrides, just need to surface builder/verifier split

---

### 6. MCP Server Support (9 votes)

**What users want:** Connect to MCP servers (GitHub, Notion, Linear, Sentry, custom npx servers) for external context.

**Our position:** ✅ **Planned in Phase 5**

Slice 5.6 defines MCP server for tool calls. But we should also support **consuming** MCP servers, not just exposing one.

**Gap identified:** We have MCP as an output (exposing orchestrator tools) but not as an input (consuming external context).

**Design implication:** Add bidirectional MCP:

```yaml
# In routine or project config
mcp_connections:
  - name: "github"
    url: "npx @modelcontextprotocol/server-github"
  - name: "linear"
    url: "https://mcp.linear.app"
```

Tasks can then reference MCP tools:
```yaml
task:
  mcp_tools:
    - github.list_issues
    - linear.get_ticket
```

**Add to:** Phase 5 as Slice 5.7: MCP Client Integration

---

### 7. Git Worktree Issues (bug report, 0 votes but significant)

**What users want:** Reliable worktree handling during re-verification.

**User quote:** *"On the first iteration Traycer seems to use the git worktree folder because I specifically tell it to. When I click re-review it does not use it and says that changes were not implemented."*

**Our position:** ✅ **First-class feature**

Phase 7 (Git Integration) makes worktrees a core concept, not an afterthought. Each run gets its own worktree, and the orchestrator tracks which worktree belongs to which run.

**Design implication:** This validates our worktree-per-run architecture. Make sure:
- Worktree path is stored in run state
- All operations (build, verify, re-verify) use the same worktree
- Worktree cleanup is explicit, not implicit

---

### 8. Pricing/Throttling Pain (7 votes)

**What users want:** No artificial limits that interrupt workflow.

**User quote:** *"artifact cooldown limits slow down the development process"*

**Our position:** ✅ **Non-issue for us**

Local-first means no metering. Users pay their LLM provider directly. No slots, no cooldowns, no throttling.

**Design implication:** This is a competitive advantage to emphasize. "No artificial limits — run as many workflows as your API budget allows."

---

## Summary: Feature Backlog from Traycer Community

### Already Solved by Our Architecture
| Feature | How We Solve It |
|---------|-----------------|
| BYOK | Local-first with user API keys |
| No throttling | No metering layer |
| Worktree reliability | First-class worktree-per-run |
| Model choice | model_overrides per task |

### Should Add to Current Design
| Feature | Where to Add | Priority |
|---------|--------------|----------|
| Configurable verify/re-verify cycles | Phase 2 or 9 | High |
| Separate builder/verifier models | Phase 5 | Medium |
| MCP client (consume external servers) | Phase 5, Slice 5.7 | High |
| Step-level conversation/notes | Phase 9 or future | Medium |
| Pause-for-clarification state | Phase 9 | Medium |

### Out of Scope for MVP
| Feature | Why |
|---------|-----|
| Student pricing | Business model, not product |
| Warp support | CLI-agnostic already |
| Multiple simultaneous chats | Complexity; single-run focus first |
| UI wireframe generation | Out of scope |

---

## Recommended Schema Additions

Based on community feedback, consider these schema extensions:

### 1. Enhanced Retry Configuration

```yaml
retry:
  max_attempts: 3
  verification_strategy:
    re_verify_limit: 2
    fresh_after_re_verify: true
    fresh_verify_limit: 2
    
  # Existing
  backoff:
    type: exponential
    initial_delay: 5s
    max_delay: 60s
```

### 2. Builder/Verifier Model Split

```yaml
task:
  builder:
    model: "claude-sonnet-4-20250514"
    temperature: 0.7
  verifier:
    model: "o3"  # Reasoning model for verification
    temperature: 0.2
```

### 3. MCP Client Connections

```yaml
# Project-level config
mcp_clients:
  - id: "github"
    command: "npx @modelcontextprotocol/server-github"
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
  - id: "linear"
    url: "https://mcp.linear.app/sse"

# Task-level usage
task:
  context_from_mcp:
    - server: "github"
      tool: "list_issues"
      args:
        repo: "myorg/myrepo"
        state: "open"
```

### 4. Clarification Support

```yaml
task:
  clarification:
    enabled: true
    timeout: 30m
    max_questions: 3
```

When builder hits an ambiguity, it can:
1. Pause execution
2. Surface the question via API/UI
3. Wait for human response
4. Resume with clarification in context

---

## Competitive Positioning Update

Based on this analysis, our messaging should emphasize:

**Problems Traycer users have that we solve:**

1. ❌ "Artifact cooldown limits slow down development" → ✅ No limits, your API budget
2. ❌ "Can't use my own API keys" → ✅ BYOK is default
3. ❌ "Worktree handling is buggy" → ✅ First-class worktree-per-run
4. ❌ "Can't configure verification cycles" → ✅ Full retry/verification config
5. ❌ "Planning runs on their cloud" → ✅ Everything runs locally

**Tagline options:**
- "The orchestrator that respects your workflow — and your wallet"
- "No slots. No cooldowns. No cloud dependency. Just workflows that work."
