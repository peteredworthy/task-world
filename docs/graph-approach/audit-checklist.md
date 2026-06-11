# Slice Audit Checklist — Frontier True Pass

Reusable audit prompt. Run at the end of EVERY slice, regardless of execution mode
(loop or routine). A slice is **done** when this audit signs off — not when the loop
says it converged or the routine says it completed.

Ground truth: `docs/graph-approach/execution-graph-prd-plus.md` and
`docs/graph-approach/execution-graph-evaluation.md`. The builder's summary is NOT
ground truth.

## Audit prompt (paste verbatim, fill placeholders)

```
You are auditing slice {SLICE_ID} ({SLICE_TITLE}) implemented on branch {BRANCH}.

Ground truth documents (read these FIRST, before the diff or any summary):
- docs/graph-approach/execution-graph-prd-plus.md — section(s): {PRD_SECTIONS}
- docs/graph-approach/execution-graph-evaluation.md (where it amends the PRD)
- The slice definition: {SLICE_SCOPE_TEXT}

Protocol — do these in order, do not skip steps:

1. RE-DERIVE acceptance criteria for this slice from the PRD sections above,
   ignoring the builder's summary entirely. Write them as a numbered list.

2. MAP each criterion to specific evidence: file:line for the implementation,
   and the exact test(s) that exercise it. A criterion with no test evidence
   is UNMET even if code exists.

3. RUN the test suite fresh (do not trust reported results):
   - uv run pytest tests/unit tests/integration
   - any slice-specific fixture suite or e2e drill named in the slice's "done when"

4. ADVERSARIAL pass — attempt one violation per invariant the slice claims.
   For each invariant, describe the attack you tried and what happened.

5. LAZINESS check — work avoided:
   - Stubbed or pass-through implementations hiding behind green tests
   - Fixtures asserting weaker properties than the PRD table they came from
   - Edge rows silently dropped (count PRD table rows vs fixture cases)
   - Error paths that log instead of reject
   - "Deferred to follow-up" notes that were never in scope to defer

6. LIES check — claims unsupported by the diff:
   - Summary claims a behavior no test exercises
   - "All fixtures pass" where fixtures were edited to pass (diff the fixtures!)
   - Determinism claims with hidden clock/random/IO in reducers
   - Renamed-but-unchanged code presented as refactor
   - Acceptance criteria checked off without evidence links

7. TESTING-STANDARDS check (project convention, non-negotiable):
   - NO mocks, NO monkeypatching anywhere in new/changed tests
   - Tests use real sqlite DBs (in-memory or tmp-file) and real files in tmp dirs
   - e2e acceptance drill named in the slice definition exists and passes
   - Commits are small and regular, each leaving tests green

8. VERDICT — exactly one of:
   - ACCEPT — every criterion evidenced, fresh run green, no laziness/lies findings
   - ACCEPT-WITH-PUNCHLIST — minor gaps; list them; none touches a core invariant
   - BOUNCE — gap list returned to the builder; slice is not done

Output format:
- Criteria table: # | criterion | code evidence | test evidence | status
- Findings list: severity | laziness/lie/standards | description | location
- Verdict with one-paragraph justification.
```

## Recording

Audit findings are recorded per slice (count + severity + bounce/accept) — they are
the primary metric for comparing loop vs routine modes. File findings that imply new
work as tuning slices; do not silently fix in the audit pass.
