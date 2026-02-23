# Verification Report: Run Review, Prune & Merge Workbench

**Date:** 2026-02-23
**Stage:** 7 – Final Check (cross-check intent, plan, step files, and dry run output)

---

## 1. Intent ↔ Plan Alignment

The plan (`plan.md`) was checked against every item in the intent (`intent.md`) "Definition of Complete" checklist and the "In Scope" list.

### Coverage Matrix

| Intent Item | Plan Coverage | Status |
|---|---|---|
| Review & Merge tab with branch status, file lists, conflict group, worktree path copy | Milestone 1, Steps 1–2 | Covered |
| Diff viewer with react-diff-view (inline/side-by-side, aggregate/commit/task scopes) | Milestone 1, Step 3 | Covered |
| Near full-screen diff dialog with scope selector, search, navigation | Milestone 1, Step 3 | Covered |
| Prune mode (file/hunk/line selection, preview, apply confirmation) | Milestone 2, Steps 4–5 | Covered |
| Prune auditability via run events + activity timeline | Milestone 2, Steps 4–5 (PRUNE_APPLIED event) | Covered |
| Test execution with pass/fail summary and collapsible logs | Milestone 2, Steps 6–7 | Covered |
| "Use Agent to Fix Tests" dispatching agent work | Milestone 5, Step 7 | Covered |
| Back merge with confirmation modal and impact summary | Milestone 3, Steps 8–9 | Covered |
| Conflict resolver with keep-ours/keep-theirs/manual per block | Milestone 4, Steps 8–9 | Covered |
| "Use Agent to Resolve Conflicts" dispatching agent work | Milestone 5, Step 9 | Covered |
| Merge readiness bar with gate statuses, disabled when unmet | Milestone 6, Step 10 | Covered |
| "Commit Merge Back" only enabled when all gates pass | Milestone 6, Step 10 | Covered |
| Branch history timeline with per-commit diff | Milestone 7, Step 11 | Covered |
| Task cards with per-task file attribution and task-scoped diffs | Milestone 7, Step 11 | Covered |
| Backend endpoints for all review operations | Steps 1, 4, 6, 8, 10 | Covered |
| Playwright E2E tests for every major workflow | Step 12 (batched) | Covered |
| Playwright visual regression tests | Step 12 | Covered |
| All existing tests continue to pass | Verification criteria in every step | Covered |
| `uv run pre-commit run --all-files` passes | Each step's verification criteria | Covered |

### Key Design Decisions (Clarifications ↔ Plan ↔ Architecture)

All six clarifications from `clarifications.md` are reflected consistently across `intent.md`, `plan.md`, and `architecture.md`:

| Clarification | Intent | Plan | Architecture | Step Files |
|---|---|---|---|---|
| Q1: Agent backend — default run's agent, Advanced toggle for override | Key Design Decisions §3 | Key Decisions table row "Agent assist dispatch" | §Resolved Decisions #2 | Steps 7, 9 (modal descriptions) |
| Q2: Test command source — routine's auto_verify | Key Design Decisions §4 | Key Decisions table row "Test command source" | §Resolved Decisions #3 | Step 6 (test runner accesses auto_verify) |
| Q3: Merge strategy — user choice, default squash | Key Design Decisions §5 | Key Decisions table row "Merge strategy" | §Resolved Decisions #4 | Step 10 (confirmation modal with strategy picker) |
| Q4: Tab availability — any status if worktree exists | Key Design Decisions §2 | Key Decisions table row "Tab availability" | §Resolved Decisions #1 | Step 2 (tab visibility condition) |
| Q5: Task-level file attribution — file under every task | Key Design Decisions §7 | Key Decisions table row "Task-level file attribution" | §Resolved Decisions #6 | Step 11 (TaskFilesPanel) |
| Q6: Back merge — auto-commit clean + undo banner | Key Design Decisions §6 | Key Decisions table row "Back merge behavior" | §Resolved Decisions #5 | Steps 8–9 (BackMergeBanner with undo) |

**Result: No misalignment found between intent, plan, and clarifications.**

---

## 2. Plan ↔ Step Files Alignment

Each of the 12 plan steps was checked against its corresponding step-plan file (`step-XX-plan.md`) and step execution file (`steps/step-XX.md`).

### Step-by-Step Alignment

| Step | Plan Description | Step-Plan Covers It | Execution File Covers It | Aligned |
|---|---|---|---|---|
| 1 | Backend diff endpoints + branch status enhancements | Yes — diff_ops.py, review models, schemas, router, branch status enhancement | Yes — 7 tasks covering all deliverables | Yes |
| 2 | Frontend Review & Merge tab skeleton + branch status panel | Yes — ReviewMergeTab, BranchStatusSection, FileListSection, API client, hooks | Yes — 5 tasks covering all deliverables | Yes |
| 3 | Diff dialog with react-diff-view | Yes — DiffViewer, DiffDialog, inline/split toggle, scope switching | Yes — 4 tasks covering all deliverables | Yes |
| 4 | Backend prune endpoints | Yes — prune_ops.py, preview/apply/revert, PRUNE_APPLIED event | Yes — 5 tasks covering all deliverables | Yes |
| 5 | Frontend prune mode | Yes — PruneModeProvider, PruneGutter, PruneToolbar, PrunePreviewModal | Yes — 4 tasks covering all deliverables | Yes |
| 6 | Backend test execution endpoint | Yes — test_runner.py, POST/GET test endpoints, events | Yes — 4 tasks covering all deliverables | Yes |
| 7 | Frontend test panel + agent fix tests | Yes — TestPanel, TestLogsDrawer, AgentFixTestsModal | Yes — 4 tasks covering all deliverables | Yes |
| 8 | Backend conflict resolution endpoints | Yes — conflict_ops.py, enhanced back_merge, revert, events | Yes — 5 tasks covering all deliverables | Yes |
| 9 | Frontend back merge + conflict resolver | Yes — BackMergeModal, BackMergeBanner, ConflictResolverDialog, AgentResolveConflictsModal | Yes — 4 tasks covering all deliverables | Yes |
| 10 | Merge readiness gating + final merge | Yes — merge-readiness endpoint, MergeReadinessBar, strategy picker | Yes — 4 tasks covering all deliverables | Yes |
| 11 | Branch history + task file attribution | Yes — HistoryPanel, TaskFilesPanel, commit badges, task-scoped diffs | Yes — 3 tasks covering all deliverables | Yes |
| 12 | Visual polish + edge states + keyboard shortcuts + visual regression | Yes — empty states, binary files, large diffs, shortcuts, Playwright visual tests, docs update | Yes — 5 tasks covering all deliverables | Yes |

### Dependency Chain Validation

The plan declares this dependency chain:

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

**Verified:** Each step-plan file's "Prerequisites" section matches the dependency chain above. No circular dependencies or missing prerequisites found.

**Parallelization opportunities:**
- Steps 4, 6, 8 are independent backend steps — can run in parallel after Step 1
- Step 11 can start as soon as Steps 2 and 3 complete (independent of Steps 4–10)

**Result: Step files fully align with plan. No missing steps or deliverables.**

---

## 3. Dry Run Gaps Analysis

The dry run (`dry-run-notes.md`) identified 32 gaps (G-01 through G-32). This section categorizes each gap's status.

### High-Severity Gaps (7 total)

| ID | Gap | Resolution Status |
|---|---|---|
| G-04 | RunDetail.tsx has no tab system — must be built from scratch | **Tracked.** Step 2 execution file Task 5 explicitly describes creating the tab system. Dry run's remediation is incorporated: "Create a tab bar with 'Overview' and 'Review & Merge' tabs." |
| G-08 | Hunk/line-level prune algorithm unspecified | **Tracked.** Step 4 execution file Task 3 describes the reverse-patch algorithm. The dry run's detailed algorithm specification (construct reverse patch, `git apply --reverse --cached`, adjust hunk headers for line-level) serves as agent guidance. |
| G-12 | Test runner doesn't specify how to access auto_verify commands | **Tracked.** Step 6 execution file Task 1 references sourcing commands from the routine's auto_verify config. The dry run's model traversal guidance (load run → get routine → access auto_verify.items) provides the needed specificity. |
| G-15 | No ad-hoc agent dispatch mechanism exists for review actions | **Tracked.** Identified as a cross-cutting gap (also G-31). Steps 7 and 9 execution files describe the agent modals. The dry run recommends creating a generic `POST /review/agent-dispatch` endpoint. This must be implemented as the first backend task in Step 7. |
| G-17 | back_merge() behavior change breaks existing callers | **Tracked.** Step 8 execution file Task 2 describes enhancing back_merge() with backward-compatible changes. Dry run's recommended approach (add `abort_on_conflict` parameter or create a new function) is the expected implementation path. |
| G-29 | Async vs sync git subprocess calls — inconsistent pattern | **Tracked.** Identified as cross-cutting. Step 1 creates new async diff_ops.py, establishing the pattern. Steps 4 and 8 follow. The dry run recommends deciding on `_run_git_async()` or `asyncio.to_thread()` in Step 1 and reusing. |
| G-31 | Agent dispatch for review actions needs new backend mechanism | **Tracked.** Same as G-15. Steps 7 and 9 both need this. Must be addressed in Step 7's backend work before the frontend agent modals can function. |

### Medium-Severity Gaps (14 total)

| ID | Gap | Resolution Status |
|---|---|---|
| G-01 | `_run_git()` is sync, not async | **Addressed** via G-29 (async pattern in Step 1) |
| G-02 | `predicted_conflict_count` needs domain + schema changes | **Tracked.** Step 1 Task 5 covers both layers. |
| G-05 | Playwright E2E test setup not described in Step 2 | **Tracked.** Batched in Step 12 per dry run recommendation (G-32 option A). |
| G-06 | `unidiff` npm package may not exist; react-diff-view has built-in `parseDiff` | **Tracked.** Step 3 Task 1 should evaluate react-diff-view's built-in parser first. Agent should verify at install time. |
| G-09 | `preview_prune()` risk with `git stash` | **Tracked.** Step 4 execution file describes preview as a dry-run computation without modifying the worktree. |
| G-11 | react-diff-view custom gutter API version-dependent | **Tracked.** Step 5 Task 2 describes gutter implementation. Agent must check installed version's API. |
| G-18 | File path in URL for conflict resolution needs `{file_path:path}` converter | **Tracked.** Step 8 Task 4 should use FastAPI's path converter. |
| G-19 | `git revert` on merge commit requires `-m 1` | **Tracked.** Step 8 Task 2 describes revert-back-merge. Must use `git revert --no-edit -m 1 <sha>`. |
| G-20 | Existing `useBackMerge()` hook returns void, review needs response data | **Tracked.** Step 9 creates new review-specific hooks in useReview.ts. |
| G-22 | `merge_back()` already has strategy parameter | **Tracked.** Step 10 Task 1 should verify existing signature sufficiency rather than re-adding it. |
| G-23 | "no active jobs" gate needs centralized job registry | **Tracked.** Step 10 Task 1 (compute_readiness) must check both AgentExecutor and TestRunner. |
| G-25 | Task commit range availability for file attribution | **Tracked.** Step 11 uses task start_commit/end_commit from the run detail API. |
| G-27 | Playwright visual regression needs seeded test environment | **Tracked.** Step 12 Task 5 must include fixture setup. |
| G-30 | ReviewService vs direct git ops calls inconsistency | **Tracked.** Dry run recommends option B (direct calls, simpler). Architecture doc should be updated to reflect this if no ReviewService is created. |

### Low-Severity Gaps (11 total)

| ID | Gap | Resolution Status |
|---|---|---|
| G-03 | Existing branch status tests may break with new fields | **Mitigated** — use default values for new fields |
| G-07 | react-diff-view CSS import needed | **Tracked** — agent task during Step 3 |
| G-10 | PRUNE_APPLIED event dataclass fields unspecified | **Tracked** — Step 4 Task 4 |
| G-13 | In-memory test run tracking doesn't survive restart | **Accepted** as v1 limitation |
| G-14 | In-memory tracking doesn't support multi-worker | **Accepted** as v1 limitation |
| G-16 | ANSI color support in test logs needs library | **Tracked** — Step 7 Task 2 |
| G-21 | Manual Selection in conflict resolver needs textarea | **Tracked** — Step 9 Task 3 |
| G-24 | "tests_pass" gate behavior when no tests run | **Tracked** — treat as pass with explanation |
| G-26 | Badge detection by commit message is fragile | **Accepted** as v1 limitation |
| G-28 | ARCHITECTURE.md update must check current file state | **Tracked** — Step 12 Task 4 |
| G-32 | Playwright E2E tests batched in Step 12, not per-step | **Accepted** — each step verifies via unit/integration tests |

---

## 4. Cross-Cutting Concern Summary

| Concern | Steps Affected | Status |
|---|---|---|
| Async git subprocess pattern | 1, 4, 8 | **Tracked** (G-29). Decided in Step 1, reused in 4 and 8. |
| Ad-hoc agent dispatch mechanism | 7, 9 | **Tracked** (G-15, G-31). Must be built in Step 7 backend before frontend can use it. |
| ReviewService vs direct calls | 1, 4, 6, 8, 10 | **Tracked** (G-30). Recommend direct calls (option B). |
| Playwright E2E test strategy | 2–11, 12 | **Tracked** (G-32). Batched in Step 12; each step has unit/integration tests. |
| Tab system creation | 2 | **Tracked** (G-04). Must be built from scratch in Step 2. |
| Backward compatibility of back_merge() | 8 | **Tracked** (G-17). Requires careful parameter addition or new function. |

---

## 5. Conflict Check

No unresolved critical conflicts remain between artifacts:

- **Intent ↔ Plan:** Full coverage of all "Definition of Complete" items. All "In Scope" features have corresponding milestones and steps.
- **Intent ↔ Clarifications:** All six Q&A resolutions from `clarifications.md` are reflected in the intent's "Key Design Decisions" section.
- **Plan ↔ Architecture:** The architecture document's "Proposed Changes" section enumerates every new backend module, frontend component, and API endpoint described in the plan. API route table matches plan steps.
- **Plan ↔ Step Files:** Each step-plan and execution file maps 1:1 to a plan implementation step. Deliverables, prerequisites, and verification criteria are consistent.
- **Dry Run ↔ Step Files:** All 7 high-severity gaps have been acknowledged and have clear remediation paths. No gap blocks execution — each has a concrete fix that can be applied during implementation.
- **Architecture ↔ Step Files:** Every new/modified file listed in the architecture document appears in at least one step execution file's file modifications list.

### Out-of-Scope Items Verified

The following items are confirmed out of scope (not in any step file, matching intent):

- Full code editing IDE in browser
- Commit history rewriting (rebase/squash/amend)
- Multi-user collaborative editing
- Binary file conflict resolution beyond keep-ours/keep-theirs
- Configurable test profiles (v1 uses single default)

---

## 6. Risks and Recommendations

### Implementation Risks

| Risk | Severity | Mitigation |
|---|---|---|
| react-diff-view API compatibility across versions | Medium | Verify API at install time (Step 3). Pin exact version in package.json. |
| Hunk/line-level prune correctness | High | Thorough unit tests with edge cases (Step 4). Test with multi-hunk files, adjacent changes, empty hunks. |
| Ad-hoc agent dispatch design | High | Design the mechanism early in Step 7. Keep it simple — a generic endpoint accepting a prompt string. |
| back_merge() backward compatibility | Medium | Add `abort_on_conflict` parameter with default `True`. Existing callers unaffected. |
| Large diff performance | Medium | Deferred to Step 12 (lazy rendering). Acceptable for v1 with reasonable file counts. |

### Recommendations

1. **Decide async pattern early** (Step 1): Choose between `_run_git_async()` with `asyncio.create_subprocess_exec` or `asyncio.to_thread()` wrapping sync calls. Document the decision in the Step 1 implementation.
2. **Build agent dispatch before frontend agent modals** (Step 7): The `POST /review/agent-dispatch` or equivalent endpoint is a prerequisite for both the test-fix and conflict-resolve agent modals.
3. **Use react-diff-view's built-in `parseDiff`** (Step 3): Evaluate before installing a separate diff parser library.
4. **Pin merge commit revert to `-m 1`** (Step 8): This is a subtle git requirement; missing it will cause `git revert` to fail on merge commits.
5. **Update architecture.md if ReviewService is omitted** (Step 1+): If the review router calls git ops directly (recommended simpler approach), update the architecture doc to reflect that instead of mentioning a `ReviewService` class.

---

## 7. Verdict

**All artifacts are aligned and ready for execution.**

- Intent fully covered by plan (all DoC items mapped to steps)
- Plan fully covered by step-plan and step-execution files (12 steps, all deliverables present)
- All 6 clarification resolutions consistently reflected across intent, plan, architecture, and step files
- All 32 dry-run gaps have been categorized — 7 high, 14 medium, 11 low — with concrete remediations tracked
- No unresolved critical conflicts between any pair of artifacts
- Dependency chain validated with no circular dependencies
- Out-of-scope items verified as absent from step files

The workbench implementation can proceed to Stage 8 (Final Plan Review) and then Stage 9 (Execution).
