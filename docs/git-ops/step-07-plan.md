# Step 07 Plan: Frontend Test Panel + Agent Fix Tests

## Purpose

Implement the test execution UI and agent-assisted test fixing in the Review & Merge workbench. Users can run the routine's auto_verify commands from the workbench, view results and logs, and dispatch an agent to fix failing tests — all without leaving the review tab.

## Prerequisites

- **Step 5** — Frontend prune mode must exist, as the test panel sits alongside it in the left rail and tests are typically run after pruning.
- **Step 6** — Backend test execution endpoints must exist (`POST /review/test`, `GET /review/test/{id}`) for the frontend to call.
- Existing agent executor infrastructure for dispatching agent work against worktrees.

## Functional Contract

### Inputs

- User interactions: click "Run Tests", view test logs, click "Use Agent to Fix Tests"
- `POST /api/runs/{id}/review/test` → start test execution
- `GET /api/runs/{id}/review/test/{test_run_id}` → poll for test results
- `POST /api/runs/{id}/review/agent-fix-tests` → dispatch agent to fix failing tests (body includes optional agent override)

### Outputs

- `TestPanel` component in left rail: last run status indicator, "Run Tests" button, "View Logs" link
- `TestLogsDrawer` component: collapsible drawer with summary counts (total/passed/failed/skipped), failing test list, terminal-style log output
- `AgentFixTestsModal` component: scope description ("Fix N failing tests"), confirmation button, progress indicator; defaults to run's agent with "Advanced" toggle revealing agent picker for override
- After agent completion: diff and test status auto-refresh via TanStack Query invalidation
- TanStack Query hooks: `useRunTests()`, `useTestResult()` (polling), `useAgentFixTests()`

### Errors

- Test execution fails to start → error toast with reason
- Agent dispatch fails → error message in modal
- Test result polling timeout → "Test run timed out" status display
- No auto_verify commands configured → "No test commands configured" message, run button disabled

## Tasks

1. Create `ui/src/components/review/TestPanel.tsx` — left rail section with status indicator and run button
2. Create `ui/src/components/review/TestLogsDrawer.tsx` — collapsible log viewer with summary and terminal output
3. Create `ui/src/components/review/AgentFixTestsModal.tsx` — agent dispatch modal with default agent + Advanced override toggle
4. Add TanStack Query hooks to `useReview.ts`: `useRunTests()` mutation, `useTestResult()` polling query, `useAgentFixTests()` mutation
5. Add API client functions to `reviewClient.ts`: `runTests()`, `getTestResult()`, `agentFixTests()`
6. Wire TestPanel into ReviewMergeTab left rail
7. Implement post-agent auto-refresh (invalidate diff files, test results on agent completion)
8. Write Playwright tests: run tests, view logs, trigger agent fix, verify post-agent state

## Verification

### Auto-Verify

- [ ] Playwright test `test_run_tests` — execute tests, verify results display, log viewer works
- [ ] Playwright test `test_agent_fix_tests` — dispatch agent fix, verify post-agent state updates
- [ ] `npx tsc --noEmit` — no TypeScript errors
- [ ] `npm run build` — frontend builds

### Manual Verify

- [ ] "Run Tests" button triggers test execution and shows running indicator
- [ ] Test results display pass/fail summary with counts
- [ ] Log viewer shows full test output in terminal-style formatting
- [ ] "Use Agent to Fix Tests" modal defaults to run's agent
- [ ] Advanced toggle reveals agent picker with available agent backends
- [ ] After agent completion, diff viewer and test results refresh automatically
- [ ] Button is disabled with explanation when no auto_verify commands are configured

## Context & References

- `ui/src/components/review/ReviewMergeTab.tsx` — parent component for test panel placement
- `src/orchestrator/agents/executor.py` — agent executor pattern for agent dispatch
- `docs/git-ops/clarifications.md` — Q1: agent defaults to run's agent with Advanced toggle; Q2: test commands from auto_verify
- `docs/git-ops/architecture.md` — TestPanel, TestLogsDrawer, AgentFixTestsModal specs
