# Execution Summary: Bug and Gap Removal

**Date**: 2026-02-19
**Status**: Ready for Implementation
**Prepared from**: `intent.md`, `plan.md`, `architecture.md`, `clarifications.md`, `dry-run-notes.md`, `verification-report.md`, step plan files (01–12), step execution task files (01–12)

---

## Intent Satisfaction Summary

The original request asked for removal of all 10 bugs and UI gaps identified in `docs/bugs/`. The plan addresses every identified issue:

| Bug / Gap ID | Addressed By | Approach |
|---|---|---|
| AGENT-DEATH-HUMAN-GATE | Steps 1 + 2 | Re-raise `GateBlockedError` in `cli.py`; catch in `executor.py`; rewrite no-op gate prompts in `idea-to-plan.yaml` |
| FAILED-RUN-RECOVERY | Steps 3 + 4 | `POST /api/runs/{id}/recover` backend + `RecoveryPanel` frontend |
| MCP-TOOLS-NO-PHASE-FILTERING | Step 5 | Phase-aware tool filtering at MCP server initialization |
| UI-STEP-APPROVAL | Step 6 | `approveStep` client + `useApproveStep` + `StepApprovalBanner` |
| UI-AGENT-GUIDANCE-PANEL | Step 7 | `agentStarted`/`agentCancelled`/`getGuidance` client + hooks + panel rewrite |
| UI-BACKWARD-TRANSITIONS | Step 8 | `transitionBack` client + `useTransitionBack` + revert UI in step timeline |
| UI-BRANCH-STATUS | Step 9 | `getBranchStatus`/`backMerge` client + hooks + `BranchStatusPanel` |
| UI-ENV-FILE-MANAGEMENT | Step 10 | 5 client functions + 5 hooks + `EnvFilesPanel` |
| UI-GLOBAL-CONFIG | Step 11 | `getConfig` + `GlobalConfig` type + `useGlobalConfig` + settings panel section |
| UI-ROUTINE-VALIDATION | Step 12 | `validateRoutine` + `useValidateRoutine` + `RoutineValidatorModal` |

All 10 bug/gap IDs are fully covered. No intent item is deferred, dropped, or partially addressed (except the out-of-scope items explicitly noted in `intent.md`).

**Definition of Complete alignment**: All 14 criteria in `intent.md` §Definition of Complete map directly to deliverables in the step execution files. TypeScript and Python static analysis gates are embedded in the per-step verification criteria.

---

## Ordered Step List with Task Counts

**Total**: 12 steps, 34 tasks

| Step | Title | Bug / Gap | Tasks | Milestone | Prerequisites |
|------|-------|-----------|-------|-----------|---------------|
| 1 | Fix GateBlockedError Handling (Backend) | AGENT-DEATH-HUMAN-GATE | 3 | 1 — Backend Agent Reliability | None |
| 2 | Rewrite Human Gate Task Prompts (Routine) | AGENT-DEATH-HUMAN-GATE | 2 | 1 — Backend Agent Reliability | Step 1 |
| 3 | Implement Failed-Run Recovery API | FAILED-RUN-RECOVERY | 4 | 1 — Backend Agent Reliability | None |
| 4 | Add Recovery UI | FAILED-RUN-RECOVERY | 4 | 1 — Backend Agent Reliability | Step 3 |
| 5 | Phase-Aware MCP Tool Filtering | MCP-TOOLS-NO-PHASE-FILTERING | 3 | 2 — MCP + High-Severity UI | None |
| 6 | Wire Step-Level Human Approval UI | UI-STEP-APPROVAL | 3 | 2 — MCP + High-Severity UI | None |
| 7 | Wire AgentGuidancePanel Lifecycle Hooks | UI-AGENT-GUIDANCE-PANEL | 3 | 3 — Medium-Severity UI | None |
| 8 | Add Backward Step Transition UI | UI-BACKWARD-TRANSITIONS | 2 | 3 — Medium-Severity UI | None |
| 9 | Branch Status Panel and Back-Merge | UI-BRANCH-STATUS | 3 | 3 — Medium-Severity UI | None |
| 10 | Env File Management UI | UI-ENV-FILE-MANAGEMENT | 3 | 4 — Low-Severity UI | None |
| 11 | Surface Server GlobalConfig | UI-GLOBAL-CONFIG | 3 | 4 — Low-Severity UI | None |
| 12 | Routine YAML Validation UI | UI-ROUTINE-VALIDATION | 3 | 4 — Low-Severity UI | None |

### Task Breakdown by Milestone

- **Milestone 1** (Steps 1–4): 13 tasks — backend agent reliability + run recovery
- **Milestone 2** (Steps 5–6): 6 tasks — MCP phase filtering + step approval UI
- **Milestone 3** (Steps 7–9): 8 tasks — medium-severity UI gaps
- **Milestone 4** (Steps 10–12): 9 tasks — low-severity UI gaps (env files, config, routine validation)

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| GateBlockedError handling location | Re-raise in `cli.py`; catch in `executor.py` | Executor is single authority on task lifecycle; `cli.py` stays thin |
| Recovery endpoint starting status | FAILED only; COMPLETED remains terminal | COMPLETED recovery deferred to follow-up; common case stays simple |
| Recovery checklist reset default | Reset to open by default; `preserve_checklist: true` flag to override | Avoids stale state; flag enables fast recovery when builder work was valid |
| Recovery target parameter | `target_task_id` required; `target_step_id` inferred | Tasks are the atomic unit; step is always derivable from task |
| MCP phase filtering approach | Server-side `phase` parameter at initialization (Option A) | Single MCP endpoint; no separate filtered endpoints; simpler agent config |
| `StepTimeline.tsx` gap remediation | Step 8 agent must choose: create from scratch or implement inline in existing step renderer | Dry-run confirmed file is absent; two valid paths documented |
| Frontend client API pattern | Extend existing `api` object (or export individual functions alongside it, consistently) | Decision deferred to Step 4 agent; must be applied uniformly across Steps 4–12 |
| Routine YAML validation UI placement | Modal accessible from `RoutineSelector` or `CreateRunModal` | Minimizes new routes; validation naturally precedes run creation |
| Frontend gap priority order | Step approval (Step 6) → guidance panel (Step 7) → backward transitions (Step 8) → branch status (Step 9) → env files (Step 10) → config (Step 11) → routine validation (Step 12) | Most-urgent user-blocking issues addressed first |

---

## Risks and Mitigations

### Critical Risks

| Risk | Affected Steps | Mitigation |
|------|---------------|-----------|
| `StepTimeline.tsx` does not exist | Step 8 | Before T2, agent must search for existing step renderer (likely `StepProgressBar` in `RunDetail.tsx`) and either create `StepTimeline.tsx` from scratch or implement revert UI inline. Documented in `dry-run-notes.md` §Step 8. |
| Step 2 gate prompts deployed before Step 1 GateBlockedError fix | 1 → 2 | Deploy Step 1 first. Actionable prompts alone are insufficient if agents still die on `GateBlockedError`. |

### High-Priority Risks

| Risk | Affected Steps | Mitigation |
|------|---------------|-----------|
| `client.ts` uses object pattern (`api.methodName()`) instead of individual exports assumed in plan snippets | Steps 4–12 | Step 4 agent establishes the pattern; all subsequent steps must follow consistently. Two valid options: extend `api` object or export individual functions. |
| `executor.py` already handles `GateBlockedError` but at wrong level (`_run_agent_loop` not `_execute_task`) | Step 1 | Confirm catch location before modifying. Move only if at wrong level. |
| `end_commit` field may be absent on attempt records | Step 3 | Fall back to `source_branch` HEAD if `end_commit` is not stored. |
| Frontend schema drift (TypeScript types diverge from backend response shapes) | Steps 4, 6, 7, 9, 10, 11, 12 | Agents must read backend handler/schema before implementing TypeScript types. Do not infer types from plan descriptions alone. |

### Medium-Priority Risks

| Risk | Affected Steps | Mitigation |
|------|---------------|-----------|
| `ConfirmationDialog` component may not exist | Steps 4, 8, 10 | Verify existence before referencing. If absent, create shared component first or adapt to available dialog primitive. |
| `ui/src/components/detail/` directory may not exist | Steps 4, 6, 9, 10 | Step 4 agent (first to create files there) must create the directory. |
| YAML field name in `idea-to-plan.yaml` differs from plan expectation | Step 2 | Verify actual field name before editing. Validate YAML after each change with `python -c "import yaml; yaml.safe_load(...)"`. |
| FastMCP tool registration API differs from plan assumptions | Step 5 | Read `server.py` before implementing. Check for `@tool` decorator vs. `add_tool()` call pattern. |
| `usePendingActions` endpoint may already return aggregated count (not raw step array) | Step 6 | Read `getPendingActions` endpoint response schema before deciding whether to filter client-side or use server count. |
| `useTaskPrompt` used by other components besides `AgentGuidancePanel` | Step 7 | Grep all usages before removing. |

### Low-Priority Risks

| Risk | Affected Steps | Mitigation |
|------|---------------|-----------|
| TypeScript types added in isolation lack a shared re-export index | Steps 4, 7, 9–12 | Maintain `ui/src/types/index.ts` as types accumulate across steps. |
| 30s polling in `useBranchStatus` creates flaky Vitest tests | Step 9 | Use `vi.useFakeTimers()` or mock `useBranchStatus` in tests. |
| `copyBackPath` initializes to empty string when no default target exists | Step 10 | Allow manual path input in the copy-back dialog, or pre-populate from a sensible fallback. |
| Settings panel may not exist as a standalone component | Step 11 | Search for settings-related components before deciding where to add the "Server" section. |
| Routine validate endpoint path may be singular (`/api/routine/validate`) | Step 12 | Verify exact path in backend before implementing client function. |

### Execution Order Risks

| Scenario | Steps | Mitigation |
|---|---|---|
| Step 4 UI deployed before Step 3 backend | 3 → 4 | Deploy backend first. UI must degrade gracefully when endpoint is absent. |
| Step 5 T1 (phase param) deployed before T2 (executor passes phase) | 5-T1 → 5-T2 | Safe by design: default `"building"` gives all connections builder tools during the gap window. |
| Multiple steps modifying `client.ts` and `useApi.ts` concurrently | Steps 4–12 | Serialize steps or use a feature-branch merge strategy to avoid conflicts in shared files. |

---

## Caveats for Execution

### General

1. **Read before implementing.** Every step that modifies an existing file (especially `client.ts`, `useApi.ts`, `runs.py`, `server.py`) must be read in full before any edits are made. Plan code snippets are illustrative, not literal.

2. **Static analysis gates are non-negotiable.** All new backend code must pass `uv run pyright` and `uv run ruff check .`. All new frontend code must pass `tsc --noEmit`. Per-step verification criteria are listed in `dry-run-notes.md` §Verification Checkpoint Summary.

3. **Tasks must remain atomic.** No task should touch more than 5 files or 500 lines. If a task expands beyond this, split it.

4. **System must remain runnable after every task commit.** Do not leave the system in a broken intermediate state between tasks.

### Step-Specific Caveats

5. **Step 1**: Confirm whether `except GateBlockedError: raise` already exists in `cli.py` `execute()` before adding it. If already present, mark T1 done after verifying—do not add a duplicate clause.

6. **Step 2**: Use `|` block scalar syntax for multi-line YAML replacements. Validate with `yaml.safe_load` after each edit. Preserve `{{feature}}` template variables verbatim—do not collapse double braces.

7. **Step 3**: The recovery endpoint returns 409 for **all** non-FAILED statuses (ACTIVE, PAUSED, COMPLETED, PENDING), not just COMPLETED. Integration tests must cover all cases. COMPLETED run recovery is explicitly out of scope per Clarification #1.

8. **Step 5**: The `"building"` default on the `phase` parameter ensures backward compatibility during deployment. Tasks T1 and T2 should not be combined into a single commit if deployment order matters.

9. **Step 8**: This step has a **critical pre-condition**: `StepTimeline.tsx` does not exist. Before beginning T2, search for the current step renderer in `RunDetail.tsx` (look for `run.steps.map` or `StepProgressBar`). Choose one of: (a) create `StepTimeline.tsx` from scratch with full props interface, or (b) implement revert UI inline in the existing renderer. Update Vitest test paths accordingly.

10. **Steps 4–12 (frontend)**: The existing `client.ts` uses an `api` object pattern. The pattern established in Step 4 must be followed consistently in all subsequent steps. Do not mix individual exports and object methods.

11. **Security (Step 10)**: Env file values must never appear unmasked in component state, logs, or rendered output. Only `masked_value` is safe to display. The backend provides masking guarantees; the frontend must not request or expose raw values.

12. **Step 11**: `useGlobalConfig` with `staleTime: Infinity` will not refetch between test cases if a shared QueryClient is used. Vitest tests must create a fresh QueryClient per test to avoid state leakage.

---

## Out-of-Scope Items (for Reference)

The following were explicitly excluded from this initiative and should not be implemented as part of these steps:

- Rewriting the routine YAML schema or executor architecture
- Adding new routine steps or changing `idea-to-plan.yaml` beyond S-02/S-08 prompt fixes
- OpenHands or Codex-specific agent fixes (changes target shared `cli.py` / MCP layer only)
- File/output viewer for worktree artifacts (noted in AGENT-DEATH-HUMAN-GATE docs but outside scope)
- Question/answer UI for design questions (noted in AGENT-DEATH-HUMAN-GATE docs but outside scope)
- COMPLETED run recovery (deferred to a follow-up; FAILED only per Clarification #1)
