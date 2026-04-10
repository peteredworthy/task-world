# Frontend-Gaps Execution Summary

## Intent Satisfaction

The frontend-gaps plan closes all **21 identified frontend gaps** (plus 1 deferred new gap from human feedback) in the orchestrator web UI. Upon completion, all four user story journeys will be fully executable through the web UI:

- **Happy Path** — successful run from creation to completion
- **Revision Loop** — multi-attempt build, verify, revise cycle
- **Human-in-the-Loop** — user approvals, clarifications, guidance
- **Long-Running Run** — monitoring and branch management

**Definition of Complete:**

- All 3 HIGH gaps closed (story-blocking)
- All 8 MEDIUM gaps closed (story-degrading)
- All 10 LOW gaps closed (friction/polish)
- No TypeScript errors (`tsc --noEmit` passes)
- Existing functionality unbroken
- Pre-commit linting passes

## Ordered Step List with Task Counts

| Step | Milestone | Gaps Addressed | Focus Area | Tasks |
|------|-----------|----------------|------------|-------|
| 1 | HIGH | Gap 1 | Step-level approval UI | 4 |
| 2 | HIGH | Gaps 2–3 | Branch status + back-merge | 6 |
| 3 | MEDIUM | Gaps 4, 7–8 | Merge strategy, clarification context, gate types | 6 |
| 4 | MEDIUM | Gaps 5–6, 9 | Attempt cost, auto-verify output, step progress text | 5 |
| 5 | MEDIUM | Gaps 10–11 | History page + live guidance | 3 |
| 6 | LOW | Gaps 12–14 | Routine detail, agents flow, revision visualization | 4 |
| 7 | LOW | Gaps 15–17 | Grade threshold, blocked state, elapsed time | 6 |
| 8 | LOW | Gaps 18–21 | Validation, env files, transitions, dashboard WebSocket | 9 |

**Total: 43 atomic tasks across 8 steps, covering 21 gaps.**

### Dependency Order

- Steps 1, 4, 5, 6, 7 have no inter-step dependencies and can run in parallel.
- Step 2 is a root step (no dependencies).
- Step 3 depends on Step 2 (BackMergeDialog must exist first).
- Step 8 is independent but should ideally follow Steps 1–7 for integration testing.

## Key Decisions

Seven design questions were resolved during planning (all marked with `[HUMAN]` indicating human-reviewed):

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| Q1 | Step approval modal | Separate `StepApprovalModal` component | Different API endpoint, no reject flow, cleaner separation from existing ApprovalModal |
| Q2 | Branch status refresh | Fetch on load + WebSocket event-driven | Avoids expensive git polling; refreshes only on state changes |
| Q3 | History page | Dedicated page replacing the stub | Reuses RunCard components; cleaner than enhancing Dashboard |
| Q4 | Dashboard real-time | Dashboard-level WebSocket/SSE aggregate channel | Single connection for all runs; may need new backend endpoint |
| Q5 | Env file UI | Config area with CreateRunModal overrides | Base templates in settings, per-run overrides during creation |
| Q6 | Auto-verify output | Collapsible code block in ActivityFeed | Collapsed by default, expandable inline |
| Q7 | Attempt timeline viz | Flat list with visual connectors | Lowest effort while adding meaningful visual flow between attempts |

## Risks and Mitigations

| Risk | Affected Step | Severity | Mitigation |
|------|---------------|----------|------------|
| Branch status endpoint (`GET /api/runs/{id}/branch-status`) not confirmed | 2 | Medium | Derive from run detail metadata if endpoint missing |
| Routine validation endpoint (`POST /api/routines/validate`) not confirmed | 8 | Low | Client-side YAML parsing fallback |
| Dashboard aggregate WebSocket endpoint missing | 8 | Low | Fall back to 10s polling (existing behavior) |
| Env file template endpoint for global templates missing | 8 | Low | Run-scoped only for MVP; defer global templates |

No critical blockers exist. All gaps have documented fallback strategies. The dry-run simulation confirmed these mitigations are viable.

## Caveats for Execution

1. **Design-Question UI (Gap 22)** — A new gap surfaced from human feedback requiring a question schema, backend endpoint, and new frontend component. This is deferred and tracked in CONFLICTS.md as future work.

2. **No Automated Regression Testing** — The project has no Vitest infrastructure. Verification relies on `npx tsc --noEmit` for type safety, `uv run pre-commit run --all-files` for linting, and manual browser testing for critical flows.

3. **Env File Templates Scope** — Backend may only support run-scoped endpoints, not template-level CRUD. The MVP fallback is run-scoped only.

4. **Dashboard WebSocket** — May need a new backend endpoint for aggregate updates. If unavailable, the existing 10s polling serves as a graceful fallback.

5. **Graceful Degradation Points** — Several components are designed to degrade gracefully when backend data is unavailable:
   - Clarification context missing → skip rendering
   - Gate type missing → generic "gate" badge
   - Grade threshold unavailable → generic "Verification failed" message
   - Navigation state loss (agent pre-fill) → modal opens without pre-fill
   - Auto-verify output unavailable → link to logs viewer

6. **Post-Execution Gates** — Every step must pass `tsc --noEmit` and pre-commit checks before proceeding to the next step.
