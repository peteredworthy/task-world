# Step 03 Plan: WebSocket Push (10b)

## Purpose

Ensure that when a clarification is requested or responded to, a WebSocket event is broadcast to all connected clients immediately. This eliminates the 10-second polling delay and allows the frontend to react instantly. The existing 10s polling in `usePendingClarification` is preserved as a fallback.

## Prerequisites

- **Step 1 complete**: `ClarificationRequested` and `ClarificationResponded` dataclasses must be stable. The `ClarificationRequested` event may need a `questions` field added (empty by default per Q4 decision) so the schema is forward-compatible.
- Can proceed **concurrently with Step 2** once Step 1 is merged.

## Functional Contract

### Inputs

- Internal: `PersistentEventEmitter` emits `ClarificationRequested` and `ClarificationResponded` events as part of the existing `request_clarification` and `respond_to_clarification` service calls.
- `ClarificationRequested` WebSocket payload (broadcast by the WS broadcaster):
  ```json
  {
    "event_type": "clarification_requested",
    "run_id": "<run_id>",
    "task_id": "<task_id>",
    "request_id": "<clarification_request_id>",
    "question_count": <int>
  }
  ```
- `ClarificationResponded` WebSocket payload:
  ```json
  {
    "event_type": "clarification_responded",
    "run_id": "<run_id>",
    "task_id": "<task_id>",
    "request_id": "<clarification_request_id>"
  }
  ```

### Outputs

- All WebSocket clients subscribed to the run's channel receive the appropriate event message within the same request cycle as the originating HTTP call.
- The `ClarificationRequested` broadcast includes at minimum `task_id`, `request_id`, and `question_count`.
- The `ClarificationResponded` broadcast includes at minimum `task_id` and `request_id`.
- No full question/answer payload is included in the WS message (per Q4 decision: minimal payload; frontend fetches full data via existing REST query).

### Errors

- If the WS broadcaster encounters a disconnected client, it silently skips that client (existing behavior).
- If `ClarificationRequested` or `ClarificationResponded` events are missing required fields, the broadcaster raises a `KeyError` / `AttributeError` that surfaces as a 500 in the originating request (fail-fast, not silent).
- Polling fallback (`usePendingClarification`) continues to function if WS message is missed.

## Tasks

1. Audit `workflow/events.py`: confirm `ClarificationRequested` includes `task_id`, `request_id`, `question_count`; add `questions: list[dict] = field(default_factory=list)` for future forward-compatibility (empty by default per Q4).
2. Audit `api/websocket.py` (or equivalent broadcaster): confirm the WS broadcaster serializes `ClarificationRequested` events and emits them to the run's channel; if not, add the serialization branch.
3. Confirm `ClarificationResponded` is also broadcast; add if missing.
4. Write integration test: POST a clarification request; assert WebSocket message received on the run's channel contains `event_type='clarification_requested'`, `task_id`, `request_id`, `question_count`.
5. Write integration test: POST a clarification response; assert WebSocket message contains `event_type='clarification_responded'`, `task_id`, `request_id`.

## Verification

### Auto-Verify

- [ ] Integration test for `clarification_requested` WS message passes.
- [ ] Integration test for `clarification_responded` WS message passes.
- [ ] `mypy src/orchestrator/workflow/events.py src/orchestrator/api/websocket.py` reports no errors.
- [ ] `ruff check` reports no errors on changed files.
- [ ] Existing WS broadcast tests (for other event types) continue to pass.

### Manual Verify

- [ ] Open browser dev tools WebSocket inspector; trigger a clarification request; confirm `clarification_requested` message appears in WS frame log within 1 second (not waiting for 10s poll).
- [ ] Submit a clarification response; confirm `clarification_responded` message appears in WS frame log.
- [ ] Disconnect and reconnect WS client; confirm no errors in server logs related to disconnected client broadcast.

## Context & References

- `src/orchestrator/workflow/events.py` – `ClarificationRequested`, `ClarificationResponded` dataclasses
- `src/orchestrator/workflow/event_logger.py` – `PersistentEventEmitter` (persists + notifies WS listeners)
- `src/orchestrator/api/websocket.py` – WS broadcaster (verify broadcast path for clarification events)
- `docs/enhanced-clarifications/architecture.md` – Interactions diagram, WS payload spec
- `docs/enhanced-clarifications/design-questions.md` – Q4 (WebSocket payload size: minimal IDs only)
- Step 1 plan – prerequisite; stable `ClarificationRequested` dataclass
