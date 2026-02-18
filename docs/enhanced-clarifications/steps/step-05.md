# Step 05: Frontend – WebSocket Handler & History UI (10b + 10c frontend)

Wire the WebSocket clarification events into the React Query cache invalidation so the UI reacts instantly (not waiting for the 10s poll). Add `useClarificationHistory` query hook backed by the new history endpoint. Render completed clarification rounds as expandable `ClarificationHistoryCard` components in the activity feed so users have full context of past Q&A rounds.

## Intent Verification
**Original Intent**: `docs/enhanced-clarifications/intent.md` – "WebSocket push – `ClarificationRequested` events broadcast immediately so the UI reacts without waiting for the 10s poll cycle" and "Answer history in the activity timeline – completed clarification rounds shown as expandable cards in the activity feed"

**Functionality to Produce**:
- `useWebSocket` `processEvent` invalidates query caches on `clarification_requested` and `clarification_responded` events
- `useClarificationHistory` hook fetches all Q&A rounds from the history endpoint
- `ClarificationHistoryCard` renders collapsed/expanded view with Q&A, timestamp, and status badge
- Activity feed shows a `ClarificationHistoryCard` for each `clarification_responded` event

**Final Verification Criteria**:
- `npm run typecheck` passes with no TypeScript errors
- `npm run lint` passes on changed files
- `npm test` passes; unit tests for `ClarificationHistoryCard` and `useWebSocket` event handlers pass
- Clarification modal opens within ~1 second of WS push (not after 10s poll)

---

## Task 1: Add clarification event payload types to activity.ts

**Description**: Define TypeScript types for the incoming WS event payloads so `processEvent` is fully typed.

**Implementation Plan (Do These Steps)**

- [ ] Open `ui/src/types/activity.ts` and read it fully.
- [ ] Add the following interfaces:
```ts
export interface ClarificationRequestedPayload {
  event_type: 'clarification_requested';
  run_id: string;
  task_id: string;
  request_id: string;
  question_count: number;
}

export interface ClarificationRespondedPayload {
  event_type: 'clarification_responded';
  run_id: string;
  task_id: string;
  request_id: string;
}
```
- [ ] If there is a union type for all WS event payloads (e.g., `ActivityEvent`), add both new interfaces to the union.

**References**
- `docs/enhanced-clarifications/step-05-plan.md` – Task 1
- `docs/enhanced-clarifications/architecture.md` – "Modified Components: ui/src/hooks/useWebSocket.ts" (event shape)

**Constraints**
- [ ] Only `activity.ts` changes in this task.
- [ ] Do not modify existing type definitions.

**Functionality (Expected Outcomes)**
- [ ] `ClarificationRequestedPayload` and `ClarificationRespondedPayload` are exported
- [ ] TypeScript accepts the payload shapes defined in Step 3's WS broadcast

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `cd ui && npm run typecheck` passes with no errors

---

## Task 2: Extend useWebSocket processEvent with clarification handlers

**Description**: Add cache invalidation logic so `ClarificationModal` auto-opens on `clarification_requested` and the history refetches on `clarification_responded`.

**Implementation Plan (Do These Steps)**

- [ ] Open `ui/src/hooks/useWebSocket.ts` and read it fully.
- [ ] Find the `processEvent` function (or equivalent) that dispatches on `event_type`.
- [ ] Add the following branches (after the existing branches, before the default/fallthrough):
```ts
} else if (eventType === 'clarification_requested') {
  const payload = data as ClarificationRequestedPayload;
  qc.invalidateQueries({ queryKey: ['pending-actions', runId] });
  if (payload.task_id) {
    qc.invalidateQueries({ queryKey: ['pending-clarification', runId, payload.task_id] });
  }
} else if (eventType === 'clarification_responded') {
  const payload = data as ClarificationRespondedPayload;
  if (payload.task_id) {
    qc.invalidateQueries({ queryKey: ['clarification-history', runId, payload.task_id] });
  }
}
```
  Use the actual variable names for `qc` (QueryClient) and `runId` as they appear in the existing hook.

**Dependencies**
- [ ] Task 1 complete: `ClarificationRequestedPayload` and `ClarificationRespondedPayload` types are defined.
- [ ] Step 3 complete: backend broadcasts these events over WS.

**References**
- `docs/enhanced-clarifications/architecture.md` – "Modified Components: ui/src/hooks/useWebSocket.ts" with exact code snippet
- `docs/enhanced-clarifications/step-05-plan.md` – Task 2

**Constraints**
- [ ] Only add the two new `else if` branches; do not modify existing event handlers.
- [ ] Guard `task_id` access to avoid crashing on malformed payloads.

**Functionality (Expected Outcomes)**
- [ ] On `clarification_requested` event: `['pending-actions', runId]` and `['pending-clarification', runId, taskId]` are invalidated
- [ ] On `clarification_responded` event: `['clarification-history', runId, taskId]` is invalidated
- [ ] A payload without `task_id` does not throw (guard is in place)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Unit test: `processEvent` with `clarification_requested` payload calls `invalidateQueries` with both keys
- [ ] Unit test: `processEvent` with `clarification_responded` payload calls `invalidateQueries` with history key
- [ ] Unit test: `processEvent` with missing `task_id` does not throw
- [ ] `cd ui && npm run typecheck` passes

---

## Task 3: Add useClarificationHistory query hook

**Description**: Add a React Query hook that fetches all Q&A history from `GET /api/runs/{run_id}/tasks/{task_id}/clarifications`.

**Implementation Plan (Do These Steps)**

- [ ] Open `ui/src/hooks/useClarifications.ts` and read it fully.
- [ ] Add the following hook at the end of the file:
```ts
import { ClarificationHistoryResponse } from '../types/clarifications';

export function useClarificationHistory(
  runId: string | undefined,
  taskId: string | undefined,
) {
  return useQuery<ClarificationHistoryResponse>({
    queryKey: ['clarification-history', runId, taskId],
    queryFn: async () => {
      const res = await fetch(`/api/runs/${runId}/tasks/${taskId}/clarifications`);
      if (!res.ok) throw new Error(`Failed to fetch clarification history: ${res.status}`);
      return res.json() as Promise<ClarificationHistoryResponse>;
    },
    enabled: !!runId && !!taskId,
    staleTime: 30_000,
  });
}
```
  Adapt the fetch call to match the existing API client pattern used in other hooks in the file (e.g., using `apiClient`, axios, or a custom fetch wrapper).

**Dependencies**
- [ ] Step 2 complete: `GET .../clarifications` history endpoint exists.
- [ ] Task 1 complete: `ClarificationHistoryResponse` type is defined.

**References**
- `docs/enhanced-clarifications/architecture.md` – "Modified Components: ui/src/hooks/useClarifications.ts"
- `docs/enhanced-clarifications/step-05-plan.md` – Task 3, Functional Contract
- `docs/enhanced-clarifications/design-questions.md` – Q3 (history includes all rounds, including pending)

**Constraints**
- [ ] Only add `useClarificationHistory`; do not modify `usePendingClarification` or `useRespondToClarification`.
- [ ] Query must be disabled when `runId` or `taskId` is undefined (to avoid invalid requests).

**Functionality (Expected Outcomes)**
- [ ] Hook returns `ClarificationHistoryItem[]` from `data.items`
- [ ] Hook is disabled (no fetch) when `runId` or `taskId` is undefined
- [ ] Non-200 response surfaces as React Query `error` state

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `cd ui && npm run typecheck` passes
- [ ] `cd ui && npm run lint` passes on `useClarifications.ts`

---

## Task 4: Create ClarificationHistoryCard component

**Description**: Create the new `ClarificationHistoryCard` component that renders a single completed (or pending) clarification round in the activity feed.

**Implementation Plan (Do These Steps)**

- [ ] Create `ui/src/components/detail/ClarificationHistoryCard.tsx` with the following structure:
```tsx
import { useState } from 'react';
import { ClarificationHistoryItem } from '../../types/clarifications';

interface Props {
  item: ClarificationHistoryItem;
  roundNumber: number;
}

export function ClarificationHistoryCard({ item, roundNumber }: Props) {
  const [expanded, setExpanded] = useState(false);
  const { request, response } = item;
  const isSkipped = response?.skipped ?? false;
  const isPending = response === null;

  return (
    <div className="clarification-history-card">
      <button
        className="clarification-history-card__header"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span>Clarification {roundNumber}</span>
        {isPending && <span className="badge badge--pending">Pending</span>}
        {!isPending && isSkipped && <span className="badge badge--skipped">Skipped</span>}
        {!isPending && !isSkipped && <span className="badge badge--answered">Answered</span>}
        {request.created_at && (
          <time dateTime={request.created_at}>
            {new Date(request.created_at).toLocaleString()}
          </time>
        )}
      </button>

      {expanded && (
        <div className="clarification-history-card__body">
          {isPending ? (
            <p className="clarification-history-card__placeholder">Awaiting response…</p>
          ) : (
            <>
              {request.questions?.map((q) => {
                const answer = response?.answers?.find((a) => a.question_id === q.id);
                return (
                  <div key={q.id} className="clarification-history-card__qa">
                    <p className="question">{q.text}</p>
                    {answer?.skipped ? (
                      <p className="answer answer--skipped">
                        Skipped{answer.skip_reason ? `: ${answer.skip_reason}` : ''}
                      </p>
                    ) : (
                      <p className="answer">
                        {answer?.selected_options?.join(', ') ??
                          answer?.selected_option ??
                          answer?.other_text ??
                          '—'}
                      </p>
                    )}
                  </div>
                );
              })}
              {isSkipped && response?.skip_reason && (
                <p className="clarification-history-card__skip-reason">
                  Skip reason: {response.skip_reason}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
```
  Adapt CSS class names to match the existing component style convention in the project.

**References**
- `docs/enhanced-clarifications/architecture.md` – "New Components: ClarificationHistoryCard"
- `docs/enhanced-clarifications/step-05-plan.md` – Task 4, Functional Contract (Outputs)

**Constraints**
- [ ] This is a new file; do not modify any existing component.
- [ ] The component must render a non-crashing placeholder when `response === null`.
- [ ] Collapsed by default (`expanded: false`).

**Functionality (Expected Outcomes)**
- [ ] Collapsed: shows "Clarification N", timestamp, and status badge
- [ ] Expanded: shows per-question rows with question text and answer(s)
- [ ] Skipped state: badge reads "Skipped"; skip reason is shown
- [ ] Pending state: badge reads "Pending" or equivalent; body shows "Awaiting response…"
- [ ] `null` response does not crash the component

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `cd ui && npm test -- ClarificationHistoryCard` passes: collapsed render, expanded render, skipped state, pending/null-response state
- [ ] `cd ui && npm run typecheck` passes
- [ ] `cd ui && npm run lint` passes on `ClarificationHistoryCard.tsx`

---

## Task 5: Wire ClarificationHistoryCard into the activity feed

**Description**: Render `ClarificationHistoryCard` in the activity feed for each `clarification_responded` event.

**Implementation Plan (Do These Steps)**

- [ ] Open `ui/src/components/detail/RunDetail.tsx` (or the activity sub-component that renders event cards). Read the file to find where individual activity events are rendered.
- [ ] Import `useClarificationHistory` and `ClarificationHistoryCard`.
- [ ] Call `useClarificationHistory(runId, taskId)` at the top of the component (or activity sub-component) to get the history data.
- [ ] In the event-rendering section, add a branch for `clarification_responded`:
```tsx
} else if (event.event_type === 'clarification_responded') {
  const historyItems = clarificationHistory?.items ?? [];
  // Find the matching history item by request_id
  const matchingItem = historyItems.find(
    (item) => item.request.id === event.request_id,
  );
  if (matchingItem) {
    const roundNumber =
      historyItems.findIndex((item) => item.request.id === event.request_id) + 1;
    return (
      <ClarificationHistoryCard
        key={event.id ?? event.request_id}
        item={matchingItem}
        roundNumber={roundNumber}
      />
    );
  }
  // Fallback: event exists but history item not found
  return <div key={event.id}>Clarification response recorded</div>;
```
  Adapt to the exact event shape and rendering pattern used in the existing activity feed.
- [ ] If `useClarificationHistory` returns an error, render a fallback instead of the card:
```tsx
if (historyError) {
  return <div>Unable to load clarification history.</div>;
}
```

**References**
- `docs/enhanced-clarifications/architecture.md` – "Activity feed rendering (RunDetail or activity sub-component)"
- `docs/enhanced-clarifications/step-05-plan.md` – Task 5

**Constraints**
- [ ] Minimize changes to `RunDetail.tsx`; only add the new rendering branch and hook call.
- [ ] Do not change existing event rendering logic for other event types.

**Side Effects**
- [ ] A new query (`useClarificationHistory`) fires on every render of `RunDetail` for tasks with clarifications; this is expected and acceptable per performance considerations in `architecture.md`.

**Functionality (Expected Outcomes)**
- [ ] After a clarification response, `ClarificationHistoryCard` appears in the activity feed at the correct chronological position
- [ ] Card shows correct round number, Q&A content, and status badge
- [ ] If history endpoint fails, a fallback message is shown (no crash)
- [ ] Other activity events render exactly as before (no regression)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Manual end-to-end: complete a clarification round; confirm `ClarificationHistoryCard` appears in activity feed
- [ ] Click card header to expand; confirm Q&A content is visible
- [ ] Force-skip a clarification; confirm card shows "Skipped" badge and displays skip reason
- [ ] `cd ui && npm run typecheck` passes
- [ ] `cd ui && npm run lint` passes on `RunDetail.tsx`
