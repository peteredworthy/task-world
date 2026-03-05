# Step 6: Migrate agent-specific instructions (A8)

**Milestone:** M2 — Prompt & Context Efficiency
**Plan:** [step-06-plan.md](../step-06-plan.md)
**Architecture:** [architecture.md](../architecture.md) §4 (Prompt Builder, A8)
**Intent:** [intent.md](../intent.md) — Completion Criteria #5

## Tasks

### Task 6.1: Move agent-specific instructions from shared prompt to agent runners

Remove agent-specific behavioral instructions from `prompts.py`. Add them to
each agent's `build_prompt()` method:
- CLI: git workflow, commit conventions
- OpenHands: file re-reading avoidance, Docker context
- Codex: sandbox constraints, shorter responses
- Claude SDK: tool usage patterns, sub-agent guidance

**Files:** `src/orchestrator/workflow/prompts.py`, `src/orchestrator/agents/cli.py`, `src/orchestrator/agents/openhands.py`, `src/orchestrator/agents/codex_server.py`, `src/orchestrator/agents/claude_sdk.py`
**LOC estimate:** ~120 (moves, net change small)
**Verify:** Unit tests — each agent's prompt includes its specific instructions;
shared prompt has no agent-specific content. Existing agent prompt tests pass.
