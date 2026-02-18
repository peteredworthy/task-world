# Step 05 Plan: Frontend – WebSocket Handler & History UI (10b + 10c frontend)

## Purpose

Wire the WebSocket clarification events into the React Query cache invalidation so the UI reacts instantly (not waiting for the 10s poll). Add `useClarificationHistory` query hook backed by the new history endpoint. Render completed clarification rounds as expandable `ClarificationHistoryCard` components in the activity feed so users have full context of past Q&A rounds.

## Prerequisites

- **Step 2 complete**: `GET .../clarifications` history endpoint must be available.
- **Step 3 complete**: WebSocket must broadcast `clarification_requested` and `clarification_responded` events with the agreed payload shape (`task_id`, `request_id`, `question_count`).
- **Step 4 complete**: `ClarificationHistoryCard` renders Q&A using the updated TypeScript types.

## Functional Contract

### Inputs

- WebSocket event `clarification_requested`:
  ```ts
  { event_type: 'clarification_requested', run_id: string, task_id: string, request_id: string, question_count: number }
  ```
- WebSocket event `clarification_responded`:
  ```ts
  { event_type: 'clarification_responded', run_id: string, task_id: string, request_id: string }
  ```
- `GET /api/runs/{run_id}/tasks/{task_id}/clarifications` response:
  ```ts
  ClarificationHistoryResponse { items: ClarificationHistoryItem[] }
  ```
  where `ClarificationHistoryItem = { request: ClarificationRequest; response: ClarificationResponse | null }`.
- Activity feed event: `{ event_type: 'clarification_responded', ... }` rendered in chronological order.

### Outputs

- On receiving `clarification_requested` WS event: React Query cache for `['pending-actions', runId]` and `['pending-clarification', runId, taskId]` is invalidated → `ClarificationModal` auto-opens within one query cycle.
- On receiving `clarification_responded` WS event: React Query cache for `['clarification-history', runId, taskId]` is invalidated → history list refetches and new card appears.
- `useClarificationHistory(runId, taskId)` returns `ClarificationHistoryItem[]`; stale-while-revalidate; enabled only when both IDs are defined.
- `ClarificationHistoryCard` renders:
  - Collapsed header: "Clarification {round_number}" + timestamp + status badge (Answered / Skipped)
  - Expanded body: per-question rows with question text, chosen answer(s) (highlight selected option), free text, skip reason if present
  - Collapsed by default; click header to toggle
- Activity feed shows `ClarificationHistoryCard` for each `clarification_responded` event in chronological position.

### Errors

- If the history endpoint returns a non-200, `useClarificationHistory` surfaces the error via React Query's `error` state; the activity feed shows a fallback message instead of the card.
- If `task_id` is absent from the WS event payload, `useWebSocket` skips the `pending-clarification` invalidation (guards against undefined query key).
- If `ClarificationHistoryCard` receives a `null` response (pending round), it renders a placeholder "Awaiting response" state rather than crashing.

## Tasks

1. Add `ClarificationRequestedPayload` and `ClarificationRespondedPayload` types to `ui/src/types/activity.ts`.
2. Update `ui/src/hooks/useWebSocket.ts` `processEvent`: add handlers for `clarification_requested` (invalidate `pending-actions` and `pending-clarification`) and `clarification_responded` (invalidate `clarification-history`).
3. Add `useClarificationHistory(runId, taskId)` query in `ui/src/hooks/useClarifications.ts` using `GET .../clarifications`; query key `['clarification-history', runId, taskId]`.
4. Create `ui/src/components/detail/ClarificationHistoryCard.tsx`: accepts a `ClarificationHistoryItem` prop; renders collapsed/expanded toggle; handles skipped and answered states; handles `null` response.
5. Wire `ClarificationHistoryCard` into the activity feed (locate in `RunDetail.tsx` or activity sub-component): when event type is `clarification_responded`, look up the matching history item from `useClarificationHistory` and render the card.
6. Manual smoke test: complete a clarification round end-to-end; confirm modal opens without waiting for poll, and history card appears in activity feed after submission.

## Verification

### Auto-Verify

- [ ] `cd ui && npm run typecheck` passes with no TypeScript errors.
- [ ] `cd ui && npm run lint` passes on changed files.
- [ ] `cd ui && npm test` passes; unit tests for `ClarificationHistoryCard` cover: collapsed render, expanded render, skipped state, null-response placeholder.
- [ ] Unit test for `useWebSocket` `processEvent` covers: `clarification_requested` invalidates correct query keys; `clarification_responded` invalidates history query key; missing `task_id` does not crash.

### Manual Verify

- [ ] Trigger a clarification request from a running task; confirm `ClarificationModal` opens within ~1 second (before the 10s poll would fire).
- [ ] Submit the clarification response; confirm the activity feed displays a `ClarificationHistoryCard` with the correct Q&A content.
- [ ] Click the history card header to expand; confirm question text and selected answer(s) are visible.
- [ ] Force-skip a clarification; confirm the history card shows "Skipped" status badge and displays the skip reason.
- [ ] Open two browser tabs on the same run; trigger a clarification in one tab; confirm both tabs open the modal promptly via WS push.

## Context & References

- `ui/src/hooks/useWebSocket.ts` – `processEvent` to extend with clarification event handlers
- `ui/src/hooks/useClarifications.ts` – add `useClarificationHistory` query
- `ui/src/types/activity.ts` – add clarification event payload types
- `ui/src/types/clarifications.ts` – `ClarificationHistoryItem` type (from Step 4)
- `ui/src/components/detail/ClarificationHistoryCard.tsx` – new component to create
- `RunDetail.tsx` (or activity sub-component) – wire `ClarificationHistoryCard` into feed
- `docs/enhanced-clarifications/architecture.md` – WS handler code snippet, history card spec, Interactions diagram
- `docs/enhanced-clarifications/design-questions.md` – Q3 (all rounds including pending), Q4 (minimal WS payload)
- Step 2 plan – prerequisite; history endpoint contract
- Step 3 plan – prerequisite; WS event payload shape
- Step 4 plan – prerequisite; updated TS types and `QuestionCard` rendering
