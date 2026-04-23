# UI QA Test Suite — Code Map

Maps each planned deliverable to existing source files that tests will exercise,
plus new files to be created. Line numbers reference the current codebase.

---

## Existing Source Files (test targets)

### Type Definitions (`ui/src/types/`)

All types re-exported from `ui/src/types/index.ts` (lines 1–15).

- `ui/src/types/runs.ts` — `RunResponse`, `RunListResponse`, `CreateRunRequest`, `StepSummary`, `TaskSummary`, `ModelTokenUsage`, `GradeSummaryItem`, `AttemptOutcome`: lines 1–100+
- `ui/src/types/tasks.ts` — `ChecklistItemSchema` (lines 3–11), `GradeSnapshotItem`, `ActionLogEntry`, `ActionLog`, `TurnMetrics`, `ToolUseDetail`, `ToolResultDetail`: lines 1–80+
- `ui/src/types/enums.ts` — `RunStatus`, `TaskStatus`, `ChecklistStatus`, `Priority`, `AgentRunnerType`: lines 1–8
- `ui/src/types/routines.ts` — `RoutineSummary` (lines 7–15), `RoutineDetail` (lines 17–25), `RoutineListResponse` (lines 33–35)
- `ui/src/types/activity.ts` — `ActivityEvent` (lines 1–8), `ActivityResponse` (lines 10–14), `ClarificationRequestedPayload`, `ClarificationRespondedPayload`
- `ui/src/types/clarifications.ts` — `ClarificationQuestion` (lines 1–12), `ClarificationRequest` (lines 23–31), `PendingAction` (lines 56–64)
- `ui/src/types/agents.ts`, `agentRunners.ts`, `branches.ts`, `envFiles.ts`, `config.ts`, `repos.ts`, `review.ts` — additional API types

### API Client

- `ui/src/api/client.ts` — `fetchApi<T>()` (line 132), `listRuns()`, `getRun()`, `createRun()`, `startRun()`, `pauseRun()`, `resumeRun()`, `cancelRun()`, `deleteRun()`, `getTask()`, `getActivity()`, `approveTask()`, `rejectTask()`, `respondToClarification()`: lines 1–702
- `ui/src/api/reviewClient.ts` — review-specific API calls

### React Query Hooks

- `ui/src/hooks/useApi.ts` — all query/mutation hooks (lines 1–443):
  - Queries: `useRuns()` (line 7), `useRun()` (line 22), `useRoutines()` (line 75), `useGlobalConfig()` (line 98), `useRoutine()` (line 106), `useAgentRunners()` (line 120), `useTask()` (line 129), `useActivity()` (line 138), `useTaskPrompt()` (line 151)
  - Mutations: `useCreateRun()` (line 160), `useStartRun()` (line 168), `usePauseRun()` (line 176), `useResumeRun()` (line 184), `useCancelRun()` (line 204), `useDeleteRun()` (line 294)

### WebSocket / SSE

- `ui/src/hooks/useWebSocket.ts` — `createWebSocket()` (line 17), `processEvent()` (line 69), `useRunWebSocket()` (line 127): lines 1–185
  - `ConnectionStatus` type, `MAX_RECONNECT_ATTEMPTS = 10` (line 15)
  - Handles batch messages (line 57), cache invalidation on events
- `ui/src/hooks/useActivitySSE.ts` — `useActivitySSE()` (line 13): lines 1–115
  - `MAX_BACKOFF_MS = 30000` (line 6), exponential backoff reconnect
- `ui/src/context/WebSocketContext.tsx` — `WebSocketProvider()` (line 4)
- `ui/src/hooks/useWebSocketStatus.ts` — connection status hook

### Page Components

- `ui/src/pages/Dashboard.tsx` — `Dashboard()` (line 17): uses useRuns, useRoutines, useStartRun, usePauseRun, useCancelRun, useDeleteRun, useGlobalConfig
- `ui/src/pages/History.tsx` — `History()` (line 1)
- `ui/src/pages/RoutineLibrary.tsx` — `RoutineLibrary()` (line 27): uses useRoutines, useArchiveRoutine, useUnarchiveRoutine
- `ui/src/pages/Agents.tsx` — `Agents()` (line 23): uses useQuery, useQueryClient
- `ui/src/pages/AgentRunners.tsx` — agent runner config page
- `ui/src/pages/Repos.tsx` — repository management page
- `ui/src/pages/NotFound.tsx` — 404 page

### Modal / Dialog Components

- `ui/src/components/dashboard/CreateRunModal.tsx` — `CreateRunModal()` (line 72), `CreateRunModalProps`, `FormState`, `INITIAL_FORM`: lines 1–605
  - Uses: useRepos, useAgentRunners, useCreateRun, useStartRun, useRoutine, useFocusTrap, BranchSelector, RoutineSelector, RoutineValidatorModal
- `ui/src/components/SettingsModal.tsx` — `SettingsModal()` (line 7): lines 1–60+
- `ui/src/components/RoutineValidatorModal.tsx` — `RoutineValidatorModal()` (line 18), `lineNumberFor()` (line 14): lines 1–80+
- `ui/src/components/ConfirmDialog.tsx` — `ConfirmDialog()` (line 13): lines 1–71
- `ui/src/components/detail/ApprovalModal.tsx` — `ApprovalModal()` (line 15), `renderSummary()` (line 90): lines 1–355
- `ui/src/components/detail/ClarificationModal.tsx` — `ClarificationModal()` (line 44), `AnswerMode` (line 16), `createInitialAnswers()` (line 30), `isAnswerComplete()` (line 94): lines 1–530

### Dashboard Components

- `ui/src/components/dashboard/RunCard.tsx` — `RunCard()` (line 1026), `StatusIcon()` (line 29): lines 1–1026
- `ui/src/components/dashboard/RunFilters.tsx` — `RunFilters()` (line 34): lines 1–80+
- `ui/src/components/dashboard/StepTimeline.tsx` — `StepTimeline()` (line 16): lines 1–80+
- `ui/src/components/dashboard/ActivityFeed.tsx` — `ActivityFeed()` (line 55), `eventLabel()` (line 7): lines 1–55+

### Detail Components

- `ui/src/components/detail/TaskDetailCard.tsx` — `TaskDetailCard()` (line 719), `StatusIcon()` (line 65), `CompactGradeBadges()` (line 93): lines 1–719
- `ui/src/components/detail/AttemptHistory.tsx` — `AttemptHistory()` (line 10), `getMetric()` (line 5): lines 1–58
- `ui/src/components/detail/ChecklistTable.tsx` — `ChecklistTable()` (line 83), `StatusIcon()`, `CompactGradeMarker()`: lines 1–100+
- `ui/src/components/detail/MetricsBar.tsx` — `MetricsBar()` (line 40), `estimateCost()` (line 8), `MetricCard()` (line 18): lines 1–82
- `ui/src/components/detail/ActivityFeed.tsx` — `ActivityFeed()` (line 342), `eventLabel()`, `TaskGroupCard()`: lines 1–342+

### Supporting Components

- `ui/src/components/GradeBadge.tsx` — `GradeBadge()` (line 8): lines 1–29
- `ui/src/components/ConnectionBanner.tsx` — `ConnectionBanner()` (line 8): lines 1–56
- `ui/src/components/ConnectionIndicator.tsx` — connection status indicator

### Utility Hooks

- `ui/src/hooks/useFocusTrap.ts` — focus management for modals
- `ui/src/hooks/useSettings.ts` — user settings
- `ui/src/hooks/useSettingsModal.ts` — settings modal state
- `ui/src/hooks/useCreateRunModal.ts` — create run modal state
- `ui/src/hooks/useApproval.ts` — `useApproveTask()`, `useApproveStep()`, `useRejectTask()`
- `ui/src/hooks/useClarifications.ts` — clarification hooks
- `ui/src/hooks/usePendingActions.ts` — pending actions handling

---

## Existing Test Infrastructure

### Configuration

- `ui/playwright.config.ts` — existing Playwright config, `testDir: './tests/e2e'`, `baseURL: 'http://localhost:5399'`, chromium project: lines 1–51
- `ui/vitest.config.ts` — `environment: 'jsdom'`, `include: 'src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'`, `setupFiles: './tests/setup.ts'`: lines 1–12
- `ui/tests/setup.ts` — imports `@testing-library/jest-dom/vitest`

### Existing Test Files (27 component tests + API/lib/hook tests)

- `ui/tests/api/client.test.ts`
- `ui/tests/components/` — 27 test files covering: ApprovalModal, AttemptHistory, BranchSelector, ChecklistTable, ClarificationModal, ConfirmDialog, ConnectionIndicator, ErrorBoundary, GradeBadge, Layout, RunCard, RunFilters, StepTimeline, TaskDetailCard, etc.
- `ui/tests/hooks/useFocusTrap.test.tsx`
- `ui/tests/lib/` — format, recency, status, url tests
- `ui/tests/pages/NotFound.test.tsx`
- `ui/tests/e2e/visual-regression.spec.ts` — 8 visual snapshots

### Package Dependencies (relevant)

- `@playwright/test: ^1.58.2`
- `@testing-library/react: ^16.3.2`, `@testing-library/jest-dom: ^6.9.1`, `@testing-library/user-event: ^14.6.1`
- `vitest: ^4.0.18`, `jsdom: ^28.0.0`
- `@tanstack/react-query: ^5.90.20`
- `react: ^19.2.0`, `react-router-dom: ^7.13.0`

---

## New Files to Create

### Test Infrastructure (`ui/tests/fixtures/`)

| File | Key Exports | Purpose |
|------|------------|---------|
| `factories.ts` | `buildRun()`, `buildTask()`, `buildAttempt()`, `buildStep()`, `buildRoutine()`, `buildAgent()`, `buildAgentRunner()`, `buildActivityEvent()` | Type-safe factory functions using `ui/src/types/` interfaces |
| `api-handlers.ts` | `setupApiHandlers(page, options)` | Playwright `route()` interceptors for all `/api/*` endpoints; stateful mutation handling |
| `fake-ws.ts` | `FakeWebSocket` class: `pushEvent()`, `pushBatch()`, `simulateDisconnect()`, `simulateReconnect()` | Replaces native WebSocket via `page.addInitScript()`; mirrors event types from `useWebSocket.ts` |
| `fake-sse.ts` | `FakeSSE` class: `pushEvent()`, `simulateDrop()`, `simulateReconnect()` | Controllable SSE stream for `/api/runs/{id}/activity/stream`; mirrors `useActivitySSE.ts` behavior |
| `scenarios.ts` | `activeRunScenario()`, `completedRunScenario()`, `failedTaskScenario()`, `revisionCycleScenario()` | Pre-built state configurations combining factory outputs |

### BDD Feature Files (`ui/tests/bdd/features/`)

| File | Scenarios | Traces |
|------|----------|--------|
| `dashboard.feature` | View runs, filter, search, create run, navigate to detail | [I-06], [I-07], [I-27] |
| `run-detail.feature` | View detail, step timeline, task list, pause/resume, cancel | [I-06], [I-08], [I-27] |
| `run-lifecycle.feature` | Draft → active → paused → completed; draft → active → cancelled | [I-08], [I-29] |
| `task-lifecycle.feature` | Queued → building → verifying → complete; fail → revision → pass | [I-08], [I-30] |
| `routines.feature` | Browse library, validate routine | [I-06], [I-27] |
| `agents.feature` | View agents, configure runner | [I-06], [I-27] |
| `history.feature` | View completed runs | [I-06], [I-27] |
| `settings.feature` | Open settings, toggle options | [I-07], [I-27] |
| `run-transitions.feature` | Full state transition matrix for run lifecycle (valid + invalid transitions) via Scenario Outlines | [I-08], [I-25], [I-31] |
| `task-transitions.feature` | Full state transition matrix for task lifecycle (valid + invalid transitions) via Scenario Outlines | [I-08], [I-25], [I-31] |
| `edge-state-change.feature` | Run completes during modal, task transitions during view, cancel during grading | [I-03], [I-10], [I-31] |
| `edge-dialogs.feature` | Double-click prevention, gate resolution, orphan modal cleanup | [I-07], [I-28], [I-31] |
| `edge-connection.feature` | WS disconnect/reconnect, SSE drop, API 500/404 | [I-09], [I-12], [I-31] |
| `edge-stale-data.feature` | Background WS updates, React Query invalidation | [I-09], [I-25], [I-31] |

### Step Definitions (`ui/tests/bdd/steps/`)

| File | Key Steps | Source Components Exercised |
|------|----------|---------------------------|
| `common.steps.ts` | `Given the API returns...`, `Given the WebSocket is connected`, `Given I am on the Dashboard` | api-handlers.ts, fake-ws.ts, all pages |
| `dashboard.steps.ts` | `When I click "New Run"`, `Then I should see a run card` | Dashboard.tsx, CreateRunModal.tsx, RunCard.tsx |
| `run-detail.steps.ts` | `When I click pause`, `Then the step timeline shows` | RunDetail page, StepTimeline.tsx, TaskDetailCard.tsx |
| `lifecycle.steps.ts` | `When the server sends a WebSocket event`, `Then the status badge shows` | useWebSocket.ts, useActivitySSE.ts |
| `edge-cases.steps.ts` | `When the WebSocket disconnects`, `When I double-click` | ConnectionBanner.tsx, ConfirmDialog.tsx |

### Page Objects (`ui/tests/bdd/pages/`)

| File | Class | Key Methods | Wraps Components |
|------|-------|------------|-----------------|
| `dashboard.page.ts` | `DashboardPage` | `goto()`, `getRunCards()`, `clickCreateRun()`, `filterByStatus()`, `searchRuns()` | Dashboard.tsx, RunCard.tsx, RunFilters.tsx |
| `run-detail.page.ts` | `RunDetailPage` | `goto(id)`, `getStepTimeline()`, `getTaskCards()`, `clickPause()`, `clickResume()`, `clickCancel()` | RunDetail, StepTimeline.tsx, TaskDetailCard.tsx, MetricsBar.tsx |
| `routines.page.ts` | `RoutinesPage` | `goto()`, `getRoutineList()`, `clickValidate()` | RoutineLibrary.tsx, RoutineValidatorModal.tsx |
| `agents.page.ts` | `AgentsPage` | `goto()`, `getAgentList()`, `configureRunner()` | Agents.tsx, AgentRunners.tsx |
| `modals.page.ts` | `CreateRunModalPage`, `SettingsModalPage`, `ConfirmDialogPage`, `ApprovalModalPage`, `ClarificationModalPage` | `fillForm()`, `submit()`, `close()`, `isOpen()` | All modal components |

### Configuration Files

| File | Purpose |
|------|---------|
| `ui/playwright.bdd.config.ts` | Playwright config for BDD tests; `baseURL: http://localhost:5398`; uses `defineBddConfig()` from playwright-bdd |

### Package Changes

| File | Change |
|------|--------|
| `ui/package.json` | Add `playwright-bdd: ^8.0.0` to devDependencies; add `test:bdd` and `test:bdd:ui` scripts |
