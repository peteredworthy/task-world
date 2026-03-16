# Verification Report: Idea-to-Plan Routine Optimization

**Status: ✓ Ready**

**Date:** 2026-03-16
**Artifacts verified:** intent.md, plan.md, architecture.md, dry-run-notes.md, steps/step-01.md through steps/step-06.md

---

## 1. Intent → Plan → Step Alignment

### Step-to-Milestone Mapping

| Step File | Plan Milestone | Intent Recommendations | Aligned? |
|-----------|---------------|----------------------|----------|
| step-01.md | M1: Context Injection | R1, R6, R7 | ✓ |
| step-02.md | M2: Verification Optimization | R5 | ✓ |
| step-03.md | M3: Profile-Based Model Routing | R4 | ✓ |
| step-04.md | M4 Prerequisites (engine) | Completion criteria #11, #12 | ✓ |
| step-05.md | M4b: Fan-Out Parallelism | R2, R3 | ✓ |
| step-06.md | M4c: Validation & Live Test | Completion criteria #8, #9, #10, #13 | ✓ |

### Completion Criteria Traceability (all 13)

| # | Criterion | Step File | Covered |
|---|-----------|-----------|---------|
| 1 | context_from on all artifact-consuming tasks | step-01.md | ✓ |
| 2 | S-04/T-01 uses fan_out over step-plan files | step-05.md T1 | ✓ |
| 3 | S-05 restructured: fan_out T-01 + merge T-02 | step-05.md T2 | ✓ |
| 4 | Every task has profile field | step-03.md | ✓ |
| 5 | S-07/T-01 and S-08/T-01 no verifier rubric | step-02.md | ✓ |
| 6 | S-01/T-01 no-source-code directive | step-01.md | ✓ |
| 7 | S-01/T-01 context_from for reference docs | step-01.md | ✓ |
| 8 | YAML schema validation passes | step-06.md T1 | ✓ |
| 9 | Auto-verify commands work with restructured tasks | step-06.md T2 | ✓ |
| 10 | Live test run with measurably lower cost | step-06.md T2 | ✓ |
| 11 | Two-pass template resolution in templates.py | step-04.md T1 | ✓ |
| 12 | executor.py passes run variables to shared_context | step-04.md T2 | ✓ |
| 13 | Original routine unchanged | step-06.md T1 | ✓ |

**Details:**

- **Step 01** covers all M1 items: `context_from` on 5 tasks (S-04/T-01, S-05/T-01, S-06/T-01, S-08/T-01, S-08/T-02), reference doc injection on S-01/T-01 and S-04/T-01, and source code suppression directive on S-01/T-01. Matches plan M1 changes 1-8.
- **Step 02** covers M2: removes `verifier.rubric` from S-07/T-01 and S-08/T-01, adds structural auto-verify to S-08/T-01. Matches plan M2 changes 1-2. Note on `verifier_model` override included (M2 change 3).
- **Step 03** covers M3: adds `profile` field to all 9 tasks with correct tier assignments (architect/coder/summarizer). Matches plan M3 changes 1-3. Note: S-05/T-02 (merge task, added in step-05) also needs a profile — step-05.md includes `profile: "summarizer"` in the T-02 spec, so this is covered.
- **Step 04** covers M4 engine prereqs: two-pass template resolution (plan M4 change 0a) and shared_context variable passing (plan M4 change 0b). Both tasks have detailed implementation plans with correct code.
- **Step 05** covers M4 fan-out: S-04/T-01 fan-out (plan M4 change 1), S-05 restructure from dry_run to fan-out + merge (plan M4 changes 2-3). S-06 context_from update noted (plan M4 change 4).
- **Step 06** covers validation and live test: schema validation, test suites, live run with metrics comparison. Matches plan testing strategy and completion criteria #8, #10, #13.

**Stage numbering:** Intent and plan correctly reference the actual 8-step routine structure (S-01 through S-08). No references to a non-existent S-09, consistent with the clarification decision to correct docs to match the actual routine.

---

## 2. Dry-Run Gap Resolution

All 13 gaps identified in dry-run-notes.md and cross-verification have been applied to step files.

| Gap ID | Severity | Description | Applied to Step Files? | Step File | Verification |
|--------|----------|-------------|----------------------|-----------|--------------|
| GAP-01 | MEDIUM | Reference docs (`docs/plan-runner/*.md`) don't exist | **YES** | step-01.md | Lines 127-141: dependency check with existence test, fallback instructions, and explicit warning not to add `context_from` for missing files |
| GAP-05 | CRITICAL | Regex nesting failure — `.+?` can't handle nested `{{}}` | **YES** | step-04.md | Lines 29-63: uses `_SIMPLE_VAR_RE` with `[^{]+?` character class for Pass 1, preserving original regex for Pass 2. Includes critical test case (line 72) |
| GAP-07 | MEDIUM | shared_context entries produce path strings, not file contents | **YES** | step-04.md | Lines 141-155: explicit note that shared_context must use `{{file:...}}` format, with WRONG vs CORRECT examples |
| GAP-08 | CRITICAL | `fan_out` and `task_context` mutually exclusive — ValueError | **YES** | step-05.md | Lines 31, 66 (S-04/T-01) and lines 111, 161 (S-05/T-01): explicit instructions to REMOVE `task_context` when adding `fan_out`, with warning about schema validation failure |
| GAP-09 | HIGH | Double-plan naming — `{{item_stem}}-plan.md` produces `step-01-plan-plan.md` | **YES** | step-05.md | Lines 115, 147: uses `{{item_stem}}.md` instead of `{{item_stem}}-plan.md`, with explanation that stem already contains `-plan` |
| GAP-10 | HIGH | shared_context bare paths produce literal strings, not file contents | **YES** | step-05.md | Lines 54-58 (S-04) and 151-153 (S-05): all shared_context entries use `"{{file:docs/{{feature}}/...}}"` format |
| GAP-11 | MEDIUM | Per-item auto_verify at task level — `{{output_path}}` undefined | **YES** | step-05.md | Lines 113, 155-159: auto_verify with `{{output_path}}` placed inside `fan_out` block, with explicit warning note |
| GAP-12 | MEDIUM | Profile mappings not configured — silent fallback to default model | **YES** | step-06.md | Lines 82-96: pre-flight environment checks include profile mapping verification, with configuration instructions |
| GAP-13 | MEDIUM | Variable construction ordering — `config_vars` must be built before shared_context loop | **YES** | step-04.md | Lines 157-170: explicit code showing `config_vars` built from `run.config` BEFORE shared_context resolution loop, with warning not to reuse later `variables` dict |
| GAP-14 | MEDIUM | No integration test assertions for shared_context fix | **YES** | step-04.md | Lines 172-188: three specific test assertions with setup/call/assert structure (file contents resolution, nested variables, bare path regression guard) |
| GAP-15 | MEDIUM | No pass/fail thresholds for live test metrics | **YES** | step-06.md | Lines 113-123: pass threshold column added to metrics table (cost < $12 primary gate), with diagnostic guidance mapping each metric to its corresponding optimization |
| GAP-16 | LOW | Live test behavioral claims without concrete checks | **YES** | step-06.md | Lines 103-105, 156-158: concrete assertion checks — concurrent child tasks in run detail for fan-out, attempt count = 1 with no verifier_prompt for auto-verify-only tasks, agent metadata shows correct model per profile |
| GAP-17 | HIGH | `as:` values in `context_from` must match `{{context.X}}` template references | **YES** | step-01.md | Lines 31-33: critical warning added. The prompt generator does simple `{{key}} → value` replacement — `as: "plan"` resolves `{{plan}}` but NOT `{{context.plan}}`. All `as:` values updated to `context.X` prefix (e.g., `as: "context.plan"`) to match existing `{{context.X}}` patterns in task_context. |

**Result:** All critical (GAP-05, GAP-08) and significant (GAP-09, GAP-10, GAP-17) gaps are applied to step files. All 13/13 gaps verified. No gaps show "NO" or are missing the "Applied to step files" field.

---

## 3. Unresolved Conflicts

### Non-Critical Documentation Inconsistency

**architecture.md line 99** states: "context_from and task_context fields ARE mutually exclusive (schema validation rejects combinations)."

This is **incorrect**. The actual code constraint (verified in `src/orchestrator/config/models.py:215-219`) is that `fan_out` and `task_context` are mutually exclusive, NOT `context_from` and `task_context`. The existing routine already uses both `context_from` and `task_context` together (e.g., S-02/T-01, S-03/T-01).

**Impact:** Low. The step files are correct — step-05.md specifies S-05/T-02 with both `context_from` and `task_context` (lines 168-190), and explicitly notes "context_from is valid on S-05/T-02 because it is a non-fan_out task" (line 218). Implementers following the step files will produce correct YAML.

**Recommendation:** Fix architecture.md line 99 to say "`fan_out` and `task_context` fields ARE mutually exclusive" during implementation.

### Non-Critical: Stale Implementation Sketch in Architecture

**architecture.md section 5** (line 156) implementation sketch uses `_PLACEHOLDER_RE` (the original regex with `.+?`) for Pass 1 of two-pass resolution. GAP-05 proved this approach fails because `.+?` consumes inner `{{}}` boundaries. Step-04.md correctly uses `_SIMPLE_VAR_RE` (with `[^{]+?`) for Pass 1, which only matches simple non-nested variables.

**Impact:** None. Step files drive implementation, and step-04.md has the correct approach.

### Non-Critical: Regex Notation Variance Between Dry-Run and Step File

dry-run-notes.md (GAP-05) recommends `[^{}]+` (excludes both braces, greedy). step-04.md specifies `[^{]+?` (excludes opening brace, non-greedy). Both are functionally equivalent for this use case — neither can match across `{{` boundaries, and both correctly skip the outer `{{file:...}}` pattern during pass 1.

**Impact:** None. Either notation produces the same matching behavior.

### Non-Critical: Stale Per-Item Template Reference

**architecture.md line 97** example for S-05/T-01 uses `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}`, which would produce `step-01-plan-plan.md` per GAP-09. The step file (step-05.md line 147) correctly uses `{{item_stem}}.md`. Similarly, **step-05-plan.md line 40** still references the uncorrected `{{item_stem}}-plan.md` form.

**Impact:** Low. The implementation step files (steps/step-05.md) have the correct template. Architecture and step-plan docs are stale but are planning artifacts, not implementation specs.

**Recommendation:** Update architecture.md example and step-05-plan.md during implementation to use `{{item_stem}}.md`.

### No Critical Conflicts

No unresolved critical conflicts remain. All structural, naming, and configuration issues identified during dry-run have been hardened in step files.

---

## 4. Persistence Mapping Audit

**Result: N/A — No new state model fields are introduced.**

All changes are to:
- Routine YAML configuration (steps 01-03, 05) — declarative config, no persistence impact
- `resolve_template()` pure function in `templates.py` (step 04 Task 1) — no state
- `executor.py` variable passing (step 04 Task 2) — fixes existing call, no new state

No `TaskState`, `StepState`, `Run`, or `Attempt` fields are added. No DB columns, repo write/read mappings, or Alembic migrations needed. The persistence mapping table in dry-run-notes.md correctly documents this as N/A.

---

## 5. Integration Test Assertion Quality

| Step | Test Type | Assertions Specified? | Details |
|------|-----------|----------------------|---------|
| step-04.md Task 1 | Unit tests | **YES** | Lines 66-74: specific test cases with input/output pairs. E.g., `resolve_template("{{file:docs/{{feature}}/{{item_stem}}-plan.md}}", variables={"feature": "myproject", "item_stem": "step-01"})` → reads `docs/myproject/step-01-plan.md`. Edge cases documented (line 71: variable containing `{{file:...}}`). Critical regression test specified (line 73: `test_no_recursive_resolution` still passes). |
| step-04.md Task 2 | Integration | **YES** | Lines 172-188: three concrete test assertions with setup/call/assert structure: (1) shared_context with `{{file:...}}` resolves to file contents, (2) nested variables with `{{file:...}}` resolves after two-pass, (3) bare path without `{{file:...}}` returns literal string (regression guard). Also checks variable construction ordering (config_vars built before shared_context loop). |
| step-06.md Task 1 | Schema + test suites | **YES** | Lines 28-45: specific commands with exit code assertions (`exits 0`). Specifies running both unit and integration suites, with fix-and-rerun loop for failures. |
| step-06.md Task 2 | Live test | **YES** | Lines 106-118: metric comparison table with baseline values, target ranges, and columns for actual measurements. Lines 120-128: specific artifact file existence checks by name. Lines 103-105: behavioral assertions (fan-out concurrent, no LLM verifier spawns, correct models per profile). |

**Result:** All test specifications include assertion logic, not just scenario names. Step 04 specifies exact input/output pairs for unit tests. Step 06 specifies measurable success criteria with baseline comparisons and file existence checks.

---

## Summary

| Check | Result |
|-------|--------|
| Step files align with plan and intent | ✓ Pass |
| All critical/significant dry-run gaps applied to step files | ✓ Pass (13/13 applied) |
| No unresolved critical conflicts | ✓ Pass (4 minor doc inconsistencies noted, none blocking) |
| Persistence mapping audit — no MISSING cells | ✓ N/A (no new state fields) |
| Integration test assertion logic specified | ✓ Pass |

**Overall: ✓ Ready for implementation.**
