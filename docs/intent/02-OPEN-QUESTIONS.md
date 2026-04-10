# Open Questions and Concerns

This document captures decisions made and new questions that arose during design review.

---

## ALL QUESTIONS CLOSED

All design questions have been resolved. See decisions below.

---

## CLOSED QUESTIONS (Decisions Made)

### NQ-1: Git Enforcement Level ✅

**Decision:** **Warn** - Allow uncommitted routines but warn user and record "dirty" state.

---

### NQ-2: Auto-Verify Sandboxing ✅

**Decision:** **Match agent** - Sandbox auto-verify when using OpenHands; run locally when using CLI.

---

### NQ-3: CLI Nudge Parameters ✅

**Decision:** Use output timeout only (prompt pattern matching too tool-dependent).

- Detect stuck: **60s no output**
- Nudge message: "Please continue with the task or call the orchestrator tools to submit your work."
- Max nudges: **3**
- Interval: **30s** between nudges
- Kill after 3rd nudge ignored

---

### NQ-4: Worktree Cleanup ✅

**Decision:** Simplified - orchestrator only handles worktree cleanup.

- **Completion actions in orchestrator:** `keep_worktree` or `delete_worktree`
- **Git operations (MR, merge, etc.):** Handled by the routine itself via agent instructions
- The routine contains instructions for the agent to create MRs, merge, etc.

---

### NQ-5: Model Override Structure ✅

**Decision:** Approved as proposed.

```yaml
task:
  task_context: "Default instructions..."
  model_overrides:
    "claude-sonnet-4-20250514":
      task_context: "Claude-optimized instructions..."
    "gpt-4-turbo":
      task_context: "GPT-4 optimized instructions..."
```

---

### 1.1 Agent Execution Model ✅

**Decision:** **Fresh context each phase** - Enables simpler LLMs, clear separation, predictable costs.

---

### 1.2 Agent Selection ✅

**Decision:** **No auto-selection. User choice.**

- Auto-detect available tools (OpenHands Local via SDK import, OpenHands Docker via daemon check, Codex CLI, Claude CLI)
- Present available options to user
- User explicitly chooses execution method per run

---

### 1.3 Worktree Strategy ✅

**Decision:** **Configurable, defaulting to worktree per run**

- Default: worktree per run
- Option to run without worktree
- Configurable at project/run level

---

### 1.4 State Synchronization ✅

**Decision:** **Pessimistic locking** - Simple lock with timeout. Not enough contention for optimistic.

---

### 1.5 Artifact Storage ✅

**Decision:** **Separate artifact directory with option to store in repo**

---

### 2.1 OpenHands Version ✅

**Decision:** **Latest stable with mitigations** - Abstract behind interface, pin version, adapter layer.

---

### 2.2 CLI Agent Detection ✅

**Decision:** **MCP + timeout + nudge mechanism**

- Primary: MCP tool calls
- Fallback: timeout
- Interactive mode: monitor for stuck prompt, inject nudges, kill after count exceeded

---

### 2.3 Prompt Injection ✅

**Decision:** **Trust user with mitigations**

- Schema/UI restrict where possible
- Trust user for free-text blocks
- OpenHands sandbox is best protection

---

### 2.4 Model Support ✅

**Decision:** **Multi-model via configuration alternatives**

- Model-specific overrides in templates
- Single default always required
- See NQ-5 for structure

---

### 3.1 Manual Agent UX ✅

**Decision:** **Implement mitigations**

- "I've started the agent" button
- "Cancel waiting" option  
- Clear status with elapsed time
- Auto-timeout with notification
- Applies to: CLI, Cursor, any MCP-connected tool
- Option to start CLI tools in subprocess

---

### 3.2 Real-time Updates ✅

**Decision:** **Add throttle and batching** - Proactive implementation, unlikely to be problem.

---

### 3.3 Dashboard View ✅

**Decision:** **Active + recent, configurable recency**

- Show active + recently finished
- Recency options: 1hr, 4hrs, 24hrs, 1 week
- Filter/group by project
- Support multi-project view without full context switch

---

### 4.1 Database Migrations ✅

**Decision:** **Alembic, deferred** - Implement when schema stabilizes. Early work local-only.

---

### 4.2 State Recovery ✅

**Decision:** **Event sourcing** - Reconstruct from history.jsonl on startup.

---

### 4.3 Concurrent Runs ✅

**Decision:** **Worktree isolation with configurable completion**

- Worktree per run for isolation
- Run defines completion: create MR, merge back, clean conflicts, etc.

---

### 5.1 Routine Versioning ✅

**Decision:** **Git-based versioning**

- Routines must be in git repo
- Must be committed before use
- Git SHA as version snapshot
- Durable for historical runs

---

### 5.2 External Routine Security ✅

**Decision:** **Allowlist of sources** - Explicit trust only.

---

### 5.3 Routine Discovery ✅

**Decision:** **Local + git import** - Defer marketplace.

---

### 6.1 Command Execution ✅

**Decision:** **OpenHands sandbox when available** - Run auto-verify through OpenHands for protection.

---

### 6.2 Git Credentials ✅

**Decision:** **System credentials** - Rely on system git credential helper.

---

### 7.1 Observability ✅

**Decision:** **Cheap metrics focused on key data**

- Time per task/step/phase
- Token counts (read/write/cache)
- Invocation counts (from task history)

---

### 7.2 Cost Tracking ✅

**Decision:** **Token estimate with real counts**

- Display real token counts
- Calculate estimate
- Hover note: "Estimate only. Hidden costs may exist."

---

### 8.1 Build Approach ✅

**Decision:** **Incremental with full testing, not MVP**

Build order:
1. Orchestration and routing
2. Step parsing and setup
3. MCP/HTTP methods
4. Agent integration
5. UI

All features complete before external availability.

---

### 8.2 Testing Strategy ✅

**Decision:** **Real credentials for integration tests**

- Unit: Mock interface
- Integration: Real API keys, authenticated CLIs
- E2E: Full workflow

---

### 9.1 Config Migration ✅

**Decision:** **Clean break** - Few routines to migrate. LLM can assist if needed.

---

### 9.2 YAML Schema ✅

**Decision:** **Simplify** - Remove ref/use inheritance, flatten catalogs, explicit IDs.

---

## Summary

All questions have been resolved. The system is ready for implementation.

Key decisions:
- **Routines**: Git-versioned, warn on uncommitted
- **Agent selection**: User chooses, no auto-select
- **Context**: Fresh per phase
- **Locking**: Pessimistic
- **Schema**: Simplified (no ref/use)
- **Worktree**: Default on, orchestrator handles cleanup only
- **Git operations**: Agent executes via routine instructions
- **Auto-verify sandbox**: Match agent (OpenHands sandboxed, CLI local)
- **CLI nudge**: Output timeout only (60s), 3 nudges max
