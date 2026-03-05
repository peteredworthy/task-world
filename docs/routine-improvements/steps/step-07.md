# Step 7: Compress clarifications on resolution (A6)

**Milestone:** M2 — Prompt & Context Efficiency
**Plan:** [step-07-plan.md](../step-07-plan.md)
**Architecture:** [architecture.md](../architecture.md) — A6
**Intent:** [intent.md](../intent.md) — Completion Criteria #10

## Tasks

### Task 7.1: Add clarification compression logic

After Q&A resolves, produce a compact "decisions" section (decision + rationale)
using template-based extraction (not LLM summarization). Archive raw Q&A
separately. Downstream prompts receive decisions only.

**Files:** `src/orchestrator/workflow/service.py` (or new clarification module)
**LOC estimate:** ~60
**Verify:** Unit tests — compress function produces correct decisions structure;
downstream prompt uses decisions not raw Q&A; archive retains full data.
Existing clarification flow tests pass.
