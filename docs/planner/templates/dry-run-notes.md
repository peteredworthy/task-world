# Dry Run Notes: {{feature}}

## Summary

<!-- Overall assessment of plan executability and key blockers -->
<!-- Identify any REQUIRED severity gaps that must be resolved before proceeding -->

## Task-by-Task Simulation

### Step X, Task Y:

- **Simulation:** What would be done to execute this task
- **Assumptions:** Unstated assumptions made in the task definition
- **Gaps:** Identified gaps, unclear requirements, missing context

---

## Gap Resolution Table

| Gap Description | Severity | Affected Step/Task | Functionality Area | Resolution |
|-----------------|----------|-------------------|-------------------|-----------|
| Example: Missing error handling for network timeouts | REQUIRED | S-02 T-01 | API communication | Updated task context with retry logic and timeout values |
| Example: Unclear validation rules for input format | EXPECTED | S-03 T-02 | Input validation | Clarified in design-questions.md and added to requirements |
| Example: Performance optimization for bulk operations | OPTIONAL | S-05 T-03 | Performance | Deferred; documented in plan-changes.md for post-launch |

**Severity Definitions:**
- **REQUIRED**: Critical functionality that must be resolved; blocks execution if unresolved
- **EXPECTED**: Important functionality that should be resolved; consider blocking if multiple unresolved
- **OPTIONAL**: Nice-to-have functionality; can be deferred with justification

**Resolution Column Guidance:**
- Describe the specific action taken to address the gap
- Reference the artifact updated: "Updated step-XX-plan.md: Added requirement R3"
- If unresolved, leave blank and justify in comments
- **For re-runs**: If marked resolved but gap found again, re-add with more specificity about what remains missing

---

## Recommendations

<!-- Additional suggestions for improving plan specificity, clarity, or coverage -->
<!-- Note any edge cases discovered that should be documented -->
