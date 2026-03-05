# Step 15: Failure mode analysis in dry run (A18)

## Milestone
M5: Planning Documentation

## Purpose
Update planner documentation to reflect that the dry-run stage should include failure mode analysis. Planners should identify likely failure modes per step and re-engineer the plan to minimize their likelihood. This practice is already partially present in existing routine YAML — the documentation should codify it.

## Prerequisites / Dependencies
- None. Documentation only, can run at any time.

## Functional Contract

### Inputs
- N/A (documentation change)

### Outputs
- Updated planner documentation covering:
  - What failure mode analysis is and why it matters
  - When to perform it (during dry-run stage)
  - How to identify failure modes per step
  - How to re-engineer the plan based on identified risks
  - Examples from existing routines

### Errors
- N/A

## Files Modified
- Documentation in `docs/` or routine templates (new or updated planner guidance file)

## Verification Strategy
- **Manual review:** Documentation is clear, actionable, and includes concrete examples.
- No automated tests (documentation only).
