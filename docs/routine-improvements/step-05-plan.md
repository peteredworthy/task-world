# Step 5: Trim prompt dead weight (A7)

## Milestone
M2: Prompt & Context Efficiency

## Purpose
Remove identified dead-weight sections from the shared system prompt. Experiment D4 confirmed these sections are universally ignored by agents. Removing them reduces token usage without affecting agent behavior.

## Prerequisites / Dependencies
- None. M2 runs in parallel with M1 per clarification decision.

## Functional Contract

### Inputs
- Current system prompt template in `prompts.py`

### Outputs
- System prompt without the following sections:
  - "Avoiding Loops" section (~512 chars)
  - Other agent-behavioral instructions identified in D4 as dead weight
- All required sections remain: task context, requirements, callback instructions

### Errors
- None. This is a content removal, not a logic change.

## Files Modified
- `src/orchestrator/workflow/prompts.py` — remove identified dead-weight sections

## Verification Strategy
- **Unit test:** Generated system prompt does not contain "Avoiding Loops" or other removed section headers/content.
- **Unit test:** Generated system prompt still contains required sections (task description, requirements list, orchestrator integration).
- **Regression:** Existing prompt generation tests pass with updated expectations.
