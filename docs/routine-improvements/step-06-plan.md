# Step 6: Migrate agent-specific instructions (A8)

## Milestone
M2: Prompt & Context Efficiency

## Purpose
Move agent-behavioral instructions from the shared prompt template to individual agent implementations. Each agent type has unique behavioral needs (git workflow for CLI, Docker awareness for OpenHands, etc.) that don't belong in the shared prompt sent to all agents.

## Prerequisites / Dependencies
- Step 5 (prompt trim) should be done first or coordinated, since both modify `prompts.py`. No hard dependency, but reduces merge conflicts.

## Functional Contract

### Inputs
- Shared prompt template containing agent-specific sections
- Each agent's `build_prompt()` method

### Outputs
- Shared prompt no longer contains agent-specific behavioral instructions
- Each agent's prompt includes its relevant instructions:
  - **CLI agent:** git workflow instructions, commit conventions
  - **OpenHands agent:** file re-reading avoidance, Docker context awareness
  - **Codex agent:** sandbox constraints, shorter response preferences
  - **Claude SDK agent:** tool usage patterns, sub-agent guidance

### Errors
- None. This is a content migration, not a logic change.

## Files Modified
- `src/orchestrator/workflow/prompts.py` — remove agent-specific sections
- `src/orchestrator/agents/cli.py` — add CLI-specific instructions to `build_prompt()`
- `src/orchestrator/agents/openhands.py` — add OpenHands-specific instructions
- `src/orchestrator/agents/codex_server.py` — add Codex-specific instructions
- `src/orchestrator/agents/claude_sdk.py` — add Claude SDK-specific instructions

## Verification Strategy
- **Unit test:** Each agent's generated prompt includes its specific instructions (check for key phrases).
- **Unit test:** Shared prompt does not contain agent-specific content (check absence of agent-specific phrases).
- **Regression:** Existing agent prompt tests pass with updated expectations.
