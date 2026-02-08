# Planning Artifacts Specification

All planning artifacts are created in `docs/{feature}/` where `{feature}` is the feature name provided when creating the run.

## Directory Structure

```
docs/{feature}/
├── intent.md                    # Goal, scope, completion definition
├── plan.md                      # Milestones, implementation order
├── design-questions.md          # Open questions with resolution tracking
├── architecture.md              # Tech choices, interactions, testing
├── CONFLICTS.md                 # Conflicts and resolutions (if any)
├── dry-run-notes.md             # Simulation results and gaps
├── verification-report.md       # Cross-artifact consistency checks
├── plan-summary.md              # Final summary proving intent satisfaction
├── step-01-plan.md              # Detailed plan for step 1
├── step-02-plan.md              # Detailed plan for step 2
├── ...
└── steps/
    ├── step-01.md               # Atomic tasks for step 1
    ├── step-02.md               # Atomic tasks for step 2
    └── ...
```

---

## Core Artifacts

### intent.md

Captures the original request and defines what "complete" means.

```markdown
# Intent: {Feature Name}

## Original Request

{The idea or request that initiated this planning process}

## Goal

{What we're trying to accomplish - the desired end state}

## Scope

### In Scope
- {What's included}

### Out of Scope
- {What's explicitly excluded}

## Definition of Complete

{Specific, verifiable criteria for when this feature is done}

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3
```

---

### plan.md

The implementation plan with milestones and ordering.

```markdown
# Plan: {Feature Name}

## Overview

{Brief summary of the approach}

## Milestones

### Milestone 1: {Name}
- {Deliverable 1}
- {Deliverable 2}

### Milestone 2: {Name}
- {Deliverable 3}
- {Deliverable 4}

## Implementation Order

1. **Step 1:** {Brief description}
   - Prerequisites: None
   - Deliverables: {What's produced}

2. **Step 2:** {Brief description}
   - Prerequisites: Step 1
   - Deliverables: {What's produced}

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| {Decision 1} | {Choice made} | {Why} |

## References

- {Link to relevant documentation}
- {Link to example code}
```

---

### design-questions.md

Tracks unknowns and their resolution.

```markdown
# Design Questions: {Feature Name}

## Open Questions

### Q1: {Question}
- **Context:** {Why this matters}
- **Options:**
  1. {Option A} - {Pro/con}
  2. {Option B} - {Pro/con}
- **Impact:** {What depends on this decision}
- **Priority:** {High/Medium/Low}
- **Status:** Open

## Resolved Questions

### Q0: {Question}
- **Resolution:** {What was decided}
- **Rationale:** {Why}
- **Resolved by:** {Human/Agent} on {date}
```

---

### architecture.md

Technical architecture and design decisions.

```markdown
# Architecture: {Feature Name}

## Current State

{Brief description of existing architecture relevant to this feature}

## Proposed Changes

### New Components

{Diagrams or descriptions of new components}

### Modified Components

{What existing components change and how}

### Interactions

{How components communicate}

## Technology Choices

| Area | Choice | Rationale |
|------|--------|-----------|
| {Area} | {Technology} | {Why} |

## Testing Strategy

- **Unit Tests:** {Approach}
- **Integration Tests:** {Approach}
- **E2E Tests:** {Approach}

## Security Considerations

{Security-relevant aspects of the design}

## Performance Considerations

{Performance-relevant aspects of the design}
```

---

### CONFLICTS.md

Documents conflicts that need human resolution. Only created when conflicts exist.

```markdown
# Conflicts: {Feature Name}

## Active Conflicts

### C1: {Conflict Title}
- **Description:** {What the conflict is}
- **Artifacts Affected:** {Which documents are inconsistent}
- **Options:**
  1. {Resolution option A}
  2. {Resolution option B}
- **Recommendation:** {Agent's recommendation, if any}
- **Status:** Awaiting human decision

## Resolved Conflicts

### C0: {Conflict Title}
- **Resolution:** {What was decided}
- **Resolved by:** {Who} on {date}
```

---

## Step Planning Artifacts

### step-XX-plan.md

Detailed plan for a single step.

```markdown
# Step {XX} Plan: {Step Title}

## Purpose

{What this step accomplishes and why it matters}

## Prerequisites

- Step {YY} complete: {specific deliverable needed}
- {Other prerequisites}

## Functional Contract

### Inputs
- {Input 1}: {Description}
- {Input 2}: {Description}

### Outputs
- {Output 1}: {Description}
- {Output 2}: {Description}

### Errors
- {Error condition 1}: {How it's handled}
- {Error condition 2}: {How it's handled}

## Tasks

1. {Task 1 description}
2. {Task 2 description}
3. {Task 3 description}

## Verification

### Auto-Verify
- [ ] {Automated check 1}
- [ ] {Automated check 2}

### Manual Verify
- [ ] {What verifier should check}

## Context & References

- {Relevant file or documentation}
- {Example to follow}
```

---

### steps/step-XX.md

Atomic tasks ready for agent execution.

```markdown
# Step {XX}: {Step Title}

## Context

{Brief context from step plan}

## Tasks

### Task 1: {Task Title}

**Do:**
{Specific, actionable instructions}

**Expected Outcome:**
{What should exist when done}

**Verify:**
{How to check it worked}

**References:**
- {Relevant file}
- {Documentation link}

---

### Task 2: {Task Title}

**Do:**
{Specific, actionable instructions}

**Expected Outcome:**
{What should exist when done}

**Verify:**
{How to check it worked}

**References:**
- {Relevant file}
```

---

## Verification Artifacts

### dry-run-notes.md

Results of simulating task execution.

```markdown
# Dry Run Notes: {Feature Name}

## Summary

{Overall assessment - are the tasks executable?}

## Task-by-Task Simulation

### Step 1, Task 1: {Title}
- **Simulation:** {What would happen}
- **Assumptions:** {What we're assuming}
- **Gaps:** {Issues identified, or "None"}

### Step 1, Task 2: {Title}
- **Simulation:** {What would happen}
- **Assumptions:** {What we're assuming}
- **Gaps:** {Issues identified, or "None"}

## Identified Gaps

| Gap | Affected Task | Resolution |
|-----|---------------|------------|
| {Gap description} | {Task reference} | {How to fix} |

## Recommendations

{Any suggested changes to the plan}
```

---

### verification-report.md

Cross-artifact consistency check results.

```markdown
# Verification Report: {Feature Name}

## Checks Performed

### 1. Intent Coverage
- **Check:** All intent items have corresponding plan steps
- **Result:** Pass/Fail
- **Details:** {Specifics}

### 2. Plan-Step Alignment
- **Check:** All plan steps have step files
- **Result:** Pass/Fail
- **Details:** {Specifics}

### 3. Dry Run Gaps Addressed
- **Check:** All gaps from dry run are resolved
- **Result:** Pass/Fail
- **Details:** {Specifics}

### 4. Architecture Consistency
- **Check:** Implementation matches architecture
- **Result:** Pass/Fail
- **Details:** {Specifics}

### 5. No Open Conflicts
- **Check:** CONFLICTS.md has no active conflicts
- **Result:** Pass/Fail
- **Details:** {Specifics}

## Summary

{Overall assessment - ready for execution or not}
```

---

### plan-summary.md

Final summary document.

```markdown
# Plan Summary: {Feature Name}

## Intent Satisfaction

{How this plan addresses the original intent}

## Step Files

| Step | Title | Tasks |
|------|-------|-------|
| 01 | {Title} | {Count} |
| 02 | {Title} | {Count} |

## Key Decisions

{Summary of major decisions made}

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| {Risk} | {How it's addressed} |

## Notes & Caveats

{Anything the executor should be aware of}

## Ready for Execution

- [x] All artifacts consistent
- [x] Human approval received
- [x] Step files complete
```
