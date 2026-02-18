# Plan: Enhanced Clarification System

## Overview

The enhancement spans five logically independent sub-features (10a–10e) that share a single data model at the core. The implementation order is chosen to be **contract-first**: we extend the data model first (10a backend), then the API surface, then plumb prompt changes, then WebSocket push, then frontend. Each milestone leaves the system runnable. Frontend work begins only after the backend contracts are stable.

Because each sub-feature can be worked on by a separate builder task, milestones are scoped to minimize dependencies between concurrent work streams. Sub-features 10b (WebSocket push) and 10d (line-range prompt) can proceed in parallel after milestone 1 stabilises the model.

## Milestones

### Milestone 1: Data Model & MCP Tool (10a backend)

Extend the core data model and MCP tool so the LLM can emit richer question types. No UI changes yet; existing `single_select` behavior is preserved.

- Extend `ClarificationQuestion` in `workflow/clarifications.py` with `question_type`, `allow_other`, `required`, `min`, `max`, `placeholder`; default `question_type='single_select'` and `required=True` for backward compatibility
- Extend `ClarificationAnswer` with `skipped: bool = False` and `skip_reason: str | None = None`
- Update `format_clarification_artifact` to return `(str, int, int)` – formatted text plus start and end line numbers of the appended section
- Update `api/schemas/clarifications.py` to reflect new model fields
- Update `CLARIFICATION_TOOL` inputSchema in `mcp/clarification_tools.py` to expose `question_type` and type-specific fields; add input validation
- Update `api/routers/clarifications.py` router to pass new fields through; update `RespondToClarificationRequest` to accept `skipped` / `skip_reason`
- Integration tests for all new fields (creation, response, skip path)

### Milestone 2: Prompt & History Endpoints (10d + history backend)

Wire the line-range data from Milestone 1 into the builder prompt and add the history endpoint.

- `workflow/service.py`: capture `(start_line, end_line)` returned by `format_clarification_artifact`; pass to `generate_builder_prompt`
- `workflow/prompts.py`: when `clarification_line_range` is provided, include `"User answers written to {path} (lines {start}–{end}). Read that section."` in the resume prompt; when skip signal is present, include `"User skipped: {list}. Reason: {reason}. Proceed with best judgment."`
- `api/routers/clarifications.py`: add `GET /api/runs/{run_id}/tasks/{task_id}/clarifications` endpoint returning all historical `ClarificationRequest` + matched `ClarificationResponse` pairs; add `ClarificationHistoryResponse` schema
- Integration tests: verify prompt text contains line reference; verify history endpoint returns completed rounds

### Milestone 3: WebSocket Push (10b)

Broadcast clarification events over the run's WebSocket channel so the frontend reacts instantly.

- Verify `ClarificationRequested` and `ClarificationResponded` events already flow through `PersistentEventEmitter` (they do per `workflow/service.py`)
- In `api/websocket.py` (or wherever events are broadcast), ensure the WebSocket broadcaster serializes `ClarificationRequested` events with full Q&A payload fields (`question_count`, `request_id`, `task_id`) – currently only `question_count` and `request_id` are on the dataclass; add question payload to `ClarificationRequested` if needed for frontend without a separate fetch
- Keep existing 10s polling in `usePendingClarification` as fallback
- Integration test: emit `ClarificationRequested` event; assert WebSocket message contains expected fields

### Milestone 4: Frontend – Question Types & Skip (10a + 10e frontend)

Update the frontend to render all four question types and support force-skip.

- `ui/src/types/clarifications.ts`: add `question_type`, `allow_other`, `required`, `min`, `max`, `placeholder` to `ClarificationQuestion`; add `skipped`, `skip_reason` to `ClarificationAnswer` and `RespondToClarificationRequest`
- `ui/src/components/detail/QuestionCard.tsx`: branch on `question_type` to render radio buttons (`single_select`), checkboxes (`multi_select`), textarea (`free_text`), number input with validation (`number`); show required indicator; respect `allow_other` flag
- `ui/src/components/detail/ClarificationModal.tsx`: update answer validation to use `required` flag and question type; add "Skip remaining" button (visible when at least one required question is answered or all questions are optional); include a short reason textarea; submit with `skipped: true` and partial answers
- Smoke-test by running existing clarification flow; confirm backward-compat with `single_select` questions

### Milestone 5: Frontend – WebSocket Handler & History UI (10b + 10c frontend)

Wire the WebSocket event and render clarification history in the activity feed.

- `ui/src/hooks/useWebSocket.ts`: in `processEvent`, add handler for `clarification_requested` event type – invalidate `['pending-actions', runId]` and `['pending-clarification', runId, taskId]`; same for `clarification_responded`
- `ui/src/types/activity.ts`: add clarification event payload types (`ClarificationRequestedPayload`, `ClarificationRespondedPayload`)
- Activity feed rendering (locate in `RunDetail.tsx` or its activity sub-component): when event type is `clarification_responded`, render an expandable card showing round number, Q&A pairs (highlight selected option, show free text), and timestamp; collapsed by default
- Hook up `useQuery` for `GET /api/runs/{id}/tasks/{task_id}/clarifications` to populate history; integrate into task detail or activity feed
- Manual test: complete a clarification round and confirm it appears in the activity feed

## Implementation Order

1. **Step 1: Data model & MCP tool (10a backend)**
   - Prerequisites: None
   - Deliverables: Extended `ClarificationQuestion`, `ClarificationAnswer`, updated `format_clarification_artifact`, updated schemas, updated `CLARIFICATION_TOOL`, integration tests

2. **Step 2: Prompt changes & history endpoint (10d + history backend)**
   - Prerequisites: Step 1 (needs line-range return from `format_clarification_artifact`)
   - Deliverables: Updated `generate_builder_prompt`, updated `respond_to_clarification` in service, `GET .../clarifications` endpoint, integration tests

3. **Step 3: WebSocket push (10b)**
   - Prerequisites: Step 1 (needs stable `ClarificationRequested` dataclass)
   - Deliverables: WebSocket broadcast of clarification events with full payload, integration test
   - _Can start concurrently with Step 2_

4. **Step 4: Frontend – question types & skip (10a + 10e frontend)**
   - Prerequisites: Step 1 (stable schema; API contracts must be known)
   - Deliverables: Updated TS types, `QuestionCard`, `ClarificationModal`

5. **Step 5: Frontend – WebSocket handler & history UI (10b + 10c frontend)**
   - Prerequisites: Steps 2, 3, 4
   - Deliverables: Updated `useWebSocket`, activity feed clarification cards, history query hook

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Backward compatibility for `question_type` | Default `'single_select'`, `required=True` | Existing MCP tool callers and stored data remain valid without migration |
| `format_clarification_artifact` return type | `tuple[str, int, int]` (text, start_line, end_line) | Cleanest way to return line range without side effects; callers can ignore if not needed |
| Skip handling | Accept partial answers when `skipped=True`; do not require all `required` questions | Matches intent: user signals "proceed with incomplete info" |
| WebSocket payload for `ClarificationRequested` | Include `question_count` only (current); full question data fetched via existing API | Avoids bloating WS messages; frontend already has a query for the pending clarification |
| Activity feed history source | `GET /api/runs/{id}/tasks/{task_id}/clarifications` (new endpoint) | Decouples history from the event log; provides structured Q&A data the feed can render directly |
| `multi_select` answer encoding | `selected_options: list[str]` field on `ClarificationAnswer` | Adds one new field rather than repurposing `selected_option`; avoids comma-encoding hacks |

## References

- `src/orchestrator/workflow/clarifications.py` – current model
- `src/orchestrator/mcp/clarification_tools.py` – current MCP tool
- `src/orchestrator/api/routers/clarifications.py` – current router
- `src/orchestrator/api/schemas/clarifications.py` – current schemas
- `src/orchestrator/workflow/service.py` – `request_clarification`, `respond_to_clarification`
- `src/orchestrator/workflow/prompts.py` – `generate_builder_prompt`
- `src/orchestrator/workflow/events.py` – `ClarificationRequested`, `ClarificationResponded` dataclasses
- `src/orchestrator/workflow/event_logger.py` – `PersistentEventEmitter`
- `ui/src/types/clarifications.ts` – TypeScript types
- `ui/src/components/detail/ClarificationModal.tsx` – current modal
- `ui/src/components/detail/QuestionCard.tsx` – current question renderer
- `ui/src/hooks/useClarifications.ts` – query/mutation hooks
- `ui/src/hooks/useWebSocket.ts` – WebSocket event handler
- `tests/integration/test_api_runs.py` – integration test patterns
