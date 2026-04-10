# Step 7: Compress clarifications on resolution (A6)

## Milestone
M2: Prompt & Context Efficiency

## Purpose
After each Q&A clarification round resolves, summarize resolved questions into a compact "decisions" section. Downstream tasks receive only the decisions, not the full Q&A history. This reduces prompt size while preserving the information agents need.

## Prerequisites / Dependencies
- None directly. Independent of Steps 5-6, though all are in M2.

## Functional Contract

### Inputs
- Resolved clarification Q&A data (question, options, chosen answer, rationale)

### Outputs
- **Decisions section:** Compact format containing decision + rationale for each resolved question
- **Archive:** Raw Q&A preserved separately for reference
- **Downstream prompts:** Contain only the decisions section, not raw Q&A

### Errors
- None expected. Compression is template-based (not LLM-based), so it's deterministic.

### Design Decision
Use template-based extraction (decision + rationale), not LLM summarization. This avoids summarization quality issues and keeps the operation deterministic.

## Files Modified
- `src/orchestrator/workflow/service.py` — add clarification compression logic (or new module)

## Verification Strategy
- **Unit test:** Compress function takes Q&A input and produces decisions section with correct structure.
- **Unit test:** Downstream prompt assembly uses decisions section, not raw Q&A.
- **Unit test:** Archive retains full Q&A data.
- **Regression:** Existing clarification flow tests pass.
