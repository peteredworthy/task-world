# Verification Report: Routine System Effectiveness Improvements

## Summary

Cross-checked intent, plan, architecture, step plan files (step-01-plan through step-15-plan), step task files (steps/step-01 through steps/step-15), dry-run simulation notes, and clarifications for mutual consistency and execution readiness.

**Overall assessment:** Artifacts are well-aligned with 4 known issues (all identified in dry-run notes) and 2 minor inconsistencies found during verification. No unresolved critical conflicts remain — all issues are tracked below with recommended fixes.

---

## 1. Intent-to-Plan Alignment

| Intent Item | Plan Step | Aligned? | Notes |
|-------------|-----------|----------|-------|
| A1 — auto_verify timing | Step 1 | Yes | |
| A2 — require verification | Step 2 | Yes | Clarification Q2 (warn by default) reflected in plan |
| A4 — test regression guard | Step 9 | Yes | |
| A5 — pre-run test health check | Step 3 | Yes | Clarification Q1 (project-level config) reflected |
| A6 — clarification compression | Step 7 | Yes | |
| A7 — prompt dead weight | Step 5 | Yes | Clarification Q6 (informational %) reflected |
| A8 — agent-specific instructions | Step 6 | Yes | |
| A10 — verifier model pinning | Step 4 | Yes | |
| A11 — agent escalation | Step 10 | Yes | |
| A12 — step-level auto_verify | Step 11 | Yes | Clarification Q3 (halt run) reflected |
| A13 — context summarization | Step 12 | Yes | Clarification Q4 (configurable model) reflected |
| A14 — step_context guidance | Step 8 | Yes | |
| A16 — task complexity | Step 13 | Yes | |
| A17 — multi-file routines | Step 14 | Yes | Clarification Q7 (fail validation) reflected |
| A18 — failure mode analysis | Step 15 | Yes | |
| A3, A9, A15 — out of scope | N/A | Yes | Correctly excluded from plan |

All 16 in-scope actions map to plan steps. All 7 clarification decisions are reflected in the corresponding plan steps and step task files. Milestone structure (M1-M5) matches the plan's dependency analysis. Clarification Q5 (parallel M1+M2) is reflected in plan's dependency section.

## 2. Plan-to-Step-Files Alignment

All 15 plan steps have corresponding step-plan files (step-XX-plan.md) and step task files (steps/step-XX.md). Task decomposition in step files matches plan descriptions. Verification strategies in step-plan files are consistent with the architecture's testing strategy section.

## 3. Dry-Run Gaps Analysis

### Critical Gaps (from dry-run notes)

| # | Gap | Dry-Run Rec | Status in Step Files | Resolution |
|---|-----|-------------|---------------------|------------|
| 1 | Step 1 Task 1.1: file ref says `engine.py` but auto_verify logic is in `service.py` | Fix file reference | **NOT FIXED** — step-01.md and step-01-plan.md still reference `engine.py` | Must fix before execution |
| 2 | Step 11 Task 11.2: step completion logic likely in `service.py`, not `engine.py` | Fix file reference | **NOT FIXED** — steps/step-11.md still references `engine.py` | Must fix before execution |
| 3 | Step 12 Task 12.1: model name `ContextFromConfig` vs actual `ContextSource` | Fix model name | **PARTIALLY ADDRESSED** — steps/step-12.md uses `ContextFromConfig` in the task title but this matches architecture.md which defines `ContextFromConfig` as the model name; the dry-run claims actual name is `ContextSource` — needs code verification | Verify actual model name in codebase before execution |
| 4 | Step 14 Task 14.2: `loader.py` doesn't exist, task says "Update" | Change to "Create" | **NOT FIXED** — steps/step-14.md still says "Update `loader.py`" without noting it needs creation | Must fix before execution |

### High Priority Gaps (from dry-run notes)

| # | Gap | Status | Resolution |
|---|-----|--------|------------|
| 5 | Step 3 Task 3.1: `.task-world/config.yaml` format undefined | **ADDRESSED** — step-03-plan.md defines config format; steps/step-03.md includes format details | No action needed |
| 6 | Step 6 Task 6.1: need to inventory agent-specific sections; `codex_server.py` uses `_build_prompt` | **PARTIALLY ADDRESSED** — architecture.md lists sections per agent; codex method name NOT noted in step files | Add note about `_build_prompt` to step-06 |
| 7 | Step 9 Task 9.1: script modes (`--snapshot`/`--compare`) undefined | **NOT ADDRESSED** — steps/step-09.md doesn't specify operating modes | Add mode specification |
| 8 | Step 12 Task 12.3: LLM integration complexity (async, client, fallback) | **PARTIALLY ADDRESSED** — steps/step-12.md specifies fallback behavior but doesn't address async question or which client to use | Add implementation guidance |

### Medium Priority Gaps (from dry-run notes)

| # | Gap | Status |
|---|-----|--------|
| 9 | Step 2 Tasks 2.1/2.2: define "verification present" | Addressed in architecture.md (auto_verify items OR verifier section) |
| 10 | Step 7 Task 7.1: clarification data flow unclear | Not addressed in step files — agent must trace |
| 11 | Step 10 Task 10.1: reference existing checklist models | Addressed — step-10.md references requirement/checklist concepts |
| 12 | Step 14 Task 14.1: list conflicting fields, use `model_fields_set` | Not addressed in step files |

## 4. Architecture Consistency

- Architecture references `ContextFromConfig` as the model name (line 43-48). If actual code uses `ContextSource`, architecture also needs updating.
- Architecture correctly lists all modified and new files, matching step file references.
- Testing strategy in architecture matches step-level verification strategies.
- Architecture §4 (Prompt Builder, A8) says "Each agent's `build_prompt()` method already exists" — dry-run notes flag that codex uses `_build_prompt` and some agents may not have the method at all.

## 5. Conflicts and Inconsistencies

### Issue A: File reference mismatch (Steps 1, 11)
- **Severity:** Critical for execution
- **Description:** Step-plan and step-task files reference `engine.py` for auto_verify timing (Step 1) and step completion (Step 11), but dry-run analysis found the logic is in `service.py`. Architecture doc also references `engine.py`.
- **Impact:** Agents will edit the wrong file, wasting attempts.
- **Resolution:** Update step-01-plan.md, steps/step-01.md, step-11-plan.md (if applicable), steps/step-11.md, and architecture.md to reference `service.py` with method names.

### Issue B: loader.py existence (Step 14)
- **Severity:** Medium for execution
- **Description:** Task 14.2 says "Update `loader.py`" but the file doesn't exist.
- **Impact:** Agent confusion about starting point.
- **Resolution:** Change verb to "Create" and add guidance to find current loading code.

### Issue C: Script operating modes (Step 9)
- **Severity:** Low
- **Description:** `check_test_count.sh` needs defined `--snapshot`/`--compare` interface.
- **Impact:** Inconsistent implementations across attempts.
- **Resolution:** Add mode specification to steps/step-09.md.

## 6. Completion Criteria Coverage

All 15 completion criteria from intent.md map to at least one step:

| Criteria | Step(s) | Covered? |
|----------|---------|----------|
| 1. Auto-verify before gate | Step 1 | Yes |
| 2. No undefended tasks | Step 2 | Yes |
| 3. Test health gate | Step 3 | Yes |
| 4. Verifier model pinned | Step 4 | Yes |
| 5. Prompt reduction | Steps 5, 6 | Yes |
| 6. Test regression guard | Step 9 | Yes |
| 7. Agent escalation | Step 10 | Yes |
| 8. Step-level auto_verify | Step 11 | Yes |
| 9. Context summarization | Step 12 | Yes |
| 10. Clarification compression | Step 7 | Yes |
| 11. Multi-file routines | Step 14 | Yes |
| 12. Task complexity field | Step 13 | Yes |
| 13. Planning docs updated | Steps 8, 15 | Yes |
| 14. All existing tests pass | All steps | Yes (via regression testing) |
| 15. New tests cover features | All steps | Yes (per-step verification) |

## 7. Recommended Actions Before Execution

### Must Fix (Critical)

1. **Steps 1 & 11:** Update file references from `engine.py` to `service.py` with specific method names (`submit_task()` for Step 1, step completion method for Step 11). Update architecture.md accordingly.
2. **Step 14 Task 14.2:** Change "Update `loader.py`" to "Create `loader.py`" and add guidance on finding current routine loading code.
3. **Step 12 Task 12.1:** Verify actual model name in codebase (`ContextFromConfig` vs `ContextSource`) and update all references to match.

### Should Fix (High Priority)

4. **Step 6 Task 6.1:** Add note that `codex_server.py` uses `_build_prompt`, not `build_prompt`.
5. **Step 9 Task 9.1:** Add `--snapshot <file>` and `--compare <file>` mode specification.
6. **Step 12 Task 12.3:** Add guidance on LLM client to use and whether prompt assembly should be async.

### Nice to Fix (Medium Priority)

7. **Step 7 Task 7.1:** Add data flow description for clarifications.
8. **Step 14 Task 14.1:** List conflicting fields and recommend `model_fields_set`.

---

## Conclusion

The intent, plan, step files, and architecture are well-aligned at the conceptual level. All clarification decisions are properly reflected. The dry-run simulation identified real issues — 4 critical gaps that need fixing in step files before execution to prevent agent misdirection. No unresolved critical conflicts exist between the documents themselves; the gaps are between documented file references and actual codebase structure. The 3 "Must Fix" items above should be applied to the step files before the routine begins execution.
