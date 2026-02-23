# Plan Summary: Run Review, Prune & Merge Workbench

**Date:** 2026-02-23
**Stage:** 9 — Execution Summary + Validated Plan

---

## 1. Intent Satisfaction Summary

The plan fully satisfies the original intent: deliver a "Review & Merge" tab on the run detail page providing a complete pre-merge workbench. Every item in the Definition of Complete checklist (18 items) maps to one or more implementation steps, and all clarification decisions (6 Q&As) are consistently reflected across intent, plan, architecture, and step files.

### Coverage Highlights

| Intent Area | Steps Covering It | Status |
|---|---|---|
| Review & Merge tab with branch status, file lists, worktree path | Steps 1–2 | Covered |
| Diff viewer (react-diff-view, inline/side-by-side, 3 scopes) | Steps 1, 3 | Covered |
| Near full-screen diff dialog | Step 3 | Covered |
| Prune mode (file/hunk/line selection, preview, apply) | Steps 4–5 | Covered |
| Prune auditability via run events | Steps 4–5 | Covered |
| Test execution from workbench | Steps 6–7 | Covered |
| Agent assist: fix tests | Step 7 | Covered |
| Agent assist: resolve conflicts | Step 9 | Covered |
| Back merge with confirmation and impact summary | Steps 8–9 | Covered |
| Conflict resolver (ours/theirs/manual per block) | Steps 8–9 | Covered |
| Merge readiness gating (4 gates) | Step 10 | Covered |
| Final merge-back (squash/merge choice) | Step 10 | Covered |
| Branch history timeline | Step 11 | Covered |
| Task-level file attribution | Step 11 | Covered |
| Backend endpoints for all review operations | Steps 1, 4, 6, 8, 10 | Covered |
| Playwright E2E tests for all major workflows | Step 12 | Covered |
| Playwright visual regression tests | Step 12 | Covered |
| Existing tests continue to pass | All steps (verification criteria) | Covered |

**No intent gaps remain.** Every in-scope feature has a corresponding implementation step.

---

## 2. Ordered Step List with Task Counts

| Step | Title | Tasks | Prerequisites | Milestone |
|------|-------|------:|---------------|-----------|
| 1 | Backend diff endpoints + branch status enhancements | 7 | None | M1 |
| 2 | Frontend Review & Merge tab skeleton + branch status panel | 5 | Step 1 | M1 |
| 3 | Diff dialog with react-diff-view | 4 | Step 2 | M1 |
| 4 | Backend prune endpoints | 5 | Step 1 | M2 |
| 5 | Frontend prune mode | 4 | Steps 3, 4 | M2 |
| 6 | Backend test execution endpoint | 4 | Step 1 | M2 |
| 7 | Frontend test panel + agent fix tests | 4 | Steps 5, 6 | M5 |
| 8 | Backend conflict resolution endpoints | 5 | Step 1 | M3/M4 |
| 9 | Frontend back merge + conflict resolver | 4 | Steps 3, 8 | M3/M4/M5 |
| 10 | Merge readiness gating + final merge | 4 | Steps 5, 7, 9 | M6 |
| 11 | Branch history + task file attribution | 3 | Steps 2, 3 | M7 |
| 12 | Visual polish + edge states + keyboard shortcuts + visual regression | 5 | Steps 1–11 | M7 |
| | **Total** | **54** | | |

### Dependency Graph

```
Step 1 ──┬── Step 2 ── Step 3 ──┬── Step 5 ──┐
         ├── Step 4 ─────────────┘            │
         ├── Step 6 ── Step 7 ────────────────┤
         └── Step 8 ── Step 9 ────────────────┤
                                               │
                       Step 10 ◄───────────────┘
                       Step 11 ◄── Steps 2, 3
                       Step 12 ◄── Steps 1-11
```

### Parallelization Opportunities

- **Steps 4, 6, 8** are independent backend steps — can execute in parallel after Step 1 completes
- **Step 11** can start as soon as Steps 2 and 3 complete (independent of Steps 4–10)
- **Steps 5, 7, 9** can partially overlap once their respective backend prerequisites finish

---

## 3. Key Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Tab availability | Any run status as long as worktree exists | Maximum flexibility for in-progress, completed, and failed runs |
| 2 | Agent backend for review actions | Default to run's agent; Advanced toggle for override | Simple UX by default, flexible when needed |
| 3 | Test command source | Routine's `auto_verify` commands | Reuses existing config; no new configuration surface |
| 4 | Merge strategy for final merge-back | User choice: squash (default) or merge commit | Squash gives clean history; merge preserves audit trail; user decides |
| 5 | Back merge behavior | Auto-commit clean merges + post-merge undo banner | Standard git behavior for clean; undo option as safety net |
| 6 | Task-level file attribution | File shown under every task that touched it | Preserves full attribution; each task shows its own diff |
| 7 | Diff rendering library | `react-diff-view` | PRD-specified; supports unified/split, custom gutters |
| 8 | Prune mechanism | `git apply --reverse` (patch-based) | Safe, auditable, works at file/hunk/line level |
| 9 | Prune commit strategy | Dedicated commit per prune-apply | Full auditability via git history |
| 10 | Line-level prune scope | Selection-only from existing diff lines (no free-form editing) | v1 simplicity; avoid full editor complexity |
| 11 | Merge readiness computation | Server-side with client polling | Authoritative gate evaluation on backend |
| 12 | Conflict resolution granularity | Block-level (ours/theirs/manual) | Matches PRD; avoids full editor complexity |
| 13 | Test execution model | Subprocess in worktree directory | Consistent with existing agent execution pattern |
| 14 | Async git pattern | New `_run_git_async()` or `asyncio.to_thread()` | Must be decided in Step 1 and reused in Steps 4, 8 |
| 15 | ReviewService approach | Direct git ops calls (no intermediate service class) | Simpler; acceptable for v1 |
| 16 | Playwright E2E test strategy | Batched in Step 12 | Each prior step verified via unit/integration tests |

---

## 4. Risks and Mitigations

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| 1 | **Hunk/line-level prune correctness** — Constructing selective reverse patches is the most complex algorithm in the feature. Incorrect hunk header adjustments corrupt the worktree. | High | Thorough unit tests with edge cases (multi-hunk files, adjacent changes, empty hunks). Step 4 includes detailed algorithm specification. |
| 2 | **Ad-hoc agent dispatch mechanism** — No existing infrastructure for dispatching agents outside the builder/verifier lifecycle. Steps 7 and 9 depend on this. | High | Design and implement a generic `POST /review/agent-dispatch` endpoint early in Step 7 before frontend agent modals. Keep it simple: accept prompt + agent config, spawn against worktree. |
| 3 | **back_merge() backward compatibility** — Changing `back_merge()` to leave merges in-progress (instead of aborting on conflict) could break existing callers. | Medium | Add `abort_on_conflict: bool = True` parameter (existing callers get old behavior by default). Alternatively, create a new `back_merge_for_review()` function. |
| 4 | **react-diff-view API compatibility** — Custom gutter API differs between v2 and v3. Prune mode gutter integration depends on the installed version. | Medium | Pin exact version in package.json. Verify gutter API at install time (Step 3). |
| 5 | **Async vs sync git subprocess inconsistency** — Existing `_run_git()` is sync; new modules need async. Inconsistent patterns across codebase. | Medium | Establish async pattern once in Step 1 (`_run_git_async()` or `asyncio.to_thread()`). All subsequent steps follow the same pattern. |
| 6 | **Large diff performance** — Rendering diffs with >10K lines may cause UI slowdown. | Medium | Deferred to Step 12 (lazy rendering with collapsed file sections). Acceptable for v1 with typical file counts. |
| 7 | **In-memory test run tracking** — Test results are lost on server restart; no cross-process mutual exclusion for multi-worker deployments. | Low | Accepted as v1 limitation. Single-worker deployment is the target. |
| 8 | **Commit message badge detection** — Badge classification (prune, agent, back-merge) relies on commit message pattern matching, which is fragile. | Low | Accepted as v1 limitation. Consider structured metadata (git notes/trailers) in future iteration. |

---

## 5. Caveats for Execution

### Ordering Constraints

1. **Step 1 is the critical path.** All other steps depend on it. It must complete fully before any parallel backend work (Steps 4, 6, 8) or frontend work (Step 2) can begin.
2. **Agent dispatch mechanism must be built in Step 7 backend work** before frontend agent modals in Steps 7 and 9 can function. This is a cross-cutting dependency.
3. **Step 10 is the convergence point** — it depends on Steps 5, 7, and 9. Merge readiness gating integrates all prior subsystems.
4. **Step 12 depends on all prior steps** and should only execute after the full feature is functional.

### Known v1 Limitations (Out of Scope)

- No full code editing IDE — only selection-based prune
- No commit history rewriting (rebase/squash/amend) from UI
- No multi-user collaborative editing
- No binary file conflict resolution beyond keep-ours/keep-theirs
- No configurable test profiles (uses single default verification profile)
- In-memory test run tracking does not survive restarts
- In-memory tracking does not support multi-worker deployments

### Dry Run Findings

32 gaps were identified during dry-run simulation (documented in `dry-run-notes.md`):
- **7 high-severity** — all have concrete remediation paths tracked in step execution files
- **14 medium-severity** — addressed via task-level guidance or accepted with mitigations
- **11 low-severity** — accepted as v1 limitations or tracked as minor agent guidance items

No gap blocks execution. Each has a concrete fix or acceptable workaround.

### Cross-Cutting Concerns

| Concern | Resolution |
|---|---|
| Async git subprocess pattern | Decided in Step 1, reused in Steps 4, 8 |
| Ad-hoc agent dispatch | Built in Step 7, reused in Step 9 |
| ReviewService vs direct calls | Direct calls (simpler); update architecture doc accordingly |
| Playwright E2E strategy | Batched in Step 12; prior steps use unit/integration tests |
| Tab system creation | Built from scratch in Step 2 (RunDetail.tsx has no existing tabs) |

### Verification Cross-References

All planning artifacts have been cross-checked (see `verification-report.md`):
- Intent ↔ Plan: full coverage of all 18 Definition of Complete items
- Plan ↔ Step files: 12 steps with all deliverables present
- Clarifications ↔ All docs: 6 Q&A resolutions consistently reflected
- Dry run ↔ Step files: all 32 gaps categorized with remediations
- Architecture ↔ Step files: every new/modified file appears in at least one execution file
- Dependency chain: validated, no circular dependencies

### Estimated Scope

- **~35 new files** (8 backend Python, 20+ frontend TypeScript/React, 6+ test files)
- **~10 modified files** (API app, schemas, branch ops, events, RunDetail page, package.json, docs)
- **54 total tasks** across 12 steps
- **7 milestones** delivering vertical slices of testable functionality

---

## 6. Artifact Index

| Artifact | Path | Purpose |
|---|---|---|
| Intent | `docs/git-ops/intent.md` | Goals, scope, definition of complete |
| Plan | `docs/git-ops/plan.md` | Milestones, implementation order, key decisions |
| Architecture | `docs/git-ops/architecture.md` | Technical design, new/modified components, testing strategy |
| Clarifications | `docs/git-ops/clarifications.md` | 6 resolved design questions |
| Step plans | `docs/git-ops/step-{01..12}-plan.md` | Per-step purpose, contracts, verification criteria |
| Step execution files | `docs/git-ops/steps/step-{01..12}.md` | Per-step atomic task lists with file references |
| Dry-run notes | `docs/git-ops/dry-run-notes.md` | 32 gap findings from execution simulation |
| Verification report | `docs/git-ops/verification-report.md` | Cross-check of all artifacts for alignment |
| **This summary** | `docs/git-ops/plan-summary.md` | Execution summary, decisions, risks, caveats |
