# Step 7: Frontend Test Panel + Agent Fix Tests

Implement the test execution UI and agent-assisted test fixing in the Review & Merge workbench. Users can run the routine's auto_verify commands from the workbench, view results and logs, and dispatch an agent to fix failing tests.

## Intent Verification

**Original Intent**: `docs/git-ops/intent.md` — Test execution can be triggered from the workbench; results show pass/fail, summary counts, and collapsible log output. "Use Agent to Fix Tests" dispatches agent work against the run worktree and updates diff/test status on completion.

**Functionality to Produce**:
- `TestPanel` component in left rail with status indicator and run button
- `TestLogsDrawer` with summary counts, failing test list, terminal-style log output
- `AgentFixTestsModal` with default agent and Advanced override toggle
- TanStack Query hooks for test execution and polling
- Post-agent auto-refresh of diff and test data

**Final Verification Criteria**:
- "Run Tests" button triggers test execution and shows running indicator
- Test results display pass/fail summary with counts
- Log viewer shows full test output
- Agent fix modal defaults to run's agent with Advanced toggle
- After agent completion, data refreshes automatically
- TypeScript compiles and frontend builds

---

## Task 1: Create TestPanel Component

**Description**: Create the test panel section in the left rail with status indicator and run button.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/TestPanel.tsx`:
  - Last test run status indicator (green check / red X / spinner)
  - "Run Tests" button
  - "View Logs" link (opens logs drawer)
  - "Use Agent to Fix Tests" button (visible when tests fail)
  - Disabled state with message when no auto_verify commands configured

- [ ] Add API client functions to `ui/src/api/reviewClient.ts`:

```typescript
export async function runTests(runId: string): Promise<TestRunResponse> { ... }
export async function getTestResult(runId: string, testRunId: string): Promise<TestRunResult> { ... }
export async function agentFixTests(runId: string, agentType?: string, agentConfig?: object): Promise<AgentJobResponse> { ... }
```

- [ ] Add TanStack Query hooks to `ui/src/hooks/useReview.ts`:

```typescript
export function useRunTests(runId: string) { ... }  // mutation
export function useTestResult(runId: string, testRunId: string | null) { ... }  // polling query
export function useAgentFixTests(runId: string) { ... }  // mutation
```

**References**
- `docs/git-ops/step-07-plan.md` — Tasks 1, 4, 5
- `docs/git-ops/architecture.md` — TestPanel spec

**Functionality (Expected Outcomes)**
- [ ] Test panel shows current test status
- [ ] Run button triggers test execution
- [ ] Status updates as tests run

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 2: Create TestLogsDrawer Component

**Description**: Create the collapsible test logs viewer with summary counts and terminal-style output.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/TestLogsDrawer.tsx`:
  - Collapsible drawer (expandable from test panel)
  - Summary bar: total/passed/failed/skipped counts
  - Failing test names list (clickable to scroll to relevant output)
  - Terminal-style monospace log output with ANSI color support
  - Scrollable with auto-scroll to bottom on new output
  - Close button

**Dependencies**
- [ ] Task 1 must be complete (TestPanel and hooks exist)

**References**
- `docs/git-ops/step-07-plan.md` — Task 2

**Functionality (Expected Outcomes)**
- [ ] Drawer opens from test panel "View Logs" link
- [ ] Summary counts display correctly
- [ ] Log output renders in terminal-style formatting
- [ ] Drawer collapses cleanly

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 3: Create AgentFixTestsModal Component

**Description**: Create the agent dispatch modal for fixing failing tests.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/review/AgentFixTestsModal.tsx`:
  - Modal overlay with scope description ("Fix N failing tests")
  - Default: shows run's configured agent
  - "Advanced" toggle reveals agent picker dropdown for overriding agent backend
  - "Confirm" button dispatches agent
  - Progress indicator while agent is working
  - Error state if dispatch fails
  - On agent completion: invalidate diff files, test results via TanStack Query

**References**
- `src/orchestrator/agents/executor.py` — agent executor pattern
- `docs/git-ops/clarifications.md` — Q1: default to run's agent with Advanced toggle
- `docs/git-ops/step-07-plan.md` — Task 3

**Functionality (Expected Outcomes)**
- [ ] Modal defaults to run's configured agent
- [ ] Advanced toggle reveals agent picker
- [ ] Agent dispatch starts and shows progress
- [ ] On completion, diff and test data refresh

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors

---

## Task 4: Wire Test Panel into ReviewMergeTab

**Description**: Integrate the test panel, logs drawer, and agent fix modal into the ReviewMergeTab layout.

**Implementation Plan (Do These Steps)**

- [ ] Add `TestPanel` to the left rail in `ReviewMergeTab.tsx`
- [ ] Add state management for logs drawer and agent fix modal visibility
- [ ] Wire post-agent-completion auto-refresh: invalidate diff files and test result queries
- [ ] Ensure test result polling stops when component unmounts

**Dependencies**
- [ ] Tasks 1-3 must be complete

**References**
- `docs/git-ops/step-07-plan.md` — Tasks 6, 7

**Functionality (Expected Outcomes)**
- [ ] Test panel appears in left rail
- [ ] Full test flow works: run → view results → view logs → agent fix → auto-refresh

**Final Verification (Proof of Completion)**
- [ ] `cd ui && npx tsc --noEmit` — no TypeScript errors
- [ ] `cd ui && npm run build` — frontend builds without errors
