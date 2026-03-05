# Step 8: Step context guidance (A14)

## Milestone
M2: Prompt & Context Efficiency

## Purpose
Add guidance to planner documentation about keeping `step_context` compact and builder-relevant. Step context is intentionally duplicated per task (each task needs it), so the fix is making the content shorter rather than deduplicating.

## Prerequisites / Dependencies
- None. This is documentation only.

## Functional Contract

### Inputs
- N/A (documentation change)

### Outputs
- Updated planner documentation with guidance on:
  - Keeping `step_context` concise
  - Focusing on builder-relevant information only
  - Avoiding duplication of information already in task descriptions
  - Examples of good vs. verbose step context

### Errors
- N/A

## Files Modified
- Documentation in `docs/` (planner guidance — new or updated file)

## Verification Strategy
- **Manual review:** Documentation is clear, actionable, and includes examples.
- No automated tests (documentation only).
