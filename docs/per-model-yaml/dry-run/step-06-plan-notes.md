# Step 06 Dry-Run Analysis: Frontend Display (M6)

*Generated: 2026-04-08*

---

## Pre-flight: Actual File State

Before simulating, verifying what already exists vs. what the plan assumes:

| File | Status |
|------|--------|
| `ui/src/types/runs.ts` — `ModelTokenUsage` interface | **ALREADY EXISTS** (lines 40–51, all 10 fields present) |
| `ui/src/types/runs.ts` — `RunResponse.token_usage_by_model` | **ALREADY EXISTS** |
| `ui/src/types/tasks.ts` — `AttemptSchema.token_usage_by_model` | **MISSING** — field not present |
| `ui/src/components/detail/MetricsBar.tsx` | **EXISTS** — but orphaned (not imported anywhere) |
| `ui/src/components/detail/ModelCostBreakdown.tsx` | **DOES NOT EXIST** |
| `ui/src/components/detail/modelCostUtils.ts` | **DOES NOT EXIST** |
| `ui/src/components/dashboard/RunDetail.tsx` — imports MetricsBar | **NOT WIRED** — MetricsBar not imported or rendered |

---

## T-01: Add ModelTokenUsage TypeScript type and update RunResponse

### Assumptions
- Types need to be checked before adding (plan acknowledges this).
- `AttemptSchema` in `tasks.ts` may need `token_usage_by_model` if the task detail page will show per-attempt breakdowns.

### Expected outputs
- T-01 is mostly a no-op for `runs.ts` since both `ModelTokenUsage` and `RunResponse.token_usage_by_model` already exist.
- Only real work: add `token_usage_by_model?: ModelTokenUsage[]` to `AttemptSchema` in `tasks.ts` (currently missing).

### Blockers / Failure modes

**F1: Auto-verify commands are trivially passable without actual work.**
- `grep -n 'ModelTokenUsage' ui/src/types/runs.ts | grep -q 'interface\|export' && echo ok` — will pass immediately since the interface already exists. No risk of false positive blocking, but this means the auto_verify provides zero signal about whether the *builder actually read the file* before declaring done.
- **Mitigation**: None needed for this step since the types genuinely exist. Verifier should check `tasks.ts` has the field too.

**F2: `tasks.ts` AttemptSchema missing `token_usage_by_model`.**
- The task says "if it exists" for `tasks.ts`, but since the codebase discovery doc says `AttemptSchema` exists in `tasks.ts` and the field is missing, this is a real gap. If per-attempt breakdown is ever needed in the UI, this field must be added.
- **Mitigation**: Builder should add `token_usage_by_model?: ModelTokenUsage[]` to `AttemptSchema`. The plan context is silent on whether this matters for M6. However, since M6 only shows the run-level breakdown table, omitting it from `AttemptSchema` is acceptable for this milestone.

**F3: Type check may already pass with no changes.**
- `cd ui && npm run typecheck` will pass since all types already exist. This auto_verify is existence-level only — it won't detect if the field is *missing* from `AttemptSchema`.
- **Hardening action**: Add an explicit check: `grep -n 'token_usage_by_model' ui/src/types/tasks.ts | grep -q 'ModelTokenUsage'` to verify the attempt-level type too.

### Risk assessment
Low risk. Types already exist. The main risk is that a builder marks this done without checking `tasks.ts`.

---

## T-02: Create per-model cost breakdown table component

### Assumptions
1. A new `ModelCostBreakdown.tsx` will be created (not extending MetricsBar directly, since MetricsBar already has a defined scope).
2. The component will be wired into `RunDetail.tsx` somewhere near existing cost display.
3. React Fast Refresh constraint means utility functions go in `modelCostUtils.ts`.

### Expected outputs
- `ui/src/components/detail/ModelCostBreakdown.tsx` — new component
- `ui/src/components/detail/modelCostUtils.ts` — utility functions
- `ui/src/components/dashboard/RunDetail.tsx` modified to import and render `ModelCostBreakdown`

### Blockers / Failure modes

**F4 (CRITICAL): MetricsBar is currently orphaned — it's not imported by RunDetail.**
- The existing `MetricsBar.tsx` renders tokens + estimated cost, but is never imported or rendered anywhere in the codebase. The run detail page currently shows NO cost/token data.
- If the builder creates `ModelCostBreakdown.tsx` but also fails to wire MetricsBar (or replaces it), the cost display is still absent.
- **Hardening action**: The step must explicitly require wiring BOTH: (a) `ModelCostBreakdown` into `RunDetail`, and (b) consider whether `MetricsBar` should also finally be imported (or whether `ModelCostBreakdown` subsumes it). The step plan only says "Integrate the new component into the run detail page" — this is vague about the MetricsBar orphan problem.
- **Concrete hardening**: Add an auto_verify: `grep -n 'ModelCostBreakdown\|MetricsBar' ui/src/components/dashboard/RunDetail.tsx | grep -q 'import'` to confirm wiring.

**F5 (CRITICAL): Component wiring verification is existence-only.**
- The auto_verify `component_file_exists` checks for the file OR for `token_usage_by_model` in MetricsBar. This is AND-able with the MetricsBar orphan: the check `grep -rn 'token_usage_by_model' ui/src/components/detail/MetricsBar.tsx | grep -q 'map\|length' && echo ok` would pass if someone extends MetricsBar with the table — but MetricsBar is still never rendered. The component would exist and pass all checks while remaining invisible to users.
- **Hardening action**: Add explicit auto_verify: `grep -n 'ModelCostBreakdown\|MetricsBar' ui/src/components/dashboard/RunDetail.tsx | grep -q '.'` — must confirm the component is imported and used in the actual run detail page.

**F6: "cost unknown" badge logic is grep-only.**
- `grep -rn 'cost unknown...' ui/src/components/ | grep -qi 'cost' && echo ok` — passes if the string appears anywhere in any component file. A builder could add a comment `// show "cost unknown" badge here` without implementing it, and the check would pass.
- **Mitigation**: The verifier rubric (R5) is contract-level and will catch stubs. Auto_verify here is appropriately flagged as existence-only.

**F7: Grand total computation correctness not verified by auto_verify.**
- No auto_verify checks the math for the grand total row. A builder could render the first entry's `total_cost_usd` instead of the sum, and all auto_verifies would pass.
- **Mitigation**: Covered by R4 in verifier rubric. The T-03 test (R11) would also catch this if tests actually assert the value.

**F8: Fallback disclaimer string mismatch.**
- The auto_verify checks for `sub-agents not included` or `sub_agents_not_included` or `disclaimer`. The intent document says "cost estimate, sub-agents not included". A builder might use slightly different wording (e.g., "Sub-agents excluded") that fails the grep but passes the spirit.
- **Hardening action**: Document the exact required string in the task context, or make the auto_verify case-insensitive: `grep -ri 'sub-agent.*not\|sub_agent.*not' ui/src/components/ | grep -q .`

**F9: React Fast Refresh constraint may be violated.**
- If a builder puts utility functions and a component export in the same `.tsx` file, Fast Refresh will show lint warnings or errors. The task context mentions this but it's easy to forget.
- **Mitigation**: The `lint_passes` auto_verify would catch this if ESLint is configured for it. Verify ESLint has the Fast Refresh plugin configured.

**F10: MetricsBar and ModelCostBreakdown may create duplicate cost display.**
- MetricsBar already shows `estimated_cost_usd`. If ModelCostBreakdown is added AND MetricsBar is finally wired, users see cost twice. The builder needs to decide: replace MetricsBar's cost card with the breakdown, or extend MetricsBar internally.
- **Hardening action**: The step should explicitly say "integrate ModelCostBreakdown *as a replacement for* MetricsBar's cost card, OR add it as a section below MetricsBar." The current description is ambiguous.

### Risk assessment
High risk. The MetricsBar orphan is the biggest gap: the component wiring auto_verify is insufficient to catch the case where `ModelCostBreakdown` exists but is never rendered. The verifier rubric (R7) requires a developer to open a run and visually verify — that's the only true integration check.

---

## T-03: Frontend tests for ModelCostBreakdown component

### Assumptions
1. `ModelCostBreakdown.tsx` from T-02 is the component being tested.
2. Tests follow the RecoveryPanel pattern: pass `RunResponse` as props directly, no API mocking.
3. `makeRun()` factory needs to include `token_usage_by_model`.

### Expected outputs
- `ui/src/components/detail/__tests__/ModelCostBreakdown.test.tsx`
- 6 test cases covering all specified scenarios

### Blockers / Failure modes

**F11: makeRun() factory gap.**
- Existing `RecoveryPanel.test.tsx` uses a `makeRun()` factory. Codebase discovery confirms it does NOT include `token_usage_by_model`. If the new test imports or copies this factory without adding the field, TypeScript will error (field is required in `RunResponse`). Actually wait — `token_usage_by_model: ModelTokenUsage[]` is typed as a required array, not optional. If `makeRun()` omits it, TypeScript will error at compile time.
- **Hardening action**: The task context should explicitly say "the makeRun() factory in RecoveryPanel does not include token_usage_by_model — add it in the new test file's factory."

**F12: Grand total precision/formatting.**
- Test R11 requires "grand total displayed is 0.06" for inputs [0.01, 0.02, 0.03]. Floating point: `0.01 + 0.02 + 0.03 = 0.06000000000000001` in JavaScript. If the component formats with `toFixed(4)` or similar, the displayed value is "0.0600" — the test must use `toFixed` or approximate matching, not exact string equality "0.06".
- **Hardening action**: Document that the test should use a regex or approximate match: `expect(screen.getByText(/0\.0600|0\.06/)).toBeInTheDocument()`.

**F13: "cost unknown" badge text must match component implementation.**
- Test R9 asserts `"cost unknown"` text appears. The component developer may use a different exact string (e.g., "Cost unknown", "Unknown cost", "N/A"). The test and implementation must agree on the exact string.
- **Hardening action**: Lock the badge text to lowercase `"cost unknown"` in both component and test. Document this in T-02's task context.

**F14: Test for `undefined` token_usage_by_model may require TypeScript cast.**
- `RunResponse.token_usage_by_model` is typed as `ModelTokenUsage[]` (non-optional array). Passing `undefined` requires `as any` or a type override. This is a common pattern in tests (codebase shows `as any` usage) but should be noted.
- **Mitigation**: Use `{ ...makeRun(), token_usage_by_model: undefined as any }` pattern, consistent with existing test patterns.

**F15: `npm test -- --run` auto_verify runs all tests including slow ones.**
- `all_frontend_tests_pass` runs the entire test suite. This is contract-level (good) but slow. If T-02 wiring breaks an existing test (e.g., RunDetail snapshot test), it will be caught here.
- **Risk**: Low. No existing snapshot tests found.

**F16: Component not imported in test.**
- If T-02 is incomplete (component not created), T-03's tests will fail at import time. This is expected dependency behavior and appropriate.

### Risk assessment
Medium risk. Main risks are floating-point precision in the grand total test and TypeScript's non-optional array type requiring `as any` for the `undefined` test case.

---

## Component Wiring Summary

The most important wiring gap for this step is **MetricsBar being orphaned**. Currently:

```
RunDetail.tsx → (no MetricsBar import) → MetricsBar.tsx (orphaned)
                                        → ModelCostBreakdown.tsx (doesn't exist yet)
```

After Step 06, the required wiring is:

```
RunDetail.tsx → imports ModelCostBreakdown (or extended MetricsBar)
             → renders it with run prop
             → component reads run.token_usage_by_model
             → if non-empty: renders per-model table with totals + cost unknown badges
             → if empty: renders fallback with legacy fields + disclaimer
```

The auto_verify for R7 is existence-only (`test -f` or `grep`). The only true wiring check is the verifier rubric requiring visual confirmation. **This step needs an explicit auto_verify checking that `ModelCostBreakdown` (or `MetricsBar`) is imported in `RunDetail.tsx`.**

---

## Auto_Verify Quality Assessment

| Check | Quality | Notes |
|-------|---------|-------|
| `model_token_usage_interface_exists` | Existence-only | Types already exist; passes immediately without any builder action |
| `run_response_has_field` | Existence-only | Field already exists; passes immediately |
| `typecheck_passes` (T-01) | Contract-level | Will catch real type errors, but won't catch missing `tasks.ts` field |
| `component_file_exists` | Existence-only | Passes even if MetricsBar is extended with dead code; does NOT verify wiring into RunDetail |
| `cost_unknown_badge_logic` | Existence-only | String grep passes even for comments; real check is verifier R5 |
| `fallback_disclaimer` | Existence-only | Same — string grep; real check is verifier R6 |
| `typecheck_passes` (T-02) | Contract-level | Good — will catch broken imports and type errors |
| `lint_passes` | Contract-level | Good — will catch Fast Refresh violations |
| `test_file_exists` | Existence-only | Trivial |
| `frontend_tests_pass` | Contract-level | Best check in the step — must run and pass |
| `all_frontend_tests_pass` | Contract-level | Catches regressions in existing tests |
| `build_passes` | Contract-level | Catches bundler-level errors |

**Missing auto_verify**: No check verifies that `ModelCostBreakdown` (or MetricsBar) is imported in `RunDetail.tsx`. This is the critical gap — R7 wiring is unverified by auto_verify.

---

## Hardening Actions Summary

| # | Action | Priority |
|---|--------|----------|
| H1 | Add auto_verify to T-02: `grep -n 'ModelCostBreakdown\|MetricsBar' ui/src/components/dashboard/RunDetail.tsx | grep -q import` | Critical |
| H2 | Clarify in T-02 task context: "MetricsBar is currently not imported by RunDetail — this step must wire at least one cost component into RunDetail" | Critical |
| H3 | Clarify in T-02 task context: resolve MetricsBar vs ModelCostBreakdown overlap — avoid showing cost twice | High |
| H4 | Lock badge text to lowercase "cost unknown" in both T-02 and T-03 task contexts | High |
| H5 | Note in T-03: `token_usage_by_model` is non-optional in RunResponse — use `as any` for undefined test case | Medium |
| H6 | Note in T-03: floating-point sum 0.01+0.02+0.03; use regex/toFixed match not exact string "0.06" | Medium |
| H7 | Add auto_verify to T-01: check `tasks.ts` has `token_usage_by_model` field (or document as out-of-scope for M6) | Low |
| H8 | Note in T-02: Fast Refresh — utilities must be in `modelCostUtils.ts`, not in `.tsx` file | Low (already in context) |
