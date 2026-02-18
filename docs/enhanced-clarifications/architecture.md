# Architecture: Enhanced Clarification System

## Current State

The clarification system today is a single-question-type, poll-based flow:

```
LLM calls orchestrator_request_clarification MCP tool
  → POST /api/runs/{id}/tasks/{task_id}/clarifications  (creates ClarificationRequest, transitions to PENDING_USER_ACTION)
  → ClarificationRequested event persisted via PersistentEventEmitter
  → UI polls GET /api/runs/{id}/pending-actions every 10s
  → ClarificationModal opens with QuestionCard (radio + optional "Other" textarea)
  → User submits → POST .../clarifications/{id}/respond
  → ClarificationResponded event persisted
  → Task transitions back to BUILDING
  → Builder resumes with clarifications_path in prompt (no line reference)
```

**Key files:**
- `src/orchestrator/workflow/clarifications.py` – `ClarificationQuestion`, `ClarificationAnswer`, `ClarificationRequest`, `ClarificationResponse`, `format_clarification_artifact`
- `src/orchestrator/mcp/clarification_tools.py` – `CLARIFICATION_TOOL` dict with inputSchema
- `src/orchestrator/api/routers/clarifications.py` – CRUD router, `respond_to_clarification`, `get_pending_actions`
- `src/orchestrator/api/schemas/clarifications.py` – Pydantic API schemas (separate from domain models)
- `src/orchestrator/workflow/service.py` – `request_clarification`, `respond_to_clarification`, `get_pending_clarification`
- `src/orchestrator/workflow/prompts.py` – `generate_builder_prompt` (mentions clarifications_path only)
- `src/orchestrator/workflow/events.py` – `ClarificationRequested`, `ClarificationResponded` dataclasses
- `src/orchestrator/workflow/event_logger.py` – `PersistentEventEmitter` (persists + notifies WS listeners)
- `ui/src/types/clarifications.ts` – TypeScript domain types
- `ui/src/components/detail/ClarificationModal.tsx` – modal (all-at-once / one-at-a-time modes)
- `ui/src/components/detail/QuestionCard.tsx` – single question renderer (radio + "Other" textarea)
- `ui/src/hooks/useClarifications.ts` – `usePendingClarification`, `useRespondToClarification`
- `ui/src/hooks/useWebSocket.ts` – `processEvent` (does not handle `clarification_requested`)

**Limitations:**
- `ClarificationQuestion.options` is required (list); no support for free text, number, or multi-select question types
- Prompt includes only the artifact file path; builder must re-read the entire file to find new answers
- WebSocket does not signal clarification events; UI relies solely on 10s polling
- No history API; only the current pending clarification is exposed
- No skip mechanism; all questions must be answered

---

## Proposed Changes

### New Components

**`ClarificationHistoryCard` (new React component)**
- Location: `ui/src/components/detail/ClarificationHistoryCard.tsx`
- Renders one completed clarification round (expandable):
  - Header: "Clarification {n}" with timestamp and answered-by
  - Body: per-question rows showing question text, chosen answer(s), free text
  - Collapsed by default; click to expand
- Used by the activity feed when rendering `clarification_responded` events

**`GET /api/runs/{id}/tasks/{task_id}/clarifications` (new endpoint)**
- Returns `list[ClarificationHistoryItem]` where each item bundles a `ClarificationRequest` with its matching `ClarificationResponse` (or `null` if still pending)
- Schema: `ClarificationHistoryResponse` in `api/schemas/clarifications.py`
- Repository method: `get_clarification_history(run_id, task_id) -> list[tuple[ClarificationRequest, ClarificationResponse | None]]`

### Modified Components

**`workflow/clarifications.py`**
- `ClarificationQuestion`: add `question_type: Literal['single_select','multi_select','free_text','number'] = 'single_select'`; `allow_other: bool = True`; `required: bool = True`; `min: float | None = None`; `max: float | None = None`; `placeholder: str | None = None`. Validator: if `question_type` in `{'single_select','multi_select'}` then `options` must be non-empty; if `question_type` in `{'free_text','number'}` then `options` must be empty.
- `ClarificationAnswer`: add `selected_options: list[str] | None = None` (for `multi_select`); `skipped: bool = False`; `skip_reason: str | None = None`.
- `format_clarification_artifact`: signature changes to `→ tuple[str, int, int]` (text, start_line, end_line). Caller tracks the current line count in the file before appending to compute start_line.
- `build_artifact_header`: unchanged.

**`mcp/clarification_tools.py`**
- `CLARIFICATION_TOOL.inputSchema.items.properties`: add `question_type` (enum), `allow_other` (bool), `required` (bool), `min` (number), `max` (number), `placeholder` (string). Make `options` optional at the schema level (required only for select types). The router validates the semantic constraint.

**`api/schemas/clarifications.py`**
- `ClarificationQuestionSchema`: mirror new fields from the domain model.
- `ClarificationAnswerSchema`: add `selected_options: list[str] | None`, `skipped: bool = False`, `skip_reason: str | None`.
- `RespondToClarificationRequest`: add `skipped: bool = False`, `skip_reason: str | None`.
- New: `ClarificationHistoryItem`, `ClarificationHistoryResponse`.

**`api/routers/clarifications.py`**
- `respond_to_clarification`: when `request.skipped` is True, skip the "all required questions answered" guard; map `skipped` / `skip_reason` onto each `ClarificationAnswer`.
- Add `GET /{run_id}/tasks/{task_id}/clarifications` route returning history.

**`workflow/service.py`**
- `respond_to_clarification`: capture `(text, start_line, end_line)` from `format_clarification_artifact`; persist line range alongside the response (either in DB or passed through to the prompt generator); call `generate_builder_prompt` with new `clarification_line_range` parameter.

**`workflow/prompts.py`**
- `generate_builder_prompt`: accept optional `clarification_line_range: tuple[str, int, int] | None` (path, start, end). When present, append to the clarifications section: `"User answers have been written to {path} (lines {start}–{end}). Read that section for the answers."`. Accept optional `skipped_questions: list[str] | None` and `skip_reason: str | None`; when present, append: `"The user declined to answer: {list}. Reason: {reason or 'none given'}. Proceed with your best judgment."`.
- `BuilderPrompt` dataclass: add `clarification_line_range` and `skipped_questions` fields for introspection/testing.

**`workflow/events.py`**
- `ClarificationRequested`: add `questions: list[dict]` field for potential future full-payload broadcast (kept empty by default; populated only if Q4 design decision changes).

**`ui/src/types/clarifications.ts`**
- `ClarificationQuestion`: add `question_type`, `allow_other`, `required`, `min`, `max`, `placeholder`.
- `ClarificationAnswer`: add `selected_options`, `skipped`, `skip_reason`.
- `RespondToClarificationRequest`: add `skipped`, `skip_reason`.
- New: `ClarificationHistoryItem` type.

**`ui/src/components/detail/QuestionCard.tsx`**
- Branch on `question.question_type`:
  - `single_select`: existing radio + optional "Other" textarea (controlled by `allow_other`)
  - `multi_select`: checkboxes; `onOptionChange` replaced by `onOptionsChange(id, string[])` (or parent state handles list)
  - `free_text`: textarea with `placeholder`; no radio buttons
  - `number`: `<input type="number">` with `min`, `max`, `placeholder`; inline validation message
- Show `*` required indicator when `required === true`.
- Collapse "Other" option when `allow_other === false`.

**`ui/src/components/detail/ClarificationModal.tsx`**
- `AnswerState` per question: add `selectedOptions: string[]` for multi-select.
- Answer validation: check `required` flag; for `number`, check min/max; for `multi_select`, require at least one selected item if `required`.
- Add "Skip remaining" button (shown when: not all required questions answered AND at least one required question IS answered, OR all questions are optional). On click: show reason textarea; on confirm: submit with `skipped: true`, `skip_reason`, and whatever partial answers exist.

**`ui/src/hooks/useWebSocket.ts`**
- In `processEvent`: add:
  ```ts
  } else if (eventType === 'clarification_requested') {
    qc.invalidateQueries({ queryKey: ['pending-actions', runId] });
    if (data.task_id) {
      qc.invalidateQueries({ queryKey: ['pending-clarification', runId, data.task_id] });
    }
  } else if (eventType === 'clarification_responded') {
    if (data.task_id) {
      qc.invalidateQueries({ queryKey: ['clarification-history', runId, data.task_id] });
    }
  }
  ```

**`ui/src/hooks/useClarifications.ts`**
- Add `useClarificationHistory(runId, taskId)` query using the new history endpoint.

**Activity feed rendering (RunDetail or activity sub-component)**
- When `event.event_type === 'clarification_responded'`, render `<ClarificationHistoryCard>` with data fetched from the history query (or passed via event payload).

### Interactions

```
[LLM MCP Tool call]
  orchestrator_request_clarification({question_type: "multi_select", options: [...], required: true})
    → POST /api/runs/{id}/tasks/{task_id}/clarifications
    → service.request_clarification() → ClarificationRequest persisted
    → ClarificationRequested event emitted → PersistentEventEmitter
      → DB event store (for activity feed)
      → WS broadcaster → WebSocket clients receive {event_type: "clarification_requested", task_id, request_id}

[Frontend on WS message]
  processEvent → invalidate ['pending-actions', runId], ['pending-clarification', runId, taskId]
  → usePendingClarification refetches → ClarificationModal auto-opens

[User fills in multi_select or force-skips]
  → POST .../clarifications/{id}/respond {answers: [...], skipped: true, skip_reason: "..."}
  → service.respond_to_clarification()
    → format_clarification_artifact() → (text, start_line, end_line)
    → artifact file appended
    → generate_builder_prompt(clarification_line_range=(path, start, end), skipped_questions=[...])
    → ClarificationResponded event emitted
      → WS → invalidate ['clarification-history', runId, taskId]
  → task transitions back to BUILDING
  → Activity feed shows ClarificationHistoryCard (expandable)
```

---

## Technology Choices

| Area | Choice | Rationale |
|------|--------|-----------|
| Question type discriminator | `question_type: Literal[...]` field on Pydantic model | Simpler than full discriminated union; avoids migration of stored JSON |
| Multi-select answer storage | New `selected_options: list[str]` field on `ClarificationAnswer` | Additive change; backward-compatible with existing `selected_option` consumers |
| Line-range tracking | `format_clarification_artifact` returns `(str, int, int)` | Pure function contract; no I/O side effects; caller reads file line count before call |
| Skip encoding | `skipped: bool` flag + per-answer `skipped` field | Explicit, auditable; builder sees skip in both prompt and artifact file |
| WS payload for clarification events | Minimal (IDs + counts only) | Avoids serialization coupling; frontend fetches full data via existing query |
| History endpoint | New `GET .../clarifications` route | Clean REST; decoupled from activity event log; structured Q&A data ready for UI |
| Frontend number validation | Client-side only (HTML5 + JS) | Sufficient for MVP; server-side validation deferred (see design-questions.md Q5) |

---

## Testing Strategy

- **Unit Tests:**
  - `workflow/clarifications.py`: test `format_clarification_artifact` returns correct text and line numbers for all question types including skipped answers; test model validation rejects `options` for `free_text`/`number` and requires `options` for select types
  - `workflow/prompts.py`: test `generate_builder_prompt` includes line-range reference when `clarification_line_range` is provided; test skip signal text appears when `skipped_questions` is provided
  - `mcp/clarification_tools.py`: verify inputSchema JSON is valid against JSON Schema draft-07

- **Integration Tests** (pattern: `tests/integration/test_api_runs.py`):
  - Create a `multi_select` clarification request via `POST .../clarifications`; assert stored question has `question_type='multi_select'`
  - Respond with `selected_options=['A','B']`; assert artifact file contains both selections
  - Respond with `skipped=True`; assert task transitions to BUILDING and builder prompt contains skip message
  - `GET .../clarifications` returns history including completed and pending rounds
  - WS message received after `POST .../clarifications` contains `event_type='clarification_requested'`

- **E2E Tests / Manual Smoke:**
  - Start a run with a routine that triggers a clarification; confirm `ClarificationModal` opens without waiting for 10s poll
  - Answer using each question type; verify modal validation works correctly
  - Force-skip with a reason; verify builder receives skip message and continues
  - Review activity feed after clarification; confirm expandable history card appears

---

## Security Considerations

- No new auth surface: the clarification endpoints inherit the same `get_current_user` dependency used by the existing router. The `skip_reason` field is free text stored in the database; it must be treated as untrusted user input and not interpolated into shell commands or unsandboxed contexts.
- The builder prompt that includes `skip_reason` passes it directly to the LLM system prompt. Prompt injection is theoretically possible if a malicious user submits crafted text as `skip_reason`. This is consistent with existing `free_text` answer handling and is acceptable given the closed system (same user controls both UI and the LLM context).

## Performance Considerations

- `format_clarification_artifact` now requires knowing the current line count of the artifact file before appending to compute `start_line`. The caller (`workflow/service.py`) reads the file once to count lines. For typical clarification artifacts (tens of lines), this is negligible.
- The history endpoint (`GET .../clarifications`) joins `ClarificationRequest` with `ClarificationResponse` rows. With typical task lifetimes (2–10 clarification rounds), the query is trivially fast. No pagination is needed at this scale.
- The WebSocket invalidation on `clarification_requested` triggers one additional React Query refetch per connected client. This is identical to the existing polling behaviour; net effect is faster response with no extra server load beyond a single HTTP request.
