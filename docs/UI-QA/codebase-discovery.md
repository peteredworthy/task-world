# UI QA — Codebase Discovery

Reference for implementation agents. Dense lookup, no prose.

---

## Source File Signatures

### `ui/src/types/enums.ts`

```typescript
export type RunStatus = 'draft' | 'active' | 'paused' | 'stopping' | 'completed' | 'failed';
export type TaskStatus = 'pending' | 'building' | 'verifying' | 'recovering' | 'fan_out_running' | 'completed' | 'failed';
export type ChecklistStatus = 'open' | 'done' | 'not_applicable' | 'blocked' | 'escalated';
export type Priority = 'critical' | 'expected' | 'nice';
export type AgentRunnerType = string;
```

Note: no 'cancelled' in RunStatus — 'cancelled' is not a valid enum value (UI may show it as text but backend typing is the above set).

---

### `ui/src/types/runs.ts`

Key interfaces (all fields listed — factory functions must satisfy all):

```typescript
interface GradeSummaryItem { grade: string | null; priority: Priority; }

interface AttemptOutcome { attempt_num: number; outcome: string | null; }

interface TaskSummary {
  id: string; config_id: string; title: string; status: TaskStatus;
  current_attempt: number; max_attempts: number;
  grade_summary: GradeSummaryItem[]; attempts_summary: AttemptOutcome[];
  pending_action_type: 'clarification' | 'approval' | null;
  pending_clarification_count: number | null; parent_task_id: string | null;
}

interface StepSummary {
  id: string; config_id: string; title: string; completed: boolean;
  tasks: TaskSummary[]; has_approval_gate: boolean;
  approval_status: 'pending' | 'approved' | 'rejected' | null;
  skipped: boolean; skip_reason: string | null;
  condition: { when: string | null; repeat_for: string | null } | null;
}

interface ModelTokenUsage {
  model: string; cache_read_tokens: number; cache_creation_tokens: number;
  input_tokens: number; output_tokens: number;
  cost_per_m_cache_read: number; cost_per_m_cache_creation: number;
  cost_per_m_input: number; cost_per_m_output: number; total_cost_usd: number;
}

interface RunResponse {
  id: string; repo_name: string; status: RunStatus;
  pause_reason: string | null; last_error: string | null;
  routine_id: string | null; routine_sha: string | null;
  routine_source: string | null; routine_embedded: Record<string, unknown> | null;
  agent_type: AgentRunnerType | null; agent_type_display: string;
  agent_icon: string; agent_config: Record<string, unknown>;
  worktree_enabled: boolean; worktree_path: string | null;
  source_branch: string | null; merge_strategy: string | null;
  config: Record<string, unknown>; env_file_specs: EnvFileSpec[];
  env_source_dir: string | null; steps: StepSummary[];
  current_step_index: number; created_at: string; updated_at: string;
  started_at: string | null; completed_at: string | null;
  agent_started_at: string | null;
  total_tokens_read: number; total_tokens_write: number;
  total_tokens_cache: number; total_duration_ms: number;
  token_usage_by_model: ModelTokenUsage[];
  estimated_cost_usd: number | null; cost_disclaimer: string | null;
}

interface RunListResponse { runs: RunResponse[]; }

interface CreateRunRequest {
  routine_id?: string; repo_name: string; branch: string;
  routine_embedded?: Record<string, unknown>; config?: Record<string, unknown>;
  agent_type?: string; agent_config?: Record<string, unknown>;
}
```

---

### `ui/src/types/tasks.ts`

```typescript
interface ChecklistItemSchema {
  req_id: string; desc: string; priority: Priority; status: ChecklistStatus;
  note: string | null; grade: string | null; grade_reason: string | null;
}

interface AttemptSchema {
  id: string; attempt_num: number; started_at: string | null;
  completed_at: string | null; builder_prompt: string | null;
  verifier_prompt: string | null; verifier_comment: string | null;
  outcome: string | null; metrics: Record<string, unknown>;
  grade_snapshot: GradeSnapshotItem[]; auto_verify_results: Record<string, unknown>[] | null;
  agent_type: string | null; agent_model: string | null;
  agent_settings: Record<string, unknown>; error: string | null;
  has_output: boolean; has_action_log: boolean;
  start_commit: string | null; end_commit: string | null;
}

interface TaskDetailResponse {
  id: string; config_id: string; title: string; status: TaskStatus;
  checklist: ChecklistItemSchema[]; attempts: AttemptSchema[];
  current_attempt: number; max_attempts: number;
  parent_task_id: string | null; fan_out_index: number | null;
  fan_out_input: string | null; fan_out_output: string | null;
  fan_out_children: FanOutChildSummary[];
}

interface PromptResponse {
  system: string; user: string; phase: string; // "building" | "verifying"
  callback: CallbackInstructions | null;
}

interface TransitionResponse { success: boolean; new_status: string; error: string | null; }
```

---

### `ui/src/types/routines.ts`

```typescript
interface RoutineSummary {
  id: string; name: string; description: string | null;
  source: string; step_count: number; input_count: number; is_archived: boolean;
}

interface RoutineDetail {
  id: string; name: string; description: string | null; source: string;
  inputs: Record<string, unknown>[]; steps: StepSummarySchema[]; is_archived: boolean;
}

interface RoutineListResponse { routines: RoutineSummary[]; }
```

---

### `ui/src/types/activity.ts`

```typescript
interface ActivityEvent {
  id: number; event_type: string; timestamp: string;
  payload: Record<string, unknown>; task_title: string | null; step_title: string | null;
}

interface ActivityResponse { run_id: string; events: ActivityEvent[]; has_more: boolean; }
```

---

### `ui/src/types/agentRunners.ts`

```typescript
interface AgentRunnerOption {
  agent_type: AgentRunnerType; name: string; title: string;
  description: string; available: boolean; detail: string;
  install_hint: string; config_schema: AgentConfigField[];
  quota: AgentRunnerQuota | null;
}
```

---

### `ui/src/types/clarifications.ts`

```typescript
interface ClarificationQuestion {
  id: string; question: string; context: string; options: string[];
  question_type: 'single_select' | 'multi_select' | 'free_text' | 'number';
  allow_other: boolean; required: boolean;
  min?: number | null; max?: number | null; placeholder?: string | null;
}

interface PendingAction {
  task_id: string; step_id: string;
  action_type: 'clarification' | 'approval';
  clarification_request: ClarificationRequest | null;
  summary_artifact: string | null; approval_prompt: string | null;
  is_gate_approval: boolean;
}
```

---

### `ui/src/api/client.ts`

```typescript
// Errors
class ApiError extends Error { constructor(status: number, body: unknown); status: number; body: unknown; }
class RecoverTaskNotFoundError extends ApiError { constructor(body: unknown); }
class RecoverInvalidStateError extends ApiError { constructor(body: unknown); }

// Auth
export function setAuthToken(token: string | null): void
export function getAuthToken(): string | null

// Core fetch
export async function fetchApi<T>(path: string, init?: RequestInit): Promise<T>

// Validation types
export interface ValidationError { line: number; message: string; }
export interface ValidationResult { valid: boolean; errors: ValidationError[]; }

// api object — the main client exported as a named object
export const api = {
  getConfig(): Promise<GlobalConfig>
  listRuns(params?: { status?: string; repo_name?: string; limit?: number }): Promise<RunListResponse>
  getRun(runId: string): Promise<RunResponse>
  createRun(req: CreateRunRequest): Promise<RunResponse>
  startRun(runId: string): Promise<RunResponse>
  pauseRun(runId: string): Promise<RunResponse>
  resumeRun(runId: string, payload?: { agent_type?: string; agent_config?: Record<string, unknown>; resume_strategy?: string }): Promise<RunResponse>
  cancelRun(runId: string): Promise<RunResponse>
  deleteRun(runId: string): Promise<void>
  getTask(runId: string, taskId: string): Promise<TaskDetailResponse>
  getTaskPrompt(runId: string, taskId: string): Promise<PromptResponse>
  startTask(runId: string, taskId: string): Promise<TransitionResponse>
  submitTask(runId: string, taskId: string): Promise<TransitionResponse>
  updateChecklist(runId: string, taskId: string, reqId: string, data: UpdateChecklistRequest): Promise<ChecklistItemSchema>
  setGrade(runId: string, taskId: string, reqId: string, data: SetGradeRequest): Promise<ChecklistItemSchema>
  completeVerification(runId: string, taskId: string): Promise<TransitionResponse>
  getActivity(runId: string, params?: { after?: number; limit?: number; event_type?: string }): Promise<ActivityResponse>
  listRoutines(params?: { includeArchived?: boolean }): Promise<RoutineListResponse>
  getRoutine(routineId: string): Promise<RoutineDetail>
  archiveRoutine(routineId: string): Promise<ArchiveRoutineResponse>
  unarchiveRoutine(routineId: string): Promise<ArchiveRoutineResponse>
  validateRoutine(yamlContent: string): Promise<ValidationResult>  // note: standalone export also exists
  listAgentRunners(): Promise<AgentRunnerOption[]>
  getPendingActions(runId: string): Promise<PendingAction[]>
  getPendingClarification(runId: string, taskId: string): Promise<ClarificationRequest | null>
  getAttemptLogs(runId: string, taskId: string, attemptNum: number): Promise<AgentLogsResponse>
}
```

---

### `ui/src/hooks/useApi.ts`

All hooks return `UseQueryResult<T>` or `UseMutationResult<T>` from `@tanstack/react-query`.

```typescript
// Queries
export function useRuns(params?: { status?: string; repo_name?: string; limit?: number }): UseQueryResult<RunListResponse>
export function useRun(runId: string | undefined): UseQueryResult<RunResponse>
export function useRoutines(options?: { includeArchived?: boolean }): UseQueryResult<RoutineListResponse>
export function useRoutine(routineId: string | undefined | null): UseQueryResult<RoutineDetail>
export function useGlobalConfig(): UseQueryResult<GlobalConfig>
export function useAgentRunners(): UseQueryResult<AgentRunnerOption[]>
export function useTask(runId: string, taskId: string | undefined): UseQueryResult<TaskDetailResponse>
export function useActivity(runId: string | undefined, runStatus?: string): UseQueryResult<ActivityResponse>
export function useTaskPrompt(runId: string, taskId: string | undefined): UseQueryResult<PromptResponse>

// Mutations
export function useCreateRun(): UseMutationResult<RunResponse, Error, CreateRunRequest>
export function useStartRun(): UseMutationResult<RunResponse, Error, string>
export function usePauseRun(): UseMutationResult<RunResponse, Error, string>
export function useResumeRun(): UseMutationResult<RunResponse, Error, { runId: string; agentType?: string; agentConfig?: Record<string, unknown>; resumeStrategy?: string }>
export function useCancelRun(): UseMutationResult<RunResponse, Error, string>
export function useDeleteRun(): UseMutationResult<void, Error, string>
export function useArchiveRoutine(): UseMutationResult<ArchiveRoutineResponse, Error, string>
export function useUnarchiveRoutine(): UseMutationResult<ArchiveRoutineResponse, Error, string>
export function useValidateRoutine(): UseMutationResult<ValidationResult, Error, string>

// React Query cache keys (for manual invalidation in route handlers)
// ['runs', params]          — run list
// ['run', runId]            — single run
// ['routines', options]     — routine list
// ['routine', routineId]    — single routine
// ['globalConfig']          — global config
// ['agent-runners']         — agent runner list
// ['task', runId, taskId]   — task detail
// ['activity', runId]       — activity events
// ['task-prompt', runId, taskId] — task prompt
// ['pending-actions', runId]
// ['pending-clarification', runId, taskId]
```

---

### `ui/src/hooks/useWebSocket.ts`

```typescript
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'failed';

// Internal (not exported) — creates WS, sets up message handling + reconnect
function createWebSocket(
  runId: string,
  qc: ReturnType<typeof useQueryClient>,
  setStatus: (s: ConnectionStatus) => void,
  reconnectAttemptRef: React.RefObject<number>,
  reconnectTimerRef: React.RefObject<ReturnType<typeof setTimeout> | undefined>,
  scheduleReconnect: () => void,
): WebSocket

// Main hook
export function useRunWebSocket(runId: string | undefined): { status: ConnectionStatus; reconnect: () => void }

// WebSocket event types that trigger cache invalidation:
// 'run_status_changed'        → invalidates ['run', runId], ['runs']
// 'task_status_changed'       → invalidates ['run', runId], ['task', runId, taskId]
// 'checklist_gate_evaluated'  → invalidates ['run', runId]
// 'grades_evaluated'          → invalidates ['run', runId]
// 'clarification_requested'   → invalidates ['pending-actions', runId], ['pending-clarification', ...]
// 'clarification_responded'   → invalidates ['clarification-history', ...]
// batch messages: { type: 'batch', events: [...] } — each event processed individually
// WS URL: ws[s]://<host>/ws/runs/<runId>[?token=<token>]

const MAX_RECONNECT_ATTEMPTS = 10  // after this → status becomes 'failed'
// Backoff: Math.min(1000 * 2^attempt, 30000)
```

---

### `ui/src/hooks/useActivitySSE.ts`

```typescript
// Options
interface UseActivitySSEOptions {
  enabled?: boolean;
  onEvent?: (event: ActivityEvent) => void;
}

export function useActivitySSE(
  runId: string | undefined,
  options?: UseActivitySSEOptions
): { events: ActivityEvent[]; isConnected: boolean; connectionError: boolean }

// SSE URL: /api/runs/{runId}/activity/stream[?since_id=N]
// Reconnect backoff: Math.min(1000 * 2^attempt, 30000)
const MAX_BACKOFF_MS = 30_000
```

---

### `ui/playwright.config.ts` (existing, do not modify)

```typescript
export default defineConfig({
  testDir: './tests/e2e',    // existing visual regression only
  use: { baseURL: 'http://localhost:5399' },
  webServer: { command: 'npm run dev -- --port 5399', url: 'http://localhost:5399', reuseExistingServer: false }
});
```

---

### `ui/vitest.config.ts` (existing, do not modify)

```typescript
export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    setupFiles: ['./tests/setup.ts'],
  }
})
```

---

### `ui/tests/setup.ts` (existing)

```typescript
import '@testing-library/jest-dom/vitest';
```

---

## New Files to Create (signatures to implement)

### `ui/tests/fixtures/factories.ts`

```typescript
import type { RunResponse, TaskSummary, StepSummary, TaskDetailResponse,
  AttemptSchema, ChecklistItemSchema, ActivityEvent } from '../../src/types';
import type { RoutineSummary, RoutineDetail } from '../../src/types/routines';
import type { AgentRunnerOption } from '../../src/types/agentRunners';

export function buildRun(overrides?: Partial<RunResponse>): RunResponse
export function buildStep(overrides?: Partial<StepSummary>): StepSummary
export function buildTaskSummary(overrides?: Partial<TaskSummary>): TaskSummary
export function buildTaskDetail(overrides?: Partial<TaskDetailResponse>): TaskDetailResponse
export function buildAttempt(overrides?: Partial<AttemptSchema>): AttemptSchema
export function buildChecklist(overrides?: Partial<ChecklistItemSchema>): ChecklistItemSchema
export function buildRoutineSummary(overrides?: Partial<RoutineSummary>): RoutineSummary
export function buildRoutineDetail(overrides?: Partial<RoutineDetail>): RoutineDetail
export function buildAgentRunner(overrides?: Partial<AgentRunnerOption>): AgentRunnerOption
export function buildActivityEvent(overrides?: Partial<ActivityEvent>): ActivityEvent
```

Required default values for `buildRun` (must satisfy all RunResponse fields):
- `id: 'run-001'`, `repo_name: 'test/repo'`, `status: 'draft'`
- `pause_reason: null`, `last_error: null`, `routine_id: 'routine-001'`
- `routine_sha: null`, `routine_source: null`, `routine_embedded: null`
- `agent_type: null`, `agent_type_display: 'No Agent'`, `agent_icon: 'none'`
- `agent_config: {}`, `worktree_enabled: false`, `worktree_path: null`
- `source_branch: null`, `merge_strategy: null`, `config: {}`
- `env_file_specs: []`, `env_source_dir: null`, `steps: []`
- `current_step_index: 0`, `created_at: <ISO string>`, `updated_at: <ISO string>`
- `started_at: null`, `completed_at: null`, `agent_started_at: null`
- `total_tokens_read: 0`, `total_tokens_write: 0`, `total_tokens_cache: 0`
- `total_duration_ms: 0`, `token_usage_by_model: []`
- `estimated_cost_usd: null`, `cost_disclaimer: null`

Required default values for `buildStep` (must satisfy StepSummary):
- `id: 'step-001'`, `config_id: 'step-config-001'`, `title: 'Step 1'`
- `completed: false`, `tasks: []`, `has_approval_gate: false`
- `approval_status: null`, `skipped: false`, `skip_reason: null`, `condition: null`

Required default values for `buildTaskSummary` (must satisfy TaskSummary):
- `id: 'task-001'`, `config_id: 'task-config-001'`, `title: 'Task 1'`
- `status: 'pending'`, `current_attempt: 0`, `max_attempts: 3`
- `grade_summary: []`, `attempts_summary: []`
- `pending_action_type: null`, `pending_clarification_count: null`, `parent_task_id: null`

---

### `ui/tests/fixtures/api-handlers.ts`

```typescript
import type { Page } from '@playwright/test';
import type { RunResponse, RunListResponse } from '../../src/types';
import type { RoutineSummary } from '../../src/types/routines';
import type { AgentRunnerOption } from '../../src/types/agentRunners';

interface ApiState {
  runs: RunResponse[];
  routines: RoutineSummary[];
  agents: AgentRunnerOption[];
}

interface SetupOptions {
  runs?: RunResponse[];
  routines?: RoutineSummary[];
  agents?: AgentRunnerOption[];
  errorResponses?: {
    [endpoint: string]: { status: number; body: unknown };
  };
}

export function setupApiHandlers(page: Page, options?: SetupOptions): ApiState
// Returns mutable state object; test steps can push/mutate to simulate changes
// Intercepts via page.route():
//   GET  **/api/runs           → { runs: state.runs }
//   POST **/api/runs           → creates run, appends to state.runs
//   GET  **/api/runs/*         → find by id in state.runs
//   POST **/api/runs/*/start   → update status to 'active'
//   POST **/api/runs/*/pause   → update status to 'paused'
//   POST **/api/runs/*/resume  → update status to 'active'
//   POST **/api/runs/*/cancel  → update status to 'cancelled' (for test display)
//   GET  **/api/routines       → { routines: state.routines }
//   GET  **/api/routines/*     → find by id
//   GET  **/api/agent-runners  → state.agents
//   GET  **/api/runs/*/tasks/* → serve task detail
//   POST **/api/runs/*/tasks/*/submit  → update task status
//   GET  **/api/config         → { version: '1.0.0' }
//   GET  **/api/runs/*/activity → { run_id, events: [], has_more: false }
//   GET  **/api/runs/*/activity/stream → serve SSE (or empty 200 to prevent hanging)
```

---

### `ui/tests/fixtures/fake-ws.ts`

```typescript
// Injected via page.addInitScript() — replaces window.WebSocket before React mounts
// The script must be self-contained (no imports) when passed to addInitScript

export class FakeWebSocket {
  pushEvent(event: { type?: string; event_type?: string; data?: unknown; [key: string]: unknown }): void
  pushBatch(events: Array<{ type?: string; event_type?: string; [key: string]: unknown }>): void
  simulateDisconnect(): void   // triggers onclose → app goes to 'disconnected'
  simulateReconnect(): void    // triggers onopen → app goes to 'connected'
}

// Usage in tests:
// await page.addInitScript(() => { window.__fakeWs = new FakeWebSocket(); });
// then in step: await page.evaluate(() => window.__fakeWs.pushEvent({ event_type: 'run_status_changed', ... }))
```

FakeWebSocket injection pattern (must work in `addInitScript`):
- Replace `window.WebSocket` constructor
- Store instance on `window.__fakeWs` for test access
- Expose `pushEvent` that calls `onmessage` with `{ data: JSON.stringify(event) }`
- `pushBatch` wraps events as `{ type: 'batch', events: [...] }`
- `simulateDisconnect` calls `onclose`
- `simulateReconnect` calls `onopen`

---

### `ui/tests/fixtures/fake-sse.ts`

```typescript
// Intercepts /api/runs/*/activity/stream via page.route()
// Serves a controllable ReadableStream

export class FakeSSE {
  constructor(page: Page, runId: string)
  pushEvent(event: ActivityEvent): Promise<void>
  simulateDrop(): Promise<void>    // closes stream, triggers reconnect in useActivitySSE
  simulateReconnect(): Promise<void>
}
```

---

### `ui/playwright.bdd.config.ts` (new file)

```typescript
import { defineConfig } from '@playwright/test';
import { defineBddConfig } from 'playwright-bdd';

const testDir = defineBddConfig({
  features: 'tests/bdd/features/**/*.feature',
  steps: 'tests/bdd/steps/**/*.steps.ts',
});

export default defineConfig({
  testDir,
  workers: 4,
  use: { baseURL: 'http://localhost:5398' },
  webServer: {
    command: 'npm run dev -- --port 5398',
    url: 'http://localhost:5398',
    reuseExistingServer: false,
    timeout: 90_000,
  },
});
```

---

## Test Coverage Map

| Source File | Test File(s) | Key Fixtures / Patterns |
|---|---|---|
| `src/api/client.ts` | `tests/api/client.test.ts` | Direct imports of `ApiError`; no mocking needed (only tests error class) |
| `src/components/dashboard/RunCard.tsx` | `tests/components/RunCard.test.tsx` | `makeRun()`, `makeStep()`, `makeTask()` local helpers; `MemoryRouter` + `QueryClientProvider` wrappers |
| `src/components/dashboard/RunFilters.tsx` | `tests/components/RunFilters.test.tsx` | `vi.fn()` for callbacks; no provider needed |
| `src/components/dashboard/StepTimeline.tsx` | `tests/components/StepTimeline.test.tsx` | `makeStep()`, `makeTask()` helpers; `QueryClientProvider` wrapper |
| `src/components/detail/TaskDetailCard.tsx` | `tests/components/TaskDetailCard.test.tsx`, `tests/components/TaskDetailCard.agent.test.tsx` | `QueryClientProvider` with `retry: false`; `makeGrade()`, `makeAttemptOutcome()` helpers |
| `src/components/detail/ChecklistTable.tsx` | `tests/components/ChecklistTable.test.tsx` | `makeItem()` helper; no provider |
| `src/components/detail/ApprovalModal.tsx` | `tests/components/ApprovalModal.test.tsx` | `QueryClientProvider`; mocks `../../src/hooks/useApproval` via `import * as approvalHooks` |
| `src/components/detail/ClarificationModal.tsx` | `tests/components/ClarificationModal.test.tsx` | `QueryClientProvider`; mocks `../../src/hooks/useClarifications` via `import * as clarificationHooks` |
| `src/components/ConfirmDialog.tsx` | `tests/components/ConfirmDialog.test.tsx` | `vi.fn()` for confirm/cancel callbacks; no provider |
| `src/components/GradeBadge.tsx` | `tests/components/GradeBadge.test.tsx` | No provider; simple render test |
| `src/components/ConnectionIndicator.tsx` | `tests/components/ConnectionIndicator.test.tsx` | No provider; tests status prop |
| `src/hooks/useFocusTrap.ts` | `tests/hooks/useFocusTrap.test.tsx` | `TrapHarness` component with `useRef`; `fireEvent` for keyboard |
| `tests/e2e/visual-regression.spec.ts` | N/A (is the test) | `page.route()` Playwright mocks; `MOCK_RUN`, `MOCK_TASKS` inline fixtures |

**No existing tests** for:
- `src/hooks/useWebSocket.ts`
- `src/hooks/useActivitySSE.ts`
- `src/pages/Dashboard.tsx`
- `src/pages/History.tsx`
- `src/pages/RoutineLibrary.tsx`
- `src/pages/Agents.tsx`

These are covered by the new BDD tests.

---

## Import Reference Table

| Symbol | Import Statement |
|---|---|
| `RunResponse`, `RunListResponse`, `CreateRunRequest` | `import type { RunResponse, RunListResponse, CreateRunRequest } from '../../src/types'` |
| `TaskSummary`, `StepSummary` | `import type { TaskSummary, StepSummary } from '../../src/types'` |
| `TaskDetailResponse`, `AttemptSchema`, `ChecklistItemSchema` | `import type { TaskDetailResponse, AttemptSchema, ChecklistItemSchema } from '../../src/types'` |
| `RunStatus`, `TaskStatus`, `ChecklistStatus`, `Priority` | `import type { RunStatus, TaskStatus, ChecklistStatus, Priority } from '../../src/types'` |
| `RoutineSummary`, `RoutineDetail`, `RoutineListResponse` | `import type { RoutineSummary, RoutineDetail, RoutineListResponse } from '../../src/types'` |
| `ActivityEvent`, `ActivityResponse` | `import type { ActivityEvent, ActivityResponse } from '../../src/types'` |
| `AgentRunnerOption` | `import type { AgentRunnerOption } from '../../src/types'` |
| `PendingAction`, `ClarificationRequest` | `import type { PendingAction, ClarificationRequest } from '../../src/types'` |
| `PromptResponse`, `TransitionResponse` | `import type { PromptResponse, TransitionResponse } from '../../src/types'` |
| `ConnectionStatus` | `import type { ConnectionStatus } from '../../src/hooks/useWebSocket'` |
| `Page` (Playwright) | `import type { Page } from '@playwright/test'` |
| `test`, `expect` (Playwright) | `import { test, expect } from '@playwright/test'` |
| `defineBddConfig` | `import { defineBddConfig } from 'playwright-bdd'` |
| `Given`, `When`, `Then` (playwright-bdd) | `import { Given, When, Then } from 'playwright-bdd'` |
| `defineConfig` (Playwright) | `import { defineConfig } from '@playwright/test'` |
| All types barrel | `import type { ... } from '../../src/types'` (preferred over individual files) |

---

## Database Schema Snapshot

Not applicable — this task creates frontend test infrastructure only. No backend DB models are touched.

---

## Constants & Enums

### From `ui/src/hooks/useWebSocket.ts`
- `MAX_RECONNECT_ATTEMPTS = 10` — after 10 failed attempts, status becomes `'failed'`
- Reconnect backoff: `Math.min(1000 * Math.pow(2, attempt), 30000)` ms
- WS URL pattern: `<ws|wss>://<host>/ws/runs/<runId>[?token=<token>]`

### From `ui/src/hooks/useActivitySSE.ts`
- `MAX_BACKOFF_MS = 30_000`
- SSE URL pattern: `/api/runs/<runId>/activity/stream[?since_id=<id>]`
- Reconnect backoff: `Math.min(1000 * 2 ** attempt, 30_000)` ms

### From `ui/playwright.config.ts`
- Visual regression port: `5399`

### From architecture decisions
- BDD test port: `5398` (must not conflict with `5399`)
- BDD workers: `4`
- CI time budget: `< 3 minutes` for BDD suite
- `playwright-bdd` version: `^8.0.0`

### WebSocket event types (from `useWebSocket.ts` processEvent):
```
'run_status_changed'        — invalidates run + runs list
'task_status_changed'       — invalidates run + task
'checklist_gate_evaluated'  — invalidates run
'grades_evaluated'          — invalidates run
'clarification_requested'   — invalidates pending-actions + pending-clarification
'clarification_responded'   — invalidates clarification-history
```

### RunStatus values
```
'draft' | 'active' | 'paused' | 'stopping' | 'completed' | 'failed'
```
Note: `'cancelled'` is NOT in the TypeScript enum. Backend may return it; factories/mocks that need a cancelled state should use `as RunStatus` cast or extend the type locally in test files.

### TaskStatus values
```
'pending' | 'building' | 'verifying' | 'recovering' | 'fan_out_running' | 'completed' | 'failed'
```

### Package.json scripts to add
```json
"test:bdd": "playwright test --config playwright.bdd.config.ts",
"test:bdd:ui": "playwright test --config playwright.bdd.config.ts --ui"
```

### Existing package.json scripts (do not break)
```json
"dev": "vite",
"build": "tsc -b && vite build",
"test": "vitest run",
"test:e2e": "playwright test",
"typecheck": "tsc -b"
```

---

## Key Patterns from Existing Tests

### QueryClientProvider wrapper (required for all hooks-using components)
```typescript
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
render(<QueryClientProvider client={queryClient}><Component /></QueryClientProvider>);
```

### Hook mocking pattern (used by ApprovalModal and ClarificationModal tests)
```typescript
import * as hookModule from '../../src/hooks/useApproval';
vi.spyOn(hookModule, 'useApproveTask').mockReturnValue({ mutate: vi.fn(), isPending: false } as any);
```

### Existing visual regression test route mocking pattern
From `tests/e2e/visual-regression.spec.ts`:
```typescript
await page.route('**/api/runs', route => route.fulfill({ json: { runs: [MOCK_RUN] } }));
await page.route('**/api/runs/*', route => route.fulfill({ json: MOCK_RUN }));
```

### Local factory helpers (pattern used in existing component tests)
Existing tests define local `makeRun()`, `makeStep()`, `makeTask()` helpers inline. The new `factories.ts` centralises these — existing tests do NOT need to be updated (they have their own helpers).

### Playwright route interception (stateful pattern from architecture.md)
```typescript
const state = { runs: [...] };
page.route('**/api/runs', async route => {
  if (route.request().method() === 'GET') {
    await route.fulfill({ json: { runs: state.runs } });
  } else if (route.request().method() === 'POST') {
    const body = await route.request().postDataJSON();
    const newRun = buildRun(body);
    state.runs.push(newRun);
    await route.fulfill({ json: newRun });
  }
});
```
