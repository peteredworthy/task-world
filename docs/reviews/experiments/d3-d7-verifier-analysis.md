# D3 + D7: Rubric Split Analysis & Verifier Consistency

**Run:** `8bf41c40-9db2-49a6-b188-0145631ce134` (routine: mcp-ops-c step-level tool control)
**Date:** 2026-03-03
**Data source:** `orchestrator.db` — 33 attempts across 28 tasks, 32 with grade snapshots

---

## D7: Verifier Consistency Across 8 Evaluations

Task `946657c8` ("Create Integration Tests for Step-Level Tool Control") was graded
8 times by the LLM verifier (codex_server agent). Both requirements are `critical`
priority, meaning grade A is required to pass.

### Grade Table

| Attempt | Agent Model       | Duration | R1 (Integration Coverage) | R2 (No Regressions) | Outcome          |
|---------|-------------------|----------|---------------------------|----------------------|------------------|
| 1       | (default)         | 3m       | B                         | F                    | revision_needed  |
| 2       | (default)         | 9m       | D                         | D                    | failed           |
| 3       | (default)         | 7m       | C                         | F                    | failed           |
| 4       | (default)         | 7m       | B                         | F                    | failed           |
| 5       | (default)         | 31m      | D                         | C                    | failed           |
| 6       | gpt-5.3-codex     | 23m      | **A**                     | B                    | failed           |
| 7       | gpt-5.3-codex     | 23m      | **A**                     | C                    | failed           |
| 8       | gpt-5.1-codex-mini| 24m      | **A**                     | C                    | failed           |

### R1 (Integration Test Coverage) — High Variance

R1 grades swing dramatically: B, D, B, D across early attempts, then stabilize at A
for attempts 6-8. The verifier's assessment of the *same conceptual concern* (whether
tests exercise integration-level paths vs. model-level parsing) led to grades ranging
from D to A.

**Key inconsistency:** Attempts 2 and 5 both received D for essentially the same
observation ("tests only instantiate StepConfig directly"). Attempt 4 received B for
acknowledging the tests "cover the three requested areas at a meaningful level" but
calling multi-step cases "weaker." Attempts 6-8 received A for coverage that the
verifier found satisfactory.

The underlying code was being rewritten between attempts (this is expected), but the
verifier's threshold for what constitutes "integration-level" vs. "model-level" testing
was not stable. The same tests that got D in attempt 5 ("only instantiate StepConfig
directly") were structurally similar to what got B in attempt 4.

**Variance:** R1 grades span 4 letter grades (A through D) across 8 evaluations.

### R2 (No Regressions) — Consistently Failing, But For External Reasons

R2 never passed. The verifier consistently found that the full test suite did not run
cleanly. However, the *reason* varied:

- **Attempts 1, 3, 4:** Actual test failures detected in the worktree
- **Attempts 5, 7, 8:** Environment issues (`system-configuration` crate panic, event-loop
  shutdown) prevented verification completion
- **Attempt 6:** 99% of tests passed but the run "did not exit cleanly due to
  teardown/event-loop warnings"

The verifier correctly identified R2 as failing in all cases, but the grades ranged
from F (clear failures) to B (almost-passing) to C (environment-blocked). This is
actually *appropriate* grade variance — the verifier distinguished between "tests
actively fail" (F) and "can't confirm they pass due to environment" (C/B).

### R2 Grade Trajectory

| Attempt | R2 Grade | Verifier's Characterization                              |
|---------|----------|----------------------------------------------------------|
| 1       | F        | Full suite showed many failures/errors                    |
| 2       | D        | Broader pytest run did not complete green                 |
| 3       | F        | `.pytest_cache/v/cache/lastfailed` contains many failures |
| 4       | F        | Repository-wide run produced many failures and errors     |
| 5       | C        | Targeted files pass; broader run hit event-loop shutdown  |
| 6       | B        | 1235 tests passing; full suite 99% but unclean exit       |
| 7       | C        | `system-configuration` panic prevented any test execution |
| 8       | C        | `system-configuration` panic prevented any test execution |

### Consistency Assessment

**R1 consistency: POOR.** The verifier applied different standards to structurally
similar test code across attempts. The jump from D (attempt 5) to A (attempt 6) was
the largest, and correlates with a model change (default -> gpt-5.3-codex), suggesting
model capability differences compound with rubric interpretation variance.

**R2 consistency: FAIR.** The verifier reliably identified R2 as below threshold in
all 8 attempts. Grade variation (F/D/C/B) tracked meaningful differences in the
severity of the failure. However, attempts 7 and 8 got C for an environment issue
entirely outside the builder's control.

### Auto-Verify vs. LLM Verifier Disagreement

A critical finding: **auto-verify reported PASS on all 8 attempts** while the LLM
verifier failed R2 on all 8 attempts. The auto-verify `full_suite_pass` check used:

```
uv run pytest tests/ -x --timeout=30 -q 2>&1 | tail -5
```

The pipe through `tail -5` means the exit code is always 0 (tail's exit code), even
when pytest exits non-zero. The auto-verify output literally contained
"5 failed, 442 passed" but was marked as `passed: true`.

**Root cause:** Auto-verify checks `exit_code` of the full piped command. Since `tail`
always succeeds, the check always passes regardless of test results. This is a
systemic bug in how auto-verify commands are authored.

---

## D3: Rubric Split Analysis — Composite Grade Masking

### Overview

Across the run's 24 completed tasks:
- **47 individual requirement grades** on passing attempts — all grade A
- **7 auto-graded** (builder self-reported done, no verifier rubric) — all A
- **6 null-reason** (grade A with no explanation) — all A
- **34 verifier-graded** (with detailed reasoning) — all A

### Finding 1: No Composite Masking in Passed Tasks

Every passed task received grade A on *every* requirement. The grading logic requires:
- Critical requirements: must be A
- Expected requirements: must be B or above

Since all 47 requirement grades on passing attempts are A, there is **no evidence of
composite masking** — the verifier did not pass any task where an individual
requirement was below threshold. The system's per-requirement grading with
priority-specific thresholds prevents the kind of masking that a single composite grade
would allow.

### Finding 2: The Real Masking Is in Auto-Verify, Not Grades

The more concerning masking occurs *before* the LLM verifier runs. Seven tasks used
auto-verify-only grading ("Auto-graded: builder self-reported done, no verifier
rubric"). These tasks all received automatic A grades with no independent verification
of quality — only auto-verify command checks.

The auto-verify commands for these test-writing tasks were typically:
```
uv run pytest tests/unit/test_<specific_file>.py -v 2>&1 | tail -15
```

This confirms the tests *run*, but does not verify:
- Test quality or assertion strength
- Coverage completeness
- Whether tests are actually testing the right behavior

### Finding 3: Six Requirements Graded A With No Explanation

Six requirements across three tasks (T-02 StepConfig extension, T-01 Register All
Tools, T-03 Populate mcp_servers) received grade A with `grade_reason: null`. These
had no verifier rubric text and no auto-graded marker — suggesting the grading pathway
assigned A without generating any rationale. This could mask situations where the
verifier defaulted to A rather than performing genuine evaluation.

### Finding 4: Auto-Verify Exit Code Bug Masks Real Test Failures

As detailed in D7, the `full_suite_pass` auto-verify check (used on multiple tasks)
piped through `tail`, making exit code checks meaningless. At least two tasks
(T-02 StepConfig and T-02 Executor) had auto-verify output showing "5 failed" but were
marked as passed.

For T-02 "Extend StepConfig with available_tools and mcp_servers," the auto-verify
`backward_compat` check showed:
```
5 failed, 442 passed, 10 warnings in 26.25s
```
But auto-verify marked it `passed: true` (exit_code: 0 from `tail`). The LLM verifier
then graded both requirements A with null grade_reason — meaning neither auto-verify
nor the verifier caught 5 test failures.

### Grade Distribution Summary (All Attempts)

| Grade | Count | Context                                            |
|-------|-------|----------------------------------------------------|
| A     | 52    | All passing + some failing attempt requirements     |
| B     | 3     | Partial coverage or almost-passing regression check |
| C     | 4     | Environment-blocked verification or weak coverage   |
| D     | 3     | Tests regressed to model-level from integration     |
| F     | 4     | Clear failures in implementation or test suite      |

### Mixed-Grade Attempts (Same Attempt, Different Requirement Grades)

| Task | Attempt | Grades | Outcome |
|------|---------|--------|---------|
| T-01 Claude SDK Filtering | 1 | R1:F, R2:A, R3:A | revision_needed |
| 946657c8 Integration Tests | 1 | R1:B, R2:F | revision_needed |
| 946657c8 Integration Tests | 2 | R1:D, R2:D | failed |
| 946657c8 Integration Tests | 3 | R1:C, R2:F | failed |
| 946657c8 Integration Tests | 4 | R1:B, R2:F | failed |
| 946657c8 Integration Tests | 5 | R1:D, R2:C | failed |
| 946657c8 Integration Tests | 6 | R1:A, R2:B | failed |
| 946657c8 Integration Tests | 7 | R1:A, R2:C | failed |
| 946657c8 Integration Tests | 8 | R1:A, R2:C | failed |

The T-01 Claude SDK case is notable: the task was sent for revision because R1 was F
(additive tool filtering not implemented), despite R2 and R3 being A. Per-requirement
grading correctly prevented masking here — a composite grade might have averaged to B
or C and potentially passed.

---

## Recommendations

### For D7 (Verifier Consistency)

1. **Pin verifier model per run.** The model change from default to gpt-5.3-codex
   between attempts 5 and 6 coincided with R1 jumping from D to A. Different models
   apply different standards, making cross-attempt comparison unreliable.

2. **Distinguish environment failures from code failures in R2.** Attempts 7-8 got C
   on R2 because of a macOS `system-configuration` crate panic — entirely outside the
   builder's control. The rubric should separate "tests fail" from "tests can't run."

3. **Add calibration examples to verifier rubrics.** R1's grade swung 4 letter grades
   partly because "integration-level" vs. "model-level" testing is subjective. Concrete
   examples of A/B/C work in the rubric would improve consistency.

### For D3 (Rubric Split / Composite Masking)

4. **Fix auto-verify exit code checking.** The `| tail -N` pattern breaks exit code
   propagation. Use `set -o pipefail` or avoid pipes: write output to a temp file and
   check pytest's actual exit code separately.

5. **Require grade_reason for all grades, including A.** Six requirements got grade A
   with no explanation. This creates an audit gap — there's no way to verify the
   verifier actually evaluated the work.

6. **Add verifier rubrics to test-writing tasks.** Seven tasks were auto-graded without
   any LLM verification. While auto-verify confirms tests run, it cannot assess test
   quality. At minimum, add a rubric item for assertion strength and coverage
   completeness.

7. **Validate auto-verify output, not just exit code.** The auto-verify system should
   parse pytest output for failure counts, not just check whether the command's exit
   code was 0. A regex check for `\d+ failed` in the output would have caught the
   masking in this run.
