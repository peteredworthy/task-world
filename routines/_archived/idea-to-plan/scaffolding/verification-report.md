# Verification Report: {{feature}}

## Completeness Check

### Intent Coverage

<!-- Does the plan fully address the original intent? -->

- [ ] All goals from intent are covered by step files
- [ ] All in-scope items have corresponding steps
- [ ] Definition of complete items are addressed

**Status:** ✓ Pass | ✗ Fail

### Step File Alignment

<!-- Do all step files align with the plan? -->

- [ ] All plan steps have corresponding step files
- [ ] Step files are atomic and verifiable
- [ ] Step files maintain system runability

**Status:** ✓ Pass | ✗ Fail

## Consistency Check

### Artifact Consistency

<!-- Are all artifacts internally consistent? -->

- [ ] Intent, plan, and architecture are aligned
- [ ] Design decisions are justified in architecture
- [ ] No contradictions between documents

**Status:** ✓ Pass | ✗ Fail

### Dry Run Gap Resolution

<!-- BLOCKING: Every gap from dry-run-notes.md must be resolved IN the step files
     before this report can pass. "Documented" is not "resolved" — the fix must be
     applied to the step file text and/or routine YAML auto_verify commands.

     For each gap, confirm the fix is applied (not just proposed). -->

| Gap | Severity | Resolution in dry-run-notes | Applied to step files? | Applied to routine YAML? |
|-----|----------|----------------------------|----------------------|------------------------|
| <!-- Gap 1 --> | <!-- Critical/Significant/Moderate --> | <!-- proposed fix --> | <!-- ✓ step-XX Task Y updated / ✗ NOT APPLIED --> | <!-- ✓ auto_verify added / N/A --> |

- [ ] All critical gaps are applied to step files (not just documented in dry-run-notes)
- [ ] All significant gaps are applied to step files
- [ ] Moderate gaps are either applied or explicitly deferred with justification
- [ ] Persistence mapping audit has no MISSING cells

**GATE: If any critical or significant gap has "NOT APPLIED" status, this section FAILS
and the report status must be ✗ Needs Work. Do not proceed to execution.**

**Status:** ✓ Pass | ✗ Fail

### Persistence Mapping Audit

<!-- Copy the table from dry-run-notes.md. Any MISSING cell = Fail. -->

- [ ] Every new state model field has a corresponding DB column (if persistent)
- [ ] Every new state model field has repo write mapping
- [ ] Every new state model field has repo read mapping
- [ ] Dict-to-model conversion risks are addressed in step file instructions

**Status:** ✓ Pass | ✗ Fail | ○ N/A (no new state fields)

## Executability Check

### Task Executability

<!-- Can the step files be executed as-is by an agent? -->

- [ ] Each step has clear inputs and outputs
- [ ] Prerequisites are clearly documented
- [ ] Context references are complete

**Status:** ✓ Pass | ✗ Fail

### Verification Quality

<!-- Are auto_verify commands sufficient to catch implementation gaps? -->

- [ ] Each task has auto_verify commands that test behavior (not just existence)
- [ ] Integration test tasks have auto_verify that checks assertion coverage, not just "tests pass"
- [ ] For tasks that add persistence, auto_verify includes a write-then-read check OR the step file instructions explicitly require the test to do so

**How to assess integration test quality:**
An auto_verify of `pytest test_foo.py -v` only proves the tests run. It does NOT prove
the tests assert the right things. For integration test tasks, the step file must specify
what the tests must assert (e.g., "test must make N expansion calls then assert 429"),
and the auto_verify should run those specific tests. The verifier rubric should check
that assertion targets from the step file are present in the test code.

**Status:** ✓ Pass | ✗ Fail

## Overall Assessment

### Summary

<!-- Overall assessment of plan quality and readiness -->

### Recommendations

<!-- Any recommendations for improvement or execution -->

-

### Readiness for Execution

- [ ] Plan is complete and consistent
- [ ] All artifacts are in place
- [ ] All dry-run gaps applied to step files (no "NOT APPLIED" items)
- [ ] Persistence mapping audit clean (no MISSING cells)
- [ ] Step files are ready for agent execution

**Overall Status:** ✓ Ready | ✗ Needs Work
