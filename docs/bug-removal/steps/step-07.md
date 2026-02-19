# Step 7: Wire AgentGuidancePanel Lifecycle Hooks and Guidance Endpoint (UI-AGENT-GUIDANCE-PANEL)

This step connects the `AgentGuidancePanel` component to three existing but unwired backend
endpoints: `POST /api/runs/{id}/agent-started`, `POST /api/runs/{id}/agent-cancelled`, and
`GET /api/runs/{id}/guidance`. Currently the panel assembles guidance from multiple disconnected
hooks and hardcoded values; lifecycle events are never sent to the backend. After this step, the
panel uses the aggregate `guidance` endpoint as its single data source, and user interactions
(start/cancel) correctly update run state on the server.

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "`agentStarted`, `agentCancelled`, `getGuidance` wired in client and hooks; `AgentGuidancePanel` uses `useGuidance`; cancel button calls `agentCancelled`"
**Functionality to Produce**:
- `agentStarted(runId)`, `agentCancelled(runId)`, `getGuidance(runId)` in `ui/src/api/client.ts`
- `GuidanceResponse` type in `ui/src/types/`
- `useAgentStarted`, `useAgentCancelled` mutation hooks and `useGuidance` query hook in `ui/src/hooks/useApi.ts`
- `AgentGuidancePanel.tsx` uses `useGuidance` instead of `useTaskPrompt` and hardcoded MCP URL
- Cancel button calls `useAgentCancelled`; "I've started my agent" calls `useAgentStarted`

**Final Verification Criteria**:
- `npx tsc --noEmit` passes with no type errors
- `GuidanceResponse` exported from `ui/src/types/`
- All three client functions and all three hooks exported from their respective files
- Vitest test for `AgentGuidancePanel` passes

---

## Task 1: Add GuidanceResponse type and client functions
**Description**:
Add the `GuidanceResponse` TypeScript type and three client functions (`agentStarted`,
`agentCancelled`, `getGuidance`) to the frontend types and client files.

**Implementation Plan (Do These Steps)**
- [ ] Add `GuidanceResponse` to `ui/src/types/` (create `types/guidance.ts` or extend an existing file):
```typescript
export interface GuidanceResponse {
  task_id: string;
  prompt: string;
  phase: string;
  mcp_url: string;
  expected_actions: string[];
}
```
- [ ] Open `ui/src/api/client.ts` and add the three functions:
```typescript
export async function agentStarted(runId: string): Promise<void> {
  const response = await fetch(`/api/runs/${runId}/agent-started`, { method: 'POST' });
  if (!response.ok) throw new ApiError(response.status, await response.text());
}

export async function agentCancelled(runId: string): Promise<void> {
  const response = await fetch(`/api/runs/${runId}/agent-cancelled`, { method: 'POST' });
  if (!response.ok) throw new ApiError(response.status, await response.text());
}

export async function getGuidance(runId: string): Promise<GuidanceResponse> {
  const response = await fetch(`/api/runs/${runId}/guidance`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}
```

**References**
- `docs/bug-removal/step-07-plan.md` — Task 1 and Task 2 descriptions
- `docs/bugs/UI-AGENT-GUIDANCE-PANEL.md` — Work Required (3a and 3b)
- Backend endpoints: `src/orchestrator/api/routers/runs.py:791` (agent-started), `:818` (agent-cancelled), `:677` (guidance)

**Constraints**
- [ ] Only `ui/src/types/` (new file) and `ui/src/api/client.ts` should be changed in this task

**Functionality (Expected Outcomes)**
- [ ] `GuidanceResponse` type is exported from `ui/src/types/`
- [ ] `agentStarted`, `agentCancelled`, `getGuidance` exported from `ui/src/api/client.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0

---

## Task 2: Add useGuidance, useAgentStarted, useAgentCancelled hooks
**Description**:
Add the TanStack Query hooks for the three client functions: `useGuidance` (query with WebSocket
invalidation), `useAgentStarted` and `useAgentCancelled` (mutations with run query invalidation).

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/hooks/useApi.ts`
- [ ] Add the `useGuidance` query hook:
```typescript
export function useGuidance(runId: string) {
  return useQuery({
    queryKey: ['guidance', runId],
    queryFn: () => getGuidance(runId),
    // Invalidated by WebSocket run events; no polling needed
  });
}
```
- [ ] Add the `useAgentStarted` mutation hook:
```typescript
export function useAgentStarted(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => agentStarted(runId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['run', runId] }),
  });
}
```
- [ ] Add the `useAgentCancelled` mutation hook (same pattern as `useAgentStarted` but calls `agentCancelled`)

**References**
- `docs/bug-removal/step-07-plan.md` — Task 3 description
- `docs/bug-removal/architecture.md` — "Modified Components: useApi.ts"

**Constraints**
- [ ] Only `ui/src/hooks/useApi.ts` should be changed in this task

**Functionality (Expected Outcomes)**
- [ ] `useGuidance`, `useAgentStarted`, `useAgentCancelled` exported from `ui/src/hooks/useApi.ts`
- [ ] `useAgentStarted` and `useAgentCancelled` invalidate `['run', runId]` on success

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `grep -n "useGuidance\|useAgentStarted\|useAgentCancelled" ui/src/hooks/useApi.ts` shows all three exports

---

## Task 3: Update AgentGuidancePanel and WaitingIndicator, write Vitest test
**Description**:
Replace `useTaskPrompt()` and hardcoded MCP URL in `AgentGuidancePanel` with `useGuidance(runId)`.
Wire "I've started my agent" to `useAgentStarted` and cancel to `useAgentCancelled`. Update
`WaitingIndicator` cancel path. Write a Vitest test verifying the panel renders guidance data.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/guidance/AgentGuidancePanel.tsx`
- [ ] Replace `useTaskPrompt()` call with `useGuidance(runId)`:
```typescript
// Before:
const taskPrompt = useTaskPrompt(runId);
const mcpUrl = "http://hardcoded-url/mcp";

// After:
const { data: guidance, isLoading } = useGuidance(runId);
```
- [ ] Use `guidance.prompt` for the task prompt display
- [ ] Use `guidance.mcp_url` for the MCP URL display
- [ ] Add or update "I've started my agent" button to call `useAgentStarted(runId).mutate()`:
```typescript
const startAgent = useAgentStarted(runId);
// ...
<button onClick={() => startAgent.mutate()}>I've started my agent</button>
```
- [ ] Wire cancel to `useAgentCancelled(runId).mutate()`:
```typescript
const cancelAgent = useAgentCancelled(runId);
// ...
<button onClick={() => cancelAgent.mutate()}>Cancel</button>
```
- [ ] Handle `guidance` 404 case: show "No active task guidance available" placeholder
- [ ] Open `ui/src/components/WaitingIndicator.tsx` and update the `onCancel` prop path to call `useAgentCancelled`
- [ ] Write a Vitest test in `ui/src/components/guidance/__tests__/AgentGuidancePanel.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react';
// mock useGuidance to return mock data
const mockGuidance = {
  task_id: 'task-1',
  prompt: 'Complete the following tasks...',
  phase: 'building',
  mcp_url: 'http://localhost:8000/mcp/session-1',
  expected_actions: ['update_checklist', 'submit'],
};

test('renders prompt and mcp_url from guidance', () => {
  // mock useGuidance
  render(<AgentGuidancePanel runId="run-1" />);
  expect(screen.getByText(/Complete the following tasks/i)).toBeInTheDocument();
  expect(screen.getByText(/localhost:8000\/mcp/i)).toBeInTheDocument();
});
```
- [ ] Run `npx vitest run` and confirm all tests pass

**References**
- `docs/bug-removal/step-07-plan.md` — Task 4, Task 5, Task 6 descriptions
- `docs/bug-removal/architecture.md` — "Modified Components: AgentGuidancePanel.tsx, WaitingIndicator.tsx"
- Source files: `ui/src/components/guidance/AgentGuidancePanel.tsx`, `ui/src/components/WaitingIndicator.tsx`

**Constraints**
- [ ] Changes limited to `AgentGuidancePanel.tsx`, `WaitingIndicator.tsx`, and the new test file
- [ ] Remove `useTaskPrompt` usage and hardcoded MCP URL; do not leave dead code

**Functionality (Expected Outcomes)**
- [ ] `AgentGuidancePanel` displays prompt and `mcp_url` from the `guidance` endpoint (not hardcoded)
- [ ] "I've started my agent" button calls `agentStarted` API
- [ ] Cancel button calls `agentCancelled` API
- [ ] Vitest test for `AgentGuidancePanel` passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `npx vitest run` exits 0 (all tests pass including the new AgentGuidancePanel test)
