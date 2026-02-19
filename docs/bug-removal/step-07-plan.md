# Step 7 Plan: Wire AgentGuidancePanel Lifecycle Hooks and Guidance Endpoint (UI-AGENT-GUIDANCE-PANEL)

## Purpose

Connect the `AgentGuidancePanel` component to three existing but unwired backend endpoints: `POST /api/runs/{id}/agent-started`, `POST /api/runs/{id}/agent-cancelled`, and `GET /api/runs/{id}/guidance`. Currently, the panel assembles guidance from multiple disconnected hooks and hardcoded values; lifecycle events (`agent_started_at` timestamp, cancellation) are never sent to the backend. After this step, the panel will use the aggregate `guidance` endpoint as its single data source, and user interactions (start/cancel) will correctly update run state on the server.

## Prerequisites

- None (independent of all other steps)

## Functional Contract

### Inputs

- `run_id` (string) from the `RunDetail`/`WaitingIndicator` context
- `GET /api/runs/{id}/guidance` response (`GuidanceResponse`): `{ task_id, prompt, phase, mcp_url, expected_actions }`
- User clicking "I've started my agent" button — triggers `POST /api/runs/{id}/agent-started`
- User clicking "Cancel" button — triggers `POST /api/runs/{id}/agent-cancelled`

### Outputs

- `agentStarted(runId)` and `agentCancelled(runId)` functions added to `ui/src/api/client.ts`
- `getGuidance(runId)` function added to `ui/src/api/client.ts`
- `GuidanceResponse` type added to `ui/src/types/`
- `useAgentStarted()` and `useAgentCancelled()` mutation hooks added to `ui/src/hooks/useApi.ts`; both invalidate `['run', runId]` on success
- `useGuidance(runId)` query hook added to `ui/src/hooks/useApi.ts`; invalidated by WebSocket run events
- `AgentGuidancePanel.tsx` updated:
  - Replaces `useTaskPrompt()` and hardcoded MCP URL with `useGuidance(runId)` data
  - "I've started my agent" button calls `useAgentStarted`
  - Cancel path calls `useAgentCancelled`
- `WaitingIndicator.tsx` updated to pass `onCancel` that calls `useAgentCancelled`

### Errors

- `guidance` API 404 — panel shows "No active task guidance available" placeholder
- `agent-started` or `agent-cancelled` API errors — show toast with error message; do not crash panel
- TypeScript compile errors must be zero

## Tasks

1. Add `GuidanceResponse` type to `ui/src/types/` matching backend schema fields
2. Add `agentStarted(runId)`, `agentCancelled(runId)`, `getGuidance(runId)` to `ui/src/api/client.ts`
3. Add `useAgentStarted`, `useAgentCancelled` mutation hooks and `useGuidance` query hook to `ui/src/hooks/useApi.ts`
4. Update `ui/src/components/guidance/AgentGuidancePanel.tsx`: replace `useTaskPrompt()` and hardcoded MCP with `useGuidance`; add "I've started my agent" button wired to `useAgentStarted`; wire cancel to `useAgentCancelled`
5. Update `ui/src/components/WaitingIndicator.tsx` cancel path to call `useAgentCancelled`
6. Write Vitest test: render `AgentGuidancePanel` with a mock `useGuidance` response; confirm prompt, `mcp_url`, and `expected_actions` are displayed

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `GuidanceResponse` type is exported from `ui/src/types/`
- [ ] `agentStarted`, `agentCancelled`, `getGuidance` are exported from `ui/src/api/client.ts`
- [ ] `useAgentStarted`, `useAgentCancelled`, `useGuidance` are exported from `ui/src/hooks/useApi.ts`
- [ ] Vitest test for `AgentGuidancePanel` passes

### Manual Verify

- [ ] `AgentGuidancePanel` displays the task prompt and MCP URL from the `guidance` endpoint (not hardcoded values)
- [ ] Clicking "I've started my agent" calls `POST /api/runs/{id}/agent-started` and updates `agent_started_at` in the run
- [ ] Clicking "Cancel" calls `POST /api/runs/{id}/agent-cancelled` and transitions the run to FAILED in the UI

## Context & References

- Bug report: `docs/bugs/UI-AGENT-GUIDANCE-PANEL.md` — Current State, Work Required (3a and 3b)
- Architecture: `docs/bug-removal/architecture.md` — "Modified Components: AgentGuidancePanel.tsx, WaitingIndicator.tsx"
- Backend endpoints: `src/orchestrator/api/routers/runs.py:791` (agent-started), `:818` (agent-cancelled), `:677` (guidance)
- Source files: `ui/src/components/guidance/AgentGuidancePanel.tsx`, `ui/src/components/WaitingIndicator.tsx`
