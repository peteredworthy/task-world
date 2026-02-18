# Feature: Wire AgentGuidancePanel to Lifecycle Hooks and Aggregate Guidance Endpoint

## Summary

Three backend endpoints exist for user-managed agent workflows but are not called by the
frontend: `agent-started`, `agent-cancelled`, and the aggregate `guidance` endpoint.
`AgentGuidancePanel` assembles guidance from multiple separate hooks and hardcoded values
instead of using the single `GET /api/runs/{id}/guidance` response.

## Current State

**Backend — complete:**
- `POST /api/runs/{id}/agent-started` — sets `agent_started_at` timestamp
- `POST /api/runs/{id}/agent-cancelled` — transitions run to FAILED
- `GET /api/runs/{id}/guidance` — returns `{ task_id, prompt, phase, mcp_url, expected_actions }`

**Frontend — missing:**
- No `agentStarted(runId)` or `agentCancelled(runId)` in `ui/src/api/client.ts`
- No `useAgentStarted` / `useAgentCancelled` mutation hooks
- No `getGuidance(runId)` or `useGuidance(runId)` in client / hooks
- `AgentGuidancePanel` builds its display from `useTaskPrompt()` + hardcoded MCP path;
  it does not call the aggregate endpoint
- Cancel button in `WaitingIndicator` calls a generic `onCancel` callback rather than
  `agentCancelled`

## Work Required

### 3a. Lifecycle hooks (low effort)

1. **`ui/src/api/client.ts`** — add:
   ```ts
   agentStarted(runId: string): Promise<RunResponse>
   agentCancelled(runId: string): Promise<RunResponse>
   ```

2. **`ui/src/hooks/useApi.ts`** — add `useAgentStarted` and `useAgentCancelled` mutations
   (invalidate `['run', runId]` on success).

3. **`ui/src/components/guidance/AgentGuidancePanel.tsx`** — add an "I've started my agent"
   button that calls `useAgentStarted`. Wire the existing cancel path to call
   `useAgentCancelled` (or pass it down to `WaitingIndicator`).

### 3b. Aggregate guidance endpoint (low-medium effort)

1. **`ui/src/api/client.ts`** — add:
   ```ts
   getGuidance(runId: string): Promise<GuidanceResponse>
   ```

2. **`ui/src/types/`** — add `GuidanceResponse` type matching the backend schema
   (`task_id`, `prompt`, `phase`, `mcp_url`, `expected_actions`).

3. **`ui/src/hooks/useApi.ts`** — add `useGuidance(runId)` query with the run's WebSocket
   invalidation trigger.

4. **`AgentGuidancePanel`** — replace the `useTaskPrompt()` call and hardcoded MCP values
   with the single `useGuidance` hook result.

## Severity

**Medium** — user-managed agent runs still work (the agent can use the MCP URL shown), but
`agent_started_at` is never set and cancellation from the panel doesn't call the backend
lifecycle endpoint.

## Related

- `docs/ui-gaps2/README.md §3` and `§4`
- `src/orchestrator/api/routers/runs.py:791` — `agent-started` endpoint
- `src/orchestrator/api/routers/runs.py:818` — `agent-cancelled` endpoint
- `src/orchestrator/api/routers/runs.py:677` — `guidance` endpoint
- `ui/src/components/guidance/AgentGuidancePanel.tsx`
- `ui/src/components/WaitingIndicator.tsx`
